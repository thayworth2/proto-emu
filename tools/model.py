#!/usr/bin/env python3
"""Cycle-accurate reference model of one proto-emu core, its program memory and TX FIFO.

`Core.step()` is one rising clock edge: it takes the same inputs the RTL sees that
cycle and moves the state to what the RTL registers should hold afterwards. The cocotb
harness (test/harness.py) runs this alongside the RTL and compares state every cycle.

Unknown values are None, mirroring unreset flops that simulate as X. A None may flow
through data (OUT into X, for example) but a *decision* on one -- a JMP condition, an
uninitialized instruction fetch -- raises UseBeforeInit, because that is a real bug in
silicon, not simulation noise.

Instructions the ISA defines but core.v does not implement yet raise NotInRTL rather
than being modelled, so a test can't silently pass on behaviour nobody has built.

    python3 tools/model.py prog.asm --push 0xA5000000 --cycles 20
"""

import argparse
import sys
from collections import deque
from dataclasses import dataclass

import isa


class ModelError(Exception):
    pass


class UseBeforeInit(ModelError):
    pass


class NotInRTL(ModelError):
    pass


@dataclass
class Config:
    """Per-core config registers (hardcoded in project.v until cfgregs.v exists)."""
    enable: bool = True
    start_addr: int = 0
    wrap_bottom: int = 0
    wrap_top: int = isa.PROG_DEPTH - 1
    side_set_count: int = 0
    fifo_depth: int = 4


# State compared against the RTL every cycle. Keys match test/harness.py.
STATE_KEYS = ("pc", "delay_cnt", "x", "y", "osr", "pins_out", "pins_oe",
              "side_set", "tx_empty", "tx_full")


class Core:
    def __init__(self, image, config=None):
        if len(image) != isa.PROG_DEPTH:
            raise ValueError(f"memory image must have {isa.PROG_DEPTH} words")
        self.mem = list(image)
        self.cfg = config or Config()
        self.cycle = 0
        self.in_reset_once = False
        # Everything starts unknown, as in simulation before rst_n.
        self.pc = self.delay_cnt = self.pc_next_r = None
        self.x = self.y = self.osr = None
        self.pins_val = self.pins_dir = None
        self.fifo = None

    # ---- observable state ------------------------------------------------------------

    def _instr(self):
        return None if self.pc is None else self.mem[self.pc]

    def snapshot(self):
        instr = self._instr()
        if self.cfg.side_set_count == 0:
            side = 0  # core.v's default case drives 0 regardless of instr
        elif instr is None:
            side = None
        else:
            side = isa.split_delayss(isa.DELAYSS.get(instr), self.cfg.side_set_count)[0]
        return {
            "pc": self.pc,
            "delay_cnt": self.delay_cnt,
            "x": self.x,
            "y": self.y,
            "osr": self.osr,
            "pins_out": self.pins_val,
            "pins_oe": self.pins_dir,
            "side_set": side,
            "tx_empty": None if self.fifo is None else len(self.fifo) == 0,
            "tx_full": None if self.fifo is None else len(self.fifo) == self.cfg.fifo_depth,
        }

    def describe(self):
        return f"pc={self.pc} `{isa.disassemble(self._instr(), self.cfg.side_set_count)}`"

    # ---- one clock edge --------------------------------------------------------------

    def step(self, rst_n=True, tx_wr_en=False, tx_wr_data=0):
        self.cycle += 1

        if not rst_n:
            # Reset set only: PC, delay, OE, FIFO pointers. X/Y/OSR/pin values hold.
            self.pc = 0  # core.v resets to 0; start_addr only applies while disabled
            self.delay_cnt = 0
            self.pc_next_r = 0
            self.pins_dir = 0
            self.fifo = deque()
            self.in_reset_once = True
            return
        if not self.in_reset_once:
            raise UseBeforeInit("clocked with rst_n high before any reset")

        tx_empty = len(self.fifo) == 0
        tx_full = len(self.fifo) == self.cfg.fifo_depth

        if not self.cfg.enable:
            self.pc = self.cfg.start_addr
            self.delay_cnt = 0
        elif self.delay_cnt != 0:
            if self.delay_cnt == 1:
                self.pc = self.pc_next_r
            self.delay_cnt -= 1
        else:
            self._execute(tx_empty)

        # FIFO write sees the pre-edge full flag, same as the RTL.
        if tx_wr_en and not tx_full:
            self.fifo.append(tx_wr_data & isa.REG_MASK)

    def _execute(self, tx_empty):
        instr = self._instr()
        if instr is None:
            raise UseBeforeInit(f"fetched uninitialized program memory at pc={self.pc}")

        op = isa.OPCODE.get(instr)
        _, delay = isa.split_delayss(isa.DELAYSS.get(instr), self.cfg.side_set_count)
        cfg = self.cfg
        seq_next = cfg.wrap_bottom if self.pc == cfg.wrap_top else (self.pc + 1) % isa.PROG_DEPTH
        next_pc = seq_next

        if op == isa.OP["JMP"]:
            next_pc = self._jmp(instr, seq_next)

        elif op == isa.OP["SET"]:
            dest, imm = isa.SET_DEST.get(instr), isa.SET_IMM.get(instr)
            if dest == isa.SET_DESTS["PINS"]:
                self.pins_val = imm
            elif dest == isa.SET_DESTS["PINDIRS"]:
                self.pins_dir = imm
            elif dest == isa.SET_DESTS["X"]:
                self.x = imm
            elif dest == isa.SET_DESTS["Y"]:
                self.y = imm
            else:
                raise NotInRTL(f"SET destination {dest:03b}")

        elif op == isa.OP["OUT"]:
            self._out(instr)

        elif op == isa.OP["PUSHPULL"]:
            if isa.PP_DIR.get(instr) != isa.PP_DIR_PULL:
                raise NotInRTL("PUSH")
            if isa.PP_IFFLAG.get(instr):
                raise NotInRTL("PULL ifempty")
            if tx_empty:
                if isa.PP_BLOCK.get(instr):
                    return  # stall: nothing changes, not even the delay counter
                # non-blocking PULL on an empty FIFO is a no-op (core.v)
            else:
                self.osr = self.fifo.popleft()

        else:
            raise NotInRTL(isa.OP_NAME[op])

        if delay:
            self.delay_cnt = delay
            self.pc_next_r = next_pc
        else:
            self.pc = next_pc

    def _jmp(self, instr, seq_next):
        cond = isa.JMP_COND.get(instr)
        c = isa.JMP_CONDS

        def need(value, name):
            if value is None:
                raise UseBeforeInit(f"JMP condition reads uninitialized {name} at pc={self.pc}")
            return value

        if cond == c["ALWAYS"]:
            take = True
        elif cond == c["X_EQ_Z"]:
            take = need(self.x, "X") == 0
        elif cond == c["X_NE_Z"]:
            take = need(self.x, "X") != 0
            self.x = (self.x - 1) & isa.REG_MASK  # post-decrement, taken or not
        elif cond == c["Y_EQ_Z"]:
            take = need(self.y, "Y") == 0
        elif cond == c["Y_NE_Z"]:
            take = need(self.y, "Y") != 0
            self.y = (self.y - 1) & isa.REG_MASK
        elif cond == c["X_NE_Y"]:
            take = need(self.x, "X") != need(self.y, "Y")
        else:
            raise NotInRTL(f"JMP condition {cond}")
        return isa.JMP_TARGET.get(instr) if take else seq_next

    def _out(self, instr):
        dest = isa.OUTIN_SEL.get(instr)
        n = isa.eff_count(isa.OUTIN_CNT.get(instr))
        if self.osr is None:
            value = None
        else:
            value = self.osr >> (isa.REG_WIDTH - n)  # MSB-first
            self.osr = (self.osr << n) & isa.REG_MASK

        d = isa.OUT_DESTS
        if dest == d["PINS"]:
            self.pins_val = None if value is None else value & 0xFF
        elif dest == d["PINDIRS"]:
            self.pins_dir = None if value is None else value & 0xFF
        elif dest == d["X"]:
            self.x = value
        elif dest == d["Y"]:
            self.y = value
        elif dest == d["NULL"]:
            pass
        else:
            raise NotInRTL(f"OUT destination {dest:03b}")


def main(argv=None):
    import asm

    ap = argparse.ArgumentParser(description="Run a program on the reference model.")
    ap.add_argument("source", help="assembly file")
    ap.add_argument("--cycles", type=int, default=32)
    ap.add_argument("--push", action="append", default=[], metavar="WORD",
                    help="word to write into the TX FIFO (repeatable, one per cycle)")
    ap.add_argument("--reset-cycles", type=int, default=2)
    args = ap.parse_args(argv)

    prog = asm.assemble_file(args.source)
    core = Core(prog.image(), Config(side_set_count=prog.side_set_count))
    for _ in range(args.reset_cycles):
        core.step(rst_n=False)
    pending = deque(int(w, 0) for w in args.push)

    def fmt(v, width):
        return "x" * width if v is None else f"{int(v):0{width}X}"

    print("cycle  pc  dly  x         y         osr       pins oe  fifo  instr")
    for _ in range(args.cycles):
        word = pending[0] if pending else None
        full = len(core.fifo) == core.cfg.fifo_depth
        core.step(tx_wr_en=word is not None, tx_wr_data=word or 0)
        if word is not None and not full:
            pending.popleft()
        s = core.snapshot()
        print(f"{core.cycle:5d}  {s['pc']:3d} {s['delay_cnt']:3d}  {fmt(s['x'], 8)}  "
              f"{fmt(s['y'], 8)}  {fmt(s['osr'], 8)}  {fmt(s['pins_out'], 2)}   "
              f"{fmt(s['pins_oe'], 2)}  {len(core.fifo):4d}  "
              f"{isa.disassemble(core.mem[s['pc']], prog.side_set_count)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

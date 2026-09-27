"""RTL-vs-reference-model lockstep harness.

Each cycle the harness drives the same inputs into the RTL and into tools/model.py,
clocks both, then compares every architectural register. The first difference raises
Divergence with both states and the instruction at the PC. It also fails any cycle in
which a pin with its output enable set is driving X.

    h = await Harness.start(dut, asm.assemble_file("programs/core_test.asm"))
    await h.reset()
    h.push(0xA5000000)
    await h.run(10)
"""

import sys
from collections import deque
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from cocotb.types import LogicArray

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import isa  # noqa: E402
from model import STATE_KEYS, Config, Core, ResetSync  # noqa: E402


class Divergence(AssertionError):
    pass


def _as_int(value):
    """LogicArray/Logic -> int, or None if any bit is X/Z."""
    return int(value) if value.is_resolvable else None


class Harness:
    def __init__(self, dut, program):
        self.dut = dut
        self.top = dut.user_project
        self.core_rtl = self.top.u_core
        self.program = program
        self.cfg = self._read_config()
        if program.side_set_count != self.cfg.side_set_count:
            raise ValueError(f"program assembled for .side_set {program.side_set_count} but "
                             f"the core is configured for {self.cfg.side_set_count}")
        self.model = Core(program.image(), self.cfg)
        self.rst_sync = ResetSync()
        self.pending = deque()   # words waiting to be written into the TX FIFO
        self.trace = []          # per-cycle RTL state, for protocol decoders
        self.cycle = 0

    @classmethod
    async def start(cls, dut, program, period_us=10):
        dut.ena.value = 1
        dut.ui_in.value = 0
        dut.uio_in.value = 0
        dut.rst_n.value = 0
        dut.user_project.tx_wr_en.value = 0
        dut.user_project.tx_wr_data.value = 0
        cocotb.start_soon(Clock(dut.clk, period_us, unit="us").start())
        # Wait until time-0 initial blocks ($readmemh) and constant config ports settle.
        await FallingEdge(dut.clk)
        h = cls(dut, program)
        h._load_program()
        return h

    def _read_config(self):
        """Take core config from the RTL ports so the model can't drift from project.v."""
        c = self.core_rtl
        return Config(
            enable=bool(int(c.enable.value)),
            start_addr=int(c.start_addr.value),
            wrap_bottom=int(c.wrap_bottom.value),
            wrap_top=int(c.wrap_top.value),
            side_set_count=int(c.side_set_count.value),
            fifo_depth=len(self.top.tx_fifo.mem),
        )

    def _load_program(self):
        """Stand-in for the host interface: write every progmem word, X where unused."""
        mem = self.top.u_progmem.mem
        unused = LogicArray("X" * isa.INSTR_W)
        for addr, word in enumerate(self.program.image()):
            mem[addr].value = unused if word is None else word

    # ---- stimulus ----------------------------------------------------------------

    def push(self, *words):
        """Queue words for the TX FIFO; one is written per cycle while it has room."""
        self.pending.extend(w & isa.REG_MASK for w in words)

    async def reset(self, cycles=5, wait_release=True):
        """Hold rst_n low for `cycles`, then (by default) release it and clock until the
        synchronizer lets the core run, so the next run() cycle is the first executed."""
        for _ in range(cycles):
            await self._cycle(rst_n=False)
        if wait_release:
            for _ in range(ResetSync.STAGES):
                await self._cycle(rst_n=True)

    async def run(self, cycles):
        for _ in range(cycles):
            await self._cycle(rst_n=True)

    async def run_until(self, predicate, max_cycles=1000):
        """Run until predicate(rtl_state) is true; returns the cycles taken."""
        for n in range(1, max_cycles + 1):
            await self._cycle(rst_n=True)
            if predicate(self.trace[-1]):
                return n
        raise TimeoutError(f"condition not met within {max_cycles} cycles")

    # ---- one cycle -----------------------------------------------------------------

    async def _cycle(self, rst_n):
        core_rst_n = self.rst_sync.step(rst_n)  # what the core sees at this edge
        # The FIFO drops writes while held in reset, so only offer one once it's out.
        word = self.pending[0] if (core_rst_n and self.pending) else None
        # Only consume the word if the FIFO had room; the model's full flag was checked
        # against the RTL's last cycle, so they agree.
        if word is not None and len(self.model.fifo) < self.cfg.fifo_depth:
            self.pending.popleft()

        self.dut.rst_n.value = int(rst_n)
        self.top.tx_wr_en.value = int(word is not None)
        self.top.tx_wr_data.value = word or 0
        self.model.step(rst_n=core_rst_n, tx_wr_en=word is not None, tx_wr_data=word or 0)

        await RisingEdge(self.dut.clk)
        await ReadOnly()
        self.cycle += 1
        rtl = self.rtl_state()
        self.trace.append(rtl)
        self._check_no_x_on_driven_pins()
        if rtl["rst_n_sync"] != self.rst_sync.out:
            raise Divergence(f"cycle {self.cycle}: rst_n_sync is {rtl['rst_n_sync']}, "
                             f"model says {self.rst_sync.out}")
        self._compare(rtl, self.model.snapshot())
        await FallingEdge(self.dut.clk)

    def rtl_state(self):
        c, t = self.core_rtl, self.top
        return {
            "pc": _as_int(c.pc.value),
            "delay_cnt": _as_int(c.delay_cnt.value),
            "x": _as_int(c.x.value),
            "y": _as_int(c.y.value),
            "osr": _as_int(c.osr.reg_q.value),
            "pins_out": _as_int(self.dut.uio_out.value),
            "pins_oe": _as_int(self.dut.uio_oe.value),
            "side_set": _as_int(t.core_side_set.value),
            "tx_empty": _as_bool(t.tx_empty.value),
            "tx_full": _as_bool(t.tx_full.value),
            "rst_n_sync": _as_int(t.rst_n_sync.value),
        }

    def _check_no_x_on_driven_pins(self):
        out = str(self.dut.uio_out.value)   # MSB first
        oe = str(self.dut.uio_oe.value)
        bad = [7 - i for i, (o, e) in enumerate(zip(out, oe)) if e != "0" and o not in "01"]
        if bad or any(e not in "01" for e in oe):
            raise Divergence(f"cycle {self.cycle}: X driven on uio pins {sorted(bad)} "
                             f"(uio_out={out} uio_oe={oe}) at {self.model.describe()}")

    def _compare(self, rtl, model):
        diffs = []
        for key in STATE_KEYS:
            want = model[key]
            if want is None:
                continue  # model says unknown: RTL may hold anything, including X
            if rtl[key] != want:
                diffs.append(key)
        if diffs:
            lines = [f"cycle {self.cycle}: RTL diverged from model in {', '.join(diffs)}",
                     f"  model at {self.model.describe()}",
                     f"  {'':10s} {'RTL':>12s} {'model':>12s}"]
            for key in STATE_KEYS:
                mark = " <--" if key in diffs else ""
                lines.append(f"  {key:10s} {_fmt(rtl[key]):>12s} {_fmt(model[key]):>12s}{mark}")
            raise Divergence("\n".join(lines))


def _as_bool(value):
    v = _as_int(value)
    return None if v is None else bool(v)


def _fmt(v):
    if v is None:
        return "X"
    if isinstance(v, bool):
        return str(int(v))
    return f"0x{v:X}"

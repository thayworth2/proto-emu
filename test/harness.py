"""RTL-vs-reference-model lockstep harness.

Each cycle the harness clocks the RTL and tools/model.py together, then compares every
architectural register. The first difference raises Divergence with both states and
the instruction at the PC. It also fails any cycle in which a pin with its output
enable set is driving X.

Everything reaches the chip through its pins: the harness is the SPI host, loading the
program, the TX FIFO and the core enable through src/host_spi.v. The host interface is
not modelled; each cycle the harness reads its outputs (enable, program write, FIFO
write) from the RTL and gives the model the same ones. boot() checks that what it
wrote into program memory is the program.

    h = await Harness.start(dut, asm.assemble_file("programs/core_test.asm"))
    await h.boot()               # reset, load the program, enable the core
    h.push(0xA5000000)           # queued as an SPI frame; lands ~170 cycles later
    await h.run(200)
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


# Host SPI pins on ui_in (src/project.v)
SCK, MOSI, CS_N = 0x01, 0x02, 0x04
HOST_IDLE = CS_N


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
        self.host_pins = deque()  # ui_in value per cycle for queued SPI frames
        self.trace = []          # per-cycle RTL state, for protocol decoders
        self.cycle = 0

    @classmethod
    async def start(cls, dut, program, period_us=10):
        dut.ena.value = 1
        dut.ui_in.value = HOST_IDLE
        dut.uio_in.value = 0
        dut.rst_n.value = 0
        cocotb.start_soon(Clock(dut.clk, period_us, unit="us").start())
        # Wait until time-0 initial blocks ($readmemh) and constant config ports settle.
        await FallingEdge(dut.clk)
        h = cls(dut, program)
        h._clear_progmem()
        return h

    def _read_config(self):
        """Take core config from the RTL ports so the model can't drift from project.v."""
        c = self.core_rtl
        return Config(
            start_addr=int(c.start_addr.value),
            wrap_bottom=int(c.wrap_bottom.value),
            wrap_top=int(c.wrap_top.value),
            side_set_count=int(c.side_set_count.value),
            fifo_depth=len(self.top.tx_fifo.mem),
        )

    def _clear_progmem(self):
        """Program memory is not reset: make every word X, as it is at power-up, so a
        test can only pass on words the host actually wrote."""
        mem = self.top.u_progmem.mem
        unused = LogicArray("X" * isa.INSTR_W)
        for addr in range(isa.PROG_DEPTH):
            mem[addr].value = unused

    # ---- host SPI ------------------------------------------------------------------

    SCK_HALF = 2  # clk cycles per SCK half-period; host_spi.v needs SCK slower than clk/4

    def host_frame(self, *fields):
        """Queue one SPI frame. Each field is (value, bit count), sent MSB first. A
        short last field makes a frame that CS_n cuts off mid-word."""
        pins = [0] * self.SCK_HALF  # CS_n low, SCK low
        for value, nbits in fields:
            for i in reversed(range(nbits)):
                mosi = MOSI if (value >> i) & 1 else 0
                pins += [mosi] * self.SCK_HALF + [mosi | SCK] * self.SCK_HALF
        pins += [0] * self.SCK_HALF + [HOST_IDLE] * self.SCK_HALF
        self.host_pins.extend(pins)

    def load_program(self, words=None, addr=0):
        """Queue a frame writing `words` (default: the program) from `addr` up."""
        if words is None:
            words = self.program.words
        self.host_frame((isa.HOST_CMDS["PROG"], 8), (addr, 8),
                        *((w, isa.INSTR_W) for w in words))

    def push(self, *words):
        """Queue a frame writing words to the TX FIFO. There is no flow control: a
        word that arrives while the FIFO is full is dropped, in RTL and model alike."""
        self.host_frame((isa.HOST_CMDS["FIFO"], 8),
                        *((w & isa.REG_MASK, isa.REG_WIDTH) for w in words))

    def set_enable(self, on):
        self.host_frame((isa.HOST_CMDS["CTRL"], 8), (int(on), 8))

    async def host_idle(self):
        """Run until every queued frame has been sent and has taken effect."""
        while self.host_pins:
            await self._cycle(rst_n=True)
        await self.run(4)  # synchronizer + edge detect + write strobe

    # ---- stimulus ----------------------------------------------------------------

    async def reset(self, cycles=5, wait_release=True):
        """Hold rst_n low for `cycles`, then (by default) release it and clock until the
        synchronizer has let go. The core comes out of reset disabled."""
        for _ in range(cycles):
            await self._cycle(rst_n=False)
        if wait_release:
            for _ in range(ResetSync.STAGES):
                await self._cycle(rst_n=True)

    async def boot(self):
        """Reset, load the program over SPI and enable the core. Returns with the core
        about to execute its first instruction on the next run() cycle."""
        await self.reset()
        self.load_program()
        self.set_enable(True)
        for _ in range(len(self.host_pins) + 8):
            await self._cycle(rst_n=True)
            if self.trace[-1]["enable"]:
                break
        else:
            raise Divergence("core enable never set by the host interface")
        image = self.program.image()
        if self.model.mem != image:
            bad = [a for a, (got, want) in enumerate(zip(self.model.mem, image)) if got != want]
            raise Divergence(f"host interface wrote the wrong program: addresses {bad} differ")

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
        # The host interface's outputs are registered, so what they hold now is what
        # the core, FIFO and program memory see at this edge. In reset nothing does.
        host = self._host_outputs() if core_rst_n else {}

        self.dut.rst_n.value = int(rst_n)
        self.dut.ui_in.value = self.host_pins.popleft() if self.host_pins else HOST_IDLE
        self.model.step(rst_n=core_rst_n, **host)

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

    def _host_outputs(self):
        t = self.top

        def known(handle, name):
            value = _as_int(handle.value)
            if value is None:
                raise Divergence(f"cycle {self.cycle}: host interface output {name} is X")
            return value

        out = {"enable": bool(known(t.core_enable, "core_enable")),
               "tx_wr_en": bool(known(t.tx_wr_en, "tx_wr_en"))}
        if out["tx_wr_en"]:
            out["tx_wr_data"] = known(t.tx_wr_data, "tx_wr_data")
        if known(t.prog_wr_en, "prog_wr_en"):
            out["prog_wr"] = (known(t.prog_wr_addr, "prog_wr_addr"),
                              known(t.prog_wr_data, "prog_wr_data"))
        return out

    def rtl_state(self):
        c, t = self.core_rtl, self.top
        return {
            "enable": _as_bool(t.core_enable.value),
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

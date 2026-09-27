# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0
"""Minimal-core tests. Every test runs through harness.Harness, which checks the RTL
against tools/model.py every cycle; the explicit asserts below check intent, since a
bug shared by the RTL and the model would pass the lockstep comparison."""

from pathlib import Path

import cocotb

from harness import Divergence, Harness

import asm  # on sys.path via harness

PROGRAMS = Path(__file__).parent / "programs"


def load(name):
    return asm.assemble_file(PROGRAMS / f"{name}.asm")


@cocotb.test()
async def test_smoke_pull_out(dut):
    """core_test.asm: each TX FIFO word's top byte appears on the pins."""
    prog = load("core_test")
    h = await Harness.start(dut, prog)
    await h.reset()

    await h.run(2)
    assert h.trace[-1]["pins_oe"] == 0xFF, "pindirs should be all-output after SET"
    loop = prog.labels["loop"]
    await h.run(3)
    assert h.trace[-1]["pc"] == loop, "blocking PULL should stall on an empty FIFO"

    h.push(0xA5000000)
    # FIFO write, PULL, OUT: the byte is on the pins at the third edge.
    n = await h.run_until(lambda s: s["pins_out"] == 0xA5, max_cycles=10)
    assert n == 3, f"expected the byte on the pins 3 cycles after the push, took {n}"

    await h.run(3)
    assert h.trace[-1]["pins_out"] == 0xA5, "output should hold while PULL stalls"
    assert h.trace[-1]["pc"] == loop

    h.push(0x3C000000)
    await h.run_until(lambda s: s["pins_out"] == 0x3C, max_cycles=10)


@cocotb.test()
async def test_countdown_delays_and_jmp_conditions(dut):
    """countdown.asm: delays, X/Y post-decrement loops, and JMP conditions 0-5."""
    prog = load("countdown")
    h = await Harness.start(dut, prog)
    await h.reset()
    start = len(h.trace)
    await h.run_until(lambda s: s["pc"] == prog.labels["park"], max_cycles=500)

    pin0 = [s["pins_out"] & 1 for s in h.trace[start:] if s["pins_out"] is not None]
    assert all(s["pins_out"] != 0xFF for s in h.trace[start:]), "program reached `fail`"

    # Widths of each high run on pin 0: `set pins, 1 [2]` holds for 3 cycles.
    widths, run = [], 0
    for bit in pin0 + [0]:
        if bit:
            run += 1
        elif run:
            widths.append(run)
            run = 0
    assert widths == [3] * 6, f"expected six 3-cycle pulses, got {widths}"


@cocotb.test()
async def test_out_destinations(dut):
    """out_dest.asm: OUT to X, Y, null, pins, pindirs; bit counts 1/4/7/8/12/32;
    non-blocking PULL on an empty FIFO."""
    prog = load("out_dest")
    h = await Harness.start(dut, prog)
    await h.reset()

    w1, w2 = 0x5ABCD3C3, 0xDEADBEEF
    h.push(w1)
    await h.run_until(lambda s: s["pc"] == prog.labels["second"], max_cycles=50)
    await h.run(3)  # stalled on the blocking PULL; lockstep keeps checking
    s = h.trace[-1]
    assert s["x"] == w1 >> 28
    assert s["y"] == (w1 >> 16) & 0xFFF
    assert s["pins_out"] == (w1 >> 8) & 1
    assert s["pins_oe"] == w1 & 0xFF
    assert s["osr"] == 0, "32 bits shifted out; empty non-blocking PULL must not reload"

    h.push(w2)
    await h.run_until(lambda s: s["pc"] == prog.labels["park"], max_cycles=20)
    await h.run(1)
    assert h.trace[-1]["x"] == w2


@cocotb.test()
async def test_reset_does_not_execute(dut):
    """reset_hold.asm: holding rst_n low must not run the instruction at address 0."""
    prog = load("reset_hold")
    h = await Harness.start(dut, prog)
    await h.reset()
    h.push(0x12345678)
    await h.run_until(lambda s: s["pc"] == prog.labels["park"], max_cycles=20)
    before = h.trace[-1]
    assert before["osr"] == 0x23456780

    await h.reset()   # lockstep compares OSR/X on every reset cycle
    after = h.trace[-1]
    assert (after["osr"], after["x"]) == (before["osr"], before["x"]), \
        "OSR/X changed while rst_n was low"


@cocotb.test()
async def test_harness_catches_divergence(dut):
    """The checker must be able to fail: give the model a different OUT width than the
    RTL runs and confirm the harness reports the first diverging cycle."""
    prog = load("core_test")
    h = await Harness.start(dut, prog)
    out_addr = prog.labels["loop"] + 1
    h.model.mem[out_addr] = asm.assemble("out pins, 4").words[0]

    await h.reset()
    h.push(0xA5000000)
    try:
        await h.run(10)
    except Divergence as e:
        dut._log.info(f"harness reported, as expected:\n{e}")
        assert "pins_out" in str(e) and "osr" in str(e)
    else:
        raise AssertionError("harness missed a deliberate RTL/model difference")

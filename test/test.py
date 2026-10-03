# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0
"""Core, host-interface and protocol tests. Every test runs through harness.Harness,
which loads the chip over its SPI host pins and checks the RTL against tools/model.py
every cycle; the explicit asserts below check intent, since a bug shared by the RTL and
the model would pass the lockstep comparison."""

from pathlib import Path

import cocotb
from cocotb.triggers import ReadOnly, Timer

from harness import Divergence, Harness
import uart

import asm  # on sys.path via harness
from model import ResetSync

PROGRAMS = Path(__file__).parent / "programs"

# Upper bound on the cycles between h.push() of one word and it landing in the FIFO.
PUSH_CYCLES = 200


def load(name):
    return asm.assemble_file(PROGRAMS / f"{name}.asm")


@cocotb.test()
async def test_smoke_pull_out(dut):
    """core_test.asm: each TX FIFO word's top byte appears on the pins."""
    prog = load("core_test")
    h = await Harness.start(dut, prog)
    await h.boot()

    await h.run(2)
    assert h.trace[-1]["pins_oe"] == 0xFF, "pindirs should be all-output after SET"
    loop = prog.labels["loop"]
    await h.run(3)
    assert h.trace[-1]["pc"] == loop, "blocking PULL should stall on an empty FIFO"

    h.push(0xA5000000)
    await h.run_until(lambda s: not s["tx_empty"], max_cycles=PUSH_CYCLES)
    # PULL, then OUT: the byte is on the pins at the second edge after the FIFO write.
    n = await h.run_until(lambda s: s["pins_out"] == 0xA5, max_cycles=10)
    assert n == 2, f"expected the byte on the pins 2 cycles after the FIFO write, took {n}"

    await h.run(3)
    assert h.trace[-1]["pins_out"] == 0xA5, "output should hold while PULL stalls"
    assert h.trace[-1]["pc"] == loop

    h.push(0x3C000000)
    await h.run_until(lambda s: s["pins_out"] == 0x3C, max_cycles=PUSH_CYCLES + 10)


@cocotb.test()
async def test_countdown_delays_and_jmp_conditions(dut):
    """countdown.asm: delays, X/Y post-decrement loops, and JMP conditions 0-5."""
    prog = load("countdown")
    h = await Harness.start(dut, prog)
    await h.boot()
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
    await h.boot()

    w1, w2 = 0x5ABCD3C3, 0xDEADBEEF
    h.push(w1)
    await h.run_until(lambda s: s["pc"] == prog.labels["second"], max_cycles=PUSH_CYCLES + 50)
    await h.run(3)  # stalled on the blocking PULL; lockstep keeps checking
    s = h.trace[-1]
    assert s["x"] == w1 >> 28
    assert s["y"] == (w1 >> 16) & 0xFFF
    assert s["pins_out"] == (w1 >> 8) & 1
    assert s["pins_oe"] == w1 & 0xFF
    assert s["osr"] == 0, "32 bits shifted out; empty non-blocking PULL must not reload"

    h.push(w2)
    await h.run_until(lambda s: s["pc"] == prog.labels["park"], max_cycles=PUSH_CYCLES + 20)
    await h.run(1)
    assert h.trace[-1]["x"] == w2


@cocotb.test()
async def test_reset_does_not_execute(dut):
    """reset_hold.asm: holding rst_n low must not run the instruction at address 0."""
    prog = load("reset_hold")
    h = await Harness.start(dut, prog)
    await h.boot()
    h.push(0x12345678)
    await h.run_until(lambda s: s["pc"] == prog.labels["park"], max_cycles=PUSH_CYCLES + 20)
    before = h.trace[-1]
    assert before["osr"] == 0x23456780

    await h.reset()   # lockstep compares OSR/X on every reset cycle
    await h.run(5)    # reset cleared the enable: still nothing may execute
    after = h.trace[-1]
    assert (after["osr"], after["x"]) == (before["osr"], before["x"]), \
        "OSR/X changed during or after reset"
    assert after["pc"] == 0 and not after["enable"]


@cocotb.test()
async def test_reset_sync_timing(dut):
    """reset_sync.v: rst_n asserts before the next clock edge, releases after two. The
    core comes out of reset disabled and runs on the first edge after it is enabled."""
    prog = load("core_test")
    h = await Harness.start(dut, prog)
    await h.boot()
    await h.run(4)

    # Mid-cycle, well before the next rising edge: assertion must already be through.
    dut.rst_n.value = 0
    await Timer(1, unit="us")
    await ReadOnly()
    assert int(h.top.rst_n_sync.value) == 0, "reset assertion should be asynchronous"
    await Timer(1, unit="us")  # leave the read-only phase before driving again

    await h.reset(cycles=3, wait_release=False)
    await h.run(ResetSync.STAGES)       # rst_n high, synchronizer still releasing
    assert [s["rst_n_sync"] for s in h.trace[-2:]] == [0, 1]
    await h.run(3)
    assert all(s["pc"] == 0 and not s["enable"] and s["pins_oe"] == 0 for s in h.trace[-5:]), \
        "core must come out of reset disabled, with every pin an input"

    await h.boot()
    assert h.trace[-1]["pc"] == 0
    await h.run(1)
    assert h.trace[-1]["pc"] == 1, "core should run on the first edge after the enable"


@cocotb.test()
async def test_harness_catches_divergence(dut):
    """The checker must be able to fail: give the model a different OUT width than the
    RTL runs and confirm the harness reports the first diverging cycle."""
    prog = load("core_test")
    h = await Harness.start(dut, prog)
    await h.boot()
    out_addr = prog.labels["loop"] + 1
    h.model.mem[out_addr] = asm.assemble("out pins, 4").words[0]

    h.push(0xA5000000)
    try:
        await h.run(PUSH_CYCLES + 10)
    except Divergence as e:
        dut._log.info(f"harness reported, as expected:\n{e}")
        assert "pins_out" in str(e) and "osr" in str(e)
    else:
        raise AssertionError("harness missed a deliberate RTL/model difference")


@cocotb.test()
async def test_host_interface(dut):
    """host_spi.v: a frame cut off mid-word writes nothing, program writes
    auto-increment and wrap, a FIFO write while full is dropped, and the enable bit
    starts and stops the core."""
    prog = load("core_test")
    h = await Harness.start(dut, prog)
    await h.reset()
    mem = h.top.u_progmem.mem
    cmd = asm.isa.HOST_CMDS

    # CS_n rises 4 bits short of a full instruction: nothing may be written.
    h.host_frame((cmd["PROG"], 8), (0x10, 8), (0xABCDE, 20))
    await h.host_idle()
    assert not mem[0x10].value.is_resolvable, "a cut-off frame wrote program memory"

    # Three words starting at the second-to-last address wrap round to address 0.
    words = [0xA00011, 0xA00022, 0xA00033]
    h.load_program(words, addr=0xFE)
    await h.host_idle()
    assert [int(mem[a].value) for a in (0xFE, 0xFF, 0x00)] == words
    assert not mem[0x01].value.is_resolvable

    # Core still disabled, so nothing drains the FIFO: the fifth word is dropped.
    h.push(1 << 24, 2 << 24, 3 << 24, 4 << 24, 5 << 24)
    await h.host_idle()
    assert h.trace[-1]["tx_full"] and not h.trace[-1]["enable"]
    assert h.trace[-1]["pc"] == 0, "core ran while disabled"

    # Load the real program and enable: the four words that fit come out in order.
    h.load_program()
    h.set_enable(True)
    await h.host_idle()
    await h.run(20)
    seen = []
    for s in h.trace:
        if s["pins_oe"] == 0xFF and s["pins_out"] and s["pins_out"] not in seen[-1:]:
            seen.append(s["pins_out"])
    assert seen == [1, 2, 3, 4], f"expected FIFO words 1-4 on the pins, saw {seen}"

    # Disable: the PC returns to the start address and stays there.
    h.set_enable(False)
    await h.host_idle()
    await h.run(5)
    assert all(s["pc"] == 0 and not s["enable"] for s in h.trace[-5:])


UART_BIT_CYCLES = 16  # set by the delays in programs/uart_tx.asm


@cocotb.test()
async def test_uart_tx(dut):
    """uart_tx.asm: bytes pushed into the TX FIFO come out of pin 0 as 8N1 frames,
    16 cycles per bit, back to back while the FIFO has data, idle high otherwise."""
    prog = load("uart_tx")
    h = await Harness.start(dut, prog)
    await h.boot()
    start = len(h.trace)

    await h.run(40)  # FIFO empty: the line must be driven and idle high
    assert h.trace[-1]["pins_oe"] & 1, "TX pin should be an output"
    assert uart.decode(uart.line_levels(h.trace[start:]), UART_BIT_CYCLES) == []

    # The host delivers a word every 128 cycles and a frame takes 160, so the FIFO
    # stays non-empty for the whole burst without ever filling.
    burst = bytes([0x55, 0x41, 0x52, 0x54, 0x00, 0xFF])  # "UART", then all-0 and all-1 data
    frame = 10 * UART_BIT_CYCLES
    h.push(*(uart.tx_word(b) for b in burst))
    await h.run(PUSH_CYCLES + len(burst) * frame + 40)

    h.push(uart.tx_word(0xA5))  # after an idle gap
    await h.run(PUSH_CYCLES + frame + 40)

    levels = uart.line_levels(h.trace[start:])
    assert all(levels[:40]), "line dropped low with nothing to send"
    frames = uart.decode(levels, UART_BIT_CYCLES)
    assert bytes(b for _, b in frames) == burst + bytes([0xA5]), f"decoded {frames}"

    starts = [s for s, _ in frames]
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert gaps[:len(burst) - 1] == [frame] * (len(burst) - 1), \
        f"back-to-back frames should start exactly {frame} cycles apart, got {gaps}"
    assert gaps[-1] > frame, "last byte was pushed after an idle gap"

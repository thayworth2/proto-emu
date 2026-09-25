# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles


@cocotb.test()
async def test_minimal_core_pull_out(dut):
    """Smoke test for the minimal core (build order step 2): JMP/SET/OUT/PULL.

    No host interface exists yet, so this test pokes the TX FIFO's write
    port directly (dut.user_project.tx_wr_en/tx_wr_data) rather than going
    through SPI. The program in core_test.hex does:
        addr0: SET pindirs, 0xFF   -- all 8 core pins as outputs
        addr1: PULL block          -- TX FIFO -> OSR
        addr2: OUT pins, 8         -- top 8 bits of OSR -> pins
        addr3: JMP always, 1       -- loop back to PULL
    """
    dut._log.info("Start")

    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())

    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.user_project.tx_wr_en.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)

    assert dut.uio_oe.value == 0xFF, "pindirs should be all-output after SET"
    # Core should now be parked on the blocking PULL at addr1, empty FIFO.
    assert int(dut.user_project.u_core.pc.value) == 1

    # Push one word into the TX FIFO. `OUT pins, 8` takes the top 8 bits
    # of the OSR, so the top byte of this word is what should land on
    # uio_out. PULL executes once the FIFO shows non-empty, then OUT the
    # cycle after.
    dut.user_project.tx_wr_data.value = 0xA5000000
    dut.user_project.tx_wr_en.value = 1
    await ClockCycles(dut.clk, 1)
    dut.user_project.tx_wr_en.value = 0
    await ClockCycles(dut.clk, 3)
    assert dut.uio_out.value == 0xA5, "OUT pins,8 should drive the pulled byte"

    # The program loops on JMP always back to PULL; with the FIFO now
    # empty, the blocking PULL should stall (pc holds at addr1) rather
    # than corrupting the output.
    await ClockCycles(dut.clk, 3)
    assert dut.uio_out.value == 0xA5, "output should hold while PULL stalls on empty FIFO"
    assert int(dut.user_project.u_core.pc.value) == 1

    # Push a second word and confirm the core resumes and updates the output.
    dut.user_project.tx_wr_data.value = 0x3C000000
    dut.user_project.tx_wr_en.value = 1
    await ClockCycles(dut.clk, 1)
    dut.user_project.tx_wr_en.value = 0
    await ClockCycles(dut.clk, 3)
    assert dut.uio_out.value == 0x3C, "core should resume once the FIFO has data again"

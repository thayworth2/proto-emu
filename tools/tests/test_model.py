"""Reference-model unit tests (model alone, no RTL). Run: pytest tools"""

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import asm  # noqa: E402
from model import Config, Core, NotInRTL, ResetSync, UseBeforeInit  # noqa: E402


def make(src, **cfg):
    prog = asm.assemble(src)
    core = Core(prog.image(), Config(side_set_count=prog.side_set_count, **cfg))
    core.step(rst_n=False)
    return core


def run(core, n, push=()):
    push = list(push)
    for _ in range(n):
        core.step(tx_wr_en=bool(push), tx_wr_data=push.pop(0) if push else 0)


def test_delay_takes_n_plus_one_cycles():
    core = make("set pins, 1 [3]\nset pins, 2")
    run(core, 1)
    assert (core.pc, core.delay_cnt, core.pins_val) == (0, 3, 1)
    run(core, 3)
    assert (core.pc, core.delay_cnt) == (1, 0)


def test_blocking_pull_stalls_then_loads():
    core = make("pull block\nout x, 8")
    run(core, 3)
    assert core.pc == 0
    run(core, 1, push=[0xAB000000])   # written this edge, so PULL still sees empty
    assert core.pc == 0
    run(core, 2)
    assert core.x == 0xAB and core.osr == 0


def test_x_loop_post_decrements():
    core = make("set x, 2\nl: jmp x-- l\nk: jmp k")
    run(core, 4)
    assert core.pc == 2 and core.x == 0xFFFFFFFF


def test_branch_on_uninitialized_x_is_an_error():
    core = make("jmp !x 0")
    with pytest.raises(UseBeforeInit, match="uninitialized X"):
        run(core, 1)


def test_fetch_past_program_is_an_error():
    core = make("set x, 1")
    run(core, 1)
    with pytest.raises(UseBeforeInit, match="uninitialized program memory"):
        run(core, 1)


def test_unimplemented_opcode_is_flagged():
    core = make("wait 1 pin 0")
    with pytest.raises(NotInRTL, match="WAIT"):
        run(core, 1)


def test_fifo_full_drops_writes():
    core = make("k: jmp k")
    run(core, 6, push=[1, 2, 3, 4, 5, 6])
    assert list(core.fifo) == [1, 2, 3, 4]


def test_wrap_bounds():
    core = make("set x, 1\nset x, 2\nset x, 3", wrap_bottom=1, wrap_top=2)
    run(core, 3)
    assert core.pc == 1 and core.x == 3   # pc 2 == wrap_top -> wrap_bottom, not 3


def test_reset_sync_asserts_at_once_releases_after_two_edges():
    rs = ResetSync()
    with pytest.raises(UseBeforeInit):
        rs.step(True)
    assert rs.step(False) is False
    assert [rs.step(True) for _ in range(3)] == [False, False, True]
    assert rs.step(False) is False and rs.out == 0

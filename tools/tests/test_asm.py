"""Assembler / ISA-table unit tests. Run: pytest tools"""

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import asm  # noqa: E402
import isa  # noqa: E402

REPO = TOOLS.parent


def one(line, side_set=0):
    header = f".side_set {side_set}\n" if side_set else ""
    return asm.assemble(header + line).words[0]


# Hand-checked against the field layout in CLAUDE.md.
@pytest.mark.parametrize("line, word", [
    ("set pindirs, 0xFF", 0xA080FF),
    ("set pins, 0", 0xA00000),
    ("set x, 5", 0xA02005),
    ("pull block", 0x80A000),
    ("pull", 0x80A000),
    ("pull noblock", 0x808000),
    ("pull ifempty block", 0x80E000),
    ("push", 0x802000),
    ("out pins, 8", 0x600800),
    ("out x, 32", 0x602000),
    ("out pc, 1", 0x60A100),
    ("in zeros, 3", 0x406300),
    ("jmp 1", 0x000001),
    ("jmp x-- 7", 0x002007),
    ("jmp !osre 0", 0x007000),
    ("wait 1 gpio 4", 0x20A400),
    ("set pins, 1 [31]", 0xBF0001),
])
def test_encoding(line, word):
    assert one(line) == word


def test_side_set_packing():
    # 2 side-set bits take [20:19]; delay gets [18:16]
    assert one("set pins, 0 side 2 [7]", side_set=2) == 0xA00000 | (0b10111 << 16)
    assert one("set pins, 0 side 1", side_set=1) == 0xA00000 | (0b10000 << 16)


@pytest.mark.parametrize("src, msg", [
    ("set pins, 256", "out of range"),
    ("set pc, 1", "unknown set destination"),
    ("out isr, 8", "unknown out destination"),
    ("out pins, 0", "out of range"),
    ("out pins, 33", "out of range"),
    ("jmp nowhere", "undefined label"),
    ("jmp x++ 0", "unknown jmp condition"),
    ("set pins, 1 [32]", "delay 32 out of range"),
    (".side_set 1\nset pins, 1 [16]", "delay 16 out of range"),
    (".side_set 1\nset pins, 1", "missing `side`"),
    (".side_set 1\nset pins, 1 side 2", "does not fit"),
    ("set pins, 1 side 1", ".side_set is 0"),
    ("mov x, y", "unknown instruction"),
    ("a:\na: jmp a", "duplicate label"),
    ("set pins, 0\n.side_set 1", "before the first instruction"),
])
def test_rejects(src, msg):
    with pytest.raises(asm.AsmError, match=msg):
        asm.assemble(src)


@pytest.mark.parametrize("word, msg", [
    (0x000101, "reserved bits"),     # JMP [11:8]
    (0xA01000, "reserved bits"),     # SET [12:8]
    (0x600801, "reserved bits"),     # OUT [7:0]
    (0x80A001, "reserved bits"),     # PULL [12:0]
    (0x200001, "reserved bits"),     # WAIT [7:0]
    (0xC00000, "opcode 110"),        # MOV
    (0xE00000, "opcode 111"),        # ALU/IRQ
    (0x008000, "JMP condition 8"),
    (0xA06000, "SET destination 011"),
    (0x60C800, "OUT destination 110"),
    (0x408800, "IN source 100"),
    (0x1000000, "wider than 24"),
])
def test_word_reserved_rejection(word, msg):
    with pytest.raises(asm.AsmError, match=msg):
        asm.assemble(f".word 0x{word:X}")


def test_word_passes_legal_value():
    assert one(".word 0xA080FF") == 0xA080FF


def test_labels_and_listing():
    prog = asm.assemble("start: set x, 1\nloop:\n  jmp x-- loop ; c\n  jmp start")
    assert prog.labels == {"start": 0, "loop": 1}
    assert prog.words == [0xA02001, 0x002001, 0x000000]
    assert len(prog.image()) == isa.PROG_DEPTH and prog.image()[3] is None


def test_disassemble_round_trip():
    src = ["set pindirs, 0xFF", "pull block", "out pins, 8", "jmp x-- 3",
           "in isr, 32", "wait 0 timer 2", "push iffull noblock", "set y, 0x07 [4]"]
    for line in src:
        word = one(line)
        assert one(isa.disassemble(word)) == word, line


def test_package_parse_matches_known_layout():
    # If these move, the Verilog package changed and every table here follows it.
    assert (isa.OPCODE.hi, isa.OPCODE.lo, isa.DELAYSS.width, isa.INSTR_W) == (23, 21, 5, 24)
    assert isa.OP["SET"] == 0b101 and isa.JMP_CONDS["Y_NE_Z"] == 4


@pytest.mark.parametrize("name", ["core_test"])
def test_checked_in_hex_matches_source(name):
    """The $readmemh image in test/ must be regenerated whenever its .asm changes."""
    prog = asm.assemble_file(REPO / "test" / "programs" / f"{name}.asm")
    assert asm.read_hex(REPO / "test" / f"{name}.hex") == prog.words, \
        f"test/{name}.hex is stale: run `make -C test hex`"

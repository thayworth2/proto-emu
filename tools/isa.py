"""Instruction-set definitions shared by the assembler, the reference model and the testbench.

Every opcode, field position and width here is parsed out of src/proto_emu_pkg.vh at
import time, so the Python side cannot drift from the RTL decoder. The only things
defined in this file are the ones the Verilog package has no reason to know: which
selector values are legal per the ISA spec, and the text names used in assembly.
"""

import re
from pathlib import Path
from typing import NamedTuple

PKG_PATH = Path(__file__).resolve().parents[1] / "src" / "proto_emu_pkg.vh"

_DEFINE_RE = re.compile(r"^\s*`define\s+(\w+)\s+([^\s/]+)")
_LITERAL_RE = re.compile(r"(\d+)?'([bdhBDH])([0-9a-fA-F_]+)")


def _parse_literal(text):
    m = _LITERAL_RE.fullmatch(text)
    if m:
        base = {"b": 2, "d": 10, "h": 16}[m.group(2).lower()]
        return int(m.group(3).replace("_", ""), base)
    return int(text, 0)


def load_defines(path=PKG_PATH):
    """Return {NAME: int} for every numeric `define in the Verilog package."""
    defines = {}
    for line in Path(path).read_text().splitlines():
        m = _DEFINE_RE.match(line)
        if not m:
            continue
        try:
            defines[m.group(1)] = _parse_literal(m.group(2))
        except ValueError:
            pass  # non-numeric define (e.g. an include guard)
    return defines


D = load_defines()


class Field(NamedTuple):
    hi: int
    lo: int

    @property
    def width(self):
        return self.hi - self.lo + 1

    @property
    def mask(self):
        return ((1 << self.width) - 1) << self.lo

    def get(self, word):
        return (word >> self.lo) & ((1 << self.width) - 1)

    def put(self, value):
        if not 0 <= value < (1 << self.width):
            raise ValueError(f"{value} does not fit in {self.width} bits")
        return value << self.lo


def _bit(name):
    return Field(D[name], D[name])


def _field(prefix):
    return Field(D[prefix + "_HI"], D[prefix + "_LO"])


def _enum(prefix):
    """{"NAME": value} for every `define <prefix>NAME, skipping _HI/_LO/_BIT positions."""
    return {
        k[len(prefix):]: v
        for k, v in D.items()
        if k.startswith(prefix) and not k.endswith(("_HI", "_LO", "_BIT"))
    }


INSTR_W = D["INSTR_W"]
INSTR_MASK = (1 << INSTR_W) - 1
REG_WIDTH = D["REG_WIDTH"]
REG_MASK = (1 << REG_WIDTH) - 1
PROG_DEPTH = D["PROG_DEPTH"]
PROG_ADDR_W = D["PROG_ADDR_W"]

OPCODE = _field("OPCODE")
DELAYSS = _field("DELAYSS")

JMP_COND = _field("JMP_COND")
JMP_TARGET = _field("JMP_TARGET")
SET_DEST = _field("SET_DEST")
SET_IMM = _field("SET_IMM")
OUTIN_SEL = _field("OUTIN_SEL")
OUTIN_CNT = _field("OUTIN_CNT")
PP_DIR = _bit("PUSHPULL_DIR_BIT")
PP_IFFLAG = _bit("PUSHPULL_IFFLAG_BIT")
PP_BLOCK = _bit("PUSHPULL_BLOCK_BIT")
WAIT_POL = _bit("WAIT_POL_BIT")
WAIT_SRC = _field("WAIT_SRC")
WAIT_IDX = _field("WAIT_IDX")

OP = _enum("OP_")                  # JMP, WAIT, IN, OUT, PUSHPULL, SET, MOV, ALU
OP_NAME = {v: k for k, v in OP.items()}
JMP_CONDS = _enum("JMP_COND_")     # ALWAYS, X_EQ_Z, ...
SET_DESTS = _enum("SET_DEST_")
OUT_DESTS = _enum("OUT_DEST_")
IN_SRCS = _enum("IN_SRC_")
WAIT_SRCS = _enum("WAIT_SRC_")
PP_DIR_PUSH = D["PUSHPULL_DIR_PUSH"]
PP_DIR_PULL = D["PUSHPULL_DIR_PULL"]

# Selector values the ISA spec (CLAUDE.md "Selectors") defines. The package also names
# some "reserved for now" codes; those are not legal in programs yet.
LEGAL_SET_DESTS = {k: SET_DESTS[k] for k in ("PINS", "X", "Y", "PINDIRS")}
LEGAL_OUT_DESTS = {k: OUT_DESTS[k] for k in ("PINS", "X", "Y", "NULL", "PINDIRS", "PC")}
LEGAL_IN_SRCS = {k: IN_SRCS[k] for k in ("PINS", "X", "Y", "ZEROS", "ISR", "OSR")}
LEGAL_JMP_CONDS = {k: JMP_CONDS[k] for k in
                   ("ALWAYS", "X_EQ_Z", "X_NE_Z", "Y_EQ_Z", "Y_NE_Z", "X_NE_Y", "PIN", "OSR_NE")}

# Argument fields each opcode actually uses; every other argument bit is reserved.
OPCODE_FIELDS = {
    OP["JMP"]: (JMP_COND, JMP_TARGET),
    OP["WAIT"]: (WAIT_POL, WAIT_SRC, WAIT_IDX),
    OP["IN"]: (OUTIN_SEL, OUTIN_CNT),
    OP["OUT"]: (OUTIN_SEL, OUTIN_CNT),
    OP["PUSHPULL"]: (PP_DIR, PP_IFFLAG, PP_BLOCK),
    OP["SET"]: (SET_DEST, SET_IMM),
}

ARGS_MASK = Field(D["ARGS_HI"], D["ARGS_LO"]).mask


def reserved_mask(opcode):
    """Argument bits that must be zero for this opcode."""
    used = 0
    for f in OPCODE_FIELDS[opcode]:
        used |= f.mask
    return ARGS_MASK & ~used


def check_word(word):
    """Return a list of reasons `word` is not a legal instruction (empty if legal)."""
    if not 0 <= word <= INSTR_MASK:
        return [f"0x{word:X} is wider than {INSTR_W} bits"]
    op = OPCODE.get(word)
    if op not in OPCODE_FIELDS:
        return [f"opcode {op:03b} ({OP_NAME[op]}) is reserved"]
    problems = []
    stray = word & reserved_mask(op)
    if stray:
        problems.append(f"reserved bits set: 0x{stray:04X}")
    if op == OP["JMP"] and JMP_COND.get(word) not in LEGAL_JMP_CONDS.values():
        problems.append(f"JMP condition {JMP_COND.get(word)} is reserved")
    if op == OP["SET"] and SET_DEST.get(word) not in LEGAL_SET_DESTS.values():
        problems.append(f"SET destination {SET_DEST.get(word):03b} is reserved")
    if op == OP["OUT"] and OUTIN_SEL.get(word) not in LEGAL_OUT_DESTS.values():
        problems.append(f"OUT destination {OUTIN_SEL.get(word):03b} is reserved")
    if op == OP["IN"] and OUTIN_SEL.get(word) not in LEGAL_IN_SRCS.values():
        problems.append(f"IN source {OUTIN_SEL.get(word):03b} is reserved")
    return problems


def split_delayss(field, side_set_count):
    """Split the 5-bit delay/side-set field into (side_set_value, delay), matching core.v."""
    delay_bits = DELAYSS.width - side_set_count
    return field >> delay_bits, field & ((1 << delay_bits) - 1)


def eff_count(cnt):
    """OUT/IN bit count: 0 means 32."""
    return cnt if cnt else 32


def _name(table, value):
    for k, v in table.items():
        if v == value:
            return k.lower()
    return f"<{value:03b}>"


# Assembly spellings of JMP conditions, keyed by define name.
JMP_COND_SYNTAX = {
    "ALWAYS": "",
    "X_EQ_Z": "!x",
    "X_NE_Z": "x--",
    "Y_EQ_Z": "!y",
    "Y_NE_Z": "y--",
    "X_NE_Y": "x!=y",
    "PIN": "pin",
    "OSR_NE": "!osre",
}


def disassemble(word, side_set_count=0):
    """Best-effort text for one instruction word (used in divergence reports)."""
    if word is None:
        return "<uninitialized>"
    op = OPCODE.get(word)
    side, delay = split_delayss(DELAYSS.get(word), side_set_count)
    name = OP_NAME.get(op, "?")
    if op == OP["JMP"]:
        cond = JMP_COND_SYNTAX.get(_name(JMP_CONDS, JMP_COND.get(word)).upper(), "?")
        text = f"jmp {cond + ' ' if cond else ''}{JMP_TARGET.get(word)}"
    elif op == OP["SET"]:
        text = f"set {_name(SET_DESTS, SET_DEST.get(word))}, 0x{SET_IMM.get(word):02X}"
    elif op == OP["OUT"]:
        text = f"out {_name(OUT_DESTS, OUTIN_SEL.get(word))}, {eff_count(OUTIN_CNT.get(word))}"
    elif op == OP["IN"]:
        text = f"in {_name(IN_SRCS, OUTIN_SEL.get(word))}, {eff_count(OUTIN_CNT.get(word))}"
    elif op == OP["PUSHPULL"]:
        is_pull = PP_DIR.get(word) == PP_DIR_PULL
        parts = ["pull" if is_pull else "push"]
        if PP_IFFLAG.get(word):
            parts.append("ifempty" if is_pull else "iffull")
        parts.append("block" if PP_BLOCK.get(word) else "noblock")
        text = " ".join(parts)
    elif op == OP["WAIT"]:
        text = (f"wait {WAIT_POL.get(word)} {_name(WAIT_SRCS, WAIT_SRC.get(word))} "
                f"{WAIT_IDX.get(word)}")
    else:
        text = f"{name.lower()} 0x{word & ARGS_MASK:04X}"
    if side_set_count:
        text += f" side {side}"
    if delay:
        text += f" [{delay}]"
    return text

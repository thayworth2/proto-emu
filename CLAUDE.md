# proto-emu — Claude Code Context

## What this project is

A **protocol emulator ASIC** submitted to the Jane Street ASIC Competition via Tiny Tapeout's CMOS5L process.
The goal: a tiny CPU with an instruction set purpose-built for reading/writing pins and hitting precise timing,
so that protocols like UART, SPI, I2C, JTAG, etc. can be implemented in firmware rather than fixed logic.
Think RP2040 PIO state machines or TI PRU cores — but our own design.

**Competition deadline:** January 18, 2027
**Target process:** IHP 130nm CMOS5L via Tiny Tapeout
**Tile allocation:** 6×4 (~0.7 mm², ~24K logic cells budget)
**Top module:** `tt_um_thayworth2_proto_emu`
**Repo:** https://github.com/thayworth2/proto-emu

## Priority protocol targets

1. UART (start here — transmitter first, then RX)
2. SPI
3. I2C
4. Stretch: JTAG, SWD, PS/2, CAN, low-speed USB, 10Mbit Ethernet

## Project structure

| Path | Purpose |
|------|---------|
| `src/` | Verilog RTL source files (all synthesis targets go here) |
| `test/` | Cocotb testbench; `test/Makefile` lists `PROJECT_SOURCES` |
| `docs/info.md` | Project datasheet (auto-published by Tiny Tapeout CI) |
| `info.yaml` | Project metadata + pinout (must keep `yaml_version: 6`) |
| `.github/workflows/` | CI: gds, docs, test, fpga — run automatically on push |
| `tt/` | Tiny Tapeout support tools — do not edit |
| `.devcontainer/` | Dev container config for codespaces/VS Code |

---

# Architecture

Not a hand-written FSM per protocol. This is a small processor: behavior lives in the program, and the
hardware just executes instructions. Anything a protocol author might want to change after fabrication is a
register, not a constant.

## Block diagram

```
  host SPI  ->  host interface  ->  program memory  ->  core (PC, X, Y, ALU, branch)  <->  timer
                      |                                       | control
                      v                                       v
   TX FIFO -> OSR -> [encode + CRC] -> output mux (pin map + OE) -> IO pins
   RX FIFO <- ISR <- [decode + CRC] <- sync (2-FF) + input mux   <- IO pins
```

- The core drives everything. Shift registers do not pick their own pins; the core's decoded instruction
  says when to shift, what the output mux drives, and when to stall.
- The encode/decode stages are the main departure from PIO: optional inline CRC/LFSR, bit stuffing, and
  NRZI/Manchester coding so USB and Ethernet don't need a host CPU. Bypassed for UART/SPI/I2C.
- Input pins **must** pass through a 2-FF synchronizer before any logic sees them.
- Output enable is per-pin and separate from the output value. I2C never drives high; it pulls low or
  releases.

## Module breakdown (one file per module in `src/`)

| Module | Responsibility |
|---|---|
| `proto_emu_pkg.vh` | **Single source of truth** for opcodes, field positions, widths. Every module includes it. |
| `core.v` | PC, fetch, decode, execute, delay counter, stall logic, wrap |
| `shiftreg.v` | OSR and ISR (same module, direction parameterized) |
| `fifo.v` | TX and RX FIFOs (depth parameterized) |
| `pinmux.v` | Per-core pin base offsets, output value + OE mux, input select |
| `sync.v` | 2-FF input synchronizer |
| `cfgregs.v` | Per-core config registers, written over the host interface |
| `host_spi.v` | SPI slave: loads program memory, reads/writes FIFOs and config |
| `progmem.v` | Instruction memory wrapper (flip-flop array now, SRAM macro later) |
| `codec.v` | Later: CRC/LFSR, bit stuff/unstuff, NRZI/Manchester |
| `tt_um_thayworth2_proto_emu.v` | Top level: TT pin wiring only, no logic |

Keep these parameterized from day one — they *will* change: `NUM_CORES`, `PROG_DEPTH`, `REG_WIDTH`
(32 now, may drop to 16), `FIFO_DEPTH`.

---

# Instruction set

Full spec doc: https://claude.ai/code/artifact/7c4c77f2-20b7-4e8d-9a81-f26b664e3591

24 bits per instruction. Baseline with deliberate headroom; may narrow once the SRAM macro word width is known.

```
 23  21 20    16 15                          0
[opcode][delay/ss][         arguments         ]
  3 b     5 b              16 b
```

- `[23:21]` opcode
- `[20:16]` delay / side-set. A per-core config register sets how many of these bits are side-set pins
  (0–2); the remainder is a delay count applied after the instruction.
- `[15:0]` arguments

## Opcodes

| Code | Instruction | Purpose |
|---|---|---|
| 000 | `JMP` | Conditional jump; X/Y decrement gives loop counting |
| 001 | `WAIT` | Stall until a pin, timer, or flag reaches a value |
| 010 | `IN` | Shift bits from a source into the ISR |
| 011 | `OUT` | Shift bits from the OSR to a destination |
| 100 | `PUSH`/`PULL` | ISR → RX FIFO, or TX FIFO → OSR |
| 101 | `SET` | Write an 8-bit immediate to pins, pin directions, X, or Y |
| 110 | reserved | planned `MOV` |
| 111 | reserved | planned ALU ops / `IRQ` |

## Argument layouts

| Instruction | [15:13] | [12:8] | [7:0] |
|---|---|---|---|
| `JMP` | [15:12] condition (4b) | [11:8] reserved | target address |
| `WAIT` | [15] polarity, [14:13] source | index | reserved |
| `SET` | destination | reserved | immediate |
| `OUT` | destination | bit count | reserved |
| `IN` | source | bit count | reserved |
| `PUSH`/`PULL` | [15] 0=push 1=pull, [14] if-full/if-empty, [13] block | reserved | reserved |

`OUT` and `IN` deliberately share field positions to simplify decode.

## Field values

**`JMP` condition [15:12]:** 0 always · 1 X==0 · 2 X!=0 then decrement · 3 Y==0 · 4 Y!=0 then decrement ·
5 X!=Y · 6 pin high · 7 OSR not empty · 8–15 reserved (TX FIFO empty, flag set, timer done)

**`WAIT` source [14:13]:** 00 pin (relative to core input base) · 01 absolute pin · 10 timer · 11 flag

**Selectors [15:13]:**

| Code | `SET` dest | `OUT` dest | `IN` source |
|---|---|---|---|
| 000 | pins | pins | pins |
| 001 | X | X | X |
| 010 | Y | Y | Y |
| 011 | reserved | null (discard) | zeros |
| 100 | pindirs | pindirs | reserved |
| 101 | reserved | PC | reserved |
| 110 | reserved | reserved | ISR |
| 111 | reserved | reserved | OSR |

Bit count 0 means 32. The `SET` immediate is zero-extended into X or Y.

**Reserved bits must be zero.** The assembler rejects non-zero reserved bits; the decoder ignores them.
This keeps today's programs valid when those bits gain meaning.

## Per-core config registers

| Register | Width | Reset |
|---|---|---|
| enable | 1 | 0 |
| start address | 8 | 0 |
| wrap bottom / top | 8 + 8 | 0 / 0 |
| pin bases (in, out, set, side-set) | TBD | 0 |
| side-set count | 2 | 0 |
| clock divider | TBD | 1 |

Reset sequence: all cores disabled with PC=0, all pins inputs. Host loads program → writes config →
enables cores.

---

# Verilog conventions

- **Verilog-2001**, synthesizable subset. No SystemVerilog constructs — LibreLane/Yosys in the TT flow is
  happiest with plain Verilog.
- **One `always` block per register group.** Sequential logic is `always @(posedge clk)` with non-blocking
  `<=`. Combinational is `always @(*)` with blocking `=`.
- **No latches.** Every `always @(*)` assigns a default to every output on the first line, then overrides.
  Check the Yosys log for inferred latch warnings and treat them as errors.
- **No initial blocks** for anything that matters in silicon. Simulation-only init must be guarded.
- **No `for` loops that unroll into huge logic** without checking the cell count after.
- **Include `proto_emu_pkg.vh`** rather than re-declaring opcode constants. Duplicated magic numbers are how
  the decoder and assembler drift apart.
- Name signals `<module>_<signal>` at boundaries; active-low signals end in `_n`.

## Reset policy

Selective, not blanket. Resetting every flop wastes area and creates a high-fanout net needing buffering.

**Reset these:** core enables, all output enables (pins must power up as inputs), program counters, delay
counters, stall state, FIFO read/write pointers, host interface state, config registers.

**Do not reset these:** instruction memory (SRAM can't be anyway; host loads it before enable), FIFO
storage (pointers say it's empty), shift registers, X and Y, codec state.

- TT provides active-low `rst_n`. Synchronize release: assert immediately, deassert through two flops.
- Pick synchronous *or* asynchronous reset and use it everywhere. Do not mix.
- Unreset registers are X in simulation — **keep X-propagation on**. An X reaching a pin or a branch
  decision is a real bug (use-before-init), not noise to suppress.

## Tiny Tapeout pin discipline

- 8 dedicated inputs `ui_in`, 8 dedicated outputs `uo_out`, 8 bidirectional `uio_in`/`uio_out`/`uio_oe`.
- `uio_oe` is per-bit: 1 = drive, 0 = input. Required for I2C open-drain behavior.
- Pins spent on the host SPI link are pins unavailable to protocols. Budget explicitly and keep
  `info.yaml` pinout in sync as this settles.
- Top level does wiring only. No logic in `tt_um_*`.

---

# Verification

This is judged, not an afterthought. The competition explicitly calls out formal methods,
constrained-random testing, and AI-assisted verification.

## The three-part harness (build alongside the first core, not after)

1. **Assembler** (`tools/asm.py`): text → 24-bit hex. Enforces reserved-bits-zero.
2. **Reference model** (`tools/model.py`): executes the same program in Python, cycle-accurate.
3. **Cocotb testbench** (`test/`): runs RTL and model on the same program, compares state every cycle.

Any divergence between RTL and model is a bug in one of them. This equivalence check is the backbone of
the verification story for the writeup.

## Test layers

- **Unit:** each module standalone (FIFO fill/drain/wrap, shift register directions, synchronizer).
- **Instruction:** one test per opcode × per field value, including reserved-bit rejection.
- **Protocol:** assemble real UART/SPI/I2C programs, decode the pin waveform in Python, assert the right
  bytes came out at the right timing.
- **Constrained-random:** random valid programs through both RTL and model.
- **Formal:** worth targeting properties like "no X reaches an output pin," "PC always within wrap
  bounds," "FIFO pointers never pass each other."

Run `make` in `test/` for cocotb locally. GDS CI runs LibreLane — check the badge and action logs
after pushing.

---

# Build order

Do not build the whole thing at once. Each step ends with a real number to feed the next decision.

1. **Check SRAM macros** available on IHP 130nm via TT, and their word widths. This can change the 24-bit
   instruction decision, so resolve it before writing the decoder.
2. **Minimal core:** `JMP`, `SET`, `OUT`, `PULL` + delay/side-set. Program memory as a flip-flop array
   loaded with `$readmemh`. No host interface — testbench pokes the FIFO directly.
3. **Assembler + reference model + cocotb equivalence check.**
4. **UART TX out of a real pin** in simulation, waveform decoded and asserted.
5. **Run the full TT flow.** Synthesis cell count, then place and route, then STA. Now the area and clock
   numbers are real.
6. **Revisit architecture with those numbers:** how many cores fit, 32-bit vs 16-bit registers, flip-flop
   memory vs SRAM macro.
7. Add `WAIT`, `IN`, `PUSH` → UART RX, SPI, I2C. Log every place the ISA feels awkward; those notes drive
   the extensions and the writeup.
8. Only then: codec path (CRC, bit stuffing, line coding), instruction injection, USB/Ethernet.

**Defer:** codec stages, instruction injection, reserved opcodes, multi-core. All are easy to add to a
working core and painful to debug inside a broken one.

---

# Open questions

- Program memory depth, and which SRAM macros exist on this node (may force an instruction width change)
- How two cores share one program memory: dual-port SRAM, time-shared single port, flip-flop array with
  two read ports, or separate per-core memories
- Core count (1, 2, or 4) — decide after measuring one core's cell count
- Pin budget split between host interface and protocol pins
- Encoding for `MOV` and ALU/`IRQ` in the reserved opcodes
- Meaning of `JMP` conditions 8–15
- `REG_WIDTH`: keep X/Y/OSR/ISR at 32, or start at 16 to save area

---

# Workflow notes

- Work on the `cmos5l` branch; `main` is the upstream template base.
- Run synthesis early and often. A design that fits after synthesis can still fail to route.
- If an FPGA is available, test RTL there before committing to the ASIC flow.
- Build in public — the competition encourages it, and the writeup is part of what's judged.

## What the competition rewards

- Novel architecture / ISA design (not a PIO clone — the codec path and debug features are the
  differentiators)
- Verification methodology: formal, constrained-random, AI-assisted
- Reprogrammability after fabrication within timing/IO constraints
- Open source, with a writeup that shows *why* each departure from PIO was made

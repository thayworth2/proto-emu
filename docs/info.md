<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

This is a protocol emulator: a small processor whose instruction set is built for reading pins, writing
pins and counting clock cycles exactly. A protocol such as UART, SPI or I2C is a short program loaded
after fabrication, not fixed logic, in the spirit of the RP2040's PIO state machines.

The chip currently contains:

- **One core** with a program counter, two 32-bit scratch registers (X and Y), an output shift register
  and a per-instruction delay counter. Every instruction takes exactly one clock cycle plus its delay,
  so pin timing is set by the program.
- **Program memory**: 256 instructions of 24 bits each.
- **TX FIFO**: four 32-bit words, pulled into the output shift register by the program.
- **Host interface**: a write-only SPI slave that loads the program, fills the TX FIFO and enables the
  core.
- **Eight core pins** on the bidirectional pins, each with its own output enable. All are inputs after
  reset.

Implemented instructions:

| Instruction | Purpose |
|---|---|
| `JMP` | Jump, optionally conditional on X or Y, with decrement for loop counting |
| `SET` | Write an 8-bit immediate to the pins, the pin directions, X or Y |
| `OUT` | Shift 1 to 32 bits out of the shift register to the pins, the pin directions, X or Y |
| `PULL` | Load the shift register from the TX FIFO, optionally stalling while it is empty |

Each instruction also carries a 5-bit delay, giving 0 to 31 extra cycles before the next one runs.
`WAIT`, `IN` and `PUSH`, which the receive direction needs, are defined in the instruction set but not
built yet.

### Host interface

SPI mode 0, most significant bit first. SCK must be slower than a quarter of the chip clock. A frame is
CS_n low, one command byte, then the payload; raising CS_n ends the frame and discards a partly
received word.

| Command byte | Payload |
|---|---|
| `0x01` | One address byte, then any number of 24-bit instructions written from that address upward |
| `0x02` | Any number of 32-bit words, each written to the TX FIFO. A word sent while the FIFO is full is dropped |
| `0x03` | One control byte. Bit 0 enables the core |

After reset the core is disabled with its program counter at 0. Program memory is not cleared by
reset, so load every instruction the program uses before enabling the core.

## How to test

Load the UART transmitter (`test/programs/uart_tx.asm`), which sends 8N1 on core pin 0 (`uio[0]`) at
one bit per 16 clock cycles, so the baud rate is the clock frequency divided by 16.

1. Hold `rst_n` low for a few clock cycles, then release it.
2. Send the program: command `0x01`, address `0x00`, then these nine instructions:
   `A00001 A08001 80A000 A02007 AF0000 6E0100 002005 AC0001 000002`
3. Enable the core: command `0x03`, then `0x01`. `uio[0]` goes high and stays there (UART idle).
4. Send a byte: command `0x02`, then one 32-bit word with the byte bit-reversed in the top eight bits.
   For `0x55` (`U`) the word is `0xAA000000`.
5. Watch `uio[0]` with a UART receiver or logic analyser set to clock / 16 baud.

The same sequence runs in simulation with `make` in `test/`, which also checks the design against a
cycle-accurate Python model on every clock cycle. `tools/asm.py` assembles programs into the hex words
shown above.

## External hardware

An SPI master to load the program (any microcontroller, or the Tiny Tapeout demo board's RP2040), and
a USB-to-UART adapter or logic analyser on `uio[0]` to see the output.

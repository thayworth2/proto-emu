![GDS](../../workflows/gds/badge.svg) ![Docs](../../workflows/docs/badge.svg) ![Test](../../workflows/test/badge.svg) ![FPGA](../../workflows/fpga/badge.svg)

# proto-emu — Protocol Emulator ASIC

A programmable protocol emulator chip submitted to the [Jane Street ASIC Competition](https://asic-competition.janestreet.com) via [Tiny Tapeout](https://tinytapeout.com)'s CMOS5L process.

**The idea:** a tiny CPU with an instruction set designed for reading pins, writing pins, and counting cycles with precise timing — so hardware protocols can be implemented in firmware rather than fixed logic. Similar in spirit to the RP2040's PIO state machines or TI's PRU cores, but our own design.

## Goals

**Primary protocols:** UART · SPI · I2C  
**Stretch goals:** JTAG · SWD · PS/2 · CAN · low-speed USB · 10Mbit Ethernet

## Process

- **Foundry:** IHP 130nm CMOS5L via Tiny Tapeout
- **Tile allocation:** 6×4 (~0.7 mm²)
- **Top module:** `tt_um_thayworth2_proto_emu`
- **Deadline:** January 18, 2027

## Repository layout

```
src/        RTL source files
test/       Cocotb testbench
docs/       Project datasheet (info.md)
info.yaml   Project metadata and pinout
tt/         Tiny Tapeout support tools (do not edit)
```

## Getting started

1. Add Verilog files to `src/` and list them in `info.yaml` under `source_files`.
2. Update the pinout in `info.yaml` as the design solidifies.
3. Edit `docs/info.md` for the project datasheet.
4. Run `make` in `test/` to run the cocotb testbench.
5. The GDS CI workflow runs automatically on push — check the badge above.

If you have an FPGA, test your RTL there before committing to the full ASIC flow.

## Resources

- [Tiny Tapeout docs](https://tinytapeout.com)
- [CMOS5L template](https://github.com/TinyTapeout/tt10-verilog-template)
- [IHP 130nm PDK](https://github.com/IHP-GmbH/IHP-Open-PDK)
- [RP2040 PIO reference](https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf) (§3)
- [TI PRU reference](https://www.ti.com/lit/ug/spruhj7/spruhj7.pdf)
- [Jane Street competition page](https://asic-competition.janestreet.com)

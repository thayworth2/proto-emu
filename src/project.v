/*
 * Copyright (c) 2024 Tyler Hayworth
 * SPDX-License-Identifier: Apache-2.0
 *
 * Top level: TT pin wiring + structural instantiation only, no logic of
 * its own. Minimal-core bring-up (build order step 2): one core, its
 * program memory, and its TX FIFO. Config (enable/start/wrap/side-set)
 * is hardcoded below until cfgregs.v + host_spi.v exist; the TX FIFO's
 * write port is intentionally left for the testbench to poke directly
 * (dut.user_project.tx_fifo) until then.
 */

`default_nettype none
`include "proto_emu_pkg.vh"

module tt_um_thayworth2_proto_emu (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  // Hardcoded core config until the host interface can write it.
  localparam ENABLE         = 1'b1;
  localparam [`PROG_ADDR_W-1:0] START_ADDR  = {`PROG_ADDR_W{1'b0}};
  localparam [`PROG_ADDR_W-1:0] WRAP_BOTTOM = {`PROG_ADDR_W{1'b0}};
  localparam [`PROG_ADDR_W-1:0] WRAP_TOP    = {`PROG_ADDR_W{1'b1}};
  localparam [1:0]              SIDE_SET_COUNT = 2'b00;

  wire [`PROG_ADDR_W-1:0] pc_addr;
  wire [`INSTR_W-1:0]     instr;

  progmem #(
      .INIT_FILE("core_test.hex")
  ) u_progmem (
      .clk  (clk),
      .addr (pc_addr),
      .instr(instr)
  );

  wire                    tx_rd_en;
  wire [`REG_WIDTH-1:0]   tx_rd_data;
  wire                    tx_empty;
  wire                    tx_wr_en;
  wire [`REG_WIDTH-1:0]   tx_wr_data;
  wire                    tx_full;

  fifo #(
      .DEPTH(4),
      .WIDTH(`REG_WIDTH)
  ) tx_fifo (
      .clk    (clk),
      .rst_n  (rst_n),
      .wr_en  (tx_wr_en),    // left undriven here; testbench pokes this directly
      .wr_data(tx_wr_data),  // for now, until host_spi.v (build order step 7)
      .full   (tx_full),
      .rd_en  (tx_rd_en),
      .rd_data(tx_rd_data),
      .empty  (tx_empty)
  );

  wire [7:0] core_pins_out;
  wire [7:0] core_pins_oe;
  wire [1:0] core_side_set;

  core u_core (
      .clk           (clk),
      .rst_n         (rst_n),

      .enable        (ENABLE),
      .start_addr    (START_ADDR),
      .wrap_bottom   (WRAP_BOTTOM),
      .wrap_top      (WRAP_TOP),
      .side_set_count(SIDE_SET_COUNT),

      .pc_addr       (pc_addr),
      .instr         (instr),

      .tx_rd_en      (tx_rd_en),
      .tx_rd_data    (tx_rd_data),
      .tx_empty      (tx_empty),

      .pins_out      (core_pins_out),
      .pins_oe       (core_pins_oe),
      .side_set      (core_side_set),

      .dbg_x         (),
      .dbg_y         ()
  );

  pinmux u_pinmux (
      .core_pins_out (core_pins_out),
      .core_pins_oe  (core_pins_oe),
      .core_side_set (core_side_set),
      .uio_out       (uio_out),
      .uio_oe        (uio_oe)
  );

  // Dedicated outputs and host-facing SPI pins are unused until the host
  // interface (build order step 7+) lands.
  assign uo_out = 8'h00;

  wire _unused = &{ena, uio_in, ui_in, tx_full, 1'b0};

endmodule

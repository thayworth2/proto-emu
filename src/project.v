/*
 * Copyright (c) 2024 Tyler Hayworth
 * SPDX-License-Identifier: Apache-2.0
 *
 * Top level: TT pin wiring + structural instantiation only, no logic of
 * its own. One core, its program memory and its TX FIFO, loaded and
 * enabled by the host over SPI (host_spi.v). The rest of the core config
 * (start/wrap/side-set) is hardcoded below until cfgregs.v exists.
 *
 *   ui_in[0]  host SCK       uio[7:0]  core pins 7..0
 *   ui_in[1]  host MOSI
 *   ui_in[2]  host CS_n
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
  localparam [`PROG_ADDR_W-1:0] START_ADDR  = {`PROG_ADDR_W{1'b0}};
  localparam [`PROG_ADDR_W-1:0] WRAP_BOTTOM = {`PROG_ADDR_W{1'b0}};
  localparam [`PROG_ADDR_W-1:0] WRAP_TOP    = {`PROG_ADDR_W{1'b1}};
  localparam [1:0]              SIDE_SET_COUNT = 2'b00;

  // Every block below resets from rst_n_sync, never the raw rst_n.
  wire rst_n_sync;

  reset_sync u_reset_sync (
      .clk       (clk),
      .rst_n     (rst_n),
      .rst_n_sync(rst_n_sync)
  );

  // Host SPI pins: asynchronous to clk, so synchronized before any logic sees them.
  wire host_sck;
  wire host_mosi;
  wire host_cs_n;

  sync #(
      .WIDTH(3)
  ) u_host_sync (
      .clk(clk),
      .d  (ui_in[2:0]),
      .q  ({host_cs_n, host_mosi, host_sck})
  );

  wire                    core_enable;
  wire                    prog_wr_en;
  wire [`PROG_ADDR_W-1:0] prog_wr_addr;
  wire [`INSTR_W-1:0]     prog_wr_data;
  wire                    tx_wr_en;
  wire [`REG_WIDTH-1:0]   tx_wr_data;

  host_spi u_host (
      .clk         (clk),
      .rst_n       (rst_n_sync),
      .sck         (host_sck),
      .mosi        (host_mosi),
      .cs_n        (host_cs_n),
      .core_enable (core_enable),
      .prog_wr_en  (prog_wr_en),
      .prog_wr_addr(prog_wr_addr),
      .prog_wr_data(prog_wr_data),
      .tx_wr_en    (tx_wr_en),
      .tx_wr_data  (tx_wr_data)
  );

  wire [`PROG_ADDR_W-1:0] pc_addr;
  wire [`INSTR_W-1:0]     instr;

  progmem #(
      .INIT_FILE("core_test.hex")
  ) u_progmem (
      .clk    (clk),
      .wr_en  (prog_wr_en),
      .wr_addr(prog_wr_addr),
      .wr_data(prog_wr_data),
      .addr   (pc_addr),
      .instr  (instr)
  );

  wire                    tx_rd_en;
  wire [`REG_WIDTH-1:0]   tx_rd_data;
  wire                    tx_empty;
  wire                    tx_full;

  fifo #(
      .DEPTH(4),
      .WIDTH(`REG_WIDTH)
  ) tx_fifo (
      .clk    (clk),
      .rst_n  (rst_n_sync),
      .wr_en  (tx_wr_en),
      .wr_data(tx_wr_data),
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
      .rst_n         (rst_n_sync),

      .enable        (core_enable),
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

  // Dedicated outputs are unused until the host interface gains a MISO.
  assign uo_out = 8'h00;

  wire _unused = &{ena, uio_in, ui_in[7:3], tx_full, 1'b0};

endmodule

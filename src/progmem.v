/*
 * Copyright (c) 2024 Tyler Hayworth
 * SPDX-License-Identifier: Apache-2.0
 *
 * Instruction memory. Flip-flop array for now; will be replaced by an SRAM
 * macro once available macros/word widths are known (build order step 1/6).
 * The host interface (host_spi.v) writes this array over SPI; for
 * bring-up, simulation loads it directly with $readmemh.
 */

`default_nettype none
`include "proto_emu_pkg.vh"

module progmem #(
    parameter DEPTH   = `PROG_DEPTH,
    parameter ADDR_W  = `PROG_ADDR_W,
    parameter WORD_W  = `INSTR_W,
    parameter INIT_FILE = ""
) (
    input  wire                 clk,
    input  wire                 wr_en,
    input  wire [ADDR_W-1:0]    wr_addr,
    input  wire [WORD_W-1:0]    wr_data,
    input  wire [ADDR_W-1:0]    addr,
    output wire [WORD_W-1:0]    instr
);

  reg [WORD_W-1:0] mem [0:DEPTH-1];

  // Simulation-only load path. Real silicon has no $readmemh: the host
  // interface writes `mem` over SPI before a core is enabled.
`ifdef SIM
  initial begin
    if (INIT_FILE != "") begin
      $readmemh(INIT_FILE, mem);
    end
  end
`endif

  // Async read: single-cycle fetch, matches the flip-flop-array model.
  // Will need a fetch-stage register once this becomes a real SRAM macro.
  assign instr = mem[addr];

  // Not reset: the host loads every word a program uses before enabling a core.
  always @(posedge clk) begin
    if (wr_en) mem[wr_addr] <= wr_data;
  end

endmodule

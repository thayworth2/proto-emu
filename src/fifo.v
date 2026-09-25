/*
 * Copyright (c) 2024 Tyler Hayworth
 * SPDX-License-Identifier: Apache-2.0
 *
 * Synchronous FIFO used for both TX and RX (depth/width parameterized).
 * No host interface yet: for bring-up the testbench drives wr_en/wr_data
 * directly (TX side) to feed PULL instructions.
 */

`default_nettype none

module fifo #(
    parameter DEPTH = 4,
    parameter WIDTH = 32,
    parameter PTR_W = $clog2(DEPTH)
) (
    input  wire             clk,
    input  wire             rst_n,

    input  wire             wr_en,
    input  wire [WIDTH-1:0] wr_data,
    output wire             full,

    input  wire             rd_en,
    output wire [WIDTH-1:0] rd_data,
    output wire             empty
);

  reg [WIDTH-1:0] mem [0:DEPTH-1];
  reg [PTR_W:0]   wr_ptr;   // one extra bit to distinguish full from empty
  reg [PTR_W:0]   rd_ptr;

  wire wr_fire = wr_en && !full;
  wire rd_fire = rd_en && !empty;

  always @(posedge clk) begin
    if (!rst_n) begin
      wr_ptr <= {(PTR_W+1){1'b0}};
    end else if (wr_fire) begin
      mem[wr_ptr[PTR_W-1:0]] <= wr_data;
      wr_ptr <= wr_ptr + 1'b1;
    end
  end

  always @(posedge clk) begin
    if (!rst_n) begin
      rd_ptr <= {(PTR_W+1){1'b0}};
    end else if (rd_fire) begin
      rd_ptr <= rd_ptr + 1'b1;
    end
  end

  assign rd_data = mem[rd_ptr[PTR_W-1:0]];
  assign empty   = (wr_ptr == rd_ptr);
  assign full    = (wr_ptr[PTR_W-1:0] == rd_ptr[PTR_W-1:0]) && (wr_ptr[PTR_W] != rd_ptr[PTR_W]);

endmodule

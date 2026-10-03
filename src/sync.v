/*
 * Copyright (c) 2024 Tyler Hayworth
 * SPDX-License-Identifier: Apache-2.0
 *
 * 2-FF input synchronizer. Every pin that feeds logic goes through one of these
 * first. Not reset: two clock edges after power-up the output is defined, and
 * everything downstream is held in reset for at least that long.
 */

`default_nettype none

module sync #(
    parameter WIDTH = 1
) (
    input  wire             clk,
    input  wire [WIDTH-1:0] d,   // asynchronous
    output wire [WIDTH-1:0] q    // d, two clk edges later
);

  reg [WIDTH-1:0] meta_q;
  reg [WIDTH-1:0] sync_q;

  always @(posedge clk) begin
    meta_q <= d;
    sync_q <= meta_q;
  end

  assign q = sync_q;

endmodule

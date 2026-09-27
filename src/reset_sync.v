/*
 * Copyright (c) 2024 Tyler Hayworth
 * SPDX-License-Identifier: Apache-2.0
 *
 * Reset synchronizer for TT's active-low rst_n: asserts immediately, deasserts
 * through two flops so release is aligned to clk and can't hit a flop's recovery
 * window. Everything downstream uses rst_n_sync as a synchronous reset.
 *
 * These two flops are the one deliberate asynchronous reset in the design: it is
 * what makes assertion immediate. No other module should use `negedge rst_n`.
 */

`default_nettype none

module reset_sync (
    input  wire clk,
    input  wire rst_n,       // raw, asynchronous
    output wire rst_n_sync   // asserted with rst_n, released 2 clk edges after it
);

  reg [1:0] sync_q;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      sync_q <= 2'b00;
    end else begin
      sync_q <= {sync_q[0], 1'b1};
    end
  end

  assign rst_n_sync = sync_q[1];

endmodule

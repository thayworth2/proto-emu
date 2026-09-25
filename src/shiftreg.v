/*
 * Copyright (c) 2024 Tyler Hayworth
 * SPDX-License-Identifier: Apache-2.0
 *
 * Generic shift register used as both OSR (OUT direction) and ISR (IN
 * direction) -- only the OSR path is exercised by the minimal core today.
 * MSB-first: the bits nearest the top of the register shift out/in first.
 * `data` is combinational (current contents), read by the core the same
 * cycle a shift is issued, before the shift takes effect.
 */

`default_nettype none

module shiftreg #(
    parameter WIDTH = 32
) (
    input  wire                  clk,
    input  wire                  load,
    input  wire [WIDTH-1:0]      load_data,
    input  wire                  shift,
    input  wire [$clog2(WIDTH):0] shift_cnt,  // 0 means WIDTH bits
    output wire [WIDTH-1:0]      data
);

  reg [WIDTH-1:0] reg_q;

  wire [$clog2(WIDTH):0] eff_cnt = (shift_cnt == 0) ? WIDTH : shift_cnt;

  always @(posedge clk) begin
    if (load) begin
      reg_q <= load_data;
    end else if (shift) begin
      reg_q <= reg_q << eff_cnt;
    end
  end

  assign data = reg_q;

endmodule

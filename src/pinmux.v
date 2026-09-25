/*
 * Copyright (c) 2024 Tyler Hayworth
 * SPDX-License-Identifier: Apache-2.0
 *
 * Per-core output value + OE mux. Single-core, no base-offset yet: a
 * core's 8 pin bits map 1:1 onto the 8 bidirectional TT pins. Side-set
 * merging and per-core pin base offsets land once multi-core / host
 * interface work starts (build order step 6+); side_set is accepted here
 * so the port exists but is not yet merged onto a physical pin.
 */

`default_nettype none

module pinmux (
    input  wire [7:0] core_pins_out,
    input  wire [7:0] core_pins_oe,
    input  wire [1:0] core_side_set,

    output wire [7:0] uio_out,
    output wire [7:0] uio_oe
);

  assign uio_out = core_pins_out;
  assign uio_oe  = core_pins_oe;

  wire _unused = &{core_side_set, 1'b0};

endmodule

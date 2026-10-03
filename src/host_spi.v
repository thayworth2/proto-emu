/*
 * Copyright (c) 2024 Tyler Hayworth
 * SPDX-License-Identifier: Apache-2.0
 *
 * Host interface, first cut: a write-only SPI slave (mode 0, MSB first) that loads
 * program memory, writes the TX FIFO and sets the core enable. No MISO yet, so the
 * host cannot read status: a FIFO write while the FIFO is full is dropped.
 *
 * SCK is sampled in the clk domain, so it must be slower than clk/4. All three
 * inputs must already be synchronized (sync.v).
 *
 * One frame is CS_n low, a command byte, then its payload. Raising CS_n ends the
 * frame and discards a partly received field.
 *
 *   HOST_CMD_PROG  address byte, then 24-bit instructions; the address auto-increments
 *   HOST_CMD_FIFO  REG_WIDTH-bit words, each written to the TX FIFO as it completes
 *   HOST_CMD_CTRL  one byte; bit 0 is the core enable
 *
 * Only the low two bits of the command byte are decoded; the rest are reserved and
 * must be zero. The enable bit lives here until cfgregs.v exists.
 */

`default_nettype none
`include "proto_emu_pkg.vh"

module host_spi #(
    parameter REG_WIDTH   = `REG_WIDTH,
    parameter PROG_ADDR_W = `PROG_ADDR_W
) (
    input  wire                   clk,
    input  wire                   rst_n,

    // SPI pins, synchronized to clk
    input  wire                   sck,
    input  wire                   mosi,
    input  wire                   cs_n,

    output wire                   core_enable,

    output wire                   prog_wr_en,
    output wire [PROG_ADDR_W-1:0] prog_wr_addr,
    output wire [`INSTR_W-1:0]    prog_wr_data,

    output wire                   tx_wr_en,
    output wire [REG_WIDTH-1:0]   tx_wr_data
);

  // The shift register holds the widest field: an instruction or a FIFO word.
  localparam SH_W = (REG_WIDTH > `INSTR_W) ? REG_WIDTH : `INSTR_W;

  localparam [1:0] PH_CMD  = 2'd0;
  localparam [1:0] PH_ADDR = 2'd1;
  localparam [1:0] PH_DATA = 2'd2;

  reg            sck_q;      // sck one clk ago, for edge detection
  reg [1:0]      phase;
  reg [1:0]      cmd;
  reg [5:0]      bit_cnt;    // bits received so far in the current field
  reg            enable_q;
  reg            prog_wr_q;
  reg            tx_wr_q;
  reg [SH_W-1:0] shreg;
  reg [PROG_ADDR_W-1:0] addr;

  wire sck_rise = !cs_n && sck && !sck_q;
  wire [SH_W-1:0] shreg_next = {shreg[SH_W-2:0], mosi};

  // Index of the last bit of the field being received.
  reg [5:0] field_last;
  always @(*) begin
    field_last = 6'd7;  // command, address and control are one byte each
    if (phase == PH_DATA) begin
      case (cmd)
        `HOST_CMD_PROG: field_last = `INSTR_W - 1;
        `HOST_CMD_FIFO: field_last = REG_WIDTH - 1;
        default:        field_last = 6'd7;
      endcase
    end
  end

  wire field_done = sck_rise && (bit_cnt == field_last);

  // ---------------------------------------------------------------------
  // Frame state, write strobes and the core enable
  // ---------------------------------------------------------------------
  always @(posedge clk) begin
    if (!rst_n) begin
      sck_q     <= 1'b0;
      phase     <= PH_CMD;
      cmd       <= 2'd0;
      bit_cnt   <= 6'd0;
      enable_q  <= 1'b0;
      prog_wr_q <= 1'b0;
      tx_wr_q   <= 1'b0;
    end else begin
      sck_q     <= sck;
      prog_wr_q <= 1'b0;
      tx_wr_q   <= 1'b0;
      if (cs_n) begin
        phase   <= PH_CMD;
        bit_cnt <= 6'd0;
      end else if (field_done) begin
        bit_cnt <= 6'd0;
        case (phase)
          PH_CMD: begin
            cmd   <= shreg_next[1:0];
            phase <= (shreg_next[1:0] == `HOST_CMD_PROG) ? PH_ADDR : PH_DATA;
          end
          PH_ADDR: phase <= PH_DATA;
          default: begin
            case (cmd)
              `HOST_CMD_PROG: prog_wr_q <= 1'b1;
              `HOST_CMD_FIFO: tx_wr_q   <= 1'b1;
              `HOST_CMD_CTRL: enable_q  <= shreg_next[0];
              default: ;
            endcase
          end
        endcase
      end else if (sck_rise) begin
        bit_cnt <= bit_cnt + 1'b1;
      end
    end
  end

  // ---------------------------------------------------------------------
  // Shift register and write address: data, so not reset. Both are always
  // loaded by the frame before a write strobe uses them.
  // ---------------------------------------------------------------------
  always @(posedge clk) begin
    if (sck_rise) shreg <= shreg_next;
  end

  always @(posedge clk) begin
    if (field_done && (phase == PH_ADDR)) begin
      addr <= shreg_next[PROG_ADDR_W-1:0];
    end else if (prog_wr_q) begin
      addr <= addr + 1'b1;
    end
  end

  // The strobes are registered, so they are high the cycle after the last bit is
  // shifted in: the completed word is then sitting in shreg.
  assign core_enable  = enable_q;
  assign prog_wr_en   = prog_wr_q;
  assign prog_wr_addr = addr;
  assign prog_wr_data = shreg[`INSTR_W-1:0];
  assign tx_wr_en     = tx_wr_q;
  assign tx_wr_data   = shreg[REG_WIDTH-1:0];

endmodule

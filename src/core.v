/*
 * Copyright (c) 2024 Tyler Hayworth
 * SPDX-License-Identifier: Apache-2.0
 *
 * Minimal core: fetch/decode/execute for JMP, SET, OUT, PULL, plus the
 * delay/side-set field. Everything else (WAIT, IN, PUSH, MOV, ALU/IRQ,
 * multi-core, host interface) is deferred to later build-order steps.
 *
 * Config inputs (enable, start/wrap addresses, side-set count) are plain
 * ports for now; cfgregs.v will drive them once the host interface exists.
 */

`default_nettype none
`include "proto_emu_pkg.vh"

module core #(
    parameter REG_WIDTH  = `REG_WIDTH,
    parameter PROG_ADDR_W = `PROG_ADDR_W
) (
    input  wire                      clk,
    input  wire                      rst_n,

    // config, eventually driven by cfgregs.v
    input  wire                      enable,
    input  wire [PROG_ADDR_W-1:0]    start_addr,
    input  wire [PROG_ADDR_W-1:0]    wrap_bottom,
    input  wire [PROG_ADDR_W-1:0]    wrap_top,
    input  wire [1:0]                side_set_count,

    // program memory
    output wire [PROG_ADDR_W-1:0]    pc_addr,
    input  wire [`INSTR_W-1:0]       instr,

    // TX FIFO -> OSR (PULL only; PUSH/ISR deferred)
    output wire                      tx_rd_en,
    input  wire [REG_WIDTH-1:0]      tx_rd_data,
    input  wire                      tx_empty,

    // pin-facing outputs; pinmux applies per-core base offsets
    output wire [7:0]                pins_out,
    output wire [7:0]                pins_oe,
    output wire [1:0]                side_set,

    // debug/formal observability
    output wire [REG_WIDTH-1:0]      dbg_x,
    output wire [REG_WIDTH-1:0]      dbg_y
);

  // ---------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------
  reg [PROG_ADDR_W-1:0] pc;
  reg [PROG_ADDR_W-1:0] pc_next_r;
  reg [4:0]             delay_cnt;
  reg [REG_WIDTH-1:0]   x;
  reg [REG_WIDTH-1:0]   y;
  reg [7:0]             pins_val;
  reg [7:0]             pins_dir;

  assign pc_addr = pc;
  assign dbg_x   = x;
  assign dbg_y   = y;
  assign pins_out = pins_val;
  assign pins_oe  = pins_dir;

  // ---------------------------------------------------------------------
  // Decode (combinational)
  // ---------------------------------------------------------------------
  wire [2:0] opcode        = instr[`OPCODE_HI:`OPCODE_LO];
  wire [4:0] delayss_field = instr[`DELAYSS_HI:`DELAYSS_LO];

  wire [2:0] set_dest   = instr[`SET_DEST_HI:`SET_DEST_LO];
  wire [7:0] set_imm    = instr[`SET_IMM_HI:`SET_IMM_LO];

  wire [2:0] outin_sel  = instr[`OUTIN_SEL_HI:`OUTIN_SEL_LO];
  wire [4:0] outin_cnt  = instr[`OUTIN_CNT_HI:`OUTIN_CNT_LO];

  wire [3:0] jmp_cond   = instr[`JMP_COND_HI:`JMP_COND_LO];
  wire [PROG_ADDR_W-1:0] jmp_target = instr[`JMP_TARGET_HI:`JMP_TARGET_LO];

  wire       pp_dir     = instr[`PUSHPULL_DIR_BIT];
  wire       pp_block   = instr[`PUSHPULL_BLOCK_BIT];
  // pp_ifflag (if-full/if-empty) deferred: needs OSR/ISR-empty tracking.

  wire is_pull = (opcode == `OP_PUSHPULL) && (pp_dir == `PUSHPULL_DIR_PULL);

  // side-set / delay split, per the per-core side_set_count config
  reg [1:0] side_set_val;
  reg [4:0] delay_val;
  always @(*) begin
    side_set_val = 2'b00;
    delay_val    = 5'd0;
    case (side_set_count)
      2'd1: begin
        side_set_val = {1'b0, delayss_field[4]};
        delay_val    = {1'b0, delayss_field[3:0]};
      end
      2'd2: begin
        side_set_val = delayss_field[4:3];
        delay_val    = {2'b00, delayss_field[2:0]};
      end
      default: begin // 0: all 5 bits are delay
        side_set_val = 2'b00;
        delay_val    = delayss_field;
      end
    endcase
  end
  assign side_set = side_set_val;

  // JMP condition evaluation
  reg jmp_take;
  always @(*) begin
    jmp_take = 1'b0;
    case (jmp_cond)
      `JMP_COND_ALWAYS: jmp_take = 1'b1;
      `JMP_COND_X_EQ_Z: jmp_take = (x == {REG_WIDTH{1'b0}});
      `JMP_COND_X_NE_Z: jmp_take = (x != {REG_WIDTH{1'b0}});
      `JMP_COND_Y_EQ_Z: jmp_take = (y == {REG_WIDTH{1'b0}});
      `JMP_COND_Y_NE_Z: jmp_take = (y != {REG_WIDTH{1'b0}});
      `JMP_COND_X_NE_Y: jmp_take = (x != y);
      default:          jmp_take = 1'b0; // pin/OSR conditions: build order step 7
    endcase
  end

  // ---------------------------------------------------------------------
  // Stall: block on PULL when TX FIFO is empty and the instruction asks
  // to block. Non-blocking PULL against an empty FIFO is a no-op.
  // ---------------------------------------------------------------------
  wire stall_now       = enable && (delay_cnt == 0) && is_pull && pp_block && tx_empty;
  wire instr_executing = enable && (delay_cnt == 0) && !stall_now;

  wire osr_load = instr_executing && is_pull && !tx_empty;
  assign tx_rd_en = osr_load;

  // ---------------------------------------------------------------------
  // OSR (OUT direction only)
  // ---------------------------------------------------------------------
  wire [5:0] osr_shift_cnt = {1'b0, outin_cnt};
  wire       osr_shift     = instr_executing && (opcode == `OP_OUT);
  wire [REG_WIDTH-1:0] osr_data;

  shiftreg #(.WIDTH(REG_WIDTH)) osr (
      .clk       (clk),
      .load      (osr_load),
      .load_data (tx_rd_data),
      .shift     (osr_shift),
      .shift_cnt (osr_shift_cnt),
      .data      (osr_data)
  );

  wire [5:0] eff_out_cnt   = (outin_cnt == 0) ? 6'd32 : {1'b0, outin_cnt};
  wire [REG_WIDTH-1:0] osr_extracted = osr_data >> (REG_WIDTH - eff_out_cnt);

  // ---------------------------------------------------------------------
  // PC / delay sequencing
  // ---------------------------------------------------------------------
  wire [PROG_ADDR_W-1:0] pc_seq_next = (pc == wrap_top) ? wrap_bottom : (pc + 1'b1);
  wire [PROG_ADDR_W-1:0] pc_resolved_next =
      (opcode == `OP_JMP) ? (jmp_take ? jmp_target : pc_seq_next) : pc_seq_next;

  always @(posedge clk) begin
    if (!rst_n) begin
      pc        <= {PROG_ADDR_W{1'b0}};
      delay_cnt <= 5'd0;
      pc_next_r <= {PROG_ADDR_W{1'b0}};
    end else if (!enable) begin
      pc        <= start_addr;
      delay_cnt <= 5'd0;
    end else if (delay_cnt != 0) begin
      delay_cnt <= delay_cnt - 1'b1;
      if (delay_cnt == 5'd1) pc <= pc_next_r;
    end else if (instr_executing) begin
      if (delay_val != 0) begin
        delay_cnt <= delay_val;
        pc_next_r <= pc_resolved_next;
      end else begin
        pc <= pc_resolved_next;
      end
    end
    // else: stalled on a blocking PULL against an empty FIFO; hold pc.
  end

  // ---------------------------------------------------------------------
  // X / Y
  // ---------------------------------------------------------------------
  always @(posedge clk) begin
    if (instr_executing) begin
      case (opcode)
        `OP_SET: begin
          case (set_dest)
            `SET_DEST_X: x <= {{(REG_WIDTH-8){1'b0}}, set_imm};
            `SET_DEST_Y: y <= {{(REG_WIDTH-8){1'b0}}, set_imm};
            default: ;
          endcase
        end
        `OP_OUT: begin
          case (outin_sel)
            `OUT_DEST_X: x <= osr_extracted;
            `OUT_DEST_Y: y <= osr_extracted;
            default: ;
          endcase
        end
        `OP_JMP: begin
          case (jmp_cond)
            `JMP_COND_X_NE_Z: x <= x - 1'b1;
            `JMP_COND_Y_NE_Z: y <= y - 1'b1;
            default: ;
          endcase
        end
        default: ;
      endcase
    end
  end

  // ---------------------------------------------------------------------
  // Pin value / output-enable registers
  // ---------------------------------------------------------------------
  always @(posedge clk) begin
    if (!rst_n) begin
      pins_dir <= 8'h00;
    end else if (instr_executing) begin
      case (opcode)
        `OP_SET: begin
          case (set_dest)
            `SET_DEST_PINS:    pins_val <= set_imm;
            `SET_DEST_PINDIRS: pins_dir <= set_imm;
            default: ;
          endcase
        end
        `OP_OUT: begin
          case (outin_sel)
            `OUT_DEST_PINS:    pins_val <= osr_extracted[7:0];
            `OUT_DEST_PINDIRS: pins_dir <= osr_extracted[7:0];
            default: ;
          endcase
        end
        default: ;
      endcase
    end
  end

endmodule

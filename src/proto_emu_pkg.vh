/*
 * Copyright (c) 2024 Tyler Hayworth
 * SPDX-License-Identifier: Apache-2.0
 *
 * Single source of truth for opcodes, field positions, and widths.
 * Every module that decodes or emits an instruction includes this file.
 * Keep the assembler (tools/asm.py) and reference model (tools/model.py)
 * in sync with any change here.
 */

`ifndef PROTO_EMU_PKG_VH
`define PROTO_EMU_PKG_VH

// ---------------------------------------------------------------------------
// Instruction word layout: [23:21] opcode, [20:16] delay/side-set, [15:0] args
// ---------------------------------------------------------------------------
`define INSTR_W        24
`define OPCODE_HI      23
`define OPCODE_LO      21
`define DELAYSS_HI     20
`define DELAYSS_LO     16
`define DELAYSS_W      5
`define ARGS_HI        15
`define ARGS_LO        0

// ---------------------------------------------------------------------------
// Opcodes [23:21]
// ---------------------------------------------------------------------------
`define OP_JMP   3'b000
`define OP_WAIT  3'b001
`define OP_IN    3'b010
`define OP_OUT   3'b011
`define OP_PUSHPULL 3'b100
`define OP_SET   3'b101
`define OP_MOV   3'b110  // reserved
`define OP_ALU   3'b111  // reserved / IRQ

// ---------------------------------------------------------------------------
// JMP argument fields (within [15:0]): [15:12] condition, [11:8] reserved, [7:0] target
// ---------------------------------------------------------------------------
`define JMP_COND_HI    15
`define JMP_COND_LO    12
`define JMP_TARGET_HI  7
`define JMP_TARGET_LO  0

`define JMP_COND_ALWAYS   4'd0
`define JMP_COND_X_EQ_Z   4'd1
`define JMP_COND_X_NE_Z   4'd2  // then decrement X
`define JMP_COND_Y_EQ_Z   4'd3
`define JMP_COND_Y_NE_Z   4'd4  // then decrement Y
`define JMP_COND_X_NE_Y   4'd5
`define JMP_COND_PIN      4'd6  // reserved until WAIT/pin-mux land (step 7)
`define JMP_COND_OSR_NE   4'd7  // reserved until OSR-empty tracking lands

// ---------------------------------------------------------------------------
// SET argument fields: [15:13] destination, [12:8] reserved, [7:0] immediate
// ---------------------------------------------------------------------------
`define SET_DEST_HI    15
`define SET_DEST_LO    13
`define SET_IMM_HI     7
`define SET_IMM_LO     0

`define SET_DEST_PINS    3'b000
`define SET_DEST_X       3'b001
`define SET_DEST_Y       3'b010
`define SET_DEST_PINDIRS 3'b100

// ---------------------------------------------------------------------------
// OUT / IN argument fields (shared positions): [15:13] dest/src, [12:8] bit count
// ---------------------------------------------------------------------------
`define OUTIN_SEL_HI    15
`define OUTIN_SEL_LO    13
`define OUTIN_CNT_HI    12
`define OUTIN_CNT_LO    8

`define OUT_DEST_PINS    3'b000
`define OUT_DEST_X       3'b001
`define OUT_DEST_Y       3'b010
`define OUT_DEST_NULL    3'b011
`define OUT_DEST_PINDIRS 3'b100
`define OUT_DEST_PC      3'b101  // reserved for now
`define OUT_DEST_ISR     3'b110  // reserved for now
`define OUT_DEST_OSR     3'b111  // reserved for now

`define IN_SRC_PINS      3'b000
`define IN_SRC_X         3'b001
`define IN_SRC_Y         3'b010
`define IN_SRC_ZEROS     3'b011
`define IN_SRC_ISR       3'b110  // reserved for now
`define IN_SRC_OSR       3'b111  // reserved for now

// ---------------------------------------------------------------------------
// PUSH/PULL argument fields: [15] dir, [14] if-full/if-empty, [13] block
// ---------------------------------------------------------------------------
`define PUSHPULL_DIR_BIT     15
`define PUSHPULL_IFFLAG_BIT  14
`define PUSHPULL_BLOCK_BIT   13
`define PUSHPULL_DIR_PUSH    1'b0
`define PUSHPULL_DIR_PULL    1'b1

// ---------------------------------------------------------------------------
// Datapath widths (may narrow once the SRAM macro word width is known)
// ---------------------------------------------------------------------------
`define REG_WIDTH   32
`define PROG_DEPTH  256
`define PROG_ADDR_W 8

`endif // PROTO_EMU_PKG_VH

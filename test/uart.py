"""UART helpers for protocol tests: FIFO word encoding and a strict waveform decoder."""


class UartError(AssertionError):
    pass


def tx_word(byte):
    """FIFO word for uart_tx.asm: the byte bit-reversed into the top of the word,
    because the OSR shifts MSB-first and UART sends LSB-first."""
    return int(f"{byte:08b}"[::-1], 2) << 24


def line_levels(trace, pin=0):
    """Per-cycle level of one pin from a Harness trace. An undriven pin reads as 1,
    as it would with the pull-up a UART line idles on."""
    return [(s["pins_out"] >> pin) & 1 if (s["pins_oe"] >> pin) & 1 else 1 for s in trace]


def decode(levels, bit_cycles):
    """Decode 8N1 frames from one sample per clock cycle.

    Returns [(start_index, byte), ...]. Stricter than a real receiver: every cycle of
    every bit must hold the same level, so an edge that lands even one cycle early or
    late raises UartError rather than being absorbed by mid-bit sampling. A frame cut
    off by the end of the samples is an error too.
    """
    frames = []
    i = 1
    while i < len(levels):
        if not (levels[i - 1] == 1 and levels[i] == 0):
            i += 1
            continue
        start = i
        bits = []
        for n in range(10):  # start, 8 data, stop
            cell = levels[start + n * bit_cycles: start + (n + 1) * bit_cycles]
            if len(cell) < bit_cycles:
                raise UartError(f"frame at cycle {start} runs past the end of the samples")
            if len(set(cell)) != 1:
                raise UartError(f"frame at cycle {start}: bit {n} changes level mid-bit "
                                f"({''.join(map(str, cell))})")
            bits.append(cell[0])
        if bits[9] != 1:
            raise UartError(f"frame at cycle {start}: stop bit is low (framing error)")
        frames.append((start, sum(b << k for k, b in enumerate(bits[1:9]))))
        i = start + 10 * bit_cycles
    return frames

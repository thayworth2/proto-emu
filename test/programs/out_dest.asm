; OUT to every destination core.v implements, at bit counts 1, 4, 8, 12 and 32.
; The testbench pushes the second word only once the core is stalled at `second`.

        set pins, 0
        pull block
        out x, 4             ; X = top nibble
        out y, 12            ; Y = next 12 bits
        out null, 7          ; discard
        out pins, 1          ; one bit onto pin 0
        out pindirs, 8       ; low byte becomes the output enables
        pull noblock         ; FIFO is empty here: no-op, OSR keeps its (zero) value
second:
        pull block
        out x, 32            ; whole word into X
park:
        jmp park

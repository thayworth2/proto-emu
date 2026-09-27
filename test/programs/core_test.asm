; Minimal-core smoke test (build order step 2): FIFO word -> top byte on the 8 pins.
; Assembled into test/core_test.hex (the $readmemh default image) by `make hex`.

        set pins, 0          ; define pin values before driving them: no X on a pin
        set pindirs, 0xFF    ; all 8 core pins as outputs
loop:
        pull block           ; TX FIFO -> OSR, stall while empty
        out pins, 8          ; top 8 bits of the OSR -> pins
        jmp loop

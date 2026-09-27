; Delay + X/Y loop-counting exercise: pulse pin 0 once per X count, then run the
; remaining JMP conditions on known values and park.

        set pins, 0
        set pindirs, 1
        set x, 5
pulse:
        set pins, 1 [2]      ; high for 3 cycles
        set pins, 0 [1]      ; low for 2 cycles
        jmp x-- pulse        ; 6 pulses: X = 5..0, post-decrement leaves X = 0xFFFFFFFF

        set y, 2
spin:
        jmp y-- spin [31]    ; long delay on a taken and a not-taken branch
        jmp !x fail          ; X is 0xFFFFFFFF: not taken
        jmp !y fail          ; Y is 0xFFFFFFFF too: not taken
        jmp x!=y fail        ; equal: not taken
        set y, 0
        jmp !y ok            ; taken
fail:
        set pins, 0xFF
        jmp fail
ok:
        set x, 0
        jmp !x park          ; taken
        jmp fail
park:
        jmp park

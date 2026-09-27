; Reset must not execute instructions. The instruction at address 0 shifts the OSR
; into X; if it ran during a second reset, OSR and X would change while rst_n is low.

        out x, 4             ; first pass: OSR is uninitialized, X stays unknown
        pull block
        out y, 4             ; leave a known, non-zero OSR behind
park:
        jmp park

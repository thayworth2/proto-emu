; UART transmitter, 8N1, on pin 0. One bit is 16 clock cycles, so baud = clk / 16.
;
; The OSR shifts MSB-first and UART sends LSB-first, so the host bit-reverses each
; byte and puts it in the top of the FIFO word: word = bitrev8(byte) << 24.
;
; Every bit period below adds up to 16 cycles (an instruction takes 1 + its delay):
;   start   set [15]                         = 16
;   data    out [14] + jmp                   = 16
;   stop    set [12] + jmp + pull + set x    = 16   (longer if the FIFO is empty)

        set pins, 1          ; idle level first, so enabling the driver can't glitch low
        set pindirs, 1       ; pin 0 is TX
next:
        pull block           ; line idles high while the FIFO is empty
        set x, 7             ; 8 data bits
        set pins, 0 [15]     ; start bit
bitloop:
        out pins, 1 [14]     ; data bit, LSB of the byte first
        jmp x-- bitloop
        set pins, 1 [12]     ; stop bit
        jmp next

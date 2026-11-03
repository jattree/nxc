; .BGSHOW: a picture behind an unmodified game, for an experiment. Emulator only so far.
;
;   .bgshow [-a] [-p] [-c] [-C] ["FILE"]
;
; FILE (49152 raw RRRGGGBB bytes) is loaded into 16K banks 45-47 (or -DBANK=n when assembled), the 8K pages being
; reserved with IDE_BANK, so that a second call without a file only sets the registers.
;   -p  (default) only black PAPER is see-through: ULA palette 16 and 24 become the
;       transparent colour E3. Black ink stays solid.
;   -a  every black is see-through: NR 14 = 0.
;   -c  also leave a Copper list running that sets all of it again every frame.
;   -C  the same without NR 69, which also writes port 7FFD's shadow bit and Timex port FF.
;   -0  load the file but show nothing: a control for timing tests.
; The fallback colour NR 4A is set to black, which is what a black border then shows.

        opt     --zxnext
        org     $2000

M_P3DOS         equ $94
F_OPEN          equ $9a
F_CLOSE         equ $9b
F_READ          equ $9d
IDE_BANK        equ $01bd
        ifndef BANK
BANK            equ 45                      ; 16K bank; the top of a 1MB machine's user RAM
        endif
TRANS           equ $e3

start:  ld      a,h
        or      l
        jr      nz,.args
        ld      hl,msg_usage
        call    print
        or      a
        ret
.args:  call    parse
        ld      hl,0                        ; the file goes through MMU3: not with the stack there
        add     hl,sp
        ld      a,h
        cp      $80
        ld      hl,msg_stack
        jp      c,fail
        ld      a,(name)
        or      a
        call    nz,load
        ret     c
        ld      a,(none)
        or      a
        ret     nz                          ; A not 0: OR cleared carry
        call    apply
        or      a
        ret

; Options and a file name from the line at HL.
parse:  ld      a,(hl)
        cp      ' '
        jr      nz,.not_sp
        inc     hl
        jr      parse
.not_sp:
        or      a
        ret     z
        cp      13
        ret     z
        cp      ':'
        ret     z
        cp      '-'
        jr      nz,.file
        inc     hl
        ld      a,(hl)
        inc     hl
        cp      'a'
        jr      nz,.o1
        ld      (mode_all),a
        jr      parse
.o1:    cp      'c'
        jr      nz,.o2
        ld      (copper),a
        ld      (copper69),a
        jr      parse
.o2:    cp      '0'
        jr      nz,.o3
        ld      (none),a
        jr      parse
.o3:    cp      'C'
        jr      nz,parse
        ld      (copper),a
        jr      parse
.file:  ld      de,name
        ld      b,0                         ; no closing quote wanted
        cp      '"'
        jr      nz,.c
        ld      b,a
        inc     hl
.c:     ld      a,(hl)
        or      a
        jr      z,.end
        cp      13
        jr      z,.end
        cp      b
        jr      z,.q
        inc     b
        dec     b
        jr      nz,.keep
        cp      ' '
        jr      z,.end
        cp      ':'
        jr      z,.end
.keep:  ld      (de),a
        inc     de
        inc     hl
        jr      .c
.q:     inc     hl
.end:   xor     a
        ld      (de),a
        jr      parse

; Reserve the six pages and read the file into them through MMU3.
load:   ld      a,'*'
        ld      hl,name
        ld      b,1
        rst     $08
        db      F_OPEN
        ld      hl,msg_open
        jr      c,fail
        ld      (handle),a
        ld      a,$53
        call    nr_read
        ld      (mmu3),a
        ld      a,BANK * 2
.page:  ld      (page),a
        ld      e,a
        ld      d,0
        ld      hl,$0002                    ; ZX memory, reserve E
        exx
        ld      de,IDE_BANK
        ld      c,7
        rst     $08
        db      M_P3DOS
        ld      hl,msg_inuse
        jr      nc,.bad
        ld      a,(page)
        nextreg $53,a
        ld      a,(handle)
        ld      hl,$6000
        ld      bc,$2000
        rst     $08
        db      F_READ
        ld      hl,msg_short
        jr      c,.bad
        ld      a,b
        cp      $20
        jr      nz,.bad
        ld      a,(mmu3)
        nextreg $53,a
        ld      a,(page)
        inc     a
        cp      (BANK + 3) * 2
        jr      nz,.page
        ld      a,(handle)
        rst     $08
        db      F_CLOSE
        or      a
        ret
.bad:   push    hl
        ld      a,(mmu3)
        nextreg $53,a
        ld      a,(handle)
        rst     $08
        db      F_CLOSE
        pop     hl
fail:   xor     a
        scf
        ret

; Everything the picture needs; the bit a game could undo is listed in the Copper list too.
apply:  nextreg $12,BANK
        nextreg $13,BANK
        nextreg $70,0
        nextreg $16,0
        nextreg $17,0
        nextreg $71,0
        nextreg $1c,1                       ; the clip index
        nextreg $18,0
        nextreg $18,255
        nextreg $18,0
        nextreg $18,191
        nextreg $15,%00001001               ; SUL: sprites, ULA, Layer 2; sprites on
        nextreg $4a,0
        nextreg $43,%10010000               ; Layer 2 palette 1: identity
        ld      b,0
.pal:   ld      a,b
        nextreg $40,a
        nextreg $41,a
        inc     b
        jr      nz,.pal
        nextreg $43,%10000000               ; ULA palette 1, first palettes, no ULANext
        ld      a,(mode_all)
        or      a
        jr      nz,.all
        nextreg $14,TRANS
        nextreg $40,16
        nextreg $41,TRANS
        nextreg $40,24
        nextreg $41,TRANS
        jr      .on
.all:   nextreg $14,0
.on:    ld      bc,$123b
        ld      a,%00000010
        out     (c),a
        ld      a,(copper)
        or      a
        ret     z
; The list: pairs of register and value, ended by a wait that never comes.
        nextreg $62,0
        nextreg $61,0
        ld      hl,list_common
        ld      b,list_common_end - list_common
        call    send
        ld      a,(mode_all)
        or      a
        ld      hl,list_paper
        ld      b,list_paper_end - list_paper
        jr      z,.lp
        ld      hl,list_all
        ld      b,list_all_end - list_all
.lp:    call    send
        ld      a,(copper69)
        or      a
        jr      z,.end
        ld      hl,list_69
        ld      b,list_69_end - list_69
        call    send
.end:   ld      hl,list_end
        ld      b,list_end_end - list_end
        call    send
        nextreg $61,0
        nextreg $62,%11000000               ; run, and restart at each vertical blank
        ret
send:   ld      a,(hl)
        nextreg $60,a
        inc     hl
        djnz    send
        ret

list_common:
        db      $12,BANK, $13,BANK, $15,%00001001, $4a,0, $70,0
list_common_end:
list_paper:
        db      $14,TRANS, $43,%10000000, $40,16, $41,TRANS, $40,24, $41,TRANS
list_paper_end:
list_all:
        db      $14,0
list_all_end:
list_69:
        db      $69,$80
list_69_end:
list_end:
        db      $ff,$ff
list_end_end:

nr_read:
        ld      bc,$243b
        out     (c),a
        inc     b
        in      a,(c)
        ret

print:  ld      a,(hl)
        push    hl
        and     $7f
        rst     $10
        pop     hl
        bit     7,(hl)
        inc     hl
        jr      z,print
        ret

msg_usage:      db "BGSHOW [-a] [-c] [-C] [-0] [",34,"FILE",34,"]",13 | $80
msg_stack:      db "Needs CLEAR above 3276", '7' | $80
msg_open:       db "Cannot open the pictur", 'e' | $80
msg_inuse:      db "The picture banks are in us", 'e' | $80
msg_short:      db "Picture must be 49152 byte", 's' | $80

mode_all:       db 0
none:           db 0
copper:         db 0
copper69:       db 0
handle:         db 0
mmu3:           db 0
page:           db 0
name:           ds 128

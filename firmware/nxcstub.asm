; SPDX-License-Identifier: GPL-3.0-or-later
; Copyright (C) 2026 NextTang contributors
;
; The stub of a .nex that carries its menu (spec/NXC-FORMAT.md, "A .nex that
; carries its menu"). It lies at the start of the first menu bank, M0, which the
; header makes the entry bank, starting at 0xC000. It keeps what .nexload left,
; shows the menu of firmware/menu.asm, applies the choices from the data in the
; menu banks, and starts the build exactly as .nexload would have started the
; bare .nex: the same memory, registers (but R), interrupts, MMU and stack.
;
; Assembled at 0: once its registers are kept it maps M0 at 0x0000-0x3FFF and
; runs there, so that slots 2 to 7 are free. NextREGs are written through their
; ports, so that it runs on a plain Z80 emulator, except in the last 57 bytes,
; which cannot change a register once the game's are back.
;
;   sjasmplus --nologo --raw=firmware/nxcstub.bin firmware/nxcstub.asm
;
; M0, as seen from 0x0000: the stub, its parameters (its last 8 bytes), the
; menu's description up to DESC_END; the last-57-bytes buffer; the stack; then
; in the second page bank 5's screen while the menu is up, the font, variables.

        opt     --zxnext
        org     0

DESC_END        equ $1d00
BLOCK           equ $1d00               ; the last 57 bytes, built here
STACK_TOP       equ $3f80               ; in the second page, clear of the build's stack
REGS            equ STACK_TOP - 20      ; IY IX HL' DE' BC' AF' HL DE BC AF, as pushed
SHADOW          equ 16                  ; .nexload's bytes below the stack, when it is in the entry bank
SCRSAVE         equ $2000
FONT            equ $3b00
VARS            equ $3e00
KEEP_SP         equ VARS
KEEP_IFF        equ VARS + 2
DP_PAGE         equ VARS + 3            ; the data's reader: its 8K page, at 0x8000
DP_ADDR         equ VARS + 4            ; 2
PTRS            equ VARS + 6            ; 2: the lines' data offsets
LINE_I          equ VARS + 8
PASS            equ VARS + 9            ; what a pass applies: 0 trainers, 2 sets and toggles
RUN_LEFT        equ VARS + 10           ; 2
RUN_DST         equ VARS + 12           ; 2
BITBUF          equ SCRSAVE             ; a chunk's bitmap, once the screen is back
BITMAP_SIZE     equ 2048
MENU_RAM        equ VARS + 16
BLOCK_LEN       equ 57
C               equ $c000               ; where M0 is at entry

; ---------------------------------------------------------------- entry, at 0xC000
entry:  ld      (KEEP_SP + C),sp
        ld      sp,STACK_TOP + C
        push    af
        ld      a,i                     ; P/V: IFF2
        di
        ld      a,0
        jp      po,.off + C             ; this part runs at 0xC000
        inc     a
.off:   ld      (KEEP_IFF + C),a
        push    bc
        push    de
        push    hl
        ex      af,af'
        push    af
        ex      af,af'
        exx
        push    bc
        push    de
        push    hl
        exx
        push    ix
        push    iy
        ld      hl,$3d00                ; the ROM's font, while the ROM is there
        ld      de,FONT + C
        ld      bc,768
        ldir
        ld      a,(P_PAGE + C)          ; M0 at 0x0000 and 0x2000
        ld      e,$50
        call    nr_map + C
        inc     a
        inc     e
        call    nr_map + C
        jp      main

; NextREG E = A, through the ports. Keeps everything.
nr_map: push    bc
        ld      bc,$243b
        out     (c),e
        inc     b
        out     (c),a
        pop     bc
        ret

main:   ld      hl,-C
        add     hl,sp
        ld      sp,hl
        ld      hl,$4000                ; keep bank 5's screen
        ld      de,SCRSAVE
        ld      bc,6912
        ldir
        ld      hl,desc
        ld      de,FONT
        call    menu_run
        jr      c,reset
        ld      hl,SCRSAVE
        ld      de,$4000
        ld      bc,6912
        ldir
        call    shadow                  ; .nexload's bytes below the stack, then
        ld      a,KIND_SETS
        call    apply_kind              ; sets and toggles, then trainers
        ld      a,KIND_TRAINERS
        call    apply_kind
        jp      handoff

reset:  ld      a,1                     ; BREAK: nothing to go back to
        ld      e,$02
        call    nr_map
        jr      $

; ---------------------------------------------------------------- the choices

; With the build's stack in the entry bank, what .nexload wrote just below it
; went into M0, which the writer filled there with the entry bank's own bytes:
; they go to the entry bank, so it holds what .nexload would have left.
shadow: ld      a,(P_SHADOW)
        or      a
        ret     z
        ld      a,(P_ENTRY)
        rrca
        call    map_bank
        ld      hl,(KEEP_SP)
        ld      de,-SHADOW
        add     hl,de
        ex      de,hl                   ; DE: in the entry bank, at 0xC000
        ld      hl,-C
        add     hl,de                   ; HL: the same in M0, at 0x0000
        ld      bc,SHADOW
        ldir
        ret

KIND_SETS       equ 2
KIND_TRAINERS   equ 0

; Each line chosen, of the trainers (A = 0) or of the sets and toggles (A = 2).
apply_kind:
        ld      (PASS),a
        ld      hl,desc
        call    md_set_desc
        call    md_count
        call    md_line                 ; past the last line: the offsets
        ld      (PTRS),hl
        xor     a
        ld      (LINE_I),a
.l:     ld      a,(LINE_I)
        ld      c,a
        call    md_count
        cp      c
        ret     z
        ld      a,c
        call    md_line
        ld      a,(hl)                  ; kind
        inc     hl
        ld      b,(hl)                  ; state
        ld      c,a
        ld      a,(PASS)
        or      a
        jr      nz,.sets
        ld      a,c                     ; trainers: kind 0, on
        or      a
        jr      nz,.n
        ld      a,b
        or      a
        jr      z,.n
        call    seek_line
        call    pokes
        jr      .n
.sets:  ld      a,c
        cp      2
        jr      c,.n
        ld      a,b
        or      a
        jr      z,.n
        push    bc
        call    md_fix_on
        pop     bc
        jr      z,.n
        push    bc
        call    seek_line
        pop     bc
        ld      a,c
        cp      3
        jr      z,.one
.skip:  dec     b                       ; the chosen set of the kind: past the ones before it
        jr      z,.one
        push    bc
        call    skip_runs
        pop     bc
        jr      .skip
.one:   call    runs
.n:     ld      hl,LINE_I
        inc     (hl)
        jr      .l

md_set_desc:
        ld      (MV_DESC),hl
        ret

; The reader at line LINE_I's data.
seek_line:
        ld      a,(LINE_I)
        ld      l,a
        ld      h,0
        ld      e,l
        ld      d,h
        add     hl,hl
        add     hl,de
        ld      de,(PTRS)
        add     hl,de
        ld      e,(hl)                  ; 24 bits: page offset from M1, then within it
        inc     hl
        ld      d,(hl)
        inc     hl
        ld      a,(hl)
        ld      h,d                     ; page = A:D >> 5, address = 0x8000 + (DE & 0x1FFF)
        ld      l,e
        ld      b,5
.sh:    srl     a
        rr      h
        djnz    .sh
        ld      a,(P_PAGE)
        add     a,2
        add     a,h
        ld      (DP_PAGE),a
        call    map4
        ld      a,d
        and     $1f
        or      $80
        ld      h,a
        ld      l,e
        ld      (DP_ADDR),hl
        ret

map4:   push    de
        ld      e,$54
        call    nr_map
        pop     de
        ret

; A: the next byte of the data.
rd:     push    hl
        ld      hl,(DP_ADDR)
        ld      a,(hl)
        inc     hl
        bit     5,h
        jr      z,.ok
        push    af
        ld      a,(DP_PAGE)
        inc     a
        ld      (DP_PAGE),a
        call    map4
        pop     af
        ld      hl,$8000
.ok:    ld      (DP_ADDR),hl
        pop     hl
        ret

; Bank A at 0xC000.
map_bank:
        push    de
        add     a,a
        ld      e,$56
        call    nr_map
        inc     a
        inc     e
        call    nr_map
        pop     de
        ret

; A trainer's POKEs: a count, then each bank, offset, value.
pokes:  call    rd
        ld      b,a
.p:     push    bc
        call    rd
        call    map_bank
        call    rd
        ld      l,a
        call    rd
        or      $c0
        ld      h,a
        call    rd
        ld      (hl),a
        pop     bc
        djnz    .p
        ret

; A set's chunks, as SET2 holds them decoded: a bank, a length, then the chunk,
; a bitmap of 2,048 bytes and a byte for each bit set; until a bank of 0xFF.
runs:   call    rd
        cp      $ff
        ret     z
        call    map_bank
        call    rd                      ; the length: 2,048 and the bytes, which follow
        call    rd
        ld      hl,BITBUF               ; the bitmap, where bank 5's screen was kept
        ld      bc,BITMAP_SIZE
.b:     call    rd
        ld      (hl),a
        inc     hl
        dec     bc
        ld      a,b
        or      c
        jr      nz,.b
        ld      hl,BITBUF
        ld      de,$c000
.byte:  ld      c,(hl)
        ld      b,8
.bit:   sla     c
        jr      nc,.keep
        call    rd
        ld      (de),a
.keep:  inc     de
        djnz    .bit
        inc     hl
        ld      a,h
        cp      high (BITBUF + BITMAP_SIZE)
        jr      nz,.byte
        jr      runs

; Past one set's chunks.
skip_runs:
        call    rd
        cp      $ff
        ret     z
        call    rd
        ld      c,a
        call    rd
        ld      b,a
.s:     ld      a,b
        or      c
        jr      z,skip_runs
        call    rd
        dec     bc
        jr      .s

; ---------------------------------------------------------------- the handoff

; The last 57 bytes go in M0's second page, mapped at the slot or two holding
; the 57 bytes before P; every other slot is put back as .nexload leaves it, and
; the stub jumps there. Its last instruction gives back P's own slot.
handoff:
        ld      hl,REGS
        ld      de,BLOCK
        ld      bc,20
        ldir
        ld      hl,blk_code
        ld      bc,BLOCK_LEN - 20
        ldir
        ld      hl,(P_PC)               ; start = P - 57
        ld      de,-BLOCK_LEN
        add     hl,de
        ld      (BLOCK + 21),hl         ; LD SP,start
        ld      de,(KEEP_SP)
        ld      (BLOCK + 38),de         ; LD SP,as .nexload left it
        ld      a,h                     ; lo, the slot of start; hi, of P - 1
        rlca
        rlca
        rlca
        and     7
        ld      d,a
        ld      hl,(P_PC)
        dec     hl
        ld      a,h
        rlca
        rlca
        rlca
        and     7
        ld      e,a
        ld      (LINE_I),de             ; LINE_I: hi, LINE_I + 1: lo... kept as D = lo, E = hi
        cp      d
        jr      z,.one
        ld      a,d                     ; two slots: lo first, then hi last
        add     a,$50
        ld      (BLOCK + 50),a
        ld      a,d
        call    game_page
        ld      (BLOCK + 51),a
        jr      .last
.one:   xor     a                       ; one: four NOPs where lo's would be
        ld      hl,BLOCK + 48
        ld      (hl),a
        inc     hl
        ld      (hl),a
        inc     hl
        ld      (hl),a
        inc     hl
        ld      (hl),a
.last:  ld      a,e
        add     a,$50
        ld      (BLOCK + 55),a
        ld      a,e
        call    game_page
        ld      (BLOCK + 56),a
        ld      a,(KEEP_IFF)
        or      a
        jr      z,.di
        ld      a,$fb                   ; EI
        ld      (BLOCK + 52),a
.di:    ld      de,(LINE_I)             ; M0's second page at lo and hi
        ld      a,(P_PAGE)
        inc     a
        push    de
        ld      e,d
        ld      d,a
        ld      a,e
        add     a,$50
        ld      e,a
        ld      a,d
        call    nr_map
        pop     de
        push    de
        ld      a,e
        add     a,$50
        ld      e,a
        ld      a,(P_PAGE)
        inc     a
        call    nr_map
        ld      hl,(P_PC)               ; the 57 bytes to their place
        ld      de,-BLOCK_LEN
        add     hl,de
        ex      de,hl
        ld      hl,BLOCK
        ld      bc,BLOCK_LEN
        ldir
        pop     de                      ; every slot from 2 to 7 but lo and hi
        ld      b,2
.s:     ld      a,b
        cp      d
        jr      z,.ns
        cp      e
        jr      z,.ns
        push    bc
        push    de
        call    game_page
        ld      e,b
        push    af
        ld      a,e
        add     a,$50
        ld      e,a
        pop     af
        call    nr_map
        pop     de
        pop     bc
.ns:    inc     b
        ld      a,b
        cp      8
        jr      nz,.s
        ld      hl,(P_PC)
        ld      de,-BLOCK_LEN + 20
        add     hl,de
        jp      (hl)

; A: the page slot A has when the build starts. Keeps BC, DE, HL.
game_page:
        cp      2
        jr      nc,.ram
        ld      a,$ff
        ret
.ram:   push    hl
        ld      hl,slot_pages - 2
        add     a,l
        ld      l,a
        jr      nc,.nc
        inc     h
.nc:    ld      a,(hl)
        cp      $ee                     ; the entry bank's pages
        jr      c,.got
        sub     $ee
        ld      l,a
        ld      a,(P_ENTRY)
        add     a,l
.got:   pop     hl
        ret

slot_pages:     db 10, 11, 4, 5, $ee, $ef

; The last 57 bytes after the registers: they run at P - 37.
blk_code:
        ld      sp,0                    ; start, the registers
        pop     iy
        pop     ix
        pop     hl
        pop     de
        pop     bc
        pop     af
        exx
        ex      af,af'
        pop     hl
        pop     de
        pop     bc
        pop     af
        ld      sp,0                    ; as .nexload left it
        nextreg $50,$ff
        nextreg $51,$ff
        nextreg $50,0                   ; lo's slot, or four NOPs
        nop                             ; EI if interrupts were on
        nextreg $50,0                   ; P's slot, ending at P
blk_end:
        assert  blk_end - blk_code == BLOCK_LEN - 20

        include "menu.asm"

; The parameters, filled in by the writer: the stub's last 8 bytes.
params:
P_PAGE: db      0                       ; M0's first 8K page
P_PC:   dw      0                       ; the build's start address
P_SP:   dw      0                       ; and stack pointer
P_ENTRY: db     0                       ; its entry bank's first 8K page
P_BANKS: db     0                       ; how many menu banks
P_SHADOW: db    0                       ; 1: the build's stack is in its entry bank
desc:
        assert  desc <= DESC_END
        display "stub: ", /d, desc, " bytes"

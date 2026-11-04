; SPDX-License-Identifier: GPL-3.0-or-later
; Copyright (C) 2026 NextTang contributors
;
; The .nxc menu (spec/NXC-FORMAT.md, "The menu"): one source, included by the
; .NEXCLASH dot command and by the stub of a .nex that carries its menu
; (firmware/nxcstub.asm), so that the two cannot drift. It draws a 32 x 24 ULA
; screen at 0x4000 (bank 5 must be mapped there), in a font of 96 characters
; from 32, 8 bytes each, and reads the keyboard through port 0xFE. It changes
; nothing else: no NextREG, no border, no palette. Interrupts should be off.
;
; The includer defines MENU_RAM, 13 bytes for the module's variables.
;
; The description, at HL for menu_run (spec, "The description"):
;   flags (bit 0: the main line is fixed ON), N (most sets and toggles on at
;   once), the number of lines (1 to 10); zero-terminated: the title, the
;   publisher, colours_by (empty: none), patch_by (empty: none); then each
;   line: kind (0 trainer, 1 main line, 2 a kind of set, 3 a toggle), state,
;   the number of sets (kind 2) or 0, then zero-terminated its name, its help,
;   and for kind 2 each set's name. The states are changed in place.
;
; No Z80N instruction is used, so that it runs on a plain Z80 emulator.

MV_DESC         equ MENU_RAM
MV_FONT         equ MENU_RAM + 2
MV_SEL          equ MENU_RAM + 4
MV_ROW          equ MENU_RAM + 5
MV_COL          equ MENU_RAM + 6
MV_ATTR         equ MENU_RAM + 7
MV_LINE         equ MENU_RAM + 8
MV_SECT         equ MENU_RAM + 9
MV_REC          equ MENU_RAM + 10       ; 2: the record being drawn
MV_VTYPE        equ MENU_RAM + 12

MENU_LINES_MAX  equ 10
A_TEXT          equ $47                 ; BRIGHT, paper black, ink white
A_BAR           equ $4e                 ; paper blue, ink yellow
A_HEAD          equ $46
A_ON            equ $44
A_OFF           equ $42
A_HELP          equ $45
A_SEL           equ $69                 ; paper cyan, ink blue
M_DEBOUNCE      equ 3000

; HL: the description, DE: the font. Carry on return: BREAK; otherwise ENTER or
; SPACE, with the states in the description as chosen.
menu_run:
        ld      (MV_DESC),hl
        ld      (MV_FONT),de
        xor     a
        ld      (MV_SEL),a
.draw:  call    menu_draw
.wait:  call    menu_release
.poll:  call    menu_key
        or      a
        jr      z,.poll
        cp      13
        jr      z,.go
        cp      ' '
        jr      z,.go
        cp      1
        jr      z,.brk
        cp      'U'
        jr      z,.up
        cp      'D'
        jr      z,.down
        sub     '1'                     ; '1' to '9': lines 0 to 8; '0' the tenth
        jr      nc,.d
        ld      a,9
.d:     ld      c,a
        call    md_count
        dec     a
        cp      c
        jr      c,.wait                 ; no such line
        ld      a,c
        ld      (MV_SEL),a
        call    md_act
        jr      .draw
.up:    ld      a,(MV_SEL)
        or      a
        jr      z,.wait
        dec     a
        ld      (MV_SEL),a
        jr      .draw
.down:  ld      a,(MV_SEL)
        inc     a
        ld      c,a
        call    md_count
        cp      c
        jr      z,.wait
        ld      a,c
        ld      (MV_SEL),a
        jr      .draw
.go:    call    menu_release
        or      a
        ret
.brk:   call    menu_release
        scf
        ret

; ------------------------------------------------------------- the rules

; Act on line A: a trainer or the main line turns on or off (the main line not
; if it is fixed); a kind of set steps, a toggle turns on or off, both only with
; the main line on, and from off only while fewer than N are on.
md_act: call    md_line
        ld      a,(hl)
        inc     hl                      ; at the state
        or      a
        jr      z,.flip
        dec     a
        jr      z,.fix
        push    af
        push    hl
        call    md_fix_on
        pop     hl
        pop     bc                      ; B: kind - 1
        ret     z                       ; the main line is off: nothing
        ld      a,(hl)
        or      a
        jr      nz,.on
        push    hl                      ; from off: only with room for one more
        push    bc
        call    md_on_count
        ld      c,a
        ld      hl,(MV_DESC)
        inc     hl
        ld      a,(hl)
        cp      c
        pop     bc
        pop     hl
        ret     z
        ret     c
.on:    ld      a,b
        dec     a
        jr      z,.step                 ; a kind of set
.flip:  ld      a,(hl)                  ; a trainer, a toggle
        xor     1
        ld      (hl),a
        ret
.step:  inc     hl                      ; the number of sets
        ld      a,(hl)
        dec     hl
        cp      (hl)
        jr      z,.off
        inc     (hl)
        ret
.off:   ld      (hl),0
        ret
.fix:   ld      de,(MV_DESC)
        ld      a,(de)
        rra
        ret     c                       ; fixed on
        jr      .flip

; NZ when the main line is on, or there is none.
md_fix_on:
        call    md_count
        ld      b,a
        ld      c,0
.l:     ld      a,c
        push    bc
        call    md_line
        pop     bc
        ld      a,(hl)
        cp      1
        jr      z,.found
        inc     c
        djnz    .l
        or      1
        ret
.found: inc     hl
        ld      a,(hl)
        or      a
        ret

; A: how many kinds of set and toggles are on.
md_on_count:
        call    md_count
        ld      b,a
        ld      c,0
        ld      e,0
.l:     ld      a,c
        push    bc
        push    de
        call    md_line
        pop     de
        pop     bc
        ld      a,(hl)
        cp      2
        jr      c,.n
        inc     hl
        ld      a,(hl)
        or      a
        jr      z,.n
        inc     e
.n:     inc     c
        djnz    .l
        ld      a,e
        ret

; ------------------------------------------------------------- the description

md_count:
        ld      hl,(MV_DESC)
        inc     hl
        inc     hl
        ld      a,(hl)
        ret

; HL at the zero-terminated string after the one at HL.
md_skipz:
        ld      a,(hl)
        inc     hl
        or      a
        jr      nz,md_skipz
        ret

; HL at the title.
md_strings:
        ld      hl,(MV_DESC)
        inc     hl
        inc     hl
        inc     hl
        ret

; HL at line A's record (A = the count: just past the last). Keeps DE.
md_line:
        ld      b,a
        call    md_strings
        call    md_skipz
        call    md_skipz
        call    md_skipz
        call    md_skipz
        inc     b
.l:     dec     b
        ret     z
        call    md_skip
        jr      .l

; HL at the record after the one at HL. Keeps B, DE.
md_skip:
        inc     hl
        inc     hl
        ld      c,(hl)                  ; the number of sets' names
        inc     hl
        call    md_skipz                ; name
        call    md_skipz                ; help
        inc     c
.n:     dec     c
        ret     z
        call    md_skipz
        jr      .n

; ------------------------------------------------------------- drawing

menu_draw:
        call    scr_clear
        xor     a
        call    bar
        call    md_strings              ; the publisher, ending in column 26
        call    md_skipz
        push    hl
        ld      b,16
        call    len_max
        pop     hl
        ld      b,a
        or      a
        jr      z,.no_pub
        neg
        add     a,27
        ld      c,a
        xor     a
        call    at
        push    bc
        call    puts_max
        pop     bc
.no_pub:
        ld      a,b                     ; the title: what is left, a blank before the publisher
        or      a
        ld      a,26
        jr      z,.tmax
        ld      a,25
        sub     b
.tmax:  ld      b,a
        xor     a
        ld      c,1
        call    at
        call    md_strings
        call    puts_max
        ld      a,2                     ; the lines, in their sections
        ld      (MV_ROW),a
        ld      a,$ff
        ld      (MV_SECT),a
        xor     a
        ld      (MV_LINE),a
.ln:    ld      a,(MV_LINE)
        ld      c,a
        call    md_count
        cp      c
        jr      z,.done
        ld      a,c
        call    md_line
        ld      a,(hl)
        or      a
        jr      z,.s
        ld      a,1
.s:     ld      b,a
        ld      a,(MV_SECT)
        cp      b
        jr      z,.same
        inc     a
        jr      z,.first
        ld      a,(MV_ROW)              ; a blank row between the sections
        inc     a
        ld      (MV_ROW),a
.first: ld      a,b
        ld      (MV_SECT),a
        push    hl
        ld      hl,s_trainer
        or      a
        jr      z,.h
        ld      hl,s_options
.h:     ld      a,A_HEAD
        call    row_text
        pop     hl
.same:  call    draw_line
        ld      hl,MV_ROW
        inc     (hl)
        ld      hl,MV_LINE
        inc     (hl)
        jr      .ln
.done:  ld      a,(MV_ROW)              ; a blank, the keys, a blank, the help
        inc     a
        ld      (MV_ROW),a
        ld      hl,s_enter
        ld      a,A_ON
        call    row_text
        ld      a,(MV_ROW)
        dec     a
        ld      c,13
        call    at
        ld      a,A_OFF
        ld      (MV_ATTR),a
        ld      hl,s_break
        ld      b,32
        call    puts_max
        ld      a,(MV_SEL)                  ; the help, if the line has any
        call    md_line
        inc     hl
        inc     hl
        inc     hl
        push    hl
        call    md_skipz
        ld      a,(hl)
        pop     hl
        or      a
        jr      z,.credits
        ld      a,(MV_ROW)
        inc     a
        ld      (MV_ROW),a
        ld      c,0
        call    at
        ld      a,A_HELP
        ld      (MV_ATTR),a
        ld      b,30
        call    puts_max
        ld      a,':'
        call    putc
        call    md_skipz                ; HL at the help
        ld      a,A_TEXT
        ld      (MV_ATTR),a
        ld      b,2
.help:  push    bc
        ld      a,(MV_ROW)
        inc     a
        ld      (MV_ROW),a
        ld      c,0
        call    at
        ld      b,32
        call    puts_max
        pop     bc
        djnz    .help
; The credits: colours, the patch's maker, and the bar naming Dean's engines.
.credits:
        ld      a,A_TEXT
        ld      (MV_ATTR),a
        call    md_strings
        call    md_skipz
        call    md_skipz                ; colours_by
        ld      a,(hl)
        or      a
        jr      z,.no_col
        push    hl
        ld      a,21
        ld      c,0
        call    at
        ld      hl,s_colours
        ld      b,9
        call    puts_max
        pop     hl
        ld      b,23
        call    puts_max
.no_col:
        call    md_skipz                ; patch_by
        ld      a,(hl)
        or      a
        jr      z,.no_patch
        push    hl
        ld      a,22
        ld      c,0
        call    at
        ld      hl,s_patch
        ld      b,7
        call    puts_max
        pop     hl
        ld      b,25
        call    puts_max
.no_patch:
        ld      a,23
        call    bar
        ld      a,23
        ld      c,0
        call    at
        ld      hl,s_engine
        ld      b,27
        jp      puts_max

; The line whose record is at HL, at MV_ROW: its key, its name, its value; the
; whole row cyan if it is the selected one.
draw_line:
        ld      (MV_REC),hl
        ld      a,(MV_ROW)
        ld      c,0
        call    at
        ld      a,A_TEXT
        ld      (MV_ATTR),a
        ld      a,(MV_LINE)
        add     a,'1'
        cp      '9' + 1
        jr      c,.key
        ld      a,'0'
.key:   call    putc
        call    md_value                ; A: its type; for a name HL, B
        ld      (MV_VTYPE),a
        ld      c,5
        cp      3
        jr      nz,.w
        ld      c,b
        inc     c
        inc     c
.w:     ld      a,32                    ; the value's first column
        sub     c
        push    af
        push    hl
        push    bc
        sub     2                       ; the name: from column 2 to the value
        ld      b,a
        ld      a,(MV_ROW)
        ld      c,2
        call    at
        ld      hl,(MV_REC)
        inc     hl
        inc     hl
        inc     hl
        call    puts_max
        pop     bc
        pop     hl
        pop     af
        ld      c,a
        ld      a,(MV_ROW)
        call    at
        ld      a,'['
        call    putc
        ld      a,(MV_VTYPE)
        cp      3
        jr      z,.name
        ld      hl,s_values
        add     a,a
        add     a,a
        ld      e,a
        ld      d,0
        add     hl,de
        ld      a,(hl)                  ; its colour, then 3 characters
        inc     hl
        ld      (MV_ATTR),a
        ld      b,3
        call    puts_max
        jr      .close
.name:  ld      a,A_ON
        ld      (MV_ATTR),a
        call    puts_max
.close: ld      a,A_TEXT
        ld      (MV_ATTR),a
        ld      a,']'
        call    putc
        ld      a,(MV_LINE)
        ld      hl,MV_SEL
        cp      (hl)
        ret     nz
        ld      a,(MV_ROW)
        ld      e,A_SEL
        jp      row_attr

; A: 0 OFF, 1 ON, 2 N/A, 3 a set's name (HL at it, B its length, cut to 12), for
; the record at MV_REC.
md_value:
        ld      hl,(MV_REC)
        ld      a,(hl)
        cp      2
        jr      c,.state                ; a trainer, the main line
        push    af
        call    md_fix_on
        pop     bc
        ld      a,2
        ret     z
        ld      a,b
        cp      3
        jr      z,.state
        ld      hl,(MV_REC)
        inc     hl
        inc     hl
        ld      a,(hl)                  ; one set: ON or OFF
        dec     a
        jr      z,.state
        dec     hl
        ld      a,(hl)
        or      a
        ret     z
        ld      b,a
        inc     hl
        inc     hl
        call    md_skipz                ; past the name and the help
        call    md_skipz
.k:     dec     b
        jr      z,.got
        call    md_skipz
        jr      .k
.got:   push    hl
        ld      b,12
        call    len_max
        ld      b,a
        pop     hl
        ld      a,3
        ret
.state: ld      hl,(MV_REC)
        inc     hl
        ld      a,(hl)
        or      a
        ret     z
        ld      a,1
        ret

; ------------------------------------------------------------- the screen

scr_clear:
        ld      hl,$4000
        ld      de,$4001
        ld      bc,6143
        ld      (hl),0
        ldir
        ld      a,A_TEXT
        ld      (de),a
        ld      h,d
        ld      l,e
        inc     de
        ld      bc,767
        ldir
        ret

; Row A as a bar: blue to column 27, then the four stripes.
bar:    push    af
        ld      e,A_BAR
        call    row_attr
        pop     af
        ld      c,28
        call    at
        ld      hl,s_stripes
        ld      b,4
.s:     ld      a,(hl)
        ld      (MV_ATTR),a
        inc     hl
        push    hl
        push    bc
        ld      hl,g_stripe
        call    putg
        pop     bc
        pop     hl
        djnz    .s
        ld      a,A_BAR
        ld      (MV_ATTR),a
        ret

; Row A's attributes all E.
row_attr:
        ld      c,0
        call    at
        call    attr_addr
        ld      b,32
.a:     ld      (hl),e
        inc     hl
        djnz    .a
        ret

; The text at HL, in colour A, at column 0 of MV_ROW, then the next row.
row_text:
        ld      (MV_ATTR),a
        ld      a,(MV_ROW)
        ld      c,0
        call    at
        ld      b,32
        call    puts_max
        ld      hl,MV_ROW
        inc     (hl)
        ret

; Row A, column C.
at:     ld      (MV_ROW),a
        ld      a,c
        ld      (MV_COL),a
        ret

; A: the length of the string at HL, at most B.
len_max:
        ld      c,0
.l:     ld      a,b
        or      a
        jr      z,.e
        ld      a,(hl)
        or      a
        jr      z,.e
        inc     hl
        inc     c
        dec     b
        jr      .l
.e:     ld      a,c
        ret

; Up to B characters of the string at HL; HL left at the next.
puts_max:
        ld      a,b
        or      a
        ret     z
        ld      a,(hl)
        or      a
        ret     z
        call    putc
        inc     hl
        dec     b
        jr      puts_max

; Character A at the cursor, in MV_ATTR, the cursor moved on. Anything
; unprintable is '?'. Keeps BC, DE, HL.
putc:   push    hl
        push    de
        push    bc
        cp      32
        jr      c,.q
        cp      127
        jr      c,.ok
.q:     ld      a,'?'
.ok:    sub     32
        ld      l,a
        ld      h,0
        add     hl,hl
        add     hl,hl
        add     hl,hl
        ld      de,(MV_FONT)
        add     hl,de
        call    putg
        pop     bc
        pop     de
        pop     hl
        ret

; The 8 bytes at HL at the cursor, in MV_ATTR, the cursor moved on.
putg:   ld      a,(MV_ROW)
        ld      b,a
        and     $18
        or      $40
        ld      d,a
        ld      a,b
        and     7
        rrca
        rrca
        rrca
        ld      e,a
        ld      a,(MV_COL)
        or      e
        ld      e,a
        ld      b,8
.g:     ld      a,(hl)
        ld      (de),a
        inc     hl
        inc     d
        djnz    .g
        call    attr_addr
        ld      a,(MV_ATTR)
        ld      (hl),a
        ld      hl,MV_COL
        inc     (hl)
        ret

; HL at the cursor's attribute.
attr_addr:
        ld      a,(MV_ROW)
        ld      l,a
        ld      h,0
        add     hl,hl
        add     hl,hl
        add     hl,hl
        add     hl,hl
        add     hl,hl
        ld      a,(MV_COL)
        add     a,l
        ld      l,a
        ld      a,h
        add     a,$58
        ld      h,a
        ret

; ------------------------------------------------------------- the keyboard

; Until no key is down, steadily.
menu_release:
.again: ld      hl,M_DEBOUNCE
.loop:  ld      bc,$00fe
        in      a,(c)
        and     $1f
        cp      $1f
        jr      nz,.again
        dec     hl
        ld      a,h
        or      l
        jr      nz,.loop
        ret

; A: 0 none, 13 ENTER, ' ' SPACE, 1 BREAK, 'D' and 'U' for CAPS SHIFT with 6
; and 7, or '0' to '9'.
menu_key:
        ld      bc,$bffe
        in      a,(c)
        rra
        ld      a,13
        ret     nc
        ld      bc,$fefe
        in      a,(c)
        rra
        jr      nc,.caps
        ld      bc,$7ffe
        in      a,(c)
        rra
        ld      a,' '
        ret     nc
        ld      bc,$f7fe                ; 1 to 5: bits 0 to 4
        in      a,(c)
        ld      e,'1'
        ld      b,5
.left:  rra
        jr      nc,.found
        inc     e
        djnz    .left
        ld      bc,$effe                ; 6 to 9: bits 4 to 1; 0: bit 0
        in      a,(c)
        ld      e,'6'
        ld      b,4
.right: bit     4,a
        jr      z,.found
        add     a,a
        inc     e
        djnz    .right
        bit     4,a
        ld      e,'0'
        jr      z,.found
        xor     a
        ret
.found: ld      a,e
        ret
.caps:  ld      bc,$7ffe
        in      a,(c)
        rra
        ld      a,1
        ret     nc
        ld      bc,$effe
        in      a,(c)
        bit     4,a
        ld      a,'D'
        ret     z
        in      a,(c)
        bit     3,a
        ld      a,'U'
        ret     z
        xor     a
        ret

s_trainer:      db "TRAINER",0
s_options:      db "OPTIONS",0
s_enter:        db "ENTER play",0
s_break:        db "BREAK exit",0
s_colours:      db "Colours: "
s_patch:        db "Patch: "
s_engine:       db " Engine: Dean Woodyatt",0
s_values:       db A_OFF,"OFF",A_ON," ON",A_TEXT,"N/A"
s_stripes:      db $4a,$56,$74,$65      ; blue|red, red|yellow, yellow|green, green|cyan
g_stripe:       db $01,$03,$07,$0f,$1f,$3f,$7f,$ff

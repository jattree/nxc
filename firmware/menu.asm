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
; The includer defines MENU_RAM, 13 bytes for the module's variables, or
; MENU_RAM_SIZE with MENU_RULES defined: the menu that keeps to a patch's option
; rules (OPR1). Without MENU_RULES this assembles to exactly the menu before
; rules, which a .nex for a patch without OPR1 still carries, byte for byte.
;
; The description, at HL for menu_run (spec, "The description"):
;   flags (bit 0: the main line is fixed ON; bit 1: a version follows patch_by),
;   N (most sets and toggles on at once), the number of lines (1 to 10);
;   zero-terminated: the title, the publisher, colours_by (empty: none),
;   patch_by (empty: none), and with flags bit 1 the version; then each
;   line: kind (0 trainer, 1 main line, 2 a kind of set, 3 a toggle), state,
;   the number of sets (kind 2) or 0, then zero-terminated its name, its help,
;   and for kind 2 each set's name. The states are changed in place. Then
;   3 bytes for each line, the writer's; and with flags bit 2 (MENU_RULES only)
;   the rules: their count, then each one's type (1 excludes, 2 needs), line A,
;   the state that is A on, line B, the state that is B on.
; With MENU_LANG, flags bit 3: each kind of set's line has one more string after
;   its sets' names, its value with no set chosen, such as the game's own
;   language; with one, the line names the chosen set even when it has only one
;   (spec, "The menu"). Empty: [OFF] and [ ON] as before.
; With MENU_NEEDS (the dot command's own menu only, never a stub), a kind of set
; with no sets is an option the machine has too little memory for: it reads N/A,
; and its key changes nothing.
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
        ifdef MENU_RULES
MV_KEPT         equ MENU_RAM + 13       ; 2: a bit for each line a key's rules may not change
MV_ALSO         equ MENU_RAM + 15       ; 2: the lines the rules changed, each its number + 1, bit 7 on
MV_CHG          equ MENU_RAM + 17       ; a pass changed a line
MENU_RAM_SIZE   equ 18
MD_RULES        equ 2                   ; the flags' bit: rules follow the lines' offsets
        else
MENU_RAM_SIZE   equ 13
        endif

MENU_LINES_MAX  equ 10
MENU_TITLE_ROW  equ 27                  ; a title's characters in a bar row, before the stripes
MENU_HELP_ROW   equ 17                  ; the help's first row, at the latest, so that it ends by row 19
MENU_COLOURS    equ 20                  ; the credit rows: Colours:, then Patch:
MENU_PATCH      equ 21
MENU_FOOTER     equ 22                  ; the fixed footer, two bars, which no patch can change
MENU_VERSION    equ 8                   ; a version's characters, after its v
MD_VERSION      equ 1                   ; the flags' bit: a version follows patch_by
        ifdef MENU_LANG
MD_LANG         equ 3                   ; the flags' bit: a kind of set's line has a name for no set chosen
        endif
A_TEXT          equ $47                 ; BRIGHT, paper black, ink white
A_BAR           equ $4e                 ; paper blue, ink yellow
A_HEAD          equ $46
A_ON            equ $44
A_OFF           equ $42
A_HELP          equ $45
A_CYAN          equ $68                 ; BRIGHT, paper cyan: the footer's last cell
M_DEBOUNCE      equ 3000

; HL: the description, DE: the font. Carry on return: BREAK; otherwise A is 0
; for ENTER and not 0 for SPACE, with the states in the description as chosen.
menu_run:
        ld      (MV_DESC),hl
        ld      (MV_FONT),de
        xor     a
        ld      (MV_SEL),a
        ifdef MENU_RULES
        ld      (MV_ALSO),a
        ld      (MV_ALSO+1),a
        endif
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
        ifdef MENU_RULES
        call    md_rules
        endif
        jr      .draw
.go:    sub     13                      ; A: 0 ENTER, not 0 SPACE
        push    af
        call    menu_release
        pop     af
        or      a                       ; carry clear
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

        ifdef MENU_RULES
; After line MV_SEL's key: with rules, lines are changed until every rule is kept,
; never the keyed line or one already changed (MV_KEPT), so each at most once.
; Excludes, both on: B off, or A if B is kept. Needs, A on and B not: B on, or A
; off if B is kept. A rule that can be kept no other way turns every set and toggle off,
; which keeps them all; a writer makes sure that never happens. tools/nxc.py
; menu_settle is the same.
md_rules:
        xor     a
        ld      (MV_ALSO),a
        ld      (MV_ALSO+1),a
        ld      hl,(MV_DESC)
        bit     MD_RULES,(hl)
        ret     z
        ld      a,(MV_SEL)
        call    md_line
        ld      a,(hl)
        cp      2
        ret     c                       ; a trainer, the main line
        ld      a,(MV_SEL)
        call    md_bit
        ld      (MV_KEPT),hl
.pass:  xor     a
        ld      (MV_CHG),a
        call    md_count                ; the rules, after the lines' 3 bytes each
        push    af
        call    md_line
        pop     af
        ld      c,a
        add     a,a
        add     a,c
        ld      c,a
        ld      b,0
        add     hl,bc
        ld      b,(hl)
        inc     b
.r:     inc     hl
        dec     b
        jr      z,.end
        push    bc
        push    hl
        call    md_rule
        pop     hl
        pop     bc
        jr      c,.fail
        inc     hl
        inc     hl
        inc     hl
        inc     hl
        jr      .r
.end:   ld      a,(MV_CHG)
        or      a
        jr      nz,.pass
        ret
.fail:  call    md_count
        ld      b,a
        ld      c,0
.f:     ld      a,c
        push    bc
        call    md_line
        pop     bc
        ld      a,(hl)
        cp      2
        jr      c,.fn
        inc     hl
        ld      (hl),0
.fn:    inc     c
        djnz    .f
        xor     a
        ld      (MV_ALSO),a
        ld      (MV_ALSO+1),a
        ret

; The rule at HL, kept. Carry: it cannot be.
md_rule:
        push    hl
        pop     ix
        ld      a,(ix+3)
        call    md_state
        ld      a,(ix+4)
        sub     (hl)
        ld      e,a                     ; 0: B on
        ld      a,(ix+1)
        call    md_state
        ld      a,(ix+2)
        sub     (hl)
        jr      nz,.ok                  ; A off: it holds
        ld      a,(ix+0)
        dec     a
        ld      a,e
        jr      nz,.needs
        or      a                       ; excludes, B off: it holds
        ret     nz
        ld      a,(ix+3)
        call    md_kept
        ld      a,(ix+3)
        jr      z,md_off
        ld      a,(ix+1)
        call    md_kept
        ld      a,(ix+1)
        jr      z,md_off
        scf
        ret
.needs: or      a                       ; B on: it holds
        ret     z
        ld      a,(ix+3)
        call    md_kept
        jr      z,.on
        ld      a,(ix+1)
        call    md_kept
        scf
        ret     nz                      ; A kept too: it cannot
        ld      a,(ix+1)
        jr      md_off
.on:    ld      a,(ix+3)
        ld      c,(ix+4)
        jr      md_on
.ok:    or      a
        ret

; HL at line A's state.
md_state:
        call    md_line
        inc     hl
        ret

; HL = 1 << A.
md_bit: ld      hl,1
        or      a
        ret     z
.s:     add     hl,hl
        dec     a
        jr      nz,.s
        ret

; NZ when line A is kept.
md_kept:
        call    md_bit
        ld      a,(MV_KEPT)
        and     l
        ld      l,a
        ld      a,(MV_KEPT+1)
        and     h
        or      l
        ret

; Line A off; line A to state C: kept, and noted for the help rows. Carry clear.
md_off: ld      c,0
md_on:  push    af
        push    bc
        call    md_state
        pop     bc
        ld      (hl),c
        pop     af
        push    af
        call    md_bit
        ld      a,(MV_KEPT)
        or      l
        ld      (MV_KEPT),a
        ld      a,(MV_KEPT+1)
        or      h
        ld      (MV_KEPT+1),a
        pop     af
        inc     c
        dec     c
        jr      z,md_note
        ld      c,$80
md_note:
        ld      b,a
        ld      a,1
        ld      (MV_CHG),a
        inc     b                       ; the line's number + 1
        ld      a,b
        or      c
        ld      c,a
        ld      hl,MV_ALSO
        ld      e,2
.n:     ld      a,(hl)
        and     $7f
        jr      z,.put
        cp      b
        jr      z,.put
        inc     hl
        dec     e
        jr      nz,.n
        jr      .done
.put:   ld      (hl),c
.done:  or      a
        ret
        endif

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
        push    hl
        ld      hl,(MV_DESC)
        bit     MD_VERSION,(hl)
        pop     hl
        call    nz,md_skipz             ; the version
        inc     b
.l:     dec     b
        ret     z
        call    md_skip
        jr      .l

; HL at the record after the one at HL. Keeps B, DE.
md_skip:
        ifdef MENU_LANG
        ld      a,(hl)                  ; the kind
        endif
        inc     hl
        inc     hl
        ld      c,(hl)                  ; the number of sets' names
        inc     hl
        ifdef MENU_LANG
        cp      2
        jr      nz,.nl
        push    hl
        ld      hl,(MV_DESC)
        bit     MD_LANG,(hl)
        pop     hl
        jr      z,.nl
        inc     c                       ; and its name for no set chosen
.nl:
        endif
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
        call    md_strings              ; the title, never cut: one bar row, or two
        ld      b,MENU_TITLE_ROW + 1
        push    hl
        call    len_max
        pop     hl
        ld      e,a                     ; E: the first row's characters
        cp      MENU_TITLE_ROW + 1
        jr      c,.one_row
        ld      e,MENU_TITLE_ROW        ; longer: up to the last space that fits
        ld      d,e
        push    hl
.sp:    ld      a,e
        or      a
        jr      z,.hard
        push    hl
        ld      c,e
        ld      b,0
        add     hl,bc
        ld      a,(hl)
        pop     hl
        cp      ' '
        jr      z,.split
        dec     e
        jr      .sp
.hard:  ld      e,d                     ; no space: 27 then the rest
.split: pop     hl
.one_row:
        push    hl
        push    de
        xor     a
        call    bar
        pop     de
        pop     hl
        xor     a
        ld      c,1
        call    at
        ld      b,e
        call    puts_max                ; HL: the rest, at a space or the end
        ld      a,(hl)
        cp      ' '
        jr      nz,.no_sp
        inc     hl
.no_sp: ld      a,(hl)
        ld      b,1                     ; the publisher's row
        or      a
        jr      z,.pub
        push    hl
        ld      a,1
        call    bar
        pop     hl
        ld      a,1
        ld      c,1
        call    at
        ld      b,MENU_TITLE_ROW
        call    puts_max
        ld      b,2
.pub:   ld      a,b                     ; the publisher, in white, below the bar
        push    af
        call    md_strings
        call    md_skipz
        push    hl
        ld      b,32
        call    len_max
        pop     hl
        ld      b,a
        ld      c,1                     ; from column 1, or 0 if it needs all 32
        cp      32
        jr      c,.pc
        dec     c
.pc:    pop     af
        push    af
        call    at
        ld      a,A_TEXT
        ld      (MV_ATTR),a
        call    puts_max
        pop     af
        inc     a                       ; then a blank row, but for a title of two rows
        cp      3
        jr      z,.lines
        inc     a
.lines: ld      (MV_ROW),a
        ld      a,$ff                   ; the lines, in their sections
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
.done:  ld      a,(MV_ROW)              ; a blank, the keys, a blank, the help; the first blank is
        cp      MENU_HELP_ROW - 1       ; left out only when the keys would then pass row 16, so
        jr      nc,.keys                ; that the help still ends by row 19 (ten lines, both sections)
        inc     a
.keys:  ld      (MV_ROW),a
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
        ifdef MENU_RULES
        ld      bc,(MV_ALSO)            ; or lines the rules changed
        or      c
        endif
        or      a
        ifdef MENU_RULES
        jp      z,.credits
        else
        jr      z,.credits
        endif
        ld      a,(MV_ROW)                  ; still the keys' row: a blank after it,
        add     a,2                         ; unless the help would then pass row 19
        cp      MENU_HELP_ROW + 1
        jr      c,.hr
        ld      a,MENU_HELP_ROW
.hr:    ld      (MV_ROW),a
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
        ifdef MENU_RULES
        ld      a,(MV_ALSO)             ; the rules changed lines: they, not the help
        or      a
        jr      z,.plain
        ld      hl,MV_ALSO
        ld      b,2
.also:  push    bc
        push    hl
        ld      a,(MV_ROW)
        inc     a
        ld      (MV_ROW),a
        ld      c,0
        call    at
        pop     hl
        push    hl
        ld      a,(hl)
        and     $7f
        jr      z,.an
        dec     a
        push    af
        ld      a,(hl)
        ld      hl,s_also_on
        rla
        jr      c,.ao
        ld      hl,s_also_off
.ao:    ld      b,10
        call    puts_max
        pop     af
        call    md_line
        inc     hl
        inc     hl
        inc     hl
        ld      b,22
        call    puts_max
.an:    pop     hl
        inc     hl
        pop     bc
        djnz    .also
        jr      .credits
.plain:
        endif
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
; The credits: colours and the patch's maker, then the fixed footer.
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
        ld      a,MENU_COLOURS
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
        push    hl
        call    md_skipz                ; the version, if the flags say so, ending in column 31
        ld      de,(MV_DESC)
        ld      a,(de)
        and     1 << MD_VERSION
        jr      z,.no_ver
        push    hl
        ld      b,MENU_VERSION
        call    len_max
        pop     hl
.no_ver:
        ld      e,a                     ; E: its length, 0 for none
        or      a
        ld      a,25                    ; patch_by: cut to 25 without one
        jr      z,.pby
        ld      a,31                    ; the v in column 31 - E
        sub     e
        ld      c,a
        ld      a,MENU_PATCH
        call    at
        ld      a,'v'
        call    putc
        ld      b,e
        call    puts_max
        ld      a,23                    ; with one: cut to 23 - E, a blank column before the v
        sub     e
.pby:   pop     hl
        ld      b,a
        ld      a,(hl)
        or      a
        jr      z,.no_patch
        push    hl
        push    bc
        ld      a,MENU_PATCH
        ld      c,0
        call    at
        ld      hl,s_patch
        ld      b,7
        call    puts_max
        pop     bc
        pop     hl
        call    puts_max
.no_patch:
; The footer, the same on every patch's menu, from nothing in the patch: two bars, their stripes
; one Spectrum band running down through both, crediting the format and the engine.
        ld      a,MENU_FOOTER
        call    bar
        ld      a,MENU_FOOTER
        ld      c,0
        call    at
        ld      hl,s_by
        ld      b,MENU_TITLE_ROW
        call    puts_max
        ld      a,MENU_FOOTER + 1
        call    bar_lo
        ld      c,0
        call    at
        ld      hl,s_engine
        ld      b,MENU_TITLE_ROW - 1
        jp      puts_max

; The line whose record is at HL, at MV_ROW: its key, its name, its value; the
; keys are its number only, so no line is highlighted.
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
        ifdef MENU_LANG
        jr      c,.w                    ; 3 and 4 are names
        else
        jr      nz,.w
        endif
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
        ifdef MENU_LANG
        jr      nc,.own
        endif
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
        ifdef MENU_LANG
        jr      .nm
.own:   ld      a,A_OFF                 ; the game's own language: no set chosen
.nm:
        endif
        ld      (MV_ATTR),a
        call    puts_max
.close: ld      a,A_TEXT
        ld      (MV_ATTR),a
        ld      a,']'
        jp      putc

; A: 0 OFF, 1 ON, 2 N/A, 3 a set's name (HL at it, B its length, cut to 12), for
; the record at MV_REC; with MENU_LANG, 4 the line's name for no set chosen, the
; same way.
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
        ifdef MENU_NEEDS
        or      a                       ; no set at all: an option the machine has too little
        ld      a,2                     ; memory for (a SET3), N/A; its key steps through none
        ret     z
        ld      a,(hl)
        endif
        ifdef MENU_LANG
        call    md_own                  ; a name for no set chosen: names, even with one set
        jr      nz,.own
        ld      a,(hl)
        endif
        dec     a
        jr      z,.state
        dec     hl
        ld      a,(hl)
        or      a
        ret     z
.pick:  ld      b,a
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
        ifdef MENU_LANG
.own:   dec     hl                      ; the state
        ld      a,(hl)
        or      a
        jr      nz,.pick                ; a set chosen: its name
        ex      de,hl
        push    hl
        ld      b,12
        call    len_max
        ld      b,a
        pop     hl
        ld      a,4
        ret
        endif
.state: ld      hl,(MV_REC)
        inc     hl
        ld      a,(hl)
        or      a
        ret     z
        ld      a,1
        ret

        ifdef MENU_LANG
; NZ, with DE at it, when the kind of set's line at MV_REC has a name for no set
; chosen (the flags' bit 3, and not empty). Keeps HL.
md_own: push    hl
        ld      hl,(MV_DESC)
        bit     MD_LANG,(hl)
        jr      z,.no
        ld      hl,(MV_REC)
        inc     hl
        inc     hl
        ld      b,(hl)                  ; the number of sets
        inc     hl
        call    md_skipz                ; past the name and the help
        call    md_skipz
        inc     b
.s:     dec     b
        jr      z,.at
        call    md_skipz
        jr      .s
.at:    ld      a,(hl)
        ex      de,hl
        or      a
.no:    pop     hl
        ret
        endif

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
bar:    ld      c,28
; Row A as a bar, the stripes from column C.
bar_at: push    bc
        push    af
        ld      e,A_BAR
        call    row_attr
        pop     af
        pop     bc
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

; Row A as the footer's lower bar: its stripes a column to the left, from 27 to 30, so that each runs
; on from the one above it, and column 31 BRIGHT cyan, blank. Keeps A.
bar_lo: push    af
        ld      c,27
        call    bar_at
        ld      a,A_CYAN
        ld      (MV_ATTR),a
        ld      hl,g_blank
        call    putg
        ld      a,A_BAR
        ld      (MV_ATTR),a
        pop     af
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

; A: 0 none, 13 ENTER, ' ' SPACE, 1 BREAK (CAPS SHIFT with SPACE), or '0' to '9'.
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
        xor     a
        ret

s_trainer:      db "TRAINER",0
s_options:      db "OPTIONS",0
s_enter:        db "ENTER play",0
s_break:        db "BREAK exit",0
s_colours:      db "Colours: "
s_patch:        db "Patch: "
s_values:       db A_OFF,"OFF",A_ON," ON",A_TEXT,"N/A"
        ifdef MENU_RULES
s_also_on:      db "Also on: ",0
s_also_off:     db "Also off: ",0
        endif
s_stripes:      db $4a,$56,$74,$65      ; blue|red, red|yellow, yellow|green, green|cyan
g_stripe:       db $01,$03,$07,$0f,$1f,$3f,$7f,$ff
g_blank:        db 0,0,0,0,0,0,0,0
s_by:           db " .nxc by Jon Attree",0       ; the footer: fixed, never from a patch
s_engine:       db " Engine: Dean Woodyatt",0

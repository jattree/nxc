; SPDX-License-Identifier: GPL-3.0-or-later
; Copyright (C) 2026 NextTang contributors
;
; .NEXCLASH "GAME.nxc" - rebuild a NexClash .nex from a patch and the
; player's own copy of the game, with a menu for trainers, the colour clash fix
; and the patch's sets, one choice of each kind.
; See spec/NXC-FORMAT.md; tools/nxc.py is the reference this matches byte
; for byte. The format comes from Dean Woodyatt's NexClash (bleughb/nexclash,
; GPL-3.0-or-later). The structure of this command follows our .SPEC256; its
; ZX0 decoder is derived from dzx0_standard by Einar Saukas and Urusergi
; (BSD-3-Clause, https://github.com/einar-saukas/ZX0), rewritten to read from a
; file through the key stream and to check every copy against its buffers.
;
; NexClash chosen: the game is absorbed into a key state once, each target entry
; of its length tried from a copy of that state for the master key, the patch's
; keyed check made over the whole file, all before anything is decompressed. The
; .z80 is decoded a bank at a time, SIT1 and the trainers applied, and the header
; and banks written in .nex order as /tmp/NEXCLASH.NEX, whose CRC and length must
; match OUT1 or it is deleted. %X is left as 1.
;
; Sets chosen (SET2, at most one of each kind): as above, with each applied to each
; bank, the CRC run over the result, the POKEs after that. A set is held a bank at a
; time, so its size is not limited by memory: every chunk is decoded and checked once
; before any file is made, then again as its bank is written. As sets chosen together
; touch different bytes, the CRC that result must have comes from OUT1's and theirs.
; It and the length must match, or the file is deleted.
;
; Clash fix off: the game is copied unchanged to /tmp/NEXCLASH.Z80. With a
; trainer on, the key and check are made as above and the file is written as
; a .z80 with whole pages and the POKEs in place. %X is left as 2.
;
; A dot command cannot run another, so a line in browser.cfg starts the result
; according to %X. See firmware/README.md for the line, and what is assumed.
; A patch is named .nxc: NextZXOS's Browser goes by the 8.3 short name, so a longer
; extension such as .nexclash would be ~1.NEX to it, and go to .nexload.
;
; The file is longer than 8K, which NextZXOS allows: it loads the first 8K at
; $2000 and leaves the file open just after it. That first part is the resident
; code, then all that is only used up to the menu. After the menu the rest is read
; through M_GETHANDLE over the menu's code, so only the resident part and the overlay
; are there from then on. Nothing else is needed on the card.
;
; Memory. Up to the menu this runs on the caller's stack with the caller's
; paging, as RST $10 needs. After it, with interrupts off, it moves its stack
; into its own 8K and pages six allocated 8K pages in at 0x6000-0xBFFF, so
; never touching MMU6 and MMU7 (NextZXOS's own calls page there):
;
;   0x6000-0x9FFF  WORK: the bank being built, 16K (two pages)
;   0xA000-0xBFFF  IOPAGE: header, POKEs, bank index, CRC tables, file buffer
;                  (one page), or one of the pages of a table
;
; SIT1, and each chunk of each chosen SET2, are decoded with their three pages each
; at 0x6000-0xBFFF, reading through the small buffer in the 8K. A set's three pages
; hold one chunk at a time, and are allocated only when it is chosen. All addresses
; given to NextZXOS lie below 0xC000.
;
; No Z80N-only instruction is used, so that it runs on a plain Z80 emulator in
; tests/test_nexclash_dot.py; NextREGs are written through their ports.

        opt     --zxnext
        org     $2000

M_DOSVERSION    equ $88
M_GETHANDLE     equ $8d
M_P3DOS         equ $94
F_OPEN          equ $9a
F_CLOSE         equ $9b
F_READ          equ $9d
F_WRITE         equ $9e
F_SEEK          equ $9f
F_FSTAT         equ $a1
F_GETCWD        equ $a8
F_UNLINK        equ $ad
FA_READ         equ $01
FA_CREATE       equ $0e                     ; write, create or truncate

IDE_BANK        equ $01bd
IDE_INTEGER_VAR equ $01c9
IDE_MODE        equ $01d5
BANK_ALLOC      equ $0001                   ; ZX memory, allocate
BANK_FREE       equ $0003                   ; ZX memory, free E

NR_SELECT       equ $243b
NR_ACCESS       equ $253b
NR_SPEED        equ $07
NR_MMU3         equ $53
NR_MMU4         equ $54
NR_MMU5         equ $55

LOADER_LEVEL    equ 2                       ; 1: .z80; 2: and a loading screen; 3 adds .sna only
KIND_Z80        equ 1                       ; the one container this loader reads
TARGETS_MAX     equ 32
FILE_NAME_MAX   equ 127
KEY_ROUNDS      equ 16
FILE_HEADER     equ 38
TARGET_FIXED    equ 30
BANK_SIZE       equ 16384
PAGES           equ 6
SET_PAGES       equ 3                       ; more, for each set chosen
KINDS           equ 2                       ; colours, language
SET_FIXED       equ 5                       ; stream index, kind, choice, base, name's length
SET_CRC_INDEX   equ 255                     ; the stream of a set's CRC; a chunk's is its bank
BITMAP          equ 2048                    ; a chunk's first part: one bit for each byte of a bank
REC             equ 9                       ; a chosen set's cursor: position 4, left 4, stream 1
BASE_SPRITE     equ 1                       ; the sprite build: the one base a set here may have
CREDIT_NAME     equ 32                      ; of a name, as "Colours: " leaves 32
TRAINERS_SHOWN  equ 8
TRAINER_SIZE    equ 7                       ; on, name's length, count, position
POKES_HELD      equ 128
HANDOFF_VAR     equ 'X' - 'A'
DEBOUNCE        equ 3000

; Allocated memory, while mapped.
WORK            equ $6000
WORK_END        equ $A000
TABLE_END       equ $C000
HDR             equ $A000                   ; 512: the .nex header, or the .z80's
POKES           equ $A200                   ; POKES_HELD x 4
BANK_INDEX      equ $A400                   ; 112 x (position 4, length 4, plain 2)
; Variables used only with the I/O page mapped, none of them once the .nex is
; being written, so that the 8K holds the code. Cleared with the index up to here:
game_pages      equ $A860                   ; 8 x 6: per bank: position 4, length 2;
                                            ; length 0: none
z80_128         equ $A890
z80_v1          equ $A891
z80_packed      equ $A892
poke_mode       equ $A893
poke_count      equ $A894
z80_head_len    equ $A895                   ; 2
sit_len         equ $A897                   ; 2: each table's length, 0: none
IO_CLEAR_END    equ $A89B
v1_end          equ $A89C                   ; 4
head            equ $A8A0                   ; the .z80's first 32 bytes
tgt_buf         equ $A8C0                   ; a target entry: index, kind, length, wrap: 30
tgt_key         equ tgt_buf + 6 + 8         ; the master key, unwrapped: 16
check_buf       equ $A8E0                   ; the check field: 16
out_buf         equ $A8F0                   ; OUT1, decrypted: CRC, length: 8
CRC_T0          equ $AC00                   ; four 256-byte tables, one per byte
IOBUF           equ $B000                   ; 4096, ending on a page
IOBUF_END_HI    equ $C0
IOBUF_SIZE      equ $1000

; Fixed memory at the top of the 8K, not part of what the code may use.
PATH_SIZE       equ 224
smallbuf        equ $3E00                   ; 256, ending on a page
SMALLBUF_END_HI equ $3F
SMALLBUF_SIZE   equ $0100
TEXT_MAX        equ 252
stack_top       equ $4000
stack_floor     equ $3F40                   ; 192 of stack
rc4_s           equ $3D00                   ; aligned
statbuf         equ smallbuf                ; read at once, and nothing else is there
rc4_base        equ $AA00                   ; in the I/O page

; Variables, downwards from the key state, cleared at the start.
        macro   VAR vname, vsize
vname   equ     var_at
var_at  =       var_at + vsize
        endm
vars            equ $3A4F
var_at          =   vars
        VAR     patch_path, PATH_SIZE
game_b          equ patch_path              ; once open, its extension becomes .z80
        VAR     game_a, PATH_SIZE
        VAR     trainer_table, TRAINERS_SHOWN * TRAINER_SIZE
        VAR     entry_sp, 2
        VAR     interrupts, 1
        VAR     speed, 1                    ; bit 7: saved
        VAR     mmu3, 1                     ; three in a row, as page_list starts
        VAR     mmu4, 1
        VAR     mmu5, 1
        VAR     mapped, 1
        VAR     page_count, 1
        VAR     page_list, PAGES + KINDS * SET_PAGES ; WORK x 2, I/O, sites x 3, each set x 3
        VAR     ph, 1                       ; handles; 0: not open
        VAR     gh, 1
        VAR     oh, 1
        VAR     oh_done, 1                  ; the output is complete and checked
        VAR     out_name, 2                 ; set only once the output exists
        VAR     msg_ptr, 2
        VAR     need_name, 1                ; print TGT1's file with the error
        VAR     game_which, 1               ; the next name to try: targets, then the patch's own
        VAR     seen_wrong, 1               ; a file was there, and was not the game
        VAR     target_count, 1
        VAR     target_kinds, 1             ; not 0 if a target is one this loader reads
        VAR     scan_pos, 4                 ; where the search for a game has got to; 0: start
        VAR     open_path, 2
        VAR     handoff, 1
        VAR     game_a_file, 2              ; TGT1's file name within game_a
        VAR     trainer_count, 1
        VAR     ver_original, 1             ; the clash fix is off
        VAR     set_counts, KINDS           ; how many sets each kind offers
        VAR     set_choices, KINDS          ; 0: off; n: its nth
        VAR     set_bases, 2 * KINDS        ; the pages in page_list of each chosen; 0: none
        VAR     set_lens, 2 * KINDS         ; the length of each one's chunk for this bank; 0: none
        VAR     set_recs, REC * KINDS       ; each one's next chunk
        VAR     set_crc_too, 1
        VAR     set_tag, 4                  ; a set's streams: "SEB", then its stream index
        VAR     mode_changed, 1
        VAR     mode_old_layer, 1
        VAR     mode_old_sub, 1
        VAR     mode_old_width, 1
        VAR     out_rec, 8                  ; position, length of OUT1
        VAR     nex_rec, 8                  ; of NEX1
        VAR     sit_rec, 8                  ; and of SIT1
        VAR     src_chunk, 2
        VAR     src_left, 4
        VAR     src_handle, 1
        VAR     src_crypt, 1
        VAR     src_bad, 2                  ; message when the source runs out
        VAR     s_i, 1
        VAR     s_j, 1
        VAR     crc, 4
        VAR     want, 8                     ; the CRC and length the output must have
        VAR     out_len, 4
        VAR     zx_start, 2
        VAR     zx_end, 2
        VAR     zx_last, 2
        VAR     t_len, 2                    ; the table being walked: its length,
        VAR     t_base, 2                   ; and its pages in page_list
        VAR     t_off, 2
        VAR     t_count, 2
        VAR     t_page, 1
        VAR     t_room, 2
        VAR     cur_site, 1
        VAR     site_bank, 1
        VAR     site_off, 2
        VAR     site_len, 2
        VAR     unpack_stop, 1
        VAR     cur_bank, 1
        VAR     v1_pos, 4
        VAR     run_n, 1
        VAR     run_v, 1
        VAR     scr_left, 4                 ; what is left of the screen
        VAR     scr_chunks, 1
        VAR     scr_mask, 1
        VAR     scr_now, 1
        VAR     cur_kind, 1
        VAR     ram_bank, 1                 ; OPT1's highest 16K bank
        VAR     page_goal, 1
        VAR     next_base, 2
        VAR     a_off, 2
        VAR     b_off, 2
        VAR     cur_n, 1
        VAR     cur_stream, 1
        display "variables end ", /h, var_at
        assert  var_at == rc4_s, "the variables must end where the key state starts"
; Only up to the menu, or scratch until a key state is made, so these can lie in it.
        VAR     title, 24
        VAR     publisher, 17
        VAR     seen, 5                     ; how many of each required block
        VAR     text_len, 2
        VAR     col, 1
        VAR     patch_by, CREDIT_NAME + 1
        VAR     colours_by, CREDIT_NAME + 1
        VAR     pal_seen, 32                ; a bit per colour-set index
        VAR     opt_level, 1
        VAR     cur_line, 1
        VAR     cur_name, 1
        VAR     scr_seen, 1
vars_end        equ var_at
; These need no clearing, and lie below the stack.
var_at          =   $3F00
        VAR     psize, 4
        VAR     gsize, 4
        VAR     pos, 4
        VAR     blk_pos, 4
        VAR     blk_len, 4                  ; must follow blk_pos
        VAR     left, 4
        VAR     work32, 4
        VAR     tagbuf, 8
        VAR     nonce, 16
        VAR     tmp5, 5
        VAR     src_end_hi, 1
        VAR     base_i, 1
        VAR     base_j, 1
        assert  var_at <= stack_floor, "the variables run into the stack"

; ================================================================= resident

start:  jp      start_menu                  ; all up to the menu is read over later
after_menu:
        call    load_overlay
        jp      chosen

; The rest of this command, over the code that is only used up to the menu. The
; file must be there as the first part expects, or nothing can follow.
load_overlay:
        rst     $08
        db      M_GETHANDLE
        ld      hl,msg_overlay
        jp      c,fail_hl
        ld      hl,ov_start
        ld      bc,ov_size
        rst     $08
        db      F_READ
        ld      hl,msg_overlay
        jp      c,fail_hl
        ld      a,b
        cp      high ov_size
        jp      nz,fail_hl
        ld      a,c
        cp      low ov_size
        jp      nz,fail_hl
        ld      hl,ov_tag
        ld      de,ov_tag_want
        call    same_tag
        ld      hl,msg_overlay
        jp      nz,fail_hl
        ret

; ------------------------------------------------------------------ reading

; Carry when the 32 bits at HL are below BC:DE.
below32:
        ld      a,(hl)
        sub     e
        inc     hl
        ld      a,(hl)
        sbc     a,d
        inc     hl
        ld      a,(hl)
        sbc     a,c
        inc     hl
        ld      a,(hl)
        sbc     a,b
        ret

; Start a walk over the blocks.
walk_begin:
        ld      hl,FILE_HEADER
        ld      (pos),hl
        ld      hl,0
        ld      (pos+2),hl
        ret

; The next block's tag and length into tagbuf, its place into blk_pos and
; blk_len, the file at its data. Z at the end of the file. Anything that does
; not fit in the file is damage.
walk_next:
        ld      hl,psize
        ld      de,left
        call    copy4
        ld      hl,left
        ld      de,pos
        call    sub32
        ld      hl,left
        call    is_zero32
        ret     z
        ld      hl,left                     ; a tag and a length, at least
        ld      de,eight
        call    sub32
        jp      c,bad_patch
        ld      hl,pos
        call    seek_patch
        ld      hl,tagbuf
        ld      bc,8
        call    read_patch
        ld      hl,left                     ; the data must fit
        ld      de,tagbuf+4
        call    sub32
        jp      c,bad_patch
        ld      hl,pos
        ld      de,eight
        call    add32
        ld      hl,pos
        ld      de,blk_pos
        call    copy4
        ld      hl,tagbuf+4
        ld      de,blk_len
        call    copy4
        ld      hl,pos
        ld      de,tagbuf+4
        call    add32
        or      1                           ; NZ
        ret

; Up to TEXT_MAX bytes of a text block into the small buffer, text_len their count.
read_text:
        ld      hl,(blk_len+2)
        ld      a,h
        or      l
        ld      bc,TEXT_MAX
        jr      nz,.read
        ld      hl,(blk_len)
        or      a
        sbc     hl,bc
        jr      nc,.read
        ld      bc,(blk_len)
.read:  ld      (text_len),bc
        ld      a,b
        or      c
        ret     z
        ld      hl,smallbuf
        jp      read_patch

; DE: a key with its '=', zero-terminated. HL its value in the text, BC its
; length; carry when there is no such line, or it is cut off by the buffer.
text_find:
        ld      hl,smallbuf
        ld      bc,(text_len)
.line:  ld      a,b
        or      c
        scf
        ret     z
        push    de
.cmp:   ld      a,(de)
        or      a
        jr      z,.match
        ld      a,b
        or      c
        jr      z,.absent
        ld      a,(de)
        cp      (hl)
        jr      nz,.other
        inc     hl
        dec     bc
        inc     de
        jr      .cmp
.absent:
        pop     de
        scf
        ret
.other: pop     de
.skip:  ld      a,b
        or      c
        scf
        ret     z
        ld      a,(hl)
        inc     hl
        dec     bc
        cp      10
        jr      nz,.skip
        jr      .line
.match: pop     de
        push    hl
        ld      de,0
.value: ld      a,b
        or      c
        jr      z,.cut
        ld      a,(hl)
        cp      10
        jr      z,.found
        inc     hl
        inc     de
        dec     bc
        jr      .value
.cut:   pop     hl
        scf
        ret
.found: pop     hl
        ld      b,d
        ld      c,e
        or      a
        ret

; A target's fixed part into the small buffer, and its length taken off blk_len, so
; that the text comes next. Too short is damage.
target_fixed:
        ld      hl,blk_len
        ld      bc,0
        ld      de,TARGET_FIXED
        call    below32
        jp      c,bad_patch
        ld      hl,smallbuf
        ld      bc,TARGET_FIXED
        call    read_patch
        ld      hl,blk_len
        ld      de,target_size
        jp      sub32

; The next target in the file, from scan_pos: game_a its path. Carry when it is a
; kind this loader cannot read. They were all checked before this.
target_name:
        ld      hl,scan_pos
        ld      de,pos
        call    copy4
        ld      hl,scan_pos
        call    is_zero32
        call    z,walk_begin
.next:  call    walk_next
        jp      z,bad_patch
        ld      de,magic_tgt1
        call    tag_is
        jr      nz,.next
        ld      hl,pos
        ld      de,scan_pos
        call    copy4
        call    target_fixed
        ld      a,(smallbuf+1)
        cp      KIND_Z80
        scf
        ret     nz
        call    read_text
        ld      de,key_file
        call    text_find
        jp      c,bad_patch
        call    build_game_a
        or      a
        ret

; The file at the (cur_n)th set of kind (cur_kind) this loader can apply, from 1, past its
; fixed part: tagbuf holds that, blk_pos and blk_len its name and stream.
find_set:
        call    walk_begin
.next:  call    walk_next
        jp      z,bad_patch
        ld      de,magic_set2
        call    tag_is
        jr      nz,.next
        ld      hl,tagbuf
        ld      bc,SET_FIXED
        call    read_patch
        ld      a,(tagbuf+3)
        cp      BASE_SPRITE
        jr      nz,.next
        ld      a,(cur_kind)
        inc     a
        ld      hl,tagbuf+1
        cp      (hl)
        jr      nz,.next
        ld      hl,cur_n
        dec     (hl)
        jr      nz,.next
        ld      a,(tagbuf)
        ld      (cur_stream),a
        ret

; Open the next file that could be the game: each target's name, then the patch's own
; with .z80. One that is not there is passed over, as is one no target has the length
; of, which is noted. One that is an output name is refused. Carry when none is left.
next_game:
.again: ld      a,(game_which)
        ld      hl,target_count
        cp      (hl)
        jr      c,.listed
        scf
        ret     nz                          ; past the patch's own
        inc     a
        ld      (game_which),a
        ld      hl,game_b
        ld      a,(hl)
        or      a
        jr      nz,.have
        scf
        ret
.listed:
        inc     a
        ld      (game_which),a
        call    target_name
        jr      c,.again
        ld      hl,game_a
.have:  ld      (open_path),hl
        call    try_open
        jr      c,.again
        ld      hl,(open_path)
        call    check_alias
        call    length_wanted
        ret     z                           ; carry clear from the compare
        ld      a,1
        ld      (seen_wrong),a
        ld      hl,gh
        call    close_at
        call    after_os
        jr      .again

; Z, carry clear, when a target this loader reads has the game's length.
length_wanted:
        call    walk_begin
.next:  call    walk_next
        jr      z,.none
        ld      de,magic_tgt1
        call    tag_is
        jr      nz,.next
        ld      hl,tagbuf
        ld      bc,6
        call    read_patch
        ld      a,(tagbuf+1)
        cp      KIND_Z80
        jr      nz,.next
        ld      hl,tagbuf+2
        ld      de,gsize
        call    same_tag
        jr      nz,.next
        xor     a
        ret
.none:  or      1
        ret

; No file was the game: say which is needed, from the first target this loader reads.
refuse_game:
        ld      hl,0
        ld      (scan_pos),hl
        ld      (scan_pos+2),hl
.find:  call    target_name
        jr      c,.find
        ld      a,1
        ld      (need_name),a
        ld      a,(seen_wrong)
        or      a
        ld      hl,msg_no_game
        jp      z,fail_hl
        ld      hl,msg_wrong_game
        jp      fail_hl

; An input must not be one of the two names this command writes, or making the output
; would destroy it. NextZXOS resolves the file's folder for us, F_GETCWD with A=$FF
; giving "C:/TMP/" for /tmp/x, c:\tmp\x, tmp/x from the root or x from /tmp, whatever
; the case or any ".." (found by trying it). The name itself is compared without regard
; to case, as FAT is, and to dots and spaces at its end, which FAT drops. A folder it cannot
; resolve is refused too, as nothing then says the file is safe. HL: the file's path.
check_alias:
        push    hl
        xor     a
        ld      (smallbuf+1),a
        ld      d,h
        ld      e,l
        ld      hl,smallbuf
        ld      a,$ff
        rst     $08
        db      F_GETCWD
        call    after_os
        pop     hl
        ld      a,(smallbuf+1)
        cp      ':'
        jr      nz,.refuse
        ld      a,(smallbuf+2)
        cp      '/'
        jr      nz,.refuse
        push    hl
        ld      hl,smallbuf
        ld      de,str_tmp
        call    same_name
        pop     hl
        ret     nz                          ; not the output's folder
        call    name_in
        push    hl
        ld      de,nex_out_name+5
        call    same_name
        pop     hl
        jr      z,.refuse
        ld      de,z80_out_name+5
        call    same_name
        ret     nz
.refuse:
        ld      hl,msg_alias
        jp      fail_hl

; Z when the string at HL is the capitals at DE, whatever the case, then dots or spaces.
same_name:
.c:     ld      a,(de)
        or      a
        jr      z,.end
        cp      (hl)
        jr      z,.ok
        or      $20
        cp      (hl)
        ret     nz
.ok:    inc     hl
        inc     de
        jr      .c
.end:   ld      a,(hl)
        inc     hl
        or      a
        ret     z
        cp      '.'
        jr      z,.end
        cp      ' '
        jr      z,.end
        ret

; HL = where the patch's name starts after its folder.
name_start:
        ld      hl,patch_path
; HL = where the name in the path at HL starts.
name_in:
        ld      d,h
        ld      e,l
.c:     ld      a,(hl)
        or      a
        jr      z,.end
        inc     hl
        cp      '/'
        jr      z,.mark
        cp      92
        jr      z,.mark
        cp      ':'
        jr      nz,.c
.mark:  ld      d,h
        ld      e,l
        jr      .c
.end:   ex      de,hl
        ret

; game_a: the patch's folder, then TGT1's file (HL, BC long). That it does not fit is
; a refusal: a name cut short could be another file.
build_game_a:
        push    hl
        push    bc
        call    name_start
        ld      de,patch_path
        or      a
        sbc     hl,de
        ld      b,h
        ld      c,l                         ; BC = the folder's length (<255)
        ld      hl,patch_path
        ld      de,game_a
        ld      a,b
        or      c
        jr      z,.none
        ldir
.none:  ld      (game_a_file),de
        pop     bc
        pop     hl
        ld      a,low (game_a + PATH_SIZE - 1)      ; room left, the zero apart
        sub     e
        cp      c
        jr      c,.long
        ldir
        xor     a
        ld      (de),a
        ret
.long:  ld      hl,msg_long
        jp      fail_hl

; IX = the entry of trainer A (from 0). BC kept.
trainer_entry:
        ld      e,a
        add     a,a
        add     a,a
        add     a,a
        sub     e
        ld      e,a
        ld      d,0
        ld      ix,trainer_table
        add     ix,de
        ret

; Z when the tag in tagbuf is the one at DE. Keeps BC.
tag_is: ld      hl,tagbuf
same_tag:
        push    bc
        ld      b,4
.byte:  ld      a,(de)
        cp      (hl)
        jr      nz,.end
        inc     hl
        inc     de
        djnz    .byte
.end:   pop     bc
        ret

bad_patch:
        ld      hl,msg_damaged
        jp      fail_hl

; Seek the patch file to the position at HL.
seek_patch:
        ld      a,(ph)
; Seek the file A to the 32-bit position at HL. A failure is a read error.
seek_file:
        ld      e,(hl)
        inc     hl
        ld      d,(hl)
        inc     hl
        ld      c,(hl)
        inc     hl
        ld      b,(hl)
        ld      l,0
        rst     $08
        db      F_SEEK
        jr      c,bad_patch
after_os:
        ld      a,(mapped)
        or      a
        ret     z
        di
        ret

; Exactly BC bytes from the patch to HL.
read_patch:
        ld      a,(ph)
        ld      de,msg_damaged
        jr      read_exact

; Exactly BC bytes from the game to HL.
read_game:
        ld      a,(gh)
        ld      de,msg_game_bad
; Exactly BC bytes from file A to HL; otherwise the message at DE.
read_exact:
        push    de
        push    bc
        rst     $08
        db      F_READ
        pop     de
        jr      c,.bad
        ld      a,b
        cp      d
        jr      nz,.bad
        ld      a,c
        cp      e
        jr      nz,.bad
        pop     de
        jr      after_os
.bad:   pop     hl
        jp      fail_hl

; Open HL for reading, as the game. Carry when it cannot be.
try_open:
        ld      a,'*'
        ld      b,FA_READ
        rst     $08
        db      F_OPEN
        ret     c
        ld      (gh),a
        ld      hl,statbuf
        rst     $08
        db      F_FSTAT
        ld      hl,msg_game_bad
        jp      c,fail_hl
        ld      hl,statbuf+7
        ld      de,gsize
        call    copy4
        or      a
        ret

; Print the zero-terminated string at HL, counting columns.
put_z:  ld      a,(hl)
        or      a
        ret     z
        push    hl
        call    put
        pop     hl
        inc     hl
        jr      put_z

put:    ld      hl,col
        inc     (hl)
        rst     $10
        ret

mode_off:
        ld      a,(mode_old_width)          ; 0 before mode_on
        or      a
        ret     z
        ld      a,30
        rst     $10
        ld      a,(mode_old_width)
        rst     $10
        ld      a,14
        rst     $10
        xor     a
        ld      (mode_old_width),a
        ld      a,(mode_changed)
        or      a
        ret     z
        xor     a
        ld      (mode_changed),a
        ld      a,(mode_old_sub)
        ld      c,a
        ld      a,(mode_old_layer)
        ld      b,a
        ld      a,1
        jr      call_mode

call_mode_bc0:
        ld      bc,0
call_mode:
        exx
        ld      de,IDE_MODE
        ld      c,7
        rst     $08
        db      M_P3DOS
        ret

; The three slots from the three bytes at HL.
map3:   ld      a,NR_MMU3
.slot:  ld      e,(hl)
        inc     hl
        push    af
        call    nr_write
        pop     af
        inc     a
        cp      NR_MMU5 + 1
        jr      nz,.slot
        ret

unmap:  ld      a,(mapped)
        or      a
        ret     z
        xor     a
        ld      (mapped),a
        ld      hl,mmu3
        jr      map3

; Close the file whose handle is at HL, if it is open.
close_at:
        ld      a,(hl)
        or      a
        ret     z
        ld      (hl),0
        rst     $08
        db      F_CLOSE
        ret

; Close everything, delete an unfinished output, free the pages, put the
; display and speed back.
finish: ld      hl,gh
        call    close_at
        ld      hl,ph
        call    close_at
        ld      hl,oh
        call    close_at
        ld      a,(oh_done)
        or      a
        jr      nz,.keep
        ld      hl,(out_name)
        ld      a,h
        or      l
        jr      z,.keep
        ld      a,'$'
        rst     $08
        db      F_UNLINK
.keep:  ld      a,(page_count)
        or      a
        jr      z,.free_done
        dec     a
        ld      (page_count),a
        ld      e,a
        ld      d,0
        ld      hl,page_list
        add     hl,de
        ld      e,(hl)
        ld      d,0
        ld      hl,BANK_FREE
        exx
        ld      de,IDE_BANK
        ld      c,7
        rst     $08
        db      M_P3DOS
        jr      .keep
.free_done:
        call    mode_off
        ld      a,(speed)
        or      a
        ret     z
        and     3
        ld      e,a
        ld      a,NR_SPEED
        jp      nr_write

; Errors: HL is the message, whose last character has bit 7 set. Any state.
fail_de:
        ex      de,hl
fail_hl:
        ld      (msg_ptr),hl
        di
        call    unmap
        ld      sp,(entry_sp)
        call    finish
        ld      a,(need_name)
        or      a
        jr      z,.plain
        ld      hl,msg_needs
        call    print
        ld      hl,(game_a_file)
        call    put_z
        ld      a,13
        rst     $10
.plain: ld      a,(interrupts)
        or      a
        jr      z,.di
        ei
.di:    ld      hl,(msg_ptr)
        xor     a
        scf
        ret

; Print a message whose last character has bit 7 set.
print:  ld      a,(hl)
        push    hl
        and     $7f
        rst     $10
        pop     hl
        bit     7,(hl)
        inc     hl
        jr      z,print
        ret

; ------------------------------------------------------------------ NextREG

nr_read:
        ld      bc,NR_SELECT
        out     (c),a
        inc     b
        in      a,(c)
        ret

nr_write:
        ld      bc,NR_SELECT
        out     (c),a
        inc     b
        out     (c),e
        ret

; ------------------------------------------------------------ arithmetic

; (HL) += (DE), 32 bits.
add32:  ld      b,4
        or      a
.byte:  ld      a,(de)
        adc     a,(hl)
        ld      (hl),a
        inc     hl
        inc     de
        djnz    .byte
        ret

; (HL) -= (DE), 32 bits; carry when it went below zero.
sub32:  ld      b,4
        or      a
.byte:  ld      a,(de)
        ld      c,a
        ld      a,(hl)
        sbc     a,c
        ld      (hl),a
        inc     hl
        inc     de
        djnz    .byte
        ret

; Four bytes from HL to DE.
copy4:  ld      bc,4
        ldir
        ret

; Z when the 32 bits at HL are 0.
is_zero32:
        ld      a,(hl)
        inc     hl
        or      (hl)
        inc     hl
        or      (hl)
        inc     hl
        or      (hl)
        ret

magic_nxc1:     db "NXC1"
first_tags:
magic_opt1:     db "OPT1"
magic_inf1:     db "INF1"
magic_out1:     db "OUT1"
magic_nex1:     db "NEX1"
magic_sit1:     db "SIT1"
magic_tgt1:     db "TGT1"
magic_set2:     db "SET2"
ov_tag_want:    db "NXQ1"
key_file:       db "file=",0
str_tmp:        db "C:/TMP/",0
nex_out_name:   db "/tmp/NEXCLASH.NEX",0
z80_out_name:   db "/tmp/NEXCLASH.Z80",0
opt_size:       dd 3
eight:          dd 8
target_size:    dd TARGET_FIXED
msg_no_os:      db "Needs NextZXO", 'S' | $80
msg_damaged:    db "Patch damaged: get it agai", 'n' | $80
msg_no_game:    db "Game not beside the patc", 'h' | $80
msg_wrong_game: db "Wrong game file for this patc", 'h' | $80
msg_needs:      db "Needs this game file:",13 | $80
msg_game_bad:   db "Game file is damage", 'd' | $80
msg_long:       db "File name too lon", 'g' | $80
msg_alias:      db "Input has the /tmp output's nam", 'e' | $80
msg_overlay:    db "NEXCLASH cut or mixed: recopy i", 't' | $80
msg_no_patch:   db "Cannot open the .nx", 'c' | $80
msg_level:      db "Patch needs a newer .NEXCLAS", 'H' | $80

ov_start_at:

; ================================================ only up to the menu

; Everything before the menu, on the caller's stack and paging.
start_menu:
        ld      a,i                         ; P/V = IFF2: were interrupts on?
        ld      a,0
        jp      po,.di
        inc     a
.di:    push    af
        push    hl
        ld      hl,vars
        ld      de,vars+1
        ld      bc,vars_end - vars - 1
        ld      (hl),0
        ldir
        pop     hl
        pop     af
        ld      (interrupts),a
        ld      (entry_sp),sp
        ld      a,h
        or      l
        jp      z,usage
        call    parse_name
        jp      c,usage

        rst     $08
        db      M_DOSVERSION
        ld      hl,msg_no_os
        jp      c,fail_hl
        or      a
        jp      nz,fail_hl

        ld      a,NR_SPEED                  ; 28 MHz while it works
        call    nr_read
        and     3
        or      $80
        ld      (speed),a
        ld      a,NR_SPEED
        ld      e,3
        call    nr_write
        ld      hl,mmu3
        ld      b,3
        ld      a,NR_MMU3
.mmu:   push    bc
        push    af
        call    nr_read
        ld      (hl),a
        inc     hl
        pop     af
        inc     a
        pop     bc
        djnz    .mmu

        ld      a,'*'
        ld      hl,patch_path
        ld      b,FA_READ
        rst     $08
        db      F_OPEN
        ld      hl,msg_no_patch
        jp      c,fail_hl
        ld      (ph),a
        ld      hl,patch_path               ; never read what would be written over
        call    check_alias
        ld      a,(ph)
        ld      hl,statbuf
        rst     $08
        db      F_FSTAT
        jp      c,bad_patch
        ld      hl,statbuf+7
        ld      de,psize
        call    copy4

        call    read_header
        call    walk_first
        call    build_game_b
        call    next_game
        call    c,refuse_game
        call    menu
        jp      after_menu

; 38 bytes: magic, version, flags, nonce, check. Flags must be 0: this reader knows of none.
read_header:
        ld      bc,0
        ld      de,FILE_HEADER
        ld      hl,psize
        call    below32
        ld      hl,msg_not_patch
        jp      c,fail_hl
        ld      hl,smallbuf
        ld      bc,FILE_HEADER
        call    read_patch
        ld      hl,smallbuf
        ld      de,magic_nxc1
        call    same_tag
        ld      hl,msg_not_patch
        jp      nz,fail_hl
        ld      a,(smallbuf+4)
        cp      1
        jp      nz,fail_hl
        ld      a,(smallbuf+5)
        or      a
        jp      nz,fail_hl
        ld      hl,smallbuf+6
        ld      de,nonce
        ld      bc,16
        ldir
        ret

; Every block before the menu: the required ones once each, OPT1's level, each
; target's shape and name, INF1's text, the trainers and the sets' shape.
walk_first:
        call    walk_begin
.next:  call    walk_next
        jr      z,.end
        ld      de,first_tags
        ld      hl,seen
        ld      b,5
.tag:   push    hl
        push    de
        call    tag_is
        pop     de
        pop     hl
        jr      z,.known
        inc     hl
        inc     de
        inc     de
        inc     de
        inc     de
        djnz    .tag
        ld      de,magic_tgt1
        call    tag_is
        call    z,first_tgt1
        ld      de,magic_trn1
        call    tag_is
        call    z,note_trainer
        ld      de,magic_set2
        call    tag_is
        call    z,note_set
        ld      de,magic_scr1_p
        call    tag_is
        jr      nz,.next
        ld      a,1
        ld      (scr_seen),a
        jr      .next
.known: ld      a,(hl)                      ; a second one is damage, whatever follows
        or      a
        jp      nz,bad_patch
        inc     (hl)
        ld      a,b                         ; 5 for the first
        ld      hl,.next
        push    hl
        cp      5
        jr      z,first_opt1
        cp      4
        jp      z,first_inf1
        ld      de,out_rec
        cp      3
        jp      z,first_out1
        ld      de,nex_rec
        cp      2
        jr      z,.rec
        ld      de,sit_rec
.rec:   ld      hl,blk_pos
        ld      bc,8
        ldir
        ret
.end:   ld      hl,seen
        ld      b,5
.req:   ld      a,(hl)
        or      a
        jp      z,bad_patch
        inc     hl
        djnz    .req
        ld      a,(target_count)
        or      a
        jp      z,bad_patch
        ld      a,(scr_seen)                ; a screen must say level 2, or a level 1
        or      a                           ; loader would write a wrong file
        jr      z,.level_ok
        ld      a,(opt_level)
        cp      2
        jp      c,bad_patch
.level_ok:
        ld      a,(set_counts)              ; ten lines have keys: two kinds leave room for 7
        or      a
        jr      z,.lines
        ld      a,(set_counts+1)
        or      a
        jr      z,.lines
        ld      a,(trainer_count)
        cp      TRAINERS_SHOWN
        jr      c,.lines
        dec     a
        ld      (trainer_count),a
.lines: ld      a,(target_kinds)            ; targets, and none this loader can read
        or      a
        ret     nz
        ld      hl,msg_level
        jp      fail_hl
; Exactly 3 bytes: a level this loader has, no flags, the highest 16K bank needed.
first_opt1:
        ld      hl,blk_len
        ld      de,opt_size
        call    same_tag
        jp      nz,bad_patch
        ld      hl,smallbuf
        ld      bc,3
        call    read_patch
        ld      a,(smallbuf+2)
        cp      112
        jp      nc,bad_patch
        ld      (ram_bank),a
        ld      a,(smallbuf+1)
        or      a
        ld      hl,msg_level
        jp      nz,fail_hl
        ld      a,(smallbuf)
        ld      (opt_level),a
        cp      LOADER_LEVEL + 1
        ret     c
        jp      fail_hl
; Exactly 8 bytes.
first_out1:
        push    de
        ld      hl,blk_len
        ld      de,eight
        call    same_tag
        pop     de
        jp      nz,bad_patch
        ld      hl,blk_pos
        ld      bc,8
        ldir
        ret
first_inf1:
        call    read_text
        ld      de,key_publisher
        call    text_find
        ld      de,publisher
        ld      a,16
        call    nc,copy_text
        ld      de,key_patch_by
        call    text_find
        ld      de,patch_by
        call    nc,copy_credit
        ld      de,key_colours_by
        call    text_find
        ld      de,colours_by
        ret     c
copy_credit:
        ld      a,CREDIT_NAME
        jp      copy_text
; A target entry. Its index says its place; its file must be a bare name, for any kind.
first_tgt1:
        call    target_fixed
        ld      a,(target_count)
        cp      TARGETS_MAX
        jp      nc,bad_patch
        ld      c,a
        ld      a,(smallbuf)
        cp      c
        jp      nz,bad_patch
        inc     c
        ld      a,c
        ld      (target_count),a
        ld      a,(smallbuf+1)
        cp      KIND_Z80
        jr      nz,.other
        ld      (target_kinds),a
.other: call    read_text
        ld      de,key_file
        call    text_find
        jp      c,bad_patch
        call    check_name
        ld      a,(title)
        or      a
        ret     nz                          ; the first with a title
        ld      de,key_title
        call    text_find
        ret     c
        ld      de,title
        ld      a,23
        call    copy_text
        jp      upper_title
; HL, BC: a file name. 1 to FILE_NAME_MAX bytes, printable, none of / \ : * ? " < > |,
; no "..", no space first, no space or dot last: never a path. Otherwise damage.
check_name:
        ld      a,b
        or      a
        jp      nz,bad_patch
        ld      a,c
        or      a
        jp      z,bad_patch
        cp      FILE_NAME_MAX + 1
        jp      nc,bad_patch
        ld      a,(hl)
        cp      ' '
        jp      z,bad_patch
        ld      b,c
        ld      d,0                         ; the byte before
.c:     ld      a,(hl)
        inc     hl
        cp      ' '
        jp      c,bad_patch
        cp      $7f
        jp      nc,bad_patch
        ld      c,a
        cp      d
        jr      nz,.not_two
        cp      '.'
        jp      z,bad_patch
.not_two:
        ld      d,a
        push    hl
        push    bc
        ld      hl,bad_chars
        ld      b,9
.bad:   cp      (hl)
        jp      z,bad_patch
        inc     hl
        djnz    .bad
        pop     bc
        pop     hl
        djnz    .c
        ld      a,d
        cp      '.'
        jp      z,bad_patch
        cp      ' '
        jp      z,bad_patch
        ret
bad_chars:
        db      "/\\:*?",34,"<>|"
; BC bytes from HL to DE, at most A of them, then a zero. Anything unprintable
; becomes '?'.
copy_text:
        ex      af,af'
        ld      a,b
        or      a
        jr      nz,.cap
        ex      af,af'
        cp      c
        jr      c,.capped
        ld      a,c
        jr      .capped
.cap:   ex      af,af'
.capped:
        ld      b,a
        or      a
        jr      z,.end
.byte:  ld      a,(hl)
        inc     hl
        cp      ' '
        jr      c,.bad
        cp      $7f
        jr      c,.ok
.bad:   ld      a,'?'
.ok:    ld      (de),a
        inc     de
        djnz    .byte
.end:   xor     a
        ld      (de),a
        ret

upper_title:
        ld      hl,title
.c:     ld      a,(hl)
        or      a
        ret     z
        cp      'a'
        jr      c,.n
        cp      'z'+1
        jr      nc,.n
        sub     'a'-'A'
        ld      (hl),a
.n:     inc     hl
        jr      .c

; game_b: the patch's whole path with its extension changed to .z80, in place,
; as nothing needs that name once the patch is open.
build_game_b:
        call    name_start
        ex      de,hl                       ; DE = the name
        ld      bc,0
.dot:   ld      a,(de)                      ; find the last '.' in the name
        or      a
        jr      z,.end
        cp      '.'
        jr      nz,.nx
        ld      b,d
        ld      c,e
.nx:    inc     de
        jr      .dot
.end:   ld      a,b
        or      c
        jr      nz,.has
        ld      b,d                         ; no extension: at the end
        ld      c,e
.has:   ld      h,b
        ld      l,c
        ld      de,patch_path
        or      a
        sbc     hl,de
        ld      a,l
        cp      PATH_SIZE - 5
        jr      nc,.none                    ; no room
        ld      d,b
        ld      e,c
        ld      hl,ext_z80
        ld      bc,5
        ldir
        ret
.none:  xor     a
        ld      (game_b),a
        ret

; A TRN1 block: where its name and POKEs are. Those past the menu's room are
; left alone, as an unknown block is, once checked. Length = 3 + name + 4 x count.
; The flags must be 0: every menu starts with its trainers off, and no other is defined.
note_trainer:
        ld      hl,blk_len+2
        ld      a,(hl)
        inc     hl
        or      (hl)
        jp      nz,bad_patch                ; far longer than any trainer can be
        ld      bc,(blk_len)
        ld      hl,28                       ; up to 28 bytes: to the POKE count
        or      a
        sbc     hl,bc
        jr      nc,.short
        ld      bc,28
.short: ld      hl,smallbuf
        call    read_patch
        ld      a,(smallbuf)
        or      a
        jp      nz,bad_patch
        ld      a,(smallbuf+1)              ; the name: 1 to 25
        dec     a
        cp      25
        jp      nc,bad_patch
        add     a,4
        ld      c,a
        ld      b,0                         ; BC = bytes to the end of the count
        ld      hl,(blk_len)
        or      a
        sbc     hl,bc
        jp      c,bad_patch                 ; the count lies past the block
        ld      hl,smallbuf-1
        add     hl,bc
        ld      a,(hl)                      ; the count
        or      a
        jp      z,bad_patch
        ld      e,a
        ld      d,0
        ex      de,hl
        add     hl,hl
        add     hl,hl
        add     hl,bc
        ld      de,(blk_len)
        or      a
        sbc     hl,de
        jp      nz,bad_patch
        ld      (left),bc                   ; every POKE is in range, chosen or not
        push    bc
        ld      hl,blk_pos
        ld      de,work32
        call    copy4
        ld      hl,0
        ld      (left+2),hl
        ld      hl,work32
        ld      de,left
        call    add32
        ld      hl,work32
        call    seek_patch
        pop     bc
        push    bc
        ld      hl,smallbuf-1
        add     hl,bc
        ld      b,(hl)
.poke:  push    bc
        ld      hl,work32
        ld      bc,4
        call    read_patch
        pop     bc
        ld      a,(work32)
        cp      112
        jp      nc,bad_patch
        ld      a,(work32+2)
        cp      $40
        jp      nc,bad_patch
        djnz    .poke
        pop     bc
        ld      a,(trainer_count)
        cp      TRAINERS_SHOWN
        ret     nc
        push    bc
        call    trainer_entry
        ld      hl,trainer_count
        inc     (hl)
        ld      a,(smallbuf+1)
        ld      (ix+1),a                    ; the name's length
        ld      c,a
        ld      b,0
        ld      hl,smallbuf+2
        add     hl,bc
        ld      a,(hl)
        ld      (ix+2),a                    ; the count
        pop     bc
        ld      hl,(blk_pos)                ; where the POKEs start
        add     hl,bc
        ld      (ix+3),l
        ld      (ix+4),h
        ld      hl,(blk_pos+2)
        ld      bc,0
        adc     hl,bc
        ld      (ix+5),l
        ld      (ix+6),h
        ret

; A SET2 block, the file at its data: stream index, kind, choice, base, a name of 1 to
; 25, which must fit. A stream index given twice would use one stream twice. A kind or
; base this loader cannot apply is not offered, but is checked all the same.
note_set:
        ld      hl,blk_len
        ld      bc,0
        ld      de,SET_FIXED
        call    below32
        jp      c,bad_patch
        ld      hl,smallbuf
        ld      bc,SET_FIXED
        call    read_patch
        ld      a,(smallbuf+4)
        dec     a
        cp      25
        jp      nc,bad_patch
        add     a,SET_FIXED+1
        ld      e,a
        ld      d,0
        ld      bc,0
        ld      hl,blk_len
        call    below32
        jp      c,bad_patch
        ld      a,(smallbuf)
        ld      c,a
        and     7
        ld      b,a
        inc     b
        ld      a,$80
.bit:   rlca
        djnz    .bit
        ld      d,a
        ld      a,c
        rrca
        rrca
        rrca
        and     31
        ld      c,a
        ld      b,0
        ld      hl,pal_seen
        add     hl,bc
        ld      a,d
        and     (hl)
        jp      nz,bad_patch
        ld      a,d
        or      (hl)
        ld      (hl),a
        ld      a,(smallbuf+3)
        cp      BASE_SPRITE
        ret     nz
        ld      a,(smallbuf+1)
        dec     a
        cp      KINDS
        ret     nc
        ld      c,a
        ld      b,0
        ld      hl,set_counts
        add     hl,bc
        inc     (hl)
        ret     nz
        jp      bad_patch                   ; 256 of a kind: more than there are streams

; ----------------------------------------------------------------- the menu

menu:   call    mode_on
        call    menu_draw
.wait:  call    wait_release
.poll:  call    scan_keys
        or      a
        jr      z,.poll
        cp      13
        jr      z,.go
        cp      1
        jr      z,.cancel
        cp      ' '                         ; as ENTER: with what the menu shows
        jr      z,.go
        sub     '0'                         ; a digit
        ld      c,a
        ld      a,(trainer_count)
        inc     a
        cp      c
        jr      z,.version
        jr      c,.colours
        ld      a,c
        dec     a
        call    trainer_entry
        ld      a,(ix+0)
        xor     1
        ld      (ix+0),a
.again: call    menu_draw
        jr      .wait
.version:
        ld      a,(ver_original)
        xor     1
        ld      (ver_original),a
        jr      .again
.colours:                                   ; each line after: a kind that offers any
        ld      hl,set_counts
        ld      b,KINDS
.kind:  ld      e,(hl)
        inc     e
        dec     e
        jr      z,.not_this
        inc     a
        cp      c
        jr      z,.step
.not_this:
        inc     hl
        djnz    .kind
        jr      .wait                       ; no such line
.step:  ld      a,(ver_original)            ; unavailable: the choice stays as it is
        or      a
        jr      nz,.wait
        ld      a,e                         ; off, then each in turn, then off
        ld      de,KINDS
        add     hl,de
        cp      (hl)
        jr      nz,.more
        ld      (hl),0
        jr      .again
.more:  inc     (hl)
        jr      .again
.go:    call    wait_release
        call    check_ram
        jp      mode_off
.cancel:
        ld      hl,msg_cancelled
        jp      fail_hl

; The rebuilt game must fit this machine: its highest bank is within the 8K banks NextZXOS
; says there are. The player's own game with the fix off needs nothing of the kind. If
; the call fails, nothing is known, and it goes on.
check_ram:
        ld      a,(ver_original)
        or      a
        ret     nz
        ld      hl,0                        ; ZX memory, total
        exx
        ld      de,IDE_BANK
        ld      c,7
        rst     $08
        db      M_P3DOS
        ret     nc
        ld      a,(ram_bank)
        inc     a
        add     a,a
        cp      e
        ret     c
        ret     z
        ld      hl,msg_ram_small
        jp      fail_hl

; Until no key is down, steadily.
wait_release:
.again: ld      hl,DEBOUNCE
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

; A: 0 none, 13 Enter, ' ' Space, 1 Break, or '1' to '9', and '9'+1 for key 0,
; which is the tenth line.
scan_keys:
        ld      bc,$bffe                    ; Enter
        in      a,(c)
        rra
        ld      a,13
        ret     nc
        ld      bc,$7ffe                    ; Space, or Break with Caps Shift
        in      a,(c)
        rra
        jr      c,.digits
        ld      bc,$fefe
        in      a,(c)
        rra
        ld      a,' '
        ret     c
        ld      a,1
        ret
.digits:
        ld      bc,$f7fe                    ; 1 to 5: bits 0 to 4
        in      a,(c)
        ld      e,'1'
        ld      b,5
.left:  rra
        jr      nc,.found
        inc     e
        djnz    .left
        ld      bc,$effe                    ; 6 to 9, 0: bits 4 down to 0
        in      a,(c)
        ld      e,'6'
        ld      b,5
.right: bit     4,a
        jr      z,.found
        add     a,a
        inc     e
        djnz    .right
        xor     a
        ret
.found: ld      a,e
        ret

menu_draw:
        ld      a,14                        ; clear the window
        rst     $10
        xor     a
        ld      (col),a
        ld      a,' '
        call    put
        ld      hl,title
        call    put_z
        ld      hl,publisher
        call    len_z
        jr      z,.no_publisher
        ld      a,41                        ; flush with the last column
        sub     c
        call    pad_to
.no_publisher:
        ld      hl,publisher
        call    put_z
        call    newline
        call    newline
        ld      a,(trainer_count)
        or      a
        jr      z,.no_trainers
        ld      hl,str_trainer
        call    put_z
        call    newline
        ld      a,(trainer_count)
        ld      b,a
        ld      c,0
.row:   push    bc
        ld      a,c
        call    digit_row
        pop     bc
        push    bc
        ld      a,c
        call    trainer_entry
        push    ix                          ; the name lies before the POKEs
        pop     hl
        ld      de,3
        add     hl,de
        ld      de,work32
        call    copy4
        ld      a,(ix+1)                    ; - (name's length + 1)
        inc     a
        neg
        ld      e,a
        ld      d,$ff
        ld      (left),de
        ld      hl,$ffff
        ld      (left+2),hl
        ld      hl,work32
        ld      de,left
        call    add32
        ld      hl,work32
        call    seek_patch
        ld      c,(ix+1)
        ld      b,0
        ld      hl,smallbuf
        call    read_patch
        ld      b,(ix+1)
        ld      hl,smallbuf
        call    put_name
        pop     bc
        push    bc
        ld      a,c
        call    trainer_entry
        ld      a,(ix+0)
        call    put_on_off
        pop     bc
        inc     c
        dec     b
        jr      nz,.row
        call    newline
.no_trainers:
        ld      hl,str_nexclash
        call    put_line
        ld      a,(trainer_count)
        call    digit_row
        ld      hl,str_fix
        call    put_z
        ld      a,(ver_original)
        xor     1
        call    put_on_off
        ld      a,(trainer_count)
        ld      (cur_line),a
        xor     a
        call    kind_line
        ld      a,1
        call    kind_line
        call    newline
        ld      hl,str_keys
        call    put_line
; The credit line, if there is anything to show: "Patch: a     Colours: b", in 41
; columns from the first. Colours only with a set. With both, the words and a gap of
; 2 leave 23 for the names: a keeps 11 or what b leaves, b the rest, and the gap is 5
; if that fits. A name is cut in its buffer, so all this can repeat.
        ld      a,(set_counts)
        or      a
        jr      nz,.sets
        ld      (colours_by),a
.sets:  ld      a,(patch_by)
        ld      hl,colours_by
        or      (hl)
        ret     z                           ; neither
        call    newline
        ld      a,(patch_by)
        or      a
        ld      hl,str_colours
        jr      z,.no_patch
        ld      hl,colours_by
        call    len_z
        jr      z,.one
        cp      12                          ; both: b, or 12 of it, has its room
        jr      c,.short
        ld      a,12
.short: neg
        add     a,23
        ld      hl,patch_by
        call    cut_name
        ld      hl,patch_by
        call    len_z
        neg
        add     a,23
        ld      hl,colours_by
        call    cut_name
.one:   ld      hl,str_patch
        call    put_z
        ld      hl,patch_by
        call    put_z
        ld      hl,colours_by
        call    len_z
        jp      z,newline
        neg
        add     a,41 - 9                    ; "Colours: b" ends in the last column
        ld      d,a
        ld      a,(col)
        add     a,5
        cp      d
        jr      c,.gap
        ld      a,d
.gap:   call    pad_to
        ld      hl,str_colours
.no_patch:
        call    put_z
        ld      hl,colours_by
        jp      put_line

; The line of kind A, if it offers any. Colours with one set is [ON] or [OFF]; otherwise it
; says [OFF] or the name, from the patch, at most 17 characters, ending in the last column.
kind_line:
        ld      (cur_kind),a
        ld      c,a
        ld      b,0
        ld      hl,set_counts
        add     hl,bc
        ld      a,(hl)
        or      a
        ret     z
        ld      hl,cur_line
        inc     (hl)
        ld      a,(hl)
        call    digit_row
        ld      a,(cur_kind)
        or      a
        ld      hl,str_enhanced
        jr      z,.label
        ld      hl,str_language
.label: call    put_z
        ld      a,(ver_original)
        or      a
        jr      nz,.unavailable
        ld      a,(cur_kind)
        ld      c,a
        ld      b,0
        ld      hl,set_choices
        add     hl,bc
        ld      a,(hl)
        or      a
        jp      z,put_on_off                ; A=0: [OFF]
        ld      (cur_n),a
        ld      a,(cur_kind)
        or      a
        jr      nz,.name
        ld      a,(set_counts)
        dec     a
        jr      nz,.name
        inc     a
        jp      put_on_off                  ; [ON]
.name:  call    find_set
        ld      a,(tagbuf+4)
        cp      18
        jr      c,.short
        ld      a,17
.short: ld      (cur_name),a
        ld      c,a                         ; only as much as is shown, in any case
        ld      b,0
        ld      hl,smallbuf
        call    read_patch
        ld      a,(cur_name)
        neg
        add     a,41-2
        cp      31
        jr      c,.pad
        ld      a,31                        ; [ON] and [OFF] start here, and names that fit
.pad:   call    pad_to
        ld      a,'['
        call    put
        ld      a,(cur_name)
        ld      b,a
        ld      hl,smallbuf
        call    put_name
        ld      hl,str_close
        jp      put_line
.unavailable:
        ld      a,31
        call    pad_to
        ld      hl,str_unavailable
        jp      put_line

; End the name at HL after A characters.
cut_name:
        ld      e,a
        ld      d,0
        add     hl,de
        ld      (hl),d
        ret

put_line:
        call    put_z
        jr      newline

; B bytes of a name from HL; anything unprintable is shown as '?'.
put_name:
.name:  ld      a,(hl)
        cp      ' '
        jr      c,.q
        cp      $7f
        jr      c,.n
.q:     ld      a,'?'
.n:     push    hl
        push    bc
        call    put
        pop     bc
        pop     hl
        inc     hl
        djnz    .name
        ret

; From column 31, [ON] if A is not 0, otherwise [OFF], and the end of the line.
put_on_off:
        push    af
        ld      a,31
        call    pad_to
        pop     af
        or      a
        ld      hl,str_on
        jr      nz,put_line
        ld      hl,str_off
        jr      put_line

; "  n  " for line A (from 0). The tenth line's key is 0.
digit_row:
        push    af
        ld      hl,str_indent
        call    put_z
        pop     af
        add     a,'1'
        cp      '9'+1
        jr      nz,.digit
        ld      a,'0'
.digit: call    put
        ld      hl,str_indent
        jp      put_z
; C = the length of the string at HL.
len_z:  ld      c,0
.c:     ld      a,(hl)
        or      a
        jr      z,.end
        inc     hl
        inc     c
        jr      .c
.end:   ld      a,c
        or      a
        ret

; Spaces up to column A.
pad_to: ld      hl,col
        cp      (hl)
        ret     c
        ret     z
        push    af
        ld      a,' '
        call    put
        pop     af
        jr      pad_to

newline:
        xor     a
        ld      (col),a
        ld      a,13
        rst     $10
        ret

; A window that holds the menu's 41 columns: 6-pixel characters on layer 1,1
; (layer 0 has only 32 columns and no such codes). Anything that was changed
; is put back by mode_off.
mode_on:
        xor     a
        call    call_mode_bc0
        ld      hl,msg_no_os
        jp      nc,fail_hl
        ld      d,a
        ld      a,b
        ld      (mode_old_width),a
        ld      a,d
        and     3
        ld      (mode_old_layer),a
        ld      e,a
        ld      a,d
        rrca
        rrca
        and     3
        ld      (mode_old_sub),a
        ld      c,a
        ld      a,e                         ; layer 0, or lo-res: too narrow
        or      a
        jr      z,.change
        dec     a
        jr      nz,.width
        ld      a,c
        or      a
        jr      nz,.width
.change:
        ld      a,1
        ld      b,1
        ld      c,1
        call    call_mode
        ld      hl,msg_no_os
        jp      nc,fail_hl
        ld      a,b
        ld      (mode_old_width),a
        ld      a,1
        ld      (mode_changed),a
.width: ld      a,30                        ; character width 6
        rst     $10
        ld      a,6
        rst     $10
        ret

usage:  ld      hl,msg_usage
        call    print
        or      a
        ret

; ---------------------------------------------------------------- the name

; The file name from HL: quoted, or up to a space, ':' or the line's end.
parse_name:
.skip:  ld      a,(hl)
        cp      ' '
        jr      nz,.first
        inc     hl
        jr      .skip
.first: ld      de,patch_path
        ld      b,0
        cp      '"'
        jr      nz,.char
        inc     hl
        ld      b,'"'
.char:  ld      a,(hl)
        or      a
        jr      z,.end
        cp      13
        jr      z,.end
        cp      b
        jr      z,.end
        inc     b
        dec     b
        jr      nz,.keep                    ; quoted: spaces and ':' are part
        cp      ' '
        jr      z,.end
        cp      ':'
        jr      z,.end
.keep:  ld      (de),a
        inc     de
        inc     hl
        ld      a,e
        cp      low (patch_path + PATH_SIZE - 1)
        jr      nz,.char
        ld      hl,msg_long
        jp      fail_hl
.end:   xor     a
        ld      (de),a
        ld      a,(patch_path)
        or      a
        ret     nz
        scf
        ret

magic_trn1:     db "TRN1"
magic_scr1_p:   db "SCR1"
key_title:      db "title=",0
key_publisher:  db "publisher=",0
key_patch_by:   db "patch_by=",0
key_colours_by: db "colours_by=",0
ext_z80:        db ".z80",0
str_trainer:    db " TRAINER",0
str_nexclash:   db " NEXCLASH",0
str_indent:     db "  ",0
str_on:         db "[ON]",0
str_off:        db "[OFF]",0
str_close:      db "]",0
str_unavailable: db "[N/A]",0
str_fix:        db "Colour clash fix",0
str_enhanced:   db "Enhanced colours",0
str_language:   db "Language",0
str_keys:       db " ENTER to play",0
str_patch:      db "Patch: ",0
str_colours:    db "Colours: ",0
msg_usage:      db ".NEXCLASH ",34,"GAME.nxc",34,13
                db "Rebuilds NexClash's game from a",13
                db "patch and your own copy.",13
                db "Inspired by Bleugh.biz's",13
                db "nexclash (bleughb/nexclash,",13
                db "GPL-3.0+). ZX0: Einar Saukas.",13 | $80
msg_not_patch:  db "Not a .nxc fil", 'e' | $80
msg_cancelled:  db "Cancelle", 'd' | $80
msg_ram_small:  db "Needs more RAM: turn fix of", 'f' | $80

first_end:
        assert  first_end <= vars, "the first part runs into the variables"
        ds      $4000 - $, 0                ; the first 8K, as NextZXOS loads it

; ================================================ read in after the menu

        disp    ov_start_at
ov_start:

; ------------------------------------------------------------ the routes

chosen:
        ld      a,(ver_original)
        or      a
        jp      z,nexclash_chosen
        xor     a                           ; with the fix off, no set applies
        ld      (set_choices),a
        ld      (set_choices+1),a
        call    any_trainer_on
        jp      nz,original_with_trainers
        call    original_plain
        ld      a,2
        jp      done

; NZ when a trainer is on.
any_trainer_on:
        ld      a,(trainer_count)
        or      a
        ret     z
.t:     dec     a
        push    af
        call    trainer_entry
        ld      c,(ix+0)
        pop     af
        inc     c
        dec     c
        ret     nz
        or      a
        jr      nz,.t
        ret

; Clash fix off, no trainer: the same bytes, under a fixed name.
original_plain:
        ld      hl,z80_out_name
        call    create_out
.chunk: ld      hl,smallbuf
        ld      bc,SMALLBUF_SIZE
        ld      a,(gh)
        rst     $08
        db      F_READ
        ld      hl,msg_game_bad
        jp      c,fail_hl
        ld      a,b
        or      c
        jr      z,.end
        ld      hl,smallbuf
        call    write_out
        jr      .chunk
.end:   jp      close_out

; Clash fix off with a trainer on: proved against the patch, then rebuilt.
original_with_trainers:
        call    work_begin
        call    unlock
        call    parse_game
        ld      a,1
        call    load_pokes
        ld      hl,z80_out_name
        call    create_out
        call    write_z80_head
        ld      a,(z80_128)
        or      a
        jr      nz,.k128
        ld      hl,pages_48k
        ld      b,3
        jr      .pages
.k128:  ld      hl,pages_128k
        ld      b,8
.pages: ld      a,(hl)
        inc     hl
        ld      e,(hl)                      ; the bank
        inc     hl
        push    bc
        push    hl
        ld      hl,HDR
        ld      (hl),$ff
        inc     hl
        ld      (hl),$ff
        inc     hl
        ld      (hl),a
        ld      a,e
        ld      (cur_bank),a
        ld      hl,HDR
        ld      bc,3
        call    write_out
        call    decode_game_bank
        call    apply_pokes
        ld      hl,WORK
        ld      bc,BANK_SIZE
        call    write_out
        pop     hl
        pop     bc
        djnz    .pages
        call    close_out
        ld      a,2
        jp      done

pages_48k:
        db      8, 5, 4, 2, 5, 0
pages_128k:
        db      3, 0, 4, 1, 5, 2, 6, 3, 7, 4, 8, 5, 9, 6, 10, 7

; The .z80's header, made version 2 if it was version 1.
write_z80_head:
        ld      hl,head
        ld      de,HDR
        ld      bc,32
        ldir
        ld      a,(z80_v1)
        or      a
        jr      z,.keep
        ld      a,(HDR+12)                  ; 255 means 1; no compression flag
        cp      255
        jr      nz,.f
        ld      a,1
.f:     and     $df
        ld      (HDR+12),a
        ld      hl,(HDR+6)
        ld      (HDR+32),hl
        ld      hl,0
        ld      (HDR+6),hl
        ld      hl,23
        ld      (HDR+30),hl
        ld      hl,HDR+34                   ; hardware mode and the rest 0
        ld      de,HDR+35
        ld      bc,20
        ld      (hl),0
        ldir
        ld      hl,HDR
        ld      bc,55
        jp      write_out
.keep:  ld      hl,head_pos
        ld      a,(gh)
        call    seek_file
        ld      hl,(z80_head_len)
        ld      bc,32
        or      a
        sbc     hl,bc
        ld      b,h
        ld      c,l
        ld      a,b
        or      c
        jr      z,.write
        ld      hl,HDR+32
        call    read_game
.write: ld      hl,HDR
        ld      bc,(z80_head_len)
        jp      write_out

head_pos:
        dd      32

; NexClash: the checks, the header, the site table, then each bank.
nexclash_chosen:
        call    work_begin
        call    unlock
        call    load_bank_index
        call    decode_nex_header
        call    parse_game
        call    decode_sites
        ld      a,$ff
        call    sites_walk                  ; check the whole table
        call    map_iopage
        call    all_banks_available
        call    check_screen
        call    check_sets
        xor     a
        call    load_pokes
        ld      hl,nex_out_name
        call    create_out
        ld      hl,$ffff
        ld      (crc),hl
        ld      (crc+2),hl
        ld      hl,HDR
        ld      bc,512
        call    crc_update
        ld      hl,HDR
        ld      bc,512
        call    write_out
        call    write_screen

        ld      b,0                         ; .nex order: 5,2,0,1,3,4,6,7,8...
.order: push    bc
        call    order_bank
        ld      a,(z80_v1)                  ; a v1 file is one stream: 5, 2, 0
        or      a
        jr      z,.not_v1
        pop     bc
        push    bc
        ld      a,b
        cp      3
        call    c,decode_game_bank
.not_v1:
        ld      a,(cur_bank)
        call    header_has
        jr      z,.next
        call    bank_index_entry            ; IX at the patch's bank, if any
        jr      nz,.patch
        ld      a,(z80_v1)
        or      a
        call    z,decode_game_bank
        ld      a,(cur_bank)
        call    sites_walk
        call    map_iopage
        jr      .emit
.patch: call    decode_patch_bank
.emit:  call    bank_sets
        call    apply_sets
        ld      hl,WORK
        ld      bc,BANK_SIZE
        call    crc_update
        call    apply_pokes
        ld      hl,WORK
        ld      bc,BANK_SIZE
        call    write_out
.next:  pop     bc
        inc     b
        ld      a,b
        cp      112
        jr      c,.order

        call    close_out                   ; length and CRC, or no file
        ld      hl,crc
        ld      de,want
        call    check_result
        ld      a,1
        ld      (oh_done),a
        jp      done

; The running CRC at HL and out_len against the CRC and length at DE.
check_result:
        ld      b,4
.crc:   ld      a,(de)
        cpl
        cp      (hl)
        jr      nz,.wrong
        inc     hl
        inc     de
        djnz    .crc
        ld      hl,out_len
        ld      b,4
.len:   ld      a,(de)
        cp      (hl)
        jr      nz,.wrong
        inc     hl
        inc     de
        djnz    .len
        ret
.wrong: ld      hl,msg_bad_result
        jp      fail_hl

; The Bth bank in .nex order into cur_bank, and A. Keeps BC.
order_bank:
        ld      a,b
        ld      (cur_bank),a
        cp      8
        ret     nc
        ld      e,a
        ld      d,0
        ld      hl,nex_order
        add     hl,de
        ld      a,(hl)
        ld      (cur_bank),a
        ret
nex_order:
        db      5, 2, 0, 1, 3, 4, 6, 7

; ---------------------------------------------------------------- the loading screen

; What lies between a .nex's header and its banks, by the header's byte 10, as
; .nexload reads it: a palette of 512 unless bit 7 is set or a ULA, hi-res or hi-colour
; screen is there; then Layer 2, 49152; ULA, 6912; lo-res, hi-res, hi-colour, 12288 each.
; Bits 5 and 6 are V1.3's screens, which this format does not hold. scr_left: the size.
screen_size:
        ld      hl,0
        ld      (scr_left),hl
        ld      (scr_left+2),hl
        ld      a,(HDR+10)
        or      a
        ret     z
        ld      c,a
        and     $60
        ld      hl,msg_screen
        jp      nz,fail_hl
        ld      a,c
        and     $9a
        jr      nz,.no_palette
        ld      hl,512
        ld      (scr_left),hl
.no_palette:
        ld      hl,screen_sizes
        ld      b,5
.flag:  ld      e,(hl)
        inc     hl
        ld      d,(hl)
        inc     hl
        rrc     c
        jr      nc,.absent
        push    hl
        ld      hl,(scr_left)
        add     hl,de
        ld      (scr_left),hl
        jr      nc,.no_carry
        ld      hl,scr_left+2
        inc     (hl)
.no_carry:
        pop     hl
.absent:
        djnz    .flag
        ret
screen_sizes:
        dw      49152, 6912, 12288, 12288, 12288

; Every SCR1 block before any file is made: one for each 16K of the screen, in range,
; no index given twice, and none at all if the header lists no screen.
check_screen:
        call    screen_size
        ld      a,(scr_left+2)              ; chunks = size / 16384, rounded up
        ld      h,a
        ld      a,(scr_left+1)
        ld      l,a
        ld      a,(scr_left)
        or      a
        jr      z,.even
        inc     hl                          ; (a palette: 512 is $200, not a low byte)
.even:  ld      de,$3f
        add     hl,de
        add     hl,hl
        add     hl,hl
        ld      a,h
        ld      (scr_chunks),a
        xor     a
        ld      (scr_mask),a
        call    walk_begin
.next:  call    walk_next
        jr      z,.end
        ld      de,magic_scr1
        call    tag_is
        jr      nz,.next
        ld      hl,blk_len
        ld      bc,0
        ld      de,3
        call    below32
        jp      c,bad_patch
        ld      hl,tagbuf
        ld      bc,3
        call    read_patch
        ld      a,(scr_chunks)
        ld      c,a
        ld      a,(tagbuf)
        cp      c
        jp      nc,bad_patch
        ld      b,a
        inc     b
        ld      a,$80
.bit:   rlca
        djnz    .bit
        ld      c,a
        ld      a,(scr_mask)
        ld      b,a
        and     c
        jp      nz,bad_patch
        ld      a,b
        or      c
        ld      (scr_mask),a
        ld      hl,(tagbuf+1)               ; at most 16K, and data if it says so
        ld      de,BANK_SIZE+1
        or      a
        sbc     hl,de
        jp      nc,bad_patch
        ld      hl,(tagbuf+1)
        ld      a,h
        or      l
        jr      nz,.next
        ld      hl,blk_len
        ld      de,three
        call    same_tag
        jp      nz,bad_patch
        jr      .next
.end:   ld      a,(scr_chunks)              ; all of them there
        ld      b,a
        xor     a
        inc     b
.count: dec     b
        jr      z,.counted
        scf
        rla
        jr      .count
.counted:
        ld      c,a
        ld      a,(scr_mask)
        cp      c
        jp      nz,bad_patch
        ret

; The screen into the file, 16K at a time through WORK, under both CRCs. Each is
; decoded as a BNK1 is, its stream SCR1 with its index.
write_screen:
        ld      a,(scr_chunks)
        or      a
        ret     z
        xor     a
.chunk: ld      (scr_now),a
        call    walk_begin
.find:  call    walk_next
        jp      z,bad_patch
        ld      de,magic_scr1
        call    tag_is
        jr      nz,.find
        ld      hl,tagbuf
        ld      bc,3
        call    read_patch
        ld      a,(scr_now)
        ld      c,a
        ld      a,(tagbuf)
        cp      c
        jr      nz,.find
        ld      hl,blk_pos
        ld      de,three
        call    add32
        ld      hl,blk_len
        ld      de,three
        call    sub32
        ld      de,WORK
        ld      hl,(tagbuf+1)
        ld      a,h
        or      l
        jr      z,.zeros
        add     hl,de
        call    zx_bounds
        call    src_patch
        ld      de,magic_scr1
        ld      a,(scr_now)
        ld      c,a
        ld      hl,blk_pos
        call    block_decode
        ld      hl,(zx_end)
        or      a
        sbc     hl,de
        jp      nz,bad_patch
.zeros: call    fill_zeros
        ld      bc,BANK_SIZE                ; this much of it is the screen
        ld      hl,(scr_left+2)
        ld      a,h
        or      l
        jr      nz,.full
        ld      hl,(scr_left)
        or      a
        sbc     hl,bc
        jr      nc,.full
        ld      bc,(scr_left)
.full:  ld      hl,(tagbuf+1)               ; no more than the screen has room for
        or      a
        sbc     hl,bc
        jr      c,.fits
        jp      nz,bad_patch
.fits:  ld      hl,scr_left
        ld      a,(hl)
        sub     c
        ld      (hl),a
        inc     hl
        ld      a,(hl)
        sbc     a,b
        ld      (hl),a
        inc     hl
        ld      a,(hl)
        sbc     a,0
        ld      (hl),a
        push    bc
        ld      hl,WORK
        call    crc_update
        pop     bc
        ld      hl,WORK
        call    write_out
        ld      a,(scr_chunks)
        ld      c,a
        ld      a,(scr_now)
        inc     a
        cp      c
        jp      c,.chunk
        ret

; NZ when the header lists bank A.
header_has:
        ld      e,a
        ld      d,0
        ld      hl,HDR+18
        add     hl,de
        ld      a,(hl)
        or      a
        ret

; All banks the header lists must come from somewhere, before any file is made.
all_banks_available:
        ld      b,112
        ld      c,0
.b:     push    bc
        ld      a,c
        ld      (cur_bank),a
        call    bank_index_entry
        push    af
        ld      a,(cur_bank)
        call    header_has
        jr      nz,.listed
        pop     af                          ; a BNK1 for a bank not listed is damage
        jp      nz,bad_patch
        jr      .ok
.listed:
        ld      a,(ram_bank)                ; OPT1 may say more than the header lists, not less
        ld      hl,cur_bank
        cp      (hl)
        jp      c,bad_patch
        pop     af
        jr      nz,.ok
        ld      a,(cur_bank)
        call    game_has
        jp      nc,bad_patch
.ok:    pop     bc
        inc     c
        djnz    .b
        ret

; Create the output on the system drive.
create_out:
        push    hl
        ld      a,'$'
        ld      b,FA_CREATE
        rst     $08
        db      F_OPEN
        pop     hl
        jr      c,.none
        ld      (oh),a
        ld      (out_name),hl               ; only now is there a file to delete
        jp      after_os
.none:  ld      hl,msg_write
        jp      fail_hl

; Write BC bytes from HL, counting them; anything less is an error.
write_out:
        push    bc
        ld      a,(oh)
        rst     $08
        db      F_WRITE
        pop     de
        ld      hl,msg_write
        jp      c,fail_hl
        ld      a,b
        cp      d
        jp      nz,fail_hl
        ld      a,c
        cp      e
        jp      nz,fail_hl
        ld      hl,out_len
        ld      a,(hl)
        add     a,e
        ld      (hl),a
        inc     hl
        ld      a,(hl)
        adc     a,d
        ld      (hl),a
        inc     hl
        ld      a,(hl)
        adc     a,0
        ld      (hl),a
        inc     hl
        ld      a,(hl)
        adc     a,0
        ld      (hl),a
        jp      after_os

; Close the output, keeping its name for a delete if something later fails.
close_out:
        ld      a,(oh)
        rst     $08
        db      F_CLOSE
        ld      hl,msg_write
        jp      c,fail_hl
        xor     a
        ld      (oh),a
        ld      a,(ver_original)            ; a .nex is not done until checked
        ld      (oh_done),a
        jp      after_os

; ------------------------------------------------------------------ memory

; Pages, the 8K's stack, 0x6000-0xBFFF mapped: the key state, CRC tables.
work_begin:
        ld      a,(set_choices)
        or      a
        ld      b,PAGES
        jr      z,.second
        ld      b,PAGES + SET_PAGES
.second:
        ld      a,(set_choices+1)
        or      a
        jr      z,.alloc
        ld      a,b
        add     a,SET_PAGES
        ld      b,a
.alloc: ld      a,b
        ld      (page_goal),a
.more:  push    bc
        ld      hl,BANK_ALLOC
        exx
        ld      de,IDE_BANK
        ld      c,7
        rst     $08
        db      M_P3DOS
        ld      a,e
        pop     bc
        jr      nc,.none
        ld      hl,page_count
        ld      e,(hl)
        inc     (hl)
        ld      d,0
        ld      hl,page_list
        add     hl,de
        ld      (hl),a
        djnz    .more
        pop     hl                          ; the return address, to the new stack
        di
        ld      sp,stack_top
        push    hl
        ld      a,1
        ld      (mapped),a
        call    map_std
        ld      hl,BANK_INDEX
        ld      de,BANK_INDEX+1
        ld      bc,IO_CLEAR_END-BANK_INDEX-1
        ld      (hl),0
        ldir
        jp      crc_make
.none:  ld      a,b
        ld      a,(page_goal)
        ld      hl,msg_ram
        cp      PAGES
        jp      z,fail_hl
        ld      hl,msg_ram_set
        cp      PAGES + SET_PAGES
        jp      z,fail_hl
        ld      hl,msg_ram_two
        jp      fail_hl

; ---- page_list: W0, W1, IO, sites x 3, set x 3.


map_std:
        ld      hl,page_list
        jp      map3

map_iopage:
        ld      a,(page_list+2)
map_slot5:
        ld      e,a
        ld      a,NR_MMU5
        jp      nr_write

; The caller's paging, its stack and all done with. A is what %X becomes.
done:   ld      (handoff),a
        di
        call    unmap
        ld      sp,(entry_sp)
        call    finish
        ld      hl,$5c3b                    ; FLAGS: the Enter that chose is spent
        res     5,(hl)
        ld      a,(handoff)
        ld      e,a
        ld      d,0
        ld      hl,$0100                    ; set, not an array
        ld      bc,HANDOFF_VAR
        exx
        ld      de,IDE_INTEGER_VAR
        ld      c,7
        rst     $08
        db      M_P3DOS
        push    af
        ld      a,(interrupts)
        or      a
        jr      z,.di
        ei
.di:    pop     af
        ld      hl,msg_no_os
        ccf                                 ; carry was success: now it is failure
        ld      a,0
        ret     c
        or      a
        ret

; ----------------------------------------------------------------- the checks

; The right game and an undamaged patch, before anything is decompressed. The game is
; absorbed once, and each target of its length tried from a copy of that state, so that
; it is never read again for another entry. A wrong game: on to the next file there is.
unlock:
        call    absorb_game
        call    walk_begin
.next:  call    walk_next
        jr      z,.wrong
        ld      de,magic_tgt1
        call    tag_is
        jr      nz,.next
        ld      hl,tgt_buf
        ld      bc,TARGET_FIXED
        call    read_patch
        ld      a,(tgt_buf+1)
        cp      KIND_Z80
        jr      nz,.next
        ld      hl,tgt_buf+2
        ld      de,gsize
        call    same_tag
        jr      nz,.next
        ld      de,magic_tgt1
        ld      a,(tgt_buf)
        ld      c,a
        call    stream_open
        ld      hl,tgt_buf+6
        ld      bc,24
        call    rc4_xor
        ld      hl,tgt_buf+6
        ld      de,wrap_check
        ld      b,8
.chk:   ld      a,(de)
        cp      (hl)
        jr      nz,.next
        inc     hl
        inc     de
        djnz    .chk
        call    make_master
        jp      check_file
.wrong: ld      hl,gh
        call    close_at
        di
        ld      a,1
        ld      (seen_wrong),a
        call    next_game
        di
        jr      nc,unlock
        jp      refuse_game

; s[n] = n.
state_new:
        ld      hl,rc4_s
        xor     a
.fill:  ld      (hl),a
        inc     hl
        inc     a
        jr      nz,.fill
        ld      (s_i),a
        ld      (s_j),a
        ret

; The state made so far becomes the base that streams start from.
state_keep:
        ld      hl,rc4_s
        ld      de,rc4_base
        ld      bc,256
        ldir
        ld      a,(s_i)
        ld      (base_i),a
        ld      a,(s_j)
        ld      (base_j),a
        ret

; Keyed by the master key: nonce, key, nonce, KEY_ROUNDS times.
make_master:
        call    state_new
        ld      b,KEY_ROUNDS
.round: push    bc
        ld      hl,nonce
        ld      bc,16
        call    rc4_absorb
        ld      hl,tgt_key
        ld      bc,16
        call    rc4_absorb
        ld      hl,nonce
        ld      bc,16
        call    rc4_absorb
        pop     bc
        djnz    .round
        jr      state_keep

; Keyed by the game: nonce, the whole file, nonce.
absorb_game:
        call    state_new
        ld      hl,nonce
        ld      bc,16
        call    rc4_absorb
        call    src_game
        ld      a,(gh)
        ld      hl,zero32
        ld      de,gsize
        call    absorb_range
        ld      hl,nonce
        ld      bc,16
        call    rc4_absorb
        jr      state_keep

; Absorb file A from the position at HL, for the length at DE. The source is plain.
absorb_range:
        ld      (src_handle),a
        push    de
        call    seek_file
        pop     hl
        ld      de,src_left
        call    copy4
.chunk: ld      hl,src_left
        call    is_zero32
        ret     z
        call    src_refill
        call    src_avail
        call    rc4_absorb
        jr      .chunk

; The keyed check: under the master state, CHK1 and 0, then the file but for the check
; field; 256 dropped; the next 16 must be the field. Then OUT1, which is all right to read.
check_file:
        ld      de,magic_chk1
        ld      c,0
        call    stream_start
        call    use_iobuf
        xor     a
        ld      (src_crypt),a
        ld      hl,msg_damaged
        ld      (src_bad),hl
        ld      a,(ph)
        ld      hl,zero32
        ld      de,check_at
        call    absorb_range
        ld      hl,psize
        ld      de,left
        call    copy4
        ld      hl,left
        ld      de,file_header
        call    sub32
        ld      a,(ph)
        ld      hl,file_header
        ld      de,left
        call    absorb_range
        call    stream_drop
        ld      hl,check_at
        call    seek_patch
        ld      hl,check_buf
        ld      bc,16
        call    read_patch
        ld      hl,check_buf
        ld      bc,16
        call    rc4_xor
        ld      hl,check_buf
        ld      b,16
.cmp:   ld      a,(hl)
        or      a
        jp      nz,bad_patch
        inc     hl
        djnz    .cmp
        ld      de,magic_out1
        ld      c,0
        call    stream_open
        ld      hl,out_rec
        call    seek_patch
        ld      hl,out_buf
        ld      bc,8
        call    read_patch
        ld      hl,out_buf
        ld      bc,8
        call    rc4_xor
        ld      hl,out_buf
        ld      de,want
        ld      bc,8
        ldir
        ret

; BC = what is in the buffer from HL.
src_avail:
        ld      a,(src_end_hi)
        ld      b,a
        ld      c,0
        push    hl
        ex      de,hl
        ld      h,b
        ld      l,c
        or      a
        sbc     hl,de
        ld      b,h
        ld      c,l
        pop     hl
        ret

; Encrypted, from the patch, with damage reported as the patch's.
src_patch:
        call    use_iobuf
src_patch_crypt:
        ld      a,1
        ld      hl,msg_damaged
        jr      src_kind
; Plain, from the game, with damage reported as the game's.
src_game:
        call    use_iobuf
        xor     a
        ld      hl,msg_game_bad
src_kind:
        ld      (src_crypt),a
        ld      (src_bad),hl
        ret

use_smallbuf:
        ld      a,SMALLBUF_END_HI
        ld      hl,SMALLBUF_SIZE
        jr      use_buf
use_iobuf:
        ld      a,IOBUF_END_HI
        ld      hl,IOBUF_SIZE
use_buf:
        ld      (src_end_hi),a
        ld      (src_chunk),hl
        ret

; ------------------------------------------------------------------- key stream

; The stream for one use: DE a tag, C its index.
stream_open:
        call    stream_start
stream_drop:
        ld      hl,smallbuf                 ; the first 256 go nowhere that matters
        ld      bc,256
        jr      rc4_xor

; A copy of the base with the tag and index absorbed.
stream_start:
        ld      hl,tmp5
        ex      de,hl
        push    bc
        call    copy4
        pop     bc
        ld      a,c
        ld      (de),a
        ld      hl,rc4_base
        ld      de,rc4_s
        ld      bc,256
        ldir
        ld      a,(base_i)
        ld      (s_i),a
        ld      a,(base_j)
        ld      (s_j),a
        ld      hl,tmp5
        ld      bc,5
        jp      rc4_absorb

; XOR BC bytes at HL with the stream.
rc4_xor:
        ld      a,b
        or      c
        ret     z
        push    hl
        pop     ix
        ld      a,(s_i)
        ld      e,a
        ld      d,high rc4_s
        ld      a,(s_j)
        ld      l,a
        ld      h,d
.byte:  inc     e
        ld      a,(de)
        add     a,l
        ld      l,a
        push    bc
        ld      a,(de)                      ; s[i]
        ld      c,a
        ld      b,(hl)                      ; s[j]
        ld      (hl),c
        ld      a,b
        ld      (de),a
        add     a,c
        ld      c,a
        ld      b,d
        ld      a,(bc)
        xor     (ix+0)
        ld      (ix+0),a
        inc     ix
        pop     bc
        dec     bc
        ld      a,b
        or      c
        jr      nz,.byte
        ld      a,e
        ld      (s_i),a
        ld      a,l
        ld      (s_j),a
        ret

; Absorb BC bytes at HL into the state.
rc4_absorb:
        ld      a,b
        or      c
        ret     z
        push    hl
        pop     ix
        ld      a,(s_i)
        ld      e,a
        ld      d,high rc4_s
        ld      a,(s_j)
        ld      l,a
        ld      h,d
.byte:  inc     e
        ld      a,(de)
        add     a,l
        add     a,(ix+0)
        ld      l,a
        inc     ix
        ld      a,(de)                      ; swap s[i], s[j]
        ex      af,af'
        ld      a,(hl)
        ld      (de),a
        ex      af,af'
        ld      (hl),a
        dec     bc
        ld      a,b
        or      c
        jr      nz,.byte
        ld      a,e
        ld      (s_i),a
        ld      a,l
        ld      (s_j),a
        ret

; -------------------------------------------------------------------- CRC-32

; The tables, in the I/O page.
crc_make:
        ld      c,0
.n:     ld      e,c
        ld      d,0
        ld      l,d
        ld      h,d
        ld      b,8
.bit:   srl     h
        rr      l
        rr      d
        rr      e
        jr      nc,.skip
        ld      a,h
        xor     $ed
        ld      h,a
        ld      a,l
        xor     $b8
        ld      l,a
        ld      a,d
        xor     $83
        ld      d,a
        ld      a,e
        xor     $20
        ld      e,a
.skip:  djnz    .bit
        push    hl                          ; bytes 2, 3
        ld      l,c
        ld      h,high CRC_T0
        ld      (hl),e
        inc     h
        ld      (hl),d
        pop     de
        inc     h
        ld      (hl),e
        inc     h
        ld      (hl),d
        inc     c
        jr      nz,.n
        ret

; Run BC bytes at HL through the CRC at crc.
crc_update:
        push    hl
        push    bc
        exx
        pop     bc
        pop     hl
        exx
        ld      de,(crc)
        ld      bc,(crc+2)
.byte:  exx
        ld      a,b
        or      c
        jr      z,.end
        dec     bc
        ld      a,(hl)
        inc     hl
        exx
        xor     e
        ld      l,a
        ld      h,high CRC_T0
        ld      a,(hl)
        xor     d
        ld      e,a
        inc     h
        ld      a,(hl)
        xor     c
        ld      d,a
        inc     h
        ld      a,(hl)
        xor     b
        ld      c,a
        inc     h
        ld      b,(hl)
        jp      .byte
.end:   exx
        ld      (crc),de
        ld      (crc+2),bc
        ret

; ------------------------------------------------------------------ the source

; Bytes from a file, through the key stream if src_crypt, in chunks that end
; at the end of the buffer. HL is the read pointer; a buffer it has reached the
; end of is refilled. src_get is what all the decoders use.

; Start reading: A the file, the record at HL (position, length) as the source.
; HL comes back at the end of the empty buffer.
src_open:
        ld      (src_handle),a
        push    hl
        call    seek_file
        pop     hl
        ld      de,4
        add     hl,de
        ld      de,src_left
        call    copy4
src_empty:
        ld      a,(src_end_hi)
        ld      h,a
        ld      l,0
        ret

; A = the next byte; HL moves on. BC and DE are kept.
src_get:
        ld      a,(src_end_hi)
        cp      h
        jr      z,.refill
        ld      a,(hl)
        inc     hl
        ret
.refill:
        call    src_refill
        ld      a,(hl)
        inc     hl
        ret

; Fill the buffer's end with up to a chunk; HL at its start, A kept. Nothing
; left is the source's damage.
src_refill:
        push    af
        push    bc
        push    de
        ld      hl,(src_left+2)
        ld      a,h
        or      l
        ld      bc,(src_chunk)
        jr      nz,.got
        ld      hl,(src_left)
        ld      a,h
        or      l
        jr      nz,.some
        ld      hl,(src_bad)
        jp      fail_hl
.some:  or      a
        sbc     hl,bc
        jr      nc,.got
        ld      bc,(src_left)
.got:   ld      hl,src_left                 ; what is left comes down
        ld      a,(hl)
        sub     c
        ld      (hl),a
        inc     hl
        ld      a,(hl)
        sbc     a,b
        ld      (hl),a
        inc     hl
        ld      a,(hl)
        sbc     a,0
        ld      (hl),a
        inc     hl
        ld      a,(hl)
        sbc     a,0
        ld      (hl),a
        ld      a,(src_end_hi)
        ld      h,a
        ld      l,0
        or      a
        sbc     hl,bc                       ; HL = the chunk's start
        push    hl
        push    bc
        ld      a,(src_handle)
        ld      de,(src_bad)
        call    read_exact
        pop     bc
        pop     hl
        push    hl
        ld      a,(src_crypt)
        or      a
        call    nz,rc4_xor
        pop     hl
        pop     de
        pop     bc
        pop     af
        ret

; Copy BC bytes from the source to DE, across as many refills as it takes.
src_copy:
        push    af
.more:  ld      a,b
        or      c
        jr      z,.end
        ld      a,(src_end_hi)
        cp      h
        call    z,src_refill
        push    bc                          ; wanted
        push    de                          ; destination
        ld      d,a                         ; the buffer's end (A kept by the refill)
        ld      e,0
        ex      de,hl
        or      a
        sbc     hl,de                       ; HL = what there is
        ex      de,hl                       ; DE = that, HL = the source
        push    hl
        ld      h,b
        ld      l,c
        or      a
        sbc     hl,de
        jr      nc,.part
        ld      d,b                         ; all that is wanted is there
        ld      e,c
.part:  pop     hl
        ld      b,d
        ld      c,e                         ; BC = this time's count
        pop     de
        ex      (sp),hl                     ; HL = wanted; stack = the source
        or      a
        sbc     hl,bc
        ex      (sp),hl                     ; stack = wanted now; HL = the source
        ldir
        pop     bc
        jr      .more
.end:   pop     af
        ret

; ------------------------------------------------------------------- ZX0

; Decode a stream from the source to DE, which must stay below zx_end. A ZX0
; stream that is longer, that copies from before zx_start, that runs out, or
; that leaves bytes over, is damage: nothing reaches outside the buffer.
; Standard format, version 2. DE comes back after the last byte.
zx0_decode:
        ld      hl,$ffff
        ld      (zx_last),hl
        call    src_empty
        ld      bc,0
        ld      a,$80
.literals:
        call    .elias
        call    .room
        call    src_copy
        add     a,a
        jr      c,.new_offset
        ld      bc,0
        call    .elias
.copy:  call    .room
        push    af
        push    hl
        ld      h,d                         ; produced + (negative offset) must carry
        ld      l,e
        push    de
        ld      de,(zx_start)
        or      a
        sbc     hl,de
        ld      de,(zx_last)
        add     hl,de
        pop     de
        jp      nc,.bad
        ld      hl,(zx_last)
        add     hl,de
        ldir
        pop     hl
        pop     af
        add     a,a
        ld      bc,0
        jr      nc,.literals
.new_offset:
        ld      c,$fe
.msb:   add     a,a
        jr      nz,.msb1
        call    src_get
        scf
        rla
.msb1:  jr      c,.msb_end
        add     a,a
        rl      c
        jr      .msb
.msb_end:
        inc     c
        jr      z,.end
        ld      b,c
        push    af
        call    src_get
        ld      c,a
        pop     af
        rr      b
        rr      c
        ld      (zx_last),bc
        ld      bc,1
        call    nc,.back
        inc     bc
        jr      .copy
.end:   ; the marker: nothing may be left over
        ld      a,(src_end_hi)
        cp      h
        jr      nz,.bad
        ld      a,l
        or      a
        jr      nz,.bad
        ld      hl,src_left
        call    is_zero32
        ret     z
.bad:   ld      hl,msg_damaged
        jp      fail_hl
.elias: inc     c
.loop:  add     a,a
        jr      nz,.skip
        call    src_get
        scf
        rla
.skip:  ret     c
.back:  add     a,a
        rl      c
        rl      b
        jr      nc,.loop
        jr      .bad
; BC bytes more at DE must be possible, and BC not zero. Keeps all but flags.
.room:  push    af
        ld      a,b
        or      c
        jr      z,.bad
        push    hl
        ld      h,d
        ld      l,e
        add     hl,bc
        jr      c,.bad
        push    de
        ld      de,(zx_end)
        or      a
        sbc     hl,de
        pop     de
        jr      z,.fits
        jr      nc,.bad
.fits:  pop     hl
        pop     af
        ret

; Where a decode is bounded: from DE, up to HL.
zx_bounds:
        ld      (zx_end),hl
        ld      (zx_start),de
        ret

; A block from the patch, tag DE, index C, place HL, through its key stream
; into the bounds set by zx_bounds; DE comes back after the last byte.
block_decode:
        push    hl
        call    stream_open
        pop     hl
; The same with the stream already open.
block_decode_open:
        ld      a,(ph)
        call    src_open
        ld      de,(zx_start)
        jp      zx0_decode

; NEX1 into HDR: exactly 512 bytes.
decode_nex_header:
        call    src_patch
        ld      de,HDR
        ld      hl,HDR+512
        call    zx_bounds
        ld      de,magic_nex1
        ld      c,0
        ld      hl,nex_rec
        call    block_decode
        ld      hl,HDR+512
        or      a
        sbc     hl,de
        jp      nz,bad_patch
        ld      hl,HDR
        ld      de,nex_magic
        call    same_tag
        ret     z
        jp      bad_patch

; A table into its three pages (page_list at t_base): the record at HL, tag DE,
; index C. HL comes back with its length, the pages still mapped.
decode_table:
        push    hl
        push    de
        push    bc
        call    use_smallbuf
        call    src_patch_crypt
        pop     bc
        pop     de
        call    stream_open                 ; before the table's pages cover the base
        ld      hl,(t_base)
        call    map3
        ld      de,WORK
        ld      hl,TABLE_END
        call    zx_bounds
        pop     hl
        call    block_decode_open
        ex      de,hl
        ld      de,WORK
        or      a
        sbc     hl,de
        ret

; SIT1. sit_len: its length, 0 if the block is empty.
decode_sites:
        ld      hl,sit_rec+4
        call    is_zero32
        ret     z
        ld      hl,page_list+3
        ld      (t_base),hl
        ld      hl,sit_rec
        ld      de,magic_sit1
        ld      c,0
        call    decode_table
        push    hl
        call    map_std
        pop     hl
        ld      (sit_len),hl
        ld      de,2                        ; a count, at least
        or      a
        sbc     hl,de
        ret     nc
        jp      bad_patch

; The chosen sets, before any file is made: each one's CRC taken into what the output must
; be, then every chunk of each decoded and checked in the order they will be needed. A chunk
; in the wrong order, or for a bank the header does not list, is never reached, and being left
; over is damage. As they touch different bytes and the file's length and layout are the same:
; CRC(all) = CRC(base) XOR each (CRC(set) XOR CRC(base)).
check_sets:
        ld      a,(set_choices)
        ld      hl,set_choices+1
        or      (hl)
        ret     z
        ld      a,1
        call    sets_open
        ld      b,0
.order: push    bc
        call    order_bank
        call    header_has
        call    nz,bank_sets
        pop     bc
        inc     b
        ld      a,b
        cp      112
        jr      c,.order
        ld      hl,set_recs+4
        call    is_zero32
        jp      nz,bad_patch
        ld      hl,set_recs+REC+4
        call    is_zero32
        jp      nz,bad_patch
        xor     a                           ; from the start again, to write
; Each chosen set's cursor at its first chunk, and its pages. A not 0: its CRC taken in too.
sets_open:
        ld      (set_crc_too),a
        ld      hl,'S' + 'E' * 256
        ld      (set_tag),hl
        ld      a,'B'
        ld      (set_tag+2),a
        ld      hl,page_list+3+SET_PAGES
        ld      (next_base),hl
        xor     a
.kind:  ld      (cur_kind),a
        ld      c,a
        ld      b,0
        ld      hl,set_choices
        add     hl,bc
        ld      a,(hl)
        or      a
        jp      z,.none
        ld      (cur_n),a
        ld      hl,(next_base)
        ld      (t_base),hl
        ld      de,SET_PAGES
        add     hl,de
        ld      (next_base),hl
        call    find_set
        ld      a,(tagbuf+4)                ; past its fixed part and name
        add     a,SET_FIXED
        ld      l,a
        ld      h,0
        ld      (left),hl
        ld      l,h
        ld      (left+2),hl
        ld      hl,blk_pos
        ld      de,left
        call    add32
        ld      hl,blk_len
        ld      de,left
        call    sub32
        ld      hl,blk_len                  ; a CRC, at least
        ld      de,four
        call    sub32
        jp      c,bad_patch
        ld      a,(set_crc_too)
        or      a
        jr      z,.past
        ld      a,(cur_stream)
        ld      (set_tag+3),a
        ld      de,set_tag
        ld      c,SET_CRC_INDEX
        call    stream_open
        ld      hl,blk_pos
        call    seek_patch
        ld      hl,tmp5
        ld      bc,4
        call    read_patch
        ld      hl,tmp5
        ld      bc,4
        call    rc4_xor
        ld      hl,want
        ld      de,tmp5
        ld      bc,out_buf
        ld      a,4
.xor:   push    af
        ld      a,(bc)
        ex      de,hl
        xor     (hl)
        ex      de,hl
        xor     (hl)
        ld      (hl),a
        inc     hl
        inc     de
        inc     bc
        pop     af
        dec     a
        jr      nz,.xor
.past:  ld      hl,blk_pos
        ld      de,four
        call    add32
        call    rec_of_kind
        ex      de,hl
        ld      hl,blk_pos
        ld      bc,8
        ldir
        ld      a,(cur_stream)
        ld      (de),a
        ld      a,(cur_kind)
        add     a,a
        ld      c,a
        ld      b,0
        ld      hl,set_bases
        add     hl,bc
        ld      de,(t_base)
        ld      (hl),e
        inc     hl
        ld      (hl),d
.none:  ld      a,(cur_kind)
        inc     a
        cp      KINDS
        jp      c,.kind
        ret

; HL at kind (cur_kind)'s cursor.
rec_of_kind:
        ld      hl,set_recs
        ld      a,(cur_kind)
        or      a
        ret     z
        ld      hl,set_recs+REC
        ret

; t_base and t_len for kind (cur_kind). Z when it is not chosen.
set_of_kind:
        ld      a,(cur_kind)
        add     a,a
        ld      e,a
        ld      d,0
        ld      hl,set_lens
        add     hl,de
        ld      c,(hl)
        inc     hl
        ld      b,(hl)
        ld      (t_len),bc
        ld      hl,set_bases
        add     hl,de
        ld      c,(hl)
        inc     hl
        ld      b,(hl)
        ld      (t_base),bc
        ld      a,b
        or      c
        ret

; Bank (cur_bank): the chunk of each chosen set that has one, decoded and checked. Sets chosen
; together must touch different bytes, even if they write the same: that is what lets their
; CRCs be combined. So no bit may be set in both bitmaps.
bank_sets:
        xor     a
.kind:  ld      (cur_kind),a
        call    set_of_kind
        call    nz,next_chunk
        ld      a,(cur_kind)
        inc     a
        cp      KINDS
        jr      c,.kind
        ld      hl,(set_lens)
        ld      a,h
        or      l
        ret     z
        ld      hl,(set_lens+2)
        ld      a,h
        or      l
        ret     z
        ld      hl,(set_bases)
        ld      e,(hl)
        ld      a,NR_MMU4
        call    nr_write
        ld      hl,(set_bases+2)
        ld      a,(hl)
        call    map_slot5
        ld      hl,$8000
        ld      de,$a000
        ld      bc,BITMAP
.both:  ld      a,(de)
        and     (hl)
        jp      nz,bad_patch
        inc     hl
        inc     de
        dec     bc
        ld      a,b
        or      c
        jr      nz,.both
        jp      map_std

; Kind (cur_kind)'s next chunk, if it is for bank (cur_bank), into its pages: 1 byte bank, 2
; bytes stream length, the stream. It must be a bitmap and exactly as many bytes as the bitmap
; has bits, at least one. t_base is the kind's. Its length goes in set_lens, or 0 if none.
next_chunk:
        ld      hl,0
        call    set_chunk_len
        call    rec_of_kind
        ld      de,blk_pos
        ld      bc,8
        ldir
        ld      a,(hl)
        ld      (set_tag+3),a
        ld      hl,blk_len
        call    is_zero32
        ret     z
        ld      hl,blk_len
        ld      de,three
        call    sub32
        jp      c,bad_patch
        ld      hl,blk_pos
        call    seek_patch
        ld      hl,tagbuf
        ld      bc,3
        call    read_patch
        ld      a,(cur_bank)
        ld      hl,tagbuf
        cp      (hl)
        ret     nz
        ld      hl,blk_pos
        ld      de,three
        call    add32
        ld      hl,(tagbuf+1)
        ld      (work32),hl
        ld      hl,0
        ld      (work32+2),hl
        ld      hl,blk_len                  ; it must fit in what is left of the block
        ld      de,work32
        call    sub32
        jp      c,bad_patch
        ld      hl,blk_pos                  ; the cursor goes past it
        ld      de,work32
        call    add32
        call    rec_of_kind
        ex      de,hl
        ld      hl,blk_pos
        ld      bc,8
        ldir
        ld      hl,blk_pos                  ; and the stream is the source
        ld      de,work32
        call    sub32
        ld      hl,work32
        ld      de,blk_len
        call    copy4
        ld      a,(cur_bank)
        ld      c,a
        ld      hl,blk_pos
        ld      de,set_tag
        call    decode_table
        push    hl
        ld      de,BITMAP+1
        or      a
        sbc     hl,de
        jp      c,bad_patch
        ex      de,hl
        inc     de                          ; DE: the bytes after the bitmap
        ld      hl,WORK
.byte:  ld      a,(hl)
.bit:   add     a,a
        jr      nc,.clear
        dec     de
.clear: jr      nz,.bit
        inc     hl
        ld      a,h
        cp      high (WORK+BITMAP)
        jr      nz,.byte
        ld      a,d
        or      e
        jp      nz,bad_patch
        call    map_std
        pop     hl
; HL is kind (cur_kind)'s chunk's length.
set_chunk_len:
        ex      de,hl
        ld      a,(cur_kind)
        add     a,a
        ld      c,a
        ld      b,0
        ld      hl,set_lens
        add     hl,bc
        ld      (hl),e
        inc     hl
        ld      (hl),d
        ret

; Bank (cur_bank) with each chosen set's chunk applied. A set bit in the bitmap takes the next
; byte: nothing else says where a byte goes, so no chunk can reach outside WORK.
apply_sets:
        xor     a
.kind:  ld      (cur_kind),a
        call    set_of_kind
        jr      z,.next
        ld      hl,(t_len)
        ld      a,h
        or      l
        call    nz,apply_chunk
.next:  ld      a,(cur_kind)
        inc     a
        cp      KINDS
        jr      c,.kind
        jp      map_iopage

apply_chunk:
        ld      hl,0
        ld      (a_off),hl
        ld      hl,BITMAP
        ld      (b_off),hl
        ld      de,WORK
.byte:  push    de
        ld      hl,(a_off)
        ld      (t_off),hl
        inc     hl
        ld      (a_off),hl
        call    t_seek
        ld      c,(hl)
        ld      a,c
        or      a
        jr      z,.none
        push    bc
        ld      hl,(b_off)
        ld      (t_off),hl
        call    t_seek
        pop     bc
        pop     de
        ld      b,8
.bit:   sla     c
        jr      nc,.keep
        call    t_get
        ld      (de),a
.keep:  inc     de
        djnz    .bit
        ld      a,(t_page)                  ; where the next value is, as an offset
        rrca
        rrca
        rrca
        ld      b,a
        ld      a,h
        and     $1f
        or      b
        ld      h,a
        ld      (b_off),hl
        jr      .more
.none:  pop     de
        ex      de,hl
        ld      bc,8
        add     hl,bc
        ex      de,hl
.more:  ld      a,(a_off+1)
        cp      high BITMAP
        jr      nz,.byte
        ret

; ---------------------------------------------------------------- the patch's banks

; IX at bank (cur_bank)'s entry in the index; Z when the patch has no such bank.
bank_index_entry:
        ld      a,(cur_bank)
        ld      l,a
        ld      h,0
        ld      d,h
        ld      e,l
        add     hl,hl
        add     hl,hl
        add     hl,de
        add     hl,hl                       ; x 10
        ld      de,BANK_INDEX
        add     hl,de
        push    hl
        pop     ix
        ld      a,(ix+0)
        or      (ix+1)
        or      (ix+2)
        or      (ix+3)
        ret

; Walk the file again for its BNK1 blocks: refuse bad lengths, bad banks, a
; bank given twice. Nothing is decompressed.
load_bank_index:
        call    walk_begin
.next:  call    walk_next
        ret     z
        ld      de,magic_bnk1
        call    tag_is
        jr      nz,.next
        ld      hl,blk_len                  ; bank number and length, at least
        ld      bc,0
        ld      de,3
        call    below32
        jp      c,bad_patch
        ld      hl,tagbuf
        ld      bc,3
        call    read_patch
        ld      a,(tagbuf)
        cp      112
        jp      nc,bad_patch
        ld      (cur_bank),a
        ld      hl,(tagbuf+1)               ; at most a bank
        ld      de,BANK_SIZE+1
        or      a
        sbc     hl,de
        jp      nc,bad_patch
        call    bank_index_entry
        jp      nz,bad_patch                ; given twice
        ld      hl,(tagbuf+1)
        ld      (ix+8),l
        ld      (ix+9),h
        ld      hl,blk_len                  ; the stream's length: the rest
        ld      de,three
        call    sub32
        ld      a,(ix+8)
        or      (ix+9)
        jr      nz,.has
        ld      hl,blk_len                  ; no data: none may follow
        call    is_zero32
        jp      nz,bad_patch
.has:   ld      hl,blk_pos
        ld      de,three
        call    add32
        ld      hl,blk_pos
        push    ix
        pop     de
        ld      bc,8
        ldir
        jp      .next

; Bank (cur_bank) from the patch into WORK, zeros to its end.
decode_patch_bank:
        call    bank_index_entry
        ld      l,(ix+8)
        ld      h,(ix+9)
        ld      a,h
        or      l
        ld      de,WORK
        jr      z,fill_zeros
        add     hl,de
        call    zx_bounds
        call    src_patch
        ld      de,magic_bnk1
        ld      a,(cur_bank)
        ld      c,a
        push    ix
        pop     hl
        call    block_decode
        ld      hl,(zx_end)
        or      a
        sbc     hl,de
        jp      nz,bad_patch
; Zeros from DE to the end of WORK.
fill_zeros:
        ld      hl,WORK_END
        or      a
        sbc     hl,de
        ld      a,h
        or      l
        ret     z
        ld      b,h
        ld      c,l
        ld      h,d
        ld      l,e
        ld      (hl),0
        inc     de
        dec     bc
        ld      a,b
        or      c
        ret     z
        ldir
        ret

; ------------------------------------------------------------- the snapshot

; The .z80's header, where its pages are. The same rules as NexClash's reader,
; as tools/nxc.py uses it: version 1 is PC not 0, a 48K block; otherwise the
; extended header, then pages. Hardware modes say 48K or 128K.
parse_game:
        ld      hl,zero32
        ld      a,(gh)
        call    seek_file
        ld      bc,0
        ld      de,30
        ld      hl,gsize
        call    below32
        jp      c,bad_game
        ld      hl,head
        ld      bc,30
        call    read_game
        ld      hl,(head+6)
        ld      a,h
        or      l
        jp      z,.v2
        ld      a,1                         ; version 1
        ld      (z80_v1),a
        ld      hl,30
        ld      (z80_head_len),hl
        ld      a,(head+12)
        cp      255
        jr      nz,.f
        ld      a,1
.f:     and     $20
        ld      (z80_packed),a
        ; v1: from offset 30, to the file's end (without the end marker)
        ld      hl,30
        ld      (v1_pos),hl
        ld      l,h
        ld      (v1_pos+2),hl
        ld      hl,gsize
        ld      de,v1_end
        call    copy4
        ld      a,(z80_packed)
        or      a
        jr      z,.v1_end
        ld      bc,0
        ld      de,34
        ld      hl,gsize
        call    below32
        jr      c,.v1_end
        ld      hl,gsize
        ld      de,work32
        call    copy4
        ld      hl,work32
        ld      de,four
        call    sub32
        ld      hl,work32
        ld      a,(gh)
        call    seek_file
        ld      hl,tmp5
        ld      bc,4
        call    read_game
        ld      hl,tmp5
        ld      de,z80_marker
        call    same_tag
        jr      nz,.v1_end
        ld      hl,work32
        ld      de,v1_end
        call    copy4
.v1_end:
        ld      a,1                         ; banks 5, 2, 0 by flag, in the v1 order
        ld      (game_pages+5*6+4),a
        ld      (game_pages+2*6+4),a
        ld      (game_pages+0*6+4),a
        ret
.v2:    ld      hl,tmp5                     ; the extended header's length
        ld      bc,2
        call    read_game
        ld      hl,head+30
        ld      de,(tmp5)
        ld      (hl),e
        inc     hl
        ld      (hl),d
        ld      hl,32                       ; 32 + length, bounded
        add     hl,de
        ld      (z80_head_len),hl
        ld      bc,128 + 32 + 1
        or      a
        sbc     hl,bc
        jp      nc,bad_game
        ld      a,d
        or      a
        jp      nz,bad_game
        ld      a,e
        cp      3
        jp      c,bad_game                  ; no PC, no mode
        ld      hl,smallbuf                 ; PC, hardware mode, ...
        ld      b,0
        ld      c,e
        call    read_game
        ld      a,(smallbuf+2)
        ld      c,a
        ld      a,(tmp5)
        cp      23
        ld      a,c
        jr      nz,.v3
        ld      hl,table_128k_v2
        ld      b,2
        jr      .is128
.v3:    ld      hl,table_128k_v3
        ld      b,7
.is128: cp      (hl)
        jr      z,.yes
        inc     hl
        djnz    .is128
        jr      .pages
.yes:   ld      a,1
        ld      (z80_128),a
.pages: ld      hl,(z80_head_len)           ; walk the pages
        ld      (pos),hl
        ld      hl,0
        ld      (pos+2),hl
.page:  ld      hl,gsize
        ld      de,left
        call    copy4
        ld      hl,left
        ld      de,pos
        call    sub32
        ld      hl,left
        call    is_zero32
        jr      z,.walked
        ld      hl,left
        ld      de,three
        call    sub32
        jp      c,bad_game
        ld      hl,pos
        ld      a,(gh)
        call    seek_file
        ld      hl,tmp5
        ld      bc,3
        call    read_game
        ld      hl,pos
        ld      de,three
        call    add32
        ld      hl,(tmp5)                   ; 0xFFFF: 16384 raw
        ld      (work32),hl
        ld      hl,0
        ld      (work32+2),hl
        ld      hl,(tmp5)
        ld      a,h
        and     l
        inc     a
        jr      nz,.len
        ld      hl,BANK_SIZE
        ld      (work32),hl
.len:   ld      hl,left
        ld      de,work32
        call    sub32
        jp      c,bad_game
        call    .note_page
        ld      hl,pos
        ld      de,work32
        call    add32
        jr      .page
.walked:
        ld      a,(z80_128)                 ; all the banks it must have
        or      a
        ld      hl,pages_48k+1
        ld      b,3
        jr      z,.need
        ld      hl,pages_128k+1
        ld      b,8
.need:  ld      a,(hl)
        push    hl
        call    game_has
        pop     hl
        jr      nc,bad_game
        inc     hl
        inc     hl
        djnz    .need
        ret
; tmp5: length, page. pos: its data. The bank it holds, if any, in game_pages.
.note_page:
        ld      a,(tmp5+2)
        ld      c,a
        ld      a,(z80_128)
        or      a
        jr      z,.p48
        ld      a,c
        sub     3
        ret     c
        cp      8
        ret     nc
        jr      .store
.p48:   ld      a,c
        cp      8
        ld      a,5
        jr      z,.store
        ld      a,c
        cp      4
        ld      a,2
        jr      z,.store
        ld      a,c
        cp      5
        ret     nz
        xor     a
.store: call    page_entry
        ex      de,hl
        ld      hl,pos
        call    copy4
        ex      de,hl
        ld      bc,(tmp5)
        ld      (hl),c
        inc     hl
        ld      (hl),b                      ; (a length of 0 reads as no bank:
        ret                                 ;  it can never make one)
table_128k_v2:
        db      3, 4
table_128k_v3:
        db      4, 5, 6, 7, 9, 12, 13

; HL at bank A's entry in game_pages.
page_entry:
        add     a,a
        ld      l,a
        add     a,a
        add     a,l
        ld      l,a
        ld      h,0
        ld      de,game_pages
        add     hl,de
        ret

; Carry when the snapshot has bank A. Keeps BC.
game_has:
        cp      8
        ret     nc
        push    bc
        call    page_entry
        ld      de,4
        add     hl,de
        ld      a,(hl)
        inc     hl
        or      (hl)
        pop     bc
        ret     z                           ; none: carry clear from the OR
        scf
        ret

bad_game:
        ld      hl,msg_game_bad
        jp      fail_hl

; Bank (cur_bank) of the game into WORK.
decode_game_bank:
        call    src_game
        ld      a,(z80_v1)
        or      a
        jr      nz,.v1
        ld      a,(cur_bank)
        call    page_entry
        ld      a,(gh)
        ld      (src_handle),a
        push    hl
        call    seek_file
        pop     hl
        ld      de,4
        add     hl,de
        ld      e,(hl)
        inc     hl
        ld      d,(hl)
        ld      a,d                         ; 0xFFFF: 16384 raw
        and     e
        inc     a
        jr      z,.raw
        ld      (src_left),de
        ld      hl,0
        ld      (src_left+2),hl
        call    src_empty
        ld      de,WORK
        xor     a
        ld      (run_n),a
        call    unpack                      ; the whole page, exactly 16K
        ld      hl,WORK_END
        or      a
        sbc     hl,de
        ret     z
        jr      bad_game
.raw:   ld      hl,BANK_SIZE
        ld      (src_left),hl
        ld      hl,0
        ld      (src_left+2),hl
        call    src_empty
        ld      de,WORK
        ld      bc,BANK_SIZE
        jp      src_copy
.v1:    ; one stream: on from where the last bank stopped
        ld      hl,v1_pos
        ld      a,(gh)
        ld      (src_handle),a
        call    seek_file
        ld      hl,v1_end
        ld      de,src_left
        call    copy4
        ld      hl,src_left
        ld      de,v1_pos
        call    sub32
        call    src_empty
        ld      de,WORK
        ld      a,(z80_packed)
        or      a
        jr      nz,.v1_packed
        ld      bc,BANK_SIZE
        call    src_copy
        jr      .v1_stop
.v1_packed:
        call    unpack_to_full
        ld      a,d                         ; a full bank, or the file was short
        cp      high WORK_END
        jp      nz,bad_game
.v1_stop:
        ; v1_pos = v1_end - what is unread - what is in the buffer
        push    hl
        call    src_avail
        pop     hl
        ld      (work32),bc
        ld      bc,0
        ld      (work32+2),bc
        ld      hl,work32
        ld      de,src_left
        call    add32
        ld      hl,v1_end
        ld      de,v1_pos
        call    copy4
        ld      hl,v1_pos
        ld      de,work32
        jp      sub32

; Carry clear, Z, when nothing is left in the source. HL is kept.
src_exhausted:
        ld      a,(src_end_hi)
        cp      h
        ret     nz
        ld      a,l
        or      a
        ret     nz
        push    hl
        ld      hl,src_left
        call    is_zero32
        pop     hl
        ret

; Carry when fewer than three bytes remain in the source.
few_left:
        push    hl
        push    de
        push    bc
        ld      a,(src_left+3)
        ld      c,a
        ld      a,(src_left+2)
        or      c
        ld      c,a
        ld      a,(src_left+1)
        or      c
        jr      nz,.end                     ; carry clear from the OR
        call    src_avail
        ld      a,(src_left)
        ld      l,a
        ld      h,0
        add     hl,bc
        ld      de,3
        or      a
        sbc     hl,de
.end:   pop     bc
        pop     de
        pop     hl
        ret

; A .z80 page's run-length data, into DE. unpack takes the whole source, and
; more output than the bank holds is refused. unpack_to_full stops when the
; bank is full, keeping a run that continues for the next.
unpack_to_full:
        ld      a,1
        jr      unpack_go
unpack: xor     a
unpack_go:
        ld      (unpack_stop),a
.next:  ld      a,(run_n)
        or      a
        jr      nz,.run
        ld      a,(unpack_stop)
        or      a
        jr      z,.src
        ld      a,d                         ; full?
        cp      high WORK_END
        ret     z
.src:   call    src_exhausted
        ret     z
        call    src_get
        cp      $ed
        jr      nz,.lit
        call    few_left                    ; ED ED n v takes three bytes more
        ld      a,$ed
        jr      c,.lit
        call    src_get
        cp      $ed
        jr      z,.pair
        ld      (run_v),a                   ; a lone ED, then a plain byte
        ld      a,1
        ld      (run_n),a
        ld      a,$ed
        jr      .lit
.pair:  call    src_get
        ld      (run_n),a
        call    src_get
        ld      (run_v),a
        jr      .next
.lit:   ld      c,a
        ld      a,d
        cp      high WORK_END
        jp      z,bad_game
        ld      a,c
        ld      (de),a
        inc     de
        jr      .next
.run:   ld      a,d                         ; a full bank with more to come
        cp      high WORK_END
        jr      nz,.fill
        ld      a,(unpack_stop)
        or      a
        ret     nz                          ; left for the next bank
        jp      bad_game
.fill:  ld      a,(run_v)
        ld      (de),a
        inc     de
        ld      a,(run_n)
        dec     a
        ld      (run_n),a
        jr      .next

; ------------------------------------------------------------- site table

; Map the table's byte t_off at 0xA000-0xBFFF; HL its address.
t_seek: ld      hl,(t_off)
        ld      a,h
        rlca
        rlca
        rlca
        and     7
        ld      (t_page),a
        call    t_map
        ld      hl,(t_off)
        ld      a,h
        and     $1f
        or      $a0
        ld      h,a
        ret

; Page A of the table at 0xA000.
t_map:  ld      e,a
        ld      d,0
        ld      hl,(t_base)
        add     hl,de
        ld      a,(hl)
        jp      map_slot5

; A = the table's next byte at HL, into the next page if need be. Keeps BC, DE.
t_get:  ld      a,(hl)
        inc     hl
        bit     6,h
        ret     z
        push    af
        push    bc
        push    de
        ld      a,(t_page)
        cp      2
        jr      nc,.last                    ; past the table: nothing more is read
        inc     a
        ld      (t_page),a
        call    t_map
.last:  ld      hl,$a000
        pop     de
        pop     bc
        pop     af
        ret

; Walk the sites. A=$FF: check every entry. Otherwise apply the entries of bank A
; to WORK. Leaves a table page mapped; the caller maps the I/O page again.
sites_walk:
        ld      (cur_site),a
        ld      hl,(sit_len)
        ld      (t_len),hl
        ld      hl,page_list+3
        ld      (t_base),hl
        ld      hl,(t_len)
        ld      a,h
        or      l
        ret     z
        ld      hl,0
        ld      (t_off),hl
        call    t_seek
        call    t_get
        ld      (t_count),a
        call    t_get
        ld      (t_count+1),a
        ld      hl,2
table_walk:
        ld      (t_off),hl
.site:  ld      hl,(t_count)
        ld      a,h
        or      l
        jp      z,.end
        dec     hl
        ld      (t_count),hl
        ld      hl,(t_len)                  ; five bytes, at least
        ld      de,(t_off)
        or      a
        sbc     hl,de
        ld      de,5
        or      a
        sbc     hl,de
        jp      c,bad_patch
        ld      (t_room),hl
        call    t_seek
        call    t_get
        ld      (site_bank),a
        call    t_get
        ld      (site_off),a
        call    t_get
        ld      (site_off+1),a
        call    t_get
        ld      (site_len),a
        call    t_get
        ld      (site_len+1),a
        push    hl
        ld      a,(cur_site)                ; its bank, in the checking walk
        inc     a
        jr      nz,.bank_done
        call    map_iopage
        ld      a,(site_bank)
        ld      c,a
        cp      8
        jp      nc,bad_patch
        call    game_has
        jp      nc,bad_patch
        ld      a,(site_bank)               ; a site is in a bank the build takes from the game
        call    header_has
        jp      z,bad_patch
        ld      a,(site_bank)
        ld      (cur_bank),a
        call    bank_index_entry
        jp      nz,bad_patch
.remap: ld      a,(t_page)
        call    t_map
.bank_done:
        ld      hl,(t_room)                 ; its data must be there
        ld      de,(site_len)
        or      a
        sbc     hl,de
        jp      c,bad_patch
        ld      hl,(site_off)               ; and within a bank
        add     hl,de
        jp      c,bad_patch
        ld      bc,BANK_SIZE+1
        or      a
        sbc     hl,bc
        jp      nc,bad_patch
        pop     hl
        ld      a,(cur_site)
        ld      c,a
        ld      a,(site_bank)
        cp      c
        jr      nz,.skip
        ld      de,(site_off)
        ld      a,d
        add     a,high WORK
        ld      d,a
        ld      bc,(site_len)
.byte:  ld      a,b
        or      c
        jr      z,.skip
        call    t_get
        ld      (de),a
        inc     de
        dec     bc
        jr      .byte
.skip:  ld      hl,(t_off)
        ld      de,5
        add     hl,de
        ld      de,(site_len)
        add     hl,de
        ld      (t_off),hl
        jp      .site
.end:   ld      a,(cur_site)                ; nothing may be left over
        inc     a
        ret     nz
        ld      hl,(t_len)
        ld      de,(t_off)
        or      a
        sbc     hl,de
        ret     z
        jp      bad_patch

; -------------------------------------------------------------- the POKEs

; The chosen trainers' POKEs into POKES, in the file's order. A=0: each must be
; in a bank the header lists (a .nex); A=1: in a bank the game has (a .z80).
load_pokes:
        ld      (poke_mode),a
        xor     a
        ld      (poke_count),a
        ld      a,(trainer_count)
        or      a
        ret     z
        ld      b,a
        ld      c,0
.t:     push    bc
        ld      a,c
        call    trainer_entry
        ld      a,(ix+0)
        or      a
        jr      z,.next
        ld      a,(poke_count)              ; room?
        ld      e,a
        ld      a,(ix+2)
        add     a,e
        ld      hl,msg_too_many
        jp      c,fail_hl
        cp      POKES_HELD + 1
        jp      nc,fail_hl
        ld      (poke_count),a
        ld      l,e                         ; to POKES + 4 x old count
        ld      h,0
        add     hl,hl
        add     hl,hl
        ld      de,POKES
        add     hl,de
        push    hl
        push    ix
        pop     hl
        ld      de,3
        add     hl,de
        call    seek_patch
        pop     hl
        ld      c,(ix+2)
        ld      b,0
        sla     c
        rl      b
        sla     c
        rl      b
        call    read_patch
.next:  pop     bc
        inc     c
        djnz    .t
        ld      a,(poke_count)              ; check them all
        or      a
        ret     z
        ld      b,a
        ld      hl,POKES
.check: ld      a,(hl)
        cp      112
        jp      nc,bad_patch
        inc     hl
        inc     hl
        ld      a,(hl)                      ; offset below 16384
        cp      $40
        jp      nc,bad_patch
        dec     hl
        dec     hl
        push    bc
        push    hl
        ld      a,(poke_mode)
        or      a
        ld      a,(hl)
        jr      nz,.game
        call    header_has
        jp      z,bad_patch
        jr      .fine
.game:  call    game_has
        jp      nc,bad_patch
.fine:  pop     hl
        pop     bc
        inc     hl
        inc     hl
        inc     hl
        inc     hl
        djnz    .check
        ret

; The POKEs of bank (cur_bank) into WORK, over any sets.
apply_pokes:
        ld      a,(poke_count)
        or      a
        ret     z
        ld      b,a
        ld      hl,POKES
.p:     ld      a,(cur_bank)
        cp      (hl)
        jr      nz,.no
        inc     hl
        ld      e,(hl)
        inc     hl
        ld      a,(hl)
        add     a,high WORK
        ld      d,a
        inc     hl
        ld      a,(hl)
        ld      (de),a
        inc     hl
        djnz    .p
        ret
.no:    inc     hl
        inc     hl
        inc     hl
        inc     hl
        djnz    .p
        ret

magic_bnk1:     db "BNK1"
magic_scr1:     db "SCR1"
msg_screen:     db "Patch needs a newer .NEXCLAS", 'H' | $80
magic_chk1:     db "CHK1"
wrap_check:     db "NXC1-KEY"
z80_marker:     db 0, $ed, $ed, 0
zero32:         dd 0
three:          dd 3
four:           dd 4
check_at:       dd 22
file_header:    dd FILE_HEADER
msg_ram:        db "Not enough free RAM: needs 48", 'K' | $80
msg_ram_set:    db "Needs 72K free RA", 'M' | $80
msg_ram_two:    db "Needs 96K free RA", 'M' | $80
msg_write:      db "Cannot write to /tm", 'p' | $80
msg_bad_result: db "Rebuild failed: patch damage", 'd' | $80
msg_too_many:   db "Too many trainers o", 'n' | $80
nex_magic:      db "Next"
ov_tag:         db "NXQ1"
ov_end:
        ent
ov_size         equ ov_end - ov_start
code_end        equ ov_start_at + ov_size
        assert  code_end <= patch_path, "the code runs into the fixed memory"
        display "resident: ", /d, ov_start_at - $2000, ", up to the menu: ", /d, first_end - ov_start_at, ", overlay: ", /d, ov_size, ", code room: ", /d, vars - $2000

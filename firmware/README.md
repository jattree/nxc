# .NEXCLASH: a NexClash patch from the NextZXOS browser

`nexclash.asm` is a NextZXOS dot command. Given a `.nxc` patch and the player's own copy of the game, it shows a menu and
rebuilds the NexClash `.nex`, with enhanced colours if chosen, or hands over the game itself, with any trainers chosen. The patch format is in
`../spec/NXC-FORMAT.md`; `../tools/nxc.py` is the reference it matches byte for byte. It is level 2 in `OPT1`'s terms:
`.z80` games and loading screens; and it reads `.tap` and `.tzx` games through `TAP1`, so takes `OPT1`'s tape flag. Built with NexClash by
Dean Woodyatt (Bleugh.biz, `bleughb/nexclash`, GPL-3.0-or-later); this command is GPL-3.0-or-later too. Its ZX0 decoder is
derived from dzx0_standard by Einar Saukas and Urusergi (BSD-3-Clause).

**Status. It has run on a Z80 emulator with NextZXOS faked, and in JNext on real NextZXOS v2.09 from a copy of an SD
image. It has not run on a Next or on the Tang.**

The file is longer than 8K, in one piece, which NextZXOS allows. It needs nothing else on the card. It reads sets as `SET2`; a patch made with `SET1` plays with no enhanced line, and has to be made again.

## Building

```
sjasmplus --nologo --raw=NEXCLASH firmware/nexclash.asm
python tools/nxc.py handoff-bas -o NXCHAND.BAS
```

## Tapes

A `.tap` or `.tzx` target is read through its `TAP1` table, as the spec says, with the same checks as `tools/nxc.py` and the same
refusals. In order, after the game unlocks the patch: the table is decoded into its three pages and checked whole (the start
state's header; every copy's block, length, bank and order; every site; nothing left over); then the tape is walked from its
start, a block's head at a time, as far as the highest data block a copy names, and each copy is given its place in the file,
in the table itself; then every bank the start state has is built once and its CRC compared with the table's; building the
`.nex`, an extra bank the header does not list is refused. A bank is then built when it is needed: zeros, each copy read from
the tape straight into it, then the table's sites. A tape is never handed over as it is: with the clash fix off, trainer or not,
the start state is written as a `.z80` of whole pages to `/tmp/NEXCLASH.Z80`, and `%x` is 2 as for a snapshot.

Measured on the Z80 harness at 28 MHz, with no file I/O: The New Zealand Story (a 178,176-byte `.tap`, a 147,968-byte `.nex`)
takes 2.75 s from Enter to the output being made, nearly all of it the tape absorbed for the key, then 0.90 s to write the `.nex`,
or 0.19 s for the `.z80`, in 9 pages. In JNext on NextZXOS v2.09, through the Browser, its `.nex` from the `.tap` and from the
`.tzx`, and its `.z80` with the fix off, were each byte for byte what `nxc.py` writes, and the game reached play. None of this has
run on a Next.

## Card setup

- `NEXCLASH` goes in `C:/DOT/`, `NXCHAND.BAS` in `C:/NEXTZXOS/`. `C:/TMP/` must exist, as it does on the standard card.
- The patch goes beside the player's game, named `NAME.nxc`. The game is looked for under each name in the patch's `TGT1`
  blocks, then as `NAME.z80`, and must have the length of one that the patch lists. A tape keeps its archive name, such as
  `New Zealand Story, The (1989)(Ocean)(48K-128K).tap`: the long name is opened as it is, as for a `.z80`. **Keep the extension to three letters:** the Browser goes by the 8.3 short name, so an old
  `Cobra.nexclash` is `COBRA~1.NEX` to it. It went to `.nexload`, which took it for a `.nex` and asked for a core update.
  The command itself reads any name.
- Add to `C:/NEXTZXOS/BROWSER.CFG`, before the `Z80,SNA` lines (CRLF line endings; `<7F>` is the single byte 0x7F, which
  the Browser replaces with `c:/nextzxos/`):

```
NXC:clear 65367:load "<7F>snapload.bas":f$="c:/tmp/nexclash.z80":adj=0:merge "<7F>nxchand.bas":.nexclash "|":cd "c:/tmp":goto 0
```

## The hand-off

A dot command cannot start another, so the line does it, in this order, for these reasons, each found by trying it in
JNext:

1. The snapshot loader is loaded first, with `f$` set, as the card's own `Z80,SNA` line does. `LOAD` clears NextBASIC's
   integer variables, so `.nexclash`, which leaves its answer in `%x`, has to come after it.
2. `.nexclash` runs. A refusal stops the line there with its message. `%x` is 1 for a `.nex`, 2 for a `.z80`.
3. `cd "c:/tmp"`: `.nexload` takes its name unquoted, and a `:` ends an unquoted argument, so it cannot be given a drive.
4. `goto 0` runs `NXCHAND.BAS`'s one merged line, `IF %x=1 THEN CLS:.nexload nexclash.nex`; otherwise line 1 of the snapshot
   loader follows, with `f$` as set.

The branch is in a merged program because a browser line cannot do it: `IF ... ELSE` and `ON` both fell through to the
menu when run from a browser line, in lower or upper case, or with the ELSE token as a byte.

The clash fix off with no trainer copies the game to `/tmp/NEXCLASH.Z80` unchanged and does not check it beyond finding
it by its length. Off with a trainer checks it against the patch, then writes it as a `.z80` of whole pages with the POKEs
in (version 1 becomes version 2).

A patch or game with the name of either output is refused, however the path is written: `F_GETCWD` with A=0xFF gives its
folder in one form on NextZXOS, tried in JNext for `/tmp/x`, `c:/tmp/x`, `C:\TMP\x`, `tmp/x` from the root, `x` from
`/tmp`, and paths through `..`. A failure to create an output deletes nothing.

## The stub of a .nex that carries its menu

`nxcstub.asm` is the start of a `.nex` that carries its menu, which `tools/nxc.py` writes by default (the spec's "A .nex
that carries its menu" has every rule). It includes `menu.asm`, the menu's one source, which draws the new menu on the ULA
screen from a description and runs its keys. `nxcstub.bin` is its assembled form, kept in the repository so that applying a
patch needs no assembler; `tests/test_menu_nex.py` checks it is what the source assembles to:

```
cd firmware && sjasmplus --nologo --raw=nxcstub.bin nxcstub.asm
```

## The menu

The command shows the same menu, from the same `menu.asm`, as a `.nex` that carries it (the spec's "The menu"): a blue bar
with the title and stripes, the publisher in white below, `TRAINER` and `OPTIONS` in yellow, `ON`
green and `OFF` red, `ENTER play` and `BREAK exit`, the help from `HLP1` of the line last keyed (the number keys are the only keys;
no cursor, no highlight), `Colours:` and `Patch:` above a plain bar with the stripes. Before the menu the command takes one 8K page for it, reads its menu part from its own file
(after the tape parts) into the page at 0xA000, with interrupts off, and builds the description there from the patch; the font
is ROM 3's, read from the card's `C:/MACHINES/NEXT/enNextZX.rom` at 0xFD00, as a dot command cannot see the ROM (without the
file it stops with `Needs NEXT/enNextZX.rom: no font`). It switches to layer 0 for the menu if the caller is in another, and
back after it.

**What the keys write.** With the clash fix on, **ENTER writes the bare `.nex`** with the choices fixed in it, so the
game starts straight after its title with no second menu (the owner's call, 2026-11-04). **SPACE writes the `.nex` that
carries its menu**: the bare `.nex` with nothing chosen, then the menu banks, its lines starting as they were left here, byte
for byte what `nxc.py PATCH GAME` with the same choices writes; `.nexload` then starts it, and its menu comes up again,
already set. With the fix off either key writes the
player's own game, as before. Either way the keys' row then flashes `Patching...` (`Loading...` with the fix off),
by the ULA's own FLASH, and the menu stays up until the command finishes, as some games take a few seconds (the owner's
suggestion, 2026-11-04). BREAK stops with `Cancelled`. The menu `.nex` is written by a part read over the game's part
once the bare banks are done; it decodes each set a chunk at a time in three pages of its own (a tape's, by then done with, or
three more), writes M0 and the data, and puts the header, the stub's count and the lines' offsets in place by seeking back
(the output is opened for reading too, to take the 16 bytes below the build's stack from it). A build that cannot carry a
menu is refused with `No menu .nex: press ENTER`.

**Memory.** The menu's page is held from before the menu to the end, so every route needs 8K more than before; the RAM
messages still name what the rebuild itself needs on top of it. The menu `.nex` needs no more pages than the bare one, but
for three to decode sets in when the patch has any.

**Assumed, and tested only in JNext running the card's own NextZXOS v2.09:** that all of the above behaves the same on
a Next, including the Browser's 8.3 matching, the merge at line 0, `cd` before `.nexload`, and the Enter that chose being
cleared from `FLAGS` (bit 5, or `PAUSE` and the snapshot loader see it). The snapshot loader keeps per-file options under
`/tmp/NEXCLASH.Z80`, so options set for one game apply to the next one started this way. Its "To begin loading, press
ENTER" page shows the first time, as it does for any snapshot.

## Testing on the Tang

Copy the three files as above with the game and `Cobra.nxc` into one folder, select `Cobra.nxc`, press Enter. Check by eye:

1. The menu fits in 41 columns (the command switches to layer 1,1 with 6-pixel characters and back).
2. `/tmp/NEXCLASH.NEX` has the MD5 in the patch's `INF1`, checked on the PC afterwards with the card out. The command's
   second part is read from its own file: cut the file short on a copy, and it should say so after the menu.
3. Cobra starts: any key, any key, hold 1, then P and O to move. Sprites stay clean over the backdrop.
4. Space and Enter with the clash fix off reach the snapshot loader. Number keys toggle the trainers; with Infinite lives
   on, the lives stay at three.
   With a patch with sets, a set's key steps through them, the `.nex` has the chosen ones, and with the fix off each line reads
   `[N/A]`.
5. Press Break at the menu: it stops with "Cancelled". Rename the game: it refuses and names the file.
6. After a refusal, `.MEM` (or the menu's free RAM figure) shows the same as before: the pages are freed.

## Memory

8K for the command, loaded in steps, then variables, buffers and a 154-byte stack. NextZXOS loads the file's first
8,192 bytes at 0x2000, and leaves the file open after them. That part is resident code, 1,589 bytes, with 2,704 bytes used only up
to the menu after it, then padding. After the menu, with `M_GETHANDLE`, the next 5,129 bytes are read in over what
was only for the menu: the code every route shares, then, from 0x35A4, 1,178 bytes that read a snapshot, behind a table of five
jumps. For a tape, three parts that follow in the file are read in their turn over the snapshot's: the first, 916 bytes, finds and
checks the table and keys a set's further files; the second, 897 bytes, walks the tape (a set's files one after another); the
third, 571 bytes, builds the banks and writes the clash fix off. The slot holds 1,185. A set's names are kept, after its files
are found, in the patch path's buffer, and each part opens the one it needs with gh, so only one game file is open at a time. A short or mismatched file, at any
part, gets a message and does nothing. Plus six 8K pages
from `IDE_BANK`, paged at MMU3 to MMU5 with interrupts off and the stack in the 8K: two for the bank being built, one for
the file buffer and tables, three for the site table, three more for each set chosen, and three for a tape's table,
so 48K, or 72K with one set or a tape, or 96K with two sets or a set and a tape. A tape and two sets need 120K, and the refusal for
too little still says 96K. MMU6 and MMU7 are never changed, and nothing given to the OS lies above `0xC000`. A bank at a
time goes to the card, so the `.nex` is never all in RAM.

**A set is held a bank at a time, so its size makes no difference to any of that.** Its three pages hold one chunk, at most 18,432 bytes, decoded when needed. Every chunk of a chosen set is decoded and checked before any file is made, then again as its bank is written, so a damaged set is refused with nothing written, and a set adds both passes to the time: in JNext, from Enter to the finished file, Everyone's a Wally (393,728 bytes) takes 6.1 s without its 43,389-byte set and 7.9 s with it, and Sabre Wulf (164,352 bytes) 3.2 s and 4.7 s.

Variables used only before the menu lie in the key state's memory, which is made after it, those needing no clearing below
the stack, and those used only with the I/O page mapped in that page. In JNext on NextZXOS the stack stayed within 64 bytes
of the top in the runs measured; on the Z80 harness 30, with several dumps and with a loading screen too.

**Sets refuse by name.** Without its pages a choice stops, before reading anything but the file's check, with `Needs 72K free RAM` or `Needs 96K free RAM`, and all pages are given back. JNext, whose machine is 2MB, showed 9 pages allocated for one set and 12 for two in a real run, with the stack within 64 bytes of the top; the Z80 harness has passed the real sets with 96 pages reported and 9 free, and refused them with 8. A small dot command, run from the same Browser line in JNext, could allocate 199 of the 224 pages; if NextZXOS keeps the same 25 on a 1MB Next, 71 of its 96 are free, against the 12 this ever asks for. No 1MB machine has been tried.

**How much memory the machine has** comes from `IDE_BANK` with reason `rc_bank_total` through `M_P3DOS`, whose total of 8K banks of ZX memory is compared with `OPT1`'s highest bank when ENTER is pressed with the clash fix on. In JNext it answers 224. Its refusal has only run on the Z80 harness, since JNext has no 1MB machine to try: what a real 1MB Next or a Tang answers is unverified.

A loading screen needs no more: it goes through the 16K for a bank, a piece at a time. The largest, 92,928 bytes of noise with
every type at once, takes 1.8 s from the screen's start to the end on a 98K build, at 28 MHz with no file I/O.

## Tests

```
python -m unittest discover -s tests
```

Set `NXC_ZX0_DIR` to the folder with the `zx0` compressor, and `NXC_EVIDENCE` or
`build/inputs` for the games, and `build/v1` for patches made from them, none of which are in this repository; what is
missing is skipped with a message. Needs `sjasmplus` and the `z80` package.

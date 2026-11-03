# .NEXCLASH: a NexClash patch from the NextZXOS browser

`nexclash.asm` is a NextZXOS dot command. Given a `.nxc` patch and the player's own copy of the game, it shows a menu and
rebuilds the NexClash `.nex`, with enhanced colours if chosen, or hands over the game itself, with any trainers chosen. The patch format is in
`../spec/NXC-FORMAT.md`; `../tools/nxc.py` is the reference it matches byte for byte. Inspired by Bleugh.biz's
nexclash (Dean Woodyatt, `bleughb/nexclash`, GPL-3.0-or-later); this command is GPL-3.0-or-later too. Its ZX0 decoder is
derived from dzx0_standard by Einar Saukas and Urusergi (BSD-3-Clause).

**Status. It has run on a Z80 emulator with NextZXOS faked, and in JNext on real NextZXOS v2.09 from a copy of an SD
image. It has not run on a Next or on the Tang.**

## Building

```
sjasmplus --nologo --raw=NEXCLASH firmware/nexclash.asm
python tools/nxc.py handoff-bas -o NXCHAND.BAS
```

## Card setup

- `NEXCLASH` goes in `C:/DOT/`, `NXCHAND.BAS` in `C:/NEXTZXOS/`. `C:/TMP/` must exist, as it does on the standard card.
- The patch goes beside the player's game, named `NAME.nxc`. The game is looked for under the name in the patch's `TGT1`,
  then as `NAME.z80`. **Keep the extension to three letters:** the Browser goes by the 8.3 short name, so an old
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

The clash fix off with no trainer copies the game to `/tmp/NEXCLASH.Z80` unchanged and does not check it. Off with a
trainer checks it against the patch, then writes it as a `.z80` of whole pages with the POKEs in (version 1 becomes
version 2).

## The menu

```
 JETPAC                    Ultimate, 1983

 TRAINER
  1  Infinite lives            [OFF]

 NEXCLASH
  2  Colour clash fix          [ON]
  3  Enhanced colours          [OFF]

 ENTER to play

Patch: Jon Attree  Colours: Alberto Conde
```

The number keys toggle a line. Trainers start off, the clash fix on, enhanced colours off, and trainers combine with any of
it. "Enhanced colours" shows only for a patch with a `PAL1`, and is `[ON]` or `[OFF]`: the menu offers the patch's first
colour set, and any others are for the tools. With the fix off it reads `[N/A]`, ignores its key and is not applied; turning
the fix on again brings the choice back. With 8 trainers on the menu it is the tenth line, on key 0. ENTER and SPACE both
start with what is shown; BREAK cancels.

The last line credits the patch's maker and colourist, from `patch_by` and `colours_by` in `INF1`, set by `nxc.py credit`.
It shows only what is there, with colours only for a patch with a `PAL1`, and no line if neither. It fits 41 columns from the
first: the gap closes from 5 to 2 before a name is cut (the spec has the rule). Dean's credit is in the usage text and here.

**Assumed, and tested only in JNext running the card's own NextZXOS v2.09:** that all of the above behaves the same on
a Next, including the Browser's 8.3 matching, the merge at line 0, `cd` before `.nexload`, and the Enter that chose being
cleared from `FLAGS` (bit 5, or `PAUSE` and the snapshot loader see it). The snapshot loader keeps per-file options under
`/tmp/NEXCLASH.Z80`, so options set for one game apply to the next one started this way. Its "To begin loading, press
ENTER" page shows the first time, as it does for any snapshot.

## Testing on the Tang

Copy the three files as above with the game and `Cobra.nxc` into one folder, select `Cobra.nxc`, press Enter. Check by eye:

1. The menu fits in 41 columns (the command switches to layer 1,1 with 6-pixel characters and back).
2. `/tmp/NEXCLASH.NEX` has the MD5 in the patch's `INF1`, checked on the PC afterwards with the card out.
3. Cobra starts: any key, any key, hold 1, then P and O to move. Sprites stay clean over the backdrop.
4. Space and Enter with the clash fix off reach the snapshot loader. Number keys toggle the trainers; with Infinite lives
   on, the lives stay at three.
   With a patch with a colour set, its line is `[ON]` or `[OFF]`, the `.nex` has the first set's colours when on, and with
   the fix off the line reads `[N/A]`.
5. Press Break at the menu: it stops with "Cancelled". Rename the game: it refuses and names the file.
6. After a refusal, `.MEM` (or the menu's free RAM figure) shows the same as before: the pages are freed.

## Memory

8K for the command: 6.8K of code and messages, then variables, buffers and a 192-byte stack. The file can never reach
8,192 bytes: the code must end where the variables start, 0x3B1A, which is 6,938 bytes, and it is 6,936. Plus six 8K pages
from `IDE_BANK`, paged at MMU3 to MMU5 with interrupts off and the stack in the 8K: two for the bank being built, one for
the file buffer and tables, three for the site table, and three more for the table of a colour set when one is chosen,
so 48K, or 72K with a set. MMU6 and MMU7 are never changed, and nothing given to the OS lies above `0xC000`. A bank at a
time goes to the card, so the `.nex` is never all in RAM.

To make room for the menu, the variables moved: those used only before the menu lie in the key state's memory, which is
made after it, those needing no clearing below the stack, which went from 256 bytes to 192, and those used only with the
I/O page mapped in that page. In JNext on NextZXOS the stack stayed within 64 bytes of the top, in the Jetpac runs with and
without a set; on the Z80 harness 30.

## Tests

```
python -m unittest discover -s tests
```

Set `NEXCLASH_REPO` to a NexClash checkout, `NXC_ZX0_DIR` to the folder with the `zx0` compressor, and `NXC_EVIDENCE` or
`build/inputs` for the games, which are not in this repository; what is missing is skipped with a message. Needs
`sjasmplus` and the `z80` package.

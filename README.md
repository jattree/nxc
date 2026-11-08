# .nxc

Colour-clash-free Spectrum games for the ZX Spectrum Next, from your own copy of the game.

[NexClash](https://github.com/bleughb/nexclash), by Dean Woodyatt (Bleugh.biz), rebuilds Spectrum games so that
their moving figures are Next hardware sprites, which keep their own colours. Its builds contain the game, so they
can't be shared. A `.nxc` patch holds only what the build adds. You put it beside your own copy of the game, and the
Next rebuilds the game with the clash fixed, plus any cheats or colour sets the patch offers.

The format and tools are by Jon Attree. Built with NexClash by Dean Woodyatt (Bleugh.biz,
[bleughb/nexclash](https://github.com/bleughb/nexclash), GPL-3.0-or-later).

## Status

**Early.** Everything has been tested in the JNext emulator. On real hardware so far, the loader has run on Jon's
NextNano (a Tang Nano 20K FPGA build of the Next) with NextZXOS v2.09, and nothing beyond that. It has not yet run on
an official Next board. The format may still change.

# Part 1: Play a patch on your Next

## What you need

- A ZX Spectrum Next, or a compatible machine, running **NextZXOS 2.09 or later**. Older versions are untested.
- Its SD card, in a PC (Windows, macOS or Linux).
- This repository: `git clone https://github.com/jattree/nxc.git`, or download it as a zip.
- Your own copy of each game you want to play, as the exact dump its patch asks for, under any name.

## One-time card setup

**The easy way.** With [Python 3](https://www.python.org/) installed, run this from the repository's folder, giving
the card's top folder:

```sh
py tools\setup_card.py E:\                    # Windows
python3 tools/setup_card.py /Volumes/NEXT      # macOS
python3 tools/setup_card.py /media/you/NEXT    # Linux
```

Add `--dry-run` first to see what it would do. It checks the card is a NextZXOS card, copies two files, keeps a copy
of `browser.cfg` as `browser.cfg.bak-pre-nxc`, adds one line to `browser.cfg`, and makes the `nxc` folder. Run it again
any time, for example after updating this repository: it changes only what is out of date.

**By hand.** Copy what is in [`sdcard/`](sdcard/) to the top of the card: `dot/NEXCLASH`, `nextzxos/NXCHAND.BAS` and
the `nxc` folder. Then add this line to `nextzxos/browser.cfg`, just before the first line that starts `Z80,SNA`:

```
NXC:clear 65367:load "<7F>snapload.bas":f$="c:/tmp/nexclash.z80":adj=0:merge "<7F>nxchand.bas":.nexclash "|":cd "c:/tmp":goto 0
```

Each `<7F>` is one byte, 0x7F, not four characters, and the file uses Windows (CRLF) line endings. The simplest way to
get both right is to copy the first `Z80,SNA` line, which already has those bytes, and edit the copy. Keep a copy of
the original file first.

## Play a game

1. Copy the game's folder from [`patches/`](patches/) into `nxc/` on the card, for example
   `nxc/Jet Pac (1983)(Ultimate Play The Game)(16K)/`.
2. Put your copy of the game in that folder, beside the `.nxc`. Its `.nfo` gives the MD5 it needs. Any name will do:
   the loader looks for the name in the `.nfo` first, then for any file in the folder of the right length, and takes it
   only if it is that exact dump.
3. On the Next, open the Browser, go to the folder and choose the `.nxc`.

The patch's menu comes up: its cheats under `TRAINER`, and under `OPTIONS` the clash fix and any colour sets. Press a
line's number to turn it on or off. Press ENTER. `Patching...` flashes while the game is rebuilt, which can take a few
seconds. Then the game's title screen shows, if it has one, and the game starts. BREAK cancels.

With the clash fix turned off, ENTER plays your own game as it is, with any cheats chosen.

## If it refuses

The loader stops with a message:

| Message | What to do |
|---|---|
| `Game not beside the patch` | Put your game file in the same folder as the `.nxc`. |
| `Wrong game file for this patch` | Your file is a different dump. Check its MD5 against the `.nfo`. If a file has the name the `.nfo` gives but is another dump, remove it: the loader tries that name first. |
| `Needs this game file:` and a name | The dump the patch wants, by the name the `.nfo` gives. Your copy can have any name, but must be that dump, in the patch's folder. |
| `Game file is damaged` | Copy the game to the card again. |
| `Patch damaged: get it again` or `Not a .nxc file` | Copy the `.nxc` again. |
| `Patch needs a newer .NEXCLASH` | Update this repository and run the card setup again. |
| `NEXCLASH cut or mixed: recopy it` | Run the card setup again. |
| `Needs NEXT/enNextZX.rom: no font` | The card is missing `machines/next/enNextZX.rom`. Use a standard NextZXOS card. |
| `Cannot write to /tmp` | The card needs a `tmp` folder at its top, and room for the game. |
| `Needs more RAM: turn fix off` | The rebuilt game needs more memory than this Next has. With the clash fix off, the original game still plays. |
| `Needs 72K free RAM` and the like | Not enough memory is free for the rebuild. Restart the Next and try again. |
| `No menu .nex: press ENTER` | SPACE, which saves a `.nex` with the menu in it, can't be used for this game. Press ENTER. |

If the Browser doesn't start the loader when you choose a `.nxc`, the `browser.cfg` line is missing: run the card
setup again.

## Or make a .nex on a PC

You can also build the game as a `.nex` file on a PC, with only Python 3, and run it on any Next or in an emulator:

```sh
python3 tools/nxc.py PATCH.nxc YOUR_GAME.z80 -o Game.nex
```

Leave out `YOUR_GAME.z80` and the tool finds the game beside the patch, as the loader does, under any name, by its MD5.

The `.nex` carries the patch's menu, so you choose cheats and colours when it starts. `--bare` builds one without the
menu, with your choices fixed. [docs/BUILDING-A-NEX.md](docs/BUILDING-A-NEX.md) has every step. A `.nex` contains the
game, so it is for your own use: share the `.nxc`, never the `.nex`.

## The patches

[`patches/`](patches/) holds the patches made so far, one folder per game, each played through the real loader in
JNext. Each has a `.nfo` naming the exact game file it needs, what it changes, its cheats, its credits and how it
was tested. None of them carries game code.

# Part 2: Make a patch

`tools/nxc.py` packages a finished NexClash build as a `.nxc`, adds cheats, colour sets, languages, help text and
credits to it, and applies it. [The format](spec/NXC-FORMAT.md) says exactly what a patch holds; the loader in
[`firmware/`](firmware/README.md) and the tool must match it byte for byte.

A `.nxc` holds what the build adds, with the game's own banks left out, and only the player's own copy of the game
unlocks it. What it adds includes sprite data derived from the game's graphics, held encrypted, and some of it is
readable to anyone: names, credits, cheats. Anyone who owns the game can read a patch, or forge one. This is not
cryptographic strength: a patch is code from whoever made it. With the patch and the right game file, you get back
exactly the `.nex` that was built, byte for byte; `make` proves that before it writes anything.

Each patch records how it was proven in its `INF1` fields, shown in its `.nfo`: replays of recorded play checked
against the original game, emulator runs, coverage, and hardware runs where there are any. Credits go in the
patch too: `patch_by` and `colours_by` on the menu, and the full `credit` (NexClash and Dean Woodyatt always) in the
`.nfo`.

| | |
|---|---|
| PC tool | Tested |
| Next loader | Tested on a Z80 emulator and in JNext on NextZXOS v2.09; run on a NextNano with NextZXOS v2.09 |
| A `.nex` with its menu | Tested on a Z80 emulator and in JNext 1.1.104 |
| Official Next board | **Not run** |
| Review by Dean Woodyatt | Testing, from 2026-11-04 |

## Making a patch

You need a finished `.nex`, usually from [NexClash](https://github.com/bleughb/nexclash), and the exact
game file it was built from. This tool packages a build: it doesn't make one, so sprites, a foreground or
a loading screen shown by the build's own start-up code all belong in the build, and carry over as they are.

**1. Package it,** which also proves it rebuilds your `.nex` exactly:

```sh
python tools/nxc.py make Game.nex Game.z80 -o Game.nxc --title "Game" --zxdb 0000123 \
    --publisher "Ocean, 1986" --patch-by "Your Name" --patch-version 1.0 --rom 1 \
    --proof "replay=IDENTICAL on 2 recordings" --proof replay_when=2026-11-03 --proof hardware=none
```

**2. Add cheats,** from a `.pok`, which you can write by hand as it's plain text. `--only` picks which:

```sh
python tools/nxc.py import-pok Game.nxc Game.pok Game.z80 -o Game2.nxc --only "Infinite Lives,Immunity"
```

On a 128K game, a `.pok` line at 0xC000 or above with bank 8 doesn't say which bank the game has paged
there when it reads the byte, and the snapshot only knows the one paged when it was saved. Such a line is
refused until you say which with `--top-bank N`, having watched the game run (or put the bank in the `.pok`).

**3. Add colours or languages** when you package it. Colours follow the [colour standard](docs/COLOUR-STANDARD.md). Each is the same build with that one change applied,
and they can be combined if they don't touch the same bytes:

```sh
python tools/nxc.py make Game.nex Game.z80 -o Game.nxc --title "Game" \
    --colours "Arcade=Game_painted.nex" --colours-by "Their Name" \
    --language "Espanol=Game_es.nex" --language-code "Espanol=es" --game-language en --text-by "Their Name"
```

**4. Check it,** on a PC, then in an emulator or on a Next. Try every cheat in play: a POKE that applies
cleanly can still do nothing, or the wrong thing, in a patched build.

```sh
python tools/nxc.py Game.nxc Game.z80 -o Check.nex --bare --trainer 1 --colours Arcade
```

**5. Share the patch only if it's yours to share.** It holds no copy of the game's code or levels, but a
sprite build's graphics are made from the game's, held encrypted, and a screen or art you add may not be in the
player's file at all. Get the agreement of whoever made the build.

### The details

The game can be `.z80` or `.sna`. It rebuilds the `.nex` from what it wrote before keeping anything, and refuses one it can't package: a `.nex` above `V1.2`, a screen of a later version, anything past the banks, or too much changed from the game for a loader to hold in `SIT1`. A colour or language set has no such limit, and is always a choice on the menu: the plain build stays the default. `--proof-file` takes the proof fields as lines of `KEY=VALUE`, and the [format](spec/NXC-FORMAT.md) lists them. `--colours NAME=NEX` and `--language NAME=NEX` add sets, each from the same build with it applied, and `--colours-by` credits a colour set.

**Memory.** A loader on a 1MB Next refuses a build that needs more, from the highest bank the `.nex` lists. If your build uses higher banks at run time than it loads, as with Layer 2 buffers, say so with `--highest-bank N`.

**From a tape.** A patch can take the game's banks from its original `.tap` or `.tzx` instead of a snapshot, if the tape holds the
game plainly: give `make` the tape, and with `--start` the `.z80` the build was made from, taken from that tape in an emulator.
What the tape does not hold of that start, such as the screen and variables, the patch carries, encrypted; more than 8,192 bytes
of it is refused, as the sign of a packed or protected tape. `--tape-bank N` names banks of the build that hold a multiload's
blocks. [docs/TAP1-NOTES.md](docs/TAP1-NOTES.md) has the steps.

```sh
python tools/nxc.py make Game.nex "Game (1989)(Ocean).tap" --start Game_start.z80 -o Game.nxc --title "Game"
python tools/nxc.py add-target Game.nxc "Game (1989)(Ocean).tap" "Game (1989)(Ocean).tzx" -o Game2.nxc
```

## Adding to a patch

```sh
python tools/nxc.py import-pok Game.nxc Game.pok Game.z80 -o Out.nxc --publisher "Ocean, 1986"
python tools/nxc.py credit Game.nxc Game.z80 -o Out.nxc --patch-by "Your Name" --colours-by "Their Name"
python tools/nxc.py version Game.nxc Game.z80 1.1 -o Out.nxc
python tools/nxc.py help Game.nxc Game.z80 -o Out.nxc --line "trainer_1=Lives stay at three." --line "fix=The sprite build."
python tools/nxc.py set Game.nxc Game.z80 notes "No outlines on the figures: my choice for this game." -o Out.nxc
python tools/make_nfo.py Out.nxc
```

`set` sets any one field of `INF1` or `PRF1`, keeping the patch's key, and refuses one it doesn't know or a value that
breaks a limit: `notes`, `enhanced` (what the colour set looks like; `enhanced_N` for set N of several), `changes`
(`1.1: what changed | 1.2: ...`), `tested` (who played it, where, when), `credit`, the menu's names, and `PRF1`'s proofs,
`pace` among them (`ORIGINAL`, `SLOWDOWN REMOVED` or `TURBO`, with `pace_measured` such as `the first room: +0.15%`).
`''` removes a field. None of them changes what the patch builds. `make_nfo.py` writes the `.nfo` from the patch alone.

`version` sets the patch's own version, up to 8 characters such as `1.1`, which the menu shows as `v1.1` at the right
of its `Patch:` row; give it a new one each time you change a published patch. `''` removes it.

`help` sets the menu's help line for each option (`fix`, `colours`, `language`, `trainer_N`, `toggle_N`), up to two rows
of 32 characters, wrapped at a space.

A POKE that lands on a byte the patch changes is refused. Passing that check doesn't prove a cheat
works in the patched build, so try it.

To accept another dump, which must rebuild the same banks or is refused:

```sh
python tools/nxc.py add-dump Game.nxc Game.z80 Other.z80 -o Out.nxc
```

A `.nex` with a loading screen is packaged too, in `V1.0` to `V1.2` screen types. Such a screen may be art
the player's file doesn't hold, and the patch then holds it, encrypted.

## Backgrounds

There are two ways, neither run on a real machine:

- **Behind any game, with no patch:** [`.bgshow`](backgrounds/README.md), which makes the game's black see-through. Good on plain black backgrounds, poor on dithered scenery. It doesn't remove clash.
- **In a patch:** a build with its own background in its banks and start-up code is packaged by `make` as it is. A menu choice of backgrounds is reserved in the format as `L2B1`, and isn't built yet.

## Requirements

- **To apply, list, add a dump or target, import cheats, credit, or set help:** Python 3 and nothing else. The tool
  reads `.z80`, `.sna`, `.tap` and `.tzx` itself, and carries its own ZX0 decoder and the menu stub
  (`firmware/nxcstub.bin`).
- **To make a patch,** and to add a tape release that needs a table of its own: [ZX0](https://github.com/einar-saukas/ZX0)'s
  `zx0` compressor, version 2: set `NXC_ZX0_DIR` to its folder. The builds themselves come from
  [NexClash](https://github.com/bleughb/nexclash), but the tool needs no NexClash checkout.
- **To build the loader or the stub:** [sjasmplus](https://github.com/z00m128/sjasmplus):
  `sjasmplus --nologo --raw=NEXCLASH firmware/nexclash.asm`, and in `firmware/`,
  `sjasmplus --nologo --raw=nxcstub.bin nxcstub.asm`. A test checks the stub in the repository is its source.
- **To run the tests:** also the Python `z80` package (`pip install z80`); tests needing what is missing skip.

## Tests

```sh
python -m unittest discover -s tests
```

Tests that need real games or builds skip without them. Set `NXC_EVIDENCE` and `NXC_REFERENCE` to your
own folders of those files. None are included. `tests/vectors/` is made only from synthetic bytes, for
checking another implementation.

## Documents

- [docs/BUILDING-A-NEX.md](docs/BUILDING-A-NEX.md): building a .nex from a patch on a PC, step by step
- [spec/NXC-FORMAT.md](spec/NXC-FORMAT.md): the format
- [docs/COLOUR-STANDARD.md](docs/COLOUR-STANDARD.md): how colours are chosen: the Next's standard 256-colour palette, and how many colours a figure can use
- [firmware/README.md](firmware/README.md): the loader and its setup
- [tools/setup_card.py](tools/setup_card.py): the one-time card setup
- [backgrounds/README.md](backgrounds/README.md): a picture behind any game, an experiment that has only run in JNext
- [docs/TAP1-NOTES.md](docs/TAP1-NOTES.md): tape targets, how to make one, and what was tested
- [docs/MENU-NOTES.md](docs/MENU-NOTES.md): the menu round: the new menu, a `.nex` that carries it, and what was tested

## Credits and licence

The sprite method, and the engines that patches package, are Dean Woodyatt's NexClash, under
GPL-3.0-or-later.

This project is under GPL-3.0-or-later: see [LICENSE](LICENSE). The loader's decompressor is derived
from Einar Saukas and Urusergi's ZX0, under BSD-3-Clause; the tool's snapshot reader follows NexClash's:
see [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES).

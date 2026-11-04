# .nxc

A patch format for ZX Spectrum Next games. By Jon Attree. Built with NexClash by Dean Woodyatt
(Bleugh.biz, [bleughb/nexclash](https://github.com/bleughb/nexclash), GPL-3.0-or-later).

NexClash turns Spectrum games into `.nex` files whose figures are hardware sprites, removing colour
clash. A `.nex` contains the game, so it can't be freely shared. A `.nxc` holds what the build adds,
with the game's own banks left out, and only the player's own copy of the game unlocks it. What it adds
includes sprite data derived from the game's graphics, held encrypted, and some of it is readable to
anyone: names, credits, cheats. [The format](spec/NXC-FORMAT.md) says exactly what.

Anyone who owns the game can read a patch, or forge one. This is not cryptographic strength: a patch is
code from whoever made it.

With the patch and the right game file, you get back exactly the `.nex` that was built, byte for byte.

## Status

**Draft.** Not reviewed by Dean Woodyatt, and not run on a Next or a NextTang. No patches have
circulated, so it may still change.

| | |
|---|---|
| PC tool | Tested |
| Next loader | Tested on a Z80 emulator and in JNext on NextZXOS v2.09, the new menu and the menu `.nex` included |
| A `.nex` with its menu | Tested on a Z80 emulator and in JNext 1.1.104 |
| Real Next or NextTang | **Not run** |
| Review by Dean Woodyatt | **Not yet** |

This repository holds no game data, and no patches from any game.

## Using a patch

**On a PC,** which writes the finished `.nex` ([docs/BUILDING-A-NEX.md](docs/BUILDING-A-NEX.md) has every step):

```sh
python3 tools/nxc.py Game.nxc Game.z80 -o Game.nex
```

The game can be any file the patch lists: `.z80`, `.sna`, `.tap` or `.tzx`; for a game on two tapes, add `--also` and the
second file. **The `.nex` carries the patch's menu:** when it starts, on any Next or emulator that runs a `.nex`, it shows
every cheat, colour set, language and toggle the patch has, applies your choices, and starts the game exactly as a `.nex`
built with those choices would. Nothing of ours is needed to run it.

```
 RENEGADE     Imagine, 1987 ////

TRAINER
1 Infinite lives           [ ON]
2 Infinite time            [OFF]
3 No death                 [OFF]
4 Easy fight, one-hit falls[OFF]
5 Start at level 2         [OFF]
6 Start at level 3         [OFF]
7 Start at level 4         [OFF]

OPTIONS
8 Colour clash fix         [ ON]
9 Enhanced colours         [OFF]

ENTER play   BREAK exit

Infinite time:
The clock stops at every round.


Patch: Jon Attree
                            ////
```

In colour: a blue bar with Spectrum stripes, yellow headings, `ON` green and `OFF` red
(the help line here was added for the picture; the published patch has none yet).

The keys are the line numbers, with no cursor or highlight; the help of the line last keyed shows
under the keys if the patch has any. ENTER or SPACE plays; BREAK resets the Next. `--bare` writes a `.nex` without the
menu, with the choices fixed: `--trainer NAME_OR_NUMBER`, `--colours NAME`, `--language NAME`, `--toggle NAME`.
`--original` writes the game itself, unchecked, or with `--trainer` a checked snapshot of it with the POKEs in.

**On the Next,** a dot command gives the same menu in the Browser. ENTER rebuilds the game from your game file with
your choices fixed and starts it: its title, then the game, with no second menu. SPACE instead writes the `.nex` that carries
the menu, set as you left it. A patch can list several dumps of a game. A wrong or missing game file gets a
message naming the file it needs. The Next reads `.z80`, `.tap` and `.tzx`. A tape with the clash fix off becomes the
game's start as a `.z80`, checked. Card setup, including the `browser.cfg` line, is in [firmware/README.md](firmware/README.md).

## Patches

[`patches/`](patches/) holds the patches made so far and played through the real loader in JNext, one folder per game. Each patch has a `.nfo` beside it naming the exact game file it needs, what it changes, its cheats, its credits and how it was tested. None of them carries game code: you need your own copy of each game. Nothing has run on a real Next yet.

## Making a patch

You need a finished `.nex`, usually from [NexClash](https://github.com/bleughb/nexclash), and the exact
game file it was built from. This tool packages a build: it doesn't make one, so sprites, a foreground or
a loading screen shown by the build's own start-up code all belong in the build, and carry over as they are.

**1. Package it,** which also proves it rebuilds your `.nex` exactly:

```sh
python tools/nxc.py make Game.nex Game.z80 -o Game.nxc --title "Game" --zxdb 0000123 \
    --publisher "Ocean, 1986" --patch-by "Your Name" --rom 1 \
    --proof "replay=IDENTICAL on 2 recordings" --proof replay_when=2026-11-03 --proof hardware=none
```

**2. Add cheats,** from a `.pok`, which you can write by hand as it's plain text. `--only` picks which:

```sh
python tools/nxc.py import-pok Game.nxc Game.pok Game.z80 -o Game2.nxc --only "Infinite Lives,Immunity"
```

On a 128K game, a `.pok` line at 0xC000 or above with bank 8 doesn't say which bank the game has paged
there when it reads the byte, and the snapshot only knows the one paged when it was saved. Such a line is
refused until you say which with `--top-bank N`, having watched the game run (or put the bank in the `.pok`).

**3. Add colours or languages** when you package it. Each is the same build with that one change applied,
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
python tools/nxc.py help Game.nxc Game.z80 -o Out.nxc --line "trainer_1=Lives stay at three." --line "fix=The sprite build."
```

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
- [firmware/README.md](firmware/README.md): the loader and its setup
- [backgrounds/README.md](backgrounds/README.md): a picture behind any game, an experiment that has only run in JNext
- [docs/TAP1-NOTES.md](docs/TAP1-NOTES.md): tape targets, how to make one, and what was tested
- [docs/BUILDING-A-NEX.md](docs/BUILDING-A-NEX.md): making a `.nex` from a patch on a PC, step by step
- [docs/MENU-NOTES.md](docs/MENU-NOTES.md): the menu round: the new menu, a `.nex` that carries it, and what was tested

## Credits and licence

The sprite method, and the engines that patches package, are Dean Woodyatt's NexClash, under
GPL-3.0-or-later.

This project is under GPL-3.0-or-later: see [LICENSE](LICENSE). The loader's decompressor is derived
from Einar Saukas and Urusergi's ZX0, under BSD-3-Clause; the tool's snapshot reader follows NexClash's:
see [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES).

# .nxc

A patch format for ZX Spectrum Next games. By Jon Attree. Inspired by Bleugh.biz's
[nexclash](https://github.com/bleughb/nexclash), by Dean Woodyatt.

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
| Next loader | Tested on a Z80 emulator and in JNext on NextZXOS v2.09 |
| Real Next or NextTang | **Not run** |
| Review by Dean Woodyatt | **Not yet** |

This repository holds no game data, and no patches from any game.

## Using a patch

**On a PC,** which writes the finished `.nex`:

```sh
python tools/nxc.py Game.nxc Game.z80 -o Game.nex
```

The game can be any file the patch lists, `.z80` or `.sna`. Add `--trainer NAME_OR_NUMBER` for a cheat,
`--colours NAME` or `--language NAME` for a set, or `--original` to write the game itself, unchecked, or with
`--trainer` a checked snapshot of it with the POKEs in.

**On the Next,** a dot command gives a menu in the Browser:

```
 JETPAC                    Ultimate, 1983

 TRAINER
  1  Infinite lives            [OFF]

 NEXCLASH
  2  Colour clash fix          [ON]
  3  Enhanced colours          [OFF]

 ENTER to play

Patch: Jon Attree  Colours: Jane Painter
```

It rebuilds the `.nex` from your game file and starts it. A patch can list several dumps of a game. A
wrong or missing game file gets a message naming the file it needs. The Next reads `.z80` only. Card
setup, including the `browser.cfg` line, is in [firmware/README.md](firmware/README.md).

## Patches

[`patches/`](patches/) holds the patches made so far and played through the real loader in JNext. Each has a `.nfo` beside it naming the exact game file it needs, what it changes, its cheats, its credits and how it was tested. None of them carries game code: you need your own copy of each game. Nothing has run on a real Next yet.

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
python tools/nxc.py Game.nxc Game.z80 -o Check.nex --trainer 1 --colours Arcade
```

**5. Share the patch only if it's yours to share.** It holds no copy of the game's code or levels, but a
sprite build's graphics are made from the game's, held encrypted, and a screen or art you add may not be in the
player's file at all. Get the agreement of whoever made the build.

### The details

The game can be `.z80` or `.sna`. It rebuilds the `.nex` from what it wrote before keeping anything, and refuses one it can't package: a `.nex` above `V1.2`, a screen of a later version, anything past the banks, or too much changed from the game for a loader to hold in `SIT1`. A colour or language set has no such limit, and is always a choice on the menu: the plain build stays the default. `--proof-file` takes the proof fields as lines of `KEY=VALUE`, and the [format](spec/NXC-FORMAT.md) lists them. `--colours NAME=NEX` and `--language NAME=NEX` add sets, each from the same build with it applied, and `--colours-by` credits a colour set.

**Memory.** A loader on a 1MB Next refuses a build that needs more, from the highest bank the `.nex` lists. If your build uses higher banks at run time than it loads, as with Layer 2 buffers, say so with `--highest-bank N`.

## Adding to a patch

```sh
python tools/nxc.py import-pok Game.nxc Game.pok Game.z80 -o Out.nxc --publisher "Ocean, 1986"
python tools/nxc.py credit Game.nxc Game.z80 -o Out.nxc --patch-by "Your Name" --colours-by "Their Name"
```

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

- Python 3 and a [NexClash](https://github.com/bleughb/nexclash) checkout, whose snapshot reader is
  imported: set `NEXCLASH_REPO`.
- [ZX0](https://github.com/einar-saukas/ZX0)'s `zx0`, to make patches: set `NXC_ZX0_DIR`.
- [sjasmplus](https://github.com/z00m128/sjasmplus), to build the loader:
  `sjasmplus --nologo --raw=NEXCLASH firmware/nexclash.asm`
- The Python `z80` package, to run the loader's tests.

## Tests

```sh
python -m unittest discover -s tests
```

Tests that need real games or builds skip without them. Set `NXC_EVIDENCE` and `NXC_REFERENCE` to your
own folders of those files. None are included. `tests/vectors/` is made only from synthetic bytes, for
checking another implementation.

## Documents

- [spec/NXC-FORMAT.md](spec/NXC-FORMAT.md): the format
- [firmware/README.md](firmware/README.md): the loader and its setup
- [backgrounds/README.md](backgrounds/README.md): a picture behind any game, an experiment that has only run in JNext

## Credits and licence

The sprite method, and the engines that patches package, are Dean Woodyatt's NexClash, under
GPL-3.0-or-later.

This project is under GPL-3.0-or-later: see [LICENSE](LICENSE). The loader's decompressor is derived
from Einar Saukas and Urusergi's ZX0, under BSD-3-Clause: see [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES).

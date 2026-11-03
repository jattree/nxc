# .nxc

A patch format for ZX Spectrum Next games. By Jon Attree. Inspired by Bleugh.biz's
[nexclash](https://github.com/bleughb/nexclash), by Dean Woodyatt.

NexClash turns Spectrum games into `.nex` files whose figures are hardware sprites, removing colour
clash. A `.nex` contains the game, so it can't be freely shared. A `.nxc` holds only what the build
adds, encrypted against the player's own copy of the game, so the patch is useless without that copy.

With the patch and the right game file, you get back exactly the `.nex` that was built, byte for byte.

## Status

**Draft, and the format will change.** The key stream is being redesigned so one patch can accept
several dumps of a game, which will break existing patches.

| | |
|---|---|
| PC tool | Tested |
| Next loader | Tested on a Z80 emulator and in JNext on NextZXOS v2.09 |
| Real Next or NextTang | **Not run yet** |
| Review by Dean Woodyatt | Not yet |

This repository holds no game data, and no patches.

## Using a patch

**On a PC,** which writes the finished `.nex`:

```sh
python tools/nxc.py Game.nxc Game.z80 -o Game.nex
```

Add `--trainer NAME_OR_NUMBER` for a cheat, `--colours NAME` for a colour set, or `--original` to write
the game unmodified, with any trainers.

**On the Next,** a dot command gives a menu in the Browser:

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

It rebuilds the `.nex` from your game file and starts it. A wrong or missing game file gets a message
naming the file it needs. Card setup, including the `browser.cfg` line, is in
[firmware/README.md](firmware/README.md).

## Adding to a patch

```sh
python tools/nxc.py import-pok Game.nxc Game.pok Game.z80 -o Out.nxc --publisher "Ocean, 1986"
python tools/nxc.py credit Game.nxc Game.z80 -o Out.nxc --patch-by "Your Name" --colours-by "Their Name"
```

A POKE that lands on a byte the patch changes is refused. Passing that check doesn't prove a cheat
works in the patched build, so try it.

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
own folders of those files. None are included.

## Documents

- [spec/NXC-FORMAT.md](spec/NXC-FORMAT.md): the format
- [firmware/README.md](firmware/README.md): the loader and its setup

## Credits and licence

The sprite method, and the engines that patches package, are Dean Woodyatt's NexClash, under
GPL-3.0-or-later.

This project is under GPL-3.0-or-later: see [LICENSE](LICENSE). The loader's decompressor is derived
from Einar Saukas and Urusergi's ZX0, under BSD-3-Clause: see [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES).

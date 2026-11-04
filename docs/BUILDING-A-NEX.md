# Building a .nex from a patch, on a PC

A `.nxc` patch plus your own copy of the game makes a `.nex`, the Spectrum Next's own program format. A `.nex` runs on
any Next and in any emulator that loads `.nex` files (JNext, CSpect, ZEsarUX and others), with no loader of ours
needed. This page shows how to make one on a PC. On a Next itself, the loader does the same thing from the
Browser: see [firmware/README.md](../firmware/README.md).

The `.nex` you make contains the game, so it's for your own use. Share the `.nxc`, never the `.nex`.

## What you need

- **Python 3** (3.8 or later), and nothing else: no other checkout, no packages, no settings. On Windows, install it
  from python.org and use `py` where this page says `python3`.
- **git**, or download this repository as a zip file:

```sh
git clone https://github.com/jattree/nxc.git
```

- **The patch,** a `.nxc` file, with its `.nfo` if it came with one.
- **Your copy of the game**, as the exact file the patch was made for. The patch names it, and its `.nfo` gives its
  MD5. Check yours matches:

```sh
md5sum "Spellbound (1985)(Mastertronic Added Dimension)(128K)[Magic Knight 2].z80"     # Linux
md5 "Spellbound (1985)(Mastertronic Added Dimension)(128K)[Magic Knight 2].z80"        # macOS
certutil -hashfile "Spellbound (1985)(Mastertronic Added Dimension)(128K)[Magic Knight 2].z80" MD5   # Windows
```

A different dump of the same game won't do: the tool refuses it and says which file it wants.

## 1. See what the patch offers

Give the tool the patch on its own:

```sh
python3 nxc/tools/nxc.py Spellbound.nxc
```

It lists the colour sets, the cheats (trainers), the RAM the game needs, the game files it accepts, and how the patch
was tested:

```
colour sets: (default), Enhanced
trainers: Infinite strength, Infinite time, Infinite spell power, ...
needs 352K of RAM, up to 16K bank 21: a 1MB Next has it
accepts Spellbound (1985)(Mastertronic Added Dimension)(128K)[Magic Knight 2].z80, z80, 85709 bytes
```

## 2. Build the .nex

```sh
python3 nxc/tools/nxc.py PATCH.nxc YOUR_GAME.z80 -o Game.nex
```

For a game on two tapes, such as a side A and a side B, give the first file, then the second with `--also`, in the order
the patch's `accepts` line lists them:

```sh
python3 nxc/tools/nxc.py new_zealand_story.nxc "New Zealand Story, The (1989)(Ocean)(48K-128K).tap" \
    --also "New Zealand Story, The (1989)(Ocean)(48K-128K)(Side B).tzx" -o NZS.nex
```

It prints `wrote Game.nex` and the file's MD5. The same patch and game files always give the same `.nex`, byte for byte.

## 3. Run it

- **On a Next:** copy `Game.nex` to the SD card and choose it in the Browser.
- **In an emulator:** open `Game.nex` in JNext, CSpect or ZEsarUX. For example: `jnext --load Game.nex`.

**The menu comes first.** The `.nex` carries the patch's menu, with every cheat, colour set, language and toggle the
patch offers:

- the number keys turn a line on or off, or step a colour or language line through its choices;
- pressing a line's number also shows that line's help under the keys;
- ENTER or SPACE plays, with what the menu shows; BREAK resets the Next.

The choices are applied to the game as it starts, and the game then starts exactly as a `.nex` built with those
choices fixed would. Choose again every time you run it.

## A .nex with the choices fixed

To build one without the menu, starting straight into the game with your choices, add `--bare` and the choices:

| Option | Does |
|---|---|
| `--colours Enhanced` | the Enhanced colour set, where the patch has one; leave it out for the game's own colours |
| `--trainer 1` | a cheat, by number from the list or by name; repeat for more: `--trainer 1 --trainer 3` |
| `--language NAME` | a language set, where the patch has one |
| `--toggle NAME` | a toggle, such as smooth scrolling, where the patch has one |

```sh
python3 nxc/tools/nxc.py Spellbound.nxc \
    "Spellbound (1985)(Mastertronic Added Dimension)(128K)[Magic Knight 2].z80" --bare --colours Enhanced --trainer 1 -o Spellbound.nex
```

Without `--bare`, the choices are refused, as they belong on the menu. `--original` writes the game without the patch
(with `--trainer`, a checked snapshot of it with the cheats in).

## Good to know

- **The menu needs a little more memory:** one 16K bank for the menu, and more for colour sets. The tool says if a build
  can't carry one, and `--bare` always works.
- **Problems.** "Refused: this is not the game file this patch was made for" means your file isn't the exact dump the
  patch lists: check the MD5 against the `.nfo`. "this build cannot carry its menu" names why; `--bare` still works.

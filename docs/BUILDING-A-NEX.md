# Building a .nex from a patch, on a PC

A `.nxc` patch plus your own copy of the game makes a `.nex`, the Spectrum Next's own program format. A `.nex` runs on
any Next and in any emulator that loads `.nex` files (JNext, CSpect, ZEsarUX and others), with no loader of ours
needed. This page shows how to make one on a PC. On a Next itself, the loader does the same thing from the
Browser: see [firmware/README.md](../firmware/README.md).

The `.nex` you make contains the game, so it's for your own use. Share the `.nxc`, never the `.nex`.

## What you need

- **Python 3** (3.8 or later). On Windows, install it from python.org and use `py` where this page says `python3`.
- **git**, or download the two repositories below as zip files.
- **This repository** and a **NexClash** checkout, whose snapshot reader the tool uses:

```sh
git clone https://github.com/jattree/nxc.git
git clone https://github.com/bleughb/nexclash.git
```

- **Your copy of the game**, as the exact file the patch was made for. Each patch's `.nfo` names it and gives its
  MD5. For example, `patches/Spellbound (1985)(Mastertronic Added Dimension)(128K)/…[Magic Knight 2].nfo` asks for
  `Spellbound (1985)(Mastertronic Added Dimension)(128K)[Magic Knight 2].z80`. Check yours matches:

```sh
md5sum "Spellbound (1985)(Mastertronic Added Dimension)(128K)[Magic Knight 2].z80"     # Linux
md5 "Spellbound (1985)(Mastertronic Added Dimension)(128K)[Magic Knight 2].z80"        # macOS
certutil -hashfile "Spellbound (1985)(Mastertronic Added Dimension)(128K)[Magic Knight 2].z80" MD5   # Windows
```

A different dump of the same game won't do: the tool refuses it and says which file it wants.

## 1. See what the patch offers

Point `NEXCLASH_REPO` at the NexClash checkout, then give the tool the patch on its own:

```sh
export NEXCLASH_REPO=$PWD/nexclash          # Windows: set NEXCLASH_REPO=%CD%\nexclash
python3 nxc/tools/nxc.py "nxc/patches/Spellbound (1985)(Mastertronic Added Dimension)(128K)/Spellbound (1985)(Mastertronic Added Dimension)(128K)[Magic Knight 2].nxc"
```

It lists the colour sets, the cheats (trainers) by number, the RAM the game needs, the game file it accepts, and how
the patch was tested:

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

Options, as many as you like:

| Option | Does |
|---|---|
| `--colours Enhanced` | the Enhanced colour set, where the patch has one; leave it out for the game's own colours |
| `--trainer 1` | a cheat, by number from the list or by name; repeat for more: `--trainer 1 --trainer 3` |
| `--language NAME` | a language set, where the patch has one |
| `--original` | the game without the patch (with `--trainer`, a checked snapshot of it with the cheats in) |

For example, Spellbound with Enhanced colours and infinite strength:

```sh
python3 nxc/tools/nxc.py "nxc/patches/Spellbound (1985)(Mastertronic Added Dimension)(128K)/Spellbound (1985)(Mastertronic Added Dimension)(128K)[Magic Knight 2].nxc" \
    "Spellbound (1985)(Mastertronic Added Dimension)(128K)[Magic Knight 2].z80" --colours Enhanced --trainer 1 -o Spellbound.nex
```

It prints `wrote Spellbound.nex` and the file's MD5. The same patch, game file and options always give the same
`.nex`, byte for byte, the same as the loader on a Next makes.

## 3. Run it

- **On a Next:** copy `Game.nex` to the SD card and choose it in the Browser.
- **In an emulator:** open `Game.nex` in JNext, CSpect or ZEsarUX. For example: `jnext --load Game.nex`.

## Good to know

- **The choices are fixed in the file.** A `.nex` built this way starts with the colours and cheats you picked. To
  change them, build it again. A `.nex` that carries the patch's menu and every option inside it is planned, so a
  built file can offer the same menu as the Next's loader.
- **Some games need several files.** A patch for a tape game can ask for more than one tape file (a Side A and a Side
  B, say). Its `.nfo` lists them all. Tape patches need a newer version of the tool than this one, which is in
  progress.
- **Problems.** "Refused: this is not the game file this patch was made for" means your file isn't the exact dump the patch lists: check the
  MD5 against the `.nfo`. "No module named nexclash" means `NEXCLASH_REPO` isn't set to the NexClash checkout.

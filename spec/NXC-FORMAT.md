# The .nxc file format, version 1 (draft)

By Jon Attree. Inspired by Bleugh.biz's nexclash, by Dean Woodyatt.

**Status: a draft, with Dean's go-ahead (2026-11-02) and not yet reviewed by him. Implemented by `tools/nxc.py` and by the dot command `firmware/nexclash.asm`, which matches it byte for byte on a Z80 emulator and in JNext running NextZXOS. Nothing here has run on a Next or a Tang.**

A `.nxc` file is a per-game NexClash patch. It holds what a NexClash build adds to a game and none of the game itself. With the player's own copy of the game, a loader rebuilds the `.nex` that NexClash built, byte for byte, and starts it. Without that copy, the patch is meaningless.

NexClash is by Dean Woodyatt (`bleughb/nexclash`, GPL-3.0-or-later). This format only packages what its engines produce. It does not replace them, and making a patch still needs a working
engine for the game.

## What a patch protects, and what it does not

The goal is that a patch can be handed around without handing around the game, or the sprite data built from it. The encryption exists so the patch is useless without the game. It is not strong security: a person who owns the game can always get the plain contents, and the cipher was chosen to be easy on a Z80. Nothing here is a legal opinion.

## Conventions

- Little-endian throughout. A bank is 16,384 bytes, numbered as in the `.nex` format.
- "ZX0" is Einar Saukas's ZX0 format, as made by its standard `zx0` compressor (version 2), chosen because Z80 decompressors already exist.

## File name

A patch is named `NAME.nxc`. The extension has to fit 8.3: NextZXOS's Browser goes by a file's short name, so the longer
`Cobra.nexclash` of early drafts is `COBRA~1.NEX` to it and is handed to `.nexload`, which reads it as a `.nex`. The tools
and the loader read a patch under any name, so files made under that name still work outside the Browser.

## File layout

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | Magic: ASCII `NXC1` |
| 4 | 1 | Format version: 1 |
| 5 | 1 | Flags: 0 (reserved) |
| 6 | 16 | Nonce: random, different for every file |
| 22 | | Blocks, to the end of the file |

Each block is a 4-byte ASCII tag (three letters and a version digit), a 4-byte length, and that many bytes of data. This is the same shape as the tagged blocks after OPT1 in a `.256`.

A loader must skip a tag it does not know, including a known name with a higher version digit. This holds for encrypted blocks too, because each has its own key stream.

As with `.256`, an extra block must never be required to play. Anything a stock Next cannot use must leave the game playable without it. A patch that truly needs a newer loader says so in `OPT1`, and is refused.

| Tag | Required | Encrypted | Contents |
|---|---|---|---|
| `OPT1` | yes | no | Loader level needed, and flags |
| `TGT1` | yes | no | The game file this patch needs |
| `INF1` | yes | no | What the patch is, and its credits |
| `PRF1` | no | no | How far it has been proven |
| `ROM1` | no | no | Which ROM the game's code needs |
| `KEY1` | yes | yes | Key check, patch file checksum and output checksum |
| `NEX1` | yes | yes | The `.nex` header |
| `SIT1` | yes | yes | Patch sites |
| `BNK1` | zero or more | yes, after its first 3 bytes | One whole bank |
| `PAL1` | no, zero or more | yes, after its name | One colour set |
| `TRN1` | no, zero or more | no | One trainer: its name and its POKEs |

Later blocks planned, all optional: `TGT2` (more dumps, tapes), `L2B1` (painted backdrops), `MEM1` and `SPR2` (Tang-only extras).

### OPT1

Byte 0: the loader level this patch needs (1). A loader below it must stop and say so. Byte 1: flags, all 0 for now.
Further bytes: reserved. This has the job of OPT1 in `.256`.

### TGT1 and INF1: readable text

Lines of `key=value`, ended by a newline, in ASCII where possible. A loader can print these to tell the player exactly which file is needed.

`TGT1` keys: `zxdb_entry` (absent if ZXDB does not list the file), `title`, `file` (the exact filename), `length`, `md5`.

A loader may read only the first 252 bytes of each of `TGT1` and `INF1`, and takes `file`, `title`, `publisher`, `patch_by`
and `colours_by` from them, so those lines go first. A line cut off there counts as absent.

`INF1` keys: `publisher` (for the menu, such as `Ocean, 1986`), `patch_by` and `colours_by` (optional, for the menu's credit
line), `build`, `nex_md5`, `nexclash`, `credit`. `credit` is required, and a patch from NexClash carries "Inspired by Bleugh.biz's nexclash". Anything derived from its GPL-3.0-or-later code keeps those terms as well.
`credit` lives here and in the project's documentation, including who painted a colour set: a loader need not show it on
its menu or play screens. `nxc.py credit PATCH GAME -o OUT --patch-by NAME --colours-by NAME` sets the two menu names, right
after `publisher`, and refuses if they would end past the first 252 bytes.

`PRF1` keys record, separately and never merged: replay verification, emulator run to gameplay, and hardware. A
replay proves game logic only: in the 2026 pilot, builds that passed it did not start in an emulator.

### ROM1

1 byte. 0: not stated. 1: the game's code runs on the Next's own ROM. 2: it needs the Sinclair 48K ROM, carried by the patch in the alt ROM. A snapshot that stops inside BASIC needs care: see NexClash's notes on ROM3.

### KEY1

20 bytes, encrypted: the ASCII text `NXC1-KEY`, then three 32-bit values: the CRC-32 of this patch file, the CRC-32 of the finished `.nex`, and the `.nex`'s length.

The patch file's CRC-32 covers every byte of the file except the 8-byte header and 20 bytes of data of `KEY1` itself, so it protects the readable blocks too.

If the first 8 bytes do not decrypt correctly, the player has the wrong file: stop and print `TGT1`. If the patch file's CRC-32 fails, the patch is damaged: stop. **Both checks come before
any decompression**, because Z80 ZX0 decompressors have no bounds checks, and a damaged stream could overwrite memory.

CRC-32 catches damage. It does not stop deliberate tampering by someone who owns the game, who can recompute it. So a loader must still bounds-check as below.

### NEX1

The 512-byte `.nex` header, ZX0-compressed, then encrypted. It lists the banks of the finished file and holds the start address.

### SIT1

Changes to banks that come from the game. Empty if there are none. Otherwise this table, ZX0-compressed, then encrypted:

- 2 bytes: the number of sites
- for each site: 1 byte bank, 2 bytes offset, 2 bytes length, then the new bytes

A loader must refuse a site whose bank the snapshot lacks, whose offset plus length passes 16,384, or which runs past the end of the table, and a table with bytes left over.

The table must be no longer than 24,576 bytes once decompressed, which is what the loader holds at once. The largest in 52 builds is 23,058.

Original bytes are deliberately not stored. The key check already proves the game file is the right one.

### BNK1

A bank the game does not supply: start-up code, hooks, sprites.

- 1 byte: bank number, in the clear
- 2 bytes: length before compression (trailing zeros removed), in the clear
- the data, ZX0-compressed, then encrypted. Absent if the length is 0, and then nothing may follow.

A loader must refuse a length over 16,384, a bank number of 112 or above, or a bank given twice, and must decompress into a buffer that a wrong length cannot escape.

Every ZX0 stream, here and in `NEX1` and `SIT1`, must make exactly the length expected, no more, must copy only from
within what it has made, and must end with its end marker on its last byte. Anything else is damage.

### PAL1

An alternative set of colours for the finished build, such as a repaint from NexClash's colour sheets.

- 1 byte: the set's index, in the clear, which is also its key-stream index
- 1 byte: name length, 1 to 25, then the name in ASCII, in the clear, so a loader can offer the sets by name. A name that
  does not fit in the block is damage, as it is with `TRN1`
- the changes, ZX0-compressed, then encrypted: the finished `.nex`'s CRC-32 and length with this set (4 bytes
  each), then entries of 1 byte bank, 2 bytes offset, 2 bytes length, then the bytes, up to the end of the table

A loader must refuse an entry whose bank the `.nex` header does not list, whose offset plus length passes 16,384, or which
runs past the end of the table, and a table shorter than its 8 bytes of CRC and length. Entries apply in order. Unlike
`SIT1`, an entry may be in a bank from `BNK1`. The table must be no longer than 24,576 bytes once decompressed, as with
`SIT1`, and a loader holds it as well as `SIT1`. A stream is checked as in `BNK1`.

Applied after the default build is rebuilt and checked, and then checked again: both the CRC and length in `KEY1`, of the
build without the set, and those in the set must match, or the file is deleted. A loader that writes a bank at a time runs
both CRCs as it goes, and makes both checks when the file is complete. A set can change only bank contents, not the
header, so it cannot change how the game starts. A loader that does not know this block plays the default colours. A patch may hold several sets, for tools; the menu offers the first in the file. A set is decoded only when it is chosen: a damaged one that is not chosen, in a file whose CRC is good, does not stop the game.

### TRN1

A cheat, in the terms of a `.pok`, resolved when the patch is made. Not encrypted: the menu shows the names before the game
has been read, the POKEs are small public values taken from public files and hold nothing of the game, and the file
CRC in `KEY1` covers them as it does the other readable blocks. A `.pok`'s original values are not stored, since those
would be game bytes.

- 1 byte: flags. Bit 0: on by default. Shipped patches leave it clear.
- 1 byte: length of the name, 1 to 25, then the name in ASCII
- 1 byte: number of POKEs, 1 to 255
- for each: 1 byte bank, 2 bytes offset (below 16,384), 1 byte value

The length of the block must be exactly that. `nxc.py import-pok` builds these from a `.pok`. A `.pok` line's bank field 0 to
7 means that bank paged at 0xC000; 8 means no paging, so an address means what it does in the snapshot as saved: bank 5
at 0x4000, bank 2 at 0x8000, and at 0xC000 the bank 7FFD selects on a 128K game, bank 0 on a 48K one. Below 0x4000 is refused.
A trainer asking the player for a value (256 in the `.pok`) is left out for now. A POKE landing on a byte the patch
changes, a colour set's changes included, or in a bank the patch supplies, is refused when the patch is made, since its
target is no longer the game's own code there. `--only "Name,Name"` imports just those trainers, in the `.pok`'s order;
a name the `.pok` lacks or that asks for a value is an error.

Trainers apply to what is chosen, in the order of the file, so with two on the same byte the later wins. With the clash
fix on they apply over the base build, and over a colour set if one is on, after the CRCs are computed: the CRC and length
in `KEY1` and in a set are always of the build without POKEs, and a failure leaves no file. A loader offers the first 8 and holds at least 128 POKEs at once,
refusing a choice with more. A trainer's bank must exist in what is being written.

**A trainer voids the replay proof.** `PRF1` describes the base build, and says nothing of a build with a trainer on.

## The key stream

An RC4-style state, keyed by the whole game file, so that it needs nothing beyond a 256-byte table
and has no multiplication. Every encrypted block gets its own stream from that state.

```text
s[n] = n for n in 0..255;  i = j = 0
for each byte b of (nonce + game file + nonce):
    i = i + 1;  j = j + s[i] + b;  swap s[i], s[j]      (all modulo 256)
keep this state: the base

for each encrypted block, starting from a copy of the base:
    do the same absorbing for the 4-byte tag, then 1 index byte (BNK1: its bank number; PAL1: its index; otherwise 0)
    discard the first 256 output bytes
    each output byte:
        i = i + 1;  j = j + s[i];  swap s[i], s[j];  output s[s[i] + s[j]]
```

The key must not be a checksum of the game. ZXDB and TOSEC publish those, so a key derived from
one could be computed without owning the game. Hashing the file through this state with a per-file
nonce avoids that; a test confirms that the published MD5, SHA-1 and SHA-512 do not unlock a patch.

RC4 has known weaknesses and is not used here for secrecy against someone determined. It suits the
goal and the CPU. To be reviewed before release.

## Applying a patch

1. Read `OPT1`, `TGT1`, `INF1` and the names of any `TRN1` and `PAL1`, walking every block; a block that does not fit in the file, or a
   required one not there exactly once, is damage. Check `OPT1`'s level. Find the game file: `TGT1`'s name beside the patch,
   then the patch's name with `.z80`. Show the menu.
2. Clash fix on, or off with a trainer on: absorb nonce, game file, nonce, as the base state.
3. Decrypt `KEY1`. If the key check fails, stop and say which file is needed. If the patch file's
   CRC-32 fails, stop and say the patch is damaged. Nothing has been decompressed or written yet.
4. Clash fix on: decrypt `NEX1` for the header and `SIT1` for the table, and check the whole table. With a colour set
   chosen, decrypt its `PAL1` under its own index and check the whole of that table too. Nothing has been written yet.
5. Write the `.nex` a bank at a time: the header, then each bank it lists, in `.nex` order (5, 2, 0, 1, 3, 4, 6, 7,
   then upward), from `BNK1` if present, otherwise from the game with `SIT1` applied. Fill short banks with zeros. Run the
   CRC over each bank, then apply the set's entries for that bank and run the set's CRC over it, then apply the trainers'
   POKEs, then write it.
6. Check the CRC-32 and length against `KEY1`, and against the set if one is on. If any differ, delete the file and report
   damage.
7. Start the `.nex` with NextZXOS's own loader.

The clash fix off with a trainer on writes the game as a `.z80` of whole pages with the POKEs in place, under the game's
own header (version 1 becomes version 2). With no trainer it is the game file itself, with no check at all.

A loader offers the same choices for every game, with trainers off, the clash fix on and enhanced colours off to begin with:

```text
 JETPAC                    Ultimate, 1983

 TRAINER
  1  Infinite lives            [OFF]

 NEXCLASH
  2  Colour clash fix          [ON]
  3  Enhanced colours          [OFF]

 ENTER to play

Patch: Jon Attree  Colours: Alberto Conde
```

- **Colour clash fix.** On, the rebuilt NexClash `.nex`. Off, the player's own game, with any trainers.
- **Enhanced colours.** Shown only for a patch with a `PAL1`. ON uses the first set in the file, and the menu shows `[ON]` or
  `[OFF]`, not its name. With the fix off it reads `[N/A]`, its key does nothing and no set is applied, and the choice is
  back when the fix is turned on.
- **The credit line.** `Patch: <patch_by>     Colours: <colours_by>`, under the rest, showing only the parts present, the
  colours only for a patch with a `PAL1`, and no line if neither. It starts in the first column and fits 41. A name is
  cut to 32 characters, and with both the gap of 5 closes to 2 before a name is cut: the first then keeps at least 11
  characters and the second what is left. So `Patch: Jon Attree     Colours: Alberto Conde`, at 44 columns, shows with a gap of 2.
  Anything unprintable shows as `?`. Dean's credit is not on this line; it stays in usage and documentation.
- Lines are numbered from 1 and the keys match, so the tenth line, 8 trainers and these two, is on key 0.
- ENTER and SPACE both start with what the menu shows. BREAK cancels.

The set a patch makes its NexClash look is its base build.

The loader is the dot command `firmware/nexclash.asm`. It writes to `/tmp` and leaves `%x` as 1 for a `.nex` or 2 for a
`.z80`, and a line in `browser.cfg` with a small merged program starts the result: see `firmware/README.md`, which also
gives what was tried and what is assumed. Both have run in JNext on real NextZXOS, not on a Next.

## Limits of version 1

- **Exact file only.** One byte different in the game file is refused. Accepting other dumps would
  need a check per site, and a later block. **This will change before release:** the key stream is tied to one game file,
  and is being redesigned so that one patch can accept several dumps of a game, and later tapes. That breaks existing patches.
- **Snapshots only.** `.z80` first. Tapes need a new kind of target, hence the version digit in
  `TGT1`.
- **Rebuilding is not proof of playing.** An exact rebuild shows the file is identical to the original
  build. It says nothing that the build's own testing did not.
- **Multi-load games** are out of scope.

## Open questions

- Whether all of this holds on a Next. On emulated T-states at 28 MHz with no wait states and no file I/O, Cobra (42,218-byte
  game, 98,816-byte `.nex`) takes 1.24 s, and the largest of 52 builds (492,032 bytes) 4.12 s. In JNext, with its
  emulated card, Cobra takes 2.2 s from Enter to the finished file.
- Whether Dean is happy with this packaging of his engines' output.
- Which proof fields `PRF1` should carry.
- Whether to prefer clean originals over dumps such as `[t]` trained ones when rebuilding patches.

## How this relates to `.256`

Same conventions: tagged blocks of three letters and a version digit, skipping what a loader does not know, a level in
OPT1, and a rule that extras are never required to play. Different purpose: a `.256` holds the whole game with colour
planes at fixed offsets, whereas a patch holds only changes.

| `.256` block | Here |
|---|---|
| Registers, 7FFD, memory banks, AYS1 | Not needed: from the player's snapshot; changes in `SIT1`, `BNK1` |
| CFG, RUL1 | No equivalent: hooks do this |
| GRX1 | No direct equivalent; ROM needs go in `ROM1` |
| Backgrounds, BGX1, BGX2 | `L2B1` later |
| CRD1 | `INF1` |
| OPT1 | `OPT1` |


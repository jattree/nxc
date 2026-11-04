# The .nxc file format, version 1 (draft)

By Jon Attree. Inspired by Bleugh.biz's nexclash, by Dean Woodyatt.

**Status: a draft, with Dean's go-ahead (2026-11-02) and not yet reviewed by him. Implemented by `tools/nxc.py` and by the dot command `firmware/nexclash.asm`, which matches it byte for byte on a Z80 emulator and in JNext running NextZXOS. Nothing here has run on a Next or a Tang.**

A `.nxc` file is a per-game NexClash patch. With the player's own copy of the game, a loader rebuilds the `.nex` that NexClash built, byte for byte, and starts it.

NexClash is by Dean Woodyatt (`bleughb/nexclash`, GPL-3.0-or-later). This format only packages what its engines produce. It does not replace them, and making a patch still needs a working engine for the game.

## What a patch holds

A patch does not contain the game file or repeat its memory: a loader takes the game's own banks from the player's copy, a snapshot or a tape. But a patch does hold things.

**Readable by anyone, in the clear:** the name, length and MD5 of each accepted game file, and its ZXDB entry and title; the publisher, credits and proof text; each trainer's name and POKEs (bank, offset, value); each set's name, kind and identifiers; the bank numbers and trimmed lengths of the banks it supplies; which tape targets share a tape table; the sizes of all its blocks. The MD5s of accepted dumps are public anyway.

**Held encrypted:**

- the `.nex` header;
- the bytes each hook writes over the game (`SIT1`);
- whole banks the game does not supply (`BNK1`): start-up code, hooks and sprites. **Sprite data is derived from the game's graphics**, so a patch holds a transformed form of part of the game, encrypted. It is not free of the game's content;
- sets (`SET2`), such as colours and languages, which may hold repainted graphics, translated text and new code;
- a loading screen, if there is one (`SCR1`). **Such a screen, unlike sprites derived from the game, may be art the player's own file does not contain, so a patch with one holds that art, encrypted.**
- for a tape, its table (`TAP1`): where in memory the tape's bytes go, the registers the game starts with, and **the bytes of that start that are not on the tape**: the screen as drawn, variables, the stack, and tables the game's own code made as it ran. Those are derived from the game, as sprites are. Anything the tape holds as it is, code above all, is taken from the player's tape and not carried.

Encryption is not protection from someone who owns an accepted dump: see below.

## What the encryption and the keyed check do, and do not do

The goal is that a patch can be handed around without handing around the game, or the sprite data built from it, and that a person without the game cannot change a patch unnoticed. Nothing here is a legal opinion.

**Someone who owns any accepted dump can recover the master key, read everything in the patch, and forge a patch that passes every check,** including a different start-up, different code and different trainers. A patch from a stranger who owns the game is as trustworthy as that stranger: a rebuilt `.nex` that passes its checks is still executable code, not sandboxed content.

Someone who does not own the game cannot, as far as is known, do these things. Every clear field and every encrypted block is covered by the check value, and making that value needs the master key. A test confirms that the attack on the first draft, flipping a clear value and repairing a checksum, is refused.

**This is not cryptographic strength.** It is an RC4-style state, chosen because it needs a 256-byte table and no multiplication on a Z80. RC4-style states have known weaknesses, including biased output and colliding keys, and using one to authenticate a file is not an established construction. The check has no proof behind it, and has not been reviewed by a cryptographer. In 60 million blind tries of a change to one byte compensated in the next, on random states, no two end states matched; that is a measure of one attack, not a bound.

The key must not be a checksum of the game. ZXDB and TOSEC publish those, so a key derived from one could be computed without owning the game. Absorbing the whole file through this state, with a per-file nonce, avoids that: a test confirms that the published MD5, SHA-1 and SHA-512 unlock nothing. That proves substitution fails, not strength.

## Conventions

- Little-endian throughout. A bank is 16,384 bytes, numbered as in the `.nex` format.
- All arithmetic on state values is modulo 256.
- "ZX0" is Einar Saukas's ZX0 format, as made by its standard `zx0` compressor (version 2), chosen because Z80 decompressors already exist.
- "CRC-32" is the common one: reflected polynomial 0xEDB88320, initial value 0xFFFFFFFF, final XOR 0xFFFFFFFF, so that the ASCII text `123456789` gives `cbf43926`.
- Encrypting is XOR, byte by byte, with the output of a stream.

## File name

A patch is named `NAME.nxc`. The extension has to fit 8.3: NextZXOS's Browser goes by a file's short name, so a longer one such as `Cobra.nexclash` is `COBRA~1.NEX` to it and is handed to `.nexload`, which reads it as a `.nex`. The tools and the loader read a patch under any name.

## File layout

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | Magic: ASCII `NXC1` |
| 4 | 1 | Format version: 1 |
| 5 | 1 | Flags: reserved, must be 0 |
| 6 | 16 | Nonce: fresh random bytes for every patch |
| 22 | 16 | Check value: see "The keyed check" |
| 38 | | Blocks, to the end of the file |

A file shorter than 38 bytes, with another magic or version, or with flags set, is not a patch this reader can read.

Each block is a 4-byte ASCII tag (three letters and a version digit), a 4-byte length, and that many bytes of data. A block that does not fit in the file is damage, and so is a file ending inside a block header. Blocks may come in any order, except that target entries number themselves. A writer puts the ones a loader needs for its menu first.

A reader skips a tag it does not know, including a known name with a higher version digit. This holds for encrypted blocks too, because each has its own stream. The check value covers skipped blocks too.

An extra block must never be required to play. A patch that truly needs more than a loader can do says so in `OPT1`, and is refused.

| Tag | Required | Encrypted | Contents |
|---|---|---|---|
| `OPT1` | once | no | Loader level needed, and flags |
| `TGT1` | 1 to 32 | key wrap only | One accepted game file |
| `INF1` | once | no | What the patch is, and its credits |
| `PRF1` | no | no | How far it has been proven |
| `ROM1` | no | no | Which ROM the game's code needs |
| `OUT1` | once | yes | The finished `.nex`'s CRC-32 and length |
| `NEX1` | once | yes | The `.nex` header |
| `SIT1` | once | yes | Patch sites |
| `BNK1` | zero or more | yes, after its first 3 bytes | One whole bank |
| `SCR1` | one per 16K of screen | yes, after its first 3 bytes | Part of the `.nex`'s loading screen |
| `SET2` | no, zero or more | yes, after its name and the heads of its chunks | One choice of a kind: a colour set, a language |
| `TRN1` | no, zero or more | no | One trainer: its name and its POKEs |
| `TAP1` | one for each group of tape targets | yes, after its first 2 + n bytes | How one or more tapes become the game's banks |

A second `OPT1`, `INF1`, `OUT1`, `NEX1` or `SIT1` is damage at once, however many there are.

### Names reserved

These names and their rules are reserved. They are not defined further, and no tool or loader here implements them. A reader that does not know one skips it, so none of them can be required to play unless `OPT1` says so, which refuses it on a loader that cannot do it.

| Tag | For |
|---|---|
| `BUN1` | A bundled `.nex`: a build the owner may distribute whole |
| `CAC1` | A build cache. Its identity must include the patch's content and every option chosen |
| `TRN2` | A trainer that asks the player for a value |
| `L2B1` | Layer 2 backgrounds, with rules below |
| `MNU1` | A picture behind a loader's menu, with rules below |
| `SNP1` | The per-input baselines of snapshot output, with rules below |
| `MEM1`, `SPR2` | Extras for machines with more memory or sprites than a Next, such as the Tang |

Custom loaders are not part of this standard. A game that needs one is out of scope, and a per-game adapter belongs in the engine that made the build.

### OPT1

Exactly 3 bytes. Byte 0: the loader level this patch needs. Byte 1: flags, each something the patch needs besides its level. A reader that does not have the level, or sees a flag set for something it cannot do, stops and says it needs a newer loader. Byte 2: the highest 16K bank the rebuilt game needs, 0 to 111. Any other length or value is damage.

| Flag | Means the patch needs a loader that can | A patch must set it when |
|---|---|---|
| Bit 0 | Read tape targets, with `TAP1` | It has no snapshot target (`.z80` or `.sna`) at all |
| Bits 1 to 7 | Reserved, 0 | |

A patch with only tape targets that does not set bit 0 is damage. Tapes are a flag and not a level because levels are a ladder, each including those below, and a loader that reads tapes need not read `.sna` or write snapshots. A loader older than this flag sees it set and refuses, as it should; one that skipped it would find no target it could read, and say the same.

| Level | Means the loader can | A patch must say it when |
|---|---|---|
| 1 | Read `.z80` targets, and everything in this document but `SCR1` | Always at least this |
| 2 | Also write a loading screen from `SCR1` | It holds a `SCR1` |
| 3 | Also read `.sna` targets | It has a snapshot target, but no `.z80` one |
| 4 | Reserved: snapshot output, below | It has no sprite build at all. Nothing here writes or reads it |

A loader that is shown a patch of its level or below can do all of it. `SCR1` makes a level necessary rather than optional because a loader that skipped it would write a wrong `.nex`: a patch with a `SCR1` that says level 1 is damage. A `.sna` target in a patch that also has a `.z80` target does not raise the level, as a level 1 or 2 loader skips the entry and uses the others. The level is worked out from the snapshot targets alone, so a patch with only tapes is level 1, or 2 with a `SCR1`, and sets bit 0; a tape in a patch that has a snapshot target too raises nothing, as a loader that cannot read tapes skips the entry.

`tools/nxc.py` is level 3 and reads tapes. `firmware/nexclash.asm` is level 2, and does not read tapes yet. Both refuse level 4. `SET2` raises no level: it is an extra, so a loader that does not know it skips it and offers no such line, and the game still plays.

**Memory.** Byte 2 lets a loader on a smaller machine refuse rather than start a game that breaks. A writer works it out from the `.nex`: the highest bank the header lists, or 48 if the header's byte 8 asks for 1792K, whichever is higher. That is all the file shows: a build may use banks at run time that it does not load, such as Layer 2 buffers, so an author may raise it, and nothing can lower it. A reader refuses a value below a bank the header lists.

A loader that can find out how much there is compares `2 x (byte 2 + 1)` with the 8K banks of ZX memory, and if there are too few, refuses the rebuilt game, saying so. A 1MB Next has banks 0 to 47, and a 2MB Next banks 0 to 111. `firmware/nexclash.asm` asks NextZXOS, with `IDE_BANK` and reason `rc_bank_total` through `M_P3DOS`, when ENTER is pressed with the clash fix on. If NextZXOS will not say, it goes on. The clash fix off is the player's own game, and is not checked. `.nexload` does not check its header's byte 8 itself, as its source on the card shows.

### Text blocks

`INF1`, `PRF1`, and the end of each `TGT1` are lines of `key=value`, each ended by one line feed (0x0A), with no carriage returns. A key is lower-case letters, digits and `_`. A writer uses only printable ASCII, 0x20 to 0x7E. A reader that finds anything else in a value it shows, shows `?`. A key is not repeated: a reader takes the first. A reader skips a key it does not know. An empty value is written as no line at all.

A loader may read only the first 252 bytes of a text, so the lines it needs go first. A line cut off there counts as absent.

### TGT1: one accepted game file

One block per accepted dump, at least 1 and at most 32. The most was set by measuring: an entry costs 56 bytes of patch and its text, 2 ms at 28 MHz when its length matches and nothing when it does not, and needs no memory, since the entries are walked in the file. 32 of one length add 0.07 s and about 1.8K, before file I/O.

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | Index: its place among the file's `TGT1` blocks, from 0 |
| 1 | 1 | Kind: 1 `.z80`, 2 `.sna`, 3 `.tap`, 4 `.tzx` |
| 2 | 4 | The file's length in bytes |
| 6 | 24 | Key wrap, encrypted: the ASCII text `NXC1-KEY`, then the 16-byte master key |
| 30 | | Text |

A reader skips an entry of a kind it does not know, or cannot read, for finding the game, but still checks its index and name. Text keys:

- `file`: required, and within the first 252 bytes of the text. The name a player has it under. See below.
- `md5`: required of a writer, 32 lower-case hexadecimal digits of the whole file. It is there to tell a person which file is wanted. A reader may ignore it, as it unlocks nothing.
- `title`: optional. A loader's menu shows the first one in the file.
- `zxdb_entry`: optional. Absent if ZXDB does not list the file.

**`file` is a bare name, never a path.** 1 to 127 bytes of printable ASCII, with none of `/ \ : * ? " < > |`, no `..` anywhere, no space first, no space or dot last. Anything else makes the whole patch damage, whichever kind the entry is, so that a wrong name can never open another path. A loader puts it after the patch's own folder: if that does not fit, it refuses, and never cuts a name short. `firmware/nexclash.asm` holds 223 bytes of path.

A writer refuses two entries with the same MD5, or the same `file` whatever the case, so that a loader does not open one file twice for two entries; and two entries of different kinds with the same length, so that a loader can tell from the length alone which kind a file is. A reader need not check this.

Every entry in a patch must rebuild the same banks. A writer checks that, by rebuilding, before it writes anything: only the banks matter, since the `.nex` carries its own start-up state, so dumps with different registers but the same memory are the same to it. With the clash fix off each player gets their own file, so its registers are theirs. A tape's banks are those its `TAP1` makes, which include any extra banks, so a tape that places a multiload's blocks and a snapshot cannot be entries of one patch.

### INF1

Keys: `publisher` (for the menu, such as `Ocean, 1986`; a loader may show the first 16 characters), `patch_by` and `colours_by` (optional, for the menu's credit line), `build`, `nex_md5`, `nexclash`, `credit`, and for languages, all optional and not needed to play: `game_language`, the ISO 639 code of the language the game itself is in; `language_codes`, each language set's code as `Name=code`, comma-separated, such as `Espanol=es`; and `text_by`, who translated it, kept here and not on the menu. A writer always includes `credit`, and a patch from NexClash carries "Inspired by Bleugh.biz's nexclash". Anything derived from its GPL-3.0-or-later code keeps those terms as well. `credit` lives here and in the project's documentation, including who painted a colour set: a loader need not show it on its menu or play screens. `nxc.py credit PATCH GAME -o OUT --patch-by NAME --colours-by NAME` sets the two menu names, right after `publisher`, and refuses if they would end past the first 252 bytes.

### PRF1

What has been shown about this build, with each kind of proof separate and never merged. Any may be left out, and leaving one out says nothing was recorded. Each has a `_when` giving the date it was true.

| Key | States |
|---|---|
| `replay`, `replay_when` | What was replayed against the original, and the result. Proves game logic only: in the 2026 pilot, builds that passed it did not start in an emulator |
| `emulator`, `emulator_when` | Which emulator and version, what was reached, and who played it if anyone |
| `hardware`, `hardware_when` | Which machine, and what was reached. `none` if nothing has run on hardware |
| `coverage`, `coverage_when` | What the proof above did not exercise |

Optional display results, from comparing what the build shows with a reference:

| Key | States |
|---|---|
| `display_samples` | How many were compared |
| `display_exact` | How many matched exactly |
| `display_misses` | The misses, by name |
| `display_approved` | The differences someone approved, and who |
| `display_model` | What the reference was |
| `display_when` | When |

A figure for how long something takes goes in `timing`, with `timing_when`, and states the machine and speed it was measured at. It is a record, not a requirement: no model of timing is part of this format.

A trainer voids the replay proof. `PRF1` describes the base build, and says nothing of a build with a trainer on.

### ROM1

1 byte. 0: not stated. 1: the game's code runs on the Next's own ROM. 2: it needs the Sinclair 48K ROM, carried by the patch in the alt ROM. A snapshot that stops inside BASIC needs care: see NexClash's notes on ROM3. A loader need not read this block.

### OUT1

Exactly 8 bytes, encrypted under `OUT1`, index 0: the CRC-32 of the finished `.nex` without trainers or sets, then its length.

### NEX1

The 512-byte `.nex` header, ZX0-compressed, then encrypted under `NEX1`, index 0. It must decode to exactly 512 bytes, starting with `Next`. It lists the banks of the finished file and holds the start address.

What can be packaged is a `.nex` of version `V1.0`, `V1.1` or `V1.2`, laid out as header, then any loading screen, then the listed banks in `.nex` order and nothing after them. A writer refuses anything else, including a bank flag other than 0 or 1, or a bank count at byte 9 that disagrees with the flags. A reader treats any bank flag that is not 0 as listed.

### SIT1

Changes to banks that come from the game. Empty if there are none. Otherwise this table, ZX0-compressed, then encrypted under `SIT1`, index 0:

- 2 bytes: the number of sites
- for each site: 1 byte bank, 2 bytes offset, 2 bytes length, then the new bytes

A reader refuses a site whose bank the game lacks (for a tape, the banks its `TAP1` makes), that the `.nex` header does not list, or that a `BNK1` supplies; whose offset plus length passes 16,384, or which runs past the end of the table; and a table with bytes left over.

The table must be no longer than 24,576 bytes once decompressed, which is what the loader holds at once. The largest in 52 builds is 23,058.

Original bytes are deliberately not stored. The key check already proves the game file is the right one.

### BNK1

A bank the game does not supply: start-up code, hooks, sprites.

- 1 byte: bank number, in the clear
- 2 bytes: length before compression (trailing zeros removed), in the clear
- the data, ZX0-compressed, then encrypted under `BNK1` with the bank number as index. Absent if the length is 0, and then nothing may follow.

A reader refuses a length over 16,384, a bank number of 112 or above, a bank given twice, or a bank the `.nex` header does not list. Such an unlisted block is never used, and refusing it means two readers cannot differ over whether its contents matter. A reader must decompress into a buffer that a wrong length cannot escape.

Every ZX0 stream, here and in `NEX1`, `SIT1`, `SCR1` and `SET2`, must make exactly the length expected, no more, must copy only from within what it has made, and must end with its end marker on its last byte. Anything else is damage.

### SCR1: a loading screen

What lies between the `.nex`'s header and its banks, for a `.nex` that has a loading screen. `.nexload` shows it while it loads the banks. The `.nex` header's byte 10 says how much there is, read as `.nexload` reads it:

| Byte 10 | Bytes in this order, if set |
|---|---|
| Palette | 512, unless byte 10 is 0, or bit 7 is set, or any of bits 1, 3, 4 is set |
| Bit 0, Layer 2, 256 x 192 | 49,152 |
| Bit 1, ULA | 6,912 |
| Bit 2, lo-res | 12,288 |
| Bit 3, Timex hi-res | 12,288 |
| Bit 4, Timex hi-colour | 12,288 |
| Bit 5 or 6 | **Not supported in this version: refused** |

Bits 5 and 6 belong to later `.nex` versions and their 320 x 256, 640 x 256 and tilemap screens, which this format does not hold because it holds only `V1.0` to `V1.2`. A writer refuses to package one, saying why, and a reader that meets one says it needs a newer loader.

The most, with every type at once, is 92,928 bytes. These bytes are cut into 16K pieces, the last shorter, each in a block of its own:

- 1 byte: its index, from 0, in the clear
- 2 bytes: length before compression (trailing zeros removed), in the clear
- the data, ZX0-compressed, then encrypted under `SCR1` with its index. Absent if the length is 0, and then nothing may follow.

So a loader needs no more than the 16K it already has for a bank. A reader refuses an index past the last piece, an index given twice, a piece missing, a piece with no screen listed, or a length over that piece's room. The bytes are part of the file the CRC-32 and length in `OUT1` describe, and a set must not change them. A patch with a `SCR1` says level 2 in `OPT1`.

**What a player sees depends on the build, not on this format.** `.nexload` loads the listed banks after the screen, in `.nex` order, so a ULA, lo-res or Timex screen, which lives in bank 5, is written over as soon as bank 5 loads, which is first; and Layer 2 lives in banks 9, 10 and 11, so any of those the build lists overwrites its third of the screen. In JNext a Layer 2 screen on a build listing banks 10 and 11 kept only its top third, and a ULA screen on a build with a bank 5 was not seen at all in frames a few apart; on a build listing neither, each stayed up and looked right. Showing a screen while the loader builds is a separate idea, and is not part of this.

### SET2: a choice of a kind

An optional set of byte replacements, on the menu: a colour set, a language. One block per set. It replaces `SET1`, whose one table had to fit in the loader's memory; no patch that left this project's hands ever used that, and a reader now skips it as it does any other tag it does not know. A patch that held one is made again from its builds. **A set is always an option on the menu, however big. A base build never has to carry someone's colours for them to fit.**

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | Stream index, in the clear. **Unique among all `SET2` blocks**, of any kind or base, or two would use one stream. A repeat is damage |
| 1 | 1 | Kind: 1 colours, 2 language. Others are reserved |
| 2 | 1 | Choice ID: which choice this is within its kind. It stays the same when a patch is remade, and is shared by the versions of one choice on different bases. A writer keeps kind, choice and base unique together |
| 3 | 1 | Base: 1 the sprite build, 2 the plain game (reserved: see "Snapshot output") |
| 4 | 1 | Length of the name, 1 to 25 |
| 5 | | The name in ASCII, in the clear, so a loader can offer it. A name that does not fit in the block is damage. A writer keeps names unique within a kind |
| | 4 | The CRC-32 of the finished file with this set alone over the base, encrypted under tag `SEB` plus the stream index, index 255 |
| | | Its chunks, to the end of the block |

**A chunk** is what the set changes in one bank:

| Size | Field |
|---|---|
| 1 | The bank, in the clear |
| 2 | The length of its stream, in the clear, not 0 |
| | Its stream: the chunk's plain bytes, ZX0-compressed on their own, then encrypted under tag `SEB` plus the stream index, with the bank as index |

The plain bytes are a **bitmap** of 2,048 bytes, one bit for each byte of the bank, the top bit of the first being offset 0; then, for each bit set, in rising order of offset, the byte to write there. So a chunk is at most 18,432 bytes whatever the bank holds, and that is the most a loader ever holds of a set at once. A set has no limit of its own: every bank a `.nex` can list may be changed in full.

A reader refuses: a block too short for the CRC; a chunk's head or stream running past the block; a stream of length 0; plain bytes that are not a bitmap and exactly one byte for each bit set, with at least one bit set; and any chunk out of `.nex` order, repeated, for a bank of 112 or above, or for a bank the `.nex` header does not list. The last group is found by going through the listed banks in order and taking the next chunk only if it is for that bank: **a chunk not taken by the end is damage.** A stream is checked as in `BNK1`. Nothing in a chunk says where a byte goes but its place in the bitmap, so no chunk can reach outside its bank. An entry may be in a bank from `BNK1`, and may overwrite bytes that `SIT1` changed.

A writer leaves out a bank the set does not change, and writes the chunks in `.nex` order, so that a loader can keep one position per set and hold one chunk at a time.

**Why this layout, as measured.** On the real sets in hand, packed with `zx0` version 2, all sizes in bytes. "Before" is `SET1`'s single table of (bank, offset, length, bytes):

| Set | Banks changed | `SET1` table | `SET1` packed | Same entries, one stream per bank | Bitmap chunks, plain | Largest chunk | **Bitmap chunks, packed** |
|---|---|---|---|---|---|---|---|
| Everyone's a Wally | 8 | 67,919 | 26,308 | 26,617 | 43,389 | 6,823 | **11,366** |
| Sabre Wulf | 5 | 39,330 | 21,379 | 21,526 | 31,376 | 9,281 | **13,629** |
| Underwurlde | 5 | 32,625 | 16,409 | 17,027 | 22,441 | 6,164 | **8,823** |

Splitting by bank alone costs 1 to 4%. Moving the offsets out of the bytes more than pays for that: the sets above have thousands of short runs, and each run's 5-byte head compresses badly. Holding more of the table in RAM was the other choice measured against: a linear table of 128K needs 16 pages and a decoder that follows its back-references across a paged window, for nothing a player sees, on every bank. Here a set needs the same three pages however big it is. `tests/test_nexclash_dot.py` holds a set of 165,888 decoded bytes.

**One choice per kind.** Alternatives within a kind may overlap, as they can never be chosen together. Sets of different kinds **must not overlap**: a writer refuses any pair that could be chosen together, and a loader refuses the actual selection, by comparing the bitmaps of the two chunks of each bank, before it makes any file. That holds even for two sets writing the same bytes to the same place. Kinds say what the menu offers, not what works together: two sets that do not overlap can still disagree about pointers or fonts, and nothing here shows that a combination plays.

**The check.** With the file's length and layout the same, and the replacements disjoint, CRC-32 being affine for equal lengths gives one value per set instead of one per combination:

```text
CRC(combination) = CRC(base) XOR (CRC(set 1) XOR CRC(base)) XOR (CRC(set 2) XOR CRC(base)) ...
```

where `CRC(base)` is in `OUT1` and `CRC(set n)` in each block. A loader runs one CRC-32 over the real output, with sets applied and before any POKEs, and compares it and the length with those. With no set chosen that is `OUT1` itself. If they differ, the file is deleted. That checks the reconstruction, as a CRC over a table could not. It is checked as the file is written, not read back from the card.

A reader that does not know a kind or a base checks the block's shape and index, and does not offer it. A set is decoded only when it is chosen, so a damaged stream in a set that is not chosen, in a file whose check value is good, does not stop the game.

**Memory.** A loader needs one bitmap and its bytes for each set chosen, for one bank at a time, as well as `SIT1`: `firmware/nexclash.asm` keeps three 8K pages for each, so 72K for one set and 96K for two, the same whatever the size of the set, and says so if it cannot get them. A 1MB Next has 96 8K pages of ZX memory, so this is well within it. What a build needs to run is separate, and is in `OPT1`.

**A set can change how a game starts.** It cannot change the header, but it can change any byte of any listed bank, and those banks hold the start-up code and hooks. An unchanged header says nothing about that. A set from a stranger is code, as the rest of a patch is.

### Reserved: snapshot output

No tool or loader here writes or reads this. A language-only patch, for a game with no sprite build, uses this same container, with `OPT1` level 4, and has no `NEX1`, `SIT1`, `OUT1` or `BNK1`. Its output is a snapshot, not a `.nex`, and none of the sprite machinery is involved. Input kinds stay as they are: "language" is a set's kind, never a target's.

- **Applying a language must pass the keyed check.** The unchecked copy of the plain route is only for the file with nothing applied.
- **The output is deterministic:** a `.z80` of whole pages under the input's own header, version 1 becoming version 2, as the clash fix off with a trainer writes now.
- **The baselines are per input.** Accepted dumps must have the same banks, but may keep different registers, so one CRC of a whole file cannot cover them. `SNP1` holds, encrypted, for each target by its index, the CRC-32 and length of that input's header part. The pages are common to them all: one CRC-32 of the pages, in `SNP1` too. A `SET2` with base 2 gives the CRC-32 of the pages with it alone, and the sum above applies to the pages.
- **A patch can do both**, with base 1 and base 2 versions of one language sharing a choice ID. The base 2 sets are extras a lower level skips, so that needs no level of its own. With the clash fix off such a language line stays available.

### Reserved: L2B1, Layer 2 backgrounds

No tool or loader here writes or reads this. The rules, so that nothing else takes the name or conflicts:

One or more pictures behind the game, each named, offered on the menu as a line of its own, whose key steps from `[OFF]` through the names. OFF is always offered. It is an extra: a loader that skips it plays the game without one, so it raises no level.

A picture is 49,152 bytes of Layer 2 at 256 x 192, in three consecutive 16K banks. It is cut, compressed and encrypted as `SCR1` is, under `L2B1` with a stream index unique among `L2B1` blocks. For a patch to run on a Tang, whose Layer 2 reaches only banks 8 to 31, the banks must all lie in that range, and be banks the build does not list. A writer refuses others.

**Its output cannot be checked as a set is.** Adding banks changes the `.nex` header (the bank flags and count, and the start address) and moves whatever comes after them, so the file differs in length and layout and the CRC sum above does not apply. Instead a loader runs two CRC-32s, in file order:

1. **The game's:** every byte of the file as if there were no background, that is, the header from `NEX1`, any screen, then the build's own banks with any sets. This must equal the sum above, whatever the picture.
2. **The picture's:** the changed header, then the added banks with the stub in them. This must equal the CRC-32 the `L2B1` holds for that picture. Length must be the base's plus 16,384 for each added bank.

POKEs apply after both, as now.

**A picture needs a start stub, or it will not be seen.** What an experiment found, in JNext only and not on hardware, on a copy of a NexClash Jetpac `.nex` and on unmodified games: registers set before `.nexload` or before the snapshot loader's `SPECTRUM` do not last, as both reset them. So:

- The stub goes in an added bank, not in the game's bytes, runs first, and ends by jumping to the build's own start address. For a `.nex`, the header's start address and entry bank are changed to reach it, which is why the second CRC covers the header.
- It sets: the Layer 2 bank (NR 0x12, 0x13) and port 0x123B's enable, scroll and clip (NR 0x16, 0x17, 0x71, 0x18, 0x1C), mode (NR 0x70), an identity Layer 2 palette (NR 0x43, 0x40, 0x41), layer order with Layer 2 behind (NR 0x15 = 0x09), the fallback colour (NR 0x4A), and transparency.
- **Transparency is a choice per picture and game.** Black paper alone see-through (ULA palette entries 16 and 24 made 0xE3, NR 0x14 = 0xE3) keeps black ink solid, and all black see-through (NR 0x14 = 0) does not; the first worked on the games tried, while a game that draws its scenery with black ink shows the picture around it, and dithered scenery suffered with either.
- **It must keep them set:** a game may change them, so a Copper list repeats the settings a game could undo, every frame. A palette is not in it, as the game may be writing its own through the same registers. NR 0x69 writes port 7FFD's shadow bit and Timex port 0xFF too, and so is a risk to a game using those.
- For the plain game, a dot command cannot run after the snapshot loader has prepared, so that route needs its settings in the merged loader line at that point. It is separate from this block and not defined here.

A picture is art, which a patch then holds, as a screen in `SCR1` is. The fallback for a machine that cannot do it is OFF.

### Reserved: MNU1, a menu backdrop

No tool or loader here writes or reads this. An optional picture behind a loader's menu. **A loader must work without it**, and must fall back to the plain menu for any reason it cannot show one. It raises no level.

- At most 512 bytes of palette and 49,152 of Layer 2 picture, at most 24,576 bytes as stored, as one ZX0 stream per 16K as `SCR1` is.
- **It is in the clear**, as the menu comes before the game is read and no key exists yet. So it must hold nothing from the game, and is not secret.
- **It is untrusted when shown:** the keyed check has not yet run. So a loader decodes it with the bounds this document requires, and never runs anything from it.

What it needs from a loader, which is why it is not built: three consecutive 16K banks for Layer 2 and memory to decode through, before the menu and on the caller's stack and paging; about 500 bytes more of code in the part used up to the menu, which there is room for; menu text kept readable over it, through transparency in the text mode; every register it changes put back on every way out, including every refusal, before `.nexload` or the snapshot loader runs; and time, perhaps half a second more before the menu, unmeasured.

### TRN1

A cheat, in the terms of a `.pok`, resolved when the patch is made. Not encrypted: the menu shows the names before the game has been read, the POKEs are small public values taken from public files and hold nothing of the game, and the check value covers them as it does the other clear blocks. A `.pok`'s original values are not stored, since those would be game bytes.

- 1 byte: flags. Reserved, must be 0, and refused otherwise: every menu starts with its trainers off, and nothing else is defined
- 1 byte: length of the name, 1 to 25, then the name in ASCII
- 1 byte: number of POKEs, 1 to 255
- for each: 1 byte bank (below 112), 2 bytes offset (below 16,384), 1 byte value

The length of the block must be exactly that. All of these are checked for every trainer, chosen or not, before the menu, so that readers agree on whether a patch is good. `nxc.py import-pok` builds these from a `.pok`. A `.pok` line's bank field 0 to 7 means that bank paged at 0xC000; 8 means no paging, so an address means what it does in the snapshot as saved: bank 5 at 0x4000, bank 2 at 0x8000, and at 0xC000 the bank 7FFD selects on a 128K game, bank 0 on a 48K one. Below 0x4000 is refused. A trainer asking the player for a value (256 in the `.pok`) is left out for now. A POKE landing on a byte the patch changes, the changes of any set included, or in a bank the patch supplies, is refused when the patch is made, since its target is no longer the game's own code there. `--only "Name,Name"` imports just those trainers, in the `.pok`'s order; a name the `.pok` lacks or that asks for a value is an error. A writer keeps names unique; a loader goes by position.

Trainers apply to what is chosen, in the order of the file, so with two on the same byte the later wins. With the clash fix on they apply over the base build, and over any sets on, after the CRC is computed: the CRC and length in `OUT1` and the CRC in a set are always of the build without POKEs, and a failure leaves no file. A loader offers the first 8, or the first 7 when it offers two kinds of set, as only ten lines have keys, and holds at least 128 POKEs at once, refusing a choice with more. A trainer's bank must exist in what is being written.

### TAP1: a game from a tape

A tape target, `TGT1` kind 3 (`.tap`) or 4 (`.tzx`), is found and keyed as any target is: by its length, then the key wrap, with `dump_base` absorbing the whole file. Its banks do not come from the file by a fixed layout, as a snapshot's do. They come from a table in a `TAP1` block: copies of bytes from the tape's data blocks into banks, then sites for what the tape does not hold, over banks of zeros. What that makes is the game's memory at the point the build starts from, and from then on a tape target is treated as a snapshot with those banks: `SIT1`, `BNK1`, sets and trainers work on them as on a snapshot's. The data blocks are defined in "Tapes", below.

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | Stream index, in the clear. **Unique among all `TAP1` blocks.** A repeat is damage |
| 1 | 1 | n, the number of tape targets it serves, 1 to 32 |
| 2 | n | Their `TGT1` indices, in the clear |
| 2 + n | | The table, ZX0-compressed, then encrypted under `TAP1` with the stream index as index. Not empty |

Every tape target is in exactly one `TAP1`, and a `TAP1` names only tape targets, each once: anything else is damage. Releases of one game, such as its `.tap` and its `.tzx`, share a `TAP1` when one table makes the same banks from each, which a writer checks by rebuilding; otherwise each has its own, under the next stream index.

**The table**, at most 24,576 bytes once decompressed, the most a loader holds at once, as for `SIT1`:

| Size | Field |
|---|---|
| 55 | The start state: a `.z80` version 2 header. Bytes 6 and 7 are 0, bytes 30 and 31 are 23, and byte 34, the hardware mode, is 0 for a 48K game or 3 for a 128K one |
| 4 | The CRC-32 of the snapshot the clash fix off writes from it, without POKEs: see below |
| 2 | The number of copies |
| 10 each | A copy: 2 bytes data block, 3 bytes offset in that block's bytes, 2 bytes length (1 to 16,384), 1 byte bank, 2 bytes offset in the bank |
| 2 | The number of sites |
| each | A site: 1 byte bank, 2 bytes offset, 2 bytes length (at least 1), then that many bytes |

and nothing after them. The header holds the start's registers, IFF1 and IFF2, interrupt mode, border, 7FFD, the last register selected on port 0xFFFD and the 16 AY registers (bytes 38 to 54), where a `.z80` file has them. Bytes a build does not use still count in the CRC.

A reader refuses as damage: a table that is not exactly those fields; a header breaking its rules; a copy naming a data block past the tape's, or past the first 1,024, or whose offset plus length passes that block's end; a copy or site whose bank is 112 or above, whose length is out of range, or whose offset plus length passes 16,384; and copies, or sites, out of order. Each of the two lists goes through banks in `.nex` order, and within a bank by rising offset, with no two of one list overlapping. A copy and a site may overlap, and then the site wins.

**The banks.** The machine's banks (0 to 7 for 128K; 5, 2 and 0 for 48K), and any other bank a copy or site names, start as 16,384 zeros. The copies are made, in order, then the sites. The machine's banks are then the game's memory at the start; another bank is an **extra bank**. Building the `.nex`, an extra bank its header does not list is damage, since it would never be used and readers could differ over whether it matters; the clash fix off uses only the machine's banks, and does not read the header. A reader works out the CRC below before it uses a bank, and refuses a mismatch as damage.

**What it holds of the game.** The copies say where things go, and the bytes come from the player's tape. The sites hold what is not on the tape: the screen as drawn, variables, the stack, and tables the game's code made when it ran, which are derived from the game. **A writer takes from the tape every run of 16 bytes or more of the start that the tape holds, wherever it holds it, and carries only the rest.** So a table holds none of the tape's code or data as it is, and no more than the 24,576 bytes a snapshot patch's `SIT1` may. `tools/nxc.py` also refuses more than 8,192 bytes of sites unless told otherwise: a start state the tape does not hold is a sign of a packed or encrypted tape, whose unpacked form is the game, and a plain copy recipe is not for those.

**Where the build starts** is the writer's choice, usually a `.z80` taken in an emulator from that tape, and the build is made from that `.z80`. The fewer of its bytes that are not on the tape, the better. For The New Zealand Story in JNext (128K), with this format's writer: at the jump into the main code, 5,151 bytes in 312 sites; at "LEVEL 1-1 READY", after the first world loads and before play, 3,813 bytes in 101 sites, with 68,367 bytes in 125 copies; in play, 6,536.

**Multiload.** A build that keeps a multiload's blocks in memory names extra banks for them. Copies place those blocks, or parts of them, wherever in those banks the build wants them; a writer takes them from the tape alone, and carries anything else the build has in such a bank in `SIT1`, as a change of its own. Hooking the game's loader to read the blocks from there is the engine's work, done in its own banks and sites: this format only places them. `OPT1` byte 2 counts them, as the `.nex` lists them.

**Clash fix off.** A tape is never handed over as it is. The plain game is the start as a `.z80`: the table's header, then the machine's banks as whole pages, each 0xFFFF, its page number, then 16,384 bytes, pages 3 to 10 for 128K and 8, 4, 5 for 48K. It is written only after the keyed check, with or without a trainer. Its CRC-32 without POKEs must equal the table's; the POKEs then go in, and each must be in one of the machine's banks.

## The keys and streams

Every patch has a fresh random 16-byte master key and a fresh random 16-byte nonce. This block is the definition, and `tests/test_vectors.py` runs it as written against the vectors in `tests/vectors/`:

```python
def new_state():
    return [list(range(256)), 0, 0]                # the table s, then i and j

def absorb(state, data):
    s, i, j = state
    for b in data:
        i = (i + 1) & 255
        j = (j + s[i] + b) & 255
        s[i], s[j] = s[j], s[i]
    state[1], state[2] = i, j

def output(state, count):
    s, i, j = state
    out = bytearray()
    for _ in range(count):
        i = (i + 1) & 255
        j = (j + s[i]) & 255
        s[i], s[j] = s[j], s[i]
        out.append(s[(s[i] + s[j]) & 255])
    state[1], state[2] = i, j
    return bytes(out)

def dump_base(nonce, game_file):
    "The base for one dump: the whole file, once, between the nonce twice."
    state = new_state()
    absorb(state, nonce + game_file + nonce)
    return state

def key_base(nonce, master_key):
    "The base for everything else. 16 rounds, as one pass of 48 bytes barely mixes the table."
    state = new_state()
    for _ in range(16):
        absorb(state, nonce + master_key + nonce)
    return state

def use(base, tag, index):
    "A copy of a base with this use's tag and index absorbed. A base is never used directly."
    state = [list(base[0]), base[1], base[2]]
    absorb(state, tag + bytes((index,)))
    return state

def stream(base, tag, index):
    "A use, ready to encrypt: its first 256 output bytes dropped."
    state = use(base, tag, index)
    output(state, 256)
    return state

def check_value(patch_file, master_base):
    "The whole file but the check field, under its own use."
    state = use(master_base, b"CHK1", 0)
    absorb(state, patch_file[:22])
    absorb(state, patch_file[38:])
    output(state, 256)
    return output(state, 16)
```

No two uses share a stream. Each tag has one purpose, and within a tag the index is unique:

| Base | Tag | Index | Used for |
|---|---|---|---|
| dump | `TGT1` | The entry's index | The key wrap |
| master | `CHK1` | 0 | The check value. It is never a block's tag |
| master | `OUT1`, `NEX1`, `SIT1` | 0 | Those blocks |
| master | `BNK1` | The bank number | That bank |
| master | `SCR1` | The piece's index | That piece |
| master | `TAP1` | The block's stream index | That tape table |
| master | `SEB` then the set's stream index, as one byte | 255 | That set's CRC |
| master | `SEB` then the set's stream index, as one byte | The bank | That set's chunk for that bank |

`TGT1` is never used under the master base nor anything else under a dump's, and these tags are fixed, so a writer needs no other rule. A new encrypted block needs a new tag, and with it its own streams. Changing a clear block keeps the nonce, the key and the streams, as the plaintext of every encrypted block is unchanged. Changing what an encrypted block holds means a new nonce and key.

The key wrap is 8 known bytes, then the key. So a wrong file passes with odds of 1 in 2^64, and the known bytes give away 8 bytes of a stream after 256 were dropped. A stream's bytes say little about its state, and nothing about the other streams; the same goes for `NEX1`, whose plaintext starts in a way that can be guessed.

The nonce is in the clear, and a game's file is public to whoever has it, so `dump_base` keeps nothing from an owner.

## The keyed check

The 16 bytes at offset 22 are `check_value` of the file. A reader computes it after it has the master key, over every byte of the file but those 16, and compares. A difference is damage. **This comes before any decompression**, because Z80 ZX0 decompressors have no bounds checks and a damaged stream could overwrite memory.

Forging it needs the master key, which needs the game. Someone owning the game can recompute it. So a reader must still bounds-check everything as this document says.

## Snapshots

A reader normalises a game file to its banks, so that dumps differ only in form.

**`.z80`.** Bytes 6 and 7 are PC. PC not 0 is version 1: 48K, one stream from offset 30, packed if bit 5 of byte 12 is set (255 in byte 12 means 1), ending at the marker `00 ED ED 00` if packed, and that stream holds banks 5, 2, 0 in that order. PC 0 means the 2 bytes at offset 30 are an extended header's length: 23 is version 2, anything else version 3 (`firmware/nexclash.asm` takes 3 to 128). The hardware mode is the extended header's third byte: 128K if it is 3 or 4 in version 2; 4, 5, 6, 7, 9, 12 or 13 in version 3; otherwise 48K. Then pages follow to the end of the file, each 2 bytes length, 1 byte page number, then its data: a length of 0xFFFF means 16,384 bytes stored whole, anything else that many packed bytes which must unpack to exactly 16,384. On a 128K game page 3 to 10 is bank 0 to 7; on a 48K game page 8 is bank 5, 4 is 2 and 5 is 0; other pages are ignored. Banks 5, 2, 0 must all be there on a 48K game, and banks 0 to 7 on a 128K one.

Packing: `ED ED n v` is `n` copies of `v`, and `n` may be 0. An `ED` with fewer than three bytes left in the stream or page is itself, as is an `ED` not followed by `ED`.

**`.sna`.** 27 bytes of registers, then bank 5, bank 2, and the bank paged at 0xC000. 49,179 bytes is a 48K file, whose third bank is bank 0. Otherwise it is a 128K file of 131,103 or 147,487 bytes: after the third bank come 2 bytes of PC, 1 byte 7FFD, whose low 3 bits say which bank was third, 1 byte for TR-DOS, then the banks other than 5, 2 and the third, in rising order. A paged bank 5 or 2 is in the file twice, which gives the longer length. A `.sna` holds what a `.z80` holds of memory, and registers elsewhere.

## Tapes

A tape target's bytes are named by **data block**, counted from 0 in the order the file stores them, and by offset in that block's bytes as stored. On a standard ROM block the flag byte is offset 0 and the checksum byte the last.

**`.tap`.** Blocks, each 2 bytes of length then that many bytes, to the end of the file. Every block is a data block, one of length 0 included. A length that runs past the end is damage.

**`.tzx`.** `ZXTape!`, 0x1A, a major version of 1 and any minor version, then blocks to the end of the file, each an ID byte and its body. Data blocks, whatever their timings, pauses and used bits:

| ID | Block | Its bytes start at | Their length |
|---|---|---|---|
| 0x10 | Standard speed data | body + 4 | 2 bytes at body + 2 |
| 0x11 | Turbo speed data | body + 18 | 3 bytes at body + 15 |
| 0x14 | Pure data | body + 10 | 3 bytes at body + 7 |

These are skipped, and get no number. Each is sized as TZX 1.20 sizes it, as a head of fixed length and, after it, the count it holds times a unit:

| ID | Head | Count, from the body's start | Unit |
|---|---|---|---|
| 0x12 pure tone | 4 | none | |
| 0x13 pulse sequence | 1 | 1 byte at 0 | 2 |
| 0x15 direct recording | 8 | 3 bytes at 5 | 1 |
| 0x18 CSW recording, 0x19 generalised data, 0x2A stop the tape if 48K, 0x2B set signal level | 4 | 4 bytes at 0 | 1 |
| 0x20 pause, 0x23 jump, 0x24 loop start | 2 | none | |
| 0x21 group start, 0x30 text | 1 | 1 byte at 0 | 1 |
| 0x22 group end, 0x25 loop end, 0x27 return | 0 | none | |
| 0x26 call sequence | 2 | 2 bytes at 0 | 2 |
| 0x28 select, 0x32 archive info | 2 | 2 bytes at 0 | 1 |
| 0x31 message | 2 | 1 byte at 1 | 1 |
| 0x33 hardware type | 1 | 1 byte at 0 | 3 |
| 0x35 custom information | 20 | 4 bytes at 16 | 1 |
| 0x5A glue | 9 | none | |

Any other ID, the deprecated 0x16, 0x17, 0x34 and 0x40 among them, and a block that runs past the end, make a file that cannot be a tape target: a writer refuses it, and a reader treats it as damage. Jumps, loops and calls change nothing here, since the numbering is the file's order, not the order a deck plays it. Direct recordings, CSW and generalised data hold a signal, not bytes, so nothing can be copied from them in this version, and a game held only in them cannot be a tape target.

A reader walks a tape from its start until it has found the highest data block its table names, refusing on the way what this section refuses, and reads nothing after that block. A writer checks the whole file.

## Applying a patch, in this order

Nothing is decompressed before step 5, and nothing is written before step 6. A set's chunks are decoded in both, one at a time for each set.

1. Open the patch, and refuse it if its name is one of the outputs: see below. Read the header. Refuse it as "not a patch" as above.
2. Walk every block, once, up to the end of the file. Refuse anything that does not fit. Refuse a second required block at once. For `OPT1`: its length, level and flags. For each `TGT1`: its shape, index and `file`. For each `TRN1`: its shape, flags and every POKE. For each `SET2`: its name fitting, its stream index unique. For each `TAP1`: its head, its stream index unique. Take `INF1`'s text. At the end: every required block there; at least one target this reader can read, or say a newer loader is needed; a `SCR1` only with level 2 or above; every tape target in exactly one `TAP1`, and nothing else in any; with only tape targets, `OPT1`'s bit 0 set.
3. Find the game: the first file that exists, in this order, whose length equals that of a target this reader can read, tapes included: each target's `file` beside the patch, then the patch's own name with `.z80`. One that is not there is passed over. One that is there under an output's name is refused. One of no listed length is noted and passed over. None found: say which file is needed, and that the one there is wrong if one was noted. Show the menu.
4. Clash fix on, or off with a trainer on: absorb the file once, as `dump_base`. Take the targets of that length, from a copy of that state each, until a wrap's first 8 bytes are right: that is the master key. The file is never read again for another entry. None right: go on to the next file from step 3, or refuse as the wrong file. Build `key_base`, and check the value at offset 22. Refuse as damage if it differs. Decrypt `OUT1`.
5. Clash fix on: walk the `BNK1` blocks and index them, refusing bad lengths and repeats. Decrypt and decode `NEX1`, and read the game's pages. For a tape, decrypt and decode its `TAP1`, check the whole table against the tape's data blocks, build the banks it makes, check its CRC, and refuse an extra bank the header does not list. Decode `SIT1` and check the whole of it. Refuse a listed bank with no source, or a `BNK1` for a bank not listed. Size any screen from byte 10 and check all its `SCR1` headers. For each set chosen, decrypt its CRC. Then go through the listed banks in `.nex` order, decoding and checking the chunk each set has for that bank, and with two, refusing any bit set in both bitmaps. A chunk not reached that way is refused. Work out what the output's CRC-32 must be, from `OUT1` and theirs. Check the chosen POKEs' banks exist.
6. Create the output. Write the `.nex`: the header; any screen, a piece at a time; then each bank the header lists, in `.nex` order (5, 2, 0, 1, 3, 4, 6, 7, then upward), from `BNK1` if present, otherwise from the game with `SIT1` applied. Fill short banks with zeros. Decode each chosen set's chunk for that bank again, check it again, apply it, run the CRC over it, then apply the trainers' POKEs, then write it.
7. Check the CRC-32 against the value from step 5, and the length against `OUT1`. If either differs, delete the file and report damage.
8. Start the `.nex` with NextZXOS's own loader.

**Outputs and inputs.** The loader writes to fixed names, `/tmp/NEXCLASH.NEX` and `/tmp/NEXCLASH.Z80`, on the system drive, whichever the choice. It must not be reading one of those: making the output would truncate its own input. Before it reads a patch or a game, it asks NextZXOS for the file's folder (`F_GETCWD` with A=0xFF), which gives one form, such as `C:/TMP/`, for `/tmp/x`, `c:\tmp\x`, `tmp/x` from the root, `x` from `/tmp` and any path through `..`; and compares the folder, then the name after the last `/`, `\` or `:`, without regard to case, and ignoring dots and spaces at the name's end, which FAT drops. Either output name in that folder is refused for a patch or a game, whichever route is chosen. A folder NextZXOS will not resolve is refused too. It only ever deletes an output it has created. Being in `/tmp` under another name, or under that name on another drive, is fine.

**The clash fix off with a trainer on** writes the game as a `.z80` of whole pages with the POKEs in place, under the game's own header (version 1 becomes version 2), after the checks of step 4. With no trainer it is the game file itself, found as in step 3, with no further check at all, as `nxc.py --original` is. `tools/nxc.py` writes the same for a `.z80`, and for a `.sna` keeps its layout, with the POKEs in place in each copy of a bank. **A tape**, trainer or not, is checked as in steps 4 and 5 and written as its start, as `TAP1` says.

## The menu

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
- **One line for each kind of set offered,** after the clash fix: `Enhanced colours`, then `Language`. Its key steps from `[OFF]` through the kind's sets, in the file's order, and back. Only sets with the sprite build as their base are offered. With one colour set the line is `[ON]` or `[OFF]`, not its name. Otherwise it shows the name, cut to 17 characters, ending in the last column. A loader with no room to step may offer the first alone and must say so in its documentation: this one has room. With the fix off each line reads `[N/A]`, its key does nothing and no set is applied, and the choice is back when the fix is turned on.
- **The credit line.** `Patch: <patch_by>     Colours: <colours_by>`, under the rest, showing only the parts present, the colours only for a patch with a colour set, and no line if neither. It starts in the first column and fits 41. A name is cut to 32 characters, and with both the gap of 5 closes to 2 before a name is cut: the first then keeps at least 11 characters and the second what is left. So `Patch: Jon Attree     Colours: Alberto Conde`, at 44 columns, shows with a gap of 2. Anything unprintable shows as `?`. Dean's credit is not on this line; it stays in usage and documentation.
- Lines are numbered from 1 and the keys match, so the tenth line is on key 0. Ten lines are all there are keys for: 8 trainers with the fix and one kind, or 7 trainers with the fix and two.
- ENTER and SPACE both start with what the menu shows. BREAK cancels.

The set a patch makes its NexClash look is its base build.

The loader is the dot command `firmware/nexclash.asm`. It writes to `/tmp` and leaves `%x` as 1 for a `.nex` or 2 for a `.z80`, and a line in `browser.cfg` with a small merged program starts the result: see `firmware/README.md`, which also gives what was tried and what is assumed. Both have run in JNext on real NextZXOS, not on a Next.

## Test vectors

`tests/vectors/` holds a whole patch, the game files it accepts and the intermediate states, all made from synthetic bytes by `tests/vectors/make_vectors.py`; and a tape patch, its `.tap`, its `.tzx`, the `.z80` it starts from and its table, made by `tests/vectors/make_tape_vectors.py`. Nothing there comes from any real game.

## Limits of version 1

- **Listed files only.** One byte different from every listed dump is refused. Accepting another dump means adding an entry for it, with its bytes in hand.
- **Snapshots, and plain tapes.** `.z80`, `.sna` for tools, and `.tap` and `.tzx` whose game is in data blocks as it runs. A tape that decrypts or unpacks its game as it loads has no start a copy table can make from it, and is refused by the 8,192-byte rule. Other snapshot formats, `.szx` among them, are not targets.
- **Rebuilding is not proof of playing.** An exact rebuild shows the file is identical to the original build. It says nothing that the build's own testing did not.
- **Multi-load games** are the engine's to hook. `TAP1` can place every block of a tape in memory for a build, and that is all it does.

## Open questions

- Whether all of this holds on a Next. On emulated T-states at 28 MHz with no wait states and no file I/O, Cobra (42,218-byte game, 98,816-byte `.nex`) takes 1.24 s, and the largest of 52 builds (492,032 bytes) 4.10 s. In JNext, with its emulated card, a 98,816-byte build takes about 2.2 s from Enter to the finished file.
- Whether Dean is happy with this packaging of his engines' output.
- Whether to prefer clean originals over dumps such as `[t]` trained ones when rebuilding patches.

## How this relates to `.256`

Same conventions: tagged blocks of three letters and a version digit, skipping what a loader does not know, a level in OPT1, and a rule that extras are never required to play. Different purpose: a `.256` holds the whole game with colour planes at fixed offsets, whereas a patch holds only changes.

| `.256` block | Here |
|---|---|
| Registers, 7FFD, memory banks, AYS1 | Not needed: from the player's snapshot; changes in `SIT1`, `BNK1` |
| CFG, RUL1 | No equivalent: hooks do this |
| GRX1 | No direct equivalent; ROM needs go in `ROM1` |
| Backgrounds, BGX1, BGX2 | `L2B1` later |
| CRD1 | `INF1` |
| OPT1 | `OPT1` |

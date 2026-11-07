# The .nxc file format, version 1 (draft)

By Jon Attree. Built with NexClash by Dean Woodyatt (Bleugh.biz, bleughb/nexclash, GPL-3.0-or-later).

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
| `HLP1` | no, once | no | Help for the menu's lines |
| `OPR1` | no, once | no | Which options go together, with no limit of two at once |
| `SET3` | no, zero or more, all of one kind | yes, after its name, its banks, its table's indices and the heads of its chunks | A choice that needs more memory than the base: banks of its own, and the most memory the game needs with it |

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
| `SPL1` | Where a build's sprite images lie, for a tool that exports and imports them, with rules below |

Also reserved: `SET2` kind 5, a game speed, with rules below. It is a kind of an existing block, not a block of its own.

Custom loaders are not part of this standard. A game that needs one is out of scope, and a per-game adapter belongs in the engine that made the build.

### OPT1

Exactly 3 bytes. Byte 0: the loader level this patch needs. Byte 1: flags, each something the patch needs besides its level. A reader that does not have the level, or sees a flag set for something it cannot do, stops and says it needs a newer loader. Byte 2: the highest 16K bank the rebuilt game needs, 0 to 111. Any other length or value is damage.

| Flag | Means the patch needs a loader that can | A patch must set it when |
|---|---|---|
| Bit 0 | Read tape targets, with `TAP1` | It has no snapshot target (`.z80` or `.sna`) at all |
| Bit 1 | Read targets of several tape files, below | Every target it has is a set of files |
| Bit 2 | Keep to `OPR1`'s rules | A reader without `OPR1`, holding two at once, could make a combination its rules forbid that it would not refuse: see "OPR1" |
| Bits 3 to 7 | Reserved, 0 | |

A patch with only tape targets that does not set bit 0 is damage, and so is one whose targets are all sets of files that does not set bit 1. A patch that also accepts the game in one file leaves bit 1 clear, since a loader without sets can use that entry. Tapes are a flag and not a level because levels are a ladder, each including those below, and a loader that reads tapes need not read `.sna` or write snapshots. A loader older than this flag sees it set and refuses, as it should; one that skipped it would find no target it could read, and say the same.

| Level | Means the loader can | A patch must say it when |
|---|---|---|
| 1 | Read `.z80` targets, and everything in this document but `SCR1` | Always at least this |
| 2 | Also write a loading screen from `SCR1` | It holds a `SCR1` |
| 3 | Also read `.sna` targets | It has a snapshot target, but no `.z80` one |
| 4 | Reserved: snapshot output, below | It has no sprite build at all. Nothing here writes or reads it |

A loader that is shown a patch of its level or below can do all of it. `SCR1` makes a level necessary rather than optional because a loader that skipped it would write a wrong `.nex`: a patch with a `SCR1` that says level 1 is damage. A `.sna` target in a patch that also has a `.z80` target does not raise the level, as a level 1 or 2 loader skips the entry and uses the others. The level is worked out from the snapshot targets alone, so a patch with only tapes is level 1, or 2 with a `SCR1`, and sets bit 0; a tape in a patch that has a snapshot target too raises nothing, as a loader that cannot read tapes skips the entry.

`tools/nxc.py` is level 3 and reads tapes, sets of them included, and keeps to `OPR1`. `firmware/nexclash.asm` is level 2 and reads tapes, sets of them included, and keeps to `OPR1`. Both refuse level 4. `SET2` raises no level: it is an extra, so a loader that does not know it skips it and offers no such line, and the game still plays.

**Memory.** Byte 2 lets a loader on a smaller machine refuse rather than start a game that breaks. A writer works it out from the `.nex`: the highest bank the header lists, or 48 if the header's byte 8 asks for 1792K, whichever is higher. That is all the file shows: a build may use banks at run time that it does not load, such as Layer 2 buffers, so an author may raise it, and nothing can lower it. A reader refuses a value below a bank the header lists.

This is the base build's need. A choice that needs more, such as a colour set whose pictures fill a 2MB Next, is a `SET3` and says its own need: a loader offers it only on a machine that has it, and the base still fits the smaller one. See "SET3".

A loader that can find out how much there is compares `2 x (byte 2 + 1)`, or with a `SET3` chosen `2 x` (its need `+ 1`), with the 8K banks of ZX memory, and if there are too few, refuses the rebuilt game, saying so. A 1MB Next has banks 0 to 47, and a 2MB Next banks 0 to 111. `firmware/nexclash.asm` asks NextZXOS, with `IDE_BANK` and reason `rc_bank_total` through `M_P3DOS`, when ENTER is pressed with the clash fix on. If NextZXOS will not say, it goes on. The clash fix off is the player's own game, and is not checked. `.nexload` does not check its header's byte 8 itself, as its source on the card shows.

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
| 30 | | Text, or for a set of files the fields below, then text |

A reader skips an entry of a kind it does not know, or cannot read, for finding the game, but still checks its index and name. Text keys:

- `file`: required, and within the first 252 bytes of the text. The name a player has it under. See below.
- `md5`: required of a writer, 32 lower-case hexadecimal digits of the whole file. It is there to tell a person which file is wanted, and lets a reader on a PC find the file under another name (step 3 of "Applying a patch"). It unlocks nothing, so a reader may use instead the key wrap, which only that file passes.
- `title`: optional. A loader's menu shows the first one in the file.
- `zxdb_entry`: optional. Absent if ZXDB does not list the file.

**A set of files.** A release whose game is on several tapes, such as a side A and a side B, is one entry naming every file. Its kind has bit 7 set over the first file's kind (0x83 or 0x84); offset 2 is the first file's length, as for any entry, so a reader finds a set's first file as it finds a single one. Then, after the key wrap:

| Offset | Size | Field |
|---|---|---|
| 30 | 1 | n, the number of files, 2 to 8 |
| 31 | 5 each | For files 2 to n in order: kind (3 `.tap` or 4 `.tzx`), then the length, 4 bytes |
| 31 + 5(n - 1) | | Text |

Only tapes make sets: a first or later kind other than 3 or 4, or n out of range, is damage. The text names them all: `file` the first, `file_2` to `file_n` the others, each with the same rules as `file`, and each required within the first 252 bytes, or the entry is damage; and a writer adds `md5_2` to `md5_n` beside `md5`. No name appears twice in one entry, whatever the case. **The key wrap of a set is keyed over all of its files in order**: `dump_base(nonce, file_1 + file_2 + ... + file_n)`, the files' bytes one after another. Several releases may still be accepted, each an entry of its own with its whole set; a set and a single file may be entries of one patch, and two sets may share a file, which then has the same name, length and MD5 in each. A writer refuses a set and a single file whose first files have the same length, and two sets whose first files have the same length unless they name the same further files with the same lengths: so a loader knows from the first file's length alone whether the game is a set, and which further files to look for. A loader that does not read sets skips such an entry as a kind it does not know. Data blocks are numbered within each file, from 0, and `TAP1` names a file by its place in the set: see "TAP1".

**`file` is a bare name, never a path.** 1 to 127 bytes of printable ASCII, with none of `/ \ : * ? " < > |`, no `..` anywhere, no space first, no space or dot last. Anything else makes the whole patch damage, whichever kind the entry is, so that a wrong name can never open another path. A loader puts it after the patch's own folder: if that does not fit, it refuses, and never cuts a name short. `firmware/nexclash.asm` holds 223 bytes of path.

A writer refuses two entries with the same MD5 (for sets, the same MD5s in the same order), or the same `file` whatever the case (a name used in two sets must name the same file in both), so that a loader does not open one file twice for two entries; and two entries of different kinds with the same length, so that a loader can tell from the length alone which kind a file is. A reader need not check this.

Every entry in a patch must rebuild the same banks. A writer checks that, by rebuilding, before it writes anything: only the banks matter, since the `.nex` carries its own start-up state, so dumps with different registers but the same memory are the same to it. With the clash fix off each player gets their own file, so its registers are theirs. A tape's banks are those its `TAP1` makes, which include any extra banks, so a tape that places a multiload's blocks and a snapshot cannot be entries of one patch.

### INF1

Keys: `publisher` (for the menu, such as `Ocean, 1986`; a loader may show the first 16 characters), `patch_by` and `colours_by` (optional, for the menu's credit line), `build`, `nex_md5`, `nexclash`, `credit`, and for languages, all optional and not needed to play: `game_language`, the ISO 639 code of the language the game itself is in; `language_codes`, each language set's code as `Name=code`, comma-separated, such as `Espanol=es`; and `text_by`, who translated it, kept here and not on the menu. A writer always includes `credit`, and a patch from NexClash carries "Built with NexClash by Dean Woodyatt (Bleugh.biz, bleughb/nexclash, GPL-3.0-or-later)", which `nxc.py make` writes. Anything derived from its GPL-3.0-or-later code keeps those terms as well. `credit` lives here and in the project's documentation, including who painted a colour set: a loader need not show it on its menu or play screens. `nxc.py credit PATCH GAME -o OUT --patch-by NAME --colours-by NAME` sets the two menu names, right after `publisher`, and refuses if they would end past the first 252 bytes.

**`version`**, optional: the patch's own version, for the menu's `Patch:` row, such as `1.0`, so that a player can tell one release of a patch from the next. It is 1 to 8 printable ASCII characters with no spaces and without a leading `v` or `V`, as a reader shows it after a `v` of its own. A writer refuses anything else, or one that would end past the first 252 bytes, and writes it after the menu's other keys (`publisher`, `patch_by`, `colours_by`, `fix_label`). A reader that finds it longer shows the first 8, with anything unprintable as `?`. **Absent, empty or cut off at 252 bytes, the menu shows no version** and is the menu it always was, as it is from a reader that does not know the key. It says nothing about what the patch does or needs: a reader never refuses a patch by it. `nxc.py version PATCH GAME VERSION -o OUT` sets it (`''` removes it), keeping the nonce and key as `credit` does and needing the game, and `nxc.py make --patch-version VERSION` sets it when a patch is made; listing a patch shows it.

**`fix_label`**, optional: the menu's name for its main line, the rebuilt NexClash game on or off, for a game where "Colour clash fix" is the wrong words, such as `Colour` for a game that never had clash. It is 1 to 25 printable ASCII characters, as a toggle's name is, so `[ON]` keeps its column. A writer refuses a longer one, or one that would end past the first 252 bytes, and writes it after `publisher`, `patch_by` and `colours_by`. A reader that finds it longer shows the first 25, with anything unprintable as `?`. **Absent, the line reads `Colour clash fix`**: a patch without the key, or with it cut off at 252 bytes, shows the menu it always did, and a reader that does not know the key shows that too. It names the line and nothing else: what the line does, its `[ON]` and `[OFF]`, and the `[N/A]` of the lines after it with it off, are the clash fix's. `nxc.py make --fix-label TEXT` sets it.

**Notes for the `.nfo`**, all optional: what a person reads about the patch, beside it. A loader never shows them, and no reader needs them to play, so they raise no level and set no flag. Each is one line of 1 to 1,024 printable ASCII characters, and a writer puts them after every key a loader reads, so that they never push a menu key past the first 252 bytes:

| Key | Holds |
|---|---|
| `notes` | What a player should know that the rest does not say: choices the owner made, such as no outlines, and faults that are the original game's own |
| `enhanced_N` | What colour set N looks like, from frames viewed, N being the set's choice ID in decimal (as for `PRF1`'s `toggle_N`), so that it stays with the set when the patch is remade. A key for a choice no colour set has is skipped |
| `changes` | What changed in each version of the patch: entries of the version (as `version` holds it), `: ` and what changed, in the order written, separated by ` \| `, such as `1.1: writes the whole alt ROM image` |
| `tested` | Who played it, where and when: one sentence, such as `Played by Jon Attree in JNext through the real loader, 2026-11-04` |

A reader that does not know a key skips it, as always, so a patch with them is the same patch to a loader: the same description, menu and output, byte for byte. `trainers_played`, also optional and also not shown on the menu, records how each trainer was tried. `cheats_source`, optional and not shown on the menu, says where the trainers come from, for the `.nfo`; without it the `.nfo` says they are the archive's POKEs for the release. `credit`, `build`, `nex_md5` (32 lower-case hexadecimal digits) and `nexclash` are as above.

**`nxc.py set PATCH GAME FIELD VALUE -o OUT`** sets any one field of `INF1` or of `PRF1` (below), or removes it with `''`, keeping the nonce and key as `credit` and `version` do and needing the game. It refuses a field it does not know, and checks each as this document says: a menu key (`publisher`, `patch_by`, `colours_by`, `fix_label`, `version`) goes among the menu's lines, in that order, and is refused if they would then end past the first 252 bytes; `fix_label` and `version` keep their own limits; `credit` cannot be removed; `enhanced` alone means `enhanced_N` of a patch's one colour set, and `enhanced_N` must name a colour set the patch offers; `changes` must be entries, each version a valid one. Any other field goes after the menu's lines, in place if it is there, otherwise last. Every block but the one changed is as it was.

`tools/make_nfo.py PATCH.nxc` writes the `.nfo` beside it from these fields and the patch's other clear blocks alone, without the game: the files it needs and their MD5s, what it does, each colour set's look, its pace, its changes and notes, its menu, its credits and its proofs.

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

**Pace**, optional: how fast the rebuilt game plays against the original, in fields a reader can show the same way for every patch.

| Key | States |
|---|---|
| `pace` | What the build aims for, one of three words: `ORIGINAL`, the original game's pace, the patch's own work hidden; `SLOWDOWN REMOVED`, the original's pace with the slowdown of its busy scenes taken out, which is a change to how it plays; `TURBO`, faster than the original, on purpose |
| `pace_measured` | The penalty measured against the original, per scene: entries of the scene, `: ` and a signed percentage of the original's time (`+` slower, `-` faster), separated by `; `, the first being the headline, such as `the walk through rooms 0, 2, 3 and 16: +0.15%; room 2: +0.9%` |
| `pace_where` | Where it was measured: the emulator and its version, or the machine |
| `pace_when` | When |

Absent, nothing is said of pace, and a reader shows nothing. A `pace` that is not one of the three words is refused by a writer and shown as nothing by a reader. `tools/make_nfo.py` shows one line, the word in lower case, then the headline figure and where: `Pace: original (+0.15% measured in JNext 1.1.104)`. `nxc.py set` sets each, checking the word and the entries. Like everything in `PRF1`, it describes the base build, with nothing chosen.

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
| 1 | 1 | Kind: 1 colours, 2 language, 3 a toggle that changes only what is shown or heard, 4 a toggle that changes the game's logic, 5 a game speed (reserved: see "Reserved: game speed"). Others are reserved |
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

**One choice per kind.** Alternatives within a kind may overlap, as they can never be chosen together. Sets of different kinds **must not overlap**: a writer refuses any pair that could be chosen together (with `OPR1`, any pair its rules let be on together), and a loader refuses the actual selection, by comparing the bitmaps of the two chunks of each bank, before it makes any file. That holds even for two sets writing the same bytes to the same place. Kinds say what the menu offers, not what works together: two sets that do not overlap can still disagree about pointers or fonts, and nothing here shows that a combination plays.

**The check.** With the file's length and layout the same, and the replacements disjoint, CRC-32 being affine for equal lengths gives one value per set instead of one per combination:

```text
CRC(combination) = CRC(base) XOR (CRC(set 1) XOR CRC(base)) XOR (CRC(set 2) XOR CRC(base)) ...
```

where `CRC(base)` is in `OUT1` and `CRC(set n)` in each block. A loader runs one CRC-32 over the real output, with sets applied and before any POKEs, and compares it and the length with those. With no set chosen that is `OUT1` itself. If they differ, the file is deleted. That checks the reconstruction, as a CRC over a table could not. It is checked as the file is written, not read back from the card.

A reader that does not know a kind or a base checks the block's shape and index, and does not offer it. A set is decoded only when it is chosen, so a damaged stream in a set that is not chosen, in a file whose check value is good, does not stop the game.

**Memory.** A loader needs one bitmap and its bytes for one set, for one bank at a time, as well as `SIT1`, and the bits the sets chosen before it took in that bank, 2,048 bytes: `firmware/nexclash.asm` keeps three 8K pages for the sets, however many are chosen, so 72K with any, 96K for a tape with any, the same whatever their size, and says so if it cannot get them. For each bank it decodes the chunk of each chosen set in turn into those pages (a chunk ends by 18,432 bytes, so the last 2,048 bytes of the third page hold the bits taken so far), checks it against those bits, adds its own, and applies it, before the next. Until 2026-11-06 it kept three pages for each set chosen, two at most, 96K, and so held two at once. A 1MB Next has 96 8K pages of ZX memory, so this is well within it. What a build needs to run is separate, and is in `OPT1`.

**A set can change how a game starts.** It cannot change the header, but it can change any byte of any listed bank, and those banks hold the start-up code and hooks. An unchanged header says nothing about that. A set from a stranger is code, as the rest of a patch is.

### Toggles: SET2 kinds 3 and 4

A **toggle** is a set of its own kind, on its own menu line, for a bug fix or an extra such as smooth scrolling. It is a `SET2` block exactly as above (stream index, choice, base, name, CRC, chunks), with kind 3 or 4:

- **Kind 3, display only.** It changes what the player sees or hears, never the game's logic: the game's memory and registers, outside what the toggle's own code keeps, are as without it. Its proof says so by replay: `PRF1`'s `replay` states the game logic was IDENTICAL with it on, and how its own layer was checked.
- **Kind 4, changes the logic**, as a bug fix does. It cannot be proven identical to the original, and is not. Its proof states what it changes and how that was checked instead: `PRF1` key `toggle_<choice>` (the toggle's choice ID in decimal), one line saying what the toggle does, what was replayed or tested with it on, and against what. A writer refuses a kind 4 toggle without that line. The menu does not show the difference: the name says what it is.

**What a toggle may change.** Bytes, code or data, in banks the base build already lists, as any set; the base build reserves the room (a toggle's hook code lives in pages the base already has, and its chunks fill them). It cannot add a bank, change the header, or change the length of the output.

**Choice and name.** Each toggle is one choice: its choice ID is unique among the toggles of its kind and stays the same when a patch is remade. Its name, 1 to 25 characters, is its menu line. A writer keeps names unique among all toggles.

**Together.** Without `OPR1`, any toggles may be on together, and with one colour set, one language and any trainers. So a writer refuses a patch where any two toggles, or a toggle and any set of another kind, or a toggle and any trainer's POKE, could write the same byte, even the same value; and a reader that finds such an overlap among what is chosen, comparing the chunks' bitmaps as for two sets and each chosen POKE against them, refuses the patch as damaged before it makes any file. Several toggles combine in the CRC as several sets do: one term each. With `OPR1`, the same holds for every pair its rules let be on together, and only for those: two options the rules keep apart may change the same bytes.

**Limits.** A patch has at most 4 toggles of the sprite build. A reader that finds a fifth offers the first 4 and ignores the rest, as a writer never makes one.

**Compatibility.** A reader that does not know kinds 3 and 4 checks the block's shape and index as for any `SET2`, offers no line, and the game plays without it. So toggles raise no level and set no flag in `OPT1`. Patches and vectors made before toggles are unchanged byte for byte.

**Memory, and a reader's limit.** A chosen toggle is held as a chosen set is: one chunk at a time, in the same pages. A reader may hold fewer chosen sets and toggles at once than a patch offers, and states its limit N: its menu then lets no more than N be on, and a key that would turn on one more does nothing. **For a patch without `OPR1` every reader's N is 2**, the dot command's and a `.nex`'s menu alike, so that such a patch has the menu, and the `.nex`, it always had. A reader that keeps to `OPR1` holds every option at once, a colour set, a language and four toggles: `firmware/nexclash.asm` does, in the same three pages. A writer warns when a patch without `OPR1` offers more than 2 that can be on together.

### OPR1: which options go together

Optional, at most once, in the clear, covered by the check value. **With it a menu has no limit of two at once: any options its rules allow may be on together.** Without it a patch reads as it always has. Its presence alone, with no rule, lifts the limit.

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | n, the number of rules, 0 to 32 |
| 1 | 5 each | Each rule: its type, then option A (kind, choice ID) and option B (kind, choice ID) |

An **option** is a set the menu offers: a colour set or a language (kinds 1 and 2), or a toggle (kinds 3 and 4), named by its kind and choice ID, which stay the same when a patch is remade, with the sprite build as its base. **Types:** 1, *excludes*: A and B are never on together. 2, *needs*: A is on only with B on. Bit 7 set on either, *menu only*: a reader without `OPR1` may make the combination, and it plays (so the writer checks it too); a reader with `OPR1` keeps to it all the same. A *needs* with bit 7 is written *implies*: A turns B on by itself when it runs, so A alone still plays, and the menu shows B on with it. Two sets of one kind are kept apart by their line already, and never named in one rule.

**A reader refuses as damage:** a block not exactly 1 + 5n bytes, n above 32, a second `OPR1`, a type other than 1, 2, 0x81 or 0x82, a rule naming an option the menu does not offer (no such set, another base, a fifth toggle), one option twice, or two sets of one kind; and `OPT1`'s bit 2 without an `OPR1`. A reader that does not know `OPR1` skips it, as any tag, and so does a reader that knows only `OPR1` and finds `OPR2`: it is then a patch without rules, with the limit of two.

**A reader keeps to the rules** in what it builds as well as on its menu: `tools/nxc.py` refuses a combination that breaks a rule without bit 7, and its menu `.nex` refuses to start in one that breaks any.

**The menu.** When a set's or a toggle's key has changed its line, the menu changes other lines until every rule is kept, never changing the keyed line or a line it has already changed, so each line changes at most once: it goes through the rules in order, again and again until a pass changes nothing; an *excludes* with both on turns B off, or A if B's line may not change; a *needs* with A on and B not turns B on, or, if B's line may not change, A off. Should a rule still be broken with neither line free, every set and toggle goes off, which breaks none; a writer makes sure that never happens. The help rows then say what changed, for up to two lines: `Also on: ` or `Also off: ` and the line's name, in place of the keyed line's help, until the next key. Trainers and the main line take no part, and with the main line off nothing changes, as before. `tools/nxc.py` `menu_settle` is these steps, and `firmware/menu.asm` with `MENU_RULES` is the same in Z80.

**A writer** (`nxc.py make --excludes A=B --needs A=B --implies A=B --no-cap`, or `nxc.py rules PATCH GAME -o OUT` with the same, keeping the nonce and key) refuses rules under which, from all off, the menu's keys reach a state that breaks a rule or cannot keep them, or leave an option impossible to turn on; checks, for every combination the rules allow, that no two options in it change the same byte and no toggle a trainer's POKE, and builds each one and checks its CRC; and works out what a reader without `OPR1` could make: any one or two options at once, one of each kind. Such a combination that the rules forbid is safe if two of its options overlap, as that reader refuses it before it makes any file, or if every rule it breaks has bit 7. **If any is neither, the writer sets `OPT1`'s bit 2**, so that a reader without `OPR1` refuses the whole patch as needing a newer loader, rather than build what the rules forbid.

**Compatibility.** A patch without `OPR1` is unchanged, byte for byte, and so are its bare and menu `.nex`, from every reader before and after. A reader before `OPR1` reads a patch with it as one without: two at once, with no rules, and it refuses the combinations whose options overlap, as it always has; one whose rules it could break otherwise is refused, by bit 2. `OPR1` raises no level.

### SET3: a choice that needs more memory

A colour set or a language that only fits a bigger Next: Enhanced colours whose pictures fill a 2MB Next, on a game whose base build fits a 1MB one. It is a `SET2` in every way but these: it says the most memory the game needs with it on; it may **add banks**, which the base build does not list and the set fills; and a loader offers it only on a machine with that memory. Optional. A patch may have several, all of one kind, as **alternatives on one line**, such as Enhanced colours at the Speed pace and at the original pace: each has the same need, the same added banks holding the same bytes, and the same table's indices, so that one carrier serves them all. They differ only in the banks the base lists. A writer refuses anything else; a reader refuses alternatives whose need, banks or table's indices differ as damage.

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | Stream index, in the clear. **Unique among all `SET2` and `SET3` blocks**: a repeat is damage |
| 1 | 1 | Kind: 1 colours or 2 language. Others are reserved, and a reader does not offer them |
| 2 | 1 | Choice ID, as in `SET2` |
| 3 | 1 | Base: 1, the sprite build. Others are reserved, and a reader does not offer them |
| 4 | 1 | Length of the name, 1 to 25 |
| 5 | | The name in ASCII, in the clear |
| | 1 | **Its need:** the highest 16K bank the rebuilt game needs with it on, from `OPT1`'s byte 2 to 111. A 1MB Next has banks 0 to 47, so 48 or more is "needs a 2MB Next" |
| | 1 | k, the number of banks it adds, 0 to 104 |
| | k | The banks it adds, rising, each from 8 to its need. None may be listed by the base build's header |
| | 1 | m, the number of entries in its table |
| | m | The stream index of each `SET2` block its table holds a CRC for, each once |
| | 4 | The CRC-32 of the finished file with this set alone over the base, encrypted under tag `SEB` plus the stream index, index 255, as in `SET2` |
| | 4 | The CRC-32 of its **carrier**, below, the same stream, index 254 |
| | 4m | Its table: for each index listed, the CRC-32 of the finished file with this set and that `SET2` alone, the same stream, index 253, in the listed order |
| | | Its chunks, to the end of the block |

**With it on**, the `.nex` is the base build's with its banks added: each added bank's flag set in the header (byte 18 + bank), byte 9 increased by k, byte 8 set to 1 if an added bank is above 47, and nothing else in the header changed. The added banks take their places in `.nex` order, among the base's, so the file is k x 16K longer. An added bank starts as 16,384 zeros, and the set's chunks fill it. **Its chunks** are exactly a `SET2`'s, a bitmap and its bytes for each bank it changes, in `.nex` order, and may be for any bank of the header with its banks added: the base's and its own. An added bank that stays all zeros needs no chunk. A reader refuses as for `SET2`, against that header.

**The check.** The added banks change the length and the layout, so the CRCs of the `SET2` blocks, made against the base, cannot be combined with this one's. So it carries its own: with it on, the output's CRC is

```text
CRC(combination) = CRC(this alone) XOR (CRC(this and set 1) XOR CRC(this alone)) XOR (CRC(this and set 2) XOR CRC(this alone)) ...
```

taking each chosen `SET2`'s term from this set's table. A chosen `SET2` with no entry in the table is damage; a writer puts every `SET2` with base 1 in it. The length is `OUT1`'s plus k x 16,384. A `SET2`'s chunks must still be for banks the base lists. A writer refuses a `SET2` that overlaps it as it refuses two sets that overlap.

**Its need, and the machine.** A reader that can find out how much memory the machine has (see `OPT1`) offers it only when the machine has banks 0 to its need. **On a machine with less, the line is shown, but cannot be chosen:** its value reads `[N/A]`, its key does nothing, and its help reads `Needs a 2MB Next` (for a need of 48 or more; a need it can never have, above 111, is damage), whatever `HLP1` says. A reader that cannot find out offers it, and refuses at the end if the machine turns out too small, as for `OPT1`. Everything else on the menu works as before, and the base build is what plays.

**Its kind's line is its own:** a writer refuses a patch with a `SET2` of the same kind as its `SET3`s, so the line is `[ ON]` or `[OFF]` with one, or steps through their names with several, and is named as `SET2` lines are, `Enhanced colours` or `Language`; `HLP1`'s `colours` or `language` is its help. A reader that finds such a `SET2` anyway refuses the patch as damaged. A reader offers the `SET3`s of the kind of the first it can apply, in file order, and passes over any of another kind, as a writer never makes them. A reader before alternatives (`option-ram-rule` 8f4ed97) offers the first only, as `[ ON]`: still a whole, correct choice.

**Rules.** In this version an `OPR1` rule may not name a `SET3` option: a reader refuses one that does as damage, and a writer does not make it. A `SET3` option is on with any `SET2`, toggle or trainer it does not overlap.

**Old readers stay safe.** A reader from before `SET3` skips the block, as any tag it does not know, so it sees the base build: the menu without the line, and a base whose `OPT1` byte 2 it can check against the machine. That is why the base must fit on its own, and why everything only the option needs is in its block: nothing a reader before it can make needs more than `OPT1` says. `tools/nxc.py`'s tests rebuild a patch with a `SET3` through the reader as it was before it, and get the base build and its menu `.nex`, byte for byte.

**Memory, in a loader.** A chosen `SET3` is decoded a chunk at a time, as a `SET2` is, in the same pages. Its added banks are made from zeros, and need nothing more.

**How a loader on a Next finds the memory.** NextZXOS counts the machine's memory when it starts and answers for it: `IDE_BANK` (0x01BD) through `M_P3DOS`, with H = 0 (ZX memory) and L = 0 (the total), gives in E the 8K banks of ZX memory there are, 96 on a 1MB Next and 224 on a 2MB one. Banks 0 to b need `2 x (b + 1)` of them. A loader asks before its menu and again when ENTER starts the build. If NextZXOS will not say, it offers the option and goes on, as for `OPT1`. Nothing here reads a NextREG or probes memory: NextZXOS has already done that, and a loader that paged through memory to find its end would be guessing at the board's wiring.

**`firmware/nexclash.asm`** keeps to all of this, with three limits of its own, each a refusal and never a wrong file: it holds no table, so a `SET3` chosen together with another set or a toggle is refused as needing a newer loader (trainers are fine); with a `SET3` offered, SPACE writes the bare `.nex` with the choices fixed, as ENTER does, since it does not write a carrier, and the menu `.nex`s are written by `tools/nxc.py` (`--ram 1mb`, `--ram 2mb`); and it does not check the carrier's CRC or the table, which it never uses. Its menu shows the line as `[N/A]` with that help on a 1MB Next. Its code for `SET3` runs from the menu's own page, mapped at 0x6000 while the build has nothing there, as the command's 8K is full. In JNext, whose memory is a fixed 2MB, the 1MB case is NextZXOS's answer set to 96 by a script, and in `tests/test_nexclash_ram.py` the harness answers 96 or 224.

**In a `.nex` that carries its menu.** A menu `.nex` made for a machine without the option's memory leaves it out: its menu and data are those of a reader before `SET3`, byte for byte, so it runs on the smaller machine. One made for a machine with the memory **carries the option**: its bare part is the **carrier**, the base build with the set's banks added and the set's chunks for its own banks applied, and nothing else, whose CRC the block holds; its menu banks start above the set's need (M0 is the need plus 1, not `OPT1`'s byte 2 plus 1); and its data holds the set's chunks for the banks the base lists only, as its own banks are in the file already. With the set off, the game starts with the same bytes in every bank the base lists as the bare base build, and its own banks, which the base never uses, are left as they are. `nxc.py PATCH GAME --ram 1mb` and `--ram 2mb` write each; without `--ram` it writes the one that carries the option.

### Reserved: game speed, SET2 kind 5

No tool or loader here writes or offers this; both already show nothing for it, as for any kind they do not know. The rules, so that every reader that comes to offer it offers the same thing. It comes from the speed review of 2026-11-04: a loader setting the CPU's speed (NextREG 0x07) by itself changes how several games play, so a speed is the engine's work, made and proven for each game, and the format only carries and selects it.

**What it is.** A `SET2` block of kind 5, base 1, exactly as any set: its chunks change the engine's own configuration, start-up and hook bytes in banks the base build already lists, so that the build runs the game at that clock, with whatever limiter keeps its pace. It cannot add a bank, change the header or the length; a build that will offer speeds reserves the room in its base. It is not a toggle of kind 3, as a changed clock changes interrupt timing, input sampling and the game's cadence, which are logic.

**The values are a fixed set**, by choice ID, so that every patch means the same by each:

| Choice | Name, as the writer gives it and a reader shows it | The game's clock in play |
|---|---|---|
| none chosen | `Original` | as the original game, and the base build: always offered, and the default |
| 1 | `7 MHz` | 7 MHz |
| 2 | `14 MHz` | 14 MHz |
| 3 | `28 MHz` | 28 MHz |

Other choice IDs are reserved, for later policies at a clock under a rule to be written then; a reader offers none of them. **What a build supports is the blocks it has**: a kind 5 block of a choice declares that speed, and there is no separate list that could disagree with them. A writer refuses a name other than the table's, two blocks of one choice, and a kind 5 block without `PRF1` key `speed_<choice>`, one line saying what the clock and its limiter keep and change (pace, sound, interrupts), what was replayed or measured with it, and against what, as a kind 4 toggle's `toggle_<choice>` does. `pace` and its fields describe the base build, at Original.

**The menu.** One line, `Game speed`, after `Language` and before the toggles, only when the patch has a kind 5 block with base 1. Its value starts `[Original]`, off as every choice starts, and its key steps through Original, then each speed offered in rising choice ID, and back to Original. Chosen, it counts as one set towards N, as any kind does. With the main line off it reads `[N/A]` and nothing of it is applied: the player's own game runs at the original clock. In a `.nex` that carries its menu it is carried and applied as any set is. A loader's own speed while it rebuilds, which `firmware/nexclash.asm` raises to 28 MHz and puts back, is separate, and never the game's.

**Readers that do not know it**, every one up to now, check the block's shape and stream index, offer no line, and play the base build at its original clock: no level and no flag. A later reader that knows it offers it with no change to the patch.

### Reserved: SPL1, where a build's sprite images lie

No tool or loader here writes or reads this. An optional block, in the clear, covered by the check value as every block is, skipped by a reader that does not know it, so it raises no level. It says where a build keeps its sprite images, so that a tool can **export** them from the rebuilt `.nex` to be repainted and **import** the repainted images straight back into the build's own sprite memory: Dean Woodyatt's idea. The repainted build is then a colour set, packaged with `nxc.py make --colours NAME=NEX` as any other; an import never changes a patch's own blocks, whose check would refuse it.

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | The layout's version: 1 |
| 1 | 1 | The sprite palette's bank, or 0xFF for none |
| 2 | 2 | Its offset in that bank |
| 4 | 1 | Its form: 1 one byte a colour, RRRGGGBB, as NextREG 0x41 takes; 2 two bytes a colour, as NextREG 0x44 takes |
| 5 | 2 | Its colours, 1 to 256 |
| 7 | 2 | n, the images, 1 to 1,024 |
| 9 | 12 each | The images, in rising order of index |

An image:

| Size | Field |
|---|---|
| 2 | Its index: the engine's own number for it, unique |
| 1 | Its bank: one the `.nex` header lists, below 112 |
| 2 | Its offset in that bank |
| 2 | Its size in bytes: whole patterns, a multiple of 256 for 8-bit or 128 for 4-bit, ending within the bank |
| 1 | Its form: 8 for 8-bit patterns of 256 bytes, 4 for 4-bit patterns of 128 |
| 1 | Its palette offset, 0 to 15, as bits 4 to 7 of a sprite's third attribute byte take it |
| 1 | Its shape: width in patterns less 1 in bits 4 to 7, height less 1 in bits 0 to 3; width times height patterns make its size |
| 1 | Flags: bit 0, built at run time (below); bit 1, it shares its patterns with an image listed before it; others 0 |
| 1 | 0, reserved |

A reader refuses as damage anything else: a version it does not know is skipped instead, as a later layout. Images may overlap only with bit 1 set. Nothing here holds the game: positions and sizes only. The images themselves stay where they are, in the banks a patch holds encrypted, and are seen only by someone who rebuilt the `.nex` with the game.

**Images built at run time cannot be exported from the file.** Some engines make sprite images as the game runs, from the game's own graphics or the screen: Nightshade's planes, Lunar Jetman's caches and The New Zealand Story's tilemap among them. In the `.nex` their place holds nothing yet, or something else. A writer lists such an image with bit 0 set, or not at all, and an exporter refuses one with bit 0: exporting it needs the engine's help, such as a hook that writes it out, or a dump of memory taken while the game runs, and importing it needs the engine to take a painted image in place of the one it builds. Neither is defined here.

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

The length of the block must be exactly that. All of these are checked for every trainer, chosen or not, before the menu, so that readers agree on whether a patch is good. `nxc.py import-pok` builds these from a `.pok`. A `.pok` line's bank field 0 to 7 means that bank paged at 0xC000; 8 means no paging: bank 5 at 0x4000, bank 2 at 0x8000, and at 0xC000 bank 0 on a 48K game. On a 128K game, bank 8 at 0xC000 or above says nothing of which bank is paged there when the game reads the byte, and the snapshot's 7FFD gives only the bank paged when it was saved, which can be another: Rainbow Islands is saved with bank 1 there and runs the code its cheat changes from bank 0. So `nxc.py import-pok` refuses such a line unless `--top-bank N` names the bank paged there in play, found by watching the game run; a `.pok` line naming its bank needs nothing. Below 0x4000 is refused. A trainer asking the player for a value (256 in the `.pok`) is left out for now. A POKE landing on a byte the patch changes, the changes of any set included, or in a bank the patch supplies, is refused when the patch is made, since its target is no longer the game's own code there. `--only "Name,Name"` imports just those trainers, in the `.pok`'s order; a name the `.pok` lacks or that asks for a value is an error. A writer keeps names unique; a loader goes by position.

Trainers apply to what is chosen, in the order of the file, so with two on the same byte the later wins. With the clash fix on they apply over the base build, and over any sets on, after the CRC is computed: the CRC and length in `OUT1` and the CRC in a set are always of the build without POKEs, and a failure leaves no file. A loader offers the first 8, or the first 7 when it offers two kinds of set, as only ten lines have keys, and holds at least 128 POKEs at once, refusing a choice with more. A trainer's bank must exist in what is being written.

### TAP1: a game from a tape

A tape target, `TGT1` kind 3 (`.tap`) or 4 (`.tzx`), is found and keyed as any target is: by its length, then the key wrap, with `dump_base` absorbing the whole file. Its banks do not come from the file by a fixed layout, as a snapshot's do. They come from a table in a `TAP1` block: copies of bytes from the tape's data blocks into banks, then sites for what the tape does not hold, over banks of zeros. What that makes is the game's memory at the point the build starts from, and from then on a tape target is treated as a snapshot with those banks: `SIT1`, `BNK1`, sets and trainers work on them as on a snapshot's. The data blocks are defined in "Tapes", below.

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | Stream index, in the clear. **Unique among all `TAP1` blocks.** A repeat is damage |
| 1 | 1 | n, the number of tape targets it serves, 1 to 32 |
| 2 | n | Their `TGT1` indices, in the clear |
| 2 + n | | The table, ZX0-compressed, then encrypted under `TAP1` with the stream index as index. Not empty |

Every tape target is in exactly one `TAP1`, and a `TAP1` names only tape targets, each once: anything else is damage. A set is a tape target, and a table that serves it may name any of its files; one that also serves a single file can name only file 0, which a writer checks by rebuilding. Releases of one game, such as its `.tap` and its `.tzx`, share a `TAP1` when one table makes the same banks from each, which a writer checks by rebuilding; otherwise each has its own, under the next stream index.

**The table**, at most 24,576 bytes once decompressed, the most a loader holds at once, as for `SIT1`:

| Size | Field |
|---|---|
| 55 | The start state: a `.z80` version 2 header. Bytes 6 and 7 are 0, bytes 30 and 31 are 23, and byte 34, the hardware mode, is 0 for a 48K game or 3 for a 128K one |
| 4 | The CRC-32 of the snapshot the clash fix off writes from it, without POKEs: see below |
| 2 | The number of copies |
| 10 each | A copy: 2 bytes data block, 3 bytes offset in that block's bytes, 2 bytes length (1 to 16,384), 1 byte bank, 2 bytes offset in the bank. Of the data block field, bits 0 to 9 are the block's number in its file and bits 12 to 14 the file's place in a set, 0 for the first; bits 10, 11 and 15 are 0. For a single file, then, the field is the block's number, as it always was |
| 2 | The number of sites |
| each | A site: 1 byte bank, 2 bytes offset, 2 bytes length (at least 1), then that many bytes |

and nothing after them. The header holds the start's registers, IFF1 and IFF2, interrupt mode, border, 7FFD, the last register selected on port 0xFFFD and the 16 AY registers (bytes 38 to 54), where a `.z80` file has them. Bytes a build does not use still count in the CRC.

A reader refuses as damage: a table that is not exactly those fields; a header breaking its rules; a copy with bits 10, 11 or 15 of its block field set, or naming a file past the target's last; a copy naming a data block past its file's, or past the first 1,024, or whose offset plus length passes that block's end; a copy or site whose bank is 112 or above, whose length is out of range, or whose offset plus length passes 16,384; and copies, or sites, out of order. Each of the two lists goes through banks in `.nex` order, and within a bank by rising offset, with no two of one list overlapping. A copy and a site may overlap, and then the site wins.

**The banks.** The machine's banks (0 to 7 for 128K; 5, 2 and 0 for 48K), and any other bank a copy or site names, start as 16,384 zeros. The copies are made, in order, then the sites. The machine's banks are then the game's memory at the start; another bank is an **extra bank**. Building the `.nex`, an extra bank its header does not list is damage, since it would never be used and readers could differ over whether it matters; the clash fix off uses only the machine's banks, and does not read the header. A reader works out the CRC below before it uses a bank, and refuses a mismatch as damage.

**What it holds of the game.** The copies say where things go, and the bytes come from the player's tape. The sites hold what is not on the tape: the screen as drawn, variables, the stack, and tables the game's code made when it ran, which are derived from the game. **A writer takes from the tape every run of 16 bytes or more of the start that the tape holds, wherever it holds it, and carries only the rest.** So a table holds none of the tape's code or data as it is, and no more than the 24,576 bytes a snapshot patch's `SIT1` may. `tools/nxc.py` also refuses more than 8,192 bytes of sites unless told otherwise: a start state the tape does not hold is a sign of a packed or encrypted tape, whose unpacked form is the game, and a plain copy recipe is not for those.

**Where the build starts** is the writer's choice, usually a `.z80` taken in an emulator from that tape, and the build is made from that `.z80`. The fewer of its bytes that are not on the tape, the better. For The New Zealand Story in JNext (128K), with this format's writer: at the jump into the main code, 5,151 bytes in 312 sites; at "LEVEL 1-1 READY", after the first world loads and before play, 3,813 bytes in 101 sites, with 68,367 bytes in 125 copies; in play, 6,536.

**Multiload.** A build that keeps a multiload's blocks in memory names extra banks for them. Copies place those blocks, or parts of them, wherever in those banks the build wants them; a writer takes them from the tape alone, and carries anything else the build has in such a bank in `SIT1`, as a change of its own. Hooking the game's loader to read the blocks from there is the engine's work, done in its own banks and sites: this format only places them. `OPT1` byte 2 counts them, as the `.nex` lists them.

**Memory.** A loader holds the table, at most 24,576 bytes, and builds a bank at a time from it. `firmware/nexclash.asm` gives it three 8K pages of its own, and reads each copy from the tape straight into the bank being built, so a tape needs 24K more than a snapshot, however long it is.

**Clash fix off.** A tape is never handed over as it is, nor is a set of them. The plain game is the start as a `.z80`: the table's header, then the machine's banks as whole pages, each 0xFFFF, its page number, then 16,384 bytes, pages 3 to 10 for 128K and 8, 4, 5 for 48K. It is written only after the keyed check, with or without a trainer. Its CRC-32 without POKEs must equal the table's; the POKEs then go in, and each must be in one of the machine's banks.

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
| dump | `TGT1` | The entry's index | The key wrap. A set's dump base absorbs every file of the set in order |
| master | `CHK1` | 0 | The check value. It is never a block's tag |
| master | `OUT1`, `NEX1`, `SIT1` | 0 | Those blocks |
| master | `BNK1` | The bank number | That bank |
| master | `SCR1` | The piece's index | That piece |
| master | `TAP1` | The block's stream index | That tape table |
| master | `SEB` then the set's stream index, as one byte | 255 | That set's CRC |
| master | `SEB` then the set's stream index, as one byte | The bank | That set's chunk for that bank |
| master | `SEB` then a `SET3`'s stream index, as one byte | 254 | Its carrier's CRC |
| master | `SEB` then a `SET3`'s stream index, as one byte | 253 | Its table of CRCs |

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

A reader walks a tape from its start until it has found the highest data block its table names, refusing on the way what this section refuses, and reads nothing after that block. **For a set, the files are walked in order, as one tape after another:** each file before the last one the table names is walked to its end, and may hold no more than 1,024 data blocks; the last one named is walked to the highest block the table names in it, as a single file is; a file after it is still opened, found and keyed, but not walked. A reader may so meet damage in an earlier file after the blocks the table names there, and refuses it, as a writer does. This is what lets a loader walk a set with one file open at a time. A writer checks every whole file.

## Applying a patch, in this order

Nothing is decompressed before step 5, and nothing is written before step 6. A set's chunks are decoded in both, one at a time for each set.

1. Open the patch, and refuse it if its name is one of the outputs: see below. Read the header. Refuse it as "not a patch" as above.
2. Walk every block, once, up to the end of the file. Refuse anything that does not fit. Refuse a second required block at once. For `OPT1`: its length, level and flags. For each `TGT1`: its shape, index and `file`. For each `TRN1`: its shape, flags and every POKE. For each `SET2`: its name fitting, its stream index unique. For each `TAP1`: its head, its stream index unique. Take `INF1`'s text. At the end: every required block there; at least one target this reader can read, or say a newer loader is needed; a `SCR1` only with level 2 or above; every tape target in exactly one `TAP1`, and nothing else in any; with only tape targets, `OPT1`'s bit 0 set.
3. Find the game: the first file that exists, in this order, whose length equals that of a target this reader can read, tapes included: each target's `file` beside the patch, then the patch's own name with `.z80`. One that is not there is passed over. One that is there under an output's name is refused. One of no listed length is noted and passed over. **Under any name.** Only if no file in that order is there with a listed length: any file in the patch's own folder whose length is that of a target of one file this reader can read, tapes included. It is the game only if it is that dump: its MD5 is the target's `md5`, or, for a reader that does not work out MD5s, it unlocks the patch in step 4, which only that file can. Such a file is checked so whichever route is chosen, even the clash fix off with no trainer, since nothing but its length says it is the game; one that fails is refused as the wrong file, and a reader goes on to the next such file or stops there. Folders and the volume's label are passed over, and the outputs' rule holds. A set's files are found by their names alone. **`firmware/nexclash.asm`** reads the folder with `F_OPENDIR` and `F_READDIR` in their 8.3 form, which every FAT file has and which always fits in a 22-byte entry, after first putting the targets' lengths in a buffer of its own, so that the patch is not read again for each entry; it opens the file by its 8.3 name, takes the first of a listed length in the folder's own order, checks it by the key wrap, and stops there, as nothing of the scan is left in memory after the menu. With the clash fix off and no trainer that check takes the 48K a trainer does. `tools/nxc.py PATCH -o OUT` with no game does the same on a PC, going through every file of a listed length, in name order, until one has the target's MD5. A wrong file under a listed name of a listed length still stops the search, as before: the folder is not read then.

None found: say which file is needed, and that the one there is wrong if one was noted. **For a set** whose first file is found, each other file it names must be beside the patch under its name with its length, in order: one missing is refused, naming it as needed; one of another length is refused, naming it as the wrong file. Show the menu.
4. Clash fix on, or off with a trainer on: absorb the file once, as `dump_base` (for a set, each of its files in turn, then the nonce). Take the targets of that length, from a copy of that state each, until a wrap's first 8 bytes are right: that is the master key. The file is never read again for another entry. None right: go on to the next file from step 3, or refuse as the wrong file (for a set, that its files are not the release the patch wants). Build `key_base`, and check the value at offset 22. Refuse as damage if it differs. Decrypt `OUT1`.
5. Clash fix on: walk the `BNK1` blocks and index them, refusing bad lengths and repeats. Decrypt and decode `NEX1`, and read the game's pages. For a tape, decrypt and decode its `TAP1`, check the whole table against the tape's data blocks, build the banks it makes, check its CRC, and refuse an extra bank the header does not list. Decode `SIT1` and check the whole of it. Refuse a listed bank with no source, or a `BNK1` for a bank not listed. Size any screen from byte 10 and check all its `SCR1` headers. For each set chosen, decrypt its CRC. Then go through the listed banks in `.nex` order, decoding and checking the chunk each set has for that bank, and refusing any bit set in two of them (a reader keeps the bits each takes, 2,048 bytes, and so needs no more for more sets). A chunk not reached that way is refused. Work out what the output's CRC-32 must be, from `OUT1` and theirs. Check the chosen POKEs' banks exist.
6. Create the output. Write the `.nex`: the header; any screen, a piece at a time; then each bank the header lists, in `.nex` order (5, 2, 0, 1, 3, 4, 6, 7, then upward), from `BNK1` if present, otherwise from the game with `SIT1` applied. Fill short banks with zeros. Decode each chosen set's chunk for that bank again, check it again, apply it, run the CRC over it, then apply the trainers' POKEs, then write it.
7. Check the CRC-32 against the value from step 5, and the length against `OUT1`. If either differs, delete the file and report damage.
8. Start the `.nex` with NextZXOS's own loader.

**Outputs and inputs.** The loader writes to fixed names, `/tmp/NEXCLASH.NEX` and `/tmp/NEXCLASH.Z80`, on the system drive, whichever the choice. It must not be reading one of those: making the output would truncate its own input. Before it reads a patch or a game, it asks NextZXOS for the file's folder (`F_GETCWD` with A=0xFF), which gives one form, such as `C:/TMP/`, for `/tmp/x`, `c:\tmp\x`, `tmp/x` from the root, `x` from `/tmp` and any path through `..`; and compares the folder, then the name after the last `/`, `\` or `:`, without regard to case, and ignoring dots and spaces at the name's end, which FAT drops. Either output name in that folder is refused for a patch or a game, whichever route is chosen. A folder NextZXOS will not resolve is refused too. It only ever deletes an output it has created. Being in `/tmp` under another name, or under that name on another drive, is fine.

**The clash fix off with a trainer on** writes the game as a `.z80` of whole pages with the POKEs in place, under the game's own header (version 1 becomes version 2), after the checks of step 4. With no trainer it is the game file itself, found as in step 3, with no further check at all, as `nxc.py --original` is, unless it was found under another name: then it is checked first, as step 3 says. `tools/nxc.py` writes the same for a `.z80`, and for a `.sna` keeps its layout, with the POKEs in place in each copy of a bank. **A tape**, trainer or not, is checked as in steps 4 and 5 and written as its start, as `TAP1` says.

## The menu

Every reader that offers choices shows this one menu, the same in the dot command and in a `.nex` that carries it (below), from one source, `firmware/menu.asm`. It is a standard ULA screen of 32 columns and 24 rows, in the ROM's 8 x 8 font, every attribute BRIGHT. The word NexClash appears nowhere on it.

```text
row  0   RENEGADE                    ////   blue bar, yellow title, four stripes
row  1   Imagine, 1987                             the publisher, white
row  2
row  3  TRAINER                                    yellow
row  4  1 Infinite lives           [ ON]           ON green
row  5  2 Infinite time            [OFF]
row  6
row  7  OPTIONS                                    yellow
row  8  3 Colour clash fix         [ ON]
row  9  4 Enhanced colours         [OFF]           OFF red
row 10
row 11  ENTER play   BREAK exit                    green, red
row 12
row 13  Infinite time:                             cyan: the name of the line last keyed
row 14  the clock stops at every round.            its help, two rows of 32
row 20  Colours: Jane Painter
row 21  Patch: Jon Attree           v1.0           the version, if there is one, ends in column 31
row 22   .nxc by Jon Attree         ////           the fixed footer: blue bar, yellow text, four stripes
row 23   Engine: Dean Woodyatt     ////            its stripes a column to the left, column 31 cyan
```

**Colours.** Attribute bytes, BRIGHT (0x40) in each: paper black and ink white (0x47) wherever nothing else is said; the bars 0x4E (blue paper, yellow ink), and their text in it; headings 0x46; `ON` 0x44, `OFF` 0x42, `N/A` and the brackets 0x47; a set's name, shown when it is on, 0x44; `ENTER play` 0x44 and `BREAK exit` 0x42; the help's first row 0x45. No line is highlighted. The border is not changed. **The stripes** are four cells of each bar, each the same glyph, its pixels set where x + y >= 7 (x from the left, y from the top, 0 to 7: bytes 01 03 07 0F 1F 3F 7F FF), with paper and ink blue and red, red and yellow, yellow and green, green and cyan (0x4A, 0x56, 0x74, 0x65). They are columns 28 to 31 of every bar but row 23, whose stripes are columns 27 to 30, one to the left, so that each diagonal runs on unbroken from row 22 into row 23; its column 31 is BRIGHT cyan paper (0x68) with no pixels set.

**Rows.** **The title is never cut:** it has the blue bar to itself, in capitals, from column 1 to 27, before the stripes in 28 to 31. A longer one wraps at its last space within the first 27 characters (or at 27 if there is none) to a second bar row, also with its stripes; a writer keeps a title to 54 characters, two bar rows, and a reader shows no more. The publisher, `INF1`'s `publisher` as it stands, is on the row below in white, from column 1, or from column 0 when it needs all 32; it is cut only past 32. Then a blank row, unless the title took two. Then `TRAINER` and the trainers' lines, if there are any, then a blank row, then `OPTIONS` and its lines: the main line, one line for each kind of set offered, one for each toggle. A blank row, unless the keys' row would then pass row 16, then `ENTER play` in columns 0 to 9 and `BREAK exit` in 13 to 22. A blank row, unless the help would then end past row 19, then the help: the name of the line last keyed (line 1 to begin with) and `:` (cut to 31), then its help text, characters 1 to 32 and 33 to 64, if the patch gives it; otherwise those rows are blank. **The longest menu**, ten lines in both sections, has its lines in rows 3 to 15, so the blank row before the keys is the one left out: the keys are on row 16, the help in rows 17 to 19, and every shorter menu keeps both blank rows, or loses only the one after the keys. Row 20: `Colours: ` and `colours_by`, cut to 23, only for a patch with a colour set offered and that name. Row 21: `Patch: ` and `patch_by`, cut to 25, if it is there; with a version, `v` and `INF1`'s `version` (at most 8) end in column 31, and `patch_by` is cut to 23 less the version's length, so that a blank column comes before the `v`: `patch_by` is cut, never the version. Without `patch_by` the row is the version alone, ending in column 31. The whole row is in the white of 0x47. Without a version it is as it always was. Anything unprintable shows as `?`.

**The footer**, rows 22 and 23, is the same on every patch's menu, in the dot command and in a `.nex` that carries it. It is drawn by `firmware/menu.asm` from text of its own: **nothing in a patch is read for it, so no patch can change, remove or add to it**, and a reader shows it whatever the patch holds. Row 22: the bar, with ` .nxc by Jon Attree` from column 0 in its yellow, and its stripes in columns 28 to 31. Row 23: the bar, with ` Engine: Dean Woodyatt` from column 0, its stripes in columns 27 to 30 and column 31 cyan, as above. It credits the format's author and the engines' author on the screen a player sees; each patch's `credit` field and its `.nfo` still give the full credit, `Built with NexClash by Dean Woodyatt ...`. (Until 2026-11-04, row 23 was a bar with its stripes and no text, and `Colours:` and `Patch:` were rows 21 and 22.)

**A line.** Column 0 its key, `1` to `9`, then `0` for the tenth; its name from column 2; its value ending in column 31: `[ ON]`, `[OFF]` or `[N/A]`, or for a kind with more than one set, the chosen set's name, cut to 12, in brackets. The name is cut to leave a blank column before the value. Names are up to 25 characters, so `[ ON]` keeps its column.

**What the lines are** is as before, in this order:

- **Trainers**, one line each, `[OFF]` to begin with (in a `.nex`, where its writer left them), in the file's order.
- **The main line,** `INF1`'s `fix_label`, or `Colour clash fix` without one. `[ ON]` to begin with: on, the rebuilt NexClash `.nex`; off, the player's own game, with any trainers. Wherever this document says the clash fix, it means this line. **In a `.nex` that carries its menu, the line is shown `[ ON]` and its key does nothing,** by definition: that file is the rebuilt game and holds no copy of the plain one.
- **One line for each kind of set offered,** `Enhanced colours`, then `Language`. Its key steps from `[OFF]` through the kind's sets, in the file's order, and back. With one set of the kind the line is `[ ON]` or `[OFF]`; otherwise the value names the set. Only sets with the sprite build as their base are offered.
- **One line for each toggle,** its name, `[OFF]` to begin with, its key turning it on and off.
- With the main line off, every set's and toggle's line reads `[N/A]`, its key does nothing and nothing of it is applied; the choices come back when it is on again.
- Ten lines are all there are keys for: the main line, one line for each kind of set and one for each toggle come first, and trainers fill what is left, at most 8.

**The limit.** Without `OPR1`, a reader lets no more than 2 sets and toggles be on at once: a key that would turn on a third does nothing, and the line stays `[OFF]`. A `.nex` carrying its menu holds N = 2 in its description, so that the two menus offer exactly the same choices. **With `OPR1` there is no limit but its rules**, kept as "OPR1" says: the description's N is 255 and its flags' bit 2 is set.

**Keys.** A line's key acts on it as above, and its help shows. There is no cursor and no highlight: the number keys are the only way to change a line. ENTER and SPACE both start with what the menu shows. BREAK, CAPS SHIFT with SPACE, cancels.

**Defined behaviour in a `.nex` that carries its menu:** the main line is fixed `[ ON]` and its key does nothing; ENTER and SPACE start the game alike; BREAK resets the Next (NextREG 0x02 = 1), as nothing is left to return to. **In the dot command:** BREAK stops with `Cancelled`; after ENTER or SPACE the keys' row reads `Patching...` (or `Loading...` with the main line off) in FLASH, BRIGHT yellow on black (0xC6), and the menu screen stays up until the command is done, as a rebuild can take a few seconds; with the main line on, ENTER writes the bare `.nex` with the choices fixed, so the game starts straight after its title with no second menu, and SPACE writes the `.nex` that carries its menu, its lines starting where they were left; with the main line off, either key writes the player's own game, with any trainers, as before.

**Help text** comes from `HLP1`, below, and is optional: without it, or without a line's key, the help rows are blank. A reader that does not know `HLP1` shows no help.

### HLP1: help for the menu

An optional text block, in the clear, covered by the check value as every block is, and skipped by a reader that does not know it, so it raises no level and sets no flag. Lines of `key=value`, as in "Text blocks":

| Key | The help of |
|---|---|
| `fix` | the main line |
| `trainer_N` | trainer N, from 1, in the order of the file's `TRN1` blocks |
| `colours`, `language` | that kind's line |
| `toggle_N` | toggle N, from 1, in the order of the file's toggles (kinds 3 and 4 together) |

A value is 1 to 64 printable ASCII characters, shown as two rows of 32, the first 32 then the rest, as they are: a reader does not wrap. `nxc.py help` wraps a text at the last space before column 33 by padding with spaces, and refuses one that is then longer than 64, an unknown key, or a `trainer_N` or `toggle_N` past the patch's last. A reader reads at most the first 1,024 bytes of the block; a line cut off there counts as absent. A longer value shows its first 64. Changing help keeps the nonce and key, like `credit`, and needs the game, as any change to a patch does.

## A .nex that carries its menu

A rebuilt game must stay usable without this project. So the **default** output of both `nxc.py` and the dot command is a `.nex` with the menu in it: when it starts, on any Next or emulator that runs a `.nex` through `.nexload` or its own `.nex` loader, it shows the menu above, with every trainer, every set and every toggle the patch offers, applies the choices to the game's memory in place, from data carried in the file, and starts the game. **With choices X the game starts in exactly the state the `.nex` written by a reader for choices X starts in:** the same bytes in every bank the game's header lists, the same CPU registers but R, the same IFF, IM and I, the same MMU and the same stack. A writer offers a **bare** `.nex`, the one this document defined before, with the choices fixed when it is made: `nxc.py --bare`.

### The file

It is the bare `.nex` with nothing chosen, as `OUT1` describes it, changed only as follows:

- **The header.** Each menu bank's flag set (byte 18 + bank) and byte 9 increased by their count. The start address (bytes 14, 15) is 0xC000 and the entry bank (byte 139) the first menu bank, M0. Byte 8 is set to 1 if a menu bank is above 47. Nothing else changes: the stack pointer, border, screen flags, core version, delays and the rest are the build's own.
- **The menu banks,** M0, M0 + 1, ..., in `.nex` order after the build's own banks, so the file is the bare file's screen and banks followed by them. M0 is `OPT1`'s byte 2 plus 1: a bank the build never uses, by that byte's definition. A writer refuses past bank 111.

**A writer refuses a menu** for a build whose header is not `V1.2`; whose start address is 0, below 0x4000 + 57, or one to four bytes into an 8K page (see the handoff); or whose header asks `.nexload` to pass the file's handle on (bytes 140, 141 not 0), as that game would read on into the menu banks. It says so, and `--bare` is still there. The builds of all 17 published patches and of The New Zealand Story's 8 are `V1.2`, start at 0xC000 in their entry bank with the stack at 0xDFFE, and pass no handle.

**M0** is seen from 0x0000 to 0x3FFF while the stub runs:

| Offset | Size | Holds |
|---|---|---|
| 0x0000 | | The stub, `firmware/nxcstub.bin`, assembled from `firmware/nxcstub.asm`, which includes `firmware/menu.asm` |
| | 8 | Its parameters, the stub's last 8 bytes: M0's first 8K page, the build's start address (2), its stack pointer (2), its entry bank's first 8K page, how many menu banks, then 0 |
| | | The menu's description, below |
| to 0x1D00 | | All of that must end by here: a writer refuses a menu that does not |
| 0x1D00 | 57 | Where the last 57 bytes are put together |
| to 0x2000 | | Free, but for the shadow below |
| 0x2000 | 6,912 | Bank 5's first 6,912 bytes, kept while the menu is on the screen |
| 0x3B00 | 768 | The font, copied from the ROM at 0x3D00 |
| 0x3E00 | 384 | The stub's variables, then its stack, the registers kept at entry at its top (0x3F80) |
| 0x3F80 | 128 | Free, but for the shadow below |

**The description** is what `firmware/menu.asm` draws and changes, in the same form in the dot command's memory: a flags byte (bit 0: the main line is fixed `[ ON]`; bit 1: a version follows `patch_by`; bit 2: `OPR1`'s rules follow the lines' offsets); N; the number of lines, 1 to 10; then zero-terminated strings: the title, the publisher, `colours_by` (empty when no colour set is offered) and `patch_by`, and with bit 1 the version, as a reader shows it without its `v`, 1 to 8 characters; then each line: its kind (0 trainer, 1 the main line, 2 a kind of set, 3 a toggle), its state (0 off; for a kind of set, 0 or the chosen set from 1), the number of sets for a kind of set or 0, then zero-terminated its name, its help, and for a kind of set each set's name; then for each line, 3 bytes: where its data starts in the data, below, as an offset from the data's first byte, or 0xFFFFFF for none. With the flags' bit 2, for a patch with `OPR1`, N is 255 and the rules follow: their count, then 5 bytes each, its type (1 excludes, 2 needs, without `OPR1`'s bit 7), then line A, the state that is A on, line B, the state that is B on, lines numbered from 0 in the description's order.

**The data** starts at the first byte of M0 + 1 and runs on through the menu banks after it, the last padded with zeros to 16K; without data there is only M0. For a trainer: its count of POKEs, 1 to 255, then each POKE's bank, offset (2) and value, as in `TRN1`. For each set of a kind of set, in the file's order, and for a toggle: its chunks, decoded, in `.nex` order, each its bank, the chunk's length (2) and the chunk, the bitmap of 2,048 bytes then a byte for each bit set, exactly as `SET2` holds it once decoded; then a bank of 0xFF. Every bank is one the build lists.

**The starting states.** The description's states are where the menu starts: a writer takes them from the choices it was given (`nxc.py PATCH GAME --trainer 1 --colours Enhanced` without `--bare`, or the dot command's menu when ENTER is pressed), or all off without; the main line is always on. The data does not depend on them, so the same patch, game and choices always give the same file.

Sets and toggles are carried decoded, in the clear: this file is the player's own built game, which holds the rest of the game's memory in the clear already, and it is not for handing around, as a bare `.nex` is not.

### What the stub does

1. **Entry,** at 0xC000 with M0 there, as `.nexload` leaves it. Before anything else, without touching the game's memory or stack: keeps SP, moves the stack into M0, keeps AF, reads IFF2 with `LD A,I` and keeps it, disables interrupts, keeps BC, DE, HL, IX, IY and the alternates, and copies the ROM font. Then it maps M0's pages at 0x0000 and 0x2000 and runs there, so that slots 2 to 7 are free to page.
2. **The menu.** It keeps bank 5's first 6,912 bytes, draws the menu, and runs it. NextREGs are written through ports 0x243B and 0x253B; port 0xFE is only read. The border, the palette and the layers are not touched, so a build whose loading screen leaves Layer 2 over the ULA hides the menu: none of the pilot's builds does, and a writer that knows it would need to say so.
3. **The choices.** Bank 5's 6,912 bytes are put back. **The shadow:** with the build's stack in its entry bank (SP − 16 at 0xC000 or above, wrapping), `.nexload` writes below that stack before it starts the stub, into M0, which is there in its place: JNext's loader pushes the start address and returns. So a writer fills M0's 16 bytes below SP − 0xC000 with the entry bank's own bytes there, and the stub copies them back into the entry bank, so it holds what `.nexload` would have left. Those 16 bytes must lie in M0's free room, after the description to 0x1D00, 0x1D40 to 0x2000 or 0x3F80 to 0x4000, and no trainer, set or toggle may change them, or the writer refuses the menu. Then each chosen set and toggle is applied, in the order of the lines, and then each chosen trainer's POKEs, in the order of the lines: as a reader applies them to the `.nex` it writes. A trainer is applied whether or not the main line is on, since it is always on here.
4. **The handoff,** the same for every build: the MMU as `.nexload` leaves it for the build's own header: slots 0 and 1 to 0xFF, the ROM; 2 and 3 to pages 10 and 11; 4 and 5 to 4 and 5; 6 and 7 to the entry bank's two pages; the registers kept at entry; SP as `.nexload` left it; interrupts as they were. To leave nothing of itself in the game's memory, the stub puts its last 57 bytes into M0's second page, maps that page at the one or two 8K slots that hold the 57 bytes before the start address P, puts back every other slot, and jumps there. Those bytes are the registers, then: `LD SP` to them, the pops, `EXX`, `EX AF,AF'`, the pops, `LD SP` to the header's, `NEXTREG` slot 0 and 1 back to the ROM, then `NEXTREG` for the slot holding the 57 bytes' start if it is not P's (or four `NOP`s), `EI` if interrupts were on (or `NOP`), and last `NEXTREG` for P's own slot, which ends at P. The next fetch, at P, is from the game's page. This is why P cannot be 1 to 4 bytes into a page: with the 57 bytes in two slots, the `EI` or `NOP` and the last instruction must lie in P's slot, after the earlier slot is given back.

**What is not the same** as a bare `.nex` started by `.nexload`: R; the time taken; NextREG port 0x243B's selection, which is left at the last register the stub wrote, as a game always selects one before it reads or writes; and the menu banks, which hold the stub, and which the build never uses.

**RAM.** The menu banks are above everything the build needs, so a menu `.nex` needs `2 x (M_last + 1)` 8K banks where the bare one needs `2 x (byte 2 + 1)`: one more 16K bank for a patch with only trainers, and more for sets, as their data needs. A writer sets byte 8 when that passes 1MB, and a reader that checks memory checks the menu `.nex`'s need.

### Versions and compatibility

Nothing here changes a patch: `HLP1` is a new optional block, skipped by every reader before it, and old patches without it show the new menu with no help. Every existing vector is unchanged byte for byte, and so is the bare `.nex` for any choices. The default output changing is a change of the readers, not the format: a reader older than this one writes the bare `.nex`, as it always did. A menu `.nex` is a `V1.2` `.nex` that any `.nex` loader starts.

The fixed footer changes no patch and no description: it is in `firmware/menu.asm`, so a menu `.nex` written since has a longer stub and the footer, and is otherwise the same file.

`INF1`'s `version` is an optional key, skipped by a reader that does not know it, so it raises no level and sets no flag. The description takes it in a way that leaves it as it was without one: the version's string is there only with the flags' bit 1, so a patch without a version gives the same description, and the same menu `.nex`, byte for byte, as before. A description always travels with the `firmware/menu.asm` that draws it, in the same `.nex` or the same dot command, so an older menu never reads a newer description.

`OPR1` changes nothing for a patch without it: the description, the stub and the `.nex` are what they were, byte for byte. For a patch with it, the description has the flags' bit 2 and its rules, and the menu that keeps to them is a second stub, `firmware/nxcstub2.bin`, assembled from the same `firmware/nxcstub.asm` and `firmware/menu.asm` with `MENU_RULES` defined; `firmware/nxcstub.bin`, without it, is the one every patch without `OPR1` has always carried. A writer chooses by the block alone. The dot command carries both, after its parts in its own file, each ending in a part's tag, and reads the one it needs into M0 when it writes the menu `.nex`.

### The dot command's menu .nex

`firmware/nexclash.asm` writes the same file as `tools/nxc.py` for the same patch, game and starting states, byte for byte. Its menu, `firmware/menu.asm` and what builds the description, is read from the command's own file into an 8K page of its own before the menu, which also holds the stub; it takes the font from the card's `C:/MACHINES/NEXT/enNextZX.rom` (ROM 3, at 0xFD00), as a dot command cannot see the ROM, and refuses without it. After the menu it writes the bare `.nex` with nothing chosen, as before, then a part read over the game's part writes M0 and the data, decoding each set a chunk at a time, and puts the header, the stub's count of banks and the lines' offsets in place. It checks the bare part's CRC and length as before, and the whole file's length. It needs the page for the menu and three for decoding sets, beyond what the bare file needs.

## Test vectors

`tests/vectors/` holds a whole patch, the game files it accepts and the intermediate states, all made from synthetic bytes by `tests/vectors/make_vectors.py`; and a tape patch, its `.tap`, its `.tzx`, the `.z80` it starts from and its table, made by `tests/vectors/make_tape_vectors.py`, which also makes a patch for one target of two files, `tapeset_a.tap` and `tapeset_b.tzx`, with its table. `vector_toggle.nxc` adds a display toggle, and `vector_label.nxc` a `fix_label`. Nothing there comes from any real game.

## Limits of version 1

- **Listed files only.** A dump is found under any name, but one byte different from every listed dump is refused. Accepting another dump means adding an entry for it, with its bytes in hand.
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

# TAP1: patches from tapes

Notes for Jon, 2026-11-03. Everything here ran in JNext 1.1.104 or on the Z80 harness. **Nothing has run on a Next or a Tang.**

## What changed

- **Spec** ([NXC-FORMAT.md](../spec/NXC-FORMAT.md), "TAP1" and "Tapes"). A tape is a target of kind 3 (`.tap`) or 4 (`.tzx`),
  keyed over the whole file like any other. Its `TAP1` block holds, encrypted, the start state as a `.z80` v2 header (registers,
  IM, border, 7FFD, AY), copies of tape bytes into banks, and sites for what the tape doesn't hold. Data blocks are numbered in file
  order: every `.tap` block, and TZX 0x10, 0x11 and 0x14. Every other TZX ID the spec lists is skipped, and any other ID is
  refused. Extra banks let a build keep a multiload's blocks in memory. Hooking the game's loader to use them is engine work.
  `OPT1` byte 1 bit 0 marks a patch that only a tape can play. A writer refuses more than 8,192 bytes of sites by default. That
  keeps the rule that a patch carries no game code: everything the tape holds is taken from the player's tape.
- **Tool** (`tools/nxc.py`). `make` takes a tape with `--start START.z80` and optional `--tape-bank N`. `add-target` (another name
  for `add-dump`) adds a second release. It shares the table if the same table makes the same banks, and otherwise gives the
  release its own. `--original` on a tape writes the start state as a `.z80`. Every existing patch and vector is unchanged byte
  for byte. I regenerated `vector.nxc` and `vectors.json` and compared them.
- **Loader** (`firmware/nexclash.asm`). It reads `.tap` and `.tzx`. Only 42 bytes were free, so the snapshot code now sits behind a
  jump table, and for a tape two parts are read over it from the same file. [firmware/README.md](../firmware/README.md), "Tapes",
  has the details. A tape needs 24K more RAM than a snapshot.

## Making a TAP1 patch

1. Load the plain tape in JNext as a 128K machine. Save the machine at a point where it waits, with the most loaded and the least
   drawn. For NZS that was "LEVEL 1-1 READY", after the first world loads. A script does it: `save_snapshot "x.szx"` at a frame.
   JNext saves `.szx` or `.sna`, not `.z80`. `NextTang-evidence/2026-11-03-tap1/tmp/work/szx2z80.py` converts the `.szx`.
   JNext's `.szx` has no AY chunk, so the AY registers start at 0.
2. Build from that `.z80` as usual. My plain proofs used NexClash's `z80tonex.py`, with `--tail 0x7D00` for NZS, whose stack is in
   the top 16K.
3. Package from the tape:
   `nxc.py make Game.nex "Game.tap" --start Game_start.z80 -o Game.nxc --title ... --publisher ... --patch-by "Jon Attree"`.
   It prints how much came from the tape and how much it carries.
4. Add the other release with `nxc.py add-target Game.nxc Game.tap Game.tzx -o Game2.nxc`.

## Tests

- Whole suite: **310 tests, all pass, 92 skipped** (the real-game tests whose files aren't in the repo, as before). The baseline was
  255 tests.
- New: `test_nxc_tape.py` (33 tests, the tool), `test_nexclash_tape.py` (13, the loader on the harness: byte-exact with the tool,
  every damaged table refused with nothing written, cut parts, two controls), and tape vectors with a walker written from the spec
  alone.
- **JNext, real loader, NextZXOS v2.09, through the Browser:**
  - **The New Zealand Story** `.tap` (d5f47d90…): `/tmp/NEXCLASH.NEX` is `902a84eee4e179d94244107f119575bf`, the same as `nxc.py`.
    The `.tzx` (b0711e0d…) alone gives the same `.nex`. With the fix off, `/tmp/NEXCLASH.Z80` is
    `e544e5784e11f51ce8ff793db5053e7b`, the same as `nxc.py --original`. The patch is 4,029 bytes for both releases, carrying
    3,813 bytes of the start. The game reached play: Tiki shooting, score 350, lives lost and restarted.
  - **The Simpsons: Bart vs. the Space Mutants** (Ocean, 128K only), `.tap` 8e08c32c…: the `.nex` is
    `f35381147215d45e7940e1cecf6ae348`, the same as `nxc.py`. The patch is 4,513 bytes, with 101,206 bytes from the tape and
    6,035 carried. It reached play, with the clock counting down.
  - **Cobra** (snapshot route, new loader): `befe11d9e200531c9f2ffb9138ac51d6`, as before.

  Screens and outputs are in `NextTang-evidence/2026-11-03-tap1/tmp/jn/`.

## Found on the way

- **Rick Dangerous** (Firebird) is refused: only 964 bytes of its running memory are on the tape as they are, so 44,232 would have
  to be carried. Its tape is packed. That is the rule working.
- **The Simpsons `.tzx`** (24834cbc…) doesn't hold the same data as the `.tap`. It would need 10,988 bytes carried, so I left it
  out.
- **NZS multiload is not hooked.** The plain `.nex` starts at level 1-1 and will ask the tape for world 2, as the original does.

## For you to decide

- Should `szx2z80.py` go into the repo as a command (`nxc.py szx-to-z80`)?
- Is 8,192 bytes of start state not on the tape the right default limit?
- Tapes are an `OPT1` flag, not a level. Levels are a ladder, and level 4 is reserved for snapshot output. Is that all right?
- With a tape and two sets, the loader needs 120K, but its refusal says 96K.
- Send Dean the updated spec.

# The menu round

Notes for Jon, 2026-11-04. Everything here ran on the Z80 harnesses or in JNext 1.1.104, headless. **Nothing has run on a
Next or a Tang.**

## What changed

- **Spec** ([NXC-FORMAT.md](../spec/NXC-FORMAT.md), "The menu", "HLP1", "A .nex that carries its menu"). The new menu,
  mock-up A: black, a blue title bar and a credit bar with the four Spectrum stripes, yellow `TRAINER` and `OPTIONS`, `ON`
  green, `OFF` red, `ENTER play` green and `BREAK exit` red, a help line for the line last keyed, `Patch: <patch_by>`
  and a plain bar at the bottom (no highlight, no cursor keys, no engine line: the owner's calls, 2026-11-04; the bottom is now a fixed footer, below). NexClash is not on it. Layout, colours as
  attribute bytes, the cutting rules and the keys are all specified. `HLP1` is a new optional clear block of help texts.
  The in-`.nex` menu is specified whole: the header changes, the menu banks above `OPT1`'s byte 2, the stub, its
  description and data, the stack shadow, the handoff, what is not the same (R, time, the NextREG select latch), RAM, the
  refusals, versions. No existing patch or vector changes.
- **One menu source.** `firmware/menu.asm` draws and runs the menu from a description. `firmware/nxcstub.asm` includes it.
- **The stub,** `firmware/nxcstub.asm` (2,150 bytes, kept assembled as `firmware/nxcstub.bin`). It keeps what `.nexload`
  left, shows the menu, applies the sets and toggles, then the trainers, from runs carried in the menu banks, and starts
  the build through its last 57 bytes, so that the game's first instruction sees its own memory, registers, IFF, MMU and
  stack.
- **Tool.** `nxc.py PATCH GAME -o X.nex` writes the menu `.nex` by default. `--bare` writes the old one, with choices;
  choices without `--bare` are refused, saying why. `nxc.py help` sets `HLP1`. `nxc.py` now reads `.z80` itself, so
  applying needs nothing outside the repository and Python's standard library.

## Proofs

- **Same start, in JNext** (`--load`, real NextZXOS boot recording; a script at 0xC000 in the build's entry page logs every
  register and the MMU and dumps every bank the bare header lists): the bare `.nex` for choices X against the menu `.nex`
  with X pressed on its menu. Jetpac (none; trainer; Enhanced + trainer), Atic Atac (both trainers; Enhanced), Ikari
  (trainers 2 and 5 + Enhanced), Renegade 128K (trainers 1, 2 + Enhanced), Spellbound (1, 3 + Enhanced), The New Zealand
  Story's two-file tape patch (trainer 1 + Smooth scrolling; trainer 2): **all the same**, every register but R, IFF, IM,
  I, MMU and every listed bank. A control, trainer 1 on the menu against a bare file without it, differs, as it must.
  JNext's own loader turned out to push the start address below SP, which in the menu path landed in M0: that is the
  stack shadow in the spec, found by this comparison and fixed.
- **Same start, in the simulator** (`tests/nex_harness.py`): every choice of the vectors, IFF on and off, tape and tape-set
  vectors, and in `RealPatches` all 17 published patches and NZS's 8 patches, with no choices, every trainer, each set and
  each toggle.
- **Bare output unchanged:** 109 bare and `--original` outputs, over the 17 published patches and NZS's, with no choices,
  every trainer, each set and toggle, are byte for byte those of the tool before this round (220fbf8). Every vector is
  unchanged.
- **Snapshot reader:** the same banks, version, 128K flag, 7FFD and registers as NexClash's `Z80Snapshot` on every vector,
  every form made up in the test, and 61 game files from the published patches and the pilot runs.
- **The look:** JNext screenshots of the in-`.nex` menu are in `NextTang-evidence/2026-11-03-tap1/tmp/menu/jn/shots/`.

## The loader (second pass, 2026-11-04)

- **The same menu.** `firmware/nexclash.asm` reads `menu.asm`, with what builds its description, from its own file into a page
  of its own before the menu, and takes the font from the card's `C:/MACHINES/NEXT/enNextZX.rom` (ROM 3, 0xFD00).
- **ENTER writes the bare `.nex`** with the choices fixed, so the game starts after its title with no second menu (changed
  2026-11-04: the owner saw menu, title, menu, title, game); SPACE writes the menu `.nex`, starting as the menu was left;
  fix off, the game as before. The menu `.nex` writer is a part read over the game's part after the bare banks.
- **Byte-exact with `nxc.py`** on the harness: the vector with no choices, a trainer, both sets, a trainer and a set; the tape,
  tape-set, toggle and label vectors; and the published patches and NZS's in `NXC_MENU_GAMES`. **In JNext through the
  Browser, real NextZXOS and `.nexload`:** NZS's two-file patch with trainer 1 and Smooth scrolling gave `b297e48f…`, the
  same as `nxc.py`; `.nexload` started it, its menu came up set, and ENTER reached the title screen.
- **The same screen:** the loader's menu and the `.nex`'s, both on line 6 with 1 and 6 on, are pixel for pixel the same over
  the screen area; only the border differs (the Browser's against the build's).
- **The title is never cut:** it has the bar to itself, wrapping to a second bar row past 27; the publisher is below it.
- **The test card** is `nexclash-patch/build/batch3/card_menu.img`: `card_nzs.img` with the new `NEXCLASH` and `NXCHAND.BAS`,
  and the NZS patch (unchanged: the new menu needs no change to a patch) in `C:/NZS/`.

**Changed in the existing tests:** they drive the bare route with SPACE, as ENTER is now the menu `.nex`; page counts leave
out the menu's page, which every run holds; free-RAM thresholds are one page higher; menu text checks use the new layout;
the credit line is now two rows, each cut on its own. The real-game Cobra and Jetpac tests, which skip without `build/v1`,
still check the old menu text and will need the same change when run.

## The footer (format round, 2026-11-04)

The owner approved a fixed footer from a preview: `Colours:` moves to row 20 and `Patch:` to 21, and rows 22 and 23 are two
blue bars, ` .nxc by Jon Attree` and ` Engine: Dean Woodyatt`, the lower bar's stripes a column to the left with its last
cell cyan, so that one band of diagonals runs through both. `firmware/menu.asm` draws it from its own text, so no patch can
change it. To keep the help clear of row 20, the longest menu (ten lines, both sections) loses its blank row before
`ENTER play`; every other menu keeps it. On the Z80 harnesses only, the dot command's and the `.nex`'s screens are the same.

## For you to decide

- Decided and in the spec: the main line in a `.nex` fixed `[ ON]`; BREAK in a `.nex` resets; the loader's ENTER is the
  bare file (no menu twice); no highlight or cursor keys; no engine line on the bar (Dean is credited in `credit` and the `.nfo`), since replaced by the fixed footer above.
- **zx0.** A pure-Python compressor was considered and not written: `zx0`'s optimal parse searches every offset for every
  byte, which in Python would take minutes a bank, and matching its output byte for byte means porting its exact tie
  breaks. It stays an optional dependency for `make`; applying never needs it.

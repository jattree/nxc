# The menu round

Notes for Jon, 2026-11-04. Everything here ran on the Z80 harnesses or in JNext 1.1.104, headless. **Nothing has run on a
Next or a Tang.**

## What changed

- **Spec** ([NXC-FORMAT.md](../spec/NXC-FORMAT.md), "The menu", "HLP1", "A .nex that carries its menu"). The new menu,
  mock-up A: black, a blue title bar and a credit bar with the four Spectrum stripes, yellow `TRAINER` and `OPTIONS`, the
  selected line in cyan, `ON` green, `OFF` red, `ENTER play` green and `BREAK exit` red, a help line for the selected
  option, `Patch: <patch_by>` and ` Engine: Dean Woodyatt` at the bottom. NexClash is not on it. Layout, colours as
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

## Not done

- **The dot command still has the old menu** and writes the bare `.nex`. `menu.asm` is about 1,300 bytes and the part
  before the menu has 1,235 free, with the description to build and the ROM font to copy as well. The way in: read
  `menu.asm` as a part of the command's file into an allocated page, as the tape parts are read, build the description
  there and copy the font with MMU1 paged to the ROM from code in that page. Writing a menu `.nex` from the dot command
  then needs every set decoded into runs and the stub written after the banks. So there is no loader screenshot of the
  new menu to set beside the `.nex` one yet.
- No `HLP1` in any published patch yet: `nxc.py help` makes one.

## For you to decide

- **The main line in a `.nex`** is fixed `[ ON]`: a `.nex` holds the rebuilt game, not the plain one. Carrying the plain
  game for "off" (the bytes `SIT1` and `BNK1` replaced, the start state, a start routine like NexClash's own) is reserved
  in the spec. Wanted?
- **BREAK in a `.nex`** resets the Next, as there is nothing to go back to. All right?
- **The credit wording,** ` Engine: Dean Woodyatt` on the bottom bar, and `Colours: <colours_by>` above `Patch:` when a
  colour set has a colourist.
- **Long publishers** are cut: `Mastertronic Added Dimension, 1985` shows as `Mastertronic Ad`. Shorter `publisher`
  values (`Mastertronic, 1985`) would read better; changing them changes the patches.
- **zx0.** A pure-Python compressor was considered and not written: `zx0`'s optimal parse searches every offset for every
  byte, which in Python would take minutes a bank, and matching its output byte for byte means porting its exact tie
  breaks. It stays an optional dependency for `make`; applying never needs it.

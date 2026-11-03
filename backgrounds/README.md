# Backgrounds: a picture behind a game

An experiment, separate from the `.nxc` format. **It has run in JNext only, on NextZXOS v2.09, not on a Next or a Tang.**

`.BGSHOW` loads a 256 x 192 picture into Layer 2 and makes the game's black see-through, with no patch to the game. It doesn't remove colour clash: it only replaces black.

## What it needs

```sh
python make_picture.py picture            # an example: picture.nxi and picture.png. Needs Pillow
sjasmplus --nologo --raw=BGSHOW bgshow.asm
```

`BGSHOW` goes in `C:/DOT/` and your picture anywhere on the card. A picture is 49,152 raw `RRRGGGBB` bytes, top row first, avoiding the values 0x00 and 0xE3.

It has to run before the game starts, with `-C`. To do that for every snapshot you select in the Browser, change the `Z80,SNA` line of `C:/NEXTZXOS/BROWSER.CFG` to this, keeping a copy of the original (CRLF line endings; `<7F>` is the single byte 0x7F, which the Browser replaces with `c:/nextzxos/`):

```
Z80,SNA:clear 65367:.bgshow -C "c:/pictures/picture.nxi":load "<7F>snapload.bas":f$="|":adj=0:goto 1
```

The snapshot loader's `SPECTRUM` resets the layer order and palette, and a dot command can't run after it, so settings alone don't last. `-C` starts a Copper list, which sets them again every frame.

| Option | What it does |
|---|---|
| `-p` | Only black paper is see-through, and black ink stays solid (default) |
| `-a` | All black is see-through, including outlines and lettering |
| `-c` | Copper list, with NR 0x69 |
| `-C` | Copper list without NR 0x69, which also writes port 7FFD's shadow bit and Timex port FF |
| `-0` | Loads the picture and shows nothing: a control for timing tests |

## What was seen in JNext

- Games with plain black backgrounds look good. Games with dithered scenery look muddy, as the picture shows through the dither.
- Cobra-style games that draw their playfield in black ink don't suit `-p`, and hidden black figures can appear. `-a` lets the picture through the scenery.
- The border isn't covered.
- Screen memory matched a run with no picture at the same frames on four games, so speed looks normal. That isn't a proof of timing.
- `.nexload` stops the Copper, so a sprite `.nex` needs its own start-up code for this.

## Limits

- Banks 45-47 by default, assembled with `-DBANK=n` to change them. A 1MB Next is untested. The Tang's Layer 2 reaches only banks 8-31, so build with `-DBANK=29` there, untested on the machine.
- A Next-aware or unusual game could change these registers itself.
- Selecting a picture at launch is easy. Cycling during play needs a timer or a key handler, which this doesn't do.

## With a patch

Backgrounds in a `.nxc` have a reserved block, `L2B1`, described in [the format](../spec/NXC-FORMAT.md). No tool or loader writes or reads it yet. A build can include its own background today, in its banks and start-up code, and `make` carries that as it is.

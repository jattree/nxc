# Colour standard for .nxc patches

How colours are chosen for every patch, so that a painter's "dark red" is the same shade in every game.
This is an authoring rule, not part of the file format: the format already holds any colour the Next can
show.

## The master palette: the Next's standard 256 colours

Every colour in a patch is picked from the Next's own default 256-colour palette: each index is RRRGGGBB,
the colour the Next shows for that index after a reset. It is the palette Next art tools and artists
already know, and it costs nothing: the Next looks every colour up in a palette table, so which shades a
patch uses has no effect on speed or memory.

- Colour sheets show the master palette's swatches, so every painter works from the same set.
- Colours from another source, such as a Spec256 conversion, are matched to the nearest master colour.
  The Next shows 512 colours, so they are rounded anyway.
- A shade outside the 256 (one of the Next's other 256) may be used where it matters, and the patch's
  notes say so.

## The default mode keeps the Spectrum's colours

The default mode is the original game's look: the Spectrum's 15 colours (8 normal, 7 bright), as the
Next shows them. All of them are in the master palette. Enhanced colours are always a menu option, off by
default.

## How many colours one figure can use

What costs speed and memory is how many colours a single figure uses, because that decides how it is
drawn:

| Drawn as | Colours per figure | Memory per 16x16 pattern | Upload time |
|---|---|---|---|
| 4-bit hardware sprites (the norm) | 15 + transparent, from the master | 128 bytes | 1x |
| 8-bit hardware sprites | up to 255 | 256 bytes | 2x |
| Layer 2, 256 colours | up to 256 | already 8-bit | no extra |

- 4-bit sprites are the norm: each colour sheet gets 15 colours of the painter's choosing, from the
  master palette.
- A game moves to 8-bit sprites or Layer 2 only when it truly needs more colours per figure and still
  fits the 1MB model (everything, Enhanced included, within a standard Next's memory).
- Layer 2 engines already draw in 256 colours, so the full palette costs them nothing extra.

## Sheet rules

- One PNG pixel is one Spectrum pixel; figures are joined as the game draws them; a row of swatches
  at the top; no text.
- Outlines only where a figure gets lost against the scenery: one pixel, white, or black on a white
  figure; none on bullets and sparks.
- Paint by the figure's drawn parts, never one flat colour or one block colour per figure.

## Existing patches

Patches published before this standard keep their colours: every colour they use is already one the
Next shows. They move to the master palette when they are next updated.

#!/usr/bin/env python3
"""The README's art for .nxc: the title (hero.svg) and the before-and-after board (showcase.svg, rendered to
showcase.png because it holds pictures). Colours are the Spectrum's own on black.
  python3 make_readme_art.py OUT_DIR    (needs rsvg-convert for the PNG)"""
import os
import subprocess
import sys

BLACK, TEXT, MUTED, PANEL = "#000000", "#f4f4ee", "#a3a3a3", "#141414"
RED, YELLOW, CYAN, GREEN = "#ff3b30", "#e8e000", "#00d7d7", "#2fd34a"
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"


def tile(y, label, text, colour, strong=False):
    fill = "#1d1d1d" if strong else PANEL
    return (f'<rect x="716" y="{y}" width="420" height="74" rx="12" fill="{fill}"/>'
            f'<rect x="716" y="{y}" width="8" height="74" rx="4" fill="{colour}"/>'
            f'<text x="744" y="{y + 28}" font-family="{MONO}" font-size="18" fill="{MUTED}" letter-spacing="1.5">{label}</text>'
            f'<text x="744" y="{y + 58}" font-family="{SANS}" font-size="23" fill="{TEXT}"'
            f'{" font-weight=\"600\"" if strong else ""}>{text}</text>')


def hero():
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="380" viewBox="0 0 1200 380" role="img" aria-labelledby="title desc">
  <title id="title">.nxc</title>
  <desc id="desc">.nxc: colour-clash-free Spectrum games for the ZX Spectrum Next, from your own copy of the game. Your game plus the patch, which holds no game data, becomes the game with its clash fixed, on your Next.</desc>
  <rect width="1200" height="380" rx="28" fill="{BLACK}"/>
  <text x="64" y="96" font-family="{MONO}" font-size="18" fill="{CYAN}" letter-spacing="2.4">PATCHES FOR THE ZX SPECTRUM NEXT</text>
  <text x="58" y="222" font-family="{SANS}" font-size="140" font-weight="700" fill="{TEXT}" letter-spacing="-3"><tspan fill="{CYAN}">.</tspan>nxc</text>
  <g font-family="{SANS}" font-size="29" fill="{TEXT}">
    <text x="64" y="282">Colour-clash-free Spectrum games,</text>
    <text x="64" y="320">from your own copy of the game.</text>
  </g>
  {tile(44, "YOUR GAME", "your own .z80, .sna or .tap", YELLOW)}
  <text x="926" y="148" text-anchor="middle" font-family="{SANS}" font-size="26" fill="{MUTED}">+</text>
  {tile(156, "THE PATCH", "a .nxc, with no game in it", CYAN)}
  <text x="926" y="260" text-anchor="middle" font-family="{SANS}" font-size="26" fill="{MUTED}">=</text>
  {tile(268, "ON YOUR NEXT", "the game, clash fixed", GREEN, strong=True)}
</svg>
'''


def showcase():
    panels = [("THE ORIGINAL", RED, "tw-original.png", "Wally takes on the tree's colours"),
              ("WITH ITS .nxc", CYAN, "tw-patched.png", "Wally keeps his own colours"),
              ("WITH ITS ENHANCED COLOURS", YELLOW, "tw-enhanced.png", "Fuller colours, chosen on the menu")]
    parts = []
    for i, (label, colour, picture, caption) in enumerate(panels):
        x = 30 + i * 390
        parts.append(f'<text x="{x}" y="62" font-family="{MONO}" font-size="19" fill="{colour}" letter-spacing="1.6">{label}</text>'
                     f'<image x="{x}" y="80" width="360" height="270" href="{picture}" preserveAspectRatio="none" style="image-rendering:pixelated"/>'
                     f'<text x="{x}" y="388" font-family="{SANS}" font-size="21" fill="{TEXT}">{caption}</text>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="420" viewBox="0 0 1200 420" role="img" aria-labelledby="title desc">
  <title id="title">Three Weeks in Paradise, before and after its .nxc patch</title>
  <desc id="desc">The original game, where Wally turns the colours of the tree he walks past; with its .nxc patch, where he is a Next sprite and keeps his own colours; and with the patch's Enhanced colours.</desc>
  <rect width="1200" height="420" rx="24" fill="{BLACK}"/>
  {"".join(parts)}
</svg>
'''


def main(out):
    src = os.path.dirname(os.path.abspath(__file__))
    open(os.path.join(out, "hero.svg"), "w", encoding="utf-8", newline="\n").write(hero())
    board = os.path.join(src, "showcase.svg")
    open(board, "w", encoding="utf-8", newline="\n").write(showcase())
    subprocess.run(["rsvg-convert", "-w", "1200", board, "-o", os.path.join(out, "showcase.png")], check=True, cwd=src)


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1]))

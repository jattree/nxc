#!/usr/bin/env python3
"""Make an original 256x192 Layer 2 picture: dark sky, stars, ringed planet, horizon.

Writes OUT.nxi (49152 raw RRRGGGBB bytes, one per pixel, top row first) and OUT.png.
Usage: make_picture.py OUT [seed]. Needs Pillow. Avoids 0x00 and 0xE3, the two colours
tried as "transparent".
"""
import math, random, sys
from PIL import Image

W, H = 256, 192
BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]


def quant(rgb, x, y):
    """Ordered-dither a 0..1 float colour to RRRGGGBB."""
    t = (BAYER[y & 3][x & 3] + 0.5) / 16.0
    r = min(7, int(rgb[0] * 7 + t))
    g = min(7, int(rgb[1] * 7 + t))
    b = min(3, int(rgb[2] * 3 + t))
    v = r << 5 | g << 2 | b
    return 0x01 if v in (0x00, 0xE3) else v


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def main():
    out = sys.argv[1]
    rng = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1983)
    top, low = (0.02, 0.02, 0.22), (0.30, 0.10, 0.42)
    horizon = [150 + int(10 * math.sin(x / 23.0) + 6 * math.sin(x / 7.0 + 1)) for x in range(W)]
    stars = {(rng.randrange(W), rng.randrange(140)): rng.random() for _ in range(170)}
    cx, cy, rad = 176, 62, 44
    lx, ly, lz = -0.65, -0.45, 0.61
    pix = bytearray(W * H)
    for y in range(H):
        for x in range(W):
            c = mix(top, low, min(1.0, y / 150.0))
            s = stars.get((x, y))
            if s is not None:
                c = mix(c, (1, 1, 0.9), 0.45 + s * 0.5)
            dx, dy = (x - cx) / rad, (y - cy) / rad
            rr = dx * dx + dy * dy
            # the ring, tilted: the back half behind the planet, the front half over it
            rx = dx * 0.94 + dy * 0.34
            ry = (-dx * 0.34 + dy * 0.94) * 4.2
            q = math.sqrt(rx * rx + ry * ry)
            ring = 1.28 < q < 1.72 and not (1.46 < q < 1.52)
            if rr < 1.0:
                z = math.sqrt(1 - rr)
                lam = max(0.0, dx * lx + dy * ly + z * lz)
                band = 0.5 + 0.5 * math.sin(dy * 15 + 2.5 * math.sin(dx * 3))
                base = mix((0.75, 0.42, 0.18), (0.95, 0.72, 0.42), band)
                c = mix((0.03, 0.02, 0.1), base, 0.08 + 0.92 * lam)
            if ring and (rr >= 1.0 or ry > 0):
                c = mix(c, (0.75, 0.65, 0.5), 0.55)
            if y >= horizon[x]:
                d = (y - horizon[x]) / 40.0
                c = mix((0.16, 0.05, 0.16), (0.04, 0.02, 0.06), min(1.0, d))
                if y == horizon[x]:
                    c = (0.55, 0.22, 0.32)
            pix[y * W + x] = quant(c, x, y)
    open(out + ".nxi", "wb").write(pix)
    img = Image.new("RGB", (W, H))
    img.putdata([((v >> 5) * 255 // 7, ((v >> 2) & 7) * 255 // 7, (v & 3) * 255 // 3) for v in pix])
    img.save(out + ".png")


main()

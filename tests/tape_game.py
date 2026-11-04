"""A made-up game on tape, from bytes made here: nothing in it comes from any game. Its data blocks as a .tap and as a .tzx
holding every kind of TZX block a tape target may have, the .z80 of a start state made from them with a few bytes the tape
does not hold, and a build of it with sites, a start-up bank and an extra bank holding two of its blocks, as a build that
keeps a multiload in memory would."""
from __future__ import annotations

import hashlib
import struct


def noise(label: bytes, size: int) -> bytes:
    out = bytearray()
    n = 0
    while len(out) < size:
        out += hashlib.sha256(label + struct.pack("<I", n)).digest()
        n += 1
    return bytes(out[:size])


def rom_block(flag: int, payload: bytes) -> bytes:
    """A block as the ROM saves it: the flag, the bytes, then the XOR of all of them."""
    x = flag
    for b in payload:
        x ^= b
    return bytes((flag,)) + payload + bytes((x,))


def data_blocks(scale: int = 1) -> list[bytes]:
    """Seven data blocks: a header, a short one, a long code block, data, an empty one, and two level blocks."""
    head = bytes((3,)) + b"tape game " + struct.pack("<HHH", 6000, 0x6000, 0x8000)
    return [rom_block(0, head),
            rom_block(0xFF, noise(b"loader", 200)),
            rom_block(0xFF, noise(b"code", 6000 * scale)),
            rom_block(0xFF, noise(b"data", 3000)),
            b"",
            rom_block(0x81, noise(b"level a", 2000)),
            rom_block(0x82, noise(b"level b", 2500))]


def tap(blocks: list[bytes]) -> bytes:
    return b"".join(struct.pack("<H", len(d)) + d for d in blocks)


def tzx(blocks: list[bytes], before: bytes = b"") -> bytes:
    """The same data blocks as 0x10, 0x11 and 0x14 blocks, between every block a tape target may skip."""
    out = bytearray(b"ZXTape!\x1a\x01\x14") + before
    out += b"\x30" + bytes((9,)) + b"made here"
    out += b"\x32" + struct.pack("<HB", 6, 1) + bytes((0, 3)) + b"Tap"
    out += b"\x35" + b"custom info     " + struct.pack("<I", 5) + b"hello"
    out += b"\x33" + bytes((2,)) + bytes((0, 1, 0, 0, 3, 1))
    std = lambda d: b"\x10" + struct.pack("<HH", 1000, len(d)) + d
    turbo = lambda d: b"\x11" + struct.pack("<HHHHHHBH", 2168, 667, 735, 855, 1710, 3223, 8, 1000) + len(d).to_bytes(3, "little") + d
    pure = lambda d: b"\x14" + struct.pack("<HHBH", 855, 1710, 6, 0) + len(d).to_bytes(3, "little") + d
    out += std(blocks[0]) + b"\x20" + struct.pack("<H", 0)
    out += b"\x21" + bytes((4,)) + b"code" + turbo(blocks[1]) + std(blocks[2]) + b"\x22"
    out += b"\x12" + struct.pack("<HH", 2168, 3223) + b"\x13" + bytes((2,)) + struct.pack("<HH", 667, 735) + pure(blocks[3])
    out += b"\x15" + struct.pack("<HHB", 79, 0, 8) + (40).to_bytes(3, "little") + noise(b"samples", 40)
    out += b"\x18" + struct.pack("<I", 12) + noise(b"csw", 12) + b"\x19" + struct.pack("<I", 20) + noise(b"generalised", 20)
    out += std(blocks[4]) + b"\x2b" + struct.pack("<IB", 1, 1) + b"\x31" + bytes((5, 3)) + b"hi!"
    out += b"\x24" + struct.pack("<H", 1) + std(blocks[5]) + b"\x25" + b"\x5a" + b"XTape!\x1a\x01\x14"
    out += b"\x28" + struct.pack("<HB", 4, 1) + struct.pack("<hB", 1, 0) + b"\x23" + struct.pack("<h", 1)
    out += b"\x26" + struct.pack("<Hh", 1, 2) + std(blocks[6]) + b"\x27" + b"\x2a" + struct.pack("<I", 0)
    return bytes(out)


def start_banks(blocks: list[bytes], is128: bool = True) -> dict[int, bytes]:
    """The game's memory when the build starts: its blocks where its loader left them, the code block moved in two parts,
    and a few bytes its code made (a screen line, a table, variables) that no block holds."""
    banks = {b: bytearray(16384) for b in (range(8) if is128 else (5, 2, 0))}
    banks[5][0:256] = noise(b"a screen line", 256)
    banks[5][0x1F00:0x1F00 + 4000] = blocks[2][1:4001]
    banks[2][0:1999] = blocks[2][4001:6000]
    banks[2][0x2000:0x2000 + 3000] = blocks[3][1:3001]
    banks[2][0x3000:0x3000 + 100] = noise(b"a table", 100)
    banks[0][0:2000] = blocks[5][1:2001]
    banks[0][0x3F00:0x3F20] = noise(b"variables", 32)
    if is128:
        banks[3][0x100:0x100 + 2500] = blocks[6][1:2501]
        banks[7][0:200] = blocks[1][1:201]
    return {b: bytes(v) for b, v in banks.items()}


def pack(data: bytes) -> bytes:
    """.z80 page packing: ED ED n v for a run, an ED alone taking the byte after it with it."""
    out = bytearray()
    i = 0
    while i < len(data):
        n = 1
        while i + n < len(data) and data[i + n] == data[i] and n < 255:
            n += 1
        if n >= 5 or (data[i] == 0xED and n >= 2):
            out += bytes((0xED, 0xED, n, data[i]))
            i += n
        elif data[i] == 0xED:
            out += data[i:i + 2]
            i += 2
        else:
            out.append(data[i])
            i += 1
    return bytes(out)


def start_z80(banks: dict[int, bytes], packed: bool = False) -> bytes:
    """A .z80 version 3, 128K or 48K by its banks, every page stored whole, or packed."""
    is128 = len(banks) == 8
    h = bytearray(noise(b"registers", 30))
    h[6:8] = b"\0\0"
    h[12] = 0x0A
    h[29] = 0x41
    ext = bytearray(54)
    ext[0:2] = struct.pack("<H", 0x6000)
    ext[2] = 4 if is128 else 0
    ext[3] = 0x13 if is128 else 0
    ext[5] = 4 if is128 else 0
    ext[6] = 7
    ext[7:23] = noise(b"ay", 16)
    out = bytes(h) + struct.pack("<H", 54) + bytes(ext)
    pages = [(3 + b, b) for b in range(8)] if is128 else [(8, 5), (4, 2), (5, 0)]
    for page, b in pages:
        body = pack(banks[b]) if packed else banks[b]
        out += (struct.pack("<H", len(body)) if packed else b"\xff\xff") + bytes((page,)) + body
    return out


def build(banks: dict[int, bytes], blocks: list[bytes], order) -> tuple[bytes, list[int]]:
    """The .nex: the start's banks with hooks in banks 5 and 2, start-up code in bank 10, and in bank 20 both level blocks
    with a few bytes of the engine's. Returns it and the extra banks taken from the tape."""
    out = dict(banks)
    five = bytearray(out[5])
    five[0x1F10:0x1F18] = noise(b"a hook", 8)
    out[5] = bytes(five)
    two = bytearray(out[2])
    two[0x2100:0x2103] = b"\xc3\x00\xc0"
    out[2] = bytes(two)
    out[10] = noise(b"start-up", 400).ljust(16384, b"\0")
    extra = bytearray(16384)
    extra[0:2000] = blocks[5][1:2001]
    extra[0x1000:0x1000 + 2500] = blocks[6][1:2501]
    extra[0x3F00:0x3F10] = noise(b"engine", 16)
    out[20] = bytes(extra)
    head = bytearray(512)
    head[0:8] = b"NextV1.2"
    head[9] = len(out)
    head[14:16] = struct.pack("<H", 0xC000)
    head[139] = 10
    for b in out:
        head[18 + b] = 1
    return bytes(head) + b"".join(out[b] for b in order if b in out), [20]

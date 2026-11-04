#!/usr/bin/env python3
"""Writes the test vectors in this folder, from bytes made here: nothing in them comes from any game. The same output every
time, from fixed bytes standing in for the fresh random key and nonce. Needs the zx0 compressor; checking them does not.

    python tests/vectors/make_vectors.py
"""
import hashlib, json, os, struct, sys, tempfile, zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "tools"))
import nxc  # noqa: E402

NONCE = bytes(range(0x10, 0x20))
MASTER = bytes(range(0xA0, 0xB0))


def noise(label: bytes, size: int) -> bytes:
    out = bytearray()
    n = 0
    while len(out) < size:
        out += hashlib.sha256(label + struct.pack("<I", n)).digest()
        n += 1
    return bytes(out[:size])


def banks() -> dict:
    """Mostly empty, with some noise, so that the files stay small."""
    made = {}
    for bank in (5, 2, 0):
        data = bytearray(16384)
        data[100:300] = noise(b"bank %d" % bank, 200)
        data[8000:8040] = bytes((0xED,)) * 40
        made[bank] = bytes(data)
    return made


def pack(data: bytes) -> bytes:
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


def header(pc: int, flags: int) -> bytearray:
    h = bytearray(noise(b"registers", 30))
    h[6:8] = struct.pack("<H", pc)
    h[12] = flags
    return h


def z80_v1(b) -> bytes:
    return bytes(header(0x8000, 0x20)) + pack(b[5] + b[2] + b[0]) + b"\0\xed\xed\0"


def z80_v3(b) -> bytes:
    ext = bytearray(54)
    ext[0:2] = struct.pack("<H", 0x8000)
    out = bytes(header(0, 0)) + struct.pack("<H", 54) + bytes(ext)
    for page, bank in ((4, 2), (5, 0), (8, 5)):
        body = pack(b[bank])
        out += struct.pack("<HB", len(body), page) + body
    return out


def sna(b) -> bytes:
    return bytes(noise(b"registers", 27)) + b[5] + b[2] + b[0]


def state_hex(state) -> dict:
    return dict(s=bytes(state[0]).hex(), i=state[1], j=state[2])


def main() -> None:
    b = banks()
    v3, v1, s = z80_v3(b), z80_v1(b), sna(b)
    (HERE / "game_v3.z80").write_bytes(v3)
    (HERE / "game_v1.z80").write_bytes(v1)
    out = dict(b)
    five = bytearray(out[5])
    five[200:216] = noise(b"a hook", 16)
    out[5] = bytes(five)
    out[10] = noise(b"start-up", 400).ljust(16384, b"\0")
    head = bytearray(512)
    head[0:8] = b"NextV1.2"
    head[9] = len(out)
    head[10] = 2                                     # a ULA screen
    head[14:16] = struct.pack("<H", 0xC000)
    for bank in out:
        head[18 + bank] = 1
    screen = (noise(b"a screen", 64) + bytes(6912))[:6912]
    nex = bytes(head) + screen + b"".join(out[bank] for bank in nxc.ORDER if bank in out)
    painted = bytearray(nex)
    painted[512 + 6912 + 16384 + 3] ^= 0xFF
    spoken = bytearray(nex)
    spoken[512 + 6912 + 16384 + 40:512 + 6912 + 16384 + 44] = b"Text"
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "game_v3.z80").write_bytes(v3)
        (tmp / "game_v1.z80").write_bytes(v1)
        (tmp / "game.sna").write_bytes(s)
        (tmp / "o.nex").write_bytes(nex)
        (tmp / "p.nex").write_bytes(bytes(painted))
        (tmp / "l.nex").write_bytes(bytes(spoken))
        patch, _ = nxc.make(str(tmp / "game_v3.z80"), str(tmp / "o.nex"), dict(title="Vector", file="game_v3.z80", zxdb_entry="0000000"),
                            dict(publisher="Nobody, 2026", patch_by="Vector", build="synthetic"), nonce=NONCE, master=MASTER, rom=1,
                            proof=dict(replay="none: synthetic", hardware="none", hardware_when="2026-11-03"), colours={"Painted": str(tmp / "p.nex")}, languages={"Vector": str(tmp / "l.nex")},
                            trainer_blocks=[nxc.trn1("Lives", [(2, 16000, 0xAB)])],
                            more_dumps=[(str(tmp / "game_v1.z80"), dict(file="game_v1.z80")), (str(tmp / "game.sna"), dict(file="game.sna"))])
    (HERE / "vector.nxc").write_bytes(patch)
    master = nxc.key_state(NONCE, MASTER).base
    uses = []
    def show(base_name, base, tag, index, plain=None):
        st = [list(base[0]), base[1], base[2]]
        nxc.absorb(st, tag + bytes((index,)))
        absorbed = state_hex(st)
        nxc.Stream.output(st, bytes(nxc.DROP))
        dropped = state_hex(st)
        first = nxc.Stream.output(st, bytes(32)).hex()
        uses.append(dict(base=base_name, tag=tag.decode(), index=index, after_absorbing=absorbed, after_dropping=dropped, first_output=first))
    dumps = {"game_v3.z80": nxc.dump_state(NONCE, v3).base, "game_v1.z80": nxc.dump_state(NONCE, v1).base, "game.sna": nxc.dump_state(NONCE, s).base}
    for n, (name, base) in enumerate(dumps.items()):
        show(name, base, b"TGT1", n)
    for tag, index in ((b"OUT1", 0), (b"NEX1", 0), (b"SIT1", 0), (b"BNK1", 10), (b"SCR1", 0), (b"SEB\0", 255), (b"SEB\0", 5), (b"SEB\1", 255), (b"SEB\1", 5)):
        show("master", master, tag, index)
    st = [list(master[0]), master[1], master[2]]
    nxc.absorb(st, b"CHK1\0")
    start = state_hex(st)
    nxc.absorb(st, patch[:22])
    nxc.absorb(st, patch[38:])
    absorbed = state_hex(st)
    nxc.Stream.output(st, bytes(nxc.DROP))
    dropped = state_hex(st)
    value = nxc.Stream.output(st, bytes(16)).hex()
    layout = []
    at = nxc.HEADER
    for tag, data in nxc.blocks(patch)[1]:
        layout.append(dict(tag=tag.decode(), data_offset=at + 8, length=len(data)))
        at += 8 + len(data)
    k = nxc.key_state(NONCE, MASTER)
    plain = {}
    d = dict(nxc.blocks(patch)[1])
    plain["OUT1"] = k.block(b"OUT1")(d[b"OUT1"]).hex()
    plain["NEX1 packed"] = k.block(b"NEX1")(d[b"NEX1"]).hex()
    plain["SIT1 table"] = nxc.unzx0(k.block(b"SIT1")(d[b"SIT1"]), nxc.SITE_TABLE_MAX).hex()
    for e in nxc.sets(patch):
        crc, chunks = nxc.read_set(k, e)
        plain["SET2 stream %d crc" % e["stream"]] = "%08x" % crc
        for bank, chunk in chunks:
            plain["SET2 stream %d bank %d chunk" % (e["stream"], bank)] = chunk.hex()
    plain["SCR1 piece 0"] = nxc.unzx0(k.block(b"SCR1", 0)(d[b"SCR1"][3:]), 6912).hex()
    plain["BNK1 bank 10"] = nxc.unzx0(k.block(b"BNK1", 10)(d[b"BNK1"][3:]), 400).hex()
    def digest(data):
        return dict(length=len(data), crc32="%08x" % zlib.crc32(data), md5=hashlib.md5(data).hexdigest())
    expected = {"base": digest(nxc.apply(patch, game=v3)), "colours": digest(nxc.apply(patch, game=v3, colours="Painted")), "language": digest(nxc.apply(patch, game=v3, language="Vector")),
                "colours and language": digest(nxc.apply(patch, game=v3, colours="Painted", language="Vector")),
                "trainer": digest(nxc.apply(patch, game=v3, chosen=[1])), "colours and trainer": digest(nxc.apply(patch, game=v3, colours="Painted", chosen=[1])),
                "fix off with a trainer, v3": digest(nxc.original_with_pokes(patch, v3, [1])), "fix off with a trainer, v1": digest(nxc.original_with_pokes(patch, v1, [1])),
                "fix off with a trainer, sna": digest(nxc.original_with_pokes(patch, s, [1]))}
    bad = [dict(name=n, offset=o, xor=x) for n, o, x in (
        ("a clear trainer value", patch.index(b"Lives") + 5 + 1 + 3, 0x55), ("a clear title", patch.index(b"title=") + 6, 0x01), ("the nonce", 6, 0x01),
        ("the check value", 22, 0x01), ("a key wrap", layout[1]["data_offset"] + 6, 0x01), ("the header flags", 5, 0x80), ("OUT1", next(e["data_offset"] for e in layout if e["tag"] == "OUT1"), 0x01))]
    vectors = dict(comment="Made by make_vectors.py from synthetic bytes. Nothing here comes from any game.",
                   crc32=dict(text="123456789", value="cbf43926"), nonce=NONCE.hex(), master_key=MASTER.hex(), patch_md5=hashlib.md5(patch).hexdigest(),
                   sna_file=dict(made_by="make_vectors.sna", md5=hashlib.md5(s).hexdigest(), length=len(s)),
                   key_base=state_hex(master), dump_bases={n: state_hex(b_) for n, b_ in dumps.items()}, uses=uses,
                   check=dict(after_tag_and_index=start, after_the_file=absorbed, after_dropping=dropped, value=value),
                   layout=layout, plaintext=plain, expected=expected, refused=bad)
    (HERE / "vectors.json").write_text(json.dumps(vectors, indent=1) + "\n")
    print("patch", len(patch), "bytes; vectors", (HERE / "vectors.json").stat().st_size, "bytes")


if __name__ == "__main__":
    main()

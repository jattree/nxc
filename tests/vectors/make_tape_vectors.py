#!/usr/bin/env python3
"""Writes the tape vectors in this folder, from the made-up game in tests/tape_game.py: nothing in them comes from any game.
The same output every time, from fixed bytes standing in for the fresh random key and nonce. Needs the zx0 compressor;
checking them does not.

    python tests/vectors/make_tape_vectors.py
"""
import hashlib, json, sys, tempfile, zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "tools"))
sys.path.insert(0, str(HERE.parent))
import nxc  # noqa: E402
import tape_game as G  # noqa: E402

NONCE = bytes(range(0x30, 0x40))
MASTER = bytes(range(0xC0, 0xD0))


def state_hex(state) -> dict:
    return dict(s=bytes(state[0]).hex(), i=state[1], j=state[2])


def digest(data):
    return dict(length=len(data), crc32="%08x" % zlib.crc32(data), md5=hashlib.md5(data).hexdigest())


def main() -> None:
    blocks = G.data_blocks()
    banks = G.start_banks(blocks)
    tap, tzx, z80 = G.tap(blocks), G.tzx(blocks), G.start_z80(banks, packed=True)
    nex, extra = G.build(banks, blocks, nxc.ORDER)
    (HERE / "tape.tap").write_bytes(tap)
    (HERE / "tape.tzx").write_bytes(tzx)
    (HERE / "tape_start.z80").write_bytes(z80)
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        (tmp / "tape.tap").write_bytes(tap)
        (tmp / "tape_start.z80").write_bytes(z80)
        (tmp / "o.nex").write_bytes(nex)
        patch, _ = nxc.make(str(tmp / "tape.tap"), str(tmp / "o.nex"), dict(title="Tape Vector", file="tape.tap"),
                            dict(publisher="Nobody, 2026", patch_by="Vector", build="synthetic"), nonce=NONCE, master=MASTER, rom=1,
                            proof=dict(replay="none: synthetic", hardware="none", hardware_when="2026-11-03"),
                            trainer_blocks=[nxc.trn1("Lives", [(2, 0x2010, 0xAB)])], start=str(tmp / "tape_start.z80"), tape_banks=extra)
    patch = nxc.add_target(patch, tap, tzx, nxc.KIND_TZX, dict(file="tape.tzx"))
    (HERE / "vector_tape.nxc").write_bytes(patch)
    master = nxc.key_state(NONCE, MASTER).base
    uses = []
    def show(base_name, base, tag, index):
        st = [list(base[0]), base[1], base[2]]
        nxc.absorb(st, tag + bytes((index,)))
        absorbed = state_hex(st)
        nxc.Stream.output(st, bytes(nxc.DROP))
        dropped = state_hex(st)
        uses.append(dict(base=base_name, tag=tag.decode(), index=index, after_absorbing=absorbed, after_dropping=dropped,
                         first_output=nxc.Stream.output(st, bytes(32)).hex()))
    dumps = {"tape.tap": nxc.dump_state(NONCE, tap).base, "tape.tzx": nxc.dump_state(NONCE, tzx).base}
    for n, (name, base) in enumerate(dumps.items()):
        show(name, base, b"TGT1", n)
    show("master", master, b"TAP1", 0)
    layout = []
    at = nxc.HEADER
    for tag, data in nxc.blocks(patch)[1]:
        layout.append(dict(tag=tag.decode(), data_offset=at + 8, length=len(data)))
        at += 8 + len(data)
    k = nxc.key_state(NONCE, MASTER)
    head = dict(nxc.blocks(patch)[1])[b"TAP1"]
    e = nxc.parse_tap1(head)
    packed = k.block(b"TAP1", e["stream"])(e["data"])
    table = nxc.unzx0(packed, nxc.TAPE_TABLE_MAX)
    parts = nxc.parse_tape_table(table, nxc.tape_blocks(tap, nxc.KIND_TAP))
    plain = {"TAP1 head": head[:nxc.TAPE_FIXED + len(e["targets"])].hex(), "TAP1 packed": packed.hex(), "TAP1 table": table.hex(),
             "start header": parts["header"].hex(), "start crc32": "%08x" % parts["crc"],
             "copies": [list(c) for c in parts["copies"]], "sites": [[b, o, d.hex()] for b, o, d in parts["sites"]]}
    expected = {"base from the tap": digest(nxc.apply(patch, game=tap)), "base from the tzx": digest(nxc.apply(patch, game=tzx)),
                "trainer": digest(nxc.apply(patch, game=tzx, chosen=[1])),
                "fix off": digest(nxc.original_with_pokes(patch, tap, [])), "fix off from the tzx": digest(nxc.original_with_pokes(patch, tzx, [])),
                "fix off with a trainer": digest(nxc.original_with_pokes(patch, tap, [1]))}
    tap1 = next(x["data_offset"] for x in layout if x["tag"] == "TAP1")
    bad = [dict(name=n, offset=o, xor=x) for n, o, x in (("the TAP1 stream index", tap1, 0x01), ("a TAP1 target", tap1 + 2, 0x01),
                                                         ("the TAP1 count", tap1 + 1, 0x02), ("the TAP1 table", tap1 + 9, 0x10), ("the tape flag", next(x["data_offset"] for x in layout if x["tag"] == "OPT1") + 1, 0x01))]
    vectors = dict(comment="Made by make_tape_vectors.py from synthetic bytes. Nothing here comes from any game.",
                   nonce=NONCE.hex(), master_key=MASTER.hex(), patch_md5=hashlib.md5(patch).hexdigest(),
                   files={n: dict(md5=hashlib.md5(d).hexdigest(), length=len(d)) for n, d in (("tape.tap", tap), ("tape.tzx", tzx), ("tape_start.z80", z80))},
                   data_blocks={"tape.tap": [list(b) for b in nxc.tape_blocks(tap, nxc.KIND_TAP)], "tape.tzx": [list(b) for b in nxc.tape_blocks(tzx, nxc.KIND_TZX)]},
                   key_base=state_hex(master), dump_bases={n: state_hex(b_) for n, b_ in dumps.items()}, uses=uses, layout=layout,
                   plaintext=plain, expected=expected, refused=bad)
    (HERE / "vectors_tape.json").write_text(json.dumps(vectors, indent=1) + "\n")
    print("patch", len(patch), "bytes; vectors", (HERE / "vectors_tape.json").stat().st_size, "bytes")
    tape_set(blocks, banks, nex, extra, z80)
    toggle(blocks, nex, extra, z80, tap)


def tzx10(blocks) -> bytes:
    out = bytearray(nxc.TZX_MAGIC + bytes((1, 20))) + b"\x30\x06side b"
    for d in blocks:
        out += b"\x10" + (1000).to_bytes(2, "little") + len(d).to_bytes(2, "little") + d
    return bytes(out)


def tape_set(blocks, banks, nex, extra, z80) -> None:
    """The same game as a set of two files: side A a .tap of its first five blocks, side B a .tzx of the rest."""
    a, b = G.tap(blocks[:5]), tzx10(blocks[5:])
    (HERE / "tapeset_a.tap").write_bytes(a)
    (HERE / "tapeset_b.tzx").write_bytes(b)
    game = nxc.FileSet([a, b], [nxc.KIND_TAP, nxc.KIND_TZX])
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for n, data in (("tapeset_a.tap", a), ("tapeset_b.tzx", b), ("tape_start.z80", z80), ("o.nex", nex)): (tmp / n).write_bytes(data)
        patch, _ = nxc.make([str(tmp / "tapeset_a.tap"), str(tmp / "tapeset_b.tzx")], str(tmp / "o.nex"),
                            dict(title="Tape Set Vector", file=["tapeset_a.tap", "tapeset_b.tzx"]),
                            dict(publisher="Nobody, 2026", patch_by="Vector", build="synthetic"), nonce=NONCE, master=MASTER, rom=1,
                            proof=dict(replay="none: synthetic", hardware="none"), start=str(tmp / "tape_start.z80"), tape_banks=extra)
    (HERE / "vector_tapeset.nxc").write_bytes(patch)
    k = nxc.key_state(NONCE, MASTER)
    e = nxc.parse_tap1(dict(nxc.blocks(patch)[1])[b"TAP1"])
    table = nxc.unzx0(k.block(b"TAP1", e["stream"])(e["data"]), nxc.TAPE_TABLE_MAX)
    parts = nxc.parse_tape_table(table, (game, nxc.KIND_TAP))
    vectors = dict(comment="Made by make_tape_vectors.py from synthetic bytes: one target of two tape files. Nothing here comes from any game.",
                   nonce=NONCE.hex(), master_key=MASTER.hex(), patch_md5=hashlib.md5(patch).hexdigest(),
                   files={n: dict(md5=hashlib.md5(x).hexdigest(), length=len(x)) for n, x in (("tapeset_a.tap", a), ("tapeset_b.tzx", b))},
                   target_head=dict(nxc.blocks(patch)[1])[b"TGT1"][:36].hex(),
                   dump_base=state_hex(nxc.dump_state(NONCE, a + b).base),
                   data_blocks={"tapeset_a.tap": [list(x) for x in nxc.tape_blocks(a, nxc.KIND_TAP)],
                                "tapeset_b.tzx": [list(x) for x in nxc.tape_blocks(b, nxc.KIND_TZX)]},
                   copies=[list(c) for c in parts["copies"]], table=table.hex(),
                   expected={"base": digest(nxc.apply(patch, game=game)), "fix off": digest(nxc.original_with_pokes(patch, game, []))})
    (HERE / "vectors_tapeset.json").write_text(json.dumps(vectors, indent=1) + "\n")
    print("set patch", len(patch), "bytes")


def toggle(blocks, nex, extra, z80, tap) -> None:
    """The tape patch with one display toggle (kind 3), writing three bytes of bank 2."""
    on = bytearray(nex)
    for o, v in ((0x2100, 0x11), (0x2101, 0x22), (0x2180, 0x33)):
        on[512 + 16384 + o] = v
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        for n, data in (("tape.tap", tap), ("tape_start.z80", z80), ("o.nex", nex), ("t.nex", bytes(on))): (tmp / n).write_bytes(data)
        patch, _ = nxc.make(str(tmp / "tape.tap"), str(tmp / "o.nex"), dict(title="Toggle Vector", file="tape.tap"),
                            dict(publisher="Nobody, 2026", build="synthetic"), nonce=NONCE, master=MASTER, rom=1,
                            proof=dict(replay="none: synthetic", hardware="none"), start=str(tmp / "tape_start.z80"), tape_banks=extra,
                            toggles={"Smooth scrolling": (str(tmp / "t.nex"), False)})
    (HERE / "vector_toggle.nxc").write_bytes(patch)
    e = next(x for x in nxc.sets(patch) if x["kind"] == nxc.KIND_TOGGLE)
    st = nxc.key_state(NONCE, MASTER)
    crc, chunks = nxc.read_set(st, e)
    vectors = dict(comment="Made by make_tape_vectors.py from synthetic bytes: a toggle. Nothing here comes from any game.",
                   patch_md5=hashlib.md5(patch).hexdigest(), set_head=dict(stream=e["stream"], kind=e["kind"], choice=e["choice"],
                   base=e["base"], name=e["name"].decode()), crc_alone="%08x" % crc, chunks=[[b, c.hex()] for b, c in chunks],
                   expected={"off": digest(nxc.apply(patch, game=tap)), "on": digest(nxc.apply(patch, game=tap, toggles=["Smooth scrolling"]))})
    (HERE / "vectors_toggle.json").write_text(json.dumps(vectors, indent=1) + "\n")
    print("toggle patch", len(patch), "bytes")


if __name__ == "__main__":
    main()

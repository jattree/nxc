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


if __name__ == "__main__":
    main()

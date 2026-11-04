"""The vectors in tests/vectors, made only from synthetic bytes, against the tool and against the definition in the spec, which
is run as it stands. Needs no game. The tool's part needs NexClash's snapshot reader, the spec's part nothing."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import struct
import sys
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VECTORS = ROOT / "tests" / "vectors"
SPEC = ROOT / "spec" / "NXC-FORMAT.md"
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("NXC_ZX0_DIR", str(ROOT / "build" / "evidence" / "format-study" / "zx0bin"))
try:
    import nxc
except ImportError:
    nxc = None


def spec_code() -> dict:
    """The spec's python block, run as written."""
    text = SPEC.read_text()
    blocks = re.findall(r"```python\n(.*?)```", text, re.S)
    assert len(blocks) == 1, "the spec must define the streams in one python block"
    space: dict = {}
    exec(blocks[0], space)
    return space


def load():
    vector = json.loads((VECTORS / "vectors.json").read_text())
    return vector, (VECTORS / "vector.nxc").read_bytes(), (VECTORS / "game_v3.z80").read_bytes(), (VECTORS / "game_v1.z80").read_bytes()


def hexstate(state) -> dict:
    return dict(s=bytes(state[0]).hex(), i=state[1], j=state[2])


class SpecAgainstVectors(unittest.TestCase):
    """What an implementer reading only the spec would get."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = spec_code()
        cls.v, cls.patch, cls.v3, cls.v1 = load()
        cls.nonce = bytes.fromhex(cls.v["nonce"])
        cls.master = bytes.fromhex(cls.v["master_key"])

    def test_crc(self) -> None:
        self.assertEqual("%08x" % zlib.crc32(self.v["crc32"]["text"].encode()), self.v["crc32"]["value"])
        self.assertIn(self.v["crc32"]["value"], SPEC.read_text())

    def test_the_patch_is_the_one_the_vectors_describe(self) -> None:
        self.assertEqual(hashlib.md5(self.patch).hexdigest(), self.v["patch_md5"])
        self.assertEqual(self.patch[:4], b"NXC1")
        self.assertEqual(self.patch[6:22], self.nonce)

    def test_key_and_dump_bases(self) -> None:
        self.assertEqual(hexstate(self.spec["key_base"](self.nonce, self.master)), self.v["key_base"])
        self.assertEqual(hexstate(self.spec["dump_base"](self.nonce, self.v3)), self.v["dump_bases"]["game_v3.z80"])
        self.assertEqual(hexstate(self.spec["dump_base"](self.nonce, self.v1)), self.v["dump_bases"]["game_v1.z80"])

    def test_every_use(self) -> None:
        s = self.spec
        for u in self.v["uses"]:
            with self.subTest(tag=u["tag"], base=u["base"]):
                base = s["key_base"](self.nonce, self.master) if u["base"] == "master" else {"state": None}
                if u["base"] != "master":
                    raw = self.v["dump_bases"][u["base"]]
                    base = [list(bytes.fromhex(raw["s"])), raw["i"], raw["j"]]
                tag = u["tag"].encode()
                state = s["use"](base, tag, u["index"])
                self.assertEqual(hexstate(state), u["after_absorbing"])
                state = s["stream"](base, tag, u["index"])
                self.assertEqual(hexstate(state), u["after_dropping"])
                self.assertEqual(s["output"](state, 32).hex(), u["first_output"])

    def test_the_check_value(self) -> None:
        base = self.spec["key_base"](self.nonce, self.master)
        self.assertEqual(self.spec["check_value"](self.patch, base).hex(), self.v["check"]["value"])
        self.assertEqual(self.patch[22:38].hex(), self.v["check"]["value"])

    def test_the_layout_as_the_spec_describes_it(self) -> None:
        at = 38
        for e in self.v["layout"]:
            self.assertEqual(self.patch[at:at + 4].decode(), e["tag"])
            self.assertEqual(int.from_bytes(self.patch[at + 4:at + 8], "little"), e["length"])
            self.assertEqual(at + 8, e["data_offset"])
            at += 8 + e["length"]
        self.assertEqual(at, len(self.patch))

    def test_a_key_wrap_as_the_spec_describes_it(self) -> None:
        s = self.spec
        at = next(e for e in self.v["layout"] if e["tag"] == "TGT1")["data_offset"]
        base = s["dump_base"](self.nonce, self.v3)
        state = s["stream"](base, b"TGT1", 0)
        wrap = self.patch[at + 6:at + 30]
        plain = bytes(a ^ b for a, b in zip(wrap, s["output"](state, 24)))
        self.assertEqual(plain, b"NXC1-KEY" + self.master)

    def test_out1_as_the_spec_describes_it(self) -> None:
        s = self.spec
        e = next(e for e in self.v["layout"] if e["tag"] == "OUT1")
        state = s["stream"](s["key_base"](self.nonce, self.master), b"OUT1", 0)
        plain = bytes(a ^ b for a, b in zip(self.patch[e["data_offset"]:e["data_offset"] + 8], s["output"](state, 8)))
        self.assertEqual(plain.hex(), self.v["plaintext"]["OUT1"])
        self.assertEqual(int.from_bytes(plain[:4], "little"), int(self.v["expected"]["base"]["crc32"], 16))
        self.assertEqual(int.from_bytes(plain[4:], "little"), self.v["expected"]["base"]["length"])

    def test_the_spec_names_its_blocks_and_reservations(self) -> None:
        text = SPEC.read_text()
        for tag in {e["tag"] for e in self.v["layout"]} | {"CHK1", "TAP1", "BUN1", "CAC1", "TRN2", "L2B1", "MNU1", "SNP1", "MEM1", "SPR2"}:
            self.assertIn(f"`{tag}`", text, tag)
        for claim in ("By Jon Attree. Inspired by Bleugh.biz's nexclash, by Dean Woodyatt.", "not cryptographic strength",
                      "can recover the master key", "Sprite data is derived from the game's graphics", "A set can change how a game starts"):
            self.assertIn(claim, text)
        for gone in ("meaningless", "none of the game itself", "so it cannot change how the game starts", "This will change before release"):
            self.assertNotIn(gone, text)

    def test_nothing_in_the_folder_is_large_or_named_for_a_game(self) -> None:
        for path in VECTORS.iterdir():
            if path.is_file():
                self.assertLess(path.stat().st_size, 200_000, path.name)
        self.assertEqual(sorted(p.name for p in VECTORS.iterdir() if p.is_file()),
                         ["game_v1.z80", "game_v3.z80", "make_tape_vectors.py", "make_vectors.py", "tape.tap", "tape.tzx", "tape_start.z80",
                          "vector.nxc", "vector_tape.nxc", "vectors.json", "vectors_tape.json"])


# A tape walker and bank builder written from the spec's words and tables alone, with nothing from the tool.
TZX_DATA = {0x10: (4, 2, 2), 0x11: (18, 15, 3), 0x14: (10, 7, 3)}
TZX_SKIP = {0x12: (4, 0, 0), 0x13: (1, 1, 2), 0x15: (8, 3, 1), 0x18: (4, 4, 1), 0x19: (4, 4, 1), 0x2A: (4, 4, 1), 0x2B: (4, 4, 1), 0x20: (2, 0, 0),
            0x23: (2, 0, 0), 0x24: (2, 0, 0), 0x21: (1, 1, 1), 0x30: (1, 1, 1), 0x22: (0, 0, 0), 0x25: (0, 0, 0), 0x27: (0, 0, 0), 0x26: (2, 2, 2),
            0x28: (2, 2, 1), 0x32: (2, 2, 1), 0x31: (2, 1, 1), 0x33: (1, 1, 3), 0x35: (20, 4, 1), 0x5A: (9, 0, 0)}
COUNT_AT = {0x15: 5, 0x31: 1, 0x35: 16}
NEX_ORDER = [5, 2, 0, 1, 3, 4, 6, 7] + list(range(8, 112))


def spec_data_blocks(tape: bytes, tzx: bool) -> list:
    out, i = [], 0
    if not tzx:
        while i < len(tape):
            n = int.from_bytes(tape[i:i + 2], "little")
            out.append((i + 2, n))
            i += 2 + n
        return out
    assert tape[:8] == b"ZXTape!\x1a" and tape[8] == 1
    i = 10
    while i < len(tape):
        bid = tape[i]
        i += 1
        if bid in TZX_DATA:
            head, at, size = TZX_DATA[bid]
            n = int.from_bytes(tape[i + at:i + at + size], "little")
            out.append((i + head, n))
            i += head + n
        else:
            head, size, unit = TZX_SKIP[bid]
            at = COUNT_AT.get(bid, 0)
            i += head + int.from_bytes(tape[i + at:i + at + size], "little") * unit
    return out


def spec_start_snapshot(tape: bytes, tzx: bool, table: bytes) -> bytes:
    """The clash fix off's .z80, built from the table as the spec says."""
    blocks = spec_data_blocks(tape, tzx)
    header, i = table[:55], 59
    is128 = header[34] == 3
    banks = {b: bytearray(16384) for b in (range(8) if is128 else (5, 2, 0))}
    count, i = int.from_bytes(table[i:i + 2], "little"), i + 2
    for _ in range(count):
        k, s, n = int.from_bytes(table[i:i + 2], "little"), int.from_bytes(table[i + 2:i + 5], "little"), int.from_bytes(table[i + 5:i + 7], "little")
        b, o = table[i + 7], int.from_bytes(table[i + 8:i + 10], "little")
        start = blocks[k][0] + s
        banks.setdefault(b, bytearray(16384))[o:o + n] = tape[start:start + n]
        i += 10
    count, i = int.from_bytes(table[i:i + 2], "little"), i + 2
    for _ in range(count):
        b, o, n = table[i], int.from_bytes(table[i + 1:i + 3], "little"), int.from_bytes(table[i + 3:i + 5], "little")
        banks.setdefault(b, bytearray(16384))[o:o + n] = table[i + 5:i + 5 + n]
        i += 5 + n
    assert i == len(table)
    pages = [(3 + b, b) for b in range(8)] if is128 else [(8, 5), (4, 2), (5, 0)]
    return header + b"".join(b"\xff\xff" + bytes((p,)) + bytes(banks[b]) for p, b in pages)


class TapeSpecAgainstVectors(unittest.TestCase):
    """The tape vectors, as an implementer reading only the spec would get them."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = spec_code()
        cls.v = json.loads((VECTORS / "vectors_tape.json").read_text())
        cls.patch = (VECTORS / "vector_tape.nxc").read_bytes()
        cls.tapes = {n: (VECTORS / n).read_bytes() for n in ("tape.tap", "tape.tzx")}
        cls.nonce = bytes.fromhex(cls.v["nonce"])
        cls.master = bytes.fromhex(cls.v["master_key"])

    def test_the_files(self) -> None:
        self.assertEqual(hashlib.md5(self.patch).hexdigest(), self.v["patch_md5"])
        for name, want in self.v["files"].items():
            data = (VECTORS / name).read_bytes()
            self.assertEqual(dict(md5=hashlib.md5(data).hexdigest(), length=len(data)), want, name)

    def test_the_data_blocks(self) -> None:
        for name, tape in self.tapes.items():
            self.assertEqual([list(b) for b in spec_data_blocks(tape, name.endswith(".tzx"))], self.v["data_blocks"][name])
        tap, tzx = (self.v["data_blocks"][n] for n in ("tape.tap", "tape.tzx"))
        self.assertEqual([self.tapes["tape.tap"][a:a + n] for a, n in tap], [self.tapes["tape.tzx"][a:a + n] for a, n in tzx])

    def test_every_use(self) -> None:
        s = self.spec
        for u in self.v["uses"]:
            with self.subTest(tag=u["tag"], base=u["base"]):
                if u["base"] == "master":
                    base = s["key_base"](self.nonce, self.master)
                else:
                    base = s["dump_base"](self.nonce, self.tapes[u["base"]])
                    self.assertEqual(hexstate(base), self.v["dump_bases"][u["base"]])
                state = s["stream"](base, u["tag"].encode(), u["index"])
                self.assertEqual(hexstate(state), u["after_dropping"])
                self.assertEqual(s["output"](state, 32).hex(), u["first_output"])

    def test_both_key_wraps(self) -> None:
        s = self.spec
        wraps = [e for e in self.v["layout"] if e["tag"] == "TGT1"]
        for n, (name, tape) in enumerate(self.tapes.items()):
            at = wraps[n]["data_offset"]
            self.assertEqual(self.patch[at:at + 2], bytes((n, 3 if name.endswith(".tap") else 4)))
            plain = bytes(a ^ b for a, b in zip(self.patch[at + 6:at + 30], s["output"](s["stream"](s["dump_base"](self.nonce, tape), b"TGT1", n), 24)))
            self.assertEqual(plain, b"NXC1-KEY" + self.master)

    def test_the_tap1_block_and_its_table(self) -> None:
        s = self.spec
        e = next(e for e in self.v["layout"] if e["tag"] == "TAP1")
        data = self.patch[e["data_offset"]:e["data_offset"] + e["length"]]
        self.assertEqual(data[:4].hex(), self.v["plaintext"]["TAP1 head"])
        self.assertEqual(data[:4], bytes((0, 2, 0, 1)))
        state = s["stream"](s["key_base"](self.nonce, self.master), b"TAP1", 0)
        self.assertEqual(bytes(a ^ b for a, b in zip(data[4:], s["output"](state, len(data) - 4))).hex(), self.v["plaintext"]["TAP1 packed"])
        table = bytes.fromhex(self.v["plaintext"]["TAP1 table"])
        self.assertEqual(table[:55].hex(), self.v["plaintext"]["start header"])
        for name, tape in self.tapes.items():
            made = spec_start_snapshot(tape, name.endswith(".tzx"), table)
            self.assertEqual("%08x" % zlib.crc32(made), self.v["plaintext"]["start crc32"])
            self.assertEqual("%08x" % zlib.crc32(made), self.v["expected"]["fix off"]["crc32"])
            self.assertEqual(hashlib.md5(made).hexdigest(), self.v["expected"]["fix off"]["md5"])

    def test_options(self) -> None:
        e = next(e for e in self.v["layout"] if e["tag"] == "OPT1")
        self.assertEqual(self.patch[e["data_offset"]:e["data_offset"] + 3], bytes((1, 1, 20)))


@unittest.skipUnless(nxc is not None, "NexClash's snapshot reader is missing: set NEXCLASH_REPO")
class TapeToolAgainstVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v = json.loads((VECTORS / "vectors_tape.json").read_text())
        cls.patch = (VECTORS / "vector_tape.nxc").read_bytes()
        cls.tap, cls.tzx = ((VECTORS / n).read_bytes() for n in ("tape.tap", "tape.tzx"))

    def digest(self, data: bytes) -> dict:
        return dict(length=len(data), crc32="%08x" % zlib.crc32(data), md5=hashlib.md5(data).hexdigest())

    def test_every_output(self) -> None:
        want, p = self.v["expected"], self.patch
        self.assertEqual(self.digest(nxc.apply(p, game=self.tap)), want["base from the tap"])
        self.assertEqual(self.digest(nxc.apply(p, game=self.tzx)), want["base from the tzx"])
        self.assertEqual(want["base from the tap"], want["base from the tzx"])
        self.assertEqual(self.digest(nxc.apply(p, game=self.tzx, chosen=[1])), want["trainer"])
        self.assertEqual(self.digest(nxc.original_with_pokes(p, self.tap, [])), want["fix off"])
        self.assertEqual(self.digest(nxc.original_with_pokes(p, self.tzx, [])), want["fix off from the tzx"])
        self.assertEqual(self.digest(nxc.original_with_pokes(p, self.tap, [1])), want["fix off with a trainer"])
        start = nxc.snapshot_of((VECTORS / "tape_start.z80").read_bytes(), nxc.KIND_Z80)
        self.assertEqual(nxc.snapshot_of(nxc.original_with_pokes(p, self.tap, []), nxc.KIND_Z80).banks, start.banks)

    def test_the_tools_table(self) -> None:
        k = nxc.key_state(bytes.fromhex(self.v["nonce"]), bytes.fromhex(self.v["master_key"]))
        e = nxc.parse_tap1(dict(nxc.blocks(self.patch)[1])[b"TAP1"])
        self.assertEqual(nxc.tape_table_of(k, e).hex(), self.v["plaintext"]["TAP1 table"])
        self.assertEqual([list(b) for b in nxc.tape_blocks(self.tzx, nxc.KIND_TZX)], self.v["data_blocks"]["tape.tzx"])

    def test_refusals(self) -> None:
        for bad in self.v["refused"]:
            with self.subTest(bad["name"]):
                f = bytearray(self.patch)
                f[bad["offset"]] ^= bad["xor"]
                with self.assertRaises(nxc.Wrong):
                    nxc.apply(bytes(f), game=self.tap)
                with self.assertRaises(nxc.Wrong):
                    nxc.original_with_pokes(bytes(f), self.tzx, [])


@unittest.skipUnless(nxc is not None, "NexClash's snapshot reader is missing: set NEXCLASH_REPO")
class ToolAgainstVectors(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v, cls.patch, cls.v3, cls.v1 = load()
        spec = importlib.util.spec_from_file_location("make_vectors", VECTORS / "make_vectors.py")
        cls.maker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.maker)
        cls.sna = cls.maker.sna(nxc.snapshot_of(cls.v3, nxc.KIND_Z80).banks)

    def digest(self, data: bytes) -> dict:
        return dict(length=len(data), crc32="%08x" % zlib.crc32(data), md5=hashlib.md5(data).hexdigest())

    def test_the_tools_states(self) -> None:
        nonce = bytes.fromhex(self.v["nonce"])
        self.assertEqual(hexstate(nxc.key_state(nonce, bytes.fromhex(self.v["master_key"])).base), self.v["key_base"])
        self.assertEqual(hexstate(nxc.dump_state(nonce, self.v3).base), self.v["dump_bases"]["game_v3.z80"])

    def test_every_output(self) -> None:
        want = self.v["expected"]
        p = self.patch
        self.assertEqual(self.digest(nxc.apply(p, game=self.v3)), want["base"])
        self.assertEqual(self.digest(nxc.apply(p, game=self.v1)), want["base"])
        self.assertEqual(hashlib.md5(self.sna).hexdigest(), self.v["sna_file"]["md5"])
        self.assertEqual(self.digest(nxc.apply(p, game=self.sna)), want["base"])
        self.assertEqual(self.digest(nxc.apply(p, game=self.v3, colours="Painted")), want["colours"])
        self.assertEqual(self.digest(nxc.apply(p, game=self.v3, chosen=[1])), want["trainer"])
        self.assertEqual(self.digest(nxc.apply(p, game=self.v1, colours="Painted", chosen=[1])), want["colours and trainer"])
        self.assertEqual(self.digest(nxc.apply(p, game=self.v3, language="Vector")), want["language"])
        self.assertEqual(self.digest(nxc.apply(p, game=self.v3, colours="Painted", language="Vector")), want["colours and language"])
        self.assertEqual(self.digest(nxc.original_with_pokes(p, self.v3, [1])), want["fix off with a trainer, v3"])
        self.assertEqual(self.digest(nxc.original_with_pokes(p, self.v1, [1])), want["fix off with a trainer, v1"])
        self.assertEqual(self.digest(nxc.original_with_pokes(p, self.sna, [1])), want["fix off with a trainer, sna"])

    def test_refusals(self) -> None:
        for bad in self.v["refused"]:
            with self.subTest(bad["name"]):
                f = bytearray(self.patch)
                f[bad["offset"]] ^= bad["xor"]
                with self.assertRaises(nxc.Wrong):
                    nxc.apply(bytes(f), game=self.v3)
        wrong = bytearray(self.v3)
        wrong[len(wrong) // 2] ^= 1
        with self.assertRaises(nxc.Wrong):
            nxc.apply(self.patch, game=bytes(wrong))

    def test_the_decoded_plaintexts(self) -> None:
        k = nxc.key_state(bytes.fromhex(self.v["nonce"]), bytes.fromhex(self.v["master_key"]))
        d = dict(nxc.blocks(self.patch)[1])
        self.assertEqual(nxc.unzx0(k.block(b"SIT1")(d[b"SIT1"]), nxc.SITE_TABLE_MAX).hex(), self.v["plaintext"]["SIT1 table"])
        self.assertEqual(nxc.unzx0(k.block(b"SCR1", 0)(d[b"SCR1"][3:]), 6912).hex(), self.v["plaintext"]["SCR1 piece 0"])

    def test_the_crc_of_a_combination_as_the_spec_says(self) -> None:
        want = self.v["expected"]
        c = {k: int(want[k]["crc32"], 16) for k in ("base", "colours", "language", "colours and language")}
        self.assertEqual(c["colours and language"], c["base"] ^ (c["colours"] ^ c["base"]) ^ (c["language"] ^ c["base"]))
        self.assertEqual(int(self.v["plaintext"]["SET2 stream 0 crc"], 16), c["colours"])
        self.assertEqual(int(self.v["plaintext"]["SET2 stream 1 crc"], 16), c["language"])

    def test_a_set_block_as_the_spec_says(self) -> None:
        """The chunk made by hand from the spec's words, with no help from the tool's own decoder."""
        k = nxc.key_state(bytes.fromhex(self.v["nonce"]), bytes.fromhex(self.v["master_key"]))
        for t, d in nxc.blocks(self.patch)[1]:
            if t != b"SET2":
                continue
            stream, name_len = d[0], d[4]
            at = 5 + name_len
            crc = k.block(b"SEB" + bytes((stream,)), 255)(d[at:at + 4]).hex()
            self.assertEqual(bytes.fromhex(crc)[::-1].hex(), self.v["plaintext"]["SET2 stream %d crc" % stream])
            at += 4
            seen = 0
            while at < len(d):
                bank, size = struct.unpack_from("<BH", d, at)
                plain = nxc.unzx0(k.block(b"SEB" + bytes((stream,)), bank)(d[at + 3:at + 3 + size]), 18432)
                self.assertEqual(plain.hex(), self.v["plaintext"]["SET2 stream %d bank %d chunk" % (stream, bank)])
                self.assertEqual(sum(bin(c).count("1") for c in plain[:2048]), len(plain) - 2048)
                at += 3 + size
                seen += 1
            self.assertGreaterEqual(seen, 1)

    def test_the_format_constants_are_the_specs(self) -> None:
        text = SPEC.read_text()
        self.assertIn("1 to 32", text)
        self.assertEqual(nxc.TARGETS_MAX, 32)
        self.assertIn("1 to 127 bytes", text)
        self.assertEqual(nxc.FILE_NAME_MAX, 127)
        self.assertIn("92,928", text)
        self.assertEqual(nxc.SCREEN_MAX, 92928)
        self.assertEqual(nxc.LOADER_LEVEL, 3)


if __name__ == "__main__":
    unittest.main()

"""Toggles (SET2 kinds 3 and 4) through tools/nxc.py, on the made-up tape game: each alone, together, with a colour set and
with a trainer; the refusals a writer and a reader make; the proof line a logic toggle needs; the limit; and that a patch
without toggles is unchanged. Needs the zx0 compressor (NXC_ZX0_DIR)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import tape_game as G
import test_nexclash_dot as T
import test_nxc_tape as TT

nxc = T.nxc
ROOT = T.ROOT
TMP = os.environ.get("TMPDIR")
B2 = 512 + 16384                  # bank 2 in the .nex, after bank 5


def variant(nex: bytes, changes) -> bytes:
    out = bytearray(nex)
    for o, v in changes:
        out[B2 + o] = v
    return bytes(out)


def build(toggles, colours=None, trainers=(), proof=None, info=None):
    """(patch, base .nex, tap): toggles {name: (changes, logic)}, colours {name: changes}, changes [(bank 2 offset, value)]."""
    blocks = G.data_blocks()
    start = G.start_banks(blocks)
    nex, extra = G.build(start, blocks, nxc.ORDER)
    with tempfile.TemporaryDirectory(dir=TMP) as d:
        tmp = Path(d)
        for name, data in (("game.tap", G.tap(blocks)), ("start.z80", G.start_z80(start)), ("o.nex", nex)):
            (tmp / name).write_bytes(data)
        tog = {}
        for i, (n, (ch, logic)) in enumerate(toggles.items()):
            (tmp / f"t{i}.nex").write_bytes(variant(nex, ch)); tog[n] = (str(tmp / f"t{i}.nex"), logic)
        col = {}
        for i, (n, ch) in enumerate((colours or {}).items()):
            (tmp / f"c{i}.nex").write_bytes(variant(nex, ch)); col[n] = str(tmp / f"c{i}.nex")
        patch, _ = nxc.make(str(tmp / "game.tap"), str(tmp / "o.nex"), dict(title="Tape Game", file="game.tap"), dict(build="t", **(info or {})),
                            start=str(tmp / "start.z80"), tape_banks=extra, toggles=tog, colours=col,
                            trainer_blocks=[nxc.trn1(n, p) for n, p in trainers], proof=proof)
    return patch, nex, G.tap(blocks)


@TT.needs
class Toggles(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch, cls.nex, cls.tap = build({"Smooth scrolling": ([(0x2100, 0x11), (0x2101, 0x22)], False),
                                             "Fix the lift": ([(0x2200, 0x33)], True)},
                                            colours={"Painted": [(0x2050, 0x5A)]}, trainers=[("Lives", [(2, 0x2010, 0xAB)])],
                                            proof={"toggle_1": "the lift no longer sticks; tested by a recording reaching it"})

    def test_listed_with_their_kinds(self) -> None:
        self.assertEqual(nxc.toggles_of(self.patch), [("Smooth scrolling", False), ("Fix the lift", True)])
        kinds = [e["kind"] for e in nxc.sets(self.patch)]
        self.assertEqual(sorted(kinds), [nxc.KIND_COLOURS, nxc.KIND_TOGGLE, nxc.KIND_TOGGLE_LOGIC])

    def test_each_alone_and_every_combination(self) -> None:
        base = self.nex
        smooth = [(0x2100, 0x11), (0x2101, 0x22)]; lift = [(0x2200, 0x33)]; paint = [(0x2050, 0x5A)]; lives = [(0x2010, 0xAB)]
        for toggles, colours, chosen, changes in (
                ((), None, None, []), (("Smooth scrolling",), None, None, smooth), (("Fix the lift",), None, None, lift),
                (("Smooth scrolling", "Fix the lift"), None, None, smooth + lift),
                (("Smooth scrolling", "Fix the lift"), "Painted", None, smooth + lift + paint),
                (("Smooth scrolling",), "Painted", [1], smooth + paint + lives)):
            with self.subTest(toggles=toggles, colours=colours, chosen=chosen):
                got = nxc.apply(self.patch, game=self.tap, toggles=toggles, colours=colours, chosen=chosen)
                self.assertEqual(got, variant(base, changes))

    def test_off_is_the_base_byte_for_byte(self) -> None:
        plain, nex, tap = build({})
        self.assertEqual(nxc.apply(self.patch, game=self.tap), nxc.apply(plain, game=tap))

    def test_a_writer_refuses_overlaps(self) -> None:
        with self.assertRaisesRegex(ValueError, "both change"):
            build({"A": ([(0x2100, 1)], False), "B": ([(0x2100, 1)], False)})          # the same byte, even the same value
        with self.assertRaisesRegex(ValueError, "both change"):
            build({"A": ([(0x2050, 1)], False)}, colours={"Painted": [(0x2050, 0x5A)]})
        with self.assertRaisesRegex(ValueError, "trainer"):
            build({"A": ([(0x2010, 1)], False)}, trainers=[("Lives", [(2, 0x2010, 0xAB)])])
        with self.assertRaisesRegex(ValueError, "toggle_1"):
            build({"Fix": ([(0x2100, 1)], True)})
        with self.assertRaisesRegex(ValueError, "at most 4"):
            build({n: ([(0x2100 + i, 1)], False) for i, n in enumerate("ABCDE")})
        with self.assertRaisesRegex(ValueError, "one name"):
            build({"A": ([(0x2100, 1)], False), "a": ([(0x2101, 1)], False)})

    def test_a_reader_refuses_an_overlap_chosen(self) -> None:
        patch, nex, tap = build({"A": ([(0x2100, 1)], False), "B": ([(0x2101, 2)], False)})
        def same(bl, st):                                          # B's chunk made to write A's byte too
            a = next(e for e in bl if e[0] == nxc.SET_TAG and nxc.parse_set(e[1])["name"] == b"A")
            b = next(e for e in bl if e[0] == nxc.SET_TAG and nxc.parse_set(e[1])["name"] == b"B")
            ea, eb = nxc.parse_set(a[1]), nxc.parse_set(b[1])
            (bank, ca), = nxc.read_set(st, ea)[1]
            chunk = bytearray(ca); chunk[nxc.BITMAP:] = b"\x07"
            stream = nxc.set_use(st, eb["stream"], bank)(nxc.zx0(bytes(chunk)))
            head = b[1][:nxc.SET_FIXED + len(eb["name"]) + nxc.SET_CRC]
            b[1] = head + bytes((bank,)) + len(stream).to_bytes(2, "little") + stream
        forged = T.rekey(patch, tap, same)
        self.assertIsNotNone(nxc.apply(forged, game=tap, toggles=["A"]))
        with self.assertRaisesRegex(nxc.Wrong, "same bytes"):
            nxc.apply(forged, game=tap, toggles=["A", "B"])

    def test_the_command_line(self) -> None:
        blocks = G.data_blocks()
        start = G.start_banks(blocks)
        nex, extra = G.build(start, blocks, nxc.ORDER)
        tool = [sys.executable, str(ROOT / "tools" / "nxc.py")]
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            tmp = Path(d)
            for name, data in (("game.tap", G.tap(blocks)), ("start.z80", G.start_z80(start)), ("o.nex", nex),
                               ("s.nex", variant(nex, [(0x2100, 9)]))):
                (tmp / name).write_bytes(data)
            r = subprocess.run(tool + ["make", str(tmp / "o.nex"), str(tmp / "game.tap"), "--start", str(tmp / "start.z80"),
                                       "--tape-bank", ",".join(map(str, extra)), "--toggle", "Smooth scrolling=" + str(tmp / "s.nex"),
                                       "-o", str(tmp / "p.nxc")], capture_output=True, text=True)
            self.assertIn("rebuilds it exactly", r.stdout + r.stderr)
            r = subprocess.run(tool + [str(tmp / "p.nxc"), str(tmp / "game.tap"), "--bare", "--toggle", "Smooth scrolling", "-o", str(tmp / "out.nex")],
                               capture_output=True, text=True)
            self.assertIn("toggles: Smooth scrolling", r.stdout)
            self.assertEqual((tmp / "out.nex").read_bytes(), variant(nex, [(0x2100, 9)]))


if __name__ == "__main__":
    unittest.main()

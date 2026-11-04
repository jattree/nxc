"""INF1's version through tools/nxc.py, on the made-up tape game: where a writer puts it, what a writer refuses, what a
reader takes, the setter (which keeps the key and refuses the wrong game), that credit and import-pok keep it, the
description it adds to (and leaves as it was without it), the credit row, and the command line. Needs the zx0
compressor (NXC_ZX0_DIR)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import test_nexclash_dot as T
import test_nxc_label as L
import test_nxc_tape as TT
import test_nxc_toggle as TG

nxc = T.nxc
ROOT = T.ROOT
TMP = os.environ.get("TMPDIR")
INFO = dict(publisher="Ocean, 1989", patch_by="Jon Attree", fix_label="Colour")


def strings(desc: bytes, n: int) -> list[bytes]:
    """The first n zero-terminated strings of a description, after its three bytes."""
    return desc[3:].split(b"\0")[:n]


@TT.needs
class Version(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plain, cls.nex, cls.tap = TG.build({}, info=INFO)
        cls.patch = TG.build({}, info=dict(INFO, version="1.0"))[0]

    def test_a_writer_puts_it_after_the_menu_names(self) -> None:
        self.assertEqual(nxc.patch_version(self.patch), "1.0")
        self.assertEqual(nxc.patch_version(self.plain), "")
        text = dict(nxc.blocks(self.patch)[1])[b"INF1"]
        self.assertTrue(text.startswith(b"publisher=Ocean, 1989\npatch_by=Jon Attree\nfix_label=Colour\nversion=1.0\n"), text)

    def test_it_changes_no_game(self) -> None:
        self.assertEqual(nxc.apply(self.patch, game=self.tap), self.nex)
        self.assertEqual(nxc.original_with_pokes(self.patch, self.tap, []), nxc.original_with_pokes(self.plain, self.tap, []))

    def test_a_writer_refuses(self) -> None:
        for bad in ("123456789", "v1.0", "V2", "1.0 beta", "1.0\n", "é1", "\x01"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "a version is"):
                TG.build({}, info=dict(version=bad))
            with self.subTest(bad=bad), self.assertRaisesRegex(nxc.Wrong, "a version is"):
                nxc.set_version(self.plain, self.tap, bad)
        self.assertEqual(nxc.patch_version(TG.build({}, info=dict(version="12345678"))[0]), "12345678")   # 8 is the most
        with self.assertRaisesRegex(ValueError, "first 252"):                                            # past what a loader reads
            TG.build({}, info=dict(publisher="P" * 120, patch_by="N" * 120, version="1.0"))

    def test_what_a_reader_takes(self) -> None:
        for body, want in ((b"publisher=x\n", ""),
                           (b"version=\n", ""),
                           (b"publisher=" + b"p" * 238 + b"\nversion=1.0\n", ""),        # cut off at 252
                           (b"version=" + b"9" * 12 + b"\n", "9" * 8),
                           (b"version=1\x01\n", "1?"),
                           (b"version=1.0\nversion=2.0\n", "1.0")):                     # the first is taken
            with self.subTest(body=body[:40]):
                self.assertEqual(nxc.patch_version(L.with_inf1(self.patch, self.tap, body)), want)

    def test_the_setter(self) -> None:
        f = nxc.set_version(self.plain, self.tap, "1.0")
        self.assertEqual(nxc.patch_version(f), "1.0")
        self.assertEqual(dict(nxc.blocks(f)[1])[b"INF1"], dict(nxc.blocks(self.patch)[1])[b"INF1"])
        self.assertEqual(f[:nxc.CHECK_AT], self.plain[:nxc.CHECK_AT])                     # the same nonce
        self.assertEqual(nxc.check_key(f, self.tap)[2:], nxc.check_key(self.plain, self.tap)[2:])
        self.assertEqual(nxc.apply(f, game=self.tap), self.nex)
        f2 = nxc.set_version(f, self.tap, "1.1")
        self.assertEqual(nxc.patch_version(f2), "1.1")
        self.assertEqual(dict(nxc.blocks(f2)[1])[b"INF1"].count(b"version="), 1)
        self.assertEqual(nxc.set_version(f, self.tap, ""), self.plain)                    # removed: as it was
        with self.assertRaisesRegex(nxc.Wrong, "first 252"):
            nxc.set_version(L.with_inf1(self.plain, self.tap, b"publisher=" + b"p" * 238 + b"\n"), self.tap, "1.0")

    def test_the_setter_refuses_the_wrong_game(self) -> None:
        wrong = bytearray(self.tap)
        wrong[-3] ^= 1
        with self.assertRaises(nxc.Wrong):
            nxc.set_version(self.plain, bytes(wrong), "1.0")

    def test_credit_and_import_pok_keep_it(self) -> None:
        f = nxc.set_credits(self.patch, self.tap, patch_by="Someone Else", colours_by="")
        self.assertEqual(nxc.patch_version(f), "1.0")
        self.assertTrue(dict(nxc.blocks(f)[1])[b"INF1"].startswith(b"publisher=Ocean, 1989\npatch_by=Someone Else\nfix_label=Colour\nversion=1.0\n"))
        f = nxc.import_pok(self.patch, self.tap, "NInfinite lives\nZ  8 32784 0 0\nY\n", publisher="Ocean, 1990")
        self.assertEqual(nxc.patch_version(f), "1.0")

    def test_the_description(self) -> None:
        old, data = nxc.menu_description(self.plain)
        new, data2 = nxc.menu_description(self.patch)
        self.assertEqual(data, data2)
        self.assertEqual(old[0], nxc.DESC_FIXED)                                           # without one: as it was
        self.assertEqual(new[0], nxc.DESC_FIXED | nxc.DESC_VERSION)
        self.assertEqual(strings(new, 5)[3:], [b"Jon Attree", b"1.0"])
        at = 3
        for _ in range(4):
            at = new.index(b"\0", at) + 1
        end = new.index(b"\0", at) + 1
        self.assertEqual(bytes((nxc.DESC_FIXED,)) + new[1:at] + new[end:], old)            # only the string and the flag differ
        cut = nxc.menu_description(L.with_inf1(self.patch, self.tap, b"version=" + b"9" * 12 + b"\n"))[0]
        self.assertEqual(strings(cut, 5)[4], b"9" * 8)

    def test_the_credit_row(self) -> None:
        for info, want in ((dict(patch_by="Jon Attree", version="1.0"), "Patch: Jon Attree           v1.0"),
                           (dict(patch_by="A Very Long Patch Maker Name", version="12345678"), "Patch: A Very Long Pat v12345678"),
                           (dict(patch_by="x" * 25, version="1.0"), "Patch: " + "x" * 20 + " v1.0"),
                           (dict(version="1.0"), " " * 28 + "v1.0"),
                           (dict(patch_by="Jon Attree"), "Patch: Jon Attree"),
                           (dict(patch_by="y" * 30), "Patch: " + "y" * 25)):
            with self.subTest(info=info):
                row = nxc.credit_line(TG.build({}, info=info)[0])
                self.assertEqual(row, want)
                self.assertLessEqual(len(row), 32)

    def test_the_command_line(self) -> None:
        tool = [sys.executable, str(ROOT / "tools" / "nxc.py")]
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            tmp = Path(d)
            (tmp / "p.nxc").write_bytes(self.plain)
            (tmp / "game.tap").write_bytes(self.tap)
            r = subprocess.run(tool + ["version", str(tmp / "p.nxc"), str(tmp / "game.tap"), "1.0", "-o", str(tmp / "v.nxc")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("version: 1.0", r.stdout)
            self.assertEqual((tmp / "v.nxc").read_bytes(), nxc.set_version(self.plain, self.tap, "1.0"))
            r = subprocess.run(tool + [str(tmp / "v.nxc")], capture_output=True, text=True)
            self.assertIn("version: 1.0\n", r.stdout)
            r = subprocess.run(tool + [str(tmp / "p.nxc")], capture_output=True, text=True)
            self.assertIn("version: (none)\n", r.stdout)
            bad = bytearray(self.tap)
            bad[-3] ^= 1
            (tmp / "bad.tap").write_bytes(bytes(bad))
            r = subprocess.run(tool + ["version", str(tmp / "p.nxc"), str(tmp / "bad.tap"), "1.0", "-o", str(tmp / "w.nxc")],
                               capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("Refused", r.stderr)
            self.assertFalse((tmp / "w.nxc").exists())
            r = subprocess.run(tool + ["version", str(tmp / "p.nxc"), str(tmp / "game.tap"), "v1", "-o", str(tmp / "w.nxc")],
                               capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("a version is", r.stderr)

    def test_make_on_the_command_line(self) -> None:
        import tape_game as G
        blocks = G.data_blocks()
        start = G.start_banks(blocks)
        nex, extra = G.build(start, blocks, nxc.ORDER)
        tool = [sys.executable, str(ROOT / "tools" / "nxc.py")]
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            tmp = Path(d)
            for name, data in (("game.tap", G.tap(blocks)), ("start.z80", G.start_z80(start)), ("o.nex", nex)):
                (tmp / name).write_bytes(data)
            r = subprocess.run(tool + ["make", str(tmp / "o.nex"), str(tmp / "game.tap"), "--start", str(tmp / "start.z80"),
                                       "--tape-bank", ",".join(map(str, extra)), "-o", str(tmp / "p.nxc"), "--patch-version", "2.1"],
                               capture_output=True, text=True)
            self.assertIn("rebuilds it exactly", r.stdout + r.stderr)
            self.assertEqual(nxc.patch_version((tmp / "p.nxc").read_bytes()), "2.1")


if __name__ == "__main__":
    unittest.main()

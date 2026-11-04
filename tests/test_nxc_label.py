"""INF1's fix_label through tools/nxc.py, on the made-up tape game: the menu's name for the main line, the default when it
is absent, cut off or empty, where a writer puts it, what a writer refuses, that credit and import-pok keep it, the
command line, and that it changes nothing but the name. Needs the zx0
compressor (NXC_ZX0_DIR)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import tape_game as G
import test_nexclash_dot as T
import test_nxc_tape as TT
import test_nxc_toggle as TG

nxc = T.nxc
ROOT = T.ROOT
TMP = os.environ.get("TMPDIR")


def with_inf1(patch: bytes, tap: bytes, body: bytes) -> bytes:
    """The patch with INF1's text replaced, resealed: what an owner of the game, or a careless writer, could make."""
    def edit(bl, st):
        next(e for e in bl if e[0] == b"INF1")[1] = body
    return T.rekey(patch, tap, edit)


@TT.needs
class FixLabel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plain, cls.nex, cls.tap = TG.build({})
        cls.patch = TG.build({"Smooth scrolling": ([(0x2100, 0x11)], False)},
                             info=dict(publisher="Ocean, 1989", patch_by="Jon Attree", fix_label="Colour"))[0]

    def test_the_label_and_the_default(self) -> None:
        self.assertEqual(nxc.fix_label(self.patch), "Colour")
        self.assertEqual(nxc.fix_label(self.plain), "Colour clash fix")
        self.assertEqual(nxc.FIX_LABEL, "Colour clash fix")
        self.assertEqual(nxc.FIX_LABEL_MAX, nxc.SET_NAME_MAX)

    def test_a_writer_puts_it_after_the_menu_names(self) -> None:
        text = dict(nxc.blocks(self.patch)[1])[b"INF1"]
        self.assertTrue(text.startswith(b"publisher=Ocean, 1989\npatch_by=Jon Attree\nfix_label=Colour\n"), text)

    def test_it_changes_nothing_but_the_name(self) -> None:
        self.assertEqual(nxc.apply(self.patch, game=self.tap), self.nex)
        self.assertEqual(nxc.apply(self.patch, game=self.tap, toggles=["Smooth scrolling"]), TG.variant(self.nex, [(0x2100, 0x11)]))
        self.assertEqual(nxc.original_with_pokes(self.patch, self.tap, []), nxc.original_with_pokes(self.plain, self.tap, []))

    def test_a_writer_refuses(self) -> None:
        for bad in ("x" * 26, "Colour\n", "Couleuré", "\x01"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "fix label"):
                TG.build({}, info=dict(fix_label=bad))
        TG.build({}, info=dict(fix_label="x" * 25))                                   # 25 is the most
        with self.assertRaisesRegex(ValueError, "first 252"):                         # pushed past what a loader reads
            TG.build({}, info=dict(publisher="P" * 120, patch_by="N" * 100, fix_label="Colour"))

    def test_a_reader_shows_the_default_or_the_first_25(self) -> None:
        for body, want in ((b"publisher=x\n", "Colour clash fix"),
                           (b"fix_label=\n", "Colour clash fix"),
                           (b"publisher=" + b"p" * 238 + b"\nfix_label=Colour\n", "Colour clash fix"),  # cut off at 252
                           (b"fix_label=" + b"y" * 30 + b"\n", "y" * 25),
                           (b"fix_label=Col\x01ur\n", "Col?ur"),
                           (b"fix_label=Colour\nfix_label=Other\n", "Colour")):              # the first is taken
            with self.subTest(body=body[:40]):
                self.assertEqual(nxc.fix_label(with_inf1(self.patch, self.tap, body)), want)

    def test_credit_and_import_pok_keep_it(self) -> None:
        f = nxc.set_credits(self.patch, self.tap, patch_by="Someone Else", colours_by="")
        self.assertEqual(nxc.fix_label(f), "Colour")
        self.assertTrue(dict(nxc.blocks(f)[1])[b"INF1"].startswith(b"publisher=Ocean, 1989\npatch_by=Someone Else\nfix_label=Colour\n"))
        f = nxc.import_pok(self.patch, self.tap, "NInfinite lives\nZ  8 32784 0 0\nY\n", publisher="Ocean, 1990")
        self.assertEqual(nxc.fix_label(f), "Colour")

    def test_the_command_line(self) -> None:
        blocks = G.data_blocks()
        start = G.start_banks(blocks)
        nex, extra = G.build(start, blocks, nxc.ORDER)
        tool = [sys.executable, str(ROOT / "tools" / "nxc.py")]
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            tmp = Path(d)
            for name, data in (("game.tap", G.tap(blocks)), ("start.z80", G.start_z80(start)), ("o.nex", nex)):
                (tmp / name).write_bytes(data)
            make = tool + ["make", str(tmp / "o.nex"), str(tmp / "game.tap"), "--start", str(tmp / "start.z80"),
                           "--tape-bank", ",".join(map(str, extra)), "-o", str(tmp / "p.nxc")]
            r = subprocess.run(make + ["--fix-label", "Colour"], capture_output=True, text=True)
            self.assertIn("rebuilds it exactly", r.stdout + r.stderr)
            self.assertEqual(nxc.fix_label((tmp / "p.nxc").read_bytes()), "Colour")
            r = subprocess.run(make + ["--fix-label", "x" * 26], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("fix label", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()

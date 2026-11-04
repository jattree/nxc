"""sdcard/, the files a player copies to a Next's SD card, and tools/setup_card.py, which puts them there.

The committed binaries must be exactly what their sources build, as firmware/nxcstub.bin is checked in test_menu_nex.py.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SDCARD = ROOT / "sdcard"
sys.path.insert(0, str(ROOT / "tools"))
import nxc  # noqa: E402
import setup_card  # noqa: E402

CFG = (b"; not a real line, kept as it is\r\n"
       b"TXT,CFG:.browse |\r\n"
       b"Z80,SNA:clear 65367:load \"\x7fsnapload.bas\":f$=\"|\":adj=0:goto 1\r\n"
       b"Z80,SNA:clear 65367:load \"\x7fsnapload.bas\":f$=\"|\":adj=1:goto 1\r\n"
       b"NEX:.nexload |\r\n")


class Binaries(unittest.TestCase):
    @unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus is not installed")
    def test_the_loader_is_its_source(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "NEXCLASH"
            subprocess.run(["sjasmplus", "--nologo", f"--raw={out}", "nexclash.asm"], cwd=ROOT / "firmware", check=True,
                           capture_output=True)
            self.assertEqual(out.read_bytes(), (SDCARD / "dot" / "NEXCLASH").read_bytes())

    def test_the_hand_off_is_the_tools(self):
        self.assertEqual((SDCARD / "nextzxos" / "NXCHAND.BAS").read_bytes(), nxc.handoff_bas())

    def test_the_game_folder_says_what_goes_in_it(self):
        self.assertIn("one folder per game", (SDCARD / "nxc" / "README.txt").read_text())

    def test_the_line_is_the_one_documented(self):
        for doc in (ROOT / "firmware" / "README.md", ROOT / "README.md"):
            documented = re.search(r"^NXC:.*$", doc.read_text(), re.M).group(0)
            self.assertEqual(documented.replace("<7F>", "\x7f").encode(), setup_card.NXC_LINE, doc)


class SetupCard(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        (self.root / "NEXTZXOS").mkdir()
        (self.root / "NEXTZXOS" / "BROWSER.CFG").write_bytes(CFG)
        (self.root / "MACHINES" / "NEXT").mkdir(parents=True)
        (self.root / "MACHINES" / "NEXT" / "ENNEXTZX.ROM").write_bytes(b"\0" * 16)
        (self.root / "DOT").mkdir()
        (self.root / "DOT" / "OTHER").write_bytes(b"left alone")

    def tearDown(self):
        self.dir.cleanup()

    def run_it(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = setup_card.main([str(self.root), *args])
        return code, out.getvalue(), err.getvalue()

    def cfg(self):
        return (self.root / "NEXTZXOS" / "BROWSER.CFG").read_bytes()

    def tree(self):
        return {str(p.relative_to(self.root)): p.read_bytes() if p.is_file() else None for p in self.root.rglob("*")}

    def test_sets_up_a_card(self):
        code, out, err = self.run_it()
        self.assertEqual(code, 0, err)
        self.assertEqual((self.root / "DOT" / "NEXCLASH").read_bytes(), (SDCARD / "dot" / "NEXCLASH").read_bytes())
        self.assertEqual((self.root / "NEXTZXOS" / "NXCHAND.BAS").read_bytes(), nxc.handoff_bas())
        self.assertEqual((self.root / "DOT" / "OTHER").read_bytes(), b"left alone")
        self.assertTrue((self.root / "nxc").is_dir())
        self.assertTrue((self.root / "nxc" / "README.txt").is_file())
        self.assertTrue((self.root / "tmp").is_dir())
        self.assertEqual((self.root / "NEXTZXOS" / "BROWSER.CFG.bak-pre-nxc").read_bytes(), CFG)
        lines = self.cfg().split(b"\r\n")
        self.assertEqual(lines[2], setup_card.NXC_LINE)
        self.assertTrue(lines[3].startswith(b"Z80,SNA:"))
        self.assertEqual(self.cfg().replace(setup_card.NXC_LINE + b"\r\n", b""), CFG)
        self.assertEqual(self.cfg().count(b"\x7f"), CFG.count(b"\x7f") + 2)

    def test_twice_is_the_same_as_once(self):
        self.run_it()
        once = self.tree()
        code, out, _ = self.run_it()
        self.assertEqual(code, 0)
        self.assertEqual(self.tree(), once)
        self.assertIn("already has the NXC line", out)

    def test_an_nxc_line_is_replaced_not_added(self):
        old = b"NXC:.nexclash \"|\"\r\n"
        (self.root / "NEXTZXOS" / "BROWSER.CFG").write_bytes(CFG.replace(b"NEX:", old + b"NEX:"))
        self.assertEqual(self.run_it()[0], 0)
        self.assertEqual(self.cfg().count(b"NXC:"), 1)
        self.assertEqual(self.cfg(), CFG.replace(b"NEX:", setup_card.NXC_LINE + b"\r\nNEX:"))

    def test_the_first_backup_is_kept(self):
        (self.root / "NEXTZXOS" / "BROWSER.CFG.bak-pre-nxc").write_bytes(b"older")
        self.run_it()
        self.assertEqual((self.root / "NEXTZXOS" / "BROWSER.CFG.bak-pre-nxc").read_bytes(), b"older")

    def test_a_dry_run_changes_nothing(self):
        before = self.tree()
        code, out, _ = self.run_it("--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(self.tree(), before)
        self.assertIn("would add the NXC line", out)
        self.assertIn("would copy", out)

    def test_refuses_what_is_not_a_card(self):
        (self.root / "MACHINES" / "NEXT" / "ENNEXTZX.ROM").unlink()
        before = self.tree()
        code, _, err = self.run_it()
        self.assertEqual(code, 1)
        self.assertIn("does not look like a NextZXOS card", err)
        self.assertEqual(self.tree(), before)

    def test_refuses_a_browser_cfg_with_no_snapshot_line(self):
        (self.root / "NEXTZXOS" / "BROWSER.CFG").write_bytes(b"NEX:.nexload |\r\n")
        code, _, err = self.run_it()
        self.assertEqual(code, 1)
        self.assertIn("no Z80,SNA line", err)
        self.assertEqual(self.cfg(), b"NEX:.nexload |\r\n")

    def test_lower_case_names_too(self):
        os.rename(self.root / "NEXTZXOS", self.root / "nextzxos")
        os.rename(self.root / "nextzxos" / "BROWSER.CFG", self.root / "nextzxos" / "browser.cfg")
        self.assertEqual(self.run_it()[0], 0)
        self.assertIn(setup_card.NXC_LINE, (self.root / "nextzxos" / "browser.cfg").read_bytes())
        self.assertTrue((self.root / "nextzxos" / "NXCHAND.BAS").is_file())


if __name__ == "__main__":
    unittest.main()

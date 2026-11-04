"""sdcard/, the files a player copies to a Next's SD card.

The committed binaries must be exactly what their sources build, as firmware/nxcstub.bin is checked in test_menu_nex.py.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SDCARD = ROOT / "sdcard"
sys.path.insert(0, str(ROOT / "tools"))
import nxc  # noqa: E402

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


if __name__ == "__main__":
    unittest.main()

"""The .NEXCLASH dot command with toggles (SET2 kinds 3 and 4), on the Z80 harness: the menu's lines and numbering, each
toggle alone and with a colour set and a trainer, against tools/nxc.py byte for byte; the third choice refused at the menu;
[N/A] with the fix off; and the loader before toggles, which offers no line and makes the base. Controls restore a mistake
in the loader and show the tests catch it."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_nexclash_dot as T
import test_nxc_toggle as TG

H = T.H
nxc = T.nxc
NEX, Z80 = T.NEX, T.Z80
TMP = os.environ.get("TMPDIR")
SMOOTH = [(0x2100, 0x11), (0x2101, 0x22)]
LIFT = [(0x2200, 0x33)]
PAINT = [(0x2050, 0x5A)]
LIVES = [(0x2010, 0xAB)]


def assemble_text(text: str):
    """A loader's binary and symbols from its source text."""
    with tempfile.TemporaryDirectory(dir=TMP) as d:
        src = Path(d) / "nexclash.asm"; src.write_text(text)
        out, sym = Path(d) / "NEXCLASH", Path(d) / "nexclash.sym"
        subprocess.run(["sjasmplus", "--nologo", f"--raw={out}", f"--sym={sym}", str(src)], check=True, capture_output=True)
        symbols = {m.group(1): int(m.group(2), 16) & 0xFFFF for m in re.finditer(r"(\S+): EQU 0x([0-9A-Fa-f]+)", sym.read_text())}
        return out.read_bytes(), symbols


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class ToggleLoader(T.Base):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.patch, cls.nex, cls.tap = TG.build({"Smooth scrolling": (SMOOTH, False), "Fix the lift": (LIFT, True)},
                                               colours={"Painted": PAINT}, trainers=[("Lives", [(2, 0x2010, 0xAB)])],
                                               proof={"toggle_1": "the lift no longer sticks"})

    def go(self, keys, patch=None, **options):
        m = self.machine({"patch.nxc": patch or self.patch, "game.tap": self.tap}, keys=keys, **options)
        failed, message = m.run('"patch.nxc"')
        return m, failed, message

    def want(self, *changes):
        return TG.variant(self.nex, [c for ch in changes for c in ch])

    def test_the_menu_lines(self) -> None:
        m, failed, message = self.go(["space"])
        self.assertFalse(failed, message)
        menu = m.screens[1]
        for line in ("1 Lives", T.row("2", "Colour clash fix", "[ ON]"), T.row("3", "Enhanced colours", "[OFF]"),
                     T.row("4", "Smooth scrolling", "[OFF]"), T.row("5", "Fix the lift", "[OFF]")):
            self.assertIn(line, menu)
        self.assertEqual(bytes(m.written[NEX]), self.nex)

    def test_each_and_together(self) -> None:
        for keys, changes, apply_args in (
                (["4", "space"], [SMOOTH], dict(toggles=["Smooth scrolling"])),
                (["5", "space"], [LIFT], dict(toggles=["Fix the lift"])),
                (["4", "5", "space"], [SMOOTH, LIFT], dict(toggles=["Smooth scrolling", "Fix the lift"])),
                (["3", "4", "space"], [PAINT, SMOOTH], dict(toggles=["Smooth scrolling"], colours="Painted")),
                (["1", "4", "space"], [SMOOTH, LIVES], dict(toggles=["Smooth scrolling"], chosen=[1])),
                (["4", "4", "space"], [], dict())):
            with self.subTest(keys=keys):
                m, failed, message = self.go(keys)
                self.assertFalse(failed, message)
                self.assertEqual(m.clean(), [])
                self.assertEqual(bytes(m.written[NEX]), self.want(*changes))
                self.assertEqual(bytes(m.written[NEX]), nxc.apply(self.patch, game=self.tap, **apply_args))

    def test_a_third_choice_cannot_be_made(self) -> None:
        m, failed, message = self.go(["3", "4", "5", "space"])
        self.assertFalse(failed, message)
        self.assertIn(T.row("5", "Fix the lift", "[OFF]"), m.screens[-2])
        self.assertEqual(bytes(m.written[NEX]), self.want(PAINT, SMOOTH))
        m, failed, message = self.go(["4", "5", "3", "space"])                     # a set as the third is refused too
        self.assertIn(T.row("3", "Enhanced colours", "[OFF]"), m.screens[-2])
        self.assertEqual(bytes(m.written[NEX]), self.want(SMOOTH, LIFT))
        m, failed, message = self.go(["4", "5", "4", "3", "space"])                # one off, and there is room again
        self.assertEqual(bytes(m.written[NEX]), self.want(LIFT, PAINT))

    def test_not_available_with_the_fix_off(self) -> None:
        m, failed, message = self.go(["2", "4", "space"])
        self.assertFalse(failed, message)
        self.assertIn(T.row("4", "Smooth scrolling", "[N/A]"), m.screens[-2])
        self.assertNotIn(NEX, m.written)
        self.assertEqual(bytes(m.written[Z80]), nxc.original_with_pokes(self.patch, self.tap, []))

    def test_the_loader_before_toggles(self) -> None:
        old = subprocess.run(["git", "-C", str(T.ROOT), "show", "e018c42:firmware/nexclash.asm"], capture_output=True, text=True, check=True).stdout
        binary, symbols = assemble_text(old)
        m = self.machine({"patch.nxc": self.patch, "game.tap": self.tap}, keys=["4", "space"], binary=binary, symbols=symbols)
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertNotIn("Smooth scrolling", m.screens[1])
        self.assertEqual(bytes(m.written[NEX]), self.nex)

    def test_controls(self) -> None:
        # The menu not counting choices: the third is taken, and the loader has no slot for it.
        binary, symbols = H.assemble([("""        pop     hl
        ret     z
        ret     c
""", """        pop     hl
""")])
        m = self.machine({"patch.nxc": self.patch, "game.tap": self.tap}, keys=["3", "4", "5", "space"], binary=binary, symbols=symbols)
        failed, message = m.run('"patch.nxc"')
        self.assertTrue(failed or bytes(m.written.get(NEX, b"")) != self.want(PAINT, SMOOTH), "a loader taking a third choice passed")
        # A toggle's slot left with the colours' kind: the wrong block found, or none.
        binary, symbols = H.assemble([("""        ld      a,(hl)
        ld      (de),a
        ld      de,TOGGLES_MAX""", """        ld      a,(hl)
        ld      de,TOGGLES_MAX""")])
        m = self.machine({"patch.nxc": self.patch, "game.tap": self.tap}, keys=["4", "space"], binary=binary, symbols=symbols)
        failed, message = m.run('"patch.nxc"')
        self.assertTrue(failed or bytes(m.written.get(NEX, b"")) != self.want(SMOOTH), "a loader not saying a slot's kind passed")


if __name__ == "__main__":
    unittest.main()

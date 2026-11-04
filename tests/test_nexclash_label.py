"""The .NEXCLASH dot command with INF1's fix_label, on the Z80 harness: the menu names the main line with it, on and off,
with a toggle, a colour set and a trainer, byte for byte against tools/nxc.py; the default when it is absent, cut off or
empty; a long one cut to 25 and an unprintable byte shown as ?; and the loader before labels, which shows the default and
builds the same. A control restores the old menu line and shows the tests catch it."""
from __future__ import annotations

import subprocess
import unittest

import test_nexclash_dot as T
import test_nexclash_toggle as TL
import test_nxc_label as L
import test_nxc_toggle as TG

H = T.H
nxc = T.nxc
NEX, Z80 = T.NEX, T.Z80


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class LabelLoader(T.Base):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.patch, cls.nex, cls.tap = TG.build({"Smooth scrolling": (TL.SMOOTH, False)}, colours={"Painted": TL.PAINT},
                                               trainers=[("Lives", [(2, 0x2010, 0xAB)])],
                                               info=dict(publisher="Ocean, 1989", fix_label="Colour"))

    def go(self, keys, patch=None, **options):
        m = self.machine({"patch.nxc": patch or self.patch, "game.tap": self.tap}, keys=keys, **options)
        failed, message = m.run('"patch.nxc"')
        return m, failed, message

    def test_the_menu_line(self) -> None:
        m, failed, message = self.go(["enter"])
        self.assertFalse(failed, message)
        menu = m.screens[1]
        self.assertIn(T.row("2", "Colour", "[ ON]"), menu)
        self.assertNotIn("Colour clash fix", menu)
        for line in (T.row("3", "Enhanced colours", "[OFF]"), T.row("4", "Smooth scrolling", "[OFF]")):
            self.assertIn(line, menu)
        self.assertEqual(bytes(m.written[NEX]), self.nex)

    def test_it_is_still_the_fix(self) -> None:
        m, failed, message = self.go(["2", "4", "enter"])
        self.assertFalse(failed, message)
        self.assertIn(T.row("2", "Colour", "[OFF]"), m.screens[-2])
        self.assertIn(T.row("4", "Smooth scrolling", "[N/A]"), m.screens[-2])
        self.assertNotIn(NEX, m.written)
        self.assertEqual(bytes(m.written[Z80]), nxc.original_with_pokes(self.patch, self.tap, []))
        for keys, apply_args in ((["4", "enter"], dict(toggles=["Smooth scrolling"])),
                                 (["1", "4", "enter"], dict(toggles=["Smooth scrolling"], chosen=[1])),
                                 (["3", "4", "enter"], dict(toggles=["Smooth scrolling"], colours="Painted"))):
            with self.subTest(keys=keys):
                m, failed, message = self.go(keys)
                self.assertFalse(failed, message)
                self.assertEqual(bytes(m.written[NEX]), nxc.apply(self.patch, game=self.tap, **apply_args))

    def test_the_default_and_what_a_reader_shows(self) -> None:
        for body, line in ((b"publisher=Ocean, 1989\n", T.row("2", "Colour clash fix", "[ ON]")),
                           (b"fix_label=\n", T.row("2", "Colour clash fix", "[ ON]")),
                           (b"publisher=" + b"p" * 238 + b"\nfix_label=Colour\n", T.row("2", "Colour clash fix", "[ ON]")),
                           (b"fix_label=" + b"y" * 30 + b"\n", T.row("2", "y" * 25, "[ ON]")),
                           (b"fix_label=Col\x01ur\n", T.row("2", "Col?ur", "[ ON]"))):
            with self.subTest(body=body[:40]):
                patch = L.with_inf1(self.patch, self.tap, body)
                self.assertEqual(T.row("2", nxc.fix_label(patch), "[ ON]"), line)          # the tool agrees
                m, failed, message = self.go(["enter"], patch=patch)
                self.assertFalse(failed, message)
                self.assertIn(line, m.screens[1])
                self.assertEqual(bytes(m.written[NEX]), self.nex)

    def test_the_vector(self) -> None:
        v = L.json.loads((T.ROOT / "tests" / "vectors" / "vectors_label.json").read_text())
        patch = (T.ROOT / "tests" / "vectors" / "vector_label.nxc").read_bytes()
        tap = (T.ROOT / "tests" / "vectors" / "tape.tap").read_bytes()
        m = self.machine({"patch.nxc": patch, "tape.tap": tap}, keys=["enter"])
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(v["menu_line"].split()[1], "Colour")          # the vector's line, as the menu draws it now
        self.assertIn(T.row("1", "Colour", "[ ON]"), m.screens[1])
        self.assertEqual(L.hashlib.md5(bytes(m.written[NEX])).hexdigest(), v["expected"]["base"]["md5"])

    def test_the_loader_before_labels(self) -> None:
        old = subprocess.run(["git", "-C", str(T.ROOT), "show", "13286c8:firmware/nexclash.asm"], capture_output=True, text=True, check=True).stdout
        binary, symbols = TL.assemble_text(old)
        m = self.machine({"patch.nxc": self.patch, "game.tap": self.tap}, keys=["4", "enter"], binary=binary, symbols=symbols)
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertIn("  2  Colour clash fix          [ON]", m.screens[1])
        self.assertEqual(bytes(m.written[NEX]), nxc.apply(self.patch, game=self.tap, toggles=["Smooth scrolling"]))

    def test_controls(self) -> None:
        # The menu ignoring the label: the old line comes back, and the test sees it.
        binary, symbols = H.assemble([("""        jr      nz,.fl
        ld      hl,str_fix""", """        ld      hl,str_fix""")])
        m = self.machine({"patch.nxc": self.patch, "game.tap": self.tap}, keys=["enter"], binary=binary, symbols=symbols)
        failed, message = m.run('"patch.nxc"')
        self.assertNotIn(T.row("2", "Colour", "[ ON]"), m.screens[1])
        # The label not cleared before INF1 is read: a stale byte below the stack names the line.
        binary, symbols = H.assemble([("""        xor     a                           ; below the stack, so not cleared with the rest
        ld      (fix_label),a
""", "")])
        m = self.machine({"patch.nxc": L.with_inf1(self.patch, self.tap, b"publisher=x\n"), "game.tap": self.tap},
                         keys=["enter"], binary=binary, symbols=symbols)
        failed, message = m.run('"patch.nxc"')
        self.assertTrue(failed or T.row("2", "Colour clash fix", "[ ON]") not in m.screens[1], "a loader not clearing the label passed")


if __name__ == "__main__":
    unittest.main()

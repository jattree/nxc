"""INF1's colours_label: the menu's name for the colours line, for a patch whose colour option is something else, such as
painted backgrounds. Through tools/nxc.py and, with the Z80 harness, through the .NEXCLASH dot command: the label and the
default when it is absent, empty or cut off; a long one cut to 16 and an unprintable byte shown as ?; what a writer
refuses; that it changes nothing but the name; the loader before the label, which shows the default and builds the same;
and a control that ignores the label, which the tests catch. Needs the zx0 compressor (NXC_ZX0_DIR)."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import test_nexclash_dot as T
import test_nexclash_toggle as TL
import test_nxc_label as L
import test_nxc_tape as TT
import test_nxc_toggle as TG

H = T.H
TMP = os.environ.get("TMPDIR")


def assemble_text(text: str):
    """A loader's binary and symbols from its source text, with the stubs it includes found beside today's source."""
    with tempfile.TemporaryDirectory(dir=TMP) as d:
        src = Path(d) / "nexclash.asm"; src.write_text(text)
        out, sym = Path(d) / "NEXCLASH", Path(d) / "nexclash.sym"
        subprocess.run(["sjasmplus", "--nologo", f"--inc={T.ROOT / 'firmware'}", f"--raw={out}", f"--sym={sym}", str(src)],
                       check=True, capture_output=True)
        symbols = {m.group(1): int(m.group(2), 16) & 0xFFFF for m in re.finditer(r"(\S+): EQU 0x([0-9A-Fa-f]+)", sym.read_text())}
        return out.read_bytes(), symbols

nxc = T.nxc
NEX = T.NEX


@TT.needs
class ColoursLabel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plain, cls.nex, cls.tap = TG.build({}, colours={"Painted": TL.PAINT})
        cls.patch = TG.build({}, colours={"Painted": TL.PAINT},
                             info=dict(publisher="Ocean, 1989", patch_by="Jon Attree", fix_label="Colour", colours_label="Backgrounds"))[0]

    def test_the_label_and_the_default(self) -> None:
        self.assertEqual(nxc.colours_label(self.patch), "Backgrounds")
        self.assertEqual(nxc.colours_label(self.plain), "Enhanced colours")
        self.assertEqual(nxc.COLOURS_LABEL, "Enhanced colours")
        self.assertEqual(nxc.COLOURS_LABEL_MAX, len(nxc.COLOURS_LABEL))
        self.assertEqual([name for kind, name, _, _ in nxc.menu_lines(self.patch) if kind == 2], ["Backgrounds"])
        self.assertEqual([name for kind, name, _, _ in nxc.menu_lines(self.plain) if kind == 2], ["Enhanced colours"])

    def test_a_writer_puts_it_with_the_menu_names(self) -> None:
        text = dict(nxc.blocks(self.patch)[1])[b"INF1"]
        self.assertTrue(text.startswith(b"publisher=Ocean, 1989\npatch_by=Jon Attree\nfix_label=Colour\ncolours_label=Backgrounds\n"), text)

    def test_it_changes_nothing_but_the_name(self) -> None:
        self.assertEqual(nxc.apply(self.patch, game=self.tap), self.nex)
        self.assertEqual(nxc.apply(self.patch, game=self.tap, colours="Painted"), nxc.apply(self.plain, game=self.tap, colours="Painted"))
        self.assertEqual(nxc.colour_sets(self.patch), ["Painted"])                     # the set keeps its own name

    def test_a_writer_refuses(self) -> None:
        for bad in ("x" * 17, "Back\n", "Fonds peints\xe9", "\x01"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "colours label"):
                TG.build({}, colours={"Painted": TL.PAINT}, info=dict(colours_label=bad))
        TG.build({}, colours={"Painted": TL.PAINT}, info=dict(colours_label="x" * 16))  # 16 is the most
        with self.assertRaisesRegex(ValueError, "first 252"):                           # pushed past what a loader reads
            TG.build({}, colours={"Painted": TL.PAINT}, info=dict(publisher="P" * 120, patch_by="N" * 100, colours_label="Backgrounds"))

    def test_a_reader_shows_the_default_or_the_first_16(self) -> None:
        for body, want in ((b"publisher=x\n", "Enhanced colours"),
                           (b"colours_label=\n", "Enhanced colours"),
                           (b"publisher=" + b"p" * 238 + b"\ncolours_label=Backgrounds\n", "Enhanced colours"),   # cut off at 252
                           (b"colours_label=" + b"y" * 30 + b"\n", "y" * 16),
                           (b"colours_label=Back\x01rounds\n", "Back?rounds"),
                           (b"colours_label=Backgrounds\ncolours_label=Other\n", "Backgrounds")):                # the first is taken
            with self.subTest(body=body[:40]):
                self.assertEqual(nxc.colours_label(L.with_inf1(self.patch, self.tap, body)), want)

    def test_set_and_credit_keep_it(self) -> None:
        f = nxc.set_credits(self.patch, self.tap, patch_by="Someone Else", colours_by="")
        self.assertEqual(nxc.colours_label(f), "Backgrounds")
        f = nxc.set_field(self.plain, self.tap, "colours_label", "Scenery")
        self.assertEqual(nxc.colours_label(f), "Scenery")
        with self.assertRaisesRegex(ValueError, "colours label"):
            nxc.set_field(self.plain, self.tap, "colours_label", "x" * 17)


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class ColoursLabelLoader(T.Base):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.patch, cls.nex, cls.tap = TG.build({"Smooth scrolling": (TL.SMOOTH, False)}, colours={"Painted": TL.PAINT},
                                               info=dict(publisher="Ocean, 1989", fix_label="Colour", colours_label="Backgrounds"))

    def go(self, keys, patch=None, **options):
        m = self.machine({"patch.nxc": patch or self.patch, "game.tap": self.tap}, keys=keys, **options)
        failed, message = m.run('"patch.nxc"')
        return m, failed, message

    def test_the_menu_line(self) -> None:
        m, failed, message = self.go(["enter"])
        self.assertFalse(failed, message)
        menu = m.screens[1]
        self.assertIn(T.row("2", "Backgrounds", "[OFF]"), menu)
        self.assertNotIn("Enhanced colours", menu)
        self.assertIn(T.row("1", "Colour", "[ ON]"), menu)
        self.assertEqual(bytes(m.written[NEX]), self.nex)

    def test_it_is_still_the_colour_set(self) -> None:
        m, failed, message = self.go(["2", "enter"])
        self.assertFalse(failed, message)
        self.assertIn(T.row("2", "Backgrounds", "[ ON]"), m.screens[-2])
        self.assertEqual(bytes(m.written[NEX]), nxc.apply(self.patch, game=self.tap, colours="Painted"))

    def test_the_default_and_what_a_reader_shows(self) -> None:
        for body, name in ((b"publisher=Ocean, 1989\n", "Enhanced colours"),
                           (b"colours_label=\n", "Enhanced colours"),
                           (b"publisher=" + b"p" * 238 + b"\ncolours_label=Backgrounds\n", "Enhanced colours"),
                           (b"colours_label=" + b"y" * 30 + b"\n", "y" * 16),
                           (b"colours_label=Back\x01rounds\n", "Back?rounds")):
            with self.subTest(body=body[:40]):
                patch = L.with_inf1(self.patch, self.tap, body)
                self.assertEqual(nxc.colours_label(patch), name)                         # the tool agrees
                m, failed, message = self.go(["enter"], patch=patch)
                self.assertFalse(failed, message)
                self.assertIn(T.row("2", name, "[OFF]"), m.screens[1])
                self.assertEqual(bytes(m.written[NEX]), self.nex)

    def test_the_loader_before_the_label(self) -> None:
        old = subprocess.run(["git", "-C", str(T.ROOT), "show", "b702d90:firmware/nexclash.asm"], capture_output=True, text=True, check=True).stdout
        binary, symbols = assemble_text(old)
        m = self.machine({"patch.nxc": self.patch, "game.tap": self.tap}, keys=["2", "enter"], binary=binary, symbols=symbols)
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertIn(T.row("2", "Enhanced colours", "[ ON]"), m.screens[-2])
        self.assertEqual(bytes(m.written[NEX]), nxc.apply(self.patch, game=self.tap, colours="Painted"))

    def test_controls(self) -> None:
        # The menu ignoring the label: the old name comes back, and the test sees it.
        binary, symbols = H.assemble([("""        ld      hl,colours_label            ; INF1's name for the colours line, if it has one
        ld      a,(hl)
        or      a
        jr      nz,.kl
""", "")])
        m = self.machine({"patch.nxc": self.patch, "game.tap": self.tap}, keys=["enter"], binary=binary, symbols=symbols)
        failed, message = m.run('"patch.nxc"')
        self.assertNotIn(T.row("2", "Backgrounds", "[OFF]"), m.screens[1])
        # The label not cleared before INF1 is read: a stale byte below the stack names the line.
        binary, symbols = H.assemble([("        ld      (colours_label),a\n", "")])
        m = self.machine({"patch.nxc": L.with_inf1(self.patch, self.tap, b"publisher=x\n"), "game.tap": self.tap},
                         keys=["enter"], binary=binary, symbols=symbols)
        failed, message = m.run('"patch.nxc"')
        self.assertTrue(failed or T.row("2", "Enhanced colours", "[OFF]") not in m.screens[1], "a loader not clearing the label passed")


if __name__ == "__main__":
    unittest.main()

"""The .NEXCLASH dot command with OPR1, on the Z80 harness: more than two options on at once, byte for byte what
tools/nxc.py writes, bare and with its menu; the rules kept on its menu as tools/nxc.py menu_settle keeps them, and said
in the help rows; and the loader before OPR1 (main at the branch point), which holds two at once for a patch whose rules
it may break, and refuses one whose OPT1 says it may not. Controls put mistakes back and show the tests catch them."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import nexclash_harness as H
import test_nexclash_dot as T
import test_nxc_toggle as TG

nxc = T.nxc
NEX = T.NEX
OLD = "11f90ba"                   # main when OPR1 was added: the loader every card had
SMOOTH = [(0x2100, 0x11), (0x2101, 0x22)]
CENTRED = [(0x2110, 0x44)]
KEYS = [(0x2120, 0x55)]
WIDE = [(0x2100, 0x66), (0x2130, 0x77)]
PAINT = [(0x2050, 0x5A)]
LEVEL = "Patch needs a newer .NEXCLASH"


def old_loader():
    """The loader at OLD, assembled with its own menu and stub."""
    with tempfile.TemporaryDirectory(dir=TG.TMP) as d:
        for name in ("nexclash.asm", "menu.asm", "nxcstub.bin"):
            data = subprocess.run(["git", "-C", str(T.ROOT), "show", f"{OLD}:firmware/{name}"], capture_output=True, check=True).stdout
            (Path(d) / name).write_bytes(data)
        out, sym = Path(d) / "NEXCLASH", Path(d) / "nexclash.sym"
        subprocess.run(["sjasmplus", "--nologo", f"--raw={out}", f"--sym={sym}", str(Path(d) / "nexclash.asm")], check=True, capture_output=True)
        import re
        symbols = {m.group(1): int(m.group(2), 16) & 0xFFFF for m in re.finditer(r"(\S+): EQU 0x([0-9A-Fa-f]+)", sym.read_text())}
        return out.read_bytes(), symbols


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class RulesLoader(T.Base):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        toggles = {"Smooth scrolling": (SMOOTH, False), "Centred view": (CENTRED, True), "Cursor keys": (KEYS, True), "Wide": (WIDE, False)}
        cls.patch, cls.nex, cls.tap = TG.build(toggles, colours={"Colour": PAINT}, proof={"toggle_%d" % n: "checked" for n in (1, 2, 3)},
                                               rules=[(nxc.RULE_NEEDS | nxc.RULE_MENU_ONLY, "Centred view", "Smooth scrolling"),
                                                      (nxc.RULE_EXCLUDES, "Wide", "Smooth scrolling")])
        cls.hard = nxc.set_rules(cls.patch, cls.tap, [(nxc.RULE_NEEDS, "Centred view", "Smooth scrolling"),
                                                      (nxc.RULE_EXCLUDES, "Wide", "Smooth scrolling")])
        # 1 fix, 2 Enhanced colours, 3 Smooth scrolling, 4 Centred view, 5 Cursor keys, 6 Wide (no trainers)

    def go(self, keys, patch=None, binary=None, symbols=None):
        m = self.machine({"patch.nxc": patch or self.patch, "game.tap": self.tap}, keys=keys, binary=binary, symbols=symbols)
        failed, message = m.run('"patch.nxc"')
        return m, failed, message

    def test_four_on_at_once(self) -> None:
        on = dict(colours="Colour", toggles=["Smooth scrolling", "Centred view", "Cursor keys"])
        m, failed, message = self.go(["2", "4", "5", "enter"])
        self.assertFalse(failed, message)
        self.assertEqual(m.clean(), [])
        self.assertEqual(bytes(m.written[NEX]), nxc.apply(self.patch, game=self.tap, **on))
        self.assertEqual(bytes(m.written[NEX]), TG.variant(self.nex, PAINT + SMOOTH + CENTRED + KEYS))
        screen = m.screens[3].splitlines()                      # as the third key comes (screens[0] is before the menu): after Centred view's
        self.assertIn(T.row("3", "Smooth scrolling", "[ ON]"), m.screens[3])
        self.assertIn("Centred view:", screen)
        self.assertIn("Also on: Smooth scrolling", screen)
        m, failed, message = self.go(["2", "4", "5", "space"])
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), nxc.apply_menu(self.patch, self.tap, **on))

    def test_the_rules_as_the_tool_keeps_them(self) -> None:
        lines = nxc.menu_lines(self.patch)
        counts = {i: (len(l[3]) if l[0] == 2 else 1) for i, l in enumerate(lines) if l[0] in (2, 3)}
        lr = nxc.line_rules(self.patch, nxc.rules_of(self.patch))
        for keys in (["6", "3"], ["3", "6"], ["4", "6"], ["6", "4"], ["4", "3"], ["2", "6", "4", "5"], ["5", "4", "6", "2", "2"]):
            with self.subTest(keys=keys):
                states = [0] * len(lines); states[0] = 1
                for k in keys:
                    nxc.menu_key(states, int(k) - 1, counts, lr)
                on = {lines[i][1]: v for i, v in enumerate(states) if i in counts and v}
                m, failed, message = self.go(keys + ["enter"])
                self.assertFalse(failed, message)
                want = nxc.apply(self.patch, game=self.tap, colours="Colour" if on.get("Enhanced colours") else None,
                                 toggles=[n for n in on if n != "Enhanced colours"])
                self.assertEqual(bytes(m.written[NEX]), want)
        m, failed, message = self.go(["3", "6", "enter"])
        self.assertIn("Also off: Smooth scrolling", m.screens[3])

    def test_the_loader_before_rules(self) -> None:
        binary, symbols = old_loader()
        m, failed, message = self.go(["2", "4", "5", "enter"], binary=binary, symbols=symbols)
        self.assertFalse(failed, message)                       # two at once: the third key does nothing
        self.assertIn(T.row("5", "Cursor keys", "[OFF]"), m.screens[-2])
        self.assertEqual(bytes(m.written[NEX]), nxc.apply(self.patch, game=self.tap, colours="Colour", toggles=["Centred view"]))
        m, failed, message = self.go(["3", "6", "enter"], binary=binary, symbols=symbols)
        self.assertTrue(failed)                                 # the pair the rules exclude overlaps: refused, nothing kept
        self.assertNotIn(NEX, m.written)
        m, failed, message = self.go(["enter"], patch=self.hard, binary=binary, symbols=symbols)
        self.assertEqual((failed, message), (True, LEVEL))

    def test_controls(self) -> None:
        # The rules never kept: Centred view alone is written, which the menu would not let be.
        binary, symbols = H.assemble([("""        call    md_rules
""", """        nop
        nop
        nop
""")])
        m, failed, message = self.go(["4", "enter"], binary=binary, symbols=symbols)
        self.assertNotEqual(bytes(m.written.get(NEX, b"")), nxc.apply(self.patch, game=self.tap, toggles=["Centred view", "Smooth scrolling"]))
        # The rules read from the wrong place: refused, or not kept.
        binary, symbols = H.assemble([("""        ld      c,a
        add     a,a
        add     a,c
        ld      c,a
        ld      b,0
        add     hl,bc
        ld      b,(hl)""", """        ld      c,a
        add     a,a
        add     a,c
        ld      c,a
        ld      b,0
        nop
        ld      b,(hl)""")])
        m, failed, message = self.go(["4", "enter"], binary=binary, symbols=symbols)
        self.assertTrue(failed or bytes(m.written.get(NEX, b"")) != TG.variant(self.nex, SMOOTH + CENTRED))


if __name__ == "__main__":
    unittest.main()

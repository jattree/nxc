"""The .NEXCLASH dot command with a SET3 (an option that needs more memory and adds banks of its own), on the Z80
harness, with NextZXOS saying 2MB (224 8K banks) and 1MB (96): on 2MB the option is offered and makes exactly what
tools/nxc.py makes, alone and with a trainer, and SPACE writes the bare .nex as ENTER does; on 1MB its line reads N/A
with the help "Needs a 2MB Next", its key does nothing and the base is made; with another set chosen it is refused as
needing a newer loader; and the loader before SET3 shows no line and makes the base. Controls break the loader and show
the tests catch it."""
from __future__ import annotations

import os
import subprocess
import unittest

import test_nexclash_dot as T
import test_nxc_ram as R

H = T.H
nxc = T.nxc
NEX, Z80 = T.NEX, T.Z80
LIVES = [(0x2010, 0xAB)]


def old_loader(commit: str):
    """The dot command as it was at a commit, assembled with its own menu.asm and stubs beside it."""
    import re, tarfile, io, tempfile
    from pathlib import Path
    tar = subprocess.run(["git", "-C", str(T.ROOT), "archive", commit, "firmware"], capture_output=True, check=True).stdout
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
        tarfile.open(fileobj=io.BytesIO(tar)).extractall(d, filter="data")
        src = Path(d) / "firmware" / "nexclash.asm"; out = Path(d) / "NEXCLASH"; sym = Path(d) / "nexclash.sym"
        subprocess.run(["sjasmplus", "--nologo", f"--raw={out}", f"--sym={sym}", str(src)], check=True, capture_output=True, cwd=src.parent)
        symbols = {m.group(1): int(m.group(2), 16) & 0xFFFF for m in re.finditer(r"(\S+): EQU 0x([0-9A-Fa-f]+)", sym.read_text())}
        return out.read_bytes(), symbols


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class BigLoader(T.Base):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.patch, cls.nex, cls.tap, cls.big = R.build(trainers=[("Lives", [(2, 0x2010, 0xAB)])])
        cls.patch2, cls.nex2, _, cls.big2 = R.build(language={"Deutsch": [(0x2400, 0x44)]})

    def go(self, keys, patch=None, total_pages=224, **options):
        m = self.machine({"patch.nxc": patch or self.patch, "game.tap": self.tap}, keys=keys, total_pages=total_pages, **options)
        failed, message = m.run('"patch.nxc"')
        return m, failed, message

    def test_2mb_offers_it(self) -> None:
        m, failed, message = self.go(["enter"])
        self.assertFalse(failed, message)
        self.assertIn(T.row("3", "Enhanced colours", "[OFF]"), m.screens[1])
        self.assertEqual(bytes(m.written[NEX]), self.nex)
        for keys, args in ((["3", "enter"], dict(colours="Enhanced")), (["1", "3", "enter"], dict(colours="Enhanced", chosen=[1])),
                           (["3", "space"], dict(colours="Enhanced")), (["3", "3", "enter"], dict())):
            with self.subTest(keys=keys):
                m, failed, message = self.go(keys)
                self.assertFalse(failed, message)
                self.assertEqual(m.clean(), [])
                self.assertEqual(bytes(m.written[NEX]), nxc.apply(self.patch, game=self.tap, ram_top=111, **args))
        m, failed, message = self.go(["3", "enter"])
        self.assertEqual(bytes(m.written[NEX]), self.big)

    def test_1mb_shows_it_and_makes_the_base(self) -> None:
        m, failed, message = self.go(["3", "enter"], total_pages=96)
        self.assertFalse(failed, message)
        self.assertEqual(m.clean(), [])
        self.assertIn(T.row("3", "Enhanced colours", "[N/A]"), m.screens[-2])
        self.assertIn("Needs a 2MB Next", m.screens[-2])
        self.assertEqual(bytes(m.written[NEX]), self.nex)
        m, failed, message = self.go(["1", "3", "enter"], total_pages=96)
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), nxc.apply(self.patch, game=self.tap, chosen=[1], ram_top=47))

    def test_too_little_memory_found_only_at_the_end(self) -> None:
        # NextZXOS not saying before the menu: offered; then the check at ENTER refuses with 1MB.
        m, failed, message = self.go(["3", "enter"], total_pages=None)
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), self.big)

    def test_with_another_set_it_needs_a_newer_loader(self) -> None:
        m, failed, message = self.go(["2", "3", "enter"], patch=self.patch2)
        self.assertTrue(failed)
        self.assertIn("newer", message)
        self.assertNotIn(NEX, m.written)
        for keys, args in ((["2", "enter"], dict(colours="Enhanced")), (["3", "enter"], dict(language="Deutsch"))):
            with self.subTest(keys=keys):
                m, failed, message = self.go(keys, patch=self.patch2)
                self.assertFalse(failed, message)
                self.assertEqual(bytes(m.written[NEX]), nxc.apply(self.patch2, game=self.tap, **args))

    def test_alternatives(self) -> None:
        patch, nex, tap, big = R.build(alt=lambda n: R.big_build(n, ((0x2300, 0x66),)))
        for keys, name in ((["2", "enter"], "Enhanced"), (["2", "2", "enter"], "Orig. pace"), (["2", "2", "2", "enter"], None)):
            with self.subTest(keys=keys):
                m, failed, message = self.go(keys, patch=patch)
                self.assertFalse(failed, message)
                self.assertEqual(m.clean(), [])
                self.assertEqual(bytes(m.written[NEX]), nxc.apply(patch, game=tap, colours=name))
        m, failed, message = self.go(["2", "2", "enter"], patch=patch)
        self.assertIn(T.row("2", "Enhanced colours", "[Orig. pace]"), m.screens[-2])
        m, failed, message = self.go(["2", "enter"], patch=patch, total_pages=96)
        self.assertIn(T.row("2", "Enhanced colours", "[N/A]"), m.screens[-2])
        self.assertEqual(bytes(m.written[NEX]), nex)

    def test_the_loader_before_set3(self) -> None:
        binary, symbols = old_loader("ea2a22f")
        m = self.machine({"patch.nxc": self.patch, "game.tap": self.tap}, keys=["3", "enter"], binary=binary, symbols=symbols)
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertNotIn("Enhanced", m.screens[1])
        self.assertEqual(bytes(m.written[NEX]), self.nex)

    def test_controls(self) -> None:
        # The added banks not made from zeros: the build is refused (no source) and nothing is written.
        binary, symbols = H.assemble([("""        call    big_has                     ; a bank the chosen SET3 adds: from zeros
        jr      nz,.ok
""", "")])
        m = self.machine({"patch.nxc": self.patch, "game.tap": self.tap}, keys=["3", "enter"], binary=binary, symbols=symbols, total_pages=224)
        failed, message = m.run('"patch.nxc"')
        self.assertTrue(failed)
        self.assertNotIn(NEX, m.written)
        # The length not grown: the output fails its check and is deleted.
        binary, symbols = H.assemble([("""        ld      hl,want+4
        ld      de,work32
        call    add32
""", "")])
        m = self.machine({"patch.nxc": self.patch, "game.tap": self.tap}, keys=["3", "enter"], binary=binary, symbols=symbols, total_pages=224)
        failed, message = m.run('"patch.nxc"')
        self.assertTrue(failed)
        self.assertEqual(m.clean(), [])
        # The memory never asked: on 1MB the line is offered and the build refused only at ENTER.
        binary, symbols = H.assemble([("""        ld      a,1
        ld      (big_off),a
""", "")])
        m = self.machine({"patch.nxc": self.patch, "game.tap": self.tap}, keys=["3", "enter"], binary=binary, symbols=symbols, total_pages=96)
        failed, message = m.run('"patch.nxc"')
        self.assertTrue(failed)
        self.assertIn("RAM", message)


if __name__ == "__main__":
    unittest.main()

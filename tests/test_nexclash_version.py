"""INF1's version on the menu's Patch: row (row 22), in both menus: the .NEXCLASH dot command's (firmware/nexclash.asm
builds the description from the patch) and a .nex's that carries its menu (firmware/nxcstub.asm, the description from
tools/nxc.py), both drawn by firmware/menu.asm. The row and its colours are the same in each and as tools/nxc.py's
credit_line has it: the version right-aligned after a v; a long patch_by cut, never the version; the version alone without
patch_by; and without a version the row as it always was. The .nex the dot command writes is byte for byte the tool's."""
from __future__ import annotations

import unittest

import nex_harness as NH
import test_nexclash_dot as T
import test_nxc_toggle as TG

nxc = T.nxc

CASES = (("normal", dict(patch_by="Jon Attree", version="1.0"), "Patch: Jon Attree           v1.0"),
         ("long patch_by", dict(patch_by="A Very Long Patch Maker Name", version="12345678"), "Patch: A Very Long Pat v12345678"),
         ("no patch_by", dict(version="1.0"), " " * 28 + "v1.0"),
         ("no version", dict(patch_by="Jon Attree"), "Patch: Jon Attree"))


def nex_menu(f: bytes, game: bytes):
    """The in-.nex menu's text rows and attributes, as the first key comes."""
    m = NH.NexMachine(nxc.apply_menu(f, game), {}, keys=("enter",))
    m.final_entry = nxc.apply(f, game=game)[139]
    attrs = []
    real = m.keyboard

    def spy(row):
        if not attrs and m.key_state == "gap" and m.key_count == 6000:
            attrs.append(m.attrs())
        return real(row)
    m.keyboard = spy
    m.run_to(0xC000)
    return m.screens[0].splitlines(), attrs[0]


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class VersionRow(T.Base):
    def loader_menu(self, f: bytes, game: bytes):
        m = self.machine({"patch.nxc": f, "game.tap": game}, keys=["space"])
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[T.NEX]), nxc.apply_menu(f, game))
        return m.screens[1].splitlines(), m.menu_attrs[-1]

    def test_the_row_in_both_menus(self) -> None:
        for name, info, want in CASES:
            with self.subTest(name):
                f, _, tap = TG.build({}, info=dict(publisher="Ocean, 1989", **info))
                text, attrs = self.loader_menu(f, tap)
                ntext, nattrs = nex_menu(f, tap)
                self.assertEqual(text[22], want)
                self.assertEqual(ntext[22], want)
                self.assertEqual(nxc.credit_line(f), want)
                self.assertEqual(attrs[22], bytes((0x47,) * 32))                 # the row's white
                self.assertEqual(nattrs[22], attrs[22])
                self.assertEqual(text[:22], ntext[:22])

    def test_without_a_version_nothing_changes(self) -> None:
        plain, _, tap = TG.build({}, info=dict(publisher="Ocean, 1989", patch_by="Jon Attree"))
        versioned = nxc.set_version(plain, tap, "1.0")
        text, attrs = self.loader_menu(plain, tap)
        vtext, vattrs = self.loader_menu(versioned, tap)
        self.assertEqual(text[22], "Patch: Jon Attree")
        self.assertEqual(text[:22] + text[23:], vtext[:22] + vtext[23:])        # only row 22 differs
        self.assertEqual(attrs, vattrs)
        self.assertEqual(nxc.menu_description(plain)[0][0], nxc.DESC_FIXED)      # the description as before

    def test_a_cut_version_and_unprintable(self) -> None:
        import test_nxc_label as L
        f, _, tap = TG.build({}, info=dict(publisher="Ocean, 1989", patch_by="Jon Attree"))
        f = L.with_inf1(f, tap, b"publisher=Ocean, 1989\npatch_by=Jon Attree\nversion=1\x012345678\n")
        text, _ = self.loader_menu(f, tap)
        self.assertEqual(text[22], "Patch: Jon Attree      v1?234567")
        self.assertEqual(nxc.credit_line(f), text[22])
        self.assertEqual(nex_menu(f, tap)[0][22], text[22])


if __name__ == "__main__":
    unittest.main()

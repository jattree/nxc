"""The .NEXCLASH dot command with tape targets, on the Z80 harness: the made-up game of tape_game.py from a .tap and a .tzx,
the clash fix on and off, trainers, a set, a 48K game, and every refusal of a damaged table, each against tools/nxc.py byte
for byte. A control after each kind restores a mistake in the loader's source and shows that the test catches it."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import tape_game as G
import test_nexclash_dot as T
import test_nxc_tape as P

H = T.H
nxc = T.nxc
NEX, Z80 = T.NEX, T.Z80
TMP = os.environ.get("TMPDIR")
DAMAGED = "Patch damaged: get it again"
LEVEL = "Patch needs a newer .NEXCLASH"
WRONG = "Wrong game file for this patch"
GAME_BAD = "Game file is damaged"


def with_colours(patch_args=None):
    """The made-up game with a colour set, so that a tape's pages come after a set's."""
    blocks = G.data_blocks()
    start = G.start_banks(blocks)
    nex, extra = G.build(start, blocks, nxc.ORDER)
    painted = bytearray(nex)
    painted[512 + 16384 + 0x2050] ^= 0x5A                     # bank 2, which the tape fills
    with tempfile.TemporaryDirectory(dir=TMP) as d:
        tmp = Path(d)
        for name, data in (("game.tap", G.tap(blocks)), ("start.z80", G.start_z80(start)), ("o.nex", nex), ("p.nex", bytes(painted))):
            (tmp / name).write_bytes(data)
        patch, _ = nxc.make(str(tmp / "game.tap"), str(tmp / "o.nex"), dict(title="Tape Game", file="game.tap"), dict(build="t", publisher="T, 2026"),
                            colours={"Painted": str(tmp / "p.nex")}, trainer_blocks=[nxc.trn1("Lives", [(2, 0x2010, 0xAB)])],
                            start=str(tmp / "start.z80"), tape_banks=extra)
    return patch, nex, bytes(painted), G.tap(blocks)


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class TapeLoader(T.Base):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.patch, cls.nex, cls.tap, cls.tzx, cls.z80, cls.banks = P.made()

    def go(self, patch=None, files=None, keys=("enter",), **options):
        m = self.machine({"patch.nxc": self.patch if patch is None else patch, **(files if files is not None else {"game.tap": self.tap})},
                         keys=keys, **options)
        failed, message = m.run('"patch.nxc"')
        return m, failed, message

    def made_it(self, m, failed, message, name, want) -> None:
        self.assertFalse(failed, message)
        self.assertEqual(m.clean(), [])
        self.assertEqual(bytes(m.written[name]), want)

    def test_the_nex_from_the_tap_and_from_the_tzx(self) -> None:
        for files in ({"game.tap": self.tap}, {"game.tzx": self.tzx}, {"game.tap": b"x" * 9, "game.tzx": self.tzx}):
            with self.subTest(files=sorted(files)):
                m, failed, message = self.go(files=files)
                self.made_it(m, failed, message, NEX, self.nex)

    def test_a_trainer_on_the_nex(self) -> None:
        m, failed, message = self.go(keys=["1", "enter"])
        self.made_it(m, failed, message, NEX, nxc.apply(self.patch, game=self.tap, chosen=[1]))

    def test_the_clash_fix_off_is_the_start_checked_with_or_without_a_trainer(self) -> None:
        for keys, chosen in ((["2", "enter"], []), (["1", "2", "enter"], [1])):
            for files, tape in (({"game.tap": self.tap}, self.tap), ({"game.tzx": self.tzx}, self.tzx)):
                with self.subTest(keys=keys, tape=sorted(files)):
                    m, failed, message = self.go(files=files, keys=keys)
                    self.made_it(m, failed, message, Z80, nxc.original_with_pokes(self.patch, tape, chosen))
                    self.assertNotIn(NEX, m.written)

    def test_a_48k_game(self) -> None:
        patch, nex, tap, tzx, z80, banks = P.made(is128=False)
        m, failed, message = self.go(patch, {"game.tzx": tzx})
        self.made_it(m, failed, message, NEX, nex)
        m, failed, message = self.go(patch, {"game.tap": tap}, keys=["1", "2", "enter"])
        self.made_it(m, failed, message, Z80, nxc.original_with_pokes(patch, tap, [1]))

    def test_with_a_colour_set_the_pages_add_up(self) -> None:
        patch, nex, painted, tap = with_colours()
        self.assertEqual(nxc.apply(patch, game=tap, colours="Painted"), painted)
        m, failed, message = self.go(patch, {"game.tap": tap}, keys=["3", "enter"])
        self.made_it(m, failed, message, NEX, painted)
        self.assertEqual(m.peak_pages, 12)
        m, failed, message = self.go(patch, {"game.tap": tap}, keys=["3", "enter"], free_pages=11)
        self.assert_refused(m, failed, message, "Needs 96K free RAM")

    def test_not_enough_ram_for_the_table(self) -> None:
        m, failed, message = self.go(free_pages=8)
        self.assert_refused(m, failed, message, "Needs 72K free RAM")

    def test_the_wrong_tape(self) -> None:
        wrong = bytearray(self.tap)
        wrong[-1] ^= 1
        m, failed, message = self.go(files={"game.tap": bytes(wrong)})
        self.assert_refused(m, failed, message, WRONG)

    def test_every_damaged_table_is_refused_with_nothing_written(self) -> None:
        rules = P.TableRules("test_every_rule")
        P.TableRules.setUpClass()
        r = P.TableRules
        c, s, h = list(r.parts["copies"]), list(r.parts["sites"]), r.parts["header"]
        k, src, n, b, o = c[0]
        tables = {
            "past the last block": r.remade(rules, copies=[(len(r.blocks), 0, 1, b, o)] + c[1:]),
            "past the block's end": r.remade(rules, copies=[(k, r.blocks[k][1] - n + 1, n, b, o)] + c[1:]),
            "the 1025th block": r.remade(rules, copies=[(1024, 0, 1, b, o)] + c[1:]),
            "a bank of 112": r.remade(rules, copies=c + [(k, 0, 1, 112, 0)]),
            "a length of 0": r.remade(rules, copies=[(k, src, 0, b, o)] + c[1:]),
            "past the bank's end": r.remade(rules, copies=[(k, 0, 17, b, 16380)] + c[1:]),
            "copies out of order": r.remade(rules, copies=c[1:2] + c[:1] + c[2:]),
            "sites out of order": r.remade(rules, sites=s[::-1]),
            "a site of length 0": r.remade(rules, sites=[(s[0][0], s[0][1], b"")] + s[1:]),
            "a site past its bank": r.remade(rules, sites=s + [(1, 16383, b"ab")]),
            "the wrong CRC": r.remade(rules, crc=r.parts["crc"] ^ 1),
            "a header saying version 3": r.remade(rules, header=h[:30] + b"\x36\x00" + h[32:]),
            "a header with a PC in it": r.remade(rules, header=h[:6] + b"\x01\x00" + h[8:]),
            "hardware mode 4": r.remade(rules, header=h[:34] + b"\x04" + h[35:]),
            "a byte left over": r.remade(rules) + b"\0",
            "cut short": r.remade(rules)[:-1],
            "too short for its counts": r.remade(rules)[:62],
        }
        listed = P.with_table(self.patch, self.tap, r.remade(rules, copies=c + [(k, 0, 1, 30, 0)]))
        for name, table in tables.items():
            patch = P.with_table(self.patch, self.tap, table)
            for keys in (["enter"], ["2", "enter"]):
                with self.subTest(name, keys=keys):
                    with self.assertRaises(nxc.Wrong):
                        nxc.apply(patch, game=self.tap)
                    m, failed, message = self.go(patch, keys=keys)
                    self.assert_refused(m, failed, message, DAMAGED)
        m, failed, message = self.go(listed)
        self.assert_refused(m, failed, message, DAMAGED)
        m, failed, message = self.go(listed, keys=["2", "enter"])
        self.made_it(m, failed, message, Z80, nxc.original_with_pokes(listed, self.tap, []))

    def test_the_structure_before_the_menu(self) -> None:
        s = P.Structure("test_the_clear_head")
        P.Structure.setUpClass()
        def heads(new):
            def edit(bl, st):
                for e in bl:
                    if e[0] == nxc.TAPE_TAG:
                        e[1] = new + nxc.parse_tap1(e[1])["data"]
            return edit
        def opt(value):
            def edit(bl, st):
                for e in bl:
                    if e[0] == b"OPT1":
                        e[1] = value
            return edit
        def drop(bl, st):
            bl[:] = [e for e in bl if e[0] != nxc.TAPE_TAG]
        def split(bl, st):
            for n, e in enumerate(bl):
                if e[0] == nxc.TAPE_TAG:
                    data = nxc.parse_tap1(e[1])["data"]
                    bl[n:n + 1] = [[e[0], b"\0\x01\0" + data], [e[0], b"\0\x01\x01" + data]]
                    return
        cases = {"a target missing": (heads(b"\0\x01\0"), DAMAGED), "a target twice": (heads(b"\0\x03\0\x01\x01"), DAMAGED),
                 "a target that is not there": (heads(b"\0\x03\0\x01\x02"), DAMAGED), "no targets": (heads(b"\0\0"), DAMAGED),
                 "no table": (drop, DAMAGED), "a stream twice": (split, DAMAGED), "no tape flag": (opt(b"\x01\x00\x14"), DAMAGED),
                 "an unknown flag": (opt(b"\x01\x05\x14"), LEVEL)}
        for name, (edit, said) in cases.items():
            with self.subTest(name):
                patch = T.rekey(self.patch, self.tap, edit)
                with self.assertRaises(nxc.Wrong):
                    nxc.apply(patch, game=self.tap)
                m, failed, message = self.go(patch)
                self.assert_refused(m, failed, message, said)
                self.assertEqual(m.opened, ["patch.nxc"])

    def test_a_tape_and_a_snapshot_of_its_start(self) -> None:
        patch, nex, tap, tzx, z80, banks = P.made(tzx_too=False, tape_banks=())
        both = nxc.add_target(patch, tap, z80, nxc.KIND_Z80, dict(file="start.z80"))
        for files in ({"start.z80": z80}, {"game.tap": tap}):
            with self.subTest(files=sorted(files)):
                m, failed, message = self.go(both, files)
                self.made_it(m, failed, message, NEX, nex)

    def test_a_cut_or_mixed_file_stops_before_anything_is_written(self) -> None:
        said = "NEXCLASH cut or mixed: recopy it"
        one = H.FIRST_PART + self.symbols["ov_size"]
        two = one + self.symbols["tape1_size"]
        for name, binary in (("no tape parts", self.binary[:one]), ("the first cut short", self.binary[:two - 1]), ("the second cut short", self.binary[:-1]),
                             ("the first mixed", self.binary[:two - 4] + b"XXXX" + self.binary[two:]), ("the second mixed", self.binary[:-4] + b"XXXX")):
            for keys in (["enter"], ["2", "enter"]):
                with self.subTest(name, keys=keys):
                    m = self.machine({"patch.nxc": self.patch, "game.tap": self.tap}, keys=keys, binary=binary)
                    failed, message = m.run('"patch.nxc"')
                    self.assertEqual((failed, message), (True, said))
                    self.assertEqual(m.written, {})
                    self.assertEqual(m.clean(), [])

    def test_measure(self) -> None:
        m, failed, message = self.go()
        self.assertFalse(failed, message)
        print("\nTape, the made-up game: %d T-states from start to end, %d pages at most" % (m.ticks, m.peak_pages))

    def test_controls(self) -> None:
        """Each mistake, put back in the loader, is caught by a test above."""
        def run(replace, **kw):
            binary, symbols = H.assemble(replace)
            m = self.machine({"patch.nxc": kw.get("patch", self.patch), **kw.get("files", {"game.tap": self.tap})}, keys=kw.get("keys", ("enter",)),
                             binary=binary, symbols=symbols)
            try:
                failed, message = m.run('"patch.nxc"')
            except H.Hung as e:
                return True, str(e), m
            return failed, message, m
        r = P.TableRules
        r.setUpClass()
        rules = P.TableRules("test_every_rule")
        c = list(r.parts["copies"])
        order = P.with_table(self.patch, self.tap, r.remade(rules, copies=c[1:2] + c[:1] + c[2:]))
        crc = P.with_table(self.patch, self.tap, r.remade(rules, crc=r.parts["crc"] ^ 1))
        controls = {
            "no order check": ([("        jr      c,.later\n        jp      nz,bad_patch\n", "        jr      .later\n        jp      nz,bad_patch\n")], dict(patch=order)),
            "no CRC check": ([("        cpl\n        cp      (hl)\n        jp      nz,bad_patch\n        inc     hl\n        inc     de\n        djnz    .c\n        ret",
                               "        cpl\n        cp      (hl)\n        nop\n        nop\n        nop\n        inc     hl\n        inc     de\n        djnz    .c\n        ret")], dict(patch=crc)),
        }
        for name, (replace, kw) in controls.items():
            with self.subTest(name):
                failed, message, m = run(replace, **kw)
                self.assertFalse(failed, f"{name}: the broken loader was still refused: {message}")


if __name__ == "__main__":
    unittest.main()

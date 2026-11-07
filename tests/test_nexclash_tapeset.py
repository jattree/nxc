"""The .NEXCLASH dot command with a target of two tape files, on the Z80 harness: the made-up game of tape_game.py split
across a side A (.tap) and a side B (.tzx), against tools/nxc.py byte for byte; the clash fix off; another release as a
full set; the second file missing, short, changed or swapped, each refused with its message; the options flag; a trainer;
and the memory a tape with two colour sets needs. Controls restore a mistake in the loader and show the tests catch it."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import tape_game as G
import test_nexclash_dot as T
import test_nxc_tapeset as S

H = T.H
nxc = T.nxc
NEX, Z80 = T.NEX, T.Z80
TMP = os.environ.get("TMPDIR")
DAMAGED = "Patch damaged: get it again"
WRONG = "Wrong game file for this patch"
NOT_THERE = "Game not beside the patch"
A, B = "side a.tap", "side b.tzx"


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class SetLoader(T.Base):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.d = tempfile.TemporaryDirectory(dir=TMP)
        cls.patch, cls.nex, cls.a, cls.b, cls.z80, cls.start, _ = S.made_set(Path(cls.d.name))
        cls.game = nxc.FileSet([cls.a, cls.b], [nxc.KIND_TAP, nxc.KIND_TZX])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.d.cleanup()
        super().tearDownClass()

    def go(self, patch=None, files=None, keys=("enter",), **options):
        m = self.machine({"patch.nxc": self.patch if patch is None else patch, **(files if files is not None else {A: self.a, B: self.b})},
                         keys=keys, **options)
        failed, message = m.run('"patch.nxc"')
        return m, failed, message

    def made_it(self, m, failed, message, name, want) -> None:
        self.assertFalse(failed, message)
        self.assertEqual(m.clean(), [])
        self.assertEqual(bytes(m.written[name]), want)

    def named(self, m, name) -> None:
        text = m.printed.decode("latin-1")
        self.assertIn("Needs this game file:", text)
        self.assertIn(name, text)

    def test_the_nex_from_both_files(self) -> None:
        m, failed, message = self.go()
        self.made_it(m, failed, message, NEX, self.nex)
        self.assertEqual(self.nex, nxc.apply(self.patch, game=self.game))

    def test_a_trainer_and_the_clash_fix_off(self) -> None:
        m, failed, message = self.go(keys=["1", "enter"])
        self.made_it(m, failed, message, NEX, nxc.apply(self.patch, game=self.game, chosen=[1]))
        for keys, chosen in ((["2", "enter"], []), (["1", "2", "enter"], [1])):
            with self.subTest(keys=keys):
                m, failed, message = self.go(keys=keys)
                self.made_it(m, failed, message, Z80, nxc.original_with_pokes(self.patch, self.game, chosen))

    def test_another_release_as_a_full_set(self) -> None:
        blocks = G.data_blocks()
        a2, b2 = S.tzx10(blocks[:S.SPLIT]), G.tap(blocks[S.SPLIT:])
        other = nxc.FileSet([a2, b2], [nxc.KIND_TZX, nxc.KIND_TAP])
        f = nxc.add_target(self.patch, self.game, other, nxc.KIND_TZX, dict(file=["other a.tzx", "other b.tap"]))
        m, failed, message = self.go(f, {"other a.tzx": a2, "other b.tap": b2})
        self.made_it(m, failed, message, NEX, self.nex)
        m, failed, message = self.go(f)
        self.made_it(m, failed, message, NEX, self.nex)

    def test_the_second_file_missing(self) -> None:
        m, failed, message = self.go(files={A: self.a})
        self.assert_refused(m, failed, message, NOT_THERE)
        self.named(m, B)

    def test_the_second_file_short(self) -> None:
        m, failed, message = self.go(files={A: self.a, B: self.b[:-1]})
        self.assert_refused(m, failed, message, WRONG)
        self.named(m, B)

    def test_the_second_file_changed(self) -> None:
        wrong = bytearray(self.b)
        wrong[len(wrong) // 2] ^= 1
        m, failed, message = self.go(files={A: self.a, B: bytes(wrong)})
        self.assert_refused(m, failed, message, WRONG)

    def test_the_files_swapped(self) -> None:
        m, failed, message = self.go(files={A: self.b, B: self.a})
        self.assert_refused(m, failed, message, WRONG)
        self.named(m, A)

    def test_the_first_file_missing(self) -> None:
        m, failed, message = self.go(files={B: self.b})
        self.assert_refused(m, failed, message, NOT_THERE)
        self.named(m, A)

    def test_only_sets_must_say_so(self) -> None:
        def opt(bl, st):
            for e in bl:
                if e[0] == b"OPT1":
                    e[1] = bytes((1, nxc.OPT_TAPE, e[1][2]))
        m, failed, message = self.go(T.rekey(self.patch, self.a + self.b, opt))
        self.assert_refused(m, failed, message, DAMAGED)

    def test_a_damaged_set_head(self) -> None:
        def head(value):
            def edit(bl, st):
                for e in bl:
                    if e[0] == b"TGT1":
                        d = bytearray(e[1]); d[30] = value; e[1] = bytes(d)
            return edit
        for n in (1, 9):
            with self.subTest(n=n):
                m, failed, message = self.go(T.rekey(self.patch, self.a + self.b, head(n)))
                self.assert_refused(m, failed, message, DAMAGED)

    def test_a_copy_naming_a_third_file(self) -> None:
        import test_nxc_tape as P
        table = P.table_of(self.patch, self.a + self.b)
        t = nxc.parse_tape_table(table, (self.game, nxc.KIND_TAP))
        copies = [((2 << nxc.FILE_SHIFT) | (k & nxc.BLOCK_MASK) if k >> nxc.FILE_SHIFT == 1 else k, s, n, b, o) for k, s, n, b, o in t["copies"]]
        bad = nxc.tape_table(t["header"], t["crc"], copies, t["sites"])
        patch = P.with_table(self.patch, self.a + self.b, bad)
        with self.assertRaises(nxc.Wrong):
            nxc.apply(patch, game=self.game)
        m, failed, message = self.go(patch)
        self.assert_refused(m, failed, message, DAMAGED)

    def test_controls(self) -> None:
        # The second file never opened: the bank built from the first file alone.
        m, failed, message = self.control([("""        ld      a,(set_n)                   ; a set: the copy's file open
        or      a
        call    nz,bank_switch
""", "")])
        self.assertTrue(failed or bytes(m.written.get(NEX, b"")) != self.nex, "a loader reading every copy from the first file passed")
        # The second file not keyed: the wrap cannot be right.
        m, failed, message = self.control([("""        call    part_more                   ; a set's further files, in order
""", "")])
        self.assertTrue(failed, "a loader keying only the first file passed")
        # Lengths of the further files not checked: a short side B goes on until the key says it is wrong, unnamed.
        m, failed, message = self.control([("""        ld      hl,msg_wrong_game
        jp      nz,fail_hl
        xor     a
        ld      (need_name),a""", """        xor     a
        ld      (need_name),a""")], files={A: self.a, B: self.b[:-1]})
        self.assertNotIn(B, m.printed.decode("latin-1"))

    def control(self, replace, files=None, keys=("enter",)):
        binary, symbols = H.assemble(replace)
        return self.go(files=files, keys=keys, binary=binary, symbols=symbols)


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class TapeMemory(T.Base):
    def test_a_tape_and_two_sets_say_96k(self) -> None:
        """A tape's table (3 pages) and the sets' 3 pages, however many are chosen, over the 6 every run takes: 12 pages, 96K."""
        blocks = G.data_blocks()
        start = G.start_banks(blocks)
        nex, extra = G.build(start, blocks, nxc.ORDER)
        painted, spoken = bytearray(nex), bytearray(nex)
        painted[512 + 16384 + 0x2050] ^= 0x5A
        spoken[512 + 16384 + 0x2060] ^= 0x33
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            tmp = Path(d)
            for name, data in (("game.tap", G.tap(blocks)), ("start.z80", G.start_z80(start)), ("o.nex", nex),
                               ("p.nex", bytes(painted)), ("l.nex", bytes(spoken))):
                (tmp / name).write_bytes(data)
            patch, _ = nxc.make(str(tmp / "game.tap"), str(tmp / "o.nex"), dict(title="Tape Game", file="game.tap"), dict(build="t"),
                                colours={"Painted": str(tmp / "p.nex")}, languages={"Other": str(tmp / "l.nex")},
                                start=str(tmp / "start.z80"), tape_banks=extra)
        tap = G.tap(blocks)
        both = bytearray(nex)
        both[512 + 16384 + 0x2050] ^= 0x5A; both[512 + 16384 + 0x2060] ^= 0x33
        self.assertEqual(nxc.apply(patch, game=tap, colours="Painted", language="Other"), bytes(both))
        m = self.machine({"patch.nxc": patch, "game.tap": tap}, keys=["2", "3", "enter"])
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), bytes(both))
        self.assertEqual(m.peak_pages, 12)
        m = self.machine({"patch.nxc": patch, "game.tap": tap}, keys=["2", "3", "enter"], free_pages=11)
        failed, message = m.run('"patch.nxc"')
        self.assert_refused(m, failed, message, "Needs 96K free RAM")


if __name__ == "__main__":
    unittest.main()

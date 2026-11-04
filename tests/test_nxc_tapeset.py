"""Tape targets of several files (a release on two sides) through tools/nxc.py, on the made-up game in tape_game.py split
across two tapes: the target entry, the keying over every file in order, copies with a file index, the clash fix off,
another release as a full set, the refusals, and the command line. Needs NexClash's snapshot reader (NEXCLASH_REPO) and
the zx0 compressor (NXC_ZX0_DIR)."""
from __future__ import annotations

import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import tape_game as G
import test_nexclash_dot as T
import test_nxc_tape as TT

nxc = T.nxc
ROOT = T.ROOT
TMP = os.environ.get("TMPDIR")
SPLIT = 5          # side A: the header, loader, code and data blocks; side B: the empty one and the two level blocks


def tzx10(blocks: list[bytes]) -> bytes:
    """A .tzx of standard-speed 0x10 blocks only, with a text block first."""
    out = bytearray(nxc.TZX_MAGIC + bytes((1, 20))) + b"\x30\x04side"
    for d in blocks:
        out += b"\x10" + struct.pack("<HH", 1000, len(d)) + d
    return bytes(out)


def sides():
    blocks = G.data_blocks()
    start = G.start_banks(blocks, True)
    nex, _ = G.build(start, blocks, nxc.ORDER)
    return blocks, start, nex, G.tap(blocks[:SPLIT]), tzx10(blocks[SPLIT:]), G.start_z80(start)


def made_set(tmp: Path):
    blocks, start, nex, a, b, z80 = sides()
    (tmp / "side a.tap").write_bytes(a); (tmp / "side b.tzx").write_bytes(b)
    (tmp / "start.z80").write_bytes(z80); (tmp / "o.nex").write_bytes(nex)
    summary = {}
    patch, _ = nxc.make([str(tmp / "side a.tap"), str(tmp / "side b.tzx")], str(tmp / "o.nex"),
                        dict(title="Tape Game", file=["side a.tap", "side b.tzx"]), dict(build="t", publisher="T, 2026"),
                        trainer_blocks=[nxc.trn1("Lives", [(2, 0x2010, 0xAB)])], start=str(tmp / "start.z80"),
                        tape_banks=[20], tape_summary=summary)
    return patch, nex, a, b, z80, start, summary


@TT.needs
class TapeSet(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.d = tempfile.TemporaryDirectory(dir=TMP); cls.tmp = Path(cls.d.name)
        cls.patch, cls.nex, cls.a, cls.b, cls.z80, cls.start, cls.summary = made_set(cls.tmp)
        cls.game = nxc.FileSet([cls.a, cls.b], [nxc.KIND_TAP, nxc.KIND_TZX])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.d.cleanup()

    def test_the_set_rebuilds_the_build_and_takes_from_both_files(self) -> None:
        self.assertEqual(nxc.apply(self.patch, game=self.game), self.nex)
        self.assertTrue(all(n > 0 for n in self.summary["from_files"]), self.summary)

    def test_the_target_entry(self) -> None:
        (t,) = nxc.targets(self.patch)
        self.assertEqual(t["kind"], nxc.KIND_TAP | nxc.KIND_SET)
        self.assertEqual(t["files"], [("side a.tap", nxc.KIND_TAP, len(self.a)), ("side b.tzx", nxc.KIND_TZX, len(self.b))])
        self.assertIn(b"file_2=side b.tzx\n", t["text"]); self.assertIn(b"md5_2=", t["text"])
        opt = dict(nxc.blocks(self.patch)[1])[b"OPT1"]
        self.assertEqual(opt[1], nxc.OPT_TAPE | nxc.OPT_TAPE_SET)

    def test_the_key_wrap_absorbs_every_file_in_order(self) -> None:
        nonce, bl = nxc.blocks(self.patch)
        d = dict(bl)[b"TGT1"]
        plain = nxc.dump_state(nonce, self.a + self.b).block(b"TGT1", 0)(d[6:nxc.TARGET_FIXED])
        self.assertEqual(plain[:8], nxc.WRAP_CHECK)
        swapped = nxc.dump_state(nonce, self.b + self.a).block(b"TGT1", 0)(d[6:nxc.TARGET_FIXED])
        self.assertNotEqual(swapped[:8], nxc.WRAP_CHECK)

    def test_one_file_alone_or_a_wrong_second_file_unlocks_nothing(self) -> None:
        with self.assertRaisesRegex(nxc.Wrong, "not the game file"):
            nxc.apply(self.patch, game=self.a)
        wrong = bytearray(self.b); wrong[-3] ^= 1
        with self.assertRaisesRegex(nxc.Wrong, "not the files"):
            nxc.apply(self.patch, game=nxc.FileSet([self.a, bytes(wrong)], [nxc.KIND_TAP, nxc.KIND_TZX]))
        with self.assertRaisesRegex(nxc.Wrong, "not the files"):
            nxc.apply(self.patch, game=nxc.FileSet([self.a, self.b + b"\0"], [nxc.KIND_TAP, nxc.KIND_TZX]))
        with self.assertRaisesRegex(nxc.Wrong, "not the files"):
            nxc.apply(self.patch, game=nxc.FileSet([self.b, self.a], [nxc.KIND_TZX, nxc.KIND_TAP]))

    def test_the_clash_fix_off_is_the_start_as_for_one_tape(self) -> None:
        one, _, tap, _, _, _ = TT.made(tzx_too=False)
        self.assertEqual(nxc.original_with_pokes(self.patch, self.game, None), nxc.original_with_pokes(one, tap, None))
        with_lives = nxc.original_with_pokes(self.patch, self.game, ["Lives"])
        self.assertNotEqual(with_lives, nxc.original_with_pokes(self.patch, self.game, None))

    def test_another_release_as_a_full_set(self) -> None:
        blocks = G.data_blocks()
        a2, b2 = tzx10(blocks[:SPLIT]), G.tap(blocks[SPLIT:])
        other = nxc.FileSet([a2, b2], [nxc.KIND_TZX, nxc.KIND_TAP])
        f = nxc.add_target(self.patch, self.game, other, nxc.KIND_TZX, dict(file=["other a.tzx", "other b.tap"]))
        self.assertEqual(nxc.apply(f, game=other), self.nex)
        self.assertEqual(nxc.apply(f, game=self.game), self.nex)
        self.assertEqual(sum(1 for t, _ in nxc.blocks(f)[1] if t == nxc.TAPE_TAG), 1)     # one table serves both
        one = G.tap(blocks)                                                               # and the game on one tape
        f2 = nxc.add_target(f, self.game, one, nxc.KIND_TAP, dict(file="game.tap"))
        self.assertEqual(nxc.apply(f2, game=one), self.nex)
        self.assertEqual(dict(nxc.blocks(f2)[1])[b"OPT1"][1], nxc.OPT_TAPE)              # an old loader can use that one

    def test_a_set_without_the_blocks_it_needs_is_refused(self) -> None:
        blocks = G.data_blocks()
        short = nxc.FileSet([G.tap(blocks[:SPLIT]), tzx10(blocks[SPLIT:SPLIT + 1])], [nxc.KIND_TAP, nxc.KIND_TZX])
        with self.assertRaises(nxc.Wrong):
            nxc.add_target(self.patch, self.game, short, nxc.KIND_TAP, dict(file=["s a.tap", "s b.tzx"]))

    def test_names_a_set_must_keep(self) -> None:
        blocks = G.data_blocks()
        other = nxc.FileSet([tzx10(blocks[:SPLIT]), G.tap(blocks[SPLIT:])], [nxc.KIND_TZX, nxc.KIND_TAP])
        with self.assertRaisesRegex(nxc.Wrong, "names side b.tzx as another file"):
            nxc.add_target(self.patch, self.game, other, nxc.KIND_TZX, dict(file=["x.tzx", "side b.tzx"]))
        with self.assertRaisesRegex(nxc.Wrong, "one name"):
            nxc.add_target(self.patch, self.game, other, nxc.KIND_TZX, dict(file=["x.tzx", "X.TZX"]))
        with self.assertRaisesRegex(nxc.Wrong, "first"):
            nxc.add_target(self.patch, self.game, other, nxc.KIND_TZX, dict(file=["a" * 120 + ".tzx", "b" * 120 + ".tap"]))
        with self.assertRaises(nxc.Wrong):
            nxc.FileSet([self.a], [nxc.KIND_TAP])
        with self.assertRaises(nxc.Wrong):
            nxc.FileSet([self.a, self.z80], [nxc.KIND_TAP, nxc.KIND_Z80])

    def test_the_set_head_and_copy_file_index_rules(self) -> None:
        def entry(edit):
            def go(bl, st):
                for e in bl:
                    if e[0] == b"TGT1":
                        e[1] = edit(bytearray(e[1]))
            return go
        def n(v):
            def f(d):
                d[30] = v; return bytes(d)
            return f
        def kind(v):
            def f(d):
                d[1] = v; return bytes(d)
            return f
        def second_kind(v):
            def f(d):
                d[31] = v; return bytes(d)
            return f
        for name, edit in {"one file": n(1), "nine files": n(9), "a snapshot first": kind(nxc.KIND_Z80 | nxc.KIND_SET),
                           "a snapshot second": second_kind(nxc.KIND_Z80)}.items():
            with self.subTest(name):
                with self.assertRaises(nxc.Wrong):
                    nxc.apply(T.rekey(self.patch, self.a + self.b, entry(edit)), game=self.game)
        table = TT.table_of(self.patch, self.a + self.b)
        t = nxc.parse_tape_table(table, (self.game, nxc.KIND_TAP))
        files = [k >> nxc.FILE_SHIFT for k, *_ in t["copies"]]
        self.assertEqual(sorted(set(files)), [0, 1])
        at = nxc.START_SIZE + 6 + nxc.COPY_SIZE * files.index(1)
        for name, value in {"a third file": 2 << nxc.FILE_SHIFT, "bit 10": 1 << 10, "bit 15": 1 << 15}.items():
            with self.subTest(name):
                bad = bytearray(table); k = struct.unpack_from("<H", bad, at)[0] & nxc.BLOCK_MASK
                struct.pack_into("<H", bad, at, k | value)
                with self.assertRaises(nxc.Wrong):
                    nxc.parse_tape_table(bytes(bad), (self.game, nxc.KIND_TAP))
        with self.assertRaisesRegex(nxc.Wrong, "file the target does not have"):
            nxc.parse_tape_table(table, (self.a, nxc.KIND_TAP))

    def test_the_flag_for_sets(self) -> None:
        def opt(value):
            def edit(bl, st):
                for e in bl:
                    if e[0] == b"OPT1":
                        e[1] = value
            return edit
        with self.assertRaisesRegex(nxc.Wrong, "sets of tape files"):
            nxc.apply(T.rekey(self.patch, self.a + self.b, opt(b"\x01\x01\x14")), game=self.game)

    def test_the_command_line(self) -> None:
        tool = [sys.executable, str(ROOT / "tools" / "nxc.py")]
        out = self.tmp / "cli.nxc"
        r = subprocess.run(tool + ["make", str(self.tmp / "o.nex"), str(self.tmp / "side a.tap"), "--also", str(self.tmp / "side b.tzx"),
                                   "--start", str(self.tmp / "start.z80"), "--tape-bank", "20", "-o", str(out), "--title", "Tape Game"],
                           capture_output=True, text=True)
        self.assertIn("rebuilds it exactly", r.stdout + r.stderr)
        r = subprocess.run(tool + [str(out), str(self.tmp / "side a.tap"), "--also", str(self.tmp / "side b.tzx"), "-o", str(self.tmp / "cli.nex")],
                           capture_output=True, text=True)
        self.assertEqual((self.tmp / "cli.nex").read_bytes(), self.nex, r.stdout + r.stderr)
        self.assertIn("accepts side a.tap, tap, %d bytes + side b.tzx, tzx, %d bytes" % (len(self.a), len(self.b)), r.stdout)
        r = subprocess.run(tool + [str(out), str(self.tmp / "side a.tap"), "-o", str(self.tmp / "cli2.nex")], capture_output=True, text=True)
        self.assertIn("Refused", r.stderr)


if __name__ == "__main__":
    unittest.main()

"""Tape targets and TAP1 through tools/nxc.py, on the made-up game in tape_game.py: the data blocks of a .tap and a .tzx, the
table and every rule a reader checks in it, the clash fix off, several releases, the structure checks and the keying, and
that a patch holds none of the tape. Needs the zx0 compressor (NXC_ZX0_DIR)."""
from __future__ import annotations

import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

import tape_game as G
import test_nexclash_dot as T

nxc = T.nxc
ROOT = T.ROOT
TMP = os.environ.get("TMPDIR")


def needs(cls):
    cls = unittest.skipUnless(nxc is not None, "tools/nxc.py cannot be imported")(cls)
    return unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")(cls)


def made(is128: bool = True, tzx_too: bool = True, tape_banks=(20,), residual_max=None, banks=None):
    """(patch, .nex, .tap, .tzx, start .z80, start banks) for the made-up game, the .tzx added as a second release."""
    blocks = G.data_blocks()
    start = banks or G.start_banks(blocks, is128)
    nex, extra = G.build(start, blocks, nxc.ORDER)
    if not is128 or not tape_banks:
        nex = without_bank(nex, 20)
    tap, tzx, z80 = G.tap(blocks), G.tzx(blocks), G.start_z80(start)
    with tempfile.TemporaryDirectory(dir=TMP) as d:
        tmp = Path(d)
        (tmp / "game.tap").write_bytes(tap)
        (tmp / "start.z80").write_bytes(z80)
        (tmp / "o.nex").write_bytes(nex)
        patch, _ = nxc.make(str(tmp / "game.tap"), str(tmp / "o.nex"), dict(title="Tape Game", file="game.tap"), dict(build="t", publisher="T, 2026"),
                            trainer_blocks=[nxc.trn1("Lives", [(2, 0x2010, 0xAB)])], start=str(tmp / "start.z80"),
                            tape_banks=list(tape_banks) if is128 else [], residual_max=residual_max)
    if tzx_too:
        patch = nxc.add_target(patch, tap, tzx, nxc.KIND_TZX, dict(file="game.tzx"))
    return patch, nex, tap, tzx, z80, start


def without_bank(nex: bytes, bank: int) -> bytes:
    head = bytearray(nex[:512])
    if not head[18 + bank]:
        return nex
    at = 512 + 16384 * sum(1 for b in nxc.ORDER[:nxc.ORDER.index(bank)] if head[18 + b])
    head[18 + bank] = 0
    head[9] -= 1
    return bytes(head) + nex[512:at] + nex[at + 16384:]


def table_of(patch: bytes, game: bytes, stream: int = 0) -> bytes:
    _, bl, st, _ = T.unlocked(patch, game)
    for t, d in bl:
        if t == nxc.TAPE_TAG and d[0] == stream:
            return nxc.tape_table_of(st, nxc.parse_tap1(d))
    raise AssertionError("no such table")


def with_table(patch: bytes, game: bytes, table: bytes, head: bytes | None = None) -> bytes:
    """The patch with its first TAP1's table replaced, re-encrypted and re-checked, as someone who owns the game can do."""
    def edit(bl, st):
        for e in bl:
            if e[0] == nxc.TAPE_TAG:
                old = nxc.parse_tap1(e[1])
                e[1] = (head if head is not None else e[1][:nxc.TAPE_FIXED + len(old["targets"])]) + st.block(nxc.TAPE_TAG, old["stream"])(nxc.zx0(table))
                return
    return T.rekey(patch, game, edit)


@needs
class DataBlocks(unittest.TestCase):
    def test_a_tap_and_a_tzx_give_the_same_blocks(self) -> None:
        blocks = G.data_blocks()
        for kind, tape in ((nxc.KIND_TAP, G.tap(blocks)), (nxc.KIND_TZX, G.tzx(blocks))):
            with self.subTest(kind=kind):
                found = nxc.tape_blocks(tape, kind)
                self.assertEqual([tape[a:a + n] for a, n in found], blocks)

    def test_the_limit_stops_the_walk(self) -> None:
        blocks = G.data_blocks()
        self.assertEqual(len(nxc.tape_blocks(G.tzx(blocks), nxc.KIND_TZX, 3)), 3)
        self.assertEqual(len(nxc.tape_blocks(G.tap(blocks) + b"\x05", nxc.KIND_TAP, 7)), 7)

    def test_damage_and_blocks_no_target_may_hold(self) -> None:
        blocks = G.data_blocks()
        tzx = G.tzx(blocks)
        bad = {"a .tap length past the end": (nxc.KIND_TAP, G.tap(blocks)[:-1]), "a .tap cut in a length": (nxc.KIND_TAP, G.tap(blocks) + b"\x01"),
               "another magic": (nxc.KIND_TZX, b"ZXTape?" + tzx[7:]), "major version 2": (nxc.KIND_TZX, tzx[:8] + b"\x02" + tzx[9:]),
               "a .tzx cut short": (nxc.KIND_TZX, tzx[:-3]), "a block head cut short": (nxc.KIND_TZX, tzx + b"\x11\x00"),
               "a skipped block cut short": (nxc.KIND_TZX, tzx + b"\x35" + bytes(10))}
        for bid in (0x16, 0x17, 0x34, 0x40, 0x00, 0x29, 0x5B, 0xFF):
            bad["ID 0x%02X" % bid] = (nxc.KIND_TZX, tzx + bytes((bid,)) + bytes(64))
        for name, (kind, tape) in bad.items():
            with self.subTest(name):
                with self.assertRaises(nxc.Wrong):
                    nxc.tape_blocks(tape, kind)

    def test_every_skipped_id_is_in_the_made_up_tzx(self) -> None:
        tzx = G.tzx(G.data_blocks())
        i, seen = 10, set()
        while i < len(tzx):
            bid = tzx[i]
            seen.add(bid)
            before = len(nxc.tape_blocks(tzx[:i], nxc.KIND_TZX))
            i += 1
            if bid in nxc.TZX_DATA:
                head, at, size = nxc.TZX_DATA[bid]
                i += head + int.from_bytes(tzx[i + at:i + at + size], "little")
            else:
                head, at, size, unit = nxc.TZX_SKIP[bid]
                i += head + (0 if at is None else int.from_bytes(tzx[i + at:i + at + size], "little") * unit)
            self.assertGreaterEqual(len(nxc.tape_blocks(tzx[:i], nxc.KIND_TZX)), before)
        self.assertEqual(seen, set(nxc.TZX_DATA) | set(nxc.TZX_SKIP))


@needs
class Rebuild(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch, cls.nex, cls.tap, cls.tzx, cls.z80, cls.banks = made()

    def test_both_releases_rebuild_the_build_and_share_a_table(self) -> None:
        self.assertEqual(nxc.apply(self.patch, game=self.tap), self.nex)
        self.assertEqual(nxc.apply(self.patch, game=self.tzx), self.nex)
        tables = [nxc.parse_tap1(d) for t, d in nxc.blocks(self.patch)[1] if t == nxc.TAPE_TAG]
        self.assertEqual([(e["stream"], e["targets"]) for e in tables], [(0, [0, 1])])
        self.assertEqual([t["kind"] for t in nxc.targets(self.patch)], [nxc.KIND_TAP, nxc.KIND_TZX])

    def test_options_say_tape_and_count_the_extra_bank(self) -> None:
        self.assertEqual(dict(nxc.blocks(self.patch)[1])[b"OPT1"], bytes((1, nxc.OPT_TAPE, 20)))

    def test_the_table_takes_the_start_from_the_tape(self) -> None:
        t = nxc.parse_tape_table(table_of(self.patch, self.tap), nxc.tape_blocks(self.tap, nxc.KIND_TAP))
        held = sum(len(d) for _, _, d in t["sites"])
        self.assertEqual(held, 256 + 100 + 32)                    # the screen line, the table, the variables
        self.assertEqual(sorted({c[3] for c in t["copies"]}), [0, 2, 3, 5, 7, 20])
        self.assertEqual(t["header"], nxc.start_header(self.z80))
        self.assertTrue(t["is128"])

    def test_the_clash_fix_off_is_the_start_whatever_the_release(self) -> None:
        want = nxc.start_snapshot(nxc.start_header(self.z80), self.banks)
        for tape in (self.tap, self.tzx):
            self.assertEqual(nxc.original_with_pokes(self.patch, tape, []), want)
        snap = nxc.snapshot_of(want, nxc.KIND_Z80)
        self.assertEqual(dict(snap.banks), self.banks)
        self.assertEqual((snap.pc, snap.is128, snap.port7ffd), (0x6000, True, 0x13))
        poked = nxc.original_with_pokes(self.patch, self.tzx, [1])
        self.assertEqual(nxc.snapshot_of(poked, nxc.KIND_Z80).banks[2][0x2010], 0xAB)
        self.assertEqual(len(poked), len(want))

    def test_a_trainer_on_the_build(self) -> None:
        out = nxc.apply(self.patch, game=self.tap, chosen=[1])
        self.assertEqual(out[512 + 16384 + 0x2010], 0xAB)
        self.assertEqual(sum(a != b for a, b in zip(out, self.nex)), 1)

    def test_a_48k_game_and_no_extra_banks(self) -> None:
        patch, nex, tap, tzx, z80, banks = made(is128=False)
        self.assertEqual(nxc.apply(patch, game=tzx), nex)
        self.assertEqual(dict(nxc.blocks(patch)[1])[b"OPT1"][:2], bytes((1, nxc.OPT_TAPE)))
        self.assertEqual(nxc.snapshot_of(nxc.original_with_pokes(patch, tap, []), nxc.KIND_Z80).banks, banks)

    def test_a_tape_and_a_snapshot_of_its_start_in_one_patch(self) -> None:
        patch, nex, tap, tzx, z80, banks = made(tzx_too=False, tape_banks=())
        both = nxc.add_target(patch, tap, z80, nxc.KIND_Z80, dict(file="start.z80"))
        self.assertEqual(nxc.apply(both, game=z80), nex)
        self.assertEqual(dict(nxc.blocks(both)[1])[b"OPT1"][:2], b"\x01\x00")    # a snapshot target: no tape flag
        with self.assertRaises(nxc.Wrong):                                      # with an extra bank it cannot
            nxc.add_target(self.patch, self.tap, self.z80, nxc.KIND_Z80, dict(file="start.z80"))

    def test_a_release_laid_out_differently_gets_its_own_table(self) -> None:
        blocks = G.data_blocks()
        other = G.tzx(blocks, before=b"\x10" + struct.pack("<HH", 0, 5) + b"extra")
        three = nxc.add_target(self.patch, self.tap, other, nxc.KIND_TZX, dict(file="other.tzx"))
        tables = [nxc.parse_tap1(d) for t, d in nxc.blocks(three)[1] if t == nxc.TAPE_TAG]
        self.assertEqual([(e["stream"], e["targets"]) for e in tables], [(0, [0, 1]), (1, [2])])
        self.assertEqual(nxc.apply(three, game=other), self.nex)
        self.assertEqual(nxc.original_with_pokes(three, other, []), nxc.original_with_pokes(self.patch, self.tap, []))
        for t, d in nxc.blocks(three)[1]:                                    # the clear head and its own stream are all that changed
            if t == nxc.TAPE_TAG and d[0] == 0:
                self.assertEqual(d, dict(nxc.blocks(self.patch)[1])[nxc.TAPE_TAG])

    def test_two_kinds_of_one_length_are_refused(self) -> None:
        fake = bytes(len(self.tap))
        with self.assertRaises(nxc.Wrong) as e:
            nxc.add_target(self.patch, self.tap, fake, nxc.KIND_Z80, dict(file="same.z80"))
        self.assertIn("another kind with that length", str(e.exception))

    def test_a_release_without_the_extra_blocks_is_refused(self) -> None:
        blocks = G.data_blocks()
        short = G.tap(blocks[:6] + [G.rom_block(0x82, G.noise(b"another level", 2500))])
        with self.assertRaises(nxc.Wrong):
            nxc.add_target(self.patch, self.tap, short, nxc.KIND_TAP, dict(file="short.tap"))

    def test_a_trainer_from_a_pok_on_a_tape(self) -> None:
        pok = "NLives\nZ 8 41000 7 0\nNBank three\nZ 3 49408 9 0\nY\n"
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            (Path(d) / "game.tzx").write_bytes(self.tzx)
            out = nxc.import_pok(self.patch, str(Path(d) / "game.tzx"), pok)
        self.assertEqual([t[2] for t in nxc.trainers(out)], [[(2, 41000 - 0x8000, 7)], [(3, 0x100, 9)]])
        self.assertEqual(nxc.apply(out, game=self.tap), self.nex)

    def test_nothing_of_the_tape_or_its_start_is_in_the_patch(self) -> None:
        for source in [self.tap, self.tzx] + list(self.banks.values()):
            for i in range(0, len(source) - 16, 8):
                piece = source[i:i + 16]
                if len(set(piece)) > 2:
                    self.assertNotIn(piece, self.patch)


@needs
class TableRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch, cls.nex, cls.tap, cls.tzx, cls.z80, cls.banks = made()
        cls.table = table_of(cls.patch, cls.tap)
        cls.blocks = nxc.tape_blocks(cls.tap, nxc.KIND_TAP)
        cls.parts = nxc.parse_tape_table(cls.table, cls.blocks)

    def remade(self, header=None, crc=None, copies=None, sites=None) -> bytes:
        p = self.parts
        return nxc.tape_table(p["header"] if header is None else header, p["crc"] if crc is None else crc,
                              p["copies"] if copies is None else copies, p["sites"] if sites is None else sites)

    def test_the_table_as_it_is_and_remade(self) -> None:
        self.assertEqual(self.remade(), self.table)
        self.assertEqual(nxc.apply(with_table(self.patch, self.tap, self.remade()), game=self.tap), self.nex)

    def test_every_rule(self) -> None:
        c, s, h = list(self.parts["copies"]), list(self.parts["sites"]), self.parts["header"]
        k, src, n, b, o = c[0]
        bad = {
            "past the last block": self.remade(copies=[(len(self.blocks), 0, 1, b, o)] + c[1:]),
            "past the block's end": self.remade(copies=[(k, self.blocks[k][1] - n + 1, n, b, o)] + c[1:]),
            "the 1025th block": self.remade(copies=[(1024, 0, 1, b, o)] + c[1:]),
            "a bank of 112": self.remade(copies=c + [(k, 0, 1, 112, 0)]),
            "a length of 0": self.remade(copies=[(k, src, 0, b, o)] + c[1:]),
            "past the bank's end": self.remade(copies=[(k, 0, 17, b, 16380)] + c[1:]),
            "copies out of order": self.remade(copies=c[1:2] + c[:1] + c[2:]),
            "copies overlapping": self.remade(copies=[c[0], (c[1][0], c[1][1], c[1][2], c[0][3], c[0][4] + c[0][2] - 1)] + c[2:]) if c[1][3] == c[0][3] else None,
            "sites out of order": self.remade(sites=s[::-1]),
            "a site of length 0": self.remade(sites=[(s[0][0], s[0][1], b"")] + s[1:]),
            "a site past its bank": self.remade(sites=s + [(1, 16383, b"ab")]),
            "the wrong CRC": self.remade(crc=self.parts["crc"] ^ 1),
            "a header saying version 3": self.remade(header=h[:30] + b"\x36\x00" + h[32:]),
            "a header with a PC in it": self.remade(header=h[:6] + b"\x01\x00" + h[8:]),
            "hardware mode 4": self.remade(header=h[:34] + b"\x04" + h[35:]),
            "a byte left over": self.remade() + b"\0",
            "cut short": self.remade()[:-1],
        }
        for name, table in bad.items():
            if table is None:
                continue
            with self.subTest(name):
                with self.assertRaises(nxc.Wrong):
                    nxc.apply(with_table(self.patch, self.tap, table), game=self.tap)
                with self.assertRaises(nxc.Wrong):
                    nxc.original_with_pokes(with_table(self.patch, self.tap, table), self.tap, [])

    def test_an_extra_bank_the_nex_does_not_list(self) -> None:
        k = self.parts["copies"][0][0]
        patch = with_table(self.patch, self.tap, self.remade(copies=self.parts["copies"] + [(k, 0, 1, 30, 0)]))
        with self.assertRaises(nxc.Wrong):
            nxc.apply(patch, game=self.tap)
        self.assertEqual(nxc.original_with_pokes(patch, self.tap, []), nxc.original_with_pokes(self.patch, self.tap, []))

    def test_a_copy_and_a_site_may_overlap_and_the_site_wins(self) -> None:
        k, src, n, b, o = self.parts["copies"][0]
        sites = sorted(self.parts["sites"] + [(b, o, b"\x99")], key=lambda x: (nxc.ORDER.index(x[0]), x[1]))
        banks = dict(self.banks)
        changed = bytearray(banks[b]); changed[o] = 0x99; banks[b] = bytes(changed)
        crc = zlib.crc32(nxc.start_snapshot(self.parts["header"], banks))
        out = nxc.original_with_pokes(with_table(self.patch, self.tap, self.remade(crc=crc, sites=sites)), self.tap, [])
        self.assertEqual(nxc.snapshot_of(out, nxc.KIND_Z80).banks[b][o], 0x99)

    def test_a_reader_walks_only_as_far_as_the_table_needs(self) -> None:
        after = self.tzx + b"\x16" + bytes(40)                  # a block no target may hold, after the last one named
        last = max(c[0] for c in self.parts["copies"])
        self.assertEqual(nxc.TapeSnapshot(after, nxc.KIND_TZX, self.table).banks, nxc.TapeSnapshot(self.tzx, nxc.KIND_TZX, self.table).banks)
        cut = G.tap(G.data_blocks()[:last])                      # and one that ends before it
        with self.assertRaises(nxc.Wrong):
            nxc.TapeSnapshot(cut, nxc.KIND_TAP, self.table)
        with self.assertRaises(nxc.Wrong):
            nxc.tape_blocks(after, nxc.KIND_TZX)                 # a writer walks it all

    def test_a_table_too_long_for_a_loader(self) -> None:
        sites = self.parts["sites"] + [(1, n * 8, b"x" * 8) for n in range(1800)]
        with self.assertRaises(nxc.Wrong):
            nxc.apply(with_table(self.patch, self.tap, self.remade(sites=sites)), game=self.tap)


@needs
class Structure(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch, cls.nex, cls.tap, cls.tzx, cls.z80, cls.banks = made()

    def edited(self, edit) -> bytes:
        return T.rekey(self.patch, self.tap, edit)

    def refused(self, patch: bytes, said: str) -> None:
        with self.assertRaises(nxc.Wrong) as e:
            nxc.apply(patch, game=self.tap)
        self.assertIn(said, str(e.exception))

    def test_the_clear_head(self) -> None:
        def heads(*new):
            def edit(bl, st):
                for e in bl:
                    if e[0] == nxc.TAPE_TAG:
                        e[1] = new[0] + nxc.parse_tap1(e[1])["data"]
            return edit
        for name, head in (("a target missing", b"\0\x01\0"), ("a target twice", b"\0\x03\0\x01\x01"), ("a target that is not there", b"\0\x03\0\x01\x02"),
                           ("no targets", b"\0\0"), ("too many", b"\0\x21" + bytes(33))):
            with self.subTest(name):
                with self.assertRaises(nxc.Wrong):
                    nxc.apply(self.edited(heads(head)), game=self.tap)

    def test_no_table_two_tables_and_a_repeated_stream(self) -> None:
        def drop(bl, st):
            bl[:] = [e for e in bl if e[0] != nxc.TAPE_TAG]
        self.refused(self.edited(drop), "tape block")
        def split(bl, st):
            for n, e in enumerate(bl):
                if e[0] == nxc.TAPE_TAG:
                    data = nxc.parse_tap1(e[1])["data"]
                    bl[n:n + 1] = [[e[0], b"\0\x01\0" + data], [e[0], b"\0\x01\x01" + data]]
                    return
        self.refused(self.edited(split), "repeats a stream")

    def test_a_table_for_a_snapshot_target(self) -> None:
        patch, nex, tap, tzx, z80, banks = made(tzx_too=False, tape_banks=())
        both = nxc.add_target(patch, tap, z80, nxc.KIND_Z80, dict(file="start.z80"))
        def name_it(bl, st):
            for e in bl:
                if e[0] == nxc.TAPE_TAG:
                    e[1] = b"\0\x02\0\x01" + nxc.parse_tap1(e[1])["data"]
        with self.assertRaises(nxc.Wrong):
            nxc.apply(T.rekey(both, tap, name_it), game=z80)

    def test_the_tape_flag(self) -> None:
        def opt(value):
            def edit(bl, st):
                for e in bl:
                    if e[0] == b"OPT1":
                        e[1] = value
            return edit
        self.refused(self.edited(opt(b"\x01\x00\x14")), "only tape targets")
        self.refused(self.edited(opt(b"\x01\x05\x14")), "newer loader")
        self.assertEqual(nxc.apply(self.edited(opt(b"\x01\x01\x14")), game=self.tap), self.nex)

    def test_a_reader_without_tapes_says_it_needs_a_newer_one(self) -> None:
        old = nxc.LOADER_FLAGS
        try:
            nxc.LOADER_FLAGS = 0
            self.refused(self.patch, "newer loader")
        finally:
            nxc.LOADER_FLAGS = old

    def test_the_keyed_check_covers_the_clear_head(self) -> None:
        at = self.patch.index(b"TAP1") + 8
        for offset in (0, 1, 2, 3):
            broken = bytearray(self.patch)
            broken[at + offset] ^= 1
            with self.subTest(offset=offset):
                with self.assertRaises(nxc.Wrong):
                    nxc.apply(bytes(broken), game=self.tap)

    def test_a_flipped_byte_in_the_table_never_reaches_the_decoder(self) -> None:
        at = self.patch.index(b"TAP1") + 8 + 4
        broken = bytearray(self.patch)
        broken[at + 10] ^= 0x40
        with self.assertRaises(nxc.Wrong) as e:
            nxc.apply(bytes(broken), game=self.tap)
        self.assertIn("damaged", str(e.exception))

    def test_the_wrong_tape_unlocks_nothing(self) -> None:
        wrong = bytearray(self.tap)
        wrong[-1] ^= 1
        with self.assertRaises(nxc.Wrong):
            nxc.apply(self.patch, game=bytes(wrong))
        with self.assertRaises(nxc.Wrong):
            nxc.original_with_pokes(self.patch, bytes(wrong), [])


@needs
class Writer(unittest.TestCase):
    def run_tool(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-W", "ignore", str(ROOT / "tools/nxc.py"), *args], capture_output=True, text=True)

    def test_the_command_line(self) -> None:
        blocks = G.data_blocks()
        banks = G.start_banks(blocks)
        nex, _ = G.build(banks, blocks, nxc.ORDER)
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            tmp = Path(d)
            for name, data in (("g.tap", G.tap(blocks)), ("g.tzx", G.tzx(blocks)), ("s.z80", G.start_z80(banks)), ("o.nex", nex)):
                (tmp / name).write_bytes(data)
            r = self.run_tool("make", str(tmp / "o.nex"), str(tmp / "g.tap"), "-o", str(tmp / "out.nxc"))
            self.assertIn("needs --start", r.stderr)
            r = self.run_tool("make", str(tmp / "o.nex"), str(tmp / "g.tap"), "--start", str(tmp / "s.z80"), "-o", str(tmp / "out.nxc"))
            self.assertIn("rebuilds it exactly", r.stdout + r.stderr)          # bank 20 then goes whole in BNK1
            r = self.run_tool("make", str(tmp / "o.nex"), str(tmp / "g.tap"), "--start", str(tmp / "s.z80"), "--tape-bank", "20", "-o", str(tmp / "out.nxc"), "--title", "T")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("388 bytes in", r.stdout)
            r = self.run_tool("add-target", str(tmp / "out.nxc"), str(tmp / "g.tap"), str(tmp / "g.tzx"), "-o", str(tmp / "two.nxc"))
            self.assertEqual(r.returncode, 0, r.stderr)
            r = self.run_tool(str(tmp / "two.nxc"), str(tmp / "g.tzx"), "--bare", "-o", str(tmp / "x.nex"))
            self.assertEqual((tmp / "x.nex").read_bytes(), nex)
            r = self.run_tool(str(tmp / "two.nxc"), str(tmp / "g.tzx"), "--original", "-o", str(tmp / "x.z80"))
            self.assertEqual(nxc.snapshot_of((tmp / "x.z80").read_bytes(), nxc.KIND_Z80).banks, banks)
            r = self.run_tool("make", str(tmp / "o.nex"), str(tmp / "s.z80"), "--start", str(tmp / "s.z80"), "-o", str(tmp / "y.nxc"))
            self.assertIn("for a tape target", r.stderr)
            r = self.run_tool("make", str(tmp / "o.nex"), str(tmp / "g.tap"), "--start", str(tmp / "s.z80"), "--tape-bank", "21", "-o", str(tmp / "y.nxc"))
            self.assertIn("not a bank the .nex lists", r.stderr)
            r = self.run_tool("make", str(tmp / "o.nex"), str(tmp / "g.tap"), "--start", str(tmp / "s.z80"), "--residual-max", "100", "-o", str(tmp / "y.nxc"))
            self.assertIn("not on the tape", r.stderr)
            self.assertFalse((tmp / "y.nxc").exists())

    def test_a_start_the_tape_does_not_hold_is_refused(self) -> None:
        blocks = G.data_blocks()
        banks = dict(G.start_banks(blocks))
        banks[4] = G.noise(b"unpacked at load", 16384)
        with self.assertRaises(nxc.Wrong) as e:
            made(banks=banks)
        self.assertIn("not on the tape", str(e.exception))
        self.assertEqual(nxc.apply(made(banks=banks, residual_max=20000)[0], game=G.tap(blocks)), made(banks=banks, residual_max=20000)[1])

    def test_a_writer_takes_every_run_of_16_from_the_tape(self) -> None:
        blocks = G.data_blocks()
        tap = G.tap(blocks)
        table, summary = nxc.make_tape_table(tap, nxc.KIND_TAP, G.start_z80(G.start_banks(blocks)))
        t = nxc.parse_tape_table(table, nxc.tape_blocks(tap, nxc.KIND_TAP))
        data = b"".join(blocks)
        for b, o, d in t["sites"]:
            for i in range(len(d) - 15):
                self.assertNotIn(d[i:i + 16], data)


if __name__ == "__main__":
    unittest.main()

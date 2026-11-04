"""The rules of the format itself, on games made here, through tools/nxc.py and through the loader on the Z80 harness: the
review's bugs, the keying and keyed check, several dumps, the loading screen. A control after each kind restores the old
behaviour in the loader's source and shows that the test catches it."""
from __future__ import annotations

import hashlib
import os
import random
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

import test_nexclash_dot as T

H = T.H
nxc = T.nxc
TMP = os.environ.get("TMPDIR")
ROOT = T.ROOT
NEX, Z80 = T.NEX, T.Z80
DAMAGED = "Patch damaged: get it again"
LEVEL = "Patch needs a newer .NEXCLASH"
WRONG = "Wrong game file for this patch"
ALIAS = "Input has the /tmp output's name"


def bank(seed: int) -> bytes:
    return T.random_bank(random.Random(seed), seed)


def sna(banks: dict[int, bytes]) -> bytes:
    return bytes(27) + banks[5] + banks[2] + banks[0]


def find_block(patch: bytes, tag: bytes, nth: int = 0) -> int:
    """Where a block's data starts in the file."""
    at = nxc.HEADER
    for t, d in nxc.blocks(patch)[1]:
        if t == tag:
            if not nth:
                return at + 8
            nth -= 1
        at += 8 + len(d)
    raise AssertionError(tag)


class Case(T.Base):
    """One game made here: two sites' worth of changes, two banks of its own, a trainer and a colour set."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.banks = {b: bank(b + 40) for b in (5, 2, 0)}
        cls.game = T.snapshot_paged(cls.banks, 54, 0)
        cls.patch, cls.nex = cls.build(cls.game)
        cls.base = nxc.apply(cls.patch, game=cls.game)

    @classmethod
    def build(cls, game: bytes, name: str = "game.z80", sets: bool = True, screen: bytes = b"", flags: int = 0, more=()):
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            tmp = Path(d)
            path = tmp / name
            path.write_bytes(game)
            out = dict(cls.banks)
            b5 = bytearray(out[5])
            b5[100:140] = bytes(40)
            out[5] = bytes(b5)
            out[10] = bytes(random.Random(1).randrange(256) for _ in range(900)).ljust(16384, b"\0")
            nex = bytearray(T.nex_from(out))
            nex[10] = flags
            nex = bytes(nex[:512]) + screen + bytes(nex[512:])
            (tmp / "o.nex").write_bytes(nex)
            colours = {}
            if sets:
                painted = bytearray(nex)
                painted[512 + len(screen) + 16384 + 7] ^= 0x55
                (tmp / "p.nex").write_bytes(bytes(painted))
                colours = {"Painted": str(tmp / "p.nex")}
            extra = []
            for n, data in enumerate(more):
                other = tmp / f"more{n}{data[0]}"
                other.write_bytes(data[1])
                extra.append((str(other), dict(file=data[2])))
            patch, _ = nxc.make(str(path), str(tmp / "o.nex"), dict(title="Made Up", file=name), dict(build="t", publisher="T, 2026"),
                                colours=colours, trainer_blocks=[nxc.trn1("Lives", [(2, 16000, 0xAB)])], more_dumps=extra)
            return patch, nex

    def go(self, patch=None, game=None, keys=("enter",), name="patch.nxc", argument=None, other_files=None, **options):
        files = {name: self.patch if patch is None else patch}
        if game is not False:
            files["game.z80"] = self.game if game is None else game
        files.update(other_files or {})
        m = self.machine(files, keys=keys, **options)
        failed, message = m.run(argument or f'"{name}"')
        return m, failed, message

    def refused_by_both(self, patch: bytes, message: str | None = DAMAGED) -> None:
        with self.assertRaises(nxc.Wrong):
            nxc.apply(patch, game=self.game)
        m, failed, said = self.go(patch)
        self.assert_refused(m, failed, said, message)

    def control(self, replace, patch=None, keys=("enter",), game=None, **options):
        """A run on a loader with the given source changes."""
        binary, symbols = H.assemble(replace)
        return self.go(patch, game, keys, binary=binary, symbols=symbols, **options)


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class OutputCannotDestroyAnInput(Case):
    def test_a_patch_that_is_an_output_name_is_refused_however_it_is_written(self) -> None:
        for spec, cwd in (('/tmp/nexclash.nex', "/"), ('c:/tmp/NEXCLASH.NEX', "/"), ('C:\\TMP\\nexclash.z80', "/"),
                          ('/nextzxos/../tmp/NexClash.Nex', "/"), ('tmp/nexclash.nex', "/"), ('nexclash.z80', "/tmp"),
                          ('../tmp/nexclash.z80', "/tmp"), ('/tmp/./nexclash.nex', "/"), ('/tmp/nexclash.nex.', "/"), ('/tmp/nexclash.z80 ', "/")):
            with self.subTest(spec=spec, cwd=cwd):
                m = self.machine({spec.lower(): self.patch}, cwd=cwd)
                failed, message = m.run(f'"{spec}"')
                self.assert_refused(m, failed, message, ALIAS)
                self.assertEqual(m.deleted, [])
                self.assertEqual(m.written, {})

    def test_a_game_that_is_an_output_name_is_refused(self) -> None:
        # By its fall-back name: a patch in /tmp called NEXCLASH.nxc wants /tmp/NEXCLASH.z80.
        for keys in (["enter"], ["2", "enter"], ["1", "2", "enter"]):
            m = self.machine({"/tmp/nexclash.nxc": self.patch, "/tmp/nexclash.z80": self.game}, keys=keys)
            failed, message = m.run('"/tmp/nexclash.nxc"')
            self.assert_refused(m, failed, message, ALIAS)
            self.assertEqual(m.deleted, [])
        # By its listed name.
        def named(bl, st):
            for e in bl:
                if e[0] == b"TGT1":
                    e[1] = e[1][:nxc.TARGET_FIXED] + e[1][nxc.TARGET_FIXED:].replace(b"file=game.z80", b"file=NEXCLASH.NEX")
        patch = T.rekey(self.patch, self.game, named)
        m = self.machine({"/tmp/a.nxc": patch, "/tmp/nexclash.nex": self.game})
        failed, message = m.run('"/tmp/a.nxc"')
        self.assert_refused(m, failed, message, ALIAS)

    def test_the_same_names_elsewhere_are_fine(self) -> None:
        for spec, files in (('/games/nexclash.nxc', {"/games/nexclash.nxc": self.patch, "/games/nexclash.z80": self.game}),
                            ('d:/tmp/nexclash.nxc', {"d:/tmp/nexclash.nxc": self.patch, "d:/tmp/nexclash.z80": self.game}),
                            ('/tmp/game.nxc', {"/tmp/game.nxc": self.patch, "/tmp/game.z80": self.game})):
            with self.subTest(spec=spec):
                m = self.machine(files)
                failed, message = m.run(f'"{spec}"')
                self.assertFalse(failed, message)
                self.assertEqual(bytes(m.written[NEX]), self.base)

    def test_a_folder_that_cannot_be_resolved_is_refused(self) -> None:
        # It can be opened, but nothing says what it is: "$:/" gives rubbish from F_GETCWD when tried.
        class Odd(H.Machine):
            def esxdos(self, function):
                if function == 0xA8:
                    self.m.set_memory_block(self.m.hl, b"z*\0")
                    return False
                return super().esxdos(function)
        m = Odd(self.binary, self.symbols, {"patch.nxc": self.patch, "game.z80": self.game})
        failed, message = m.run('"patch.nxc"')
        self.assertEqual((failed, message), (True, ALIAS))

    def test_only_an_output_made_is_deleted(self) -> None:
        for keys in (["enter"], ["2", "enter"], ["1", "2", "enter"]):
            m, failed, message = self.go(keys=keys, fail_create=True)
            self.assertEqual((failed, message), (True, "Cannot write to /tmp"))
            self.assertEqual(m.deleted, [])
            self.assertEqual(m.clean(), [])

    def test_controls(self) -> None:
        # No check on the patch: the file is created over it.
        no_check = [("""        ld      hl,patch_path               ; never read what would be written over
        call    check_alias
""", "")]
        binary, symbols = H.assemble(no_check)
        m = H.Machine(binary, symbols, {"/tmp/nexclash.nex": self.patch, "/tmp/game.z80": self.game})
        failed, message = m.run('"/tmp/nexclash.nex"')
        self.assertNotEqual(message, ALIAS)
        self.assertIn(NEX, m.opened, "a loader with no check on its patch passed")
        # The old order: the name kept before the file exists, so a failure deletes what it did not make.
        m, failed, message = self.control([("""create_out:
        push    hl
""", """create_out:
        ld      (out_name),hl
        push    hl
""")], fail_create=True)
        self.assertTrue(m.deleted, "a loader that deletes what it did not make passed")


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class FileNames(Case):
    BAD = (b"../other.z80", b"..", b".", b"c:other.z80", b"c:/other.z80", b"a/b.z80", b"/b.z80", b"a\\b.z80", b"a*b", b"a?b", b'a"b',
           b"a<b", b"a>b", b"a|b", b"x" * 128, b"", b" a.z80", b"a.z80 ", b"a.z80.", b"a\x01b.z80", b"a\x7fb.z80", b"a\xc0b.z80", b"a..b.z80")

    def named(self, value: bytes) -> bytes:
        def edit(bl, st):
            for e in bl:
                if e[0] == b"TGT1":
                    e[1] = e[1][:nxc.TARGET_FIXED] + e[1][nxc.TARGET_FIXED:].replace(b"file=game.z80", b"file=" + value)
        return T.rekey(self.patch, self.game, edit)

    def test_only_a_bare_bounded_name_opens_anything(self) -> None:
        for value in self.BAD:
            with self.subTest(value=value):
                patch = self.named(value)
                with self.assertRaises(nxc.Wrong):
                    nxc.targets(patch)
                with self.assertRaises(nxc.Wrong):
                    nxc.check_key(patch, self.game)
                m, failed, message = self.go(patch)
                self.assert_refused(m, failed, message, DAMAGED)
                self.assertEqual(m.opened, ["patch.nxc"], "something else was opened")

    def test_the_longest_name_works(self) -> None:
        name = b"n" * 123 + b".z80"
        self.assertEqual(len(name), nxc.FILE_NAME_MAX)
        patch = self.named(name)
        m, failed, message = self.go(patch, game=False, other_files={name.decode().lower(): self.game})
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), self.base)

    def test_a_name_with_its_folder_too_long_is_refused_not_cut(self) -> None:
        name = b"n" * 120 + b".z80"
        folder = "d" * 120 + "/"
        patch = self.named(name)
        m, failed, message = self.go(patch, game=False, name=folder + "p.nxc")
        self.assert_refused(m, failed, message, "File name too long")
        self.assertEqual(m.opened, [folder + "p.nxc"], "a name cut short could be another file")

    def test_a_patch_path_too_long_is_refused_not_cut(self) -> None:
        m = self.machine({})
        failed, message = m.run('"' + "p" * 300 + '.nxc"')
        self.assertEqual((failed, message), (True, "File name too long"))
        self.assertEqual(m.opened, [])

    def test_the_tool_will_not_make_a_bad_name(self) -> None:
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            path = Path(d) / "g.z80"
            path.write_bytes(self.game)
            (Path(d) / "o.nex").write_bytes(self.nex)
            for value in (v for v in self.BAD if v.isascii() and b"\x01" not in v and b"\x7f" not in v):
                with self.subTest(value=value), self.assertRaises(nxc.Wrong):
                    nxc.make(str(path), str(Path(d) / "o.nex"), dict(file=value.decode()), dict(build="t"))

    def test_control(self) -> None:
        m, failed, message = self.control([("""        jp      c,bad_patch
        call    check_name
""", """        jp      c,bad_patch
""")], self.named(b"../other.z80"))
        self.assertIn("../other.z80", m.opened, "a loader with no check on the name passed")


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class RequiredBlocks(Case):
    def repeated(self, tag: bytes, times: int) -> bytes:
        def edit(bl, st):
            at = next(i for i, e in enumerate(bl) if e[0] == tag)
            for _ in range(times):
                bl.insert(at, [tag, bl[at][1]])
        return T.rekey(self.patch, self.game, edit)

    def test_a_second_occurrence_is_refused(self) -> None:
        for tag in (b"OPT1", b"INF1", b"OUT1", b"NEX1", b"SIT1"):
            for times in (1, 256):                  # 257 of a tag wrapped a byte count back to one
                with self.subTest(tag=tag, times=times):
                    self.refused_by_both(self.repeated(tag, times))

    def test_control(self) -> None:
        m, failed, message = self.control([(""".known: ld      a,(hl)                      ; a second one is damage, whatever follows
        or      a
        jp      nz,bad_patch
        inc     (hl)""", """.known: inc     (hl)""")], self.repeated(b"OPT1", 1))
        self.assertFalse(failed, "a loader with no check on a second occurrence refused it, so this test proves nothing")


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class OneValidationRoute(Case):
    def damaged(self) -> bytes:
        bad = bytearray(self.patch)
        bad[bad.index(b"build=")] ^= 1
        return bytes(bad)

    def assert_no_decompression(self, call) -> None:
        calls = []
        real = nxc.unzx0
        nxc.unzx0 = lambda *a, **k: (calls.append(1), real(*a, **k))[1]
        try:
            with self.assertRaisesRegex(nxc.Wrong, "damaged"):
                call()
        finally:
            nxc.unzx0 = real
        self.assertEqual(calls, [], "decompressed before the check")

    def test_every_route_checks_first(self) -> None:
        bad = self.damaged()
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            path = Path(d) / "g.z80"
            path.write_bytes(self.game)
            for name, call in (("credit", lambda: nxc.set_credits(bad, self.game, "Ann")),
                               ("import-pok", lambda: nxc.import_pok(bad, str(path), "NA\nZ 8 40000 1 0\nY\n")),
                               ("apply", lambda: nxc.apply(bad, game=self.game)),
                               ("original with a trainer", lambda: nxc.original_with_pokes(bad, self.game, [1])),
                               ("add-dump", lambda: nxc.add_target(bad, self.game, b"x" * 40, nxc.KIND_Z80, dict(file="x.z80"))),
                               ("patched bytes", lambda: nxc.patched_bytes(bad, self.game))):
                with self.subTest(name):
                    self.assert_no_decompression(call)

    def test_original_with_no_trainer_is_the_file_itself_unchecked(self) -> None:
        self.assertEqual(nxc.original_with_pokes(self.patch, b"not the game", None), b"not the game")
        self.assertEqual(nxc.original_with_pokes(self.patch, self.game, []), self.game)
        with self.assertRaises(nxc.Wrong):
            nxc.original_with_pokes(self.patch, b"not the game", [1])

    def test_short_files_and_empty_blocks_are_clean_refusals(self) -> None:
        for data in (b"", b"N", b"NXC1", b"NXC1\x01", b"NXC1\x01\0", self.patch[:37], self.patch[:39]):
            with self.subTest(len=len(data)), self.assertRaises(nxc.Wrong):
                nxc.blocks(data)
                nxc.targets(data)
                nxc.check_key(data, self.game)
        for edit in (lambda bl, st: bl.append([b"SET2", b""]), lambda bl, st: bl.append([b"SET2", b"\0"]),
                     lambda bl, st: bl.append([b"SET2", b"\0\1\1\1\5ab"]), lambda bl, st: bl.append([b"TRN1", b""]),
                     lambda bl, st: bl.append([b"TGT1", b""])):
            bad = T.rekey(self.patch, self.game, edit)
            with self.assertRaises(nxc.Wrong):
                nxc.colour_sets(bad)
                nxc.trainers(bad)
                nxc.targets(bad)

    def run_tool(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(ROOT / "tools/nxc.py"), *args], capture_output=True, text=True,
                              env=dict(os.environ, PYTHONWARNINGS="ignore"))

    def test_the_command_line_gives_a_message_and_no_traceback(self) -> None:
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            tmp = Path(d)
            (tmp / "g.z80").write_bytes(self.game)
            for n, data in enumerate((b"", b"NXC1", self.patch[:30], T.rekey(self.patch, self.game, lambda bl, st: bl.append([b"SET2", b""])))):
                (tmp / f"{n}.nxc").write_bytes(data)
                r = self.run_tool(str(tmp / f"{n}.nxc"), str(tmp / "g.z80"), "-o", str(tmp / "o.nex"))
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("Refused", r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                self.assertFalse((tmp / "o.nex").exists())

    def test_the_tool_will_not_write_over_an_input(self) -> None:
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            tmp = Path(d)
            (tmp / "g.z80").write_bytes(self.game)
            (tmp / "p.nxc").write_bytes(self.patch)
            for out in ("g.z80", "p.nxc"):
                r = self.run_tool(str(tmp / "p.nxc"), str(tmp / "g.z80"), "-o", str(tmp / out))
                self.assertIn("one of the inputs", r.stderr)
            self.assertEqual((tmp / "g.z80").read_bytes(), self.game)
            self.assertEqual((tmp / "p.nxc").read_bytes(), self.patch)


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class Policies(Case):
    """One rule each, the same in both implementations."""

    def test_a_bank_block_the_header_does_not_list(self) -> None:
        def add(bl, st):
            bl.append([b"BNK1", struct.pack("<BH", 60, 4) + st.block(b"BNK1", 60)(nxc.zx0(b"abcd"))])
        self.refused_by_both(T.rekey(self.patch, self.game, add))

    def test_header_flags(self) -> None:
        bad = bytearray(self.patch)
        bad[5] = 0x80
        with self.assertRaises(nxc.Wrong):
            nxc.apply(bytes(bad), game=self.game)
        m, failed, message = self.go(bytes(bad))
        self.assert_refused(m, failed, message, "Not a .nxc file")

    def test_opt1_flags_and_length(self) -> None:
        def opt(value):
            def edit(bl, st):
                for e in bl:
                    if e[0] == b"OPT1":
                        e[1] = value
            return T.rekey(self.patch, self.game, edit)
        self.refused_by_both(opt(b"\x01\x80\x0a"), LEVEL)
        self.refused_by_both(opt(b"\x01\0"))
        self.refused_by_both(opt(b"\x01\0\x0a\0"))
        self.refused_by_both(opt(b""))
        self.refused_by_both(opt(b"\x01\0\x70"))

    def test_trainer_flags_are_reserved(self) -> None:
        def flag(value):
            def edit(bl, st):
                for e in bl:
                    if e[0] == b"TRN1":
                        e[1] = bytes((value,)) + e[1][1:]
            return T.rekey(self.patch, self.game, edit)
        for value in (1, 2, 0x80):
            self.refused_by_both(flag(value))
        with self.assertRaises(nxc.Wrong):
            nxc.trainers(flag(1))
        self.assertEqual(nxc.trainers(self.patch)[0][0], 0)

    def test_a_poke_out_of_range_refuses_the_patch_whether_chosen_or_not(self) -> None:
        for poke in (struct.pack("<BHB", 112, 0, 1), struct.pack("<BHB", 2, 16384, 1)):
            add = lambda bl, st: bl.insert(1, [b"TRN1", bytes((0, 1)) + b"x" + bytes((1,)) + poke])  # noqa: E731
            self.refused_by_both(T.rekey(self.patch, self.game, add))

    def test_a_repeated_stream_index_would_reuse_a_stream(self) -> None:
        one = lambda st, index, kind, name: bytes((index, kind, 1, 1, 1)) + name + T.set_body(st, index, 1, [])  # noqa: E731
        self.refused_by_both(T.rekey(self.patch, self.game, lambda bl, st: bl.extend([[b"SET2", one(st, 7, 1, b"a")], [b"SET2", one(st, 7, 1, b"b")]])))
        # Across kinds too, whether or not this reader can apply the kind.
        self.refused_by_both(T.rekey(self.patch, self.game, lambda bl, st: bl.extend([[b"SET2", one(st, 7, 1, b"a")], [b"SET2", one(st, 7, 2, b"b")]])))
        self.refused_by_both(T.rekey(self.patch, self.game, lambda bl, st: bl.extend([[b"SET2", one(st, 7, 1, b"a")], [b"SET2", one(st, 7, 9, b"b")]])))
        m, failed, message = self.go(T.rekey(self.patch, self.game, lambda bl, st: bl.extend([[b"SET2", one(st, 255, 1, b"a")], [b"SET2", one(st, 254, 1, b"b")]])))
        self.assertFalse(failed, message)                 # different indices are fine

    def test_a_site_must_be_in_a_bank_the_build_takes_from_the_game(self) -> None:
        site = lambda b: struct.pack("<H", 1) + struct.pack("<BHH", b, 0, 2) + b"xx"  # noqa: E731
        def table(b):
            def edit(bl, st):
                for e in bl:
                    if e[0] == b"SIT1":
                        e[1] = st.block(b"SIT1")(nxc.zx0(site(b)))
            return T.rekey(self.patch, self.game, edit)
        self.refused_by_both(table(10))       # supplied by a BNK1
        self.refused_by_both(table(60))       # not in the game
        def header_without_2(bl, st):
            for e in bl:
                if e[0] == b"NEX1":
                    h = bytearray(self.nex[:512])
                    h[18 + 2] = 0
                    e[1] = st.block(b"NEX1")(nxc.zx0(bytes(h)))
                if e[0] == b"SIT1":
                    e[1] = st.block(b"SIT1")(nxc.zx0(site(2)))
        self.refused_by_both(T.rekey(self.patch, self.game, header_without_2))

    def test_controls(self) -> None:
        for name, replace, patch in (
                ("flags honoured", [("""        ld      a,(smallbuf)
        or      a
        jp      nz,bad_patch
        ld      a,(smallbuf+1)              ; the name: 1 to 25""", """        ld      a,(smallbuf+1)              ; the name: 1 to 25""")],
                 T.rekey(self.patch, self.game, lambda bl, st: [e.__setitem__(1, b"\1" + e[1][1:]) for e in bl if e[0] == b"TRN1"])),
                ("a repeated index", [("""        ld      a,d
        and     (hl)
        jp      nz,bad_patch
""", "")], T.rekey(self.patch, self.game, lambda bl, st: bl.extend(
                    [[b"SET2", bytes((7, 1, 1, 1, 1)) + b"a" + b"x"], [b"SET2", bytes((7, 1, 2, 1, 1)) + b"b" + b"y"]]))),
                ("an unlisted bank", [("""        pop     af                          ; a BNK1 for a bank not listed is damage
        jp      nz,bad_patch
""", """        pop     af
""")], T.rekey(self.patch, self.game, lambda bl, st: bl.append([b"BNK1", struct.pack("<BH", 60, 4) + b"zzzz"])))):
            with self.subTest(name):
                m, failed, message = self.control(replace, patch)
                self.assertFalse(failed, f"a loader with {name} refused it")


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class Keying(Case):
    def test_randomness_is_fresh(self) -> None:
        a = self.build(self.game)[0]
        b = self.build(self.game)[0]
        self.assertNotEqual(a[nxc.NONCE_AT:nxc.CHECK_AT], b[nxc.NONCE_AT:nxc.CHECK_AT])
        self.assertNotEqual(T.unlocked(a, self.game)[3], T.unlocked(b, self.game)[3])
        self.assertEqual(nxc.apply(a, game=self.game), nxc.apply(b, game=self.game))

    def test_no_two_uses_share_a_stream(self) -> None:
        nonce = bytes(range(16))
        master = key = nxc.key_state(nonce, bytes(range(100, 116)))
        dump = nxc.dump_state(nonce, self.game)
        seen = {}
        uses = [(key, t, 0) for t in (b"OUT1", b"NEX1", b"SIT1", b"CHK1")]
        uses += [(key, b"BNK1", n) for n in (0, 1, 112, 255)] + [(key, b"SEB" + bytes((s,)), n) for s in (0, 1, 255) for n in (0, 1, 2, 111, 255)] + [(key, b"SCR1", n) for n in range(6)]
        uses += [(dump, b"TGT1", n) for n in range(32)]
        for state, tag, index in uses:
            out = state.block(tag, index)(bytes(32))
            self.assertNotIn(out, seen, (tag, index))
            seen[out] = 1
        self.assertIsNotNone(master)

    def test_a_short_key_is_mixed_as_well_as_a_long_game_is(self) -> None:
        nonce = bytes(range(16))
        fixed = sum(a == b for a, b in enumerate(nxc.key_state(nonce, bytes(range(16))).base[0]))
        self.assertLess(fixed, 8)                         # one pass of 48 bytes leaves about 173 of the 256 where they began
        self.assertEqual(nxc.KEY_ROUNDS, 16)

    def test_the_owners_poc_against_the_new_format(self) -> None:
        # A clear TRN1 value flipped. Old: XOR the encrypted CRC by old CRC XOR new CRC. Every field that might stand in for
        # it now: the check field, and OUT1, by the same difference. Nobody without the game has anything else to XOR.
        at = find_block(self.patch, b"TRN1") + 2 + nxc.parse_trn1(dict(nxc.blocks(self.patch)[1])[b"TRN1"])[1].__len__() + 1 + 3
        bad = bytearray(self.patch)
        bad[at] ^= 0x55
        difference = struct.pack("<I", zlib.crc32(self.patch) ^ zlib.crc32(bytes(bad)))
        out_at = find_block(self.patch, b"OUT1")
        for name, places in (("flip alone", ()), ("the check, 4 bytes", (nxc.CHECK_AT,)), ("the check's end", (nxc.HEADER - 4,)),
                             ("OUT1", (out_at,)), ("both", (nxc.CHECK_AT, out_at))):
            with self.subTest(name):
                forged = bytearray(bad)
                for place in places:
                    for i in range(4):
                        forged[place + i] ^= difference[i]
                self.refused_by_both(bytes(forged))

    def test_every_clear_field_is_covered(self) -> None:
        for name, position in (("nonce", nxc.NONCE_AT), ("check", nxc.CHECK_AT), ("check's last", nxc.HEADER - 1), ("first tag", nxc.HEADER),
                               ("publisher", self.patch.index(b"publisher=") + 11), ("title", self.patch.index(b"title=") + 7),
                               ("colour set's name", self.patch.index(b"Painted")), ("bank number", find_block(self.patch, b"BNK1")),
                               ("trainer's name", self.patch.index(b"Lives"))):
            with self.subTest(name):
                bad = bytearray(self.patch)
                bad[position] ^= 0x02
                with self.assertRaises(nxc.Wrong):
                    nxc.apply(bytes(bad), game=self.game)
                m, failed, message = self.go(bytes(bad))
                self.assertTrue(failed)
                self.assertNotIn(NEX, m.written)

    def test_additions_and_removals_are_covered(self) -> None:
        self.refused_by_both(self.patch + nxc.block(b"XYZ1", b"added"))
        self.refused_by_both(self.patch[:-1], DAMAGED)
        at = find_block(self.patch, b"TRN1") - 8
        size = struct.unpack_from("<I", self.patch, at + 4)[0]
        self.refused_by_both(self.patch[:at] + self.patch[at + 8 + size:])

    def test_an_owner_can_forge_a_patch(self) -> None:
        # The format says so: this is no protection against someone with the game.
        changed = T.rekey(self.patch, self.game, lambda bl, st: bl.insert(1, [b"XYZ1", b"from an owner"]))
        self.assertEqual(nxc.apply(changed, game=self.game), self.base)

    def test_published_checksums_unlock_nothing(self) -> None:
        for key in (hashlib.md5(self.game).digest(), hashlib.md5(self.game).hexdigest().encode(),
                    hashlib.sha1(self.game).digest(), hashlib.sha512(self.game).digest()):
            with self.assertRaises(nxc.Wrong):
                nxc.check_key(self.patch, key)
            m, failed, message = self.go(game=key)
            self.assert_refused(m, failed, message, WRONG)

    def test_the_game_and_its_memory_do_not_show_through(self) -> None:
        for data in (self.game, b"".join(self.banks.values())):
            runs = {data[i:i + 16] for i in range(0, len(data) - 16) if len(set(data[i:i + 16])) > 4}
            self.assertFalse(any(self.patch[i:i + 16] in runs for i in range(len(self.patch) - 16)))

    def test_a_proof_block_has_only_its_own_fields(self) -> None:
        self.assertIn(b"replay=x\n", nxc.proof_text(dict(replay="x")))
        with self.assertRaises(ValueError):
            nxc.proof_text(dict(status="merged"))

    def test_controls(self) -> None:
        # An old-style check that only looks at a plain CRC would pass the PoC: a loader that skips the keyed check does.
        at = self.patch.index(b"Lives") + 5 + 1 + 3
        bad = bytearray(self.patch)
        bad[at] ^= 0x55
        m, failed, message = self.control([("""        or      a
        jp      nz,bad_patch
        inc     hl
        djnz    .cmp""", """        or      a
        nop
        nop
        nop
        inc     hl
        djnz    .cmp""")], bytes(bad), keys=["1", "enter"])
        self.assertFalse(failed, "a loader with no keyed check refused the forgery, so this test proves nothing")


REAL = T.HAVE_COBRA


@T.needs_tools
@unittest.skipUnless(REAL, "Cobra's game or patch is missing")
class RealGame(T.Base):
    """The same forgeries on a real game, read at run time; nothing about it is kept here."""

    def test_the_owners_poc(self) -> None:
        game = T.COBRA_GAME.read_bytes()
        patch = nxc.import_pok(T.COBRA_PATCH.read_bytes(), str(T.COBRA_GAME), "NLives\nZ 8 40000 1 0\nY\n")
        name = T.text_of(patch, b"TGT1")["file"].lower()
        at = patch.index(b"Lives") + 5 + 1 + 3
        bad = bytearray(patch)
        bad[at] ^= 0x55
        difference = struct.pack("<I", zlib.crc32(patch) ^ zlib.crc32(bytes(bad)))
        for i in range(4):
            bad[nxc.CHECK_AT + i] ^= difference[i]
        with self.assertRaises(nxc.Wrong):
            nxc.apply(bytes(bad), game=game)
        m = self.machine({"patch.nxc": bytes(bad), name: game}, keys=["1", "enter"])
        failed, message = m.run('"patch.nxc"')
        self.assert_refused(m, failed, message, DAMAGED)

    def test_the_same_memory_in_other_forms(self) -> None:
        game = T.COBRA_GAME.read_bytes()
        patch = T.COBRA_PATCH.read_bytes()
        banks = {b: bytes(d) for b, d in nxc.Z80Snapshot(str(T.COBRA_GAME)).banks.items()}
        base = nxc.apply(patch, game=game)
        forms = {"v1.z80": T.snapshot_v1(banks), "v2.z80": T.snapshot_paged(banks, 23, 0), "v3.z80": T.snapshot_paged(banks, 54, 0), "s.sna": sna(banks)}
        for name, data in forms.items():
            patch = nxc.add_target(patch, game, data, nxc.kind_of_name(name), dict(file=name))
        for name, data in forms.items():
            self.assertEqual(nxc.apply(patch, game=data), base, name)
            if name.endswith(".z80"):
                m = self.machine({"patch.nxc": patch, name: data})
                failed, message = m.run('"patch.nxc"')
                self.assertFalse(failed, message)
                self.assertEqual(bytes(m.written[NEX]), base, name)


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class SeveralDumps(Case):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        b = cls.banks
        cls.forms = {"v1pack.z80": T.snapshot_v1(b), "v1raw.z80": T.snapshot_v1(b, packed=False), "v2.z80": T.snapshot_paged(b, 23, 0),
                     "order.z80": T.snapshot_paged(b, 54, 0, order=[5, 4, 8]), "stored.z80": T.snapshot_paged(b, 54, 0, raw=(4, 8)),
                     "long.z80": T.snapshot_paged(b, 55, 0)}
        cls.many = cls.patch
        for name, data in cls.forms.items():
            cls.many = nxc.add_target(cls.many, cls.game, data, nxc.KIND_Z80, dict(file=name, zxdb_entry="0000001"))
        cls.many = nxc.add_target(cls.many, cls.game, sna(b), nxc.KIND_SNA, dict(file="s.sna"))

    def test_every_form_rebuilds_the_same_through_the_tool(self) -> None:
        self.assertEqual(len(nxc.targets(self.many)), len(self.forms) + 2)
        self.assertEqual(nxc.apply(self.many, game=self.game), self.base)
        for name, data in {**self.forms, "s.sna": sna(self.banks)}.items():
            with self.subTest(name):
                self.assertEqual(nxc.apply(self.many, game=data), self.base)
                self.assertEqual(nxc.apply(self.many, game=data, colours="Painted"), nxc.apply(self.many, game=self.game, colours="Painted"))
                self.assertEqual(nxc.apply(self.many, game=data, chosen=[1]), nxc.apply(self.many, game=self.game, chosen=[1]))

    def test_every_form_rebuilds_the_same_through_the_loader(self) -> None:
        for name, data in self.forms.items():
            with self.subTest(name):
                m = self.machine({"patch.nxc": self.many, name: data})
                failed, message = m.run('"patch.nxc"')
                self.assertFalse(failed, message)
                self.assertEqual(m.clean(), [])
                self.assertEqual(bytes(m.written[NEX]), self.base)

    def test_the_clash_fix_off_is_each_players_own_file(self) -> None:
        for name, data in self.forms.items():
            with self.subTest(name):
                m = self.machine({"patch.nxc": self.many, name: data}, keys=["2", "enter"])
                self.assertFalse(m.run('"patch.nxc"')[0])
                self.assertEqual(bytes(m.written[Z80]), data)
                m = self.machine({"patch.nxc": self.many, name: data}, keys=["1", "2", "enter"])
                self.assertFalse(m.run('"patch.nxc"')[0])
                self.assertEqual(bytes(m.written[Z80]), nxc.original_with_pokes(self.many, data, [1]))

    def test_a_file_under_any_listed_name_is_tried_against_every_entry(self) -> None:
        m = self.machine({"patch.nxc": self.many, "game.z80": self.forms["v2.z80"]})
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), self.base)

    def test_the_game_is_read_once_for_all_its_entries(self) -> None:
        # Every entry the same length, the last the right one: all tried from one absorbing.
        patch = self.patch
        nonce, _, _, master = T.unlocked(patch, self.game)
        first = struct.pack("<BBI", 0, nxc.KIND_Z80, len(self.game)) + os.urandom(24) + b"file=a.z80\nmd5=0\n"
        second = struct.pack("<BBI", 1, nxc.KIND_Z80, len(self.game)) + os.urandom(24) + b"file=b.z80\nmd5=0\n"
        third = nxc.target_block(2, nxc.KIND_Z80, self.game, nonce, master, dict(file="game.z80"))
        def edit(bl, st):
            at = next(i for i, e in enumerate(bl) if e[0] == b"TGT1")
            bl[at:at + 1] = [[b"TGT1", first], [b"TGT1", second], [b"TGT1", third]]
        forged = T.rekey(patch, self.game, edit)
        self.assertEqual(nxc.apply(forged, game=self.game), self.base)
        m = self.machine({"patch.nxc": forged, "game.z80": self.game})
        m.set_phases(["absorb_game", "create_out", "done"])
        hits = []
        m.callbacks["absorb_game"] = lambda: hits.append(1)
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(len(hits), 1, "the game was read again for another entry")
        self.assertEqual(m.opened.count("game.z80"), 1)

    def test_names_are_tried_in_turn_and_the_wrong_length_is_passed_over(self) -> None:
        m = self.machine({"patch.nxc": self.many, "game.z80": b"short", "v2.z80": self.forms["v2.z80"]})
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), self.base)
        self.assertEqual(m.opened[:3], ["patch.nxc", "game.z80", "v1pack.z80"])

    def test_a_wrong_file_of_the_right_length_is_passed_for_the_next(self) -> None:
        wrong = bytearray(self.forms["v2.z80"])
        wrong[40000 % len(wrong)] ^= 1
        m = self.machine({"patch.nxc": self.many, "v2.z80": bytes(wrong), "order.z80": self.forms["order.z80"]})
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), self.base)

    def test_one_wrong_file_is_refused(self) -> None:
        wrong = bytearray(self.forms["v2.z80"])
        wrong[len(wrong) // 2] ^= 1
        with self.assertRaises(nxc.Wrong):
            nxc.apply(self.many, game=bytes(wrong))
        m = self.machine({"patch.nxc": self.many, "v2.z80": bytes(wrong)})
        failed, message = m.run('"patch.nxc"')
        self.assert_refused(m, failed, message, WRONG)
        self.assertIn("game.z80", m.printed.decode("latin-1"))

    def test_a_file_of_no_listed_length_is_refused_before_the_menu(self) -> None:
        m = self.machine({"patch.nxc": self.many, "v2.z80": b"short"})
        failed, message = m.run('"patch.nxc"')
        self.assert_refused(m, failed, message, WRONG)
        self.assertEqual(m.screens, ["\n".join(m.screen)], "a menu was shown")

    def test_a_loader_never_opens_a_kind_it_cannot_read(self) -> None:
        m = self.machine({"patch.nxc": self.many, "s.sna": sna(self.banks)})
        failed, message = m.run('"patch.nxc"')
        self.assertEqual((failed, message), (True, "Game not beside the patch"))
        self.assertNotIn("s.sna", m.opened)

    def test_the_patchs_own_name_is_still_a_fall_back(self) -> None:
        m = self.machine({"mine.nxc": self.many, "mine.z80": self.forms["v2.z80"]})
        failed, message = m.run('"mine.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), self.base)

    def test_a_dump_that_rebuilds_differently_is_refused_before_anything_is_written(self) -> None:
        other = {**self.banks, 2: bank(99)}
        with self.assertRaisesRegex(nxc.Wrong, "does not rebuild the same banks"):
            nxc.add_target(self.patch, self.game, T.snapshot_paged(other, 23, 0), nxc.KIND_Z80, dict(file="x.z80"))
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            tmp = Path(d)
            for name, data in (("p.nxc", self.patch), ("g.z80", self.game), ("n.z80", T.snapshot_paged(other, 23, 0))):
                (tmp / name).write_bytes(data)
            r = subprocess.run([sys.executable, "-W", "ignore", str(ROOT / "tools/nxc.py"), "add-dump", str(tmp / "p.nxc"), str(tmp / "g.z80"),
                                str(tmp / "n.z80"), "-o", str(tmp / "o.nxc")], capture_output=True, text=True)
            self.assertIn("does not rebuild", r.stderr)
            self.assertFalse((tmp / "o.nxc").exists())

    def test_no_dump_twice_and_no_name_twice(self) -> None:
        with self.assertRaisesRegex(nxc.Wrong, "already accepts"):
            nxc.add_target(self.patch, self.game, self.game, nxc.KIND_Z80, dict(file="other.z80"))
        with self.assertRaisesRegex(nxc.Wrong, "that file name"):
            nxc.add_target(self.patch, self.game, self.forms["v2.z80"], nxc.KIND_Z80, dict(file="GAME.Z80"))

    def test_levels(self) -> None:
        self.assertEqual(dict(nxc.blocks(self.many)[1])[b"OPT1"][:2], b"\x01\0")     # a .z80 among them: level 1
        only_sna, _ = self.build(sna(self.banks), "g.sna")
        self.assertEqual(dict(nxc.blocks(only_sna)[1])[b"OPT1"][:2], b"\x03\0")
        self.assertEqual(nxc.apply(only_sna, game=sna(self.banks)), self.base)
        m = self.machine({"patch.nxc": only_sna, "g.sna": sna(self.banks)})
        failed, message = m.run('"patch.nxc"')
        self.assert_refused(m, failed, message, LEVEL)
        self.assertEqual(m.opened, ["patch.nxc"])
        added = nxc.add_target(only_sna, sna(self.banks), self.game, nxc.KIND_Z80, dict(file="game.z80"))
        self.assertEqual(dict(nxc.blocks(added)[1])[b"OPT1"][:2], b"\x01\0")
        self.assertEqual(nxc.original_with_pokes(only_sna, sna(self.banks), [1])[27 + 16384 + 16000], 0xAB)

    def test_a_128k_sna(self) -> None:
        b = {n: bank(n + 80) for n in range(8)}
        for top, size in ((0, 131103), (3, 131103), (5, 147487), (2, 147487)):
            rest = [n for n in range(8) if n not in (5, 2, top)]
            data = bytes(27) + b[5] + b[2] + b[top] + bytes(2) + bytes((top,)) + bytes(1) + b"".join(b[n] for n in rest)
            self.assertEqual(len(data), size)
            snap = nxc.snapshot_of(data, nxc.KIND_SNA)
            self.assertTrue(snap.is128)
            self.assertEqual({k: bytes(v) for k, v in snap.banks.items()}, b)
        for bad in (b"", bytes(100), bytes(49178), bytes(131104)):
            with self.assertRaises(nxc.Wrong):
                nxc.snapshot_of(bad, nxc.KIND_SNA)

    def test_the_most_entries_and_one_more(self) -> None:
        nonce, _, _, master = T.unlocked(self.patch, self.game)

        def entries(n):
            def edit(bl, st):
                at = next(i for i, e in enumerate(bl) if e[0] == b"TGT1")
                fill = [[b"TGT1", struct.pack("<BBI", k, nxc.KIND_Z80, len(self.game)) + bytes(24) + b"file=f%d.z80\nmd5=0\n" % k] for k in range(n - 1)]
                real = nxc.target_block(n - 1, nxc.KIND_Z80, self.game, nonce, master, dict(file="game.z80"))
                bl[at:at + 1] = fill + [[b"TGT1", real]]
            return T.rekey(self.patch, self.game, edit)

        full = entries(nxc.TARGETS_MAX)
        self.assertEqual(nxc.apply(full, game=self.game), self.base)
        m = self.machine({"patch.nxc": full, "game.z80": self.game})
        m.set_phases(["absorb_game", "check_file", "done"])
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), self.base)
        one = self.machine({"patch.nxc": self.patch, "game.z80": self.game})
        one.set_phases(["absorb_game", "check_file", "done"])
        one.run('"patch.nxc"')
        extra = (m.phase_ticks["absorb_game"] - one.phase_ticks["absorb_game"]) / 28e6
        print(f"\nEntries: {nxc.TARGETS_MAX} of one length, the right one last: {len(full) - len(self.patch)} more bytes of patch; "
              f"absorb and try {m.phase_ticks['absorb_game'] / 28e6:.3f} s against {one.phase_ticks['absorb_game'] / 28e6:.3f} s for one entry, "
              f"so {extra * 1000 / (nxc.TARGETS_MAX - 1):.1f} ms an entry at 28 MHz, no file I/O", flush=True)
        self.assertEqual(m.peak_pages, one.peak_pages)
        self.refused_by_both(entries(nxc.TARGETS_MAX + 1))

    def test_a_target_out_of_place_is_refused(self) -> None:
        def edit(bl, st):
            for e in bl:
                if e[0] == b"TGT1":
                    e[1] = bytes((1,)) + e[1][1:]
        self.refused_by_both(T.rekey(self.patch, self.game, edit))
        def short(bl, st):
            for e in bl:
                if e[0] == b"TGT1":
                    e[1] = e[1][:29]
        self.refused_by_both(T.rekey(self.patch, self.game, short))
        def no_file(bl, st):
            for e in bl:
                if e[0] == b"TGT1":
                    e[1] = e[1][:nxc.TARGET_FIXED] + b"title=x\n"
        self.refused_by_both(T.rekey(self.patch, self.game, no_file))
        self.refused_by_both(T.rekey(self.patch, self.game, lambda bl, st: bl.__setitem__(slice(None), [e for e in bl if e[0] != b"TGT1"])))


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class Split(Case):
    def test_the_first_part_is_exactly_what_nextzxos_loads(self) -> None:
        self.assertGreater(len(self.binary), H.FIRST_PART)
        self.assertEqual(len(self.binary), H.FIRST_PART + self.symbols["ov_size"])
        self.assertEqual(self.binary[-4:], b"NXQ1")
        self.assertLessEqual(self.symbols["code_end"], self.symbols["patch_path"])

    def test_every_message_fits_what_nextzxos_shows(self) -> None:
        # In JNext, NextZXOS cut an error message of 40 characters at 32.
        text = T.H.SOURCE.read_text()
        import re
        for name, body in re.findall(r"^(msg_\w+):\s+db \"([^\"]*)\", '.' \| \$80", text, re.M):
            self.assertLessEqual(len(body) + 1, 32, name)

    def test_a_cut_or_mixed_file_gives_a_clear_message(self) -> None:
        said = "NEXCLASH cut or mixed: recopy it"
        for name, binary in (("first part only", self.binary[:H.FIRST_PART]), ("cut short", self.binary[:-1]), ("cut more", self.binary[:H.FIRST_PART + 100]),
                             ("another's tail", self.binary[:-4] + b"XXXX")):
            with self.subTest(name):
                m = self.machine({"patch.nxc": self.patch, "game.z80": self.game}, binary=binary)
                failed, message = m.run('"patch.nxc"')
                self.assertEqual((failed, message), (True, said))
                self.assertEqual(m.written, {})
                self.assertEqual(m.clean(), [])

    def test_the_refusals_before_the_menu_need_only_the_first_part(self) -> None:
        m = self.machine({}, binary=self.binary[:H.FIRST_PART])
        self.assertEqual(m.run('"nothing.nxc"'), (True, "Cannot open the .nxc"))


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class Sets(Case):
    """Two kinds on one made-up build. Colours change one part of a bank, languages another; the two languages overlap."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.plain, cls.plain_nex = cls.build(cls.game, sets=False)
        offs = {b: 512 + i * 16384 for i, b in enumerate(b for b in nxc.ORDER if cls.plain_nex[18 + b])}
        cls.offs = offs

        def variant(*changes):
            d = bytearray(cls.plain_nex)
            for bank, offset, data in changes:
                d[offs[bank] + offset:offs[bank] + offset + len(data)] = data
            return bytes(d)
        cls.changes = {
            "Red": ((2, 100, b"\x11" * 8), (10, 50, b"\x22" * 4)),
            "Blue": ((2, 104, b"\x33" * 8),),
            "Deutsch": ((5, 1000, b"HALLO"), (2, 500, b"\x44" * 3)),
            "Espanol": ((5, 1002, b"BUENOS"),),
        }
        cls.patch2 = cls.two_kinds(variant)
        cls.variant = staticmethod(variant)

    @classmethod
    def two_kinds(cls, variant, colours=("Red", "Blue"), languages=("Deutsch", "Espanol"), changes=None, **more):
        changes = changes or cls.changes
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            tmp = Path(d)
            (tmp / "game.z80").write_bytes(cls.game)
            (tmp / "o.nex").write_bytes(cls.plain_nex)
            paths = {}
            for name in (*colours, *languages):
                (tmp / f"{name}.nex").write_bytes(variant(*changes[name]))
                paths[name] = str(tmp / f"{name}.nex")
            patch, _ = nxc.make(str(tmp / "game.z80"), str(tmp / "o.nex"), dict(title="Made Up", file="game.z80"), dict(build="t"),
                                colours={n: paths[n] for n in colours}, languages={n: paths[n] for n in languages},
                                trainer_blocks=[nxc.trn1("Lives", [(2, 16000, 0xAB)])], **more)
            return patch

    def want(self, colours=None, language=None) -> bytes:
        return self.variant(*(self.changes.get(colours) or ()), *(self.changes.get(language) or ()))

    def test_the_identity_itself(self) -> None:
        base = zlib.crc32(self.plain_nex)
        for colours in ("Red", "Blue"):
            for language in ("Deutsch", "Espanol"):
                combination = self.want(colours, language)
                self.assertEqual(zlib.crc32(combination), base ^ (zlib.crc32(self.want(colours)) ^ base) ^ (zlib.crc32(self.want(None, language)) ^ base))

    def test_every_combination_through_both(self) -> None:
        keys = {None: 0, "Red": 1, "Blue": 2}
        keys2 = {None: 0, "Deutsch": 1, "Espanol": 2}
        for colours, n in keys.items():
            for language, n2 in keys2.items():
                with self.subTest(colours=colours, language=language):
                    want = self.want(colours, language)
                    self.assertEqual(nxc.apply(self.patch2, game=self.game, colours=colours, language=language), want)
                    m, failed, message = self.go(self.patch2, keys=["3"] * n + ["4"] * n2 + ["enter"])
                    self.assertFalse(failed, message)
                    self.assertEqual(m.clean(), [])
                    self.assertEqual(bytes(m.written[NEX]), want)
                    self.assertEqual(m.peak_pages, 6 + 3 * bool(n) + 3 * bool(n2))

    def test_with_a_trainer_on_top(self) -> None:
        m, failed, message = self.go(self.patch2, keys=["1", "3", "4", "enter"])
        self.assertFalse(failed, message)
        out = bytes(m.written[NEX])
        self.assertEqual(out, nxc.apply(self.patch2, game=self.game, colours="Red", language="Deutsch", chosen=[1]))
        self.assertEqual(out[self.offs[2] + 16000], 0xAB)

    def test_the_menu_steps_through_the_names(self) -> None:
        m, failed, message = self.go(self.patch2, keys=["3", "3", "3", "4", "4", "enter"])
        self.assertFalse(failed, message)
        line = lambda s, label: next(x for x in s.split("\n") if label in x)  # noqa: E731
        self.assertEqual([line(s, "Enhanced colours").split("colours")[1].strip() for s in m.screens[1:5]], ["[OFF]", "[Red]", "[Blue]", "[OFF]"])
        self.assertEqual(m.screens[-2].split("\n")[3:9], ["  1  Lives                     [OFF]", "", " NEXCLASH", "  2  Colour clash fix          [ON]",
                                                          "  3  Enhanced colours          [OFF]", "  4  Language                  [Espanol]"])
        self.assertEqual(bytes(m.written[NEX]), self.want(None, "Espanol"))

    def test_with_the_fix_off_each_line_is_not_available_and_comes_back(self) -> None:
        m, failed, message = self.go(self.patch2, keys=["3", "4", "2", "3", "4", "2", "enter"])
        self.assertFalse(failed, message)
        self.assertIn("Language                  [N/A]", m.screens[4])
        self.assertIn("Enhanced colours          [N/A]", m.screens[4])
        self.assertEqual(bytes(m.written[NEX]), self.want("Red", "Deutsch"))
        m, failed, message = self.go(self.patch2, keys=["3", "4", "2", "enter"])
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[Z80]), self.game)
        self.assertEqual(m.peak_pages, 0)

    def test_one_set_of_colours_says_on_and_off_and_a_long_name_fits(self) -> None:
        longer = dict(self.changes, **{"A language of 25 letters!": self.changes["Deutsch"]})
        patch = self.two_kinds(self.variant, colours=("Red",), languages=("A language of 25 letters!",), changes=longer)
        m, failed, message = self.go(patch, keys=["3", "4", "enter"])
        self.assertFalse(failed, message)
        self.assertIn("  3  Enhanced colours          [ON]", m.screens[-2])
        self.assertIn("  4  Language " + " " * 8 + "[A language of 25 ]", m.screens[-2])
        self.assertLessEqual(max(len(x) for x in m.screens[-2].split("\n")), 41)
        self.assertEqual(bytes(m.written[NEX]), self.want("Red", "Deutsch"))

    def test_two_kinds_leave_room_for_seven_trainers(self) -> None:
        def eight(bl, st):
            for n in range(8):
                bl.insert(1, [b"TRN1", nxc.trn1(f"T{7 - n}", [(2, 15000 + n, 1)])])
        patch = T.rekey(self.patch2, self.game, lambda bl, st: (bl.__setitem__(slice(None), [e for e in bl if e[0] != b"TRN1"]), eight(bl, st)))
        m, failed, message = self.go(patch, keys=["9", "0", "enter"])
        self.assertFalse(failed, message)
        screen = m.screens[-2]
        self.assertIn("  7  T6", screen)
        self.assertNotIn("T7", screen)
        self.assertIn("  8  Colour clash fix", screen)
        self.assertIn("  9  Enhanced colours          [Red]", screen)
        self.assertIn("  0  Language                  [Deutsch]", screen)
        self.assertEqual(bytes(m.written[NEX]), self.want("Red", "Deutsch"))

    def test_selectable_sets_that_overlap_are_refused_when_made(self) -> None:
        clash = dict(self.changes, Bad=((2, 107, b"\x99" * 2),))           # within Blue's 104 to 111
        with self.assertRaisesRegex(ValueError, "chosen together"):
            self.two_kinds(self.variant, languages=("Bad",), changes=clash)
        # The same bytes written the same way are still an overlap: the CRCs could not then be combined.
        same = dict(self.changes, Bad=((2, 104, b"\x33" * 8),))
        with self.assertRaisesRegex(ValueError, "chosen together"):
            self.two_kinds(self.variant, languages=("Bad",), changes=same)
        # Alternatives within a kind may overlap: Deutsch and Espanol do here, as Red and Blue do.
        self.assertEqual(nxc.languages(self.patch2), ["Deutsch", "Espanol"])

    def forged_overlap(self) -> bytes:
        """A patch whose two kinds overlap: nothing that a maker would write, but someone with the game can."""
        def edit(bl, st):
            for e in bl:
                if e[0] == b"SET2" and e[1][1:3] == bytes((2, 1)):
                    fixed = e[1][:nxc.SET_FIXED + e[1][4]]
                    e[1] = fixed + T.set_body(st, e[1][0], zlib.crc32(self.want(None, "Deutsch")), [(2, T.chunk_of((100, b"zz")))])
        return T.rekey(self.patch2, self.game, edit)

    def test_overlap_is_refused_for_the_actual_selection(self) -> None:
        forged = self.forged_overlap()
        with self.assertRaisesRegex(nxc.Wrong, "same bytes"):
            nxc.apply(forged, game=self.game, colours="Red", language="Deutsch")
        m, failed, message = self.go(forged, keys=["3", "4", "enter"])
        self.assert_refused(m, failed, message, DAMAGED)
        self.assertNotIn(NEX, m.opened)
        # Blue does not touch those bytes, so that selection passes the overlap check and meets its CRC instead.
        m, failed, message = self.go(forged, keys=["3", "3", "enter"])
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), self.want("Blue"))

    def test_overlap_in_a_later_bank_is_refused_before_any_file_is_made(self) -> None:
        # Red changes banks 2 and 10; this language agrees on bank 2 and meets it in bank 10, the last written.
        def edit(bl, st):
            for e in bl:
                if e[0] == b"SET2" and e[1][1:3] == bytes((2, 1)):
                    fixed = e[1][:nxc.SET_FIXED + e[1][4]]
                    e[1] = fixed + T.set_body(st, e[1][0], zlib.crc32(self.want(None, "Deutsch")), [(2, T.chunk_of((500, b"zz"))), (10, T.chunk_of((52, b"zz")))])
        forged = T.rekey(self.patch2, self.game, edit)
        with self.assertRaisesRegex(nxc.Wrong, "same bytes"):
            nxc.apply(forged, game=self.game, colours="Red", language="Deutsch")
        m, failed, message = self.go(forged, keys=["3", "4", "enter"])
        self.assert_refused(m, failed, message, DAMAGED)
        self.assertNotIn(NEX, m.opened)

    def test_chunks_out_of_order_are_refused(self) -> None:
        e = T.chunk_of
        crc = zlib.crc32(self.plain_nex)
        for name, chunks in (("banks against .nex order", [(2, e((100, b"x"))), (5, e((100, b"y")))]), ("a bank twice", [(2, e((100, b"x"))), (2, e((200, b"y")))]),
                             ("an unlisted bank", [(9, e((100, b"x")))]), ("no bytes", [(2, bytes(nxc.BITMAP))]), ("a bit with no byte", [(2, e((100, b"xy"))[:-1])])):
            with self.subTest(name):
                def edit(bl, st, chunks=chunks):
                    for x in bl:
                        if x[0] == b"SET2" and x[1][0] == 0:
                            x[1] = x[1][:nxc.SET_FIXED + x[1][4]] + T.set_body(st, 0, crc, chunks)
                forged = T.rekey(self.patch2, self.game, edit)
                with self.assertRaises(nxc.Wrong):
                    nxc.apply(forged, game=self.game, colours="Red")
                m, failed, message = self.go(forged, keys=["3", "enter"])
                self.assert_refused(m, failed, message, DAMAGED)
                self.assertNotIn(NEX, m.opened)

    def test_a_wrong_crc_for_one_set_fails_any_combination_with_it(self) -> None:
        def edit(bl, st):
            for x in bl:
                if x[0] == b"SET2" and x[1][0] == 0:
                    fixed = nxc.SET_FIXED + x[1][4]
                    plain = nxc.set_use(st, 0, nxc.SET_CRC_INDEX)(x[1][fixed:fixed + 4])
                    x[1] = x[1][:fixed] + nxc.set_use(st, 0, nxc.SET_CRC_INDEX)(bytes((plain[0] ^ 1,)) + plain[1:]) + x[1][fixed + 4:]
        forged = T.rekey(self.patch2, self.game, edit)
        for keys, colours, language in ((["3", "enter"], "Red", None), (["3", "4", "enter"], "Red", "Deutsch")):
            with self.assertRaises(nxc.Wrong):
                nxc.apply(forged, game=self.game, colours=colours, language=language)
            m, failed, message = self.go(forged, keys=keys)
            self.assert_refused(m, failed, message, "Rebuild failed: patch damaged")
        m, failed, message = self.go(forged, keys=["4", "enter"])
        self.assertFalse(failed, message)                                    # a set not chosen is not read

    def test_a_retired_set1_block_is_skipped_as_unknown(self) -> None:
        patch = T.rekey(self.patch2, self.game, lambda bl, st: bl.append([b"SET1", b"\0\1\1\1\x03oldnonsense"]))
        self.assertEqual(nxc.colour_sets(patch), ["Red", "Blue"])
        m, failed, message = self.go(patch, keys=["enter"])
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), self.want())

    def test_a_flipped_byte_in_a_set_is_refused_before_any_decoding(self) -> None:
        at = find_block(self.patch2, b"SET2", 2)
        for offset in (0, 1, 2, 3, 4, 5, 8, 12):
            bad = bytearray(self.patch2)
            bad[at + offset] ^= 0x10
            m, failed, message = self.go(bytes(bad), keys=["4", "enter"])
            self.assert_refused(m, failed, message)
            self.assertNotIn("zx0_decode", m.phase_ticks)

    def test_kinds_and_bases_this_reader_cannot_apply_are_not_offered(self) -> None:
        def add(bl, st):
            for index, kind, base, name in ((200, 9, 1, b"Other kind"), (201, 2, 2, b"Plain base"), (202, 0, 1, b"No kind")):
                bl.append([b"SET2", bytes((index, kind, 1, base, len(name))) + name + b"anything"])
        patch = T.rekey(self.patch2, self.game, add)
        self.assertEqual(nxc.languages(patch), ["Deutsch", "Espanol"])
        m, failed, message = self.go(patch, keys=["4", "enter"])
        self.assertFalse(failed, message)
        for name in ("Other kind", "Plain base", "No kind"):
            self.assertNotIn(name, "\n".join(m.screens))
        self.assertEqual(bytes(m.written[NEX]), self.want(None, "Deutsch"))
        with self.assertRaisesRegex(nxc.Wrong, "no language set"):
            nxc.apply(patch, game=self.game, language="Plain base")

    def test_a_language_alone_gets_its_line(self) -> None:
        patch = self.two_kinds(self.variant, colours=(), languages=("Deutsch",))
        self.assertIsNone(nxc.inf1_value(patch, "colours_by"))
        m, failed, message = self.go(patch, keys=["3", "enter"])
        self.assertFalse(failed, message)
        self.assertIn("  3  Language                  [Deutsch]", m.screens[-2])
        self.assertNotIn("Enhanced", m.screens[-2])
        self.assertEqual(bytes(m.written[NEX]), self.want(None, "Deutsch"))

    def test_a_poke_touching_any_set_is_refused_when_authored(self) -> None:
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            path = Path(d) / "game.z80"
            path.write_bytes(self.game)
            for address, why in ((0x8000 + 100, "colours"), (0x8000 + 104, "another colour set"), (0x4000 + 1003, "a language"), (0x4000 + 1007, "another language")):
                with self.subTest(why), self.assertRaisesRegex(nxc.Wrong, "lands on a byte the patch changes"):
                    nxc.import_pok(self.patch2, str(path), f"NBad\nZ 8 {address} 1 0\nY\n")

    def test_stable_choice_ids_and_one_name_a_kind(self) -> None:
        self.assertEqual([(e["kind"], e["choice"]) for e in nxc.sets(self.patch2)], [(1, 1), (1, 2), (2, 1), (2, 2)])
        self.assertEqual(sorted(e["stream"] for e in nxc.sets(self.patch2)), [0, 1, 2, 3])

    def test_not_enough_ram(self) -> None:
        for free, keys, said in ((8, ["3", "enter"], "Needs 72K free RAM"), (11, ["3", "4", "enter"], "Needs 96K free RAM")):
            m, failed, message = self.go(self.patch2, keys=keys, free_pages=free)
            self.assert_refused(m, failed, message, said)
            self.assertEqual(m.free_pages, free)

    def test_controls(self) -> None:
        forged = self.forged_overlap()
        m, failed, message = self.control([("""        and     (hl)
        jp      nz,bad_patch
        inc     hl
        inc     de
        dec     bc
""", """        and     (hl)
        nop
        nop
        nop
        inc     hl
        inc     de
        dec     bc
""")], forged, keys=["3", "4", "enter"])
        self.assertIn(NEX, m.opened, "a loader with no overlap check passed")
        def edit(bl, st):
            for x in bl:
                if x[0] == b"SET2" and x[1][0] == 0:
                    x[1] = x[1][:nxc.SET_FIXED + x[1][4]] + T.set_body(st, 0, zlib.crc32(self.plain_nex), [(2, T.chunk_of((100, b"x"))), (5, T.chunk_of((50, b"y")))])
        unordered = T.rekey(self.patch2, self.game, edit)
        m, failed, message = self.control([("""        ld      hl,set_recs+4
        call    is_zero32
        jp      nz,bad_patch
""", """        ld      hl,set_recs+4
        call    is_zero32
        nop
        nop
        nop
""")], unordered, keys=["3", "enter"])
        self.assertIn(NEX, m.opened, "a loader with no check of order passed")
        # The CRC of a combination taken from the first set alone would be wrong for two.
        m, failed, message = self.control([("""        ld      hl,want
        ld      de,tmp5
""", """        ld      a,(cur_kind)
        or      a
        jr      nz,.past
        ld      hl,want
        ld      de,tmp5
""")], self.patch2, keys=["3", "4", "enter"])
        self.assertEqual(message, "Rebuild failed: patch damaged", "a loader that leaves a set out of the CRC passed")


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class Memory(Case):
    def with_bank(self, bank: int) -> bytes:
        return T.rekey(self.patch, self.game, lambda bl, st: [e.__setitem__(1, e[1][:2] + bytes((bank,))) for e in bl if e[0] == b"OPT1"])

    def test_it_comes_from_the_nex_and_an_author_can_only_raise_it(self) -> None:
        self.assertEqual(dict(nxc.blocks(self.patch)[1])[b"OPT1"][2], 10)     # the highest listed here
        for flag, listed, want in ((0, (5, 2, 0), 5), (0, (5, 47), 47), (0, (5, 48), 48), (1, (5,), 48), (0, (111,), 111)):
            nex = bytearray(512)
            nex[8] = flag
            for b in listed:
                nex[18 + b] = 1
            self.assertEqual(nxc.lowest_memory(bytes(nex)), want)
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            tmp = Path(d)
            (tmp / "g.z80").write_bytes(self.game)
            (tmp / "o.nex").write_bytes(self.nex)
            make = lambda bank: nxc.make(str(tmp / "g.z80"), str(tmp / "o.nex"), dict(file="g.z80"), dict(build="t"), highest_bank=bank)[0]  # noqa: E731
            self.assertEqual(dict(nxc.blocks(make(60))[1])[b"OPT1"][2], 60)
            for bad in (9, 112):
                with self.assertRaisesRegex(ValueError, "highest bank"):
                    make(bad)

    def test_a_machine_with_too_little_is_refused_clearly_and_only_for_the_rebuild(self) -> None:
        needs_more = self.with_bank(48)
        said = "Needs more RAM: turn fix off"
        m, failed, message = self.go(needs_more, total_pages=96)
        self.assert_refused(m, failed, message, said)
        self.assertEqual(m.ever_allocated, [])
        # A 2MB machine plays it. The bank that just fits a 1MB machine plays on one.
        m, failed, message = self.go(needs_more, total_pages=224)
        self.assertFalse(failed, message)
        m, failed, message = self.go(self.with_bank(47), total_pages=96)
        self.assertFalse(failed, message)
        m, failed, message = self.go(self.with_bank(111), total_pages=224)
        self.assertFalse(failed, message)
        # With the fix off it is the player's own game, which never needed it.
        m, failed, message = self.go(needs_more, keys=["2", "enter"], total_pages=96)
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[Z80]), self.game)
        m, failed, message = self.go(needs_more, keys=["1", "2", "enter"], total_pages=96)
        self.assertFalse(failed, message)
        self.assertIn(Z80, m.written)

    def test_if_nextzxos_will_not_say_it_goes_on(self) -> None:
        m, failed, message = self.go(self.with_bank(111), total_pages=None)
        self.assertFalse(failed, message)

    def test_it_cannot_say_less_than_the_header_lists(self) -> None:
        self.refused_by_both(self.with_bank(9))

    def test_it_is_covered_by_the_keyed_check(self) -> None:
        bad = bytearray(self.patch)
        bad[find_block(self.patch, b"OPT1") + 2] = 20
        self.refused_by_both(bytes(bad))

    def test_controls(self) -> None:
        m, failed, message = self.control([(""".go:    call    wait_release
        call    check_ram
""", """.go:    call    wait_release
        nop
        nop
        nop
""")], self.with_bank(48), total_pages=96)
        self.assertFalse(failed, "a loader with no check of the memory refused it, so this test proves nothing")
        m, failed, message = self.control([("""        ld      a,(ram_bank)                ; OPT1 may say more than the header lists, not less
        ld      hl,cur_bank
        cp      (hl)
        jp      c,bad_patch
""", "")], self.with_bank(9))
        self.assertFalse(failed, "a loader that believes a low figure refused it, so this test proves nothing")


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class MakeCommand(Case):
    def run_tool(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-W", "ignore", str(ROOT / "tools/nxc.py"), *args], capture_output=True, text=True)

    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory(dir=TMP)
        self.tmp = Path(self.dir.name)
        (self.tmp / "game.z80").write_bytes(self.game)
        (self.tmp / "o.nex").write_bytes(self.nex)

    def tearDown(self) -> None:
        self.dir.cleanup()

    def make(self, *more, nex="o.nex", game="game.z80") -> subprocess.CompletedProcess:
        return self.run_tool("make", str(self.tmp / nex), str(self.tmp / game), "-o", str(self.tmp / "out.nxc"), *more)

    def test_every_option_and_the_result_rebuilds_exactly(self) -> None:
        (self.tmp / "proof.txt").write_text("# made here\nreplay=none\nhardware=none\nhardware_when=2026-11-03\n")
        painted = bytearray(self.nex)
        painted[512 + 16384 + 9] ^= 1
        (self.tmp / "p.nex").write_bytes(bytes(painted))
        r = self.make("--title", "Made Up", "--zxdb", "0000001", "--publisher", "Tester, 2026", "--patch-by", "Ann", "--colours-by", "Bob", "--rom", "1",
                      "--proof", "emulator=none", "--proof-file", str(self.tmp / "proof.txt"), "--highest-bank", "47", "--colours", "Red=" + str(self.tmp / "p.nex"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("rebuilds it exactly", r.stdout)
        self.assertIn("up to 16K bank 47", r.stdout)
        f = (self.tmp / "out.nxc").read_bytes()
        self.assertEqual(nxc.apply(f, game=self.game), self.nex)
        self.assertEqual(nxc.apply(f, game=self.game, colours="Red"), bytes(painted))
        blocks = dict(nxc.blocks(f)[1])
        self.assertEqual(blocks[b"ROM1"], b"\x01")
        self.assertEqual(blocks[b"OPT1"], bytes((1, 0, 47)))
        self.assertEqual(blocks[b"PRF1"], b"emulator=none\nreplay=none\nhardware=none\nhardware_when=2026-11-03\n")
        self.assertEqual(nxc.credit_line(f), "Patch: Ann     Colours: Bob")
        self.assertEqual(nxc.inf1_value(f, "publisher"), b"Tester, 2026")
        self.assertEqual(nxc.inf1_value(f, "nex_md5"), hashlib.md5(self.nex).hexdigest().encode())
        target = nxc.targets(f)[0]
        self.assertEqual((target["file"], target["title"]), ("game.z80", b"Made Up"))
        self.assertIn(b"zxdb_entry=0000001\n", target["text"])
        m, failed, message = self.go(f, keys=["2", "enter"])
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), bytes(painted))

    def test_the_least_it_needs(self) -> None:
        r = self.make()
        self.assertEqual(r.returncode, 0, r.stderr)
        f = (self.tmp / "out.nxc").read_bytes()
        self.assertEqual(nxc.apply(f, game=self.game), self.nex)
        self.assertEqual(nxc.inf1_value(f, "build"), b"o")
        self.assertIn(nxc.CREDIT.encode(), dict(nxc.blocks(f)[1])[b"INF1"])

    def test_clear_refusals_and_no_file_left(self) -> None:
        nex = self.nex
        wrong = bytearray(self.nex); wrong[4:8] = b"V1.3"
        screen = bytearray(self.nex); screen[10] = 0x40
        count = bytearray(self.nex); count[9] += 1
        flag = bytearray(self.nex); flag[18 + 7] = 2
        for name, data, said in (("not a .nex", b"not one" * 100, "not a .nex"), ("too short", nex[:100], "not a .nex"), ("V1.3", bytes(wrong), "V1.0 to V1.2"), ("a V1.3 screen", bytes(screen), "V1.3"),
                                 ("trailing bytes", nex + b"x", "past its banks"), ("cut short", nex[:-1], "past its banks"), ("a miscount", bytes(count), "count"), ("a bad flag", bytes(flag), "0 or 1")):
            with self.subTest(name):
                (self.tmp / "bad.nex").write_bytes(data)
                r = self.make(nex="bad.nex")
                self.assertNotEqual(r.returncode, 0)
                self.assertIn(said, r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                self.assertFalse((self.tmp / "out.nxc").exists())
        for name, args, said in (("a bad PRF1 key", ("--proof", "status=merged"), "not a PRF1 key"), ("no =", ("--proof", "replay"), "KEY=VALUE"), ("a low bank", ("--highest-bank", "9"), "highest bank"),
                                 ("a bad name", ("--file", "../x.z80"), "bare name"), ("unprintable", ("--patch-by", "caf\u00e9"), "printable"), ("too long for the menu", ("--publisher", "P" * 300, "--patch-by", "Ann"), "first 252")):
            with self.subTest(name):
                r = self.make(*args)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn(said, r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                self.assertFalse((self.tmp / "out.nxc").exists())
        r = self.run_tool("make", str(self.tmp / "o.nex"), str(self.tmp / "game.z80"), "-o", str(self.tmp / "o.nex"))
        self.assertIn("one of the inputs", r.stderr)
        (self.tmp / "game.tap").write_bytes(self.game)
        self.assertIn("needs --start", self.make(game="game.tap").stderr)
        (self.tmp / "game.szx").write_bytes(self.game)
        self.assertIn("is .z80, .sna, .tap or .tzx", self.make(game="game.szx").stderr)
        self.assertIn("No such file", self.make(game="nothing.z80").stderr)
        r = subprocess.run([sys.executable, "-W", "ignore", str(ROOT / "tools/nxc.py"), "make", str(self.tmp / "o.nex"), str(self.tmp / "game.z80"), "-o", str(self.tmp / "out.nxc")],
                           capture_output=True, text=True, env=dict(os.environ, NXC_ZX0_DIR=str(self.tmp)))
        self.assertIn("needs the zx0 compressor", r.stderr)

    def test_a_build_from_another_game_is_refused_or_rebuilds(self) -> None:
        # Whatever the game, the patch rebuilds that .nex or there is none: here most of bank 5 differs, and its bytes must fit a table.
        other = T.snapshot_paged({b: bank(b + 90) for b in (5, 2, 0)}, 54, 0)
        (self.tmp / "other.z80").write_bytes(other)
        r = self.make(game="other.z80")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("too big", r.stderr)


def screen_of(flags: int, seed: int = 3) -> bytes:
    rng = random.Random(seed)
    size = nxc.screen_size(flags)
    data = bytearray(rng.randrange(256) for _ in range(size))
    if size > 400:
        data[300:400] = bytes(100)           # some of it packs
    if size:
        data[-20:] = bytes(20)               # and a tail of zeros, trimmed like a bank's
    return bytes(data)


@T.needs_tools
@unittest.skipUnless(T.ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class LoadingScreen(Case):
    TYPES = {"layer 2 with a palette": 0x01, "layer 2 without": 0x81, "ULA": 0x02, "lo-res with a palette": 0x04, "lo-res without": 0x84, "hi-res": 0x08,
             "hi-colour": 0x10, "ULA and layer 2, whose palette .nexload then skips": 0x03, "every one, the largest": 0x1F, "bit 7 alone: no screen": 0x80}

    def with_screen(self, flags: int, **options):
        screen = screen_of(flags)
        return (*self.build(self.game, screen=screen, flags=flags, **options), screen)

    def test_sizes_as_nexload_reads_them(self) -> None:
        for flags, size in ((0, 0), (0x80, 0), (1, 49664), (0x81, 49152), (2, 6912), (4, 12800), (0x84, 12288), (8, 12288), (16, 12288),
                            (3, 49152 + 6912), (5, 49152 + 12288 + 512), (0x1F, nxc.SCREEN_MAX)):
            self.assertEqual(nxc.screen_size(flags), size, hex(flags))
        for flags in (0x20, 0x40, 0x60, 0xE0):
            with self.assertRaisesRegex(nxc.Wrong, "V1.3"):
                nxc.screen_size(flags)

    def test_every_type_rebuilds_byte_exact(self) -> None:
        for name, flags in self.TYPES.items():
            with self.subTest(name):
                patch, nex, screen = self.with_screen(flags)
                self.assertEqual(nex[512:512 + len(screen)], screen)
                self.assertEqual(nxc.apply(patch, game=self.game), nex)
                level = dict(nxc.blocks(patch)[1])[b"OPT1"][0]
                self.assertEqual(level, 2 if screen else 1)
                m, failed, message = self.go(patch)
                self.assertFalse(failed, message)
                self.assertEqual(m.clean(), [])
                self.assertEqual(bytes(m.written[NEX]), nex)
                self.assertEqual(sum(t == b"SCR1" for t, _ in nxc.blocks(patch)[1]), (len(screen) + 16383) // 16384)

    def test_with_a_set_and_a_trainer(self) -> None:
        patch, nex, screen = self.with_screen(0x01)
        self.assertEqual(nxc.colour_sets(patch), ["Painted"])
        m, failed, message = self.go(patch, keys=["1", "3", "enter"])
        self.assertFalse(failed, message)
        out = bytes(m.written[NEX])
        self.assertEqual(out, nxc.apply(patch, game=self.game, colours="Painted", chosen=[1]))
        self.assertEqual(out[512:512 + len(screen)], screen)
        self.assertEqual(m.peak_pages, 9)

    def test_a_tool_refuses_a_set_that_changes_the_screen(self) -> None:
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            tmp = Path(d)
            (tmp / "g.z80").write_bytes(self.game)
            _, nex, _ = self.with_screen(0x02)
            (tmp / "o.nex").write_bytes(nex)
            changed = bytearray(nex)
            changed[600] ^= 1
            (tmp / "p.nex").write_bytes(bytes(changed))
            with self.assertRaisesRegex(ValueError, "only change banks"):
                nxc.make(str(tmp / "g.z80"), str(tmp / "o.nex"), dict(file="g.z80"), dict(build="t"), colours={"X": str(tmp / "p.nex")})

    def test_a_v13_screen_is_refused_with_its_reason(self) -> None:
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            tmp = Path(d)
            (tmp / "g.z80").write_bytes(self.game)
            nex = bytearray(self.nex)
            nex[10] = 0x40
            (tmp / "o.nex").write_bytes(bytes(nex))
            with self.assertRaisesRegex(nxc.Wrong, "V1.3"):
                nxc.make(str(tmp / "g.z80"), str(tmp / "o.nex"), dict(file="g.z80"), dict(build="t"))
        def header(bl, st):
            for e in bl:
                if e[0] == b"NEX1":
                    e[1] = st.block(b"NEX1")(nxc.zx0(bytes(nex[:512])))
        self.refused_by_both(T.rekey(self.patch, self.game, header), LEVEL)

    def forge(self, patch: bytes, edit) -> bytes:
        return T.rekey(patch, self.game, edit)

    def test_damaged_screen_blocks(self) -> None:
        patch, nex, screen = self.with_screen(0x02)                 # one chunk
        two, nex2, screen2 = self.with_screen(0x01)                 # four
        scr = lambda st, k, plain: struct.pack("<BH", k, len(plain)) + st.block(b"SCR1", k)(nxc.zx0(plain))  # noqa: E731
        drop = lambda bl, st: bl.__setitem__(slice(None), [e for e in bl if e[0] != b"SCR1"])  # noqa: E731
        cases = {
            "none, the header lists one": (patch, drop),
            "one of four missing": (two, lambda bl, st: bl.pop(next(i for i, e in enumerate(bl) if e[0] == b"SCR1"))),
            "given twice": (patch, lambda bl, st: bl.append([b"SCR1", next(e[1] for e in bl if e[0] == b"SCR1")])),
            "index too high": (patch, lambda bl, st: bl.append([b"SCR1", scr(st, 1, b"x")])),
            "too short": (patch, lambda bl, st: bl.append([b"SCR1", b"\0\0"])),
            "no data promised, data given": (patch, lambda bl, st: [e.__setitem__(1, b"\0\0\0zz") for e in bl if e[0] == b"SCR1"]),
            "longer than its room": (patch, lambda bl, st: [e.__setitem__(1, scr(st, 0, b"y" * 6913)) for e in bl if e[0] == b"SCR1"]),
            "a stream longer than it says": (patch, lambda bl, st: [e.__setitem__(1, struct.pack("<BH", 0, 10) + st.block(b"SCR1", 0)(nxc.zx0(b"y" * 11))) for e in bl if e[0] == b"SCR1"]),
            "changed, with the CRC unmoved": (patch, lambda bl, st: [e.__setitem__(1, scr(st, 0, b"z" * 6912)) for e in bl if e[0] == b"SCR1"]),
        }
        for name, (base, edit) in cases.items():
            with self.subTest(name):
                forged = self.forge(base, edit)
                with self.assertRaises(nxc.Wrong):
                    nxc.apply(forged, game=self.game)
                m, failed, message = self.go(forged)
                self.assertTrue(failed, name)
                self.assertIn(message, (DAMAGED, "Rebuild failed: patch damaged"))
                self.assertNotIn(NEX, m.written)
                self.assertEqual(m.clean(), [])
                self.assertEqual(m.bad_writes, [])
        # A screen block with no screen listed.
        self.refused_by_both(self.forge(self.patch, lambda bl, st: bl.append([b"SCR1", scr(st, 0, b"x")])))

    def test_a_flipped_byte_never_reaches_a_decoder(self) -> None:
        patch, nex, screen = self.with_screen(0x02)
        at = find_block(patch, b"SCR1")
        for offset in (0, 1, 2, 3, 10, 50):
            bad = bytearray(patch)
            bad[at + offset] ^= 0x10
            m, failed, message = self.go(bytes(bad))
            self.assert_refused(m, failed, message, DAMAGED)
            self.assertNotIn("zx0_decode", m.phase_ticks)

    def test_an_older_loader_refuses_it_rather_than_writing_a_broken_file(self) -> None:
        patch, nex, screen = self.with_screen(0x02)
        old = [("LOADER_LEVEL    equ 2 ", "LOADER_LEVEL    equ 1 ")]
        m, failed, message = self.control(old, patch)
        self.assert_refused(m, failed, message, LEVEL)
        self.assertEqual(m.opened, ["patch.nxc"])
        # And a patch with a screen may not claim level 1: such a loader would skip the block.
        low = self.forge(patch, lambda bl, st: [e.__setitem__(1, b"\x01\0" + e[1][2:]) for e in bl if e[0] == b"OPT1"])
        self.refused_by_both(low)
        # Without the screen, a level 1 loader still plays what it can.
        m, failed, message = self.control(old, self.patch)
        self.assertFalse(failed, message)

    def test_a_loader_that_skipped_the_block_is_caught(self) -> None:
        patch, nex, screen = self.with_screen(0x02)
        m, failed, message = self.control([("""        call    write_out
        call    write_screen
""", """        call    write_out
""")], patch)
        self.assertEqual((failed, message), (True, "Rebuild failed: patch damaged"))
        self.assertNotIn(NEX, m.written)

    def test_measure_the_largest_screen(self) -> None:
        for name, flags in (("layer 2 and its palette", 0x01), ("every type at once", 0x1F)):
            patch, nex, screen = self.with_screen(flags)
            m = H.Machine(self.binary, self.symbols, {"patch.nxc": patch, "game.z80": self.game})
            m.set_phases(["write_screen", "done"])
            failed, message = m.run('"patch.nxc"')
            self.assertFalse(failed, message)
            self.assertEqual(bytes(m.written[NEX]), nex)
            low = next(a for a in range(self.symbols["stack_floor"], 0x4001) if a == 0x4000 or m.m.memory[a] != H.junk(a))
            print(f"\nMeasure, a screen of {name}, {len(screen)} bytes of noise, {sum(len(d) for t, d in nxc.blocks(patch)[1] if t == b'SCR1')} in the patch: "
                  f"from the screen to the end {m.phase_ticks['write_screen'] / 28e6:.3f} s at 28 MHz, no file I/O; pages {m.peak_pages}; stack {0x4000 - low} bytes", flush=True)
            self.assertEqual(m.peak_pages, 6)

    def test_the_spec_says_what_a_screen_holds(self) -> None:
        spec = (ROOT / "spec" / "NXC-FORMAT.md").read_text()
        self.assertIn("SCR1", spec)
        self.assertIn("art the player's own file does not contain", spec)


if __name__ == "__main__":
    unittest.main()

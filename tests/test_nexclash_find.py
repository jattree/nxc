"""Finding the game whatever its name (spec, "Applying a patch", step 3): after the names the patch gives and its own with
.z80, any file in the patch's folder with a listed length, accepted only if it is the dump. The loader (firmware/nexclash.asm,
on nexclash_harness.py, whose F_OPENDIR and F_READDIR give 8.3 names as FAT makes them) checks such a file against the patch
even with the clash fix off and no trainer; tools/nxc.py checks its MD5. Only the synthetic vectors are used."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import nexclash_harness as H
import test_nexclash_dot as T

nxc = T.nxc
VECTORS = Path(__file__).resolve().parent / "vectors"
PATCH = (VECTORS / "vector.nxc").read_bytes()
GAME = (VECTORS / "game_v3.z80").read_bytes()
OTHER = (VECTORS / "game_v1.z80").read_bytes()          # an accepted dump of another length
NEEDS = "game_v3.z80"                                      # the first target's name, as the refusals print it


def wrong_of(game: bytes) -> bytes:
    """A file of the game's length that is not the game."""
    bad = bytearray(game)
    bad[len(bad) // 2] ^= 1
    return bytes(bad)


class ShortNames(unittest.TestCase):
    def test_the_harness_names_as_fat_does(self) -> None:
        self.assertEqual(H.short_names(["GAME.Z80", "my copy of the game.z80", "my copy 2.z80", ".hidden", "a.b.c"]),
                         {"GAME.Z80": "GAME.Z80", "my copy of the game.z80": "MYCOPY~1.Z80", "my copy 2.z80": "MYCOPY~2.Z80",
                          ".hidden": "HIDDEN~1", "a.b.c": "AB~1.C"})


@T.needs_tools
class Loader(T.Base):
    def run_files(self, files: dict[str, bytes], keys=("enter",), argument='"patch.nxc"', **options):
        m = self.machine(files, keys=keys, **options)
        failed, message = m.run(argument)
        return m, failed, message

    def test_a_renamed_game_is_found_and_rebuilt(self) -> None:
        for name in ("my copy of the game.z80", "GAMECOPY.BIN", "x"):
            with self.subTest(name=name):
                m, failed, message = self.run_files({"patch.nxc": PATCH, "notes.txt": b"hello", name: GAME})
                self.assertFalse(failed, message)
                self.assertEqual(bytes(m.written[T.NEX]), nxc.apply(PATCH, game=GAME))
                self.assertEqual(m.clean(), [])
                self.assertGreater(m.dir_reads, 0)

    def test_in_a_folder_with_others(self) -> None:
        files = {"nxc/vec/patch.nxc": PATCH, "nxc/vec/readme.nfo": b"x" * 100, "nxc/vec/zz other game.z80": b"y" * 3000,
                 "nxc/vec/renamed.z80": GAME, "nxc/elsewhere.z80": GAME}
        m, failed, message = self.run_files(files, keys=("space",), argument='"nxc/vec/patch.nxc"', folders=("sub",))
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[T.NEX]), nxc.apply_menu(PATCH, GAME))
        self.assertIn("nxc/vec/renamed.z80", m.opened)
        self.assertEqual(m.clean(), [])

    def test_the_clash_fix_off_checks_it_too(self) -> None:
        m, failed, message = self.run_files({"patch.nxc": PATCH, "renamed.z80": GAME}, keys=("2", "enter"))
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[T.Z80]), GAME)          # the file itself, once it unlocked the patch
        self.assertEqual(m.integer_vars[23], 2)
        self.assertEqual(m.clean(), [])
        for keys in (("2", "enter"), ("enter",), ("1", "2", "enter")):
            with self.subTest(keys=keys):
                m, failed, message = self.run_files({"patch.nxc": PATCH, "renamed.z80": wrong_of(GAME)}, keys=keys)
                self.assert_refused(m, failed, message, "Wrong game file for this patch")
                self.assertIn("Needs this game file:", m.printed.decode("latin-1"))
                self.assertIn(NEEDS, m.printed.decode("latin-1"))

    def test_under_its_own_name_it_is_still_not_checked(self) -> None:
        m, failed, message = self.run_files({"patch.nxc": PATCH, NEEDS: wrong_of(GAME)}, keys=("2", "enter"))
        self.assertFalse(failed, message)                       # the player's own file, as before
        self.assertEqual(bytes(m.written[T.Z80]), wrong_of(GAME))
        self.assertEqual(m.dir_reads, 0)

    def test_a_listed_name_of_a_listed_length_comes_first(self) -> None:
        """A file under a listed name with a listed length is the one tried; the folder is not read, so a wrong one there
        is refused even with the right game beside it under another name."""
        m, failed, message = self.run_files({"patch.nxc": PATCH, NEEDS: wrong_of(GAME), "renamed.z80": GAME})
        self.assert_refused(m, failed, message, "Wrong game file for this patch")
        self.assertEqual(m.dir_reads, 0)
        m, failed, message = self.run_files({"patch.nxc": PATCH, NEEDS: b"short", "renamed.z80": GAME})
        self.assertFalse(failed, message)                       # one of no listed length is passed over
        self.assertEqual(bytes(m.written[T.NEX]), nxc.apply(PATCH, game=GAME))

    def test_the_first_in_the_folder_is_the_one(self) -> None:
        m, failed, message = self.run_files({"patch.nxc": PATCH, "a.z80": wrong_of(GAME), "b.z80": GAME})
        self.assert_refused(m, failed, message, "Wrong game file for this patch")
        m, failed, message = self.run_files({"patch.nxc": PATCH, "a.z80": OTHER, "b.z80": GAME})
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[T.NEX]), nxc.apply(PATCH, game=OTHER))

    def test_nothing_of_a_listed_length(self) -> None:
        m, failed, message = self.run_files({"patch.nxc": PATCH, "other.z80": b"z" * 999})
        self.assert_refused(m, failed, message, "Game not beside the patch")
        self.assertIn(NEEDS, m.printed.decode("latin-1"))

    def test_an_output_name_is_still_refused(self) -> None:
        m, failed, message = self.run_files({"/tmp/patch.nxc": PATCH, "/tmp/nexclash.z80": GAME}, argument='"/tmp/patch.nxc"')
        self.assert_refused(m, failed, message, "Input has the /tmp output's name")

    def test_a_patch_at_the_root(self) -> None:
        m, failed, message = self.run_files({"/patch.nxc": PATCH, "/renamed.z80": GAME}, argument='"/patch.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[T.NEX]), nxc.apply(PATCH, game=GAME))


@unittest.skipUnless(nxc is not None, "tools/nxc.py cannot be imported")
class Tool(unittest.TestCase):
    def folder(self, files: dict[str, bytes]) -> Path:
        d = Path(tempfile.mkdtemp(dir=os.environ.get("TMPDIR")))
        self.addCleanup(lambda: [p.unlink() for p in d.iterdir()] and d.rmdir())
        for name, data in files.items():
            (d / name).write_bytes(data)
        return d

    def test_by_md5_whatever_its_name(self) -> None:
        d = self.folder({"patch.nxc": PATCH, "my copy.z80": GAME, "junk.bin": b"q" * 10})
        path, game = nxc.find_game(str(d / "patch.nxc"))
        self.assertEqual((os.path.basename(path), game), ("my copy.z80", GAME))

    def test_any_matching_file_not_only_the_first(self) -> None:
        d = self.folder({"patch.nxc": PATCH, "a.z80": wrong_of(GAME), "b.z80": GAME})
        self.assertEqual(os.path.basename(nxc.find_game(str(d / "patch.nxc"))[0]), "b.z80")

    def test_the_loader_s_messages(self) -> None:
        for files, why in (({"x.z80": wrong_of(GAME)}, "Wrong game file for this patch"), ({"x.z80": b"1"}, "Game not beside the patch"),
                           ({NEEDS: wrong_of(GAME), "renamed.z80": GAME}, "Wrong game file for this patch")):
            with self.subTest(why=why):
                d = self.folder({"patch.nxc": PATCH, **files})
                with self.assertRaises(nxc.Wrong) as e:
                    nxc.find_game(str(d / "patch.nxc"))
                self.assertEqual(str(e.exception), "%s: needs this game file: %s" % (why, NEEDS))

    def test_the_command_line(self) -> None:
        d = self.folder({"patch.nxc": PATCH, "renamed.z80": GAME})
        out = d / "out.nex"
        nxc.run([str(d / "patch.nxc"), "-o", str(out), "--bare"])
        self.assertEqual(out.read_bytes(), nxc.apply(PATCH, game=GAME))


if __name__ == "__main__":
    unittest.main()

"""tools/nxc.py: its ZX0 decoder against the compressor, .pok import, TRN1. Needs NexClash's snapshot reader
(NEXCLASH_REPO), and for the games NXC_EVIDENCE or build/inputs; skips without them."""
from __future__ import annotations

import os
import random
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get("NXC_EVIDENCE", str(Path(__file__).resolve().parents[1] / "build" / "evidence")))
os.environ.setdefault("NEXCLASH_REPO", str(EVIDENCE / "format-study" / "nexclash-latest"))
os.environ.setdefault("NXC_ZX0_DIR", str(EVIDENCE / "format-study" / "zx0bin"))
sys.path.insert(0, str(ROOT / "tools"))
try:
    import nxc
except ImportError:
    nxc = None

ZX0 = Path(os.environ["NXC_ZX0_DIR"]) / "zx0"
GAME = next((p for p in (ROOT / "build/inputs/cobra.z80", EVIDENCE / "pilot/runs/cobra/cobra.z80") if p.exists()), None)
PATCH = next((p for p in (ROOT / "build/inputs/Cobra.nxc", EVIDENCE / "format-study/cobra/Cobra.nexclash") if p.exists()), None)


@unittest.skipUnless(nxc is not None, "NexClash's snapshot reader is missing: set NEXCLASH_REPO")
class Pok(unittest.TestCase):
    TEXT = "NInfinite Lives\nM 8 36515 183 0\nZ 8 34925 183 0\nNImmunity\nZ 8 37915 201 0\nNAsk\nZ 8 40000 256 0\nY\n"

    def test_parse(self) -> None:
        entries = nxc.parse_pok(self.TEXT)
        self.assertEqual([e[0] for e in entries], ["Infinite Lives", "Immunity", "Ask"])
        self.assertEqual(entries[0][1], [(8, 36515, 183, 0), (8, 34925, 183, 0)])

    def test_stops_at_y(self) -> None:
        self.assertEqual(len(nxc.parse_pok("NA\nZ 8 40000 1 0\nY\nthis is not parsed\n")), 1)

    def test_bad_lines(self) -> None:
        for text in ("Q 8 1 1 1\n", "Z 8 40000 1 0\n", "NA\nZ 8 40000\n"):
            with self.assertRaises(ValueError):
                nxc.parse_pok(text)

    def test_sentence_case(self) -> None:
        self.assertEqual(nxc.sentence_case("Infinite Lives"), "Infinite lives")
        self.assertEqual(nxc.sentence_case("Unlimited weaponry"), "Unlimited weaponry")
        self.assertEqual(nxc.sentence_case("Invisible To UDG Bombs"), "Invisible to UDG bombs")

    def test_bank_field(self) -> None:
        class Snap:
            is128 = False
            port7ffd = 0
        self.assertEqual(nxc.poke_bank(8, 0x4000, Snap), (5, 0))
        self.assertEqual(nxc.poke_bank(8, 36515, Snap), (2, 36515 - 32768))
        self.assertEqual(nxc.poke_bank(8, 0xC123, Snap), (0, 0x123))
        Snap.is128 = True
        Snap.port7ffd = 0x13
        self.assertEqual(nxc.poke_bank(8, 0xC123, Snap), (3, 0x123))
        self.assertEqual(nxc.poke_bank(6, 0xC123, Snap), (6, 0x123))
        self.assertEqual(nxc.poke_bank(6, 0x8000, Snap), (2, 0))
        with self.assertRaises(nxc.Wrong):
            nxc.poke_bank(8, 0x3FFF, Snap)
        with self.assertRaises(nxc.Wrong):
            nxc.poke_bank(9, 0xC000, Snap)

    def test_trn1_round_trip_and_limits(self) -> None:
        data = nxc.trn1("Lives", [(2, 100, 7), (5, 16383, 255)])
        self.assertEqual(nxc.parse_trn1(data), (0, "Lives", [(2, 100, 7), (5, 16383, 255)]))
        for bad in (data[:-1], data + b"x", b"\0\0\0", b"", bytes((0, 26)) + b"n" * 26 + b"\1" + bytes(4)):
            with self.assertRaises(nxc.Wrong):
                nxc.parse_trn1(bad)
        with self.assertRaises(ValueError):
            nxc.trn1("x" * 26, [(2, 0, 0)])
        with self.assertRaises(ValueError):
            nxc.trn1("x", [])


@unittest.skipUnless(nxc is not None, "NexClash's snapshot reader is missing: set NEXCLASH_REPO")
class HandoffBas(unittest.TestCase):
    def test_a_well_formed_plus3dos_program(self) -> None:
        d = nxc.handoff_bas()
        self.assertEqual(d[:8], b"PLUS3DOS")
        self.assertEqual(sum(d[:127]) & 255, d[127])
        self.assertEqual(struct.unpack_from("<I", d, 11)[0], len(d))
        self.assertEqual(d[15], 0)
        length, start, variables = struct.unpack_from("<HHH", d, 16)
        self.assertEqual((length, start, variables), (len(d) - 128, 0x8000, len(d) - 128))
        self.assertEqual(d[128:130], b"\0\0")                                       # line 0
        self.assertEqual(struct.unpack_from("<H", d, 130)[0], len(d) - 132)
        self.assertEqual(d[-1:], b"\r")
        self.assertIn(b".nexload nexclash.nex", d)


@unittest.skipUnless(nxc is not None and GAME and PATCH, "Cobra's game or patch is missing")
class CobraTool(unittest.TestCase):
    def setUp(self) -> None:
        self.patch = PATCH.read_bytes()
        self.game = GAME.read_bytes()

    def test_import_keeps_everything_else(self) -> None:
        out = nxc.import_pok(self.patch, str(GAME), Pok.TEXT, "Ocean, 1986")
        self.assertEqual(nxc.apply(out, game=self.game), nxc.apply(self.patch, game=self.game))
        self.assertEqual([t[1] for t in nxc.trainers(out)], ["Infinite lives", "Immunity"])
        self.assertEqual([t[0] for t in nxc.trainers(out)], [0, 0])
        self.assertIn(b"publisher=Ocean, 1986\n", dict(nxc.blocks(out)[1])[b"INF1"])
        again = nxc.import_pok(out, str(GAME), Pok.TEXT, "Ocean, 1986")
        self.assertEqual(again, out)

    def test_a_poke_on_a_patched_byte_is_refused(self) -> None:
        touched = nxc.patched_bytes(self.patch, self.game)
        bank, where = next((b, w) for b, w in touched.items() if w)
        address = {5: 0x4000, 2: 0x8000, 0: 0xC000}[bank] + min(where)
        with self.assertRaisesRegex(nxc.Wrong, "lands on a byte the patch changes"):
            nxc.import_pok(self.patch, str(GAME), f"NBad\nZ 8 {address} 1 0\nY\n")

    def test_only_imports_the_named_trainers_in_the_file_order(self) -> None:
        text = Pok.TEXT.replace("Y\n", "NThird One\nZ 8 40001 1 0\nY\n")
        out = nxc.import_pok(self.patch, str(GAME), text, only=["Infinite Lives"])
        self.assertEqual([t[1] for t in nxc.trainers(out)], ["Infinite lives"])
        # as the .pok spells it or as the menu does, and the file's order whatever the order asked
        out = nxc.import_pok(self.patch, str(GAME), text, only=["Third one", "Immunity"])
        self.assertEqual([t[1] for t in nxc.trainers(out)], ["Immunity", "Third one"])
        self.assertEqual(nxc.apply(out, game=self.game), nxc.apply(self.patch, game=self.game))

    def test_only_refuses_a_name_it_cannot_import(self) -> None:
        with self.assertRaisesRegex(nxc.Wrong, "no trainer called"):
            nxc.import_pok(self.patch, str(GAME), Pok.TEXT, only=["Immunity", "Nope"])
        with self.assertRaisesRegex(nxc.Wrong, "no trainer called"):
            nxc.import_pok(self.patch, str(GAME), Pok.TEXT, only=[""])
        with self.assertRaisesRegex(nxc.Wrong, "asks the player"):
            nxc.import_pok(self.patch, str(GAME), Pok.TEXT, only=["Ask"])

    def test_only_leaves_out_a_trainer_that_would_be_refused(self) -> None:
        touched = nxc.patched_bytes(self.patch, self.game)
        bank, where = next((b, w) for b, w in touched.items() if w)
        address = {5: 0x4000, 2: 0x8000, 0: 0xC000}[bank] + min(where)
        text = f"NBad\nZ 8 {address} 1 0\nNGood\nZ 8 37915 201 0\nY\n"
        with self.assertRaises(nxc.Wrong):
            nxc.import_pok(self.patch, str(GAME), text)
        out = nxc.import_pok(self.patch, str(GAME), text, only=["Good"])
        self.assertEqual([t[1] for t in nxc.trainers(out)], ["Good"])

    def test_only_on_the_command_line(self) -> None:
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
            pok = Path(d) / "t.pok"
            pok.write_text(Pok.TEXT)
            out = Path(d) / "o.nxc"
            base = [sys.executable, str(ROOT / "tools/nxc.py"), "import-pok", str(PATCH), str(pok), str(GAME), "-o", str(out)]
            r = subprocess.run(base + ["--only", "Immunity,Infinite Lives"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual([t[1] for t in nxc.trainers(out.read_bytes())], ["Infinite lives", "Immunity"])
            out.unlink()
            r = subprocess.run(base + ["--only", "Nope"], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("no trainer called", r.stderr)
            self.assertFalse(out.exists())

    def test_credit_names_go_first_and_change_nothing_else(self) -> None:
        out = nxc.set_credits(nxc.import_pok(self.patch, str(GAME), Pok.TEXT, "Ocean, 1986"), self.game, "Ann", "Bob")
        info = dict(nxc.blocks(out)[1])[b"INF1"]
        self.assertTrue(info.startswith(b"publisher=Ocean, 1986\npatch_by=Ann\ncolours_by=Bob\n"), info)
        self.assertEqual(nxc.apply(out, game=self.game), nxc.apply(self.patch, game=self.game))
        self.assertEqual(nxc.credit_line(out), "Patch: Ann")            # no colour set here
        again = nxc.set_credits(out, self.game, colours_by="")
        self.assertIsNone(nxc.inf1_value(again, "colours_by"))
        self.assertEqual(nxc.inf1_value(again, "patch_by"), b"Ann")
        self.assertIsNone(nxc.credit_line(nxc.set_credits(again, self.game, patch_by="")))
        self.assertEqual(nxc.check_key(again, self.game)[2:], nxc.check_key(out, self.game)[2:])

    def test_credit_names_refused(self) -> None:
        wrong = bytearray(self.game)
        wrong[9] ^= 1
        with self.assertRaises(nxc.Wrong):
            nxc.set_credits(self.patch, bytes(wrong), "Ann")
        for bad in ("two\nlines", "caf\u00e9"):
            with self.assertRaises(nxc.Wrong):
                nxc.set_credits(self.patch, self.game, bad)
        with self.assertRaisesRegex(nxc.Wrong, "first 252 bytes"):
            nxc.set_credits(nxc.import_pok(self.patch, str(GAME), Pok.TEXT, "P" * 250), self.game, "Ann")

    def test_credit_on_the_command_line(self) -> None:
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
            out = Path(d) / "o.nxc"
            r = subprocess.run([sys.executable, str(ROOT / "tools/nxc.py"), "credit", str(PATCH), str(GAME), "-o", str(out),
                                "--patch-by", "Ann"], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(nxc.credit_line(out.read_bytes()), "Patch: Ann")

    def test_a_poke_outside_ram_is_refused(self) -> None:
        with self.assertRaises(nxc.Wrong):
            nxc.import_pok(self.patch, str(GAME), "NBad\nZ 8 1000 1 0\nY\n")

    def test_the_wrong_game_is_refused(self) -> None:
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
            wrong = Path(d) / "wrong.z80"
            data = bytearray(self.game)
            data[500] ^= 1
            wrong.write_bytes(data)
            with self.assertRaises(nxc.Wrong):
                nxc.import_pok(self.patch, str(wrong), Pok.TEXT)

    def test_published_checksums_do_not_unlock_it(self) -> None:
        import hashlib
        for key in (hashlib.md5(self.game).digest(), hashlib.md5(self.game).hexdigest().encode(),
                    hashlib.sha1(self.game).digest(), hashlib.sha512(self.game).digest()):
            with self.assertRaises(nxc.Wrong):
                nxc.check_key(self.patch, key)


@unittest.skipUnless(nxc is not None and ZX0.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class Zx0(unittest.TestCase):
    def test_decoder_matches_the_compressor(self) -> None:
        rng = random.Random(1)
        cases = [bytes((1,)), bytes(100), b"abc" * 500, bytes(rng.randrange(256) for _ in range(3000))]
        for _ in range(40):
            cases.append(b"".join(bytes((rng.randrange(256),)) * rng.randrange(1, 60) if rng.random() < 0.5
                                  else bytes(rng.randrange(4) for _ in range(rng.randrange(1, 60)))
                                  for _ in range(rng.randrange(1, 400))))
        for data in cases:
            self.assertEqual(nxc.unzx0(nxc.zx0(data), len(data)), data)

    def test_limits(self) -> None:
        stream = nxc.zx0(b"hello hello hello hello hello")
        with self.assertRaises(nxc.Wrong):
            nxc.unzx0(stream, 28)
        with self.assertRaises(nxc.Wrong):
            nxc.unzx0(stream[:-1], 29)
        with self.assertRaises(nxc.Wrong):
            nxc.unzx0(stream + b"\0", 29)
        with self.assertRaises(nxc.Wrong):
            nxc.unzx0(bytes((0xCA, 0x58, 0, 0, 0)), 1000)
        with self.assertRaises(nxc.Wrong):
            nxc.unzx0(bytes(40), 1000)


if __name__ == "__main__":
    unittest.main()

"""INF1's notes for the .nfo (notes, enhanced_N, changes, tested), PRF1's pace, the generic setter `nxc.py set`, and
tools/make_nfo.py (spec, "INF1" and "PRF1"). Only the synthetic vectors, and the published patches, which hold no game
code, are used: a published .nfo must be what make_nfo.py writes from its patch alone."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))
import make_nfo  # noqa: E402
import nxc  # noqa: E402

PATCH = (HERE / "vectors" / "vector.nxc").read_bytes()
GAME = (HERE / "vectors" / "game_v3.z80").read_bytes()


def inf1(f: bytes) -> list[str]:
    return dict(nxc.blocks(f)[1])[b"INF1"].decode().splitlines()


class Setter(unittest.TestCase):
    def test_notes_fields_change_no_build(self) -> None:
        f = PATCH
        for k, v in (("notes", "No outlines: the owner's choice."), ("enhanced", "Painted all over."), ("changes", "1.1: one | 1.2: two"),
                     ("tested", "Played by Ann in JNext, 2026-11-04"), ("credit", nxc.CREDIT + "; colours by Bob")):
            f = nxc.set_field(f, GAME, k, v)
        lines = inf1(f)
        self.assertIn("enhanced_1=Painted all over.", lines)
        self.assertEqual(nxc.text_fields(f, b"INF1")["changes"], "1.1: one | 1.2: two")
        self.assertEqual(nxc.change_entries("1.1: one | 1.2: two"), [("1.1", "one"), ("1.2", "two")])
        self.assertEqual(f[:nxc.CHECK_AT], PATCH[:nxc.CHECK_AT])                 # the same nonce
        for kw in ({}, dict(colours="Painted"), dict(chosen=["1"])):
            self.assertEqual(nxc.apply(f, game=GAME, **kw), nxc.apply(PATCH, game=GAME, **kw))
        self.assertEqual(nxc.apply_menu(f, GAME), nxc.apply_menu(PATCH, GAME))
        self.assertEqual(nxc.menu_description(f), nxc.menu_description(PATCH))
        self.assertEqual(lines[:2], ["publisher=Nobody, 2026", "patch_by=Vector"])     # the menu's lines first
        removed = nxc.set_field(f, GAME, "notes", "")
        self.assertNotIn("notes", nxc.text_fields(removed, b"INF1"))

    def test_menu_keys_go_among_the_menu_lines(self) -> None:
        f = nxc.set_field(PATCH, GAME, "version", "1.0")
        f = nxc.set_field(f, GAME, "colours_by", "Bob")
        f = nxc.set_field(f, GAME, "fix_label", "Colour")
        self.assertEqual(inf1(f)[:5], ["publisher=Nobody, 2026", "patch_by=Vector", "colours_by=Bob", "fix_label=Colour", "version=1.0"])
        self.assertEqual(nxc.credit_line(f), "Colours: Bob\nPatch: Vector               v1.0")
        self.assertEqual(nxc.fix_label(f), "Colour")
        self.assertEqual(f, nxc.set_version(nxc.set_credits(nxc.set_field(PATCH, GAME, "fix_label", "Colour"), GAME, colours_by="Bob"), GAME, "1.0"))

    def test_refusals(self) -> None:
        for k, v in (("nonsense", "x"), ("credit", ""), ("version", "v1"), ("fix_label", "x" * 26), ("enhanced_9", "x"),
                     ("notes", "x" * 1025), ("notes", "two\nlines"), ("notes", "café"), ("changes", "no version here"),
                     ("changes", "v1: bad version"), ("pace", "FAST"), ("pace_measured", "room 2 0.9%"), ("nex_md5", "ABC"),
                     ("publisher", "x" * 260), ("game_language", "English")):
            with self.subTest(k=k, v=v[:20]):
                with self.assertRaises(nxc.Wrong):
                    nxc.set_field(PATCH, GAME, k, v)
        with self.assertRaises(nxc.Wrong):
            nxc.set_field(PATCH, b"not the game", "notes", "x")

    def test_pace(self) -> None:
        f = nxc.set_field(PATCH, GAME, "pace", "ORIGINAL")
        f = nxc.set_field(f, GAME, "pace_measured", "the walk: +0.15%; room 2: -0.3%")
        self.assertEqual(make_nfo.pace_line(nxc.text_fields(f, b"PRF1")), "original (+0.15% measured)")   # where is optional
        self.assertEqual(make_nfo.pace_line({"pace": "TURBO"}), "turbo")
        f = nxc.set_field(f, GAME, "pace_where", "JNext 1.1.104")
        prf = nxc.text_fields(f, b"PRF1")
        self.assertEqual(nxc.pace_entries(prf["pace_measured"]), [("the walk", "+0.15%"), ("room 2", "-0.3%")])
        self.assertEqual(make_nfo.pace_line(prf), "original (+0.15% measured in JNext 1.1.104)")
        self.assertEqual(make_nfo.pace_line({"pace": "WARP"}), "")
        self.assertEqual(make_nfo.pace_line({}), "")
        self.assertIn("  Pace        original (+0.15% measured in JNext 1.1.104)", make_nfo.nfo(f, "x").splitlines())
        self.assertNotIn("Pace", make_nfo.nfo(PATCH, "x"))
        self.assertEqual(nxc.apply(f, game=GAME), nxc.apply(PATCH, game=GAME))

    def test_the_command_line(self) -> None:
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
            (Path(d) / "p.nxc").write_bytes(PATCH)
            (Path(d) / "g.z80").write_bytes(GAME)
            nxc.run(["set", str(Path(d) / "p.nxc"), str(Path(d) / "g.z80"), "tested", "Played by Ann, 2026-11-04", "-o", str(Path(d) / "q.nxc")])
            q = (Path(d) / "q.nxc").read_bytes()
            self.assertEqual(nxc.text_fields(q, b"INF1")["tested"], "Played by Ann, 2026-11-04")
            make_nfo.main([str(Path(d) / "q.nxc")])
            text = (Path(d) / "q.nfo").read_text(newline="")
            self.assertIn("  Tested      Played by Ann, 2026-11-04\r\n", text)
            self.assertTrue(all(len(line) <= 78 and line.isascii() for line in text.split("\r\n")))


class Published(unittest.TestCase):
    def test_each_nfo_is_made_from_its_patch_alone(self) -> None:
        patches = sorted((ROOT / "patches").glob("*/*.nxc"))
        listed = [l for l in (ROOT / "patches" / "manifest.tsv").read_text().splitlines()[1:] if l.strip()]
        self.assertEqual(len(patches), len(listed))   # every patch is in the manifest, and no more
        for p in patches:
            with self.subTest(p.name):
                self.assertEqual(make_nfo.nfo(p.read_bytes(), p.stem), p.with_suffix(".nfo").read_text(newline="", encoding="ascii"))
                inf = nxc.text_fields(p.read_bytes(), b"INF1")
                self.assertTrue(inf.get("tested"))
                for e in nxc.offered(p.read_bytes(), nxc.KIND_COLOURS):
                    self.assertTrue(inf.get("enhanced_%d" % e["choice"]), "every colour set says how it looks")


if __name__ == "__main__":
    unittest.main()

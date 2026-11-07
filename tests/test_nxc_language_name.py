"""INF1's game_language_name: the menu's Language line names the game's own language with no language set chosen, and
the chosen set's name with one, with one set as with several, never [ ON] or [OFF] (spec, "INF1" and "The menu").
Through tools/nxc.py (writer, reader, description, stub) and on the Z80 harness, in a .nex that carries its menu and in
the .NEXCLASH dot command. A patch without it, and a reader from before it (main at 8bf89f6), keep what they had, and
every build of a patch with it is the same file, byte for byte, as without it."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import nex_harness as N
import tape_game as G
import test_nexclash_dot as T
import test_nxc_tape as TT
import test_nxc_toggle as TG

nxc = T.nxc
H = T.H
ROOT = T.ROOT
V = ROOT / "tests" / "vectors"
TMP = os.environ.get("TMPDIR")
PATCH = (V / "vector.nxc").read_bytes()
GAME = (V / "game_v3.z80").read_bytes()
NEX = T.NEX
BEFORE = "8bf89f6"          # main before the key


def named(name="Spanish", patch=PATCH, game=GAME):
    return nxc.set_field(patch, game, "game_language_name", name)


def old_reader():
    """tools/nxc.py as it was before game_language_name, imported on its own, with the stubs it knew."""
    src = subprocess.run(["git", "-C", str(ROOT), "show", BEFORE + ":tools/nxc.py"], check=True, capture_output=True).stdout
    with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False, dir=TMP) as g:
        g.write(src)
        path = g.name
    spec = importlib.util.spec_from_file_location("nxc_before_language_name", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.STUB = nxc.STUB; m.STUB_RULES = nxc.STUB_RULES
    os.unlink(path)
    return m


CHOICES = ({}, dict(language="Vector"), dict(colours="Painted"), dict(chosen=["1"]),
           dict(colours="Painted", language="Vector", chosen=["1"]))


class Writer(unittest.TestCase):
    def test_set_and_read(self):
        f = named()
        self.assertEqual(nxc.game_language_name(f), "Spanish")
        self.assertEqual(nxc.game_language_name(PATCH), "")
        inf = dict(nxc.blocks(f)[1])[b"INF1"]
        self.assertTrue(inf.startswith(b"publisher=Nobody, 2026\npatch_by=Vector\ngame_language_name=Spanish\n"), inf)
        self.assertEqual(nxc.set_field(f, GAME, "game_language_name", ""), PATCH)     # removed: the patch it was

    def test_refusals(self):
        for bad in ("Thirteen char", "Español", "Tab\there"):
            with self.subTest(bad=bad), self.assertRaises(nxc.Wrong):
                named(bad)
        self.assertEqual(nxc.game_language_name(named("Twelve chars")), "Twelve chars")

    def test_the_description(self):
        d0, data0 = nxc.menu_description(PATCH)
        self.assertEqual(d0[0] & nxc.DESC_LANG, 0)
        d, data = nxc.menu_description(named())
        self.assertEqual(d[0], d0[0] | nxc.DESC_LANG)
        self.assertEqual(data, data0)
        self.assertIn(b"Enhanced colours\0\0Painted\0\0", d)          # colours: an empty name, so [OFF] stays
        self.assertIn(b"Language\0\0Vector\0Spanish\0", d)
        self.assertEqual(len(d), len(d0) + 1 + len(b"Spanish\0"))

    def test_without_a_language_line(self):
        f = (V / "vector_toggle.nxc").read_bytes()
        tape = (V / "tape.tap").read_bytes()
        g = nxc.set_field(f, tape, "game_language_name", "Spanish")
        self.assertEqual(nxc.menu_description(g), nxc.menu_description(f))
        self.assertEqual(nxc.apply_menu(g, tape), nxc.apply_menu(f, tape))

    def test_the_stub(self):
        self.assertNotEqual(nxc.stub_binary(lang=True), nxc.stub_binary(rules=True))
        menu = nxc.apply_menu(named(), GAME)
        bare = nxc.apply(named(), game=GAME)
        stub = nxc.stub_binary(lang=True)
        self.assertEqual(menu[len(bare):len(bare) + len(stub) - 8], stub[:-8])

    def test_every_build_is_the_same(self):
        f = named()
        for kw in CHOICES:
            with self.subTest(**{k: str(v) for k, v in kw.items()}):
                self.assertEqual(nxc.apply(f, game=GAME, **kw), nxc.apply(PATCH, game=GAME, **kw))
                a, b = nxc.apply_menu(f, GAME, **kw), nxc.apply_menu(PATCH, GAME, **kw)
                self.assertEqual(len(a), len(b))
                bare = len(nxc.apply(PATCH, game=GAME))
                self.assertEqual(a[:bare], b[:bare])                         # the game, and its header: the same
                self.assertEqual(a[bare + 16384:], b[bare + 16384:])         # the data: the same; only M0 differs

    def test_a_reader_from_before(self):
        old = old_reader()
        f = named()
        self.assertEqual(old.menu_description(f), old.menu_description(PATCH))
        for kw in CHOICES:
            with self.subTest(**{k: str(v) for k, v in kw.items()}):
                self.assertEqual(old.apply(f, game=GAME, **kw), nxc.apply(f, game=GAME, **kw))
                self.assertEqual(old.apply_menu(f, GAME, **kw), old.apply_menu(PATCH, GAME, **kw))
                self.assertEqual(old.apply_menu(PATCH, GAME, **kw), nxc.apply_menu(PATCH, GAME, **kw))   # unchanged without it


@TT.needs
class Make(unittest.TestCase):
    def build(self, languages, info):
        blocks = G.data_blocks()
        start = G.start_banks(blocks)
        nex, extra = G.build(start, blocks, nxc.ORDER)
        with tempfile.TemporaryDirectory(dir=TMP) as d:
            tmp = Path(d)
            for name, data in (("game.tap", G.tap(blocks)), ("start.z80", G.start_z80(start)), ("o.nex", nex)):
                (tmp / name).write_bytes(data)
            lang = {}
            for i, (n, ch) in enumerate(languages.items()):
                (tmp / f"l{i}.nex").write_bytes(TG.variant(nex, ch)); lang[n] = str(tmp / f"l{i}.nex")
            patch, _ = nxc.make(str(tmp / "game.tap"), str(tmp / "o.nex"), dict(title="Tape Game", file="game.tap"),
                                {**dict(build="t", publisher="Nobody, 2026", version="1.0"), **info}, start=str(tmp / "start.z80"),
                                tape_banks=extra, languages=lang)
        return patch, G.tap(blocks)

    def test_make_and_its_limits(self):
        f, tap = self.build({"English": [(0x2100, 0x11)], "Deutsch": [(0x2100, 0x22)]}, dict(game_language_name="Espanol"))
        inf = dict(nxc.blocks(f)[1])[b"INF1"]
        self.assertTrue(inf.startswith(b"publisher=Nobody, 2026\nversion=1.0\ngame_language_name=Espanol\n"), inf)
        self.assertEqual(nxc.game_language_name(f), "Espanol")
        with self.assertRaises(nxc.Wrong):
            self.build({"English": [(0x2100, 0x11)]}, dict(game_language_name="A language too long"))
        with self.assertRaises(nxc.Wrong):
            self.build({"English": [(0x2100, 0x11)]}, dict(game_language_name="Spanish", publisher="x" * 240))


@T.needs_tools
class TheMenu(T.Base):
    """The Language line's value, and its colour, as the menu .nex and the dot command draw it, after each key."""

    def nex_screens(self, f, keys):
        m = N.NexMachine(nxc.apply_menu(f, GAME), {}, keys=tuple(keys) + ("enter",))
        m.final_entry = nxc.apply(f, game=GAME)[139]
        attrs = []
        real = m.keyboard
        def spy(row):
            if m.key_state == "gap" and m.key_count == 6000:
                attrs.append(m.attrs())
            return real(row)
        m.keyboard = spy
        m.run_to(0xC000)
        return m.screens, attrs

    def test_the_menu_nex(self):
        screens, attrs = self.nex_screens(named(), ("4", "4", "2"))
        rows = [s.splitlines()[9] for s in screens]
        self.assertEqual(rows[:3], ["4 Language             [Spanish]", "4 Language              [Vector]", "4 Language             [Spanish]"])
        self.assertEqual(screens[0].splitlines()[8], "3 Enhanced colours         [OFF]")   # colours: as before
        self.assertEqual(attrs[0][9][24:31], bytes((0x42,) * 7))                   # the game's own: OFF's red
        self.assertEqual(attrs[1][9][25:31], bytes((0x44,) * 6))                   # a set's name: green
        self.assertEqual((attrs[0][9][23], attrs[0][9][31]), (0x47, 0x47))         # the brackets: white

    def test_one_set_without_the_key(self):
        screens, _ = self.nex_screens(PATCH, ("4",))
        self.assertEqual([s.splitlines()[9] for s in screens[:2]], ["4 Language                 [OFF]", "4 Language                 [ ON]"])

    def test_the_same_start(self):
        f = named()
        for keys, kw in (((), {}), (("4",), dict(language="Vector")), (("3", "4", "1"), dict(colours="Painted", language="Vector", chosen=["1"]))):
            with self.subTest(keys=keys):
                bare = nxc.apply(f, game=GAME, **kw)
                a, _ = N.start_state(bare, {})
                b, _ = N.start_state(nxc.apply_menu(f, GAME), {}, keys=tuple(keys) + ("enter",), bare_header=bare[:512])
                self.assertEqual((a["regs"], a["mmu"], a["banks"]), (b["regs"], b["mmu"], b["banks"]))

    def run_dot(self, f, keys):
        m = self.machine({"patch.nxc": f, "game_v3.z80": GAME}, keys=keys)
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(m.clean(), [])
        return m

    def test_the_dot_command(self):
        f = named()
        m = self.run_dot(f, ("4", "4", "space"))
        rows = [s.splitlines()[9] for s in m.screens[1:4]]
        self.assertEqual(rows, ["4 Language             [Spanish]", "4 Language              [Vector]", "4 Language             [Spanish]"])
        self.assertEqual(m.menu_attrs[0][9][24:31], bytes((0x42,) * 7))
        self.assertEqual(m.menu_attrs[1][9][25:31], bytes((0x44,) * 6))
        self.assertEqual(bytes(m.written[NEX]), nxc.apply_menu(f, GAME))
        m = self.run_dot(f, ("4", "space"))
        self.assertEqual(bytes(m.written[NEX]), nxc.apply_menu(f, GAME, language="Vector"))
        m = self.run_dot(f, ("3", "4", "1", "enter"))
        self.assertEqual(bytes(m.written[NEX]), nxc.apply(PATCH, game=GAME, colours="Painted", language="Vector", chosen=["1"]))
        nexm, _ = self.nex_screens(f, ("4",))
        dot = self.run_dot(f, ("4", "space"))
        self.assertEqual(dot.screens[1:3], nexm[:2])

    def test_the_dot_command_without_the_key(self):
        m = self.run_dot(PATCH, ("4", "space"))
        self.assertEqual([s.splitlines()[9] for s in m.screens[1:3]], ["4 Language                 [OFF]", "4 Language                 [ ON]"])
        self.assertEqual(bytes(m.written[NEX]), nxc.apply_menu(PATCH, GAME, language="Vector"))


if __name__ == "__main__":
    unittest.main()

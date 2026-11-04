"""A .nex that carries its menu (spec, "A .nex that carries its menu"): tools/nxc.py writes it, firmware/nxcstub.asm with
firmware/menu.asm runs it, on a Z80 emulator with the Next's paging (nex_harness.py).

The rule tested throughout: with choices X made on its menu, the game starts in exactly the state the bare .nex for X
starts in, every listed bank, every register but R, IFF, I, the MMU and the stack. Also the menu's look (text and
colours), its keys and rules, help text, the refusals, the command line, and that the stub in the repository is what its
source assembles to. Real patches are tried when NXC_MENU_GAMES names a JSON file of {patch: [[game files]]}.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VECTORS = HERE / "vectors"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
import nex_harness as N  # noqa: E402
import nxc  # noqa: E402

REGS = dict(af=0x1234, bc=0x5678, de=0x9ABC, hl=0xDEF0, ix=0x1111, iy=0x2222, alt_af=0x3333, alt_bc=0x4444,
            alt_de=0x5555, alt_hl=0x6666, i=0x3F)
PATCH = (VECTORS / "vector.nxc").read_bytes()
GAME = (VECTORS / "game_v3.z80").read_bytes()


def same_start(test, f, game, keys, iff=False, **kw):
    bare = nxc.apply(f, game=game, **kw)
    menu = nxc.apply_menu(f, game)
    a, _ = N.start_state(bare, REGS, iff=iff)
    b, machine = N.start_state(menu, REGS, keys=tuple(keys) + ("enter",), iff=iff, bare_header=bare[:512])
    test.assertEqual(a["regs"], b["regs"])
    test.assertEqual(a["mmu"], b["mmu"])
    for bank in a["banks"]:
        test.assertEqual(a["banks"][bank], b["banks"][bank], f"bank {bank}")
    return machine


@unittest.skipUnless(N.z80 is not None, "the z80 package is not installed (pip install z80)")
class SameStart(unittest.TestCase):
    def test_every_choice_on_the_vector(self):
        for keys, kw in (((), {}), (("1",), dict(chosen=["1"])), (("3",), dict(colours="Painted")),
                         (("4",), dict(language="Vector")), (("3", "4", "1"), dict(colours="Painted", language="Vector", chosen=["1"])),
                         (("1", "1"), {}), (("3", "3"), {})):
            for iff in (False, True):
                with self.subTest(keys=keys, iff=iff):
                    same_start(self, PATCH, GAME, keys, iff=iff, **kw)

    def test_a_control_differs(self):
        bare = nxc.apply(PATCH, game=GAME)
        a, _ = N.start_state(bare, REGS)
        b, _ = N.start_state(nxc.apply_menu(PATCH, GAME), REGS, keys=("1", "enter"), bare_header=bare[:512])
        self.assertNotEqual(a["banks"], b["banks"])
        c, _ = N.start_state(bare, dict(REGS, bc=1))
        self.assertNotEqual(a["regs"], c["regs"])

    def test_a_tape_patch_and_a_toggle(self):
        tape = (VECTORS / "tape.tap").read_bytes()
        for name, keys, kw in (("vector_tape.nxc", ("1",), dict(chosen=["1"])), ("vector_toggle.nxc", ("2",), dict(toggles=["Smooth scrolling"])),
                               ("vector_label.nxc", (), {})):
            with self.subTest(name=name):
                same_start(self, (VECTORS / name).read_bytes(), tape, keys, **kw)

    def test_a_set_of_tapes(self):
        game = nxc.FileSet([(VECTORS / "tapeset_a.tap").read_bytes(), (VECTORS / "tapeset_b.tzx").read_bytes()], [nxc.KIND_TAP, nxc.KIND_TZX])
        same_start(self, (VECTORS / "vector_tapeset.nxc").read_bytes(), game, ())

    def test_break_resets(self):
        m = N.NexMachine(nxc.apply_menu(PATCH, GAME), REGS, keys=("caps+space",))
        m.final_entry = 0
        with self.assertRaises(N.Reset):
            m.run_to(0xC000)


@unittest.skipUnless(N.z80 is not None, "the z80 package is not installed (pip install z80)")
class TheMenu(unittest.TestCase):
    def screens(self, f, game, keys):
        m = N.NexMachine(nxc.apply_menu(f, game), REGS, keys=tuple(keys) + ("enter",))
        m.final_entry = nxc.apply(f, game=game)[139]
        m.run_to(0xC000)
        return m

    def test_the_look(self):
        m = N.NexMachine(nxc.apply_menu(PATCH, GAME), REGS, keys=("enter",))
        m.final_entry = 0
        attrs = []
        real = m.keyboard
        def spy(row):          # the screen as the first key comes
            if not attrs and m.key_state == "gap" and m.key_count == 6000:
                attrs.append(m.attrs())
            return real(row)
        m.keyboard = spy
        m.run_to(0xC000)
        text = m.screens[0].splitlines()
        self.assertEqual(text[0], " VECTOR                     ////")
        self.assertEqual(text[1], " Nobody, 2026")
        self.assertEqual(text[3], "TRAINER")
        self.assertEqual(text[4], "1 Lives                    [OFF]")
        self.assertEqual(text[6], "OPTIONS")
        self.assertEqual(text[7], "2 Colour clash fix         [ ON]")
        self.assertEqual(text[8], "3 Enhanced colours         [OFF]")
        self.assertEqual(text[9], "4 Language                 [OFF]")
        self.assertEqual(text[11], "ENTER play   BREAK exit")
        self.assertEqual(text[22], "Patch: Vector")
        self.assertEqual(text[23], " Engine: Dean Woodyatt      ////")
        self.assertNotIn("nexclash", m.screens[0].lower())
        a = attrs[0]
        self.assertEqual(set(a[0][:28]) | set(a[23][:28]), {0x4E})
        self.assertEqual(bytes(a[0][28:]), bytes((0x4A, 0x56, 0x74, 0x65)))
        self.assertEqual(set(a[4]), {0x69})                 # line 1, selected
        self.assertEqual(a[3][0], 0x46)
        self.assertEqual(a[8][28:31], bytes((0x42,) * 3))   # OFF in red
        self.assertEqual(a[7][29:31], bytes((0x44,) * 2))   # ON in green
        self.assertEqual(a[11][:10], bytes((0x44,) * 10))
        self.assertEqual(a[11][13:23], bytes((0x42,) * 10))
        self.assertEqual(a[1], bytes((0x47,) * 32))         # the publisher, in white
        self.assertEqual(a[2], bytes((0x47,) * 32))

    def test_keys_and_rules(self):
        m = self.screens(PATCH, GAME, ("caps+6", "caps+6", "caps+7", "3", "3", "2", "4", "1"))
        s = [x.splitlines() for x in m.screens]
        # m.screens[k]: the screen as key k is pressed, so after the keys before it
        self.assertTrue(s[1][4].endswith("[OFF]"))
        self.assertEqual(s[4][8], "3 Enhanced colours         [ ON]")     # one set: ON
        self.assertEqual(s[5][8], "3 Enhanced colours         [OFF]")     # and back
        self.assertEqual(s[6][7], "2 Colour clash fix         [ ON]")     # fixed on in a .nex
        self.assertEqual(s[7][9], "4 Language                 [ ON]")
        self.assertEqual(s[8][4], "1 Lives                    [ ON]")
        self.assertEqual(m.screens[-1].splitlines()[4], "1 Lives                    [ ON]")

    def test_the_limit(self):
        menu = bytearray(nxc.apply_menu(PATCH, GAME))
        at = len(nxc.apply(PATCH, game=GAME)) + len(nxc.stub_binary()) + 1     # the description's N, in M0
        menu[at] = 1
        m = N.NexMachine(bytes(menu), REGS, keys=("3", "4", "enter"))
        m.final_entry = 0
        m.run_to(0xC000)
        self.assertEqual(m.screens[-1].splitlines()[9], "4 Language                 [OFF]")

    def test_help(self):
        f = nxc.set_help(PATCH, GAME, {"trainer_1": "Lives stay at three, whatever happens to you.", "fix": "The sprite build."})
        self.assertEqual(nxc.help_texts(f)["trainer_1"], "Lives stay at three, whatever   happens to you.")
        m = self.screens(f, GAME, ("caps+6",))
        s0, s1 = m.screens[0].splitlines(), m.screens[1].splitlines()
        self.assertEqual(s0[13:16], ["Lives:", "Lives stay at three, whatever", "happens to you."])
        self.assertEqual(s1[13:15], ["Colour clash fix:", "The sprite build."])
        same_start(self, f, GAME, ("1",), chosen=["1"])
        for bad in ({"trainer_2": "x"}, {"toggle_1": "x"}, {"fix": "x" * 65}, {"fix": "two\nlines"}):
            with self.assertRaises(nxc.Wrong):
                nxc.set_help(PATCH, GAME, bad)
        self.assertEqual(nxc.help_texts(nxc.set_help(f, GAME, {"fix": ""})), {"trainer_1": "Lives stay at three, whatever   happens to you."})


@unittest.skipUnless(N.z80 is not None, "the z80 package is not installed (pip install z80)")
class Presets(unittest.TestCase):
    def test_choices_are_where_the_menu_starts(self):
        menu = nxc.apply_menu(PATCH, GAME, chosen=["1"], language="Vector")
        bare = nxc.apply(PATCH, game=GAME, chosen=["1"], language="Vector")
        a, _ = N.start_state(bare, REGS)
        b, m = N.start_state(menu, REGS, keys=("enter",), bare_header=bare[:512])
        self.assertEqual(a, b)
        text = m.screens[0].splitlines()
        self.assertEqual((text[4], text[9]), ("1 Lives                    [ ON]", "4 Language                 [ ON]"))
        b, _ = N.start_state(menu, REGS, keys=("1", "4", "enter"), bare_header=nxc.apply(PATCH, game=GAME)[:512])
        self.assertEqual(N.start_state(nxc.apply(PATCH, game=GAME), REGS)[0], b)
        for bad in (dict(chosen=["9"]), dict(colours="Blue"), dict(toggles=["x"])):
            with self.assertRaises(nxc.Wrong):
                nxc.apply_menu(PATCH, GAME, **bad)

    def test_a_long_title(self):
        for title, rows in (("A TITLE OF TWENTY-SEVEN CHS", 1), ("THE TITLE THAT GOES ON AND ON PAST ONE ROW", 2)):
            rows = [None] * rows
            m = N.NexMachine(nxc.apply_menu(retitle(PATCH, title), GAME), REGS, keys=("enter",))
            m.run_to(0xC000)
            text = m.screens[0].splitlines()
            self.assertTrue(all(t.endswith("////") for t in text[:len(rows)]))
            joined = " ".join(t[1:28].strip() for t in text[:len(rows)])
            self.assertEqual(joined, title)
            self.assertEqual(text[len(rows)], " Nobody, 2026")
            self.assertEqual(text[len(rows) + (1 if len(rows) == 2 else 2)], "TRAINER")


def retitle(f, title):
    """The vector patch with its target's title changed, resealed."""
    st, bl = nxc.check_key(f, GAME)[:2]
    out = []
    for t, d in bl:
        if t == b"TGT1":
            d = d.replace(b"title=Vector", b"title=" + title.encode())
        out.append([t, d])
    return nxc.seal(f[:nxc.CHECK_AT], out, st)


class Writer(unittest.TestCase):
    def test_layout(self):
        bare = nxc.apply(PATCH, game=GAME)
        menu = nxc.apply_menu(PATCH, GAME)
        h, b = menu[:512], bare[:512]
        self.assertEqual(menu[512:len(bare)], bare[512:])          # the bare file's banks, then the menu banks
        self.assertEqual((h[139], h[14:16], h[9]), (11, b"\x00\xc0", b[9] + 2))
        self.assertEqual([x for x in range(112) if h[18 + x]], [x for x in range(112) if b[18 + x]] + [11, 12])
        diff = [i for i in range(512) if h[i] != b[i]]
        self.assertEqual(diff, [9, 18 + 11, 18 + 12, 139])          # its start is 0xC000 already
        stub = nxc.stub_binary()
        self.assertEqual(menu[len(bare):len(bare) + len(stub) - 8], stub[:-8])

    def test_refusals(self):
        real = nxc.apply
        for change, why in (((4, b"V1.1"), "V1.1"), ((140, b"\x01\x00"), "handle"), ((14, b"\x02\xc0"), "start address"),
                            ((14, b"\x00\x40"), "start address")):
            def patched(*a, change=change, **k):
                out = bytearray(real(*a, **k))
                out[change[0]:change[0] + len(change[1])] = change[1]
                return bytes(out)
            nxc.apply = patched
            try:
                with self.assertRaises(nxc.Wrong) as e:
                    nxc.apply_menu(PATCH, GAME)
                self.assertIn(why, str(e.exception))
                self.assertIn("--bare", str(e.exception))
            finally:
                nxc.apply = real

    def test_command_line(self):
        with tempfile.TemporaryDirectory() as d:
            g = Path(d) / "g.z80"
            g.write_bytes(GAME)
            def tool(*args):
                return subprocess.run([sys.executable, str(ROOT / "tools/nxc.py"), *args], capture_output=True, text=True)
            r = tool(str(VECTORS / "vector.nxc"), str(g), "-o", str(Path(d) / "m.nex"))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((Path(d) / "m.nex").read_bytes(), nxc.apply_menu(PATCH, GAME))
            r = tool(str(VECTORS / "vector.nxc"), str(g), "-o", str(Path(d) / "b.nex"), "--bare", "--trainer", "1")
            self.assertEqual((Path(d) / "b.nex").read_bytes(), nxc.apply(PATCH, game=GAME, chosen=["1"]))
            r = tool(str(VECTORS / "vector.nxc"), str(g), "-o", str(Path(d) / "x.nex"), "--trainer", "1", "--colours", "Painted")
            self.assertEqual((Path(d) / "x.nex").read_bytes(), nxc.apply_menu(PATCH, GAME, chosen=["1"], colours="Painted"))
            r = tool("help", str(VECTORS / "vector.nxc"), str(g), "-o", str(Path(d) / "h.nxc"), "--line", "fix=The sprite build.")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(nxc.help_texts((Path(d) / "h.nxc").read_bytes()), {"fix": "The sprite build."})

    @unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus is not installed")
    def test_the_stub_is_its_source(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "stub.bin"
            subprocess.run(["sjasmplus", "--nologo", f"--raw={out}", "nxcstub.asm"], cwd=ROOT / "firmware", check=True, capture_output=True)
            self.assertEqual(out.read_bytes(), nxc.stub_binary())


@unittest.skipUnless(N.z80 is not None and os.environ.get("NXC_MENU_GAMES"), "no real games listed: set NXC_MENU_GAMES")
class RealPatches(unittest.TestCase):
    def test_each(self):
        listed = json.loads(Path(os.environ["NXC_MENU_GAMES"]).read_text())
        for pf, targets in listed.items():
            files = targets[0]
            if not all(files) or not Path(pf).exists():
                continue
            game = Path(files[0]).read_bytes() if len(files) == 1 else nxc.FileSet([Path(x).read_bytes() for x in files], [nxc.kind_of_name(x) for x in files])
            f = Path(pf).read_bytes()
            lines = nxc.menu_lines(f)
            trainers = [str(i + 1) for i, line in enumerate(lines) if line[0] == 0]
            with self.subTest(patch=Path(pf).name):
                same_start(self, f, game, ())
                if trainers:
                    same_start(self, f, game, trainers, chosen=trainers)
                for i, (kind, name, _, payload) in enumerate(lines):
                    if kind == 2:
                        same_start(self, f, game, (str(i + 1),), **{"colours" if name == "Enhanced colours" else "language": payload[0]["name"].decode()})
                    if kind == 3:
                        same_start(self, f, game, (str((i + 1) % 10),), toggles=[name])


if __name__ == "__main__":
    unittest.main()

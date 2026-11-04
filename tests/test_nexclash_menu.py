"""The loader's new menu (firmware/menu.asm, read into a page of its own) and its default output, the .nex that carries
its menu: byte for byte what tools/nxc.py apply_menu writes for the same patch, game and choices, for a snapshot, a
tape, a set of tapes and a toggle; SPACE still writes the bare .nex; and the loader's menu looks exactly as the one in
the .nex does, text and colours. Real patches too where NXC_MENU_GAMES names a JSON file of {patch: [[game files]]}.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
import nex_harness as NH  # noqa: E402
import nexclash_harness as H  # noqa: E402
import nxc  # noqa: E402
import test_nexclash_dot as T  # noqa: E402

V = HERE / "vectors"
NEX = "$/tmp/nexclash.nex"
PATCH = (V / "vector.nxc").read_bytes()
GAME = (V / "game_v3.z80").read_bytes()


def files_of(game, names):
    if isinstance(game, nxc.FileSet):
        return dict(zip(names, game))
    return {names[0]: game}


@T.needs_tools
class LoaderMenuNex(T.Base):
    def run_menu(self, patch, game, names, keys):
        files = {"patch.nxc": patch, **files_of(game, names)}
        m = self.machine(files, keys=keys)
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(m.clean(), [])
        return m

    def test_snapshot_choices(self):
        for keys, kw in ((("space",), {}), (("1", "space"), dict(chosen=["1"])), (("3", "4", "space"), dict(colours="Painted", language="Vector")),
                         (("1", "3", "space"), dict(chosen=["1"], colours="Painted"))):
            with self.subTest(keys=keys):
                m = self.run_menu(PATCH, GAME, ["game_v3.z80"], keys)
                self.assertEqual(bytes(m.written[NEX]), nxc.apply_menu(PATCH, GAME, **kw))
                self.assertEqual(m.integer_vars.get(H.HANDOFF_VAR if hasattr(H, "HANDOFF_VAR") else 23, 1), 1)

    def test_enter_is_bare(self):
        m = self.run_menu(PATCH, GAME, ["game_v3.z80"], ("1", "3", "enter"))
        self.assertEqual(bytes(m.written[NEX]), nxc.apply(PATCH, game=GAME, chosen=["1"], colours="Painted"))

    def test_tapes_and_toggles(self):
        tape = (V / "tape.tap").read_bytes()
        tset = nxc.FileSet([(V / "tapeset_a.tap").read_bytes(), (V / "tapeset_b.tzx").read_bytes()], [nxc.KIND_TAP, nxc.KIND_TZX])
        for name, game, names, keys, kw in (("vector_tape.nxc", tape, ["tape.tap"], ("1", "space"), dict(chosen=["1"])),
                                            ("vector_toggle.nxc", tape, ["tape.tap"], ("2", "space"), dict(toggles=["Smooth scrolling"])),
                                            ("vector_label.nxc", tape, ["tape.tap"], ("space",), {}),
                                            ("vector_tapeset.nxc", tset, ["tapeset_a.tap", "tapeset_b.tzx"], ("space",), {})):
            with self.subTest(name=name):
                f = (V / name).read_bytes()
                m = self.run_menu(f, game, names, keys)
                self.assertEqual(bytes(m.written[NEX]), nxc.apply_menu(f, game, **kw))

    def test_help_and_the_same_screen(self):
        f = nxc.set_help(PATCH, GAME, {"trainer_1": "Lives stay at three, whatever happens to you.", "fix": "The sprite build."})
        m = self.run_menu(f, GAME, ["game_v3.z80"], ("2", "2", "space"))       # the fix off and on: its help
        self.assertEqual(bytes(m.written[NEX]), nxc.apply_menu(f, GAME))
        loader = m.screens[1:-1]
        nexm = NH.NexMachine(nxc.apply_menu(f, GAME), {}, keys=("2", "2", "enter"))   # fixed on in a .nex
        nexm.run_to(0xC000)
        self.assertEqual(loader[0], nexm.screens[0])
        self.assertEqual(loader[2], nexm.screens[2])
        self.assertIn("Lives stay at three, whatever", loader[0])
        self.assertIn("The sprite build.", loader[2])

    def test_the_same_colours(self):
        m = self.run_menu(PATCH, GAME, ["game_v3.z80"], ("space",))
        nexm = NH.NexMachine(nxc.apply_menu(PATCH, GAME), {}, keys=("enter",))
        attrs = []
        real = nexm.keyboard
        def spy(row):
            if not attrs and nexm.key_state == "gap" and nexm.key_count == 6000:
                attrs.append(nexm.attrs())
            return real(row)
        nexm.keyboard = spy
        nexm.run_to(0xC000)
        self.assertEqual(m.menu_attrs[-1], attrs[0])

    def test_without_the_rom_file(self):
        files = {"patch.nxc": PATCH, "game_v3.z80": GAME}
        m = self.machine(files, keys=("space",))
        m.files.pop(H.ROM_FILE)
        failed, message = m.run('"patch.nxc"')
        self.assertTrue(failed)
        self.assertEqual(message, "Needs NEXT/enNextZX.rom: no font")
        self.assertEqual(m.clean(), [])


@T.needs_tools
@unittest.skipUnless(os.environ.get("NXC_MENU_GAMES"), "no real games listed: set NXC_MENU_GAMES")
class RealLoaderMenuNex(T.Base):
    def test_each(self):
        listed = json.loads(Path(os.environ["NXC_MENU_GAMES"]).read_text())
        for pf, targets in listed.items():
            files = targets[0]
            if not all(files) or not Path(pf).exists() or "." in Path(pf).stem.replace("new_zealand_story", ""):
                continue
            game = Path(files[0]).read_bytes() if len(files) == 1 else nxc.FileSet([Path(x).read_bytes() for x in files], [nxc.kind_of_name(x) for x in files])
            f = Path(pf).read_bytes()
            names = [t for t in nxc.targets(f) if len(t["files"]) == len(files)][0]["files"]
            names = [n for n, _, _ in names]
            lines = nxc.menu_lines(f)
            keys, kw = ["1"], dict(chosen=["1"]) if lines[0][0] == 0 else ({},)
            if lines[0][0] != 0:
                keys, kw = [], {}
            for i, (kind, name, _, payload) in enumerate(lines):
                if kind == 3:
                    keys.append(str((i + 1) % 10)); kw.setdefault("toggles", []).append(name)
                    break
            with self.subTest(patch=Path(pf).name):
                m = self.machine({"patch.nxc": f, **files_of(game, names)}, keys=tuple(keys) + ("space",), free_pages=200)
                failed, message = m.run('"patch.nxc"', limit_seconds=600)
                self.assertFalse(failed, message)
                self.assertEqual(bytes(m.written[NEX]), nxc.apply_menu(f, game, **kw))
                print("loader menu .nex = nxc.py:", Path(pf).name, keys, flush=True)


if __name__ == "__main__":
    unittest.main()

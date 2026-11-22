"""INF1's build_screen (spec, "INF1"): at ENTER with the main line on, the loader (firmware/nexclash.asm, on
nexclash_harness.py) reads 6,912 bytes of the game file, from the offset given, straight to the display, before the game
is checked, with Patching on the last line and a dot for each bank made. Without the key nothing changes. Only the
synthetic vectors are used: their files hold no screen, so what shows is whatever lies at the offset."""
from __future__ import annotations

import unittest
from pathlib import Path

import nexclash_harness as H
import test_nexclash_dot as T

nxc = T.nxc
VECTORS = Path(__file__).resolve().parent / "vectors"
PATCH = (VECTORS / "vector_tape.nxc").read_bytes()
GAME = (VECTORS / "tape.tap").read_bytes()
NAME = "tape.tap"
SHORT_PATCH = (VECTORS / "vector.nxc").read_bytes()      # a game file shorter than a screen
SHORT_GAME = (VECTORS / "game_v3.z80").read_bytes()
OFFSET = 100
SCREEN = 6912
LAST_LINE = 23
SYSVARS = ["the caller's page 10 changed"]      # ATTR_P and BORDCR, so that BASIC's CLS clears to black


def rows(mem: bytes) -> list[str]:
    """A display file as text in the harness's font, '#' for a cell that is no glyph."""
    return ["".join(H.GLYPHS.get(bytes(mem[(r & 0x18) << 8 | (r & 7) << 5 | c | k << 8] for k in range(8)), "#")
                    for c in range(32)) for r in range(24)]


def text_cells(n: int) -> set[int]:
    """The display file's bytes that the first n cells of the last line own."""
    out = set()
    for c in range(n):
        out |= {(LAST_LINE & 0x18) << 8 | (LAST_LINE & 7) << 5 | c | k << 8 for k in range(8)} | {0x1800 + LAST_LINE * 32 + c}
    return out


@T.needs_tools
class BuildScreen(T.Base):
    def go(self, patch: bytes, game: bytes = GAME, keys=("enter",)):
        m = self.machine({"patch.nxc": patch, NAME: game}, keys=keys)
        shots = {}
        m.callbacks["unlock"] = lambda: shots.setdefault("unlock", bytes(m.m.memory[0x4000:0x5B00]))
        m.set_phases(T.PHASES + ["unlock"])
        m.guard_iopage()
        for address in (0x5C8D, 0x5C48):
            m.m.unmark_addr(address, m.m.WRITE_MARK)
        failed, message = m.run('"patch.nxc"')
        return m, failed, message, shots.get("unlock")

    def test_the_tool_sets_and_checks_it(self) -> None:
        f = nxc.set_field(PATCH, GAME, "build_screen", str(OFFSET))
        self.assertEqual(nxc.text_fields(f, b"INF1")["build_screen"], str(OFFSET))
        self.assertEqual(nxc.apply(f, game=GAME), nxc.apply(PATCH, game=GAME))
        self.assertNotIn("build_screen", nxc.text_fields(nxc.set_field(f, GAME, "build_screen", ""), b"INF1"))
        for bad in ("x", "-1", "65536", "1 ", "123456"):
            with self.subTest(bad=bad), self.assertRaises(nxc.Wrong):
                nxc.set_field(PATCH, GAME, "build_screen", bad)

    def test_the_screen_is_up_before_the_game_is_checked(self) -> None:
        f = nxc.set_field(PATCH, GAME, "build_screen", str(OFFSET))
        m, failed, message, at_unlock = self.go(f)
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[T.NEX]), nxc.apply(PATCH, game=GAME))
        want = GAME[OFFSET:OFFSET + SCREEN]
        self.assertTrue(rows(at_unlock)[LAST_LINE].startswith("Patching"))
        self.assertNotEqual(rows(at_unlock)[LAST_LINE][8], ".")
        self.assertLessEqual({i for i in range(SCREEN) if at_unlock[i] != want[i]}, text_cells(8))
        final = bytes(m.m.memory[0x4000:0x5B00])
        line = rows(final)[LAST_LINE]
        self.assertEqual(line, "Patching" + "." * 24)   # the 24 dots spread over the banks, the last at the edge
        self.assertLessEqual({i for i in range(SCREEN) if final[i] != want[i]}, text_cells(32))
        self.assertEqual((m.m.memory[0x5C8D], m.m.memory[0x5C48]), (7, 7))
        self.assertEqual(m.clean(), SYSVARS)

    def test_without_the_key_the_menu_stays(self) -> None:
        m, failed, message, at_unlock = self.go(PATCH)
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.m.memory[0x4000:0x5B00]), at_unlock)
        self.assertEqual(m.clean(), [])

    def test_the_fix_off_shows_nothing(self) -> None:
        f = nxc.set_field(PATCH, GAME, "build_screen", str(OFFSET))
        m = self.machine({"patch.nxc": f, NAME: GAME}, keys=("2", "enter"))
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertNotIn(T.NEX, m.written)
        self.assertFalse(rows(bytes(m.m.memory[0x4000:0x5B00]))[LAST_LINE].startswith("Patching"))
        self.assertEqual(m.clean(), [])

    def test_a_file_shorter_than_a_screen_shows_what_it_has(self) -> None:
        f = nxc.set_field(SHORT_PATCH, SHORT_GAME, "build_screen", str(OFFSET))
        m = self.machine({"patch.nxc": f, "game_v3.z80": SHORT_GAME})
        m.guard_iopage()
        for address in (0x5C8D, 0x5C48):
            m.m.unmark_addr(address, m.m.WRITE_MARK)
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[T.NEX]), nxc.apply(SHORT_PATCH, game=SHORT_GAME))
        self.assertEqual(bytes(m.m.memory[0x4000:0x4000 + len(SHORT_GAME) - OFFSET]), SHORT_GAME[OFFSET:])
        self.assertEqual(m.clean(), SYSVARS)

    def test_a_wrong_file_is_still_refused(self) -> None:
        f = nxc.set_field(PATCH, GAME, "build_screen", str(OFFSET))
        bad = bytearray(GAME)
        bad[len(bad) // 2] ^= 1
        m, failed, message, _ = self.go(f, game=bytes(bad))
        self.assertTrue(failed)
        self.assertEqual(message, "Wrong game file for this patch")
        self.assertNotIn(T.NEX, m.written)


if __name__ == "__main__":
    unittest.main()

"""Reserved names show nothing (spec, "Reserved: game speed, SET2 kind 5" and "Reserved: SPL1"): a patch with a kind 5 set
and an SPL1 block gives the same menu, from the dot command and from tools/nxc.py, and the same files, as without them."""
from __future__ import annotations

import unittest

import test_nexclash_dot as T
import test_nexclash_find as F

nxc = T.nxc


def with_reserved(f: bytes, game: bytes) -> bytes:
    """The patch with a game speed set (a copy of its colour set's block made kind 5, choice 1, named 7 MHz, under a stream
    index of its own) and an SPL1 block, resealed."""
    st, bl = nxc.check_key(f, game)[:2]
    colours = next(d for t, d in bl if t == nxc.SET_TAG and d[1] == nxc.KIND_COLOURS)
    rest = colours[nxc.SET_FIXED + colours[4]:]
    speed = bytes((200, 5, 1, nxc.BASE_SPRITE, 5)) + b"7 MHz" + rest
    spl = bytes((1, 0xFF, 0, 0, 1, 1, 0, 1, 0)) + bytes((0, 0, 8, 0, 0, 0, 1, 8, 0, 0, 0, 0))
    return nxc.seal(f[:nxc.CHECK_AT], [[t, d] for t, d in bl] + [[nxc.SET_TAG, speed], [b"SPL1", spl]], st)


@T.needs_tools
class ShowNothing(T.Base):
    def test_both_readers(self) -> None:
        f = with_reserved(F.PATCH, F.GAME)
        self.assertEqual(nxc.menu_lines(f), nxc.menu_lines(F.PATCH))
        self.assertEqual(nxc.menu_description(f), nxc.menu_description(F.PATCH))
        for kw in ({}, dict(colours="Painted"), dict(chosen=["1"])):
            self.assertEqual(nxc.apply(f, game=F.GAME, **kw), nxc.apply(F.PATCH, game=F.GAME, **kw))
        screens = []
        for patch in (F.PATCH, f):
            m = self.machine({"patch.nxc": patch, "game_v3.z80": F.GAME}, keys=["space"])
            failed, message = m.run('"patch.nxc"')
            self.assertFalse(failed, message)
            self.assertEqual(bytes(m.written[T.NEX]), nxc.apply_menu(patch, F.GAME))
            screens.append(m.screens[1])
        self.assertEqual(screens[0], screens[1])
        self.assertNotIn("MHz", screens[1])


if __name__ == "__main__":
    unittest.main()

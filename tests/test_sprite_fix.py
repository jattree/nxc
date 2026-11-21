"""tools/sprite_fix.py on a synthetic patch: every choice rebuilds as the old build with all 128 sprites hidden, the
rest is kept, and it refuses what it cannot do. Needs the zx0 compressor (NXC_ZX0_DIR); skips without it."""
from __future__ import annotations

import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(os.environ.get("NXC_EVIDENCE", str(ROOT / "build" / "evidence")))
os.environ.setdefault("NXC_ZX0_DIR", str(EVIDENCE / "format-study" / "zx0bin"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
try:
    import nxc
    import sprite_fix as F
    from test_nxc_tool import z80_128
    from test_automap_fix import nex
except ImportError:
    nxc = None

ZX0 = Path(os.environ["NXC_ZX0_DIR"]) / "zx0"


@unittest.skipUnless(nxc is not None and ZX0.exists(), "tools/nxc.py or the zx0 compressor is missing")
class SpriteFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        rng = random.Random(4)
        cls.banks = {b: bytes(rng.randrange(256) for _ in range(256)).ljust(16384, b"\0") for b in range(8)}
        cls.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        tmp = Path(cls.tmp.name)
        cls.game = z80_128(cls.banks, 0x10)
        (tmp / "game.z80").write_bytes(cls.game)
        built = dict(cls.banks)
        built[2] = b"\x5a" * 64 + built[2][64:]
        built[10] = (b"\xf3\x31\xfe\xdf" + bytes(range(60))).ljust(0x1000, b"\0") + F.OLD
        built[10] = built[10].ljust(16384, b"\0")
        (tmp / "out.nex").write_bytes(nex(built))
        painted = dict(built)
        painted[2] = b"\x77" * 8 + built[2][8:]
        (tmp / "enh.nex").write_bytes(nex(painted))
        target = dict(title="Synthetic", file="game.z80", length=len(cls.game))
        info = dict(build="test", publisher="Tester, 2026")
        cls.patch, _ = nxc.make(str(tmp / "game.z80"), str(tmp / "out.nex"), target, info,
                                colours={"Enhanced": str(tmp / "enh.nex")})
        cls.poking, _ = nxc.make(str(tmp / "game.z80"), str(tmp / "out.nex"), target, info,
                                 trainer_blocks=[nxc.trn1("Bad", [(10, 0x1000 + F.AT, 0x80)])])
        moved = dict(built)                                                          # a set that breaks the
        b10 = bytearray(built[10]); b10[0x1000] = 0; b10[0x1100:0x1100 + len(F.OLD)] = F.OLD          # loop, not its count,
        moved[10] = bytes(b10)                                                                        # and makes it again
        (tmp / "moved.nex").write_bytes(nex(moved))
        cls.moving, _ = nxc.make(str(tmp / "game.z80"), str(tmp / "out.nex"), target, info,
                                 colours={"Moved": str(tmp / "moved.nex")})
        plain = dict(cls.banks)
        plain[10] = (b"\xf3" + bytes(10)).ljust(16384, b"\0")
        (tmp / "plain.nex").write_bytes(nex(plain))
        cls.plain, _ = nxc.make(str(tmp / "game.z80"), str(tmp / "plain.nex"), target, info)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_every_choice_is_the_old_build_hiding_128(self) -> None:
        new, report = F.fix(self.patch, self.game)
        for choice in ({}, {"colours": "Enhanced"}):
            old = nxc.apply(self.patch, game=self.game, **choice)
            got = nxc.apply(new, game=self.game, **choice)
            self.assertEqual(got, F.hide_all(old))
            self.assertEqual(sum(a != b for a, b in zip(got, old)), 1)
        self.assertIn("set Enhanced", report)

    def test_only_the_build_blocks_change(self) -> None:
        new, _ = F.fix(self.patch, self.game)
        old_blocks, new_blocks = nxc.blocks(self.patch)[1], nxc.blocks(new)[1]
        self.assertEqual([t for t, _ in old_blocks], [t for t, _ in new_blocks])
        changed = {t for (t, a), (_, b) in zip(old_blocks, new_blocks) if a != b}
        self.assertTrue(changed <= {b"NEX1", b"OUT1", b"BNK1", nxc.SET_TAG, nxc.BIG_TAG}, changed)

    def test_idempotent(self) -> None:
        new, _ = F.fix(self.patch, self.game)
        self.assertEqual(F.fix(new, self.game), (new, "already done"))

    def test_a_trainer_poking_the_count_is_refused(self) -> None:
        with self.assertRaisesRegex(nxc.Wrong, "trainer"):
            F.fix(self.poking, self.game)

    def test_a_set_that_moves_the_setup_is_refused(self) -> None:
        with self.assertRaisesRegex(nxc.Wrong, "moves the sprite count"):
            F.fix(self.moving, self.game)

    def test_a_build_without_the_setup_is_refused(self) -> None:
        with self.assertRaisesRegex(nxc.Wrong, "no TID"):
            F.fix(self.plain, self.game)


if __name__ == "__main__":
    unittest.main()

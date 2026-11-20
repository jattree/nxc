"""tools/automap_fix.py on a synthetic patch: every choice rebuilds as automap_off(the old build), the rest is kept,
and it refuses what it cannot do. Needs the zx0 compressor (NXC_ZX0_DIR); skips without it."""
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
    import automap_fix as A
    from test_nxc_tool import z80_128
except ImportError:
    nxc = None

ZX0 = Path(os.environ["NXC_ZX0_DIR"]) / "zx0"


def nex(banks: dict, entry: int = 10) -> bytes:
    head = bytearray(512)
    head[0:8] = b"NextV1.2"
    head[9] = len(banks)
    head[12:16] = bytes((0xFE, 0xDF, 0x00, 0xC0))
    head[139] = entry
    for b in banks:
        head[18 + b] = 1
    return bytes(head) + b"".join(banks[b] for b in nxc.ORDER if b in banks)


@unittest.skipUnless(nxc is not None and ZX0.exists(), "tools/nxc.py or the zx0 compressor is missing")
class AutomapFix(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        rng = random.Random(10)
        cls.banks = {b: bytes(rng.randrange(256) for _ in range(256)).ljust(16384, b"\0") for b in range(8)}
        cls.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        tmp = Path(cls.tmp.name)
        cls.game = z80_128(cls.banks, 0x10)
        (tmp / "game.z80").write_bytes(cls.game)
        built = dict(cls.banks)
        built[2] = b"\x5a" * 64 + built[2][64:]
        built[10] = (b"\xf3\x31\xfe\xdf" + bytes(range(60))).ljust(16384, b"\0")      # a "stub" at 0xC000
        (tmp / "out.nex").write_bytes(nex(built))
        painted = dict(built)
        painted[2] = b"\x77" * 8 + built[2][8:]
        painted[10] = built[10][:4] + b"\x99" + built[10][5:]                        # the set touches the stub bank
        (tmp / "enh.nex").write_bytes(nex(painted))
        clash = dict(built)
        clash[10] = built[10][:A.AT] + b"\x01" + built[10][A.AT + 1:]                 # ... and one over the window
        (tmp / "clash.nex").write_bytes(nex(clash))
        target = dict(title="Synthetic", file="game.z80", length=len(cls.game))
        info = dict(build="test", publisher="Tester, 2026")
        cls.patch, _ = nxc.make(str(tmp / "game.z80"), str(tmp / "out.nex"), target, info,
                                colours={"Enhanced": str(tmp / "enh.nex")})
        cls.poking, _ = nxc.make(str(tmp / "game.z80"), str(tmp / "out.nex"), target, info,
                                 trainer_blocks=[nxc.trn1("Bad", [(10, A.AT + 12, 0xFF)])])
        late = dict(built)
        (tmp / "late.nex").write_bytes(nex(late)[:14] + b"\x00\xde" + nex(late)[16:])   # starts at 0xDE00, no code there
        cls.late, _ = nxc.make(str(tmp / "game.z80"), str(tmp / "late.nex"), target, info)
        cls.clash, _ = nxc.make(str(tmp / "game.z80"), str(tmp / "out.nex"), target, info,
                                colours={"Enhanced": str(tmp / "clash.nex")})

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_every_choice_is_the_old_build_with_automap_off(self) -> None:
        new, report = A.fix(self.patch, self.game)
        for choice in ({}, {"colours": "Enhanced"}):
            old = nxc.apply(self.patch, game=self.game, **choice)
            self.assertEqual(nxc.apply(new, game=self.game, **choice), A.automap_off(old))
        out = nxc.apply(new, game=self.game)
        self.assertEqual(out[14:16], b"\x00\xde")
        e = A.offsets(out)[10] + A.AT
        self.assertEqual(out[e:e + 19], A.code(0xC000))
        self.assertIn("set Enhanced", report)

    def test_only_the_build_blocks_change(self) -> None:
        new, _ = A.fix(self.patch, self.game)
        old_blocks, new_blocks = nxc.blocks(self.patch)[1], nxc.blocks(new)[1]
        self.assertEqual([t for t, _ in old_blocks], [t for t, _ in new_blocks])
        changed = {t for (t, a), (_, b) in zip(old_blocks, new_blocks) if a != b}
        self.assertTrue(changed <= {b"NEX1", b"OUT1", b"BNK1", nxc.SET_TAG, nxc.BIG_TAG}, changed)

    def test_idempotent(self) -> None:
        new, _ = A.fix(self.patch, self.game)
        again, report = A.fix(new, self.game)
        self.assertEqual(again, new)
        self.assertEqual(report, "already done")

    def test_a_set_over_the_window_is_refused(self) -> None:
        with self.assertRaisesRegex(nxc.Wrong, "window"):
            A.fix(self.clash, self.game)

    def test_a_trainer_poking_the_window_is_refused(self) -> None:
        with self.assertRaisesRegex(nxc.Wrong, "trainer"):
            A.fix(self.poking, self.game)

    def test_a_start_at_the_window_without_the_code_is_refused(self) -> None:
        with self.assertRaises(nxc.Wrong):
            A.fix(self.late, self.game)

    def test_automap_off_refuses_a_short_file(self) -> None:
        good = nxc.apply(self.patch, game=self.game)
        with self.assertRaises(nxc.Wrong):
            A.automap_off(good[:600])


if __name__ == "__main__":
    unittest.main()

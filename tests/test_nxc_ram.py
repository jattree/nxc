"""SET3: an option with a memory need and banks of its own, through tools/nxc.py, on the made-up tape game. Made from a
colour build that lists banks the base does not; applied alone, with another set, with a toggle and with a trainer; refused
on a machine with too little memory; carried by a menu .nex only for a machine that has it; and read by the reader before
SET3 (main's nxc.py, as it was) as the base with no such line. Needs the zx0 compressor (NXC_ZX0_DIR)."""
from __future__ import annotations

import importlib.util
import os
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

import tape_game as G
import test_nexclash_dot as T
import test_nxc_tape as TT

nxc = T.nxc
ROOT = T.ROOT
TMP = os.environ.get("TMPDIR")
B2 = 512 + 16384                  # bank 2 in the .nex, after bank 5
ADDED = (50, 60)                  # the big option's own banks, above a 1MB Next's 47


def variant(nex: bytes, changes) -> bytes:
    out = bytearray(nex)
    for o, v in changes:
        out[B2 + o] = v
    return bytes(out)


def with_banks(nex: bytes, extra: dict) -> bytes:
    """The .nex with whole banks added: listed in the header, in .nex order, byte 8 as the format says."""
    banks = nxc.nex_banks(nex)
    banks.update(extra)
    header = bytearray(nex[:512])
    for b in extra:
        header[18 + b] = 1
    header[9] += len(extra)
    if any(b > 47 for b in extra):
        header[8] = 1
    return bytes(header) + nxc.nex_screen(nex) + b"".join(banks[b] for b in nxc.ORDER if header[18 + b])


def big_build(nex: bytes, changes=((0x2300, 0x77),)) -> bytes:
    extra = {b: bytes((b + i) & 255 for i in range(16384)) for b in ADDED}
    return with_banks(variant(nex, list(changes)), extra)


def build(big=True, colours=None, language=None, toggles=None, trainers=(), set_top=None, rules=None, extra_big=None):
    """(patch, base .nex, tap, big .nex)."""
    blocks = G.data_blocks()
    start = G.start_banks(blocks)
    nex, extra = G.build(start, blocks, nxc.ORDER)
    bignex = big_build(nex)
    with tempfile.TemporaryDirectory(dir=TMP) as d:
        tmp = Path(d)
        for name, data in (("game.tap", G.tap(blocks)), ("start.z80", G.start_z80(start)), ("o.nex", nex), ("big.nex", bignex)):
            (tmp / name).write_bytes(data)
        col = {}
        if big:
            col["Enhanced"] = str(tmp / "big.nex")
        for i, (n, ch) in enumerate((colours or {}).items()):
            (tmp / f"c{i}.nex").write_bytes(variant(nex, ch)); col[n] = str(tmp / f"c{i}.nex")
        if extra_big:
            (tmp / "big2.nex").write_bytes(extra_big(nex)); col["Second"] = str(tmp / "big2.nex")
        lang = {}
        for i, (n, ch) in enumerate((language or {}).items()):
            (tmp / f"l{i}.nex").write_bytes(variant(nex, ch)); lang[n] = str(tmp / f"l{i}.nex")
        tog = {}
        for i, (n, ch) in enumerate((toggles or {}).items()):
            (tmp / f"t{i}.nex").write_bytes(variant(nex, ch)); tog[n] = (str(tmp / f"t{i}.nex"), False)
        patch, _ = nxc.make(str(tmp / "game.tap"), str(tmp / "o.nex"), dict(title="Tape Game", file="game.tap"),
                            dict(build="t", colours_by="A Painter"), start=str(tmp / "start.z80"), tape_banks=extra,
                            colours=col, languages=lang, toggles=tog, trainer_blocks=[nxc.trn1(n, p) for n, p in trainers],
                            set_top=set_top, rules=rules)
    return patch, nex, G.tap(blocks), bignex


def old_reader():
    """tools/nxc.py as it was before SET3 (main at 8cf4662's successor, ea2a22f), imported on its own."""
    src = subprocess.run(["git", "-C", str(ROOT), "show", "ea2a22f:tools/nxc.py"], check=True, capture_output=True).stdout
    with tempfile.NamedTemporaryFile("wb", suffix=".py", delete=False, dir=TMP) as g:
        g.write(src)
        path = g.name
    spec = importlib.util.spec_from_file_location("nxc_before_set3", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.STUB = nxc.STUB; m.STUB_RULES = nxc.STUB_RULES      # the stubs, which SET3 does not change
    os.unlink(path)
    return m


@TT.needs
class BigOption(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch, cls.nex, cls.tap, cls.big = build(language={"Deutsch": [(0x2400, 0x44)]},
                                                     toggles={"Smooth": [(0x2500, 0x55)]},
                                                     trainers=[("Lives", [(2, 0x2010, 0xAB)])])

    def test_the_block_and_its_need(self) -> None:
        (e,) = nxc.big_offered(self.patch)
        self.assertEqual((e["name"], e["kind"], e["top"], e["added"]), (b"Enhanced", nxc.KIND_COLOURS, 60, list(ADDED)))
        self.assertEqual(nxc.colour_sets(self.patch), [])            # no SET2 colour set: what a reader before SET3 sees
        opt = dict(nxc.blocks(self.patch)[1])[b"OPT1"]
        self.assertLessEqual(opt[2], 47)                             # the base fits a 1MB Next
        self.assertEqual(nxc.option_top(self.patch, e), 60)
        self.assertEqual(len(e["table"]), 2)                         # the language and the toggle

    def test_alone_and_with_everything(self) -> None:
        lang = [(0x2400, 0x44)]; smooth = [(0x2500, 0x55)]
        self.assertEqual(nxc.apply(self.patch, game=self.tap, colours="Enhanced"), self.big)
        self.assertEqual(nxc.apply(self.patch, game=self.tap, colours="Enhanced", ram_top=111), self.big)
        both = nxc.apply(self.patch, game=self.tap, colours="Enhanced", language="Deutsch", toggles=["Smooth"], chosen=[1])
        want = bytearray(self.big)
        for o, v in lang + smooth + [(0x2010, 0xAB)]:
            want[B2 + o] = v
        self.assertEqual(both, bytes(want))
        self.assertEqual(nxc.apply(self.patch, game=self.tap, language="Deutsch"), variant(self.nex, lang))
        self.assertEqual(nxc.apply(self.patch, game=self.tap), self.nex)

    def test_too_little_memory(self) -> None:
        with self.assertRaisesRegex(nxc.Wrong, "Needs a 2MB Next"):
            nxc.apply(self.patch, game=self.tap, colours="Enhanced", ram_top=47)
        self.assertEqual(nxc.apply(self.patch, game=self.tap, ram_top=47, chosen=[1], language="Deutsch"),
                         nxc.apply(self.patch, game=self.tap, chosen=[1], language="Deutsch"))
        with self.assertRaisesRegex(nxc.Wrong, "no colours set"):
            nxc.apply_menu(self.patch, self.tap, colours="Enhanced", ram_top=47)

    def test_menu_nex_for_each_machine(self) -> None:
        small = nxc.apply_menu(self.patch, self.tap, ram_top=47)
        full = nxc.apply_menu(self.patch, self.tap)
        self.assertEqual(full, nxc.apply_menu(self.patch, self.tap, ram_top=111))
        hs, hf = small[:512], full[:512]
        self.assertEqual(hs[139], dict(nxc.blocks(self.patch)[1])[b"OPT1"][2] + 1)     # M0, the stub's bank
        self.assertLessEqual(max(b for b in range(112) if hs[18 + b]), 47)
        self.assertEqual(hs[8], 0)
        self.assertEqual(hf[139], 61)                                    # the stub above the option's need
        self.assertEqual(hf[8], 1)
        self.assertNotIn(b"Enhanced", small)
        self.assertIn(b"Enhanced", full)
        # The carrier: the big build with only its own banks' bytes, so off is the base and its line the rest.
        carrier = nxc.apply(self.patch, game=self.tap, carrier=True)
        self.assertEqual(carrier, big_build(self.nex, ()))
        self.assertEqual(full[512:len(carrier)], carrier[512:])
        # The data carries its chunk for bank 2 only.
        desc, data = nxc.menu_description(self.patch, nxc.check_key(self.patch, self.tap)[0])
        self.assertIn(b"\x02", data[:4])
        self.assertLess(len(data), 3 * 20000)

    def test_a_reader_before_set3(self) -> None:
        old = old_reader()
        self.assertEqual(old.apply(self.patch, game=self.tap), self.nex)
        self.assertEqual(old.colour_sets(self.patch), [])
        self.assertEqual([l[1] for l in old.menu_lines(self.patch)], [l[1] for l in nxc.menu_lines(self.patch, 47)])
        self.assertEqual(old.apply_menu(self.patch, self.tap), nxc.apply_menu(self.patch, self.tap, ram_top=47))
        with self.assertRaises(old.Wrong):
            old.apply(self.patch, game=self.tap, colours="Enhanced")

    def test_set_top_raises_the_need(self) -> None:
        patch, *_ = build(set_top={"Enhanced": 100})
        self.assertEqual(nxc.big_offered(patch)[0]["top"], 100)
        self.assertEqual(nxc.apply_menu(patch, self.tap)[139], 101)

    def test_writer_refusals(self) -> None:
        with self.assertRaisesRegex(ValueError, "line to itself"):
            build(colours={"Plain": [(0x2600, 1)]})
        with self.assertRaisesRegex(ValueError, "only one"):
            build(extra_big=lambda nex: with_banks(nex, {70: bytes(16384)}))
        with self.assertRaisesRegex(ValueError, "both change"):
            build(language={"Deutsch": [(0x2300, 0x44)]})            # the byte the big option changes

    def test_a_rule_may_not_name_it(self) -> None:
        with self.assertRaises(nxc.Wrong):
            build(language={"Deutsch": [(0x2400, 0x44)]}, rules=[(nxc.RULE_EXCLUDES, "Enhanced", "Deutsch")])
        patch, *_ = build(language={"Deutsch": [(0x2400, 0x44)]}, toggles={"Smooth": [(0x2500, 0x55)]},
                          rules=[(nxc.RULE_NEEDS | nxc.RULE_MENU_ONLY, "Smooth", "Deutsch")])
        small = nxc.apply_menu(patch, self.tap, ram_top=47)
        self.assertNotIn(b"Enhanced", small)
        nxc.apply_menu(patch, self.tap, toggles=["Smooth"], language="Deutsch")

    def test_damage(self) -> None:
        nonce, bl = nxc.blocks(self.patch)
        i = next(k for k, (t, _) in enumerate(bl) if t == nxc.BIG_TAG)
        for change in (lambda d: d[:13] + bytes((40,)) + d[14:],          # a need below the base's
                       lambda d: d[:14] + bytes((3,)) + d[15:]):          # a count running into the table
            bad = [list(x) for x in bl]
            bad[i][1] = change(bad[i][1])
            with self.subTest(change=change):
                with self.assertRaises(nxc.Wrong):
                    nxc.check_structure([tuple(x) for x in bad])


if __name__ == "__main__":
    unittest.main()

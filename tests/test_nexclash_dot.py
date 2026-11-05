"""The .NEXCLASH dot command, on a Z80 emulator with NextZXOS faked (nexclash_harness.py), must write what tools/nxc.py
writes, byte for byte, and refuse everything else cleanly.

Two kinds of test: synthetic ones need only sjasmplus, the z80 package, the zx0 compressor (NXC_ZX0_DIR) and
the zx0 compressor (NXC_ZX0_DIR); those on real games also need the game files, which are not in this repository, and
skip with a message without them (NXC_EVIDENCE, build/inputs). Nothing here holds game data or hashes of it: what a
build must come to is read from the files at run time.
"""
from __future__ import annotations

import glob
import hashlib
import os
import random
import shutil
import struct
import sys
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EVIDENCE = Path(os.environ.get("NXC_EVIDENCE", str(Path(__file__).resolve().parents[1] / "build" / "evidence")))
REFERENCE = Path(os.environ.get("NXC_REFERENCE", str(EVIDENCE / "reference")))
os.environ.setdefault("NXC_ZX0_DIR", str(EVIDENCE / "format-study" / "zx0bin"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))

import nexclash_harness as H  # noqa: E402

try:
    import nxc
except ImportError:
    nxc = None

INPUTS = ROOT / "build" / "inputs"
ZX0_TOOL = Path(os.environ["NXC_ZX0_DIR"]) / "zx0"
NEX = "$/tmp/nexclash.nex"
Z80 = "$/tmp/nexclash.z80"
PHASES = ["zx0_decode"]


def first_existing(*paths) -> Path | None:
    for path in paths:
        if Path(path).exists():
            return Path(path)
    return None


V1 = ROOT / "build" / "v1"     # the patches as last rebuilt, by a script that is not in this repository
COBRA_GAME = first_existing(INPUTS / "cobra.z80", EVIDENCE / "pilot/runs/cobra/cobra.z80")
COBRA_NEX = first_existing(INPUTS / "source_sprites.nex", EVIDENCE / "format-study/cobra/source_sprites.nex")
COBRA_PATCH = first_existing(V1 / "Cobra_plain.nxc")
_poks = glob.glob(str(INPUTS / "Cobra*.pok")) + glob.glob(os.path.expanduser("~/Downloads/Cobra*.pok"))
COBRA_POK = Path(_poks[0]) if _poks else None
HAVE_COBRA = bool(COBRA_GAME and COBRA_NEX and COBRA_PATCH and COBRA_POK)


def needs_tools(cls):
    cls = unittest.skipUnless(shutil.which("sjasmplus"), "sjasmplus is not installed")(cls)
    cls = unittest.skipUnless(H.z80 is not None, "the z80 package is not installed (pip install z80)")(cls)
    return unittest.skipUnless(nxc is not None, "tools/nxc.py cannot be imported")(cls)


def val(label: str, value: str) -> str:
    """A line's name and value as firmware/menu.asm draws them, from column 2 to 31."""
    return label[:30 - len(value)].ljust(30 - len(value)) + value


# The menu's fixed footer, rows 22 and 23, the same on every patch's menu (spec, "The menu"): row 23's stripes a column to
# the left, and its last cell cyan with no pixels, which the harness reads as a space.
FOOTER = {22: " .nxc by Jon Attree".ljust(28) + "////", 23: " Engine: Dean Woodyatt".ljust(27) + "////"}


def screen(rows: dict[int, str]) -> str:
    """A whole menu screen, as the harness reads it: rows not given are blank; rows 22 and 23 the fixed footer."""
    rows = {**FOOTER, **rows}
    return "\n".join(rows.get(r, "") for r in range(24))


def row(key: str, label: str, value: str) -> str:
    """A menu line as firmware/menu.asm draws it: key, name from column 2, value ending in column 31."""
    return (key + " " + label)[:32 - len(value)].ljust(32 - len(value)) + value


def text_of(patch: bytes, tag: bytes) -> dict[str, str]:
    for t, d in nxc.blocks(patch)[1]:
        if t == tag:
            d = d[nxc.TARGET_FIXED:] if tag == b"TGT1" else d
            return dict(line.split("=", 1) for line in d.decode(errors="replace").splitlines() if "=" in line)
    return {}


def unlocked(patch: bytes, game: bytes):
    """(nonce, blocks, master stream) with no check of the file, as someone who owns the game can get them."""
    nonce, bl = nxc.blocks(patch)
    base = nxc.dump_state(nonce, game)
    for t, d in bl:
        if t == b"TGT1" and len(d) >= nxc.TARGET_FIXED:
            plain = base.block(b"TGT1", d[0])(d[6:nxc.TARGET_FIXED])
            if plain[:8] == nxc.WRAP_CHECK:
                return nonce, bl, nxc.key_state(nonce, plain[8:]), plain[8:]
    raise AssertionError("that game does not unlock this patch")


def rekey(patch: bytes, game: bytes, edit=None) -> bytes:
    """The patch rebuilt with edit(list of [tag, data], stream) applied and the check value recomputed: what someone who owns
    the game can do, and no one else."""
    nonce, bl, st, _ = unlocked(patch, game)
    bl = [[t, d] for t, d in bl]
    if edit:
        edit(bl, st)
    return nxc.seal(patch[:nxc.CHECK_AT], bl, st)


def rekey_at(patch: bytes, game: bytes, position: int, mask: int) -> bytes:
    """A byte flipped in the file, then the check recomputed so the flip gets past it. Skips the check field itself."""
    _, _, st, _ = unlocked(patch, game)
    out = bytearray(patch)
    out[position] ^= mask
    return bytes(out[:nxc.CHECK_AT]) + nxc.check_value(bytes(out), st) + bytes(out[nxc.HEADER:])


# ------------------------------------------------------------------ snapshots made here


def pack_z80(data: bytes) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        n = 1
        while i + n < len(data) and data[i + n] == data[i] and n < 255:
            n += 1
        if n >= 5 or (data[i] == 0xED and n >= 2):
            out += bytes((0xED, 0xED, n, data[i]))
            i += n
        elif data[i] == 0xED:      # a single ED: the next byte goes with it, never starting a run
            out.append(0xED)
            i += 1
            if i < len(data):
                out.append(data[i])
                i += 1
        else:
            out.append(data[i])
            i += 1
    return bytes(out)


def random_bank(rng: random.Random, seed: int) -> bytes:
    data = bytearray(rng.randrange(256) for _ in range(16384))
    for _ in range(20):
        at = rng.randrange(16000)
        data[at:at + 200] = bytes((rng.choice((0, 0xED, seed & 255)),)) * 200
    data[100:103] = b"\xed\x00\xed"
    return bytes(data)


def header(pc: int = 0x8000, flags: int = 0) -> bytearray:
    h = bytearray(random.Random(pc).randrange(256) for _ in range(30))
    h[6:8] = pc.to_bytes(2, "little")
    h[12] = flags
    return h


def snapshot_v1(banks: dict[int, bytes], packed: bool = True) -> bytes:
    ram = banks[5] + banks[2] + banks[0]
    if packed:
        return bytes(header(flags=0x20)) + pack_z80(ram) + b"\x00\xED\xED\x00"
    return bytes(header(flags=0)) + ram


def snapshot_paged(banks: dict[int, bytes], ext_len: int, hw: int, order=None, raw=()) -> bytes:
    h = header(pc=0)
    ext = bytearray(ext_len)
    ext[0:2] = (0x8000).to_bytes(2, "little")
    ext[2] = hw
    out = bytes(h) + ext_len.to_bytes(2, "little") + bytes(ext)
    is128 = (hw in (3, 4)) if ext_len == 23 else (hw in (4, 5, 6, 7, 9, 12, 13))
    pages = {b + 3: d for b, d in banks.items()} if is128 else {8: banks[5], 4: banks[2], 5: banks[0]}
    for page in order or sorted(pages):
        if page in raw:
            out += b"\xff\xff" + bytes((page,)) + pages[page]
        else:
            body = pack_z80(pages[page])
            out += len(body).to_bytes(2, "little") + bytes((page,)) + body
    return out


def nex_from(banks: dict[int, bytes]) -> bytes:
    head = bytearray(512)
    head[0:8] = b"NextV1.2"
    head[9] = len(banks)
    for b in banks:
        head[18 + b] = 1
    return bytes(head) + b"".join(banks[b] for b in nxc.ORDER if b in banks)


def build_case(tmp: Path, rng: random.Random, game: bytes, banks: dict[int, bytes], extra=(10, 13), level: int = 1):
    """A patch for a made-up game: some sites, some banks the game lacks."""
    path = tmp / "game.z80"
    path.write_bytes(game)
    out = dict(banks)
    for b in list(out):
        data = bytearray(out[b])
        for _ in range(rng.randrange(1, 12)):
            at = rng.randrange(16000)
            n = rng.randrange(1, 40)
            data[at:at + n] = bytes(rng.randrange(256) for _ in range(n))
        out[b] = bytes(data)
    for b in extra:
        out[b] = bytes(rng.randrange(256) for _ in range(rng.randrange(300, 16384))).ljust(16384, b"\0")
    nex = tmp / "out.nex"
    nex.write_bytes(nex_from(out))
    patch, _ = nxc.make(str(path), str(nex), dict(title="Made Up", file="game.z80", length=len(game)),
                        dict(build="test", publisher="Tester, 2026"), level=level)
    return patch, nex.read_bytes()


class BitWriter:
    """A ZX0 stream written by hand, for ones a compressor would never make."""

    def __init__(self) -> None:
        self.out = bytearray()
        self.mask = 0
        self.at = 0

    def bit(self, b: int) -> None:
        if not self.mask:
            self.out.append(0)
            self.at = len(self.out) - 1
            self.mask = 0x80
        if b:
            self.out[self.at] |= self.mask
        self.mask >>= 1

    def bits(self, *values: int) -> "BitWriter":
        for b in values:
            self.bit(b)
        return self

    def byte(self, b: int) -> "BitWriter":
        self.out.append(b)
        return self

    def end_marker(self) -> "BitWriter":
        return self.bits(*(0, 1) * 8, 1)


def copy_before_start() -> bytes:
    """One literal, a copy of 2 from 384 bytes back, the end: well formed and exactly 3 bytes, but for where it reads."""
    return bytes(BitWriter().bits(1).byte(0x55).bits(1, 0, 0, 1).byte(1).bits(1).end_marker().out)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.makedirs(os.environ.get("TMPDIR", "/tmp"), exist_ok=True)
        cls.binary, cls.symbols = H.assemble()

    def machine(self, files: dict[str, bytes], keys=("enter",), binary=None, symbols=None, **options) -> H.Machine:
        m = H.Machine(binary or self.binary, symbols or self.symbols, files, keys=keys, **options)
        m.set_phases(PHASES)
        m.guard_iopage()
        return m

    def run_patch(self, patch: bytes, game: bytes | None, keys=("enter",), game_name: str | None = "game.z80", **options):
        files = {"patch.nxc": patch}
        if game is not None:
            files[game_name] = game
        m = self.machine(files, keys=keys, **options)
        failed, message = m.run('"patch.nxc"')
        return m, failed, message

    def assert_refused(self, m: H.Machine, failed: bool, message: str, expect: str | None = None) -> None:
        self.assertTrue(failed, "it was not refused")
        if expect is not None:
            self.assertEqual(message, expect)
        self.assertEqual(m.clean(), [])
        self.assertNotIn(NEX, m.written)
        self.assertNotIn(Z80, m.written)


@needs_tools
class UsageAndArguments(Base):
    def test_usage_credits(self) -> None:
        m = self.machine({})
        failed, _ = m.run(None)
        self.assertFalse(failed)
        text = " ".join(m.screen)
        self.assertIn("Built with NexClash by Dean Woodyatt (Bleugh.biz, bleughb/nexclash, GPL-3.0+)", text)
        self.assertIn("GPL-3.0", text)
        self.assertNotIn("Tested", text)
        self.assertNotIn("not on a Next", text)
        self.assertEqual(m.clean(), [])
        for line in m.screen:
            self.assertLessEqual(len(line), 32)

    def test_no_nextzxos(self) -> None:
        m = self.machine({}, os_mode=1)
        failed, message = m.run('"patch.nxc"')
        self.assertTrue(failed)
        self.assertEqual(message, "Needs NextZXOS")

    def test_no_patch(self) -> None:
        m = self.machine({})
        failed, message = m.run('"nothing.nxc"')
        self.assertTrue(failed)
        self.assertEqual(message, "Cannot open the .nxc")
        self.assertEqual(m.clean(), [])

    def test_not_a_patch(self) -> None:
        for data in (b"", b"NXC1", b"NOPE" + bytes(100), b"NXC1\x02" + bytes(100)):
            m = self.machine({"patch.nxc": data})
            failed, message = m.run('"patch.nxc"')
            self.assertTrue(failed)
            self.assertEqual(message, "Not a .nxc file")
            self.assertEqual(m.clean(), [])


@needs_tools
@unittest.skipUnless(ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class MadeUpGames(Base):
    """Every snapshot shape the loader must read, against tools/nxc.py, on data made here."""

    def cases(self):
        rng = random.Random(5)
        b48 = {b: random_bank(rng, b) for b in (5, 2, 0)}
        b128 = {b: random_bank(rng, b) for b in range(8)}
        yield "v1 packed", snapshot_v1(b48), b48
        yield "v1 stored", snapshot_v1(b48, packed=False), b48
        yield "v2 48K", snapshot_paged(b48, 23, 0), b48
        yield "v3 48K", snapshot_paged(b48, 54, 0), b48
        yield "v3 48K, Spectrum 16K order", snapshot_paged(b48, 54, 0, order=[5, 4, 8]), b48
        yield "v2 128K", snapshot_paged(b128, 23, 3), b128
        yield "v3 128K", snapshot_paged(b128, 54, 4), b128
        yield "v3 128K, long header", snapshot_paged(b128, 55, 12), b128
        yield "v3 128K, stored pages", snapshot_paged(b128, 54, 4, raw=(3, 8)), b128
        yield "v3 128K, shuffled", snapshot_paged(b128, 54, 4, order=[10, 3, 9, 4, 8, 5, 7, 6]), b128

    def test_every_snapshot_shape(self) -> None:
        import tempfile
        rng = random.Random(9)
        for name, game, banks in self.cases():
            with self.subTest(name), tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
                patch, want = build_case(Path(d), rng, game, banks)
                self.assertEqual(nxc.apply(patch, game=game), want)
                m, failed, message = self.run_patch(patch, game)
                self.assertFalse(failed, message)
                self.assertEqual(m.clean(), [])
                self.assertEqual(bytes(m.written[NEX]), want)
                self.assertEqual(m.integer_vars[23], 1)
                self.assertEqual(m.peak_pages, 6)

    def test_run_crossing_a_bank_in_v1(self) -> None:
        # A run from the end of bank 5 into bank 2, and an ED ED pair just before the boundary.
        import tempfile
        rng = random.Random(3)
        b48 = {b: random_bank(rng, b) for b in (5, 2, 0)}
        b48[5] = b48[5][:16000] + bytes(384)
        b48[2] = bytes(500) + b48[2][500:]
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
            game = snapshot_v1(b48)
            patch, want = build_case(Path(d), rng, game, b48)
            m, failed, message = self.run_patch(patch, game)
            self.assertFalse(failed, message)
            self.assertEqual(bytes(m.written[NEX]), want)

    def test_edges_of_the_run_length_code(self) -> None:
        # By hand: ED not followed by ED; ED at each of the last three places of a page, where the reader takes it
        # as itself; ED ED 0 x, which makes nothing.
        import tempfile
        rng = random.Random(4)
        for tail in (b"\xed", b"\xed\xed", b"\xed\xed\x01"):
            with self.subTest(tail=tail), tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
                b48 = {b: random_bank(rng, b) for b in (5, 2, 0)}
                bank = bytes(b48[5][:16384 - len(tail)])
                body = b"\xed\xed\x00\x55" + b"\xed\x01" + pack_z80(bank[2:])
                b48[5] = bank[:0] + b"\xed\x01" + bank[2:] + tail
                pages = b""
                for page, data in ((4, pack_z80(b48[2])), (5, pack_z80(b48[0])), (8, body + tail)):
                    pages += len(data).to_bytes(2, "little") + bytes((page,)) + data
                game = bytes(header(pc=0)) + (23).to_bytes(2, "little") + (0x8000).to_bytes(2, "little") + bytes(21) + pages
                got = nxc.Z80Snapshot.__new__(nxc.Z80Snapshot)
                path = Path(d) / "g.z80"
                path.write_bytes(game)
                self.assertEqual(bytes(nxc.Z80Snapshot(str(path)).banks[5]), b48[5])
                patch, want = build_case(Path(d), rng, game, b48)
                m, failed, message = self.run_patch(patch, game)
                self.assertFalse(failed, message)
                self.assertEqual(bytes(m.written[NEX]), want)

    def test_damaged_snapshots(self) -> None:
        # The key still fits, as it is keyed by these very bytes: only the decoder can refuse.
        import tempfile
        rng = random.Random(6)
        b48 = {b: random_bank(rng, b) for b in (5, 2, 0)}
        good = snapshot_paged(b48, 23, 0)
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
            patch, _ = build_case(Path(d), rng, good, b48)
            nonce, bl, st, master = unlocked(patch, good)
            for name, game in (("a page too long", snapshot_paged({**b48, 5: b48[5]}, 23, 0)[:-5] + b"\xed\xed\xff\x00" + b"zzzzz"),
                               ("a page cut off", good[:-200]),
                               ("missing bank", good[:32 + 23]),
                               ("header only", good[:20])):
                with self.subTest(name):
                    fixed = struct.pack("<BBI", 0, 1, len(game)) + nxc.dump_state(nonce, game).block(b"TGT1", 0)(nxc.WRAP_CHECK + master)
                    nb = [[t, fixed + dd[nxc.TARGET_FIXED:] if t == b"TGT1" else dd] for t, dd in bl]
                    forged = nxc.seal(patch[:nxc.CHECK_AT], nb, st)
                    m, failed, message = self.run_patch(forged, game)
                    self.assertTrue(failed, name)
                    self.assertIn(message, ("Game file is damaged", "Patch damaged: get it again"))
                    self.assertEqual(m.clean(), [])
                    self.assertNotIn(NEX, m.written)


@needs_tools
@unittest.skipUnless(HAVE_COBRA, "Cobra's game, patch, build or .pok is missing (build/inputs or NXC_EVIDENCE)")
class Cobra(Base):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.game = COBRA_GAME.read_bytes()
        cls.source = COBRA_NEX.read_bytes()
        cls.shipped = COBRA_PATCH.read_bytes()
        cls.pok = COBRA_POK.read_text(encoding="latin-1")
        cls.patch = nxc.import_pok(cls.shipped, str(COBRA_GAME), cls.pok, "Ocean, 1986")
        cls.game_name = text_of(cls.shipped, b"TGT1")["file"].lower()
        cls.base_digest = hashlib.md5(cls.source).hexdigest()

    def run_cobra(self, patch=None, keys=("enter",), game=None, **options):
        return self.run_patch(patch if patch is not None else self.patch, self.game if game is None else game, keys,
                              game_name=self.game_name, **options)

    def test_byte_exact_from_the_original_patch(self) -> None:
        m, failed, message = self.run_cobra(self.shipped)
        self.assertFalse(failed, message)
        self.assertEqual(m.clean(), [])
        out = bytes(m.written[NEX])
        self.assertEqual(hashlib.md5(out).hexdigest(), self.base_digest)
        print(f"\nCobra, Z80: {NEX} {len(out)} bytes, MD5 {hashlib.md5(out).hexdigest()}, "
              f"build's MD5 {self.base_digest}", flush=True)

    def test_byte_exact_with_trainers_available_and_off(self) -> None:
        m, failed, message = self.run_cobra()
        self.assertFalse(failed, message)
        self.assertEqual(hashlib.md5(bytes(m.written[NEX])).hexdigest(), self.base_digest)
        self.assertEqual(m.integer_vars[23], 1)
        self.assertEqual(m.peak_pages, 6)

    def test_a_three_letter_extension_as_the_browser_needs(self) -> None:
        m = self.machine({"cobra.nxc": self.patch, "cobra.z80": self.game})
        failed, message = m.run('"Cobra.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(hashlib.md5(bytes(m.written[NEX])).hexdigest(), self.base_digest)

    def test_the_key_that_chose_is_not_left_pending(self) -> None:
        for keys, written in ((["enter"], NEX), (["5", "enter"], Z80)):
            m = self.machine({"patch.nxc": self.patch, self.game_name: self.game}, keys=keys)
            m.m.memory[H.FLAGS] = 0xFF
            failed, message = m.run('"patch.nxc"')
            self.assertFalse(failed, message)
            self.assertEqual(m.m.memory[H.FLAGS], 0xDF)
            self.assertIn(written, m.written)

    def test_game_found_under_the_patch_name_too(self) -> None:
        m = self.machine({"sub/cobra.nxc": self.patch, "sub/cobra.z80": self.game})
        failed, message = m.run('"sub/Cobra.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(hashlib.md5(bytes(m.written[NEX])).hexdigest(), self.base_digest)
        # and TGT1's name beside the patch comes first
        m = self.machine({"sub/cobra.nxc": self.patch, "sub/" + self.game_name: self.game})
        failed, message = m.run('"sub/Cobra.nxc"')
        self.assertFalse(failed, message)

    def test_trainers_equal_the_reference_and_differ_only_at_their_pokes(self) -> None:
        every = nxc.trainers(self.patch)
        self.assertEqual([t[1] for t in every],
                         ["Infinite lives", "Immunity", "Unlimited weaponry", "Infinite lives (alt)"])
        for chosen in ([1], [2], [3], [4], [1, 2], [1, 2, 3], [1, 4]):
            with self.subTest(chosen=chosen):
                keys = [str(c) for c in chosen] + ["enter"]
                m, failed, message = self.run_cobra(keys=keys)
                self.assertFalse(failed, message)
                self.assertEqual(m.clean(), [])
                out = bytes(m.written[NEX])
                self.assertEqual(out, nxc.apply(self.patch, game=self.game, chosen=chosen))
                offsets = {}
                at = 512
                for b in nxc.ORDER:
                    if self.source[18 + b]:
                        offsets[b] = at
                        at += 16384
                allowed = {offsets[b] + o for c in chosen for b, o, _ in every[c - 1][2]}
                differs = {i for i in range(len(out)) if out[i] != self.source[i]}
                self.assertTrue(differs <= allowed, f"changed bytes beyond the POKEs: {sorted(differs - allowed)}")
                self.assertTrue(differs)

    def test_space_starts_with_what_the_menu_shows(self) -> None:
        # SPACE after a choice must not undo it: the owner lost immunity that way, it seems.
        m, failed, message = self.run_cobra(keys=["2", "enter"])
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), nxc.apply(self.patch, game=self.game, chosen=["Immunity"]))
        m, failed, message = self.run_cobra(keys=["enter"])
        self.assertFalse(failed, message)
        self.assertEqual(hashlib.md5(bytes(m.written[NEX])).hexdigest(), self.base_digest)

    def test_menu_layout_exactly(self) -> None:
        pok = "NInfinite Lives\nZ 8 36515 183 0\nNImmunity\nZ 8 37915 201 0\nY\n"
        patch = nxc.import_pok(self.shipped, str(COBRA_GAME), pok, "Ocean, 1986")
        m, failed, message = self.run_cobra(patch, keys=["1", "enter"])
        self.assertFalse(failed, message)
        top = {0: " COBRA".ljust(28) + "////", 1: " Ocean, 1986", 3: "TRAINER", 5: row("2", "Immunity", "[OFF]"), 7: "OPTIONS",
               8: row("3", "Colour clash fix", "[ ON]"), 10: "ENTER play   BREAK exit"}
        self.assertEqual(m.screens[-2], screen({**top, 4: row("1", "Infinite lives", "[ ON]")}))
        self.assertEqual(m.screens[-3], screen({**top, 4: row("1", "Infinite lives", "[OFF]")}))
        self.assertEqual(bytes(m.written[NEX]), nxc.apply(patch, game=self.game, chosen=[1]))

    def test_credit_with_no_colour_set_has_no_colours_part(self) -> None:
        patch = nxc.set_credits(self.patch, self.game, patch_by="Jon Attree", colours_by="Someone")
        self.assertEqual(nxc.credit_line(patch), "Patch: Jon Attree")
        m, failed, message = self.run_cobra(patch)
        self.assertFalse(failed, message)
        self.assertEqual(hashlib.md5(bytes(m.written[NEX])).hexdigest(), self.base_digest)
        self.assertEqual(m.screens[1], screen({
            0: " COBRA".ljust(28) + "////", 1: " Ocean, 1986", 3: "TRAINER",
            4: row("1", "Infinite lives", "[OFF]"), 5: row("2", "Immunity", "[OFF]"),
            6: row("3", "Unlimited weaponry", "[OFF]"), 7: row("4", "Infinite lives (alt)", "[OFF]"),
            9: "OPTIONS", 10: row("5", "Colour clash fix", "[ ON]"), 12: "ENTER play   BREAK exit",
            21: "Patch: Jon Attree"}))                     # row 20, Colours:, only with a colour set offered
        self.assertNotIn("Someone", "\n".join(m.screens))

    def test_menu_without_trainers_or_publisher(self) -> None:
        m, failed, message = self.run_cobra(self.shipped, keys=["1", "enter"])
        self.assertFalse(failed, message)
        self.assertEqual(m.screens[-2], screen({0: " COBRA".ljust(28) + "////", 3: "OPTIONS",
                                                4: row("1", "Colour clash fix", "[OFF]"), 6: "ENTER play   BREAK exit"}))
        self.assertEqual(bytes(m.written[Z80]), self.game)

    def test_more_trainers_than_the_menu_holds_still_plays(self) -> None:
        pok = "".join(f"NT{n}\nZ 8 {40000 + n} 1 0\n" for n in range(10)) + "Y\n"
        patch = nxc.import_pok(self.shipped, str(COBRA_GAME), pok)
        m, failed, message = self.run_cobra(patch, keys=["8", "9", "enter"])  # the last, then the clash fix off
        self.assertFalse(failed, message)
        self.assertIn(row("8", "T7", "[ ON]"), m.screens[-2].split("\n"))
        self.assertNotIn("T8", m.screens[-2])
        self.assertIn(row("9", "Colour clash fix", "[OFF]"), m.screens[-2].split("\n"))
        self.assertEqual(bytes(m.written[Z80]), nxc.original_with_pokes(patch, self.game, [8]))

    def test_break_cancels(self) -> None:
        m, failed, message = self.run_cobra(keys=["caps+space"])
        self.assert_refused(m, failed, message, "Cancelled")

    def test_original_alone_is_the_game_untouched(self) -> None:
        m, failed, message = self.run_cobra(keys=["5", "enter"])
        self.assertFalse(failed, message)
        self.assertEqual(m.clean(), [])
        self.assertEqual(bytes(m.written[Z80]), self.game)
        self.assertNotIn(NEX, m.written)
        self.assertEqual(m.integer_vars[23], 2)
        self.assertEqual(m.peak_pages, 0)

    def test_original_with_a_trainer_equals_the_reference(self) -> None:
        for chosen in ([1], [2, 3]):
            with self.subTest(chosen=chosen):
                keys = [str(c) for c in chosen] + ["5", "enter"]
                m, failed, message = self.run_cobra(keys=keys)
                self.assertFalse(failed, message)
                self.assertEqual(m.clean(), [])
                out = bytes(m.written[Z80])
                self.assertEqual(out, nxc.original_with_pokes(self.patch, self.game, chosen))
                self.assertEqual(m.integer_vars[23], 2)
                # the same memory as the game, but for the POKEs
                path = Path(os.environ.get("TMPDIR", "/tmp")) / "orig_trainer.z80"
                path.write_bytes(out)
                banks = nxc.snapshot_banks(str(path))
                path.unlink()
                want = {b: bytearray(d) for b, d in nxc.Z80Snapshot(str(COBRA_GAME)).banks.items()}
                for c in chosen:
                    for b, o, v in nxc.trainers(self.patch)[c - 1][2]:
                        want[b][o] = v
                self.assertEqual({b: bytes(d) for b, d in want.items()}, banks)

    def test_original_with_a_trainer_refuses_the_wrong_game(self) -> None:
        wrong = bytearray(self.game)
        wrong[1000] ^= 1
        m, failed, message = self.run_cobra(keys=["1", "5", "enter"], game=bytes(wrong))
        self.assert_refused(m, failed, message, "Wrong game file for this patch")

    # ---- refusals

    def test_wrong_game_names_the_file(self) -> None:
        m, failed, message = self.run_cobra(game=b"not the game" * 100)
        self.assert_refused(m, failed, message, "Wrong game file for this patch")
        self.assertNotIn("zx0_decode", m.phase_ticks)
        text = m.printed.decode("latin-1")
        self.assertIn("Needs this game file:", text)
        self.assertIn(text_of(self.shipped, b"TGT1")["file"], text)
        print(f"\nWrong game: error {message!r}; printed: {text[text.find('Needs'):]!r}", flush=True)

    def test_one_flipped_bit_in_the_game(self) -> None:
        for position in (0, 1000, len(self.game) // 2, len(self.game) - 1):
            wrong = bytearray(self.game)
            wrong[position] ^= 0x10
            m, failed, message = self.run_cobra(game=bytes(wrong))
            self.assert_refused(m, failed, message, "Wrong game file for this patch")
            self.assertNotIn("zx0_decode", m.phase_ticks)

    def test_game_missing_names_the_file(self) -> None:
        m, failed, message = self.run_patch(self.patch, None)
        self.assertTrue(failed)
        self.assertEqual(message, "Game not beside the patch")
        self.assertIn(text_of(self.shipped, b"TGT1")["file"], m.printed.decode("latin-1"))
        self.assertEqual(m.clean(), [])
        self.assertEqual(m.screens[0], "\n".join(m.screen))    # no menu was shown

    def test_too_high_a_level(self) -> None:
        for level in (3, 4, 255):        # 2 is this loader's own level now
            patch = bytearray(self.patch)
            at = patch.index(b"OPT1") + 8
            patch[at] = level
            m, failed, message = self.run_cobra(bytes(patch))
            self.assert_refused(m, failed, message, "Patch needs a newer .NEXCLASH")

    def test_not_enough_ram(self) -> None:
        # The menu's page is taken first; the rebuild's own check then wants 6 more, and says only what it needs.
        for free in range(1, 7):
            m, failed, message = self.run_cobra(free_pages=free)
            self.assert_refused(m, failed, message, "Not enough free RAM: needs 48K")
            self.assertEqual(m.free_pages, free)
            self.assertGreater(len(m.screens), 2)              # past the menu
        m, failed, message = self.run_cobra(free_pages=7)
        self.assertFalse(failed, message)
        self.assertEqual(hashlib.md5(bytes(m.written[NEX])).hexdigest(), self.base_digest)

    def test_not_enough_ram_for_the_menu(self) -> None:
        m, failed, message = self.run_cobra(free_pages=0)
        self.assert_refused(m, failed, message, "Not enough free RAM for the menu")
        self.assertEqual(m.free_pages, 0)
        self.assertEqual(m.screens[0], "\n".join(m.screen))    # no menu was shown

    def test_truncated_patch(self) -> None:
        for length in list(range(0, 400, 13)) + list(range(400, len(self.patch), 211)) + [len(self.patch) - 1]:
            m, failed, message = self.run_cobra(self.patch[:length])
            self.assert_refused(m, failed, message)
            self.assertIn(message, ("Patch damaged: get it again", "Not a .nxc file"))
            self.assertNotIn("zx0_decode", m.phase_ticks)

    def probe_flips(self, binary=None, symbols=None, sample: int = 500) -> list[str]:
        """Flip bytes across the patch, leaving the keyed check to find them. Nothing is ever decompressed."""
        problems = []
        rng = random.Random(21)
        positions = list(range(0, 128)) + rng.sample(range(128, len(self.patch)), min(sample, len(self.patch) - 128))
        for position in positions:
            bad = bytearray(self.patch)
            bad[position] ^= rng.choice((1, 0x40, 0x80, 0xFF))
            m = self.machine({"patch.nxc": bytes(bad), self.game_name: self.game}, keys=["enter"],
                             binary=binary, symbols=symbols)
            try:
                failed, message = m.run('"patch.nxc"')
            except H.Hung as e:
                problems.append(f"flip at {position}: hung: {e}")
                continue
            where = f"flip at {position}"
            if not failed:
                problems.append(f"{where}: not refused")
            if NEX in m.written:
                problems.append(f"{where}: an output was left")
            if m.clean():
                problems.append(f"{where}: {m.clean()}")
            if "zx0_decode" in m.phase_ticks:
                problems.append(f"{where}: decompressed something ({message})")
        return problems

    def test_flipped_bytes_in_the_patch(self) -> None:
        self.assertEqual(self.probe_flips(), [])

    def probe_tamper(self, binary=None, symbols=None, sample: int = 250) -> list[str]:
        """Flip bytes and recompute the check, as someone with the game can: every decoder faces garbage. A run may
        be refused, or end with exactly the right file; nothing else, and nothing outside its buffers."""
        problems = []
        rng = random.Random(22)
        nonce, bl = nxc.blocks(self.patch)
        at = nxc.HEADER
        ranges = []
        for t, d in bl:
            if t in (b"NEX1", b"SIT1", b"BNK1"):
                ranges.append((at + 8, at + 8 + len(d)))
            at += 8 + len(d)
        positions = []
        for start, end in ranges:
            count = max(10, sample * (end - start) // sum(e - s for s, e in ranges))
            positions += [rng.randrange(start, end) for _ in range(count)]
        want = nxc.apply(self.patch, game=self.game)
        refused = exact = 0
        for position in positions:
            bad = rekey_at(self.patch, self.game, position, rng.choice((1, 2, 0x40, 0x80, 0xFF)))
            m = self.machine({"patch.nxc": bad, self.game_name: self.game}, binary=binary, symbols=symbols)
            where = f"tamper at {position}"
            try:
                failed, message = m.run('"patch.nxc"')
            except H.Hung as e:
                problems.append(f"{where}: hung: {e}")
                continue
            if failed:
                refused += 1
                if NEX in m.written:
                    problems.append(f"{where}: refused but left an output")
            else:
                exact += 1
                if bytes(m.written[NEX]) != want:
                    problems.append(f"{where}: wrong output accepted")
            if m.clean():
                problems.append(f"{where}: {m.clean()}")
        self.tamper_counts = (refused, exact, len(positions))
        return problems

    def test_tampered_streams_with_a_good_crc(self) -> None:
        self.assertEqual(self.probe_tamper(), [])
        print(f"\nTampered with CRC recomputed: {self.tamper_counts[2]} runs, {self.tamper_counts[0]} refused, "
              f"{self.tamper_counts[1]} still exact, no out-of-range writes", flush=True)

    def forge_bank(self, plain_claim: int, stream_plain: bytes | None = None, stream: bytes | None = None) -> bytes:
        """The first BNK1 replaced with one that claims plain_claim bytes and holds the given stream."""
        def edit(bl, st):
            for entry in bl:
                if entry[0] == b"BNK1":
                    bank = entry[1][0]
                    data = stream if stream is not None else nxc.zx0(stream_plain)
                    entry[1] = struct.pack("<BH", bank, plain_claim) + st.block(b"BNK1", bank)(data)
                    return
        return rekey(self.patch, self.game, edit)

    def test_streams_that_try_to_escape(self) -> None:
        rng = random.Random(8)
        noise = bytes(rng.randrange(256) for _ in range(6000))
        cases = {
            "longer than it claims": self.forge_bank(100, noise),
            "shorter than it claims": self.forge_bank(5000, noise[:50]),
            "past the whole bank, by copying": self.forge_bank(16384, bytes(40000)),
            "past the whole bank, literally": self.forge_bank(16384, noise * 4),
            "a copy from before the buffer": self.forge_bank(3, stream=copy_before_start()),
            "the same, by a broken stream": self.forge_bank(1000, stream=bytes((0xCA, 0x58, 0x00, 0x00, 0x00))),
            "a length of over 16 bits": self.forge_bank(1000, stream=bytes(40)),
            "no end marker": self.forge_bank(100, stream=nxc.zx0(noise[:100])[:-1]),
            "bytes after the end marker": self.forge_bank(100, stream=nxc.zx0(noise[:100]) + b"\0"),
            "claims more than a bank": self.forge_bank(16385, noise),
            "empty, claims some": self.forge_bank(100, stream=b""),
        }
        for name, patch in cases.items():
            with self.subTest(name):
                with self.assertRaises(nxc.Wrong):
                    nxc.apply(patch, game=self.game)
                m = self.machine({"patch.nxc": patch, self.game_name: self.game})
                failed, message = m.run('"patch.nxc"')
                self.assert_refused(m, failed, message, "Patch damaged: get it again")

    def forge_table(self, table: bytes) -> bytes:
        def edit(bl, st):
            for entry in bl:
                if entry[0] == b"SIT1":
                    entry[1] = st.block(b"SIT1")(nxc.zx0(table))
        return rekey(self.patch, self.game, edit)

    def test_site_tables_that_try_to_escape(self) -> None:
        site = lambda b, o, data: struct.pack("<BHH", b, o, len(data)) + data  # noqa: E731
        cases = {
            "a bank the game lacks": struct.pack("<H", 1) + site(7, 0, b"xx"),
            "a bank out of range": struct.pack("<H", 1) + site(200, 0, b"xx"),
            "past the end of the bank": struct.pack("<H", 1) + site(5, 16383, b"xx"),
            "an offset past the bank": struct.pack("<H", 1) + site(5, 0xFFFF, b"x"),
            "length wraps around": struct.pack("<BHHH", 5, 5, 0xFFFF, 0) + b"xxxx",
            "more sites than there are": struct.pack("<H", 2) + site(5, 0, b"xx"),
            "bytes left over": struct.pack("<H", 1) + site(5, 0, b"xx") + b"z",
            "too short for its count": b"\x01",
            "runs past the table": struct.pack("<HBHH", 1, 5, 0, 100) + b"xx",
            "bigger than the loader holds": struct.pack("<H", 1) + site(5, 0, b"y" * 16384) * 2 + bytes(100),
        }
        for name, table in cases.items():
            with self.subTest(name):
                patch = self.forge_table(table)
                m = self.machine({"patch.nxc": patch, self.game_name: self.game})
                failed, message = m.run('"patch.nxc"')
                self.assert_refused(m, failed, message, "Patch damaged: get it again")
                self.assertNotIn(NEX, m.written)
                self.assertEqual(m.bad_writes, [])

    def test_forged_blocks(self) -> None:
        def header(data):
            def edit(bl, st):
                for entry in bl:
                    if entry[0] == b"NEX1":
                        entry[1] = st.block(b"NEX1")(nxc.zx0(data))
            return edit

        def twice(bl, st):
            for entry in list(bl):
                if entry[0] == b"BNK1":
                    bl.append([entry[0], entry[1]])
                    return

        def bad_bank(bl, st):
            for entry in bl:
                if entry[0] == b"BNK1":
                    entry[1] = bytes((112,)) + entry[1][1:]
                    return

        def drop(tag):
            def edit(bl, st):
                bl[:] = [e for e in bl if e[0] != tag]
            return edit

        def empty_with_data(bl, st):
            for entry in bl:
                if entry[0] == b"BNK1":
                    entry[1] = struct.pack("<BH", entry[1][0], 0) + b"junk"
                    return

        head = bytearray(self.source[:512])
        head[18 + 50] = 1
        cases = {
            "a header too long": header(self.source[:600]),
            "a header too short": header(self.source[:400]),
            "a header listing a bank nothing supplies": header(bytes(head)),
            "the same bank twice": twice,
            "a bank number too high": bad_bank,
            "no data promised, data given": empty_with_data,
            "no NEX1": drop(b"NEX1"),
            "no SIT1": drop(b"SIT1"),
            "no TGT1": drop(b"TGT1"),
            "no INF1": drop(b"INF1"),
            "no OPT1": drop(b"OPT1"),
        }
        for name, edit in cases.items():
            with self.subTest(name):
                patch = rekey(self.patch, self.game, edit)
                m = self.machine({"patch.nxc": patch, self.game_name: self.game})
                failed, message = m.run('"patch.nxc"')
                self.assertTrue(failed, name)
                self.assertEqual(m.clean(), [])
                self.assertNotIn(NEX, m.written)

    def test_a_wrong_result_leaves_no_file(self) -> None:
        def edit(bl, st):
            for entry in bl:
                if entry[0] == b"BNK1":
                    bank, n = struct.unpack_from("<BH", entry[1])
                    plain = bytearray(nxc.unzx0(st.block(b"BNK1", bank)(entry[1][3:]), n))
                    plain[0] ^= 1
                    entry[1] = entry[1][:3] + st.block(b"BNK1", bank)(nxc.zx0(bytes(plain)))
                    return
        patch = rekey(self.patch, self.game, edit)
        m = self.machine({"patch.nxc": patch, self.game_name: self.game})
        failed, message = m.run('"patch.nxc"')
        self.assertTrue(failed)
        self.assertEqual(message, "Rebuild failed: patch damaged")
        self.assertIn(NEX, m.deleted)
        self.assertNotIn(NEX, m.written)
        self.assertEqual(m.clean(), [])

    def test_read_and_write_failures_mid_run(self) -> None:
        m0, _, _ = self.run_cobra()
        for n in range(1, m0.reads + 1, max(1, m0.reads // 24)):
            m, failed, message = self.run_cobra(fail_read=n)
            self.assertTrue(failed, f"read {n}")
            self.assertEqual(m.clean(), [])
            self.assertNotIn(NEX, m.written)
        for n in range(1, m0.writes + 1):
            m, failed, message = self.run_cobra(fail_write=n)
            self.assertTrue(failed, f"write {n}")
            self.assertEqual(message, "Cannot write to /tmp")
            self.assertEqual(m.clean(), [])
            self.assertIn(NEX, m.deleted)

    def test_unknown_blocks_and_any_order(self) -> None:
        def add(bl, st):
            bl.insert(3, [b"XYZ1", b"hello"])
            bl.append([b"BNK2", bytes(40)])
            bl.append([b"KEY2", bytes(20)])
            bl.append([b"L2B1", bytes(7000)])
            banks = [e for e in bl if e[0] == b"BNK1"]
            others = [e for e in bl if e[0] != b"BNK1"]
            bl[:] = others + banks[::-1]
        patch = rekey(self.patch, self.game, add)
        m = self.machine({"patch.nxc": patch, self.game_name: self.game})
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(hashlib.md5(bytes(m.written[NEX])).hexdigest(), self.base_digest)

    def test_forged_trainers(self) -> None:
        good = nxc.trn1("A cheat", [(2, 100, 7)])
        cases = {
            "a POKE past its bank": bytes((0, 3)) + b"abc" + bytes((1,)) + struct.pack("<BHB", 2, 16384, 1),
            "a bank out of range": bytes((0, 3)) + b"abc" + bytes((1,)) + struct.pack("<BHB", 112, 0, 1),
            "a bank the build lacks": bytes((0, 3)) + b"abc" + bytes((1,)) + struct.pack("<BHB", 60, 0, 1),
            "a count too high": bytes((0, 3)) + b"abc" + bytes((2,)) + struct.pack("<BHB", 2, 0, 1),
            "a count too low": bytes((0, 3)) + b"abc" + bytes((1,)) + struct.pack("<BHB", 2, 0, 1) * 2,
            "no POKEs": bytes((0, 3)) + b"abc" + bytes((0,)),
            "no name": bytes((0, 0, 1)) + struct.pack("<BHB", 2, 0, 1),
            "a name too long": bytes((0, 26)) + b"n" * 26 + bytes((1,)) + struct.pack("<BHB", 2, 0, 1),
            "too short": bytes((0,)),
            "an empty block": b"",
        }
        for name, data in cases.items():
            with self.subTest(name):
                patch = rekey(self.patch, self.game, lambda bl, st: bl.insert(1, [b"TRN1", data]))
                m = self.machine({"patch.nxc": patch, self.game_name: self.game}, keys=["1", "enter"])
                failed, message = m.run('"patch.nxc"')
                self.assert_refused(m, failed, message, "Patch damaged: get it again")
        patch = rekey(self.patch, self.game, lambda bl, st: bl.insert(1, [b"TRN1", good]))
        m = self.machine({"patch.nxc": patch, self.game_name: self.game}, keys=["enter"])
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(m.clean(), [])

    def test_too_many_pokes_chosen(self) -> None:
        pokes = [(2, n, 1) for n in range(100)]
        def add(bl, st):
            bl.insert(1, [b"TRN1", nxc.trn1("Big one", pokes)])
            bl.insert(1, [b"TRN1", nxc.trn1("Big two", pokes)])
        patch = rekey(self.shipped, self.game, add)
        m = self.machine({"patch.nxc": patch, self.game_name: self.game}, keys=["1", "2", "enter"])
        failed, message = m.run('"patch.nxc"')
        self.assert_refused(m, failed, message, "Too many trainers on")
        m = self.machine({"patch.nxc": patch, self.game_name: self.game}, keys=["1", "enter"])
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), nxc.apply(patch, game=self.game, chosen=[1]))

    # ---- negative controls: a broken loader must fail these same checks

    BROKEN = {
        "no keyed check": [("""        or      a
        jp      nz,bad_patch
        inc     hl
        djnz    .cmp""", """        or      a
        nop
        nop
        nop
        inc     hl
        djnz    .cmp""")],
        "no key check": [("""        cp      (hl)
        jr      nz,.next
        inc     hl
        inc     de
        djnz    .chk""", """        cp      (hl)
        nop
        nop
        inc     hl
        inc     de
        djnz    .chk""")],
        "no room check in ZX0": [(""".room:  push    af
        ld      a,b""", """.room:  ret
        ld      a,b""")],
        "no offset check in ZX0": [("""        jr      nc,.bad
        ld      hl,(zx_last)""", """        nop
        nop
        ld      hl,(zx_last)""")],
        "no site bound": [("""        ld      bc,BANK_SIZE+1
        or      a
        sbc     hl,bc
        jp      nc,bad_patch""", """        ld      bc,BANK_SIZE+1
        or      a
        sbc     hl,bc
        nop
        nop
        nop""")],
        "no final CRC": [("""        cp      (hl)
        jr      nz,.wrong
        inc     hl
        inc     de
        djnz    .crc""", """        cp      (hl)
        nop
        nop
        inc     hl
        inc     de
        djnz    .crc""")],
        "POKEs forgotten": [("""        call    crc_update
        call    apply_pokes""", """        call    crc_update
        nop
        nop
        nop""")],
        "POKEs in the CRC": [("""        call    crc_update
        call    apply_pokes""", """        call    apply_pokes
        call    crc_update""")],
        "pages not freed": [("""        ld      hl,BANK_FREE
        exx
        ld      de,IDE_BANK
        ld      c,7
        rst     $08
        db      M_P3DOS
        jr      .keep""", """        jr      .keep""")],
    }

    def control_fails(self, name: str) -> bool:
        """True when the broken loader is caught by the checks this class relies on."""
        binary, symbols = H.assemble(self.BROKEN[name])
        files = {"patch.nxc": self.patch, self.game_name: self.game}
        if name == "no keyed check":
            return bool(self.probe_flips(binary, symbols, sample=60))
        if name == "no key check":
            wrong = bytearray(self.game)
            wrong[99] ^= 1
            m = self.machine({"patch.nxc": self.patch, self.game_name: bytes(wrong)}, binary=binary, symbols=symbols)
            failed, message = m.run('"patch.nxc"')
            return message != "Wrong game file for this patch"
        if name == "no room check in ZX0":
            # A table far bigger than the three pages: unchecked, it runs on into the caller's memory.
            site = struct.pack("<BHH", 5, 0, 16384) + b"y" * 16384
            forged = self.forge_table(struct.pack("<H", 3) + site * 3)
            m = self.machine({"patch.nxc": forged, self.game_name: self.game}, binary=binary, symbols=symbols)
            try:
                failed, message = m.run('"patch.nxc"')
            except H.Hung:
                return True
            return not failed or bool(m.clean())
        if name == "no offset check in ZX0":
            forged = self.forge_bank(3, stream=copy_before_start())
            m = self.machine({"patch.nxc": forged, self.game_name: self.game}, binary=binary, symbols=symbols)
            failed, message = m.run('"patch.nxc"')
            return message != "Patch damaged: get it again"
        if name == "no final CRC":
            def edit(bl, st):
                for entry in bl:
                    if entry[0] == b"BNK1":
                        bank, n = struct.unpack_from("<BH", entry[1])
                        plain = bytearray(nxc.unzx0(st.block(b"BNK1", bank)(entry[1][3:]), n))
                        plain[0] ^= 1
                        entry[1] = entry[1][:3] + st.block(b"BNK1", bank)(nxc.zx0(bytes(plain)))
                        return
            m = self.machine({"patch.nxc": rekey(self.patch, self.game, edit), self.game_name: self.game},
                             binary=binary, symbols=symbols)
            failed, message = m.run('"patch.nxc"')
            return not failed
        if name == "no site bound":
            site = struct.pack("<H", 1) + struct.pack("<BHH", 5, 16383, 2) + b"xx"
            m = self.machine({"patch.nxc": self.forge_table(site), self.game_name: self.game},
                             binary=binary, symbols=symbols)
            failed, message = m.run('"patch.nxc"')
            return message != "Patch damaged: get it again" or bool(m.bad_writes)
        if name in ("POKEs forgotten", "POKEs in the CRC"):
            m = self.machine(files, keys=["1", "enter"], binary=binary, symbols=symbols)
            failed, message = m.run('"patch.nxc"')
            out = bytes(m.written.get(NEX, b""))
            return out != nxc.apply(self.patch, game=self.game, chosen=[1])
        if name == "pages not freed":
            m = self.machine(files, binary=binary, symbols=symbols)
            m.run('"patch.nxc"')
            return bool(m.clean())
        raise AssertionError(name)

    def test_negative_controls(self) -> None:
        caught = []
        for name in self.BROKEN:
            with self.subTest(name):
                self.assertTrue(self.control_fails(name), f"a loader with {name} passed")
                caught.append(name)
        print(f"\nNegative controls caught: {len(caught)} of {len(self.BROKEN)}: {', '.join(caught)}", flush=True)

    # ---- measures

    def test_measure(self) -> None:
        import nexclash_harness
        m = H.Machine(self.binary, self.symbols, {"patch.nxc": self.patch, self.game_name: self.game})
        m.set_phases(["work_begin", "absorb_game", "check_file", "load_bank_index", "create_out", "done"])
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        t = m.phase_ticks
        mhz = H.SPEED_MHZ * 1e6
        absorb = t["absorb_game"]
        crc = t["check_file"]
        setup = t["load_bank_index"]
        write = t["create_out"]
        total = absorb + crc + setup + write
        code_end = self.symbols["code_end"]
        # high-water marks, from what changed in the dot command's own 8K
        stack_low = self.symbols["stack_top"]
        for a in range(self.symbols["stack_floor"], 0x4000):
            if m.m.memory[a] != H.junk(a):
                stack_low = a
                break
        touched = 0
        for page in m.ever_allocated:
            data = m.pages.get(page, b"")
            fresh = H.Machine.fill(page)
            touched += sum(1 for i in range(len(data)) if data[i] != fresh[i])
        print(f"\nMeasure, Cobra, {len(self.game)} byte game, {len(m.written[NEX])} byte .nex, T-states at 28 MHz, "
              f"no wait states, no file I/O:\n"
              f"  absorb and KEY1 {absorb:,} = {absorb / mhz:.3f} s\n"
              f"  keyed check of the patch {crc:,} = {crc / mhz:.3f} s\n"
              f"  index, header, sites {setup:,} = {setup / mhz:.3f} s\n"
              f"  decompress, CRC and write {write:,} = {write / mhz:.3f} s\n"
              f"  total {total:,} = {total / mhz:.3f} s\n"
              f"  file {len(self.binary)} bytes: 8192, then {self.symbols['ov_size']} read after the menu, tape parts "
              f"{self.symbols['tape1_size']}, {self.symbols['tape2_size']} and {self.symbols['tape3_size']}, the menu's "
              f"{self.symbols['mp_size']}, the menu .nex writer's {self.symbols['mnx_size']}; code and data end at {code_end:#06x}, variables to "
              f"{self.symbols['vars_end']:#06x}\n"
              f"  stack in the 8K reached {stack_low:#06x}, {0x4000 - stack_low} bytes\n"
              f"  allocated {m.peak_pages} pages = {m.peak_pages * 8}K, of which {touched} bytes changed; "
              f"peak RAM 8K + 8K for the menu + {m.peak_pages * 8}K", flush=True)
        parts = ("ov_size", "tape1_size", "tape2_size", "tape3_size", "mp_size", "mnx_size")
        self.assertEqual(len(self.binary), H.FIRST_PART + sum(self.symbols[n] for n in parts))
        self.assertEqual(m.peak_pages, 6)
        self.assertGreater(stack_low, self.symbols["stack_floor"], "the stack reached the variables below it")


# ------------------------------------------------------------------ the menu's choices


def chunk_of(*changes: tuple[int, bytes]) -> bytes:
    """A bank's chunk: the bitmap of the offsets these runs (offset, bytes) cover, then their bytes."""
    bitmap = bytearray(nxc.BITMAP)
    places = {}
    for offset, data in changes:
        for n, value in enumerate(data):
            bitmap[(offset + n) >> 3] |= 0x80 >> ((offset + n) & 7)
            places[offset + n] = value
    return bytes(bitmap) + bytes(places[o] for o in sorted(places))


def set_body(st, stream: int, crc: int, chunks: list[tuple[int, bytes]]) -> bytes:
    """What follows a set's name: its CRC, then each (bank, plain chunk), in the order given, as someone with the game can write it."""
    out = nxc.set_use(st, stream, nxc.SET_CRC_INDEX)(struct.pack("<I", crc))
    for bank, chunk in chunks:
        packed = nxc.set_use(st, stream, bank)(nxc.zx0(chunk))
        out += struct.pack("<BH", bank, len(packed)) + packed
    return out


def set_frame(st, stream: int, crc: int, bank: int, packed: bytes) -> bytes:
    """A set of one chunk whose stream is exactly these bytes."""
    enc = nxc.set_use(st, stream, bank)(packed)
    return nxc.set_use(st, stream, nxc.SET_CRC_INDEX)(struct.pack("<I", crc)) + struct.pack("<BH", bank, len(enc)) + enc


def painted(nex: bytes, rng: random.Random, banks, runs: int = 30) -> bytes:
    """A colour set's build: the same header and length, runs of bytes changed in the given banks."""
    head = 512
    offsets = {}
    for b in nxc.ORDER:
        if nex[18 + b]:
            offsets[b] = head
            head += 16384
    out = bytearray(nex)
    for _ in range(runs):
        b = rng.choice(banks)
        at = rng.randrange(16300)
        n = rng.randrange(1, 60)
        out[offsets[b] + at:offsets[b] + at + n] = bytes(rng.randrange(256) for _ in range(n))
    return bytes(out)


class Choices:
    """What every patch with colour sets must do, whichever game it is for. A subclass sets patch, game, game_name, sets
    (names in the file's order), with one trainer first. The menu offers the first set, as ON."""

    patch: bytes
    game: bytes
    game_name: str
    sets: list[str]

    def run_it(self, keys, patch=None, **options):
        m = self.machine({"patch.nxc": self.patch if patch is None else patch, self.game_name: self.game}, keys=keys,
                         **options)
        failed, message = m.run('"patch.nxc"')
        return m, failed, message

    def lines(self):
        count = len(nxc.trainers(self.patch))
        return "1", str(count + 1), str((count + 2) % 10)

    def want(self, fix: bool, enhanced: int, trainer: bool) -> bytes:
        chosen = [1] if trainer else None
        if not fix:
            return nxc.original_with_pokes(self.patch, self.game, chosen) if trainer else self.game
        return nxc.apply(self.patch, game=self.game, colours=self.sets[0] if enhanced else None, chosen=chosen)

    def test_every_combination(self) -> None:
        one, fix_key, set_key = self.lines()
        outputs = set()
        for fix in (True, False):
            for which in (0, 1):
                for trainer in (False, True):
                    # With the fix off a chosen set must make no difference: choose it first, then turn the fix off.
                    keys = ([one] if trainer else []) + [set_key] * which + ([] if fix else [fix_key]) + ["enter"]
                    with self.subTest(fix=fix, which=which, trainer=trainer):
                        m, failed, message = self.run_it(keys)
                        self.assertFalse(failed, message)
                        self.assertEqual(m.clean(), [])
                        name = NEX if fix else Z80
                        self.assertEqual(list(m.written), [name])
                        got = bytes(m.written[name])
                        self.assertEqual(got, self.want(fix, which, trainer))
                        outputs.add(got)
                        self.assertEqual(m.integer_vars[23], 1 if fix else 2)
                        if fix:
                            self.assertEqual(m.peak_pages, 9 if which else 6)
                        else:
                            self.assertEqual(m.peak_pages, 6 if trainer else 0)
        # On: enhanced off and on, with and without. Off: the game, and the game with the trainer.
        self.assertEqual(len(outputs), 6)

    def test_space_starts_with_what_the_menu_shows(self) -> None:
        one, fix_key, set_key = self.lines()
        for keys, fix, which, trainer in (
                (["enter"], True, 0, False),
                ([set_key, "enter"], True, 1, False),
                ([one, set_key, "enter"], True, 1, True),
                ([one, "enter"], True, 0, True),
                ([fix_key, "enter"], False, 0, False),
                ([one, fix_key, "enter"], False, 0, True)):
            with self.subTest(keys=keys):
                m, failed, message = self.run_it(keys)
                self.assertFalse(failed, message)
                self.assertEqual(m.clean(), [])
                self.assertEqual(bytes(m.written[NEX if fix else Z80]), self.want(fix, which, trainer))

    def test_enhanced_is_ignored_with_the_fix_off_and_the_choice_kept(self) -> None:
        one, fix_key, set_key = self.lines()
        # Its key does nothing with the fix off.
        m, failed, message = self.run_it([fix_key, set_key, set_key, "enter"])
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[Z80]), self.game)
        self.assertEqual(m.peak_pages, 0)
        self.assertIn(val("Enhanced colours", "[N/A]"), m.screens[-2])
        self.assertEqual(len(m.screens), 6)          # before, default, fix off, its key twice, after
        # So back on: still off.
        m, failed, message = self.run_it([fix_key, set_key, fix_key, "enter"])
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), self.want(True, 0, False))
        # A choice made first survives the fix going off and on, and is shown again.
        m, failed, message = self.run_it([set_key, fix_key, fix_key, "enter"])
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), self.want(True, 1, False))
        shown = "[ ON]" if len(self.sets) == 1 else f"[{self.sets[0][:12]}]"
        self.assertIn(val("Enhanced colours", shown), m.screens[-2])
        self.assertIn(val("Enhanced colours", "[N/A]"), m.screens[-3])
        self.assertIn(val("Enhanced colours", shown), m.screens[-4])

    def test_the_key_steps_through_what_there_is(self) -> None:
        one, fix_key, set_key = self.lines()
        turn = len(self.sets) + 1
        m, failed, message = self.run_it([set_key] * (turn + 1) + ["enter"])
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), self.want(True, 1, False))
        shown = [next(line for line in screen.split("\n") if "Enhanced colours" in line)[2:].split("colours", 1)[1].strip()
                 for screen in m.screens[1:turn + 3]]
        between = ["[ ON]"] if len(self.sets) == 1 else ["[" + name[:12] + "]" for name in self.sets]
        self.assertEqual(shown, ["[OFF]"] + between + ["[OFF]"] + between[:1])
        if len(self.sets) == 1:
            self.assertNotIn(self.sets[0], "\n".join(m.screens))

    def test_the_credit_is_not_on_the_menu(self) -> None:
        m, failed, message = self.run_it(["enter"])
        text = "\n".join(m.screens)
        self.assertNotIn("Bleugh", text)
        self.assertNotIn("SPACE", text)

    def test_not_enough_ram_for_a_set(self) -> None:
        _, _, set_key = self.lines()
        for free in (7, 9):                              # the menu's page, then the rebuild's
            m, failed, message = self.run_it([set_key, "enter"], free_pages=free)
            self.assert_refused(m, failed, message, "Needs 72K free RAM")
            self.assertEqual(m.free_pages, free)
        m, failed, message = self.run_it(["enter"], free_pages=7)
        self.assertFalse(failed, message)
        m, failed, message = self.run_it([set_key, "enter"], free_pages=10)
        self.assertFalse(failed, message)

    def test_flipped_bytes_in_a_set_are_refused_whatever_is_chosen(self) -> None:
        _, _, set_key = self.lines()
        at = nxc.HEADER
        ranges = []
        for t, d in nxc.blocks(self.patch)[1]:
            if t == b"SET2":
                ranges.append((at + 8, at + 8 + len(d)))
            at += 8 + len(d)
        rng = random.Random(31)
        for start, end in ranges:
            for position in [start, start + 1, start + 2, end - 1] + [rng.randrange(start, end) for _ in range(6)]:
                bad = bytearray(self.patch)
                bad[position] ^= rng.choice((1, 0x40, 0x80, 0xFF))
                m, failed, message = self.run_it([set_key, "enter"], patch=bytes(bad))
                self.assert_refused(m, failed, message, "Patch damaged: get it again")
                self.assertNotIn("zx0_decode", m.phase_ticks)

    def forge_set(self, chunks=None, crc: int | None = None, stream: bytes | None = None, raw: bytes | None = None, index: int = 0) -> bytes:
        """The first set with other chunks, and a good file CRC: what someone with the game can do. chunks: (bank, plain).
        stream: one chunk for the first listed bank with exactly these bytes. raw: all that follows the name, unencrypted as given."""
        base = nxc.apply(self.patch, game=self.game)
        a_bank = next(b for b in nxc.ORDER if base[18 + b])
        crc = zlib.crc32(base) if crc is None else crc

        def edit(bl, st):
            for entry in bl:
                if entry[0] == b"SET2":
                    fixed = entry[1][:nxc.SET_FIXED + entry[1][4]]
                    if raw is not None:
                        body = raw
                    elif stream is not None:
                        body = set_frame(st, index, crc, a_bank, stream)
                    else:
                        body = set_body(st, index, crc, chunks or [])
                    entry[1] = bytes((index,)) + fixed[1:] + body
                    return
        return rekey(self.patch, self.game, edit)

    def refused_by_both(self, patch: bytes) -> None:
        _, _, set_key = self.lines()
        with self.assertRaises(nxc.Wrong):
            nxc.apply(patch, game=self.game, colours=self.sets[0])
        m, failed, message = self.run_it([set_key, "enter"], patch=patch)
        self.assert_refused(m, failed, message)
        self.assertIn(message, ("Patch damaged: get it again", "Rebuild failed: patch damaged"))
        self.assertEqual(m.bad_writes, [])

    def test_corrupted_set_chunks(self) -> None:
        base = nxc.apply(self.patch, game=self.game)
        listed = [b for b in nxc.ORDER if base[18 + b]]
        a_bank, later = listed[0], listed[1]
        no_bank = next(b for b in nxc.ORDER if not base[18 + b])
        good = chunk_of((100, b"xy"))
        noise = bytes(random.Random(1).randrange(256) for _ in range(30000))
        full = chunk_of((0, noise[:16384]))
        cases = {
            "a bank the build lacks": [(no_bank, good)],
            "a bank out of range": [(200, good)],
            "the last bank out of range": [(255, good)],
            "banks against .nex order": [(later, good), (a_bank, good)],
            "a bank given twice": [(a_bank, good), (a_bank, good)],
            "one good chunk and one for a bank the build lacks": [(a_bank, good), (no_bank, good)],
            "a bitmap and nothing": [(a_bank, bytes(nxc.BITMAP))],
            "a bitmap with no bits, and a byte": [(a_bank, bytes(nxc.BITMAP) + b"x")],
            "shorter than a bitmap": [(a_bank, bytes(100))],
            "one bit more than its bytes": [(a_bank, good[:-1])],
            "one byte more than its bits": [(a_bank, good + b"x")],
            "every bit set, a byte short": [(a_bank, full[:-1])],
            "every bit set, a byte over": [(a_bank, full + b"x")],
            "bigger than a chunk can be": [(a_bank, full + noise[:4000])],
            "the wrong CRC": [],
            "changes the CRC does not know of": [(a_bank, chunk_of((3, bytes((base[512 + 3] ^ 1,)))))],
        }
        for name, chunks in cases.items():
            with self.subTest(name):
                self.refused_by_both(self.forge_set(chunks, crc=zlib.crc32(base) ^ 1 if name == "the wrong CRC" else None))

    def test_corrupted_set_streams(self) -> None:
        noise = bytes(random.Random(2).randrange(256) for _ in range(40000))
        base = nxc.apply(self.patch, game=self.game)
        crc = zlib.crc32(base)
        a_bank = next(b for b in nxc.ORDER if base[18 + b])
        cases = {
            "far too long": nxc.zx0(noise),
            "a copy from before the buffer": copy_before_start(),
            "broken": bytes((0xCA, 0x58, 0x00, 0x00, 0x00)),
            "a length of over 16 bits": bytes(40),
            "no end marker": nxc.zx0(noise[:100])[:-1],
            "bytes after the end marker": nxc.zx0(noise[:100]) + b"\0",
            "empty": b"",
        }
        for name, stream in cases.items():
            with self.subTest(name):
                self.refused_by_both(self.forge_set(stream=stream))
        # The framing itself, with the check value good.
        def framed(body):
            return lambda st: nxc.set_use(st, 0, nxc.SET_CRC_INDEX)(struct.pack("<I", crc)) + body
        for name, body in {"no CRC": None, "part of a CRC": 2, "part of a chunk's head": b"\5", "a head and no more": struct.pack("<BH", a_bank, 0),
                           "a stream past the block": struct.pack("<BH", a_bank, 40) + b"zz"}.items():
            with self.subTest(name):
                def edit(bl, st, body=body):
                    for entry in bl:
                        if entry[0] == b"SET2":
                            fixed = entry[1][:nxc.SET_FIXED + entry[1][4]]
                            entry[1] = bytes((0,)) + fixed[1:] + (b"" if body is None else b"zz" if body == 2 else framed(body)(st))
                            return
                self.refused_by_both(rekey(self.patch, self.game, edit))

    def test_corrupted_set_blocks_are_refused_before_the_menu(self) -> None:
        def with_data(data):
            def edit(bl, st):
                for entry in bl:
                    if entry[0] == b"SET2":
                        entry[1] = data
                        return
            return edit
        for name, data in {"an empty block": b"", "one byte": b"\0", "no name": b"\0\1\1\1\0zzzz",
                           "a name too long": b"\0\1\1\1\x1a" + b"n" * 26 + b"zzzz", "a name past the block": b"\0\1\1\1\x05ab",
                           "a name of 25, past the block": b"\0\1\1\1\x19" + b"n" * 24}.items():
            with self.subTest(name):
                patch = rekey(self.patch, self.game, with_data(data))
                with self.assertRaises(nxc.Wrong):
                    nxc.apply(patch, game=self.game)
                m, failed, message = self.run_it(["enter"], patch=patch)
                self.assert_refused(m, failed, message, "Patch damaged: get it again")
                self.assertEqual(m.screens[0], "\n".join(m.screen))    # no menu was shown

    def test_a_set_in_a_damaged_state_does_not_matter_until_chosen(self) -> None:
        patch = self.forge_set(stream=b"nonsense")          # and it is not read at all
        m, failed, message = self.run_it(["enter"], patch=patch)
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), self.want(True, 0, False))

    def test_tampered_sets_with_a_good_crc(self) -> None:
        _, _, set_key = self.lines()
        at = nxc.HEADER
        start = end = None
        for t, d in nxc.blocks(self.patch)[1]:
            if t == b"SET2":
                start, end = at + 8 + nxc.SET_FIXED + d[4], at + 8 + len(d)   # its CRC, then its chunks' heads and streams
                break
            at += 8 + len(d)
        rng = random.Random(23)
        want = nxc.apply(self.patch, game=self.game, colours=self.sets[0])
        refused = 0
        for _ in range(60):
            position = rng.randrange(start, end)
            bad = rekey_at(self.patch, self.game, position, rng.choice((1, 2, 0x40, 0x80, 0xFF)))
            m, failed, message = self.run_it([set_key, "enter"], patch=bad)
            where = f"tamper at {position}"
            self.assertEqual(m.clean(), [], where)
            if failed:
                refused += 1
                self.assertNotIn(NEX, m.written, where)
            else:
                self.assertEqual(bytes(m.written[NEX]), want, where)
        self.assertGreater(refused, 50)

    def test_a_later_version_of_the_block_is_skipped(self) -> None:
        def add(bl, st):
            bl.append([b"SET3", b"\0\1\1\1\x03xyzjunk"])
        patch = rekey(self.patch, self.game, add)
        one, fix_key, set_key = self.lines()
        m, failed, message = self.run_it([set_key, "enter"], patch=patch)
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), self.want(True, 1, False))
        self.assertNotIn("xyz", "\n".join(m.screens))

    def test_write_failures_with_a_set_leave_no_file(self) -> None:
        _, _, set_key = self.lines()
        for n in (1, 2, 3):
            m, failed, message = self.run_it([set_key, "enter"], fail_write=n)
            self.assertTrue(failed)
            self.assertEqual(message, "Cannot write to /tmp")
            self.assertEqual(m.clean(), [])
            self.assertIn(NEX, m.deleted)

    # ---- negative controls: a broken loader must fail these same checks

    ROOM = ('db "patch and your own copy.",13', 'db "p",13')     # the code nearly fills its room: a control may need more

    SET_BROKEN = {
        "the set never applied": [("""        call    apply_sets
        ld      hl,WORK
""", """        nop
        nop
        nop
        ld      hl,WORK
""")],
        "the output's CRC not checked": [("""        ld      hl,crc
        ld      de,want
        call    check_result
""", """        ld      hl,crc
        ld      de,want
        nop
        nop
        nop
""")],
        "the CRC run before the set": [("""        call    apply_sets
        ld      hl,WORK
        ld      bc,BANK_SIZE
        call    crc_update
""", """        ld      hl,WORK
        ld      bc,BANK_SIZE
        call    crc_update
        call    apply_sets
""")],
        "the index taken as 0": [("""        ld      a,(cur_stream)
        ld      (set_tag+3),a
        ld      de,set_tag
        ld      c,SET_CRC_INDEX
""", """        xor     a
        nop
        nop
        ld      (set_tag+3),a
        ld      de,set_tag
        ld      c,SET_CRC_INDEX
""")],
        "a chunk's stream not its bank's": [("""        ld      a,(cur_bank)
        ld      c,a
        ld      hl,blk_pos
        ld      de,set_tag
""", """        xor     a
        nop
        nop
        ld      c,a
        ld      hl,blk_pos
        ld      de,set_tag
""")],
        "the key taken with the fix off": [("""        ret     z                       ; the main line is off: nothing
""", """        nop
""")],
        "a set applied to the plain game": [("""        xor     a                           ; with the fix off, no set applies
        ld      (set_choices),a
        ld      (set_choices+1),a
""", "")],
        "a chunk left over is passed": [("""        ld      hl,set_recs+4
        call    is_zero32
        jp      nz,bad_patch
        ld      hl,set_recs+REC+4
        call    is_zero32
        jp      nz,bad_patch
""", """        ld      hl,set_recs+4
        call    is_zero32
        nop
        nop
        nop
        ld      hl,set_recs+REC+4
        call    is_zero32
        nop
        nop
        nop
""")],
        "a set not checked before the file is made": [("""        call    check_sets
""", """        ld      a,1
        call    sets_open
""")],
        "a chunk's bit count unchecked": [("""        ld      a,d
        or      e
        jp      nz,bad_patch
        call    map_std
""", """        ld      a,d
        or      e
        nop
        nop
        nop
        call    map_std
""")],
        "Enter forgets the choices": [(""".route: ld      a,(mp_key)
        or      a
        ret     z
""", """.route: ld      a,(mp_key)
        or      a
        jr      nz,.rt
        xor     a
        ld      (set_choices),a
        ret
.rt:
""")],
        "the choice lost with the fix": [(""".fix:   ld      de,(MV_DESC)
""", """.fix:   push    hl
        ld      a,(MV_SEL)
        inc     a
        call    md_line
        inc     hl
        ld      (hl),0
        pop     hl
        ld      de,(MV_DESC)
""")],
    }

    def set_control_caught(self, name: str) -> bool:
        binary, symbols = H.assemble(self.SET_BROKEN[name])
        one, fix_key, set_key = self.lines()
        base = nxc.apply(self.patch, game=self.game)

        def go(keys, patch=None):
            m = self.machine({"patch.nxc": self.patch if patch is None else patch, self.game_name: self.game},
                             keys=keys, binary=binary, symbols=symbols)
            failed, message = m.run('"patch.nxc"')
            return m, failed, message

        if name in ("the set never applied", "the CRC run before the set", "the index taken as 0", "a chunk's stream not its bank's"):
            m, failed, message = go([set_key, "enter"], self.reindexed())
            return failed or bytes(m.written.get(NEX, b"")) != nxc.apply(self.reindexed(), game=self.game, colours=self.sets[0])
        if name == "the output's CRC not checked":
            m, failed, message = go([set_key, "enter"], self.forge_set([], crc=zlib.crc32(base) ^ 1))
            return not failed
        if name == "the key taken with the fix off":
            m, failed, message = go([fix_key, set_key, fix_key, "enter"])
            return bytes(m.written.get(NEX, b"")) != base
        if name == "a set applied to the plain game":
            m, failed, message = go([one, set_key, fix_key, "enter"])
            return m.peak_pages != 6
        no_bank = next(b for b in nxc.ORDER if not base[18 + b])
        a_bank = next(b for b in nxc.ORDER if base[18 + b])
        if name == "a chunk left over is passed":
            m, failed, message = go([set_key, "enter"], self.forge_set([(no_bank, chunk_of((0, b"xx")))]))
            return not failed
        if name == "a set not checked before the file is made":
            # Refused all the same, but only as the file is being made.
            m, failed, message = go([set_key, "enter"], self.forge_set([(a_bank, chunk_of((3, b"x"))[:-1] + b"")]))
            return NEX in m.opened
        if name == "a chunk's bit count unchecked":
            # More bits than bytes: the bytes after it are read from whatever lies past the chunk.
            m, failed, message = go([set_key, "enter"], self.forge_set([(a_bank, chunk_of((3, b"xyz"))[:-2])]))
            return message != "Patch damaged: get it again"
        if name == "Enter forgets the choices":
            m, failed, message = go([set_key, "enter"])
            return bytes(m.written.get(NEX, b"")) != self.want(True, 1, False)
        if name == "the choice lost with the fix":
            m, failed, message = go([set_key, fix_key, fix_key, "enter"])
            return bytes(m.written.get(NEX, b"")) != self.want(True, 1, False)
        raise AssertionError(name)

    def reindexed(self) -> bytes:
        """The patch with each set's index and stream moved, so that an index is not its place in the file."""
        def edit(bl, st):
            for entry in bl:
                if entry[0] == b"SET2":
                    e = nxc.parse_set(entry[1])
                    crc, chunks = nxc.read_set(st, e)
                    fixed = entry[1][1:nxc.SET_FIXED + entry[1][4]]
                    entry[1] = bytes((e["stream"] + 40,)) + fixed + set_body(st, e["stream"] + 40, crc, chunks)
        return rekey(self.patch, self.game, edit)

    def test_the_block_says_its_stream(self) -> None:
        patch = self.reindexed()
        _, _, set_key = self.lines()
        m, failed, message = self.run_it([set_key, "enter"], patch=patch)
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), nxc.apply(patch, game=self.game, colours=self.sets[0]))

    def test_negative_controls(self) -> None:
        caught = []
        for name in self.SET_BROKEN:
            with self.subTest(name):
                self.assertTrue(self.set_control_caught(name), f"a loader with {name} passed")
                caught.append(name)
        print(f"\nSet negative controls caught on {type(self).__name__}: {len(caught)} of {len(self.SET_BROKEN)}",
              flush=True)


@needs_tools
@unittest.skipUnless(ZX0_TOOL.exists(), "the zx0 compressor is missing: set NXC_ZX0_DIR")
class MadeUpChoices(Choices, Base):
    """The choices on a game made here, so that they run with no game files, on two snapshot shapes."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        import tempfile
        rng = random.Random(77)
        cls.rng = rng
        cls.banks = {b: random_bank(rng, b) for b in (5, 2, 0)}
        cls.game = snapshot_paged(cls.banks, 54, 0)
        cls.game_name = "game.z80"
        cls.sets = ["First", "A very long set name", "Third"]
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
            cls.patch, cls.nex = cls.build(Path(d), cls.game, cls.banks, rng, cls.sets)

    @staticmethod
    def build(tmp: Path, game: bytes, banks, rng, sets):
        patch, nex = build_case(tmp, rng, game, banks)
        colours = {}
        for n, name in enumerate(sets):
            path = tmp / f"set{n}.nex"
            path.write_bytes(painted(nex, rng, (5, 2, 10)))
            colours[name] = str(path)
        (tmp / "out.nex").write_bytes(nex)
        made, _ = nxc.make(str(tmp / "game.z80"), str(tmp / "out.nex"), dict(title="Made Up", file="game.z80", length=len(game)),
                           dict(build="test", publisher="Tester, 2026"), colours=colours,
                           trainer_blocks=[nxc.trn1("Infinite lives", [(2, 16000, 0xAB)])])
        return made, nex

    def test_the_tool_applies_a_set(self) -> None:
        self.assertEqual(nxc.colour_sets(self.patch), self.sets)

    def test_every_snapshot_shape_with_a_set_and_a_trainer(self) -> None:
        import tempfile
        rng = random.Random(12)
        b48 = {b: random_bank(rng, b) for b in (5, 2, 0)}
        b128 = {b: random_bank(rng, b) for b in range(8)}
        for name, game, banks in (("v1 packed", snapshot_v1(b48), b48), ("v1 stored", snapshot_v1(b48, packed=False), b48),
                                  ("v2 48K", snapshot_paged(b48, 23, 0), b48), ("v3 128K", snapshot_paged(b128, 54, 4), b128)):
            with self.subTest(name), tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
                patch, _ = self.build(Path(d), game, banks, rng, ["Only"])
                for keys, chosen, colours in ((["2", "enter"], None, None), (["1", "3", "enter"], [1], "Only"),
                                              (["1", "2", "enter"], [1], None)):
                    if keys == ["2", "enter"]:
                        m = self.machine({"patch.nxc": patch, "game.z80": game}, keys=keys)
                        self.assertFalse(m.run('"patch.nxc"')[0])
                        self.assertEqual(bytes(m.written[Z80]), game)
                        continue
                    if keys == ["1", "2", "enter"]:
                        m = self.machine({"patch.nxc": patch, "game.z80": game}, keys=keys)
                        self.assertFalse(m.run('"patch.nxc"')[0])
                        self.assertEqual(bytes(m.written[Z80]), nxc.original_with_pokes(patch, game, [1]))
                        continue
                    m = self.machine({"patch.nxc": patch, "game.z80": game}, keys=keys)
                    failed, message = m.run('"patch.nxc"')
                    self.assertFalse(failed, message)
                    self.assertEqual(m.clean(), [])
                    self.assertEqual(bytes(m.written[NEX]), nxc.apply(patch, game=game, colours=colours, chosen=chosen))

    def big_set_patch(self, tmp: Path, big: bytes, **more) -> bytes:
        tmp.joinpath("game.z80").write_bytes(self.game)
        tmp.joinpath("big.nex").write_bytes(big)
        tmp.joinpath("out.nex").write_bytes(self.nex)
        return nxc.make(str(tmp / "game.z80"), str(tmp / "out.nex"), dict(title="Big", file="game.z80"), dict(build="t"),
                        colours={"Big": str(tmp / "big.nex")}, trainer_blocks=[nxc.trn1("T", [(2, 16000, 1)])], **more)[0]

    def test_a_chunk_at_its_limit_across_its_pages(self) -> None:
        import tempfile
        rng = random.Random(14)
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
            big = bytearray(self.nex)
            at = 512 + 16384 * sum(1 for b in nxc.ORDER[:nxc.ORDER.index(10)] if big[18 + b])
            for i in range(16000):                       # all but the trainer's byte: past two pages of the table
                big[at + i] ^= rng.randrange(1, 256)
            patch = self.big_set_patch(Path(d), bytes(big))
            for keys in (["3", "enter"], ["3", "1", "enter"]):
                m = self.machine({"patch.nxc": patch, "game.z80": self.game}, keys=keys)
                failed, message = m.run('"patch.nxc"')
                self.assertFalse(failed, message)
                self.assertEqual(m.clean(), [])
                self.assertEqual(bytes(m.written[NEX]), nxc.apply(patch, game=self.game, colours="Big", chosen=[1] if len(keys) == 3 else None))

    def test_a_set_of_more_than_128k_loads_holding_one_chunk_at_a_time(self) -> None:
        import tempfile
        rng = random.Random(16)
        nex = bytearray(self.nex)
        # More banks than the build here has, all changed, in .nex order: 9 banks of 16,384 changed bytes is 165,888 decoded.
        have = [b for b in nxc.ORDER if nex[18 + b]]
        added = [b for b in nxc.ORDER if not nex[18 + b]][:9 - min(9, len(have))]
        keep = bytes(nex[:512]); nex = bytearray(keep)
        nex[9] = len(have) + len(added)
        for b in added:
            nex[18 + b] = 1
        made = {b: self.nex[512 + 16384 * have.index(b):][:16384] if b in have else bytes(16384) for b in have + added}
        ordered = [b for b in nxc.ORDER if nex[18 + b]]
        plain = bytes(nex) + b"".join(made[b] for b in ordered)
        big = bytes(nex) + b"".join(bytes(x ^ rng.randrange(1, 256) for x in made[b]) for b in ordered)
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
            tmp = Path(d)
            tmp.joinpath("game.z80").write_bytes(self.game)
            tmp.joinpath("plain.nex").write_bytes(plain)
            tmp.joinpath("big.nex").write_bytes(big)
            patch, stats = nxc.make(str(tmp / "game.z80"), str(tmp / "plain.nex"), dict(title="Big", file="game.z80"), dict(build="t"), colours={"Big": str(tmp / "big.nex")})
        self.assertGreaterEqual(stats["sets"][0]["decoded"], 128 * 1024)
        self.assertLessEqual(stats["sets"][0]["largest"], nxc.SET_CHUNK_MAX)
        self.assertEqual(nxc.apply(patch, game=self.game, colours="Big"), big)
        for keys, want in ((["2", "enter"], big), (["enter"], plain)):
            m = self.machine({"patch.nxc": patch, "game.z80": self.game}, keys=keys)
            failed, message = m.run('"patch.nxc"')
            self.assertFalse(failed, message)
            self.assertEqual(m.clean(), [])
            self.assertEqual(bytes(m.written[NEX]), want)
            self.assertEqual(m.peak_pages, 9 if keys[0] == "2" else 6)     # the same 72K, or 48K, as a small set

    def test_any_bank_fits_however_its_changes_lie(self) -> None:
        import tempfile
        rng = random.Random(15)
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
            # Every other byte of a bank: 8,192 runs, which as (bank, offset, length) entries would be 49,152 bytes.
            big = bytearray(self.nex)
            for i in range(512, 512 + 16384, 2):
                big[i] ^= rng.randrange(1, 256)
            tmp = Path(d)
            patch = self.big_set_patch(tmp, bytes(big))
            m = self.machine({"patch.nxc": patch, "game.z80": self.game}, keys=["3", "enter"])
            failed, message = m.run('"patch.nxc"')
            self.assertFalse(failed, message)
            self.assertEqual(m.clean(), [])
            self.assertEqual(bytes(m.written[NEX]), bytes(big))
            for bad in ("", "x" * 26):
                with self.assertRaisesRegex(ValueError, "name"):
                    nxc.make(str(tmp / "game.z80"), str(tmp / "out.nex"), dict(title="Big", file="game.z80"), dict(build="t"),
                             colours={bad: str(tmp / "out.nex")})

    def test_memory_on_a_1mb_next(self) -> None:
        """1MB reports 96 8K pages. A big set needs the same 9 pages as a small one, and refuses by name below that."""
        for free, refused in ((10, False), (9, True), (7, True)):       # the menu's page is one of them
            m = self.machine({"patch.nxc": self.patch, "game.z80": self.game}, keys=["3", "enter"], total_pages=96, free_pages=free)
            failed, message = m.run('"patch.nxc"')
            self.assertEqual(failed, refused, message)
            if refused:
                self.assertEqual(message, "Needs 72K free RAM")
                self.assertEqual(m.free_pages, free)
            else:
                self.assertEqual(m.peak_pages, 9)

    def test_ten_lines_use_the_zero_key(self) -> None:
        def add(bl, st):
            for n in range(9):
                bl.insert(1, [b"TRN1", nxc.trn1(f"T{8 - n}", [(2, 15000 + n, 1)])])
        patch = rekey(self.patch, self.game, lambda bl, st: (bl.__setitem__(slice(None), [e for e in bl if e[0] != b"TRN1"]), add(bl, st)))
        # Nine trainers here: the menu holds eight, then the fix on 9 and enhanced on 0.
        m, failed, message = self.run_it(["0", "enter"], patch=patch)
        self.assertFalse(failed, message)
        self.assertEqual(m.clean(), [])
        self.assertEqual(bytes(m.written[NEX]), nxc.apply(patch, game=self.game, colours=self.sets[0]))
        screen = m.screens[-2].split("\n")
        self.assertEqual(screen[4 + 8 + 2], row("9", "Colour clash fix", "[ ON]"))
        self.assertEqual(screen[4 + 8 + 3], row("0", "Enhanced colours", "[First]"))
        m, failed, message = self.run_it(["9", "enter"], patch=patch)
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[Z80]), self.game)
        # With one trainer fewer than ten lines, 0 is no line at all.
        m, failed, message = self.run_it(["0", "enter"])
        self.assertFalse(failed, message)
        self.assertEqual(bytes(m.written[NEX]), self.want(True, 0, False))

    # ---- the credit line

    def with_info(self, lines: bytes, sets: bool = True) -> bytes:
        """The patch with these lines first in INF1, and with or without its sets."""
        def edit(bl, st):
            for entry in bl:
                if entry[0] == b"INF1":
                    entry[1] = lines + entry[1]
            if not sets:
                bl[:] = [e for e in bl if e[0] != b"SET2"]
        return rekey(self.patch, self.game, edit)

    def tail(self, patch: bytes) -> list[str]:
        """What the menu shows in its credit rows, 20 and 21, the ones there."""
        m, failed, message = self.run_it(["enter"], patch=patch)
        self.assertFalse(failed, message)
        self.assertEqual(m.clean(), [])
        lines = m.screens[1].split("\n")
        self.assertEqual(lines[22:], [FOOTER[22], FOOTER[23]])
        return [x for x in lines[20:22] if x]

    def assert_credit(self, patch: bytes, shown: str | None) -> None:
        self.assertEqual(nxc.credit_line(patch), shown)
        self.assertEqual(self.tail(patch), [] if shown is None else shown.split("\n"))
        if shown is not None:
            self.assertLessEqual(max(len(x) for x in shown.split("\n")), 32)

    def test_credit_each_combination_of_keys(self) -> None:
        both = b"patch_by=Ann\ncolours_by=Bob\n"
        for lines, sets, shown in (
                (b"", True, None),
                (b"", False, None),
                (b"patch_by=Ann\n", True, "Patch: Ann"),
                (b"patch_by=Ann\n", False, "Patch: Ann"),
                (b"colours_by=Bob\n", True, "Colours: Bob"),
                (b"colours_by=Bob\n", False, None),
                (both, True, "Colours: Bob\nPatch: Ann"),
                (both, False, "Patch: Ann"),
                (b"colours_by=Bob\npatch_by=Ann\n", True, "Colours: Bob\nPatch: Ann"),
                (b"patch_by=\ncolours_by=\n", True, None)):
            with self.subTest(lines=lines, sets=sets):
                self.assert_credit(self.with_info(lines, sets), shown)

    def test_credit_truncation(self) -> None:
        def names(a: int, b: int) -> bytes:
            return (b"patch_by=" + b"A" * a + b"\n" if a else b"") + (b"colours_by=" + b"B" * b + b"\n" if b else b"")
        for a, b, shown in (
                (25, 23, "Colours: " + "B" * 23 + "\nPatch: " + "A" * 25),           # each whole, ending in the last column
                (26, 24, "Colours: " + "B" * 23 + "\nPatch: " + "A" * 25),           # each cut on its own
                (40, 0, "Patch: " + "A" * 25),
                (0, 40, "Colours: " + "B" * 23),
                (3, 40, "Colours: " + "B" * 23 + "\nPatch: AAA")):
            with self.subTest(a=a, b=b):
                patch = self.with_info(names(a, b))
                self.assert_credit(patch, shown)
                # And after a redraw, which works on the same description.
                m, failed, message = self.run_it(["1", "1", "enter"], patch=patch)
                self.assertFalse(failed, message)
                self.assertIn(shown, m.screens[-2])

    def test_credit_keys_must_lie_in_what_a_loader_reads(self) -> None:
        pad = b"x=" + b"y" * 213 + b"\n"
        room = 252 - len(pad)
        inside = b"patch_by=" + b"A" * (room - 10) + b"\n"
        self.assertEqual(len(pad + inside), 252)
        self.assert_credit(self.with_info(pad + inside), "Patch: " + "A" * min(25, room - 10))
        over = b"patch_by=" + b"A" * (room - 9) + b"\n"
        self.assertEqual(len(pad + over), 253)                  # its newline falls past the end: as absent
        self.assert_credit(self.with_info(pad + over), None)
        past = b"z=" + b"y" * 260 + b"\npatch_by=Ann\n"
        self.assert_credit(self.with_info(past), None)

    def test_credit_unprintable_names(self) -> None:
        self.assert_credit(self.with_info(b"patch_by=A\x01\xffB\n"), "Patch: A??B")

    def test_credit_controls(self) -> None:
        for name, replace, patch in (
                ("colours with no set", [("""        ld      a,(set_counts)
        or      a
        jr      nz,.col
""", """        ld      a,(set_counts)
        or      a
        jr      .col
""")], self.with_info(b"colours_by=Bob\n", False)),
                ("a name cut short", [("""        ld      a,25                    ; patch_by: cut to 25 without one
""", """        ld      a,20
""")], self.with_info(b"patch_by=" + b"A" * 30 + b"\n"))):
            with self.subTest(name):
                binary, symbols = H.assemble(replace)
                m = self.machine({"patch.nxc": patch, self.game_name: self.game}, keys=["enter"], binary=binary, symbols=symbols)
                failed, message = m.run('"patch.nxc"')
                got = [x for x in m.screens[1].split("\n")[20:22] if x]
                want = nxc.credit_line(patch)
                self.assertNotEqual(got, [] if want is None else want.split("\n"), f"a loader with {name} passed")

    def test_layout_with_and_without_sets(self) -> None:
        m, failed, message = self.run_it(["enter"])
        self.assertFalse(failed, message)
        top = {0: " MADE UP".ljust(28) + "////", 1: " Tester, 2026", 3: "TRAINER", 4: row("1", "Infinite lives", "[OFF]"), 6: "OPTIONS",
               7: row("2", "Colour clash fix", "[ ON]")}
        self.assertEqual(m.screens[-2], screen({**top, 8: row("3", "Enhanced colours", "[OFF]"), 10: "ENTER play   BREAK exit"}))
        self.assertNotIn(0x69, set(m.menu_attrs[-1][4]))                         # no line highlighted
        without = rekey(self.patch, self.game, lambda bl, st: bl.__setitem__(slice(None), [e for e in bl if e[0] != b"SET2"]))
        m, failed, message = self.run_it(["3", "enter"], patch=without)    # no such line
        self.assertFalse(failed, message)
        self.assertEqual(m.screens[-2], screen({**top, 9: "ENTER play   BREAK exit"}))
        self.assertEqual(bytes(m.written[NEX]), nxc.apply(without, game=self.game))


JETPAC_DIR = EVIDENCE / "format-study" / "jetpac" / "work" / "p2"
_jetpac_games = glob.glob(str(REFERENCE / "jetpac" / "*.z80"))
JETPAC_GAME = Path(_jetpac_games[0]) if _jetpac_games else None
JETPAC_PATCH = V1 / "Jetpac.nxc"


@needs_tools
@unittest.skipUnless(JETPAC_PATCH.exists() and JETPAC_GAME and JETPAC_DIR.is_dir(),
                     "Jetpac's game, builds or patch are missing (build/v1, NXC_EVIDENCE); they are private")
class Jetpac(Choices, Base):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.patch = JETPAC_PATCH.read_bytes()
        cls.game = JETPAC_GAME.read_bytes()
        cls.game_name = text_of(cls.patch, b"TGT1")["file"].lower()
        cls.sets = nxc.colour_sets(cls.patch)
        cls.base = (JETPAC_DIR / "jetpac_sprites.nex").read_bytes()
        cls.enhanced = (JETPAC_DIR / "jetpac_sprites_painted.nex").read_bytes()

    def test_the_outputs_are_the_builds_themselves(self) -> None:
        m, failed, message = self.run_it(["enter"])
        self.assertFalse(failed, message)
        self.assertEqual(hashlib.md5(bytes(m.written[NEX])).digest(), hashlib.md5(self.base).digest())
        m, failed, message = self.run_it(["3", "enter"])
        self.assertFalse(failed, message)
        self.assertEqual(hashlib.md5(bytes(m.written[NEX])).digest(), hashlib.md5(self.enhanced).digest())

    def test_the_menu_exactly(self) -> None:
        m, failed, message = self.run_it(["1", "3", "2", "2", "enter"])
        self.assertFalse(failed, message)
        self.assertEqual(len(m.screens), 7)      # before, default, one for each key, after
        top = {0: " JETPAC".ljust(28) + "////", 1: " Ultimate, 1983", 3: "TRAINER", 6: "OPTIONS", 10: "ENTER play   BREAK exit",
               21: "Patch: Jon Attree"}           # no Colours: row, as the patch names no painter
        for shown, (trainer, fix, enhanced) in zip(m.screens[1:6], (("[OFF]", "[ ON]", "[OFF]"), ("[ ON]", "[ ON]", "[OFF]"),
                                                                    ("[ ON]", "[ ON]", "[ ON]"), ("[ ON]", "[OFF]", "[N/A]"),
                                                                    ("[ ON]", "[ ON]", "[ ON]"))):
            self.assertEqual(shown, screen({**top, 4: row("1", "Infinite lives", trainer), 7: row("2", "Colour clash fix", fix),
                                            8: row("3", "Enhanced colours", enhanced)}))
        self.assertNotIn("Colours:", "\n".join(m.screens))
        self.assertEqual(bytes(m.written[NEX]), nxc.apply(self.patch, game=self.game, colours="Spec256", chosen=[1]))

    def test_credit_and_trainer_as_built(self) -> None:
        credit = text_of(self.patch, b"INF1")["credit"]
        # build/v1/Jetpac.nxc was made before the credit named Dean Woodyatt; a patch made now carries nxc.CREDIT
        self.assertIn("bleughb/nexclash, GPL-3.0-or-later)", credit)
        self.assertIn("painter not established", credit)
        self.assertIsNone(nxc.inf1_value(self.patch, "colours_by"))
        self.assertEqual(nxc.inf1_value(self.patch, "patch_by"), b"Jon Attree")
        self.assertEqual([t[1] for t in nxc.trainers(self.patch)], ["Infinite lives"])

    def test_its_blanks_are_filled_as_the_records_say(self) -> None:
        self.assertEqual(text_of(self.patch, b"TGT1")["zxdb_entry"], "0009362")
        self.assertEqual(dict(nxc.blocks(self.patch)[1])[b"ROM1"], b"\x01")
        proof = text_of(self.patch, b"PRF1")
        self.assertIn("IDENTICAL", proof["replay"])
        self.assertIn("40/40", proof["replay"])
        self.assertIn("JNext 1.1.104", proof["emulator"])
        self.assertIn("two players not exercised", proof["coverage"])
        self.assertEqual(proof["hardware"], "none")
        for key in ("replay_when", "emulator_when", "coverage_when", "hardware_when"):
            self.assertTrue(proof[key])

    def test_measure_with_a_set(self) -> None:
        m = H.Machine(self.binary, self.symbols, {"patch.nxc": self.patch, self.game_name: self.game}, keys=["3", "enter"])
        m.set_phases(["work_begin", "done"])
        failed, message = m.run('"patch.nxc"')
        self.assertFalse(failed, message)
        low = next(a for a in range(self.symbols["stack_floor"], 0x4001)
                   if a == 0x4000 or m.m.memory[a] != H.junk(a))
        print(f"\nMeasure, Jetpac with a set: {m.phase_ticks['work_begin'] / (H.SPEED_MHZ * 1e6):.3f} s at 28 MHz, no file I/O; "
              f"{m.peak_pages} pages; stack in the 8K reached {0x4000 - low} bytes of "
              f"{0x4000 - self.symbols['stack_floor']}; file {len(self.binary)}; code ends {self.symbols['code_end']:#06x}, "
              f"variables start {self.symbols['vars']:#06x}", flush=True)
        self.assertGreater(low, self.symbols["stack_floor"])


BOMB_GAME = next((p for p in (INPUTS / "bomb_jack.z80", ) if p.exists()), None)
BOMB_PATCH = first_existing(V1 / "BombJack.nxc")


@needs_tools
@unittest.skipUnless(BOMB_GAME and BOMB_PATCH, "Bomb Jack's game or patch is missing (build/inputs, build/v1)")
class BombJack(Choices, Base):
    """A patch made before this menu, with two sets and one trainer from the archive's .pok."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.game = BOMB_GAME.read_bytes()
        cls.patch = BOMB_PATCH.read_bytes()
        cls.game_name = text_of(cls.patch, b"TGT1")["file"].lower()
        cls.sets = nxc.colour_sets(cls.patch)

    def test_the_outputs_are_the_builds_themselves(self) -> None:
        folder = EVIDENCE / "format-study" / "bomb_jack"
        for keys, name in ((["enter"], "rebuilt_default.nex"), (["3", "enter"], "rebuilt_arcade.nex")):
            if not (folder / name).exists():
                self.skipTest("the study's rebuilt files are not here")
            m, failed, message = self.run_it(keys)
            self.assertFalse(failed, message)
            self.assertEqual(hashlib.md5(bytes(m.written[NEX])).digest(), hashlib.md5((folder / name).read_bytes()).digest())
        # The second set is for tools: it is still there, and rebuilds.
        self.assertEqual(hashlib.md5(nxc.apply(self.patch, game=self.game, colours="test")).digest(),
                         hashlib.md5((folder / "rebuilt_test.nex").read_bytes()).digest())


@needs_tools
@unittest.skipUnless((V1 / "study").is_dir() and REFERENCE.is_dir(),
                     "the study's patches and games are not here (NXC_EVIDENCE); they are private")
class OtherBuilds(Base):
    """Every build of the format study: games found at run time by TGT1's MD5, nothing kept here. Results are printed
    only as counts; the list is private."""

    def test_all(self) -> None:
        games: dict[str, Path] = {}
        reference = REFERENCE
        for path in sorted(glob.glob(str(reference / "**" / "*.z80"), recursive=True)):
            games.setdefault(hashlib.md5(Path(path).read_bytes()).hexdigest(), Path(path))
        for path in sorted(glob.glob(str(EVIDENCE / "format-study" / "*.z80"))):
            games.setdefault(hashlib.md5(Path(path).read_bytes()).hexdigest(), Path(path))
        patches = sorted(glob.glob(str(V1 / "study" / "*.nxc")))
        limit = os.environ.get("NXC_BUILDS")
        done = no_game = k128 = k48 = 0
        slowest = (0, 0, 0)
        most_pages = 0
        v = {1: 0, 2: 0, 3: 0}
        for patch_path in patches[:int(limit) if limit else None]:
            patch = Path(patch_path).read_bytes()
            game_path = games.get(text_of(patch, b"TGT1").get("md5", ""))
            if game_path is None:
                no_game += 1
                continue
            game = game_path.read_bytes()
            with self.subTest(index=done):
                want = nxc.apply(patch, game=game)
                self.assertEqual(hashlib.md5(want).hexdigest(), text_of(patch, b"INF1").get("nex_md5"))
                name = text_of(patch, b"TGT1")["file"].lower()
                m = H.Machine(self.binary, self.symbols, {"patch.nxc": patch, name: game})
                m.set_phases(["absorb_game", "done"])
                failed, message = m.run('"patch.nxc"', limit_seconds=60)
                self.assertFalse(failed, message)
                self.assertEqual(m.clean(), [])
                self.assertEqual(bytes(m.written[NEX]), want, "not byte-exact")
                snap = nxc.Z80Snapshot(str(game_path))
                v[snap.version] += 1
                k128 += snap.is128
                k48 += not snap.is128
                if m.phase_ticks["absorb_game"] > slowest[0]:
                    slowest = (m.phase_ticks["absorb_game"], len(want), len(game))
                done += 1
        print(f"\nOther builds: {done} of {len(patches)} byte-exact on the Z80 ({k48} 48K games, {k128} 128K games; "
              f".z80 versions {v}), {no_game} without a game to hand; slowest {slowest[0] / 28e6:.3f} s for a "
              f"{slowest[2]} byte game and {slowest[1]} byte .nex", flush=True)
        self.assertGreaterEqual(done, 3)
        self.assertGreaterEqual(k128, 1)

    def test_the_make_command_on_real_builds(self) -> None:
        """The command line on three builds of the study. Counts only."""
        import subprocess
        import tempfile
        builds = sorted(glob.glob(str(REFERENCE / "**" / "*_sprites.nex"), recursive=True))[:3]
        games: dict[str, Path] = {}
        for path in glob.glob(str(V1 / "study" / "*.nxc")):
            patch = Path(path).read_bytes()
            games[text_of(patch, b"INF1")["nex_md5"]] = text_of(patch, b"TGT1")["md5"]
        known = {hashlib.md5(Path(p).read_bytes()).hexdigest(): p for p in glob.glob(str(REFERENCE / "**" / "*.z80"), recursive=True)}
        done = 0
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
            for index, build in enumerate(builds):
                data = Path(build).read_bytes()
                game = known.get(games.get(hashlib.md5(data).hexdigest(), ""))
                if not game:
                    continue
                out = Path(d) / f"{index}.nxc"
                r = subprocess.run([sys.executable, "-W", "ignore", str(ROOT / "tools/nxc.py"), "make", build, game, "-o", str(out), "--file", "game.z80"], capture_output=True, text=True)
                with self.subTest(index=index):
                    self.assertEqual(r.returncode, 0, "refused")
                    self.assertEqual(nxc.apply(out.read_bytes(), game=Path(game).read_bytes()), data)
                    done += 1
        print(f"\nMake command: {done} of {len(builds)} real builds rebuilt exactly", flush=True)

    def test_finished_patches(self) -> None:
        """The finished patches under build/dean, which are private: each byte-exact, and each trainer changing only its POKEs.
        Counts only."""
        paths = sorted(glob.glob(str(ROOT / "build" / "dean" / "*.nxc")))
        if not paths:
            self.skipTest("the finished patches are not here; they are private")
        games: dict[str, Path] = {}
        for path in sorted(glob.glob(str(REFERENCE / "**" / "*.z80"), recursive=True)) + sorted(glob.glob(str(INPUTS / "*.z80"))):
            games.setdefault(hashlib.md5(Path(path).read_bytes()).hexdigest(), Path(path))
        done = with_trainers = trainers = 0
        for index, path in enumerate(paths):
            patch = Path(path).read_bytes()
            game = games[text_of(patch, b"TGT1")["md5"]].read_bytes()
            with self.subTest(index=index):
                want = nxc.apply(patch, game=game)
                self.assertEqual(hashlib.md5(want).hexdigest(), text_of(patch, b"INF1")["nex_md5"])
                offsets = {}
                at = 512
                for b in nxc.ORDER:
                    if want[18 + b]:
                        offsets[b] = at
                        at += 16384
                every = nxc.trainers(patch)
                self.assertLessEqual(len(every), nxc.TRAINERS_SHOWN)
                for k, t in enumerate(every):
                    got = nxc.apply(patch, game=game, chosen=[k + 1])
                    allowed = {offsets[b] + o for b, o, _ in t[2]}
                    self.assertTrue({i for i in range(len(got)) if got[i] != want[i]} <= allowed)
                done += 1
                with_trainers += bool(every)
                trainers += len(every)
        print(f"\nFinished patches: {done} of {len(paths)} byte-exact, {with_trainers} with trainers, {trainers} trainers, none played", flush=True)


BIGSET = ROOT / "build" / "bigset"
RUNS = EVIDENCE / "pilot" / "runs"
LARGE_SETS = {
    # patch, game, base, enhanced; none is in this repository.
    "Sabre Wulf": ("sabre_wulf.nxc", RUNS / "sabre_wulf/sabre_wulf.z80", RUNS / "sabre_wulf/out/sabre_wulf_sprites.nex", RUNS / "sabre_wulf/out/sabre_wulf_sprites_spec256.nex"),
    "Underwurlde": ("underwurlde.nxc", RUNS / "underwurlde/underwurlde.z80", RUNS / "underwurlde/out/final/underwurlde_sprites.nex", RUNS / "underwurlde/out/paint/underwurlde_enhanced.nex"),
    "Wally": ("wally.nxc", REFERENCE / "everyones_a_wally/wally.z80", EVIDENCE.parent / "2026-11-03-spec256-paint/everyones_a_wally/work/u/wally_u.nex",
              EVIDENCE.parent / "2026-11-03-spec256-paint/everyones_a_wally/work/u/wally_u_painted.nex"),
}


@needs_tools
@unittest.skipUnless(all((BIGSET / v[0]).exists() and v[1].exists() and v[2].exists() and v[3].exists() for v in LARGE_SETS.values()),
                     "the large sets are private: build/bigset, NXC_EVIDENCE")
class LargeSets(Base):
    """Real sets that the single table of SET1 could not hold, as a menu option: exact either way, on a 1MB Next's numbers."""

    def test_each_is_a_choice_and_exact_either_way(self) -> None:
        for name, (patch, game, base, enhanced) in LARGE_SETS.items():
            f, g = (BIGSET / patch).read_bytes(), game.read_bytes()
            trainers = min(len(nxc.trainers(f)), 8)
            key = str((trainers + 2) % 10)
            self.assertEqual(nxc.colour_sets(f), ["Enhanced"])
            for keys, want, pages in ((["enter"], base, 6), ([key, "enter"], enhanced, 9)):
                with self.subTest(name, keys=keys):
                    # exactly enough: the menu's page, then what the rebuild needs
                    m = self.machine({"patch.nxc": f, nxc.targets(f)[0]["file"].lower(): g}, keys=keys, total_pages=96, free_pages=pages + 1)
                    failed, message = m.run('"patch.nxc"')
                    self.assertFalse(failed, message)
                    self.assertEqual(m.clean(), [])
                    self.assertEqual(bytes(m.written[NEX]), want.read_bytes())
                    self.assertEqual(m.peak_pages, pages)
                    self.assertIn(row(key, "Enhanced colours", "[OFF]"), m.screens[1].split("\n"))
                    if key in keys:
                        self.assertIn(row(key, "Enhanced colours", "[ ON]"), m.screens[-2].split("\n"))
                    print(f"\n{name}: {'enhanced' if key in keys else 'default'}: {m.ticks / (28_000_000):.2f} s at 28 MHz with no file I/O, "
                          f"8K for the menu + {pages * 8}K", flush=True)
            # one page short, either way: refused after the menu, naming what the rebuild needs
            for keys, free, said in ((["enter"], 6, "Not enough free RAM: needs 48K"), ([key, "enter"], 9, "Needs 72K free RAM")):
                with self.subTest(name, keys=keys, free=free):
                    m = self.machine({"patch.nxc": f, nxc.targets(f)[0]["file"].lower(): g}, keys=keys, total_pages=96, free_pages=free)
                    failed, message = m.run('"patch.nxc"')
                    self.assert_refused(m, failed, message, said)
                    self.assertEqual(m.free_pages, free)


if __name__ == "__main__":
    unittest.main()

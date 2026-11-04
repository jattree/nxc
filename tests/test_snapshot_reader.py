"""tools/nxc.py reads .z80 and .sna snapshots itself, and applying a patch needs nothing outside this repository and
Python's standard library.

The reader must give the same banks, version, 128K flag and 7FFD as the one in Dean Woodyatt's NexClash
(bleughb/nexclash, nexclash/z80tonex.py) that it replaced. Where a NexClash checkout is given (NEXCLASH_REPO), every
test vector and every .z80 listed in NXC_GAMES (a file of paths, one per line, or a folder searched for .z80 files)
is read by both and compared. Without them those comparisons skip; the vectors are still read and checked against
what the spec says they hold.
"""
from __future__ import annotations

import glob
import json
import os
import struct
import subprocess
import sys
import sysconfig
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
VECTORS = HERE / "vectors"
sys.path.insert(0, str(ROOT / "tools"))
import nxc  # noqa: E402


def nexclash_reader():
    repo = os.environ.get("NEXCLASH_REPO")
    if not repo or not Path(repo, "nexclash", "z80tonex.py").exists():
        return None
    sys.path.insert(0, repo)
    try:
        from nexclash.z80tonex import Z80Snapshot
    except Exception:
        return None
    return Z80Snapshot


def listed_games() -> list[Path]:
    spec = os.environ.get("NXC_GAMES")
    if not spec:
        return []
    p = Path(spec)
    if p.is_dir():
        return sorted(Path(x) for x in glob.glob(str(p / "**" / "*.z80"), recursive=True))
    return [Path(line.strip()) for line in p.read_text().splitlines() if line.strip()]


def pack(data: bytes) -> bytes:
    """A .z80 packer, for building test snapshots: runs of 5 or more, and any run of ED, as ED ED n v."""
    out = bytearray(); i = 0
    while i < len(data):
        v = data[i]; n = 1
        while i + n < len(data) and data[i + n] == v and n < 255:
            n += 1
        if n >= 5 or (v == 0xED and n >= 2):
            out += bytes((0xED, 0xED, n, v)); i += n
        elif v == 0xED:
            out.append(v); i += 1
            if i < len(data):
                out.append(data[i]); i += 1      # an ED is never followed straight by another in packed form
        else:
            out.append(v); i += 1
    return bytes(out)


def banks_of(seed: int, banks) -> dict[int, bytes]:
    return {b: bytes(((i * (seed + b + 3)) >> 3 ^ (i & 0x55 if b & 1 else 0xED if i % 97 == 0 else 0)) & 255
                     for i in range(nxc.BANK)) for b in banks}


def z80(version: int, is128: bool, packed: bool, banks: dict[int, bytes], port=0x13) -> bytes:
    head = bytearray(30)
    head[0], head[1] = 0x12, 0x34
    head[8:10] = struct.pack("<H", 0xFF00)
    head[12] = 0x20 if (packed and version == 1) else 0
    if version == 1:
        head[6:8] = struct.pack("<H", 0x8000)
        body = banks[5] + banks[2] + banks[0]
        return bytes(head) + (pack(body) + b"\x00\xed\xed\x00" if packed else body)
    ext = bytearray(23 if version == 2 else 54)
    ext[0:2] = struct.pack("<H", 0x8000)
    ext[2] = (3 if version == 2 else 4) if is128 else 0
    ext[3] = port
    pages = [(3 + b, b) for b in range(8)] if is128 else [(8, 5), (4, 2), (5, 0)]
    body = bytearray()
    for page, bank in pages:
        d = banks[bank]
        if packed:
            p = pack(d)
            body += struct.pack("<HB", len(p), page) + p
        else:
            body += struct.pack("<HB", 0xFFFF, page) + d
    return bytes(head) + struct.pack("<H", len(ext)) + bytes(ext) + bytes(body)


class ReaderAlone(unittest.TestCase):
    def test_every_form(self):
        for version in (1, 2, 3):
            for is128 in ((False,) if version == 1 else (False, True)):
                for packed in (False, True):
                    want = banks_of(version * 10 + is128 * 2 + packed, range(8) if is128 else (5, 2, 0))
                    s = nxc.Z80Snapshot(z80(version, is128, packed, want))
                    with self.subTest(version=version, is128=is128, packed=packed):
                        self.assertEqual(s.version, version)
                        self.assertEqual(s.is128, is128)
                        self.assertEqual(s.port7ffd, 0x13 if is128 else 0)
                        self.assertEqual(s.banks, want)

    def test_damage_is_refused(self):
        good = z80(2, True, True, banks_of(1, range(8)))
        for bad in (good[:20], good[:31], good[:-1], good[:-100], z80(2, False, False, banks_of(1, (5, 2)) | {0: b""})[:-1]):
            with self.assertRaises((ValueError, KeyError)):
                nxc.Z80Snapshot(bad)
        with self.assertRaises(nxc.Wrong):
            nxc.snapshot_of(good[:-5], nxc.KIND_Z80)

    def test_vectors(self):
        v1 = nxc.Z80Snapshot((VECTORS / "game_v1.z80").read_bytes())
        v3 = nxc.Z80Snapshot((VECTORS / "game_v3.z80").read_bytes())
        self.assertEqual((v1.version, v1.is128, sorted(v1.banks)), (1, False, [0, 2, 5]))
        self.assertEqual(v3.version, 3)
        self.assertEqual(sorted(v1.banks), sorted(set(v3.banks) & {0, 2, 5}))
        for b in v1.banks:
            self.assertEqual(v1.banks[b], v3.banks[b])


@unittest.skipUnless(nexclash_reader(), "no NexClash checkout to compare with: set NEXCLASH_REPO")
class SameAsNexClash(unittest.TestCase):
    def compare(self, data: bytes, name: str):
        ref_cls = nexclash_reader()
        with tempfile.NamedTemporaryFile(suffix=".z80") as t:
            t.write(data); t.flush()
            ref = ref_cls(t.name)
        ours = nxc.Z80Snapshot(data)
        with self.subTest(name=name):
            self.assertEqual({k: bytes(v) for k, v in ref.banks.items()}, ours.banks)
            for attr in ("version", "is128", "port7ffd", "pc", "sp", "im", "iff1", "iff2", "border"):
                self.assertEqual(getattr(ref, attr), getattr(ours, attr), attr)

    def test_vectors_and_synthetic(self):
        for p in sorted(VECTORS.glob("*.z80")):
            self.compare(p.read_bytes(), p.name)
        for version in (1, 2, 3):
            for is128 in ((False,) if version == 1 else (False, True)):
                for packed in (False, True):
                    self.compare(z80(version, is128, packed, banks_of(7, range(8) if is128 else (5, 2, 0))), f"v{version}")

    def test_listed_games(self):
        games = listed_games()
        if not games:
            self.skipTest("no games listed: set NXC_GAMES")
        for p in games:
            self.compare(p.read_bytes(), p.name)


class NoOutsideImports(unittest.TestCase):
    """Listing a patch and applying it, with and without the menu, load nothing from outside this repository and the
    standard library: run in a fresh interpreter with -I, no environment variables of ours, and every module checked."""

    def test_apply_and_list(self):
        v = json.loads((VECTORS / "vectors.json").read_text())
        game = VECTORS / v["sna_file"] if (VECTORS / str(v.get("sna_file", ""))).is_file() else VECTORS / "game_v1.z80"
        probe = r"""
import sys, sysconfig, os, io, contextlib
root, patch, game, out = sys.argv[1:5]
sys.path.insert(0, os.path.join(root, 'tools'))
import nxc
with contextlib.redirect_stdout(io.StringIO()):
    nxc.run([patch])
    nxc.run([patch, game, '-o', out + '.menu.nex'])
    nxc.run([patch, game, '-o', out + '.bare.nex', '--bare'])
    nxc.run([patch, game, '-o', out + '.z80', '--original'])
std = {os.path.realpath(sysconfig.get_paths()[k]) for k in ('stdlib', 'platstdlib')}
bad = []
for name, m in list(sys.modules.items()):
    f = getattr(m, '__file__', None)
    if not f:
        continue
    f = os.path.realpath(f)
    if f.startswith(os.path.realpath(root) + os.sep):
        continue
    if any(f.startswith(s + os.sep) for s in std) and 'site-packages' not in f and 'dist-packages' not in f:
        continue
    bad.append((name, f))
print(bad)
"""
        env = {k: v for k, v in os.environ.items() if not k.startswith(("NXC_", "NEXCLASH")) and k != "PYTHONPATH"}
        with tempfile.TemporaryDirectory() as d:
            r = subprocess.run([sys.executable, "-I", "-c", probe, str(ROOT), str(VECTORS / "vector.nxc"), str(game),
                                str(Path(d) / "out")], capture_output=True, text=True, env=env, cwd=d)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), "[]")


if __name__ == "__main__":
    unittest.main()

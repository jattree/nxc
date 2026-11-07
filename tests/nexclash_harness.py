"""firmware/nexclash.asm on a Z80 emulator (the `z80` package), with what NextZXOS gives a dot command faked: esxDOS
files (RST $08), IDE_BANK, IDE_MODE and IDE_INTEGER_VAR (M_P3DOS), ROM printing (RST $10), the keyboard, NextREG paging
of 8K pages. Structure from NextTang's tests/test_spec256_dot.py (GPL-3.0-or-later)."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

try:
    import z80
except ImportError:
    z80 = None

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "firmware" / "nexclash.asm"
LOAD_AT = 0x2000
ARGS_AT = 0x5D00
RETURN_AT = 0xFFF0
ENTRY_SP = 0xFF00
PAGE = 8192
HOST_MMU = {2: 10, 3: 11, 4: 4, 5: 5, 6: 0, 7: 1}   # the 128K map: banks 5, 2, 0
SPEED_MHZ = 28
FLAGS = 0x5C3B
FIRST_PART = 8192       # NextZXOS loads this much of a dot command; the rest stays in its open file
OWN_HANDLE = 2
ROM_FILE = "c:/machines/next/ennextzx.rom"   # the card's ROMs: the menu takes its font from ROM 3's


def font_glyph(c: int) -> bytes:
    """A made-up font: each character's 8 bytes differ from every other's."""
    return bytes(((c * 37 + k * 11) ^ (k << 4) ^ c) & 255 for k in range(8))


FAKE_ROM = bytearray(65536)
for _c in range(32, 128):
    FAKE_ROM[0xFD00 + (_c - 32) * 8:0xFD00 + (_c - 31) * 8] = font_glyph(_c)
GLYPHS = {font_glyph(c): chr(c) for c in range(32, 128)}
GLYPHS[bytes((0x01, 0x03, 0x07, 0x0F, 0x1F, 0x3F, 0x7F, 0xFF))] = "/"
GLYPHS[bytes(8)] = " "


def junk(address: int) -> int:
    """What lies in the 8K past what the file holds: nothing may assume it is zero."""
    return (address * 37 + 11) & 255


def resolve_folder(spec: str, cwd: str) -> str | None:
    """What F_GETCWD gives with A=$FF, as found by trying it on NextZXOS v2.09: the folder of a filespec, the name after
    the last / \\ or : ignored, in capitals with its drive and a final /. None for a folder that is not there."""
    spec = spec.replace("\\", "/")
    drive = "C"
    if len(spec) > 1 and spec[1] == ":":
        drive, spec = spec[0].upper(), spec[2:]
    folder = spec.rsplit("/", 1)[0] + "/" if "/" in spec else ""
    parts = [] if folder.startswith("/") else [p for p in cwd.split("/") if p]
    for part in folder.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part.upper())
    return drive + ":/" + "".join(p + "/" for p in parts)


SHORT_OK = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!#$%&'()-@^_`{}~")


def short_names(names: list[str]) -> dict[str, str]:
    """{name: its 8.3 name} for the files of one folder, in their order, as FAT makes them (JNext's rule, measured against
    NextZXOS): a name that is already 8.3 in capitals' terms stays, others become the first 6 of the base, ~N and the first
    3 of the extension, without spaces or dots, anything else as _."""
    out: dict[str, str] = {}
    for name in names:
        bare = name.lstrip(".")
        base, dot, ext = bare.rpartition(".") if "." in bare else (bare, "", "")
        clean = lambda t, n: "".join(c if c in SHORT_OK else "_" for c in t.upper() if c not in " .")[:n]
        native = name == bare and " " not in name and name.count(".") <= 1 and 1 <= len(base) <= 8 and len(ext) <= 3 \
            and all(c in SHORT_OK for c in (base + ext).upper())
        sfn = base.upper() + ("." + ext.upper() if ext else "") if native else None
        n = 1
        while sfn is None or sfn in out.values():
            sfn = clean(base, 6) + "~%d" % n + ("." + clean(ext, 3) if ext else "")
            n += 1
        out[name] = sfn
    return out


def assemble(replace: list[tuple[str, str]] | None = None) -> tuple[bytes, dict[str, int]]:
    """The binary and its symbols; replace: (old, new) text changes for a deliberately broken loader."""
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
        source = Path(directory) / "nexclash.asm"
        text = SOURCE.read_text()
        menu = (SOURCE.parent / "menu.asm").read_text()       # the menu's one source: a broken copy beside it is taken first
        for old, new in replace or []:
            if old in text:
                text = text.replace(old, new, 1)
            elif old in menu:
                menu = menu.replace(old, new, 1)
            else:
                raise AssertionError(f"not in the source: {old!r}")
        (Path(directory) / "menu.asm").write_text(menu)
        text = text.replace('include "menu.asm"', f'include "{Path(directory) / "menu.asm"}"')
        source.write_text(text)
        out = Path(directory) / "NEXCLASH"
        sym = Path(directory) / "nexclash.sym"
        subprocess.run(["sjasmplus", "--nologo", f"--inc={SOURCE.parent}", f"--raw={out}", f"--sym={sym}", str(source)],
                       check=True, capture_output=True)
        symbols = {}
        for line in sym.read_text().splitlines():
            m = re.match(r"(\S+): EQU 0x([0-9A-Fa-f]+)", line)
            if m:
                symbols[m.group(1)] = int(m.group(2), 16) & 0xFFFF
        return out.read_bytes(), symbols


class Hung(AssertionError):
    pass


class Machine:
    """One run of the dot command."""

    KEYS = {"enter": (0xBF, 0), "space": (0x7F, 0), "caps": (0xFE, 0)}
    # The tests before the menu round drive the bare route, SPACE: the choices fixed in the .nex, as before.
    for _i in range(5):
        KEYS[str(_i + 1)] = (0xF7, _i)
        KEYS[str(_i + 6)] = (0xEF, 4 - _i)
    KEYS["0"] = (0xEF, 0)

    def __init__(self, binary: bytes, symbols: dict[str, int], files: dict[str, bytes], keys=("enter",),
                 free_pages: int = 90, fail_read: int | None = None, os_mode: int = 0,
                 fail_write: int | None = None, fail_create: bool = False, cwd: str = "/",
                 total_pages: int | None = 224, folders: tuple[str, ...] = ()) -> None:
        self.symbols = symbols
        self.files = {name.lower(): bytes(data) for name, data in files.items()}
        self.files.setdefault(ROM_FILE, bytes(FAKE_ROM))
        self.menu_draws = 0
        self.overlay_part = None
        self.menu_page = None
        self.just_menu = False
        self.menu_attrs: list[list[bytes]] = []
        self.keys = list(keys)
        self.free_pages = free_pages
        self.fail_read = fail_read
        self.fail_write = fail_write
        self.fail_create = fail_create
        self.total_pages = total_pages
        self.cwd = cwd
        self.folders = folders               # subfolders to list, as folders, beside the files
        self.dir_reads = 0
        self.opened: list[str] = []
        self.absorbs = 0
        self.overlay = bytes(binary[FIRST_PART:])
        self.os_mode = os_mode
        self.reads = 0
        self.writes = 0
        self.handles: dict[int, list] = {OWN_HANDLE: [bytes(binary), FIRST_PART, "the command's own file"]}
        self.written: dict[str, bytearray] = {}
        self.deleted: list[str] = []
        self.next_handle = 3
        self.selected = 0
        self.nextregs = {0x07: 0}
        self.mmu = dict(HOST_MMU)
        self.pages: dict[int, bytearray] = {}
        self.allocated: list[int] = []
        self.ever_allocated: list[int] = []
        self.peak_pages = 0
        self.layer = (0, 0)
        self.width = 8
        self.integer_vars: dict[int, int] = {}
        self.printed = bytearray()
        self.screen: list[str] = [""]
        self.screens: list[str] = []
        self.control = 0
        self.problems: list[str] = []
        self.key_state = "gap"
        self.key_count = 0
        self.key_now: tuple | None = None
        self.polls_since_key = 0
        self.ticks = 0
        self.marks: dict[int, int] = {}
        self.bad_writes: list[tuple[int, int, int]] = []
        self.watch_ranges: list[tuple[int, int]] = []
        self.iopage_guard = False
        m = z80.Z80Machine()
        self.m = m
        # Everything but the dot command holds a pattern, so that stray reads are visible and writes can be found.
        for slot, page in self.mmu.items():
            self.pages[page] = self.fill(page)
            m.set_memory_block(slot * PAGE, bytes(self.pages[page]))
        self.host_hash = {page: bytes(data) for page, data in self.pages.items()}
        m.set_memory_block(0, bytes((0xC7,)) * 0x2000)      # the ROM: nothing runs here
        m.set_memory_block(LOAD_AT, bytes(binary[:FIRST_PART]))
        first_end = symbols["first_end"]
        m.set_memory_block(first_end, bytes(junk(a) for a in range(first_end, LOAD_AT + FIRST_PART)))
        m.set_memory_block(RETURN_AT, bytes((0x76,)))
        m.set_output_callback(self.output)
        m.set_input_callback(self.input)
        m.set_write_callback(self.on_write)
        m.set_breakpoint(0x0008)
        m.set_breakpoint(0x0010)
        m.set_breakpoint(RETURN_AT)
        # Writes that can never be right: the ROM, the code and its data, the screen and system variables, and the
        # caller's memory above its stack. The stack below ENTRY_SP is the caller's own.
        code_end = symbols["code_end"]
        m.mark_addrs(0x0000, code_end, m.WRITE_MARK)
        m.mark_addrs(0x5B00, 0x0500, m.WRITE_MARK)       # the screen, 0x4000 to 0x5AFF, is the menu's
        m.unmark_addr(FLAGS, m.WRITE_MARK)                  # the one system variable it touches
        m.mark_addrs(0xC000, ENTRY_SP - 256 - 0xC000, m.WRITE_MARK)
        m.mark_addrs(ENTRY_SP + 2, 0x10000 - ENTRY_SP - 2, m.WRITE_MARK)
        self.phase_ticks: dict[str, int] = {}
        self.phases: list[str] = []
        self.overlay_read = False
        self.callbacks: dict[str, object] = {}

    @staticmethod
    def fill(page: int) -> bytearray:
        return bytearray(((i * 7 + page * 13) ^ (i >> 8)) & 255 for i in range(PAGE))

    def on_write(self, addr: int, value: int) -> None:
        # Once the .nex is being written, only the ZX0 decoder may write at the I/O page's address, and only with a chunk of a set's
        # own page mapped there. A site or a stray pointer landing on a table page is still found.
        decoding = self.iopage_guard and self.mmu[5] != self.allocated[3] and self.symbols["src_copy"] <= self.m.pc < self.symbols["zx_bounds"]
        # The menu .nex's writer puts its header right, at the end, in the header's own place.
        header = self.overlay_part == "mnx" and self.symbols["mnx_start"] <= self.m.pc < self.symbols["mnx_end_code"] and 0xA000 <= addr < 0xA200
        if not (decoding and 0xA000 <= addr < 0xB000) and not header:
            self.bad_writes.append((self.m.pc, addr, value))
        self.m.memory[addr] = value

    def watch_writes(self, start: int, size: int) -> None:
        """Mark more addresses as never to be written."""
        self.m.mark_addrs(start, size, self.m.WRITE_MARK)

    def set_phases(self, names: list[str]) -> None:
        self.phases = names
        # What is read in after the menu lies over what ran before it, so its marks wait until it is there.
        if self.overlay_read:
            for name in names:
                self.m.set_breakpoint(self.symbols[name])

    def guard_iopage(self) -> None:
        """Once the .nex is being written, nothing writes to the I/O page but the file buffer: a stream or a site that
        got out of WORK lands here."""
        def check() -> None:
            if self.string(self.m.hl).lower().endswith(".nex"):
                self.iopage_guard = True
                self.watch_writes(0xA000, 0x1000)
        self.callbacks["create_out"] = check
        if "create_out" not in self.phases:
            self.set_phases(self.phases + ["create_out"])

    # ---- ports

    def map_slot(self, slot: int, page: int) -> None:
        old = self.mmu[slot]
        if old == page:
            return
        start = slot * PAGE
        self.pages[old] = bytearray(self.m.memory[start:start + PAGE])
        if page in self.mmu.values():
            self.problems.append(f"page {page} mapped twice")
        if page not in self.pages:
            self.pages[page] = self.fill(page)
        self.m.set_memory_block(start, bytes(self.pages[page]))
        self.mmu[slot] = page
        if slot in (6, 7):
            self.problems.append("MMU6 or MMU7 was changed")

    def output(self, port: int, value: int) -> None:
        if port == 0x243B:
            self.selected = value
        elif port == 0x253B:
            if 0x50 <= self.selected <= 0x57:
                slot = self.selected - 0x50
                if slot < 3:
                    self.problems.append(f"MMU{slot} was changed")
                else:
                    if value not in self.allocated and value != HOST_MMU[slot]:
                        self.problems.append(f"page {value} mapped but not allocated")
                    self.map_slot(slot, value)
            else:
                self.nextregs[self.selected] = value

    def input(self, port: int) -> int:
        if port == 0x253B:
            if 0x50 <= self.selected <= 0x57:
                return self.mmu[self.selected - 0x50]
            return self.nextregs.get(self.selected, 0)
        if port & 0xFF == 0xFE:
            return self.keyboard(port >> 8)
        return 0xFF

    def keyboard(self, row_mask: int) -> int:
        self.key_count += 1
        if self.key_state == "gap" and self.key_count > 6000:
            if self.keys:
                name = self.keys.pop(0)
                self.key_now = name
                self.key_state = "down"
                self.key_count = 0
            elif self.key_count > 400000:
                raise Hung("the menu is still polling after the last key")
        elif self.key_state == "down" and self.key_count > 200:
            self.key_now = None
            self.key_state = "gap"
            self.key_count = 0
        value = 0x1F
        if self.key_now:
            for name in self.key_now.split("+"):
                row, bit = self.KEYS[name]
                if row_mask & (row ^ 0xFF):
                    continue
                value &= ~(1 << bit)
        return value | 0xE0

    # ---- RST $10

    def rst10(self, a: int) -> None:
        if self.mmu != HOST_MMU:
            self.problems.append("RST $10 with memory paged out")
        if self.m.sp < 0xC000:
            self.problems.append(f"RST $10 on a stack at {self.m.sp:#06x}")
        if a == 0x80:
            self.problems.append("RST $10 with A=0x80")
        self.printed.append(a)
        if a >= 32:
            self.just_menu = False
        if self.control:
            if self.control == 30:
                self.width = a
                if self.layer == (0, 0):
                    self.problems.append("control code 30 on layer 0")
            self.control = 0
            return
        if a == 30:
            self.control = 30
        elif a == 14:
            if self.just_menu and self.screen == [""]:
                self.just_menu = False
                return
            self.screens.append("\n".join(self.screen))
            self.screen = [""]
            if self.layer == (0, 0):
                self.problems.append("control code 14 on layer 0")
        elif a == 13:
            self.screen.append("")
        elif 32 <= a < 127:
            self.screen[-1] += chr(a)
        else:
            self.problems.append(f"RST $10 with code {a}")

    # ---- M_P3DOS

    def p3dos(self) -> bool:
        """Answer one call; True for carry (for +3DOS calls: success)."""
        m = self.m
        if m.c != 7:
            self.problems.append("M_P3DOS without RAM 7")
        if self.mmu[2] != HOST_MMU[2]:
            self.problems.append("M_P3DOS with MMU2 moved")
        call = m.de
        if call == 0x01BD:
            reason = m.alt_l
            if m.alt_h != 0:
                self.problems.append("IDE_BANK for other than ZX memory")
            if reason == 0:
                if self.total_pages is None:
                    m.a = 7
                    return False
                m.e = self.total_pages
                return True
            if reason == 1:
                if self.free_pages <= 0:
                    m.a = 7
                    return False
                self.free_pages -= 1
                page = 223 - len(self.ever_allocated)
                self.ever_allocated.append(page)
                self.allocated.append(page)
                if not self.overlay_read and self.menu_page is None:
                    self.menu_page = page          # the menu's own, before the menu: not counted in peak_pages
                self.peak_pages = max(self.peak_pages, len(self.allocated) - (self.menu_page in self.allocated))
                m.e = page
                return True
            if reason == 3:
                page = m.alt_e
                if page not in self.allocated:
                    self.problems.append(f"freed page {page} it does not hold")
                else:
                    if page in self.mmu.values():
                        self.problems.append(f"freed page {page} while it is mapped")
                    self.allocated.remove(page)
                    self.free_pages += 1
                return True
            self.problems.append(f"IDE_BANK reason {reason}")
            return False
        if call == 0x01D5:
            if m.a == 0:
                m.a = self.layer[0] | self.layer[1] << 2
                m.b = self.width
                return True
            if m.a == 1:
                self.layer = (m.alt_b, m.alt_c)
                m.a = self.layer[0] | self.layer[1] << 2
                m.b = 5 if self.layer != (0, 0) else 8
                if self.layer != (0, 0):
                    self.width = 5
                return True
            return False
        if call == 0x01C9:
            if m.alt_h != 1:
                self.problems.append("IDE_INTEGER_VAR is only ever a set")
            self.integer_vars[m.alt_c] = m.alt_de
            return True
        self.problems.append(f"M_P3DOS call {call:#x}")
        return False

    # ---- RST $08

    def string(self, address: int) -> str:
        out = bytearray()
        while self.m.memory[address]:
            out.append(self.m.memory[address])
            address += 1
        return out.decode("latin-1")

    def esxdos(self, function: int) -> bool:
        """Answer one call; True for carry."""
        m = self.m
        if function == 0x8D:  # M_GETHANDLE
            m.a = OWN_HANDLE
            return False
        if function == 0xA8:  # F_GETCWD; as tried: no carry either way, and a folder that is not there leaves rubbish
            if m.a != 0xFF:
                self.problems.append("F_GETCWD for other than a filespec")
            folder = resolve_folder(self.string(m.de), self.cwd)
            m.set_memory_block(m.hl, (folder.encode() + b"\0") if folder else b"z*\0")
            return False
        if function == 0x88:  # M_DOSVERSION
            m.bc = ord("N") << 8 | ord("X")
            m.de = 0x0209
            m.a = self.os_mode
            return False
        if function == 0x94:
            return self.p3dos()
        if function == 0x9A:  # F_OPEN
            name = self.string(m.hl).lower()
            key = name if m.a != ord("$") else "$" + name
            self.opened.append(key)
            if m.b & 0x02:
                if self.fail_create:
                    m.a = 5
                    return True
                self.written[key] = bytearray()
                handle = self.next_handle
                self.next_handle += 1
                self.handles[handle] = [self.written[key], 0, key]
                m.a = handle
                return False
            if key not in self.files:
                key = self.by_short_name(key)
            if key is None:
                m.a = 5
                return True
            handle = self.next_handle
            self.next_handle += 1
            self.handles[handle] = [self.files[key], 0, key]
            m.a = handle
            return False
        if function == 0xA3:  # F_OPENDIR: B 0, 8.3 names; a list of (attributes, name, length) as the folder has them
            if m.b != 0:
                self.problems.append(f"F_OPENDIR mode {m.b:#x}")
            folder = resolve_folder(self.string(m.hl).rstrip("/\\") + "/x", self.cwd)
            if folder is None or not self.string(m.hl):
                m.a = 5
                return True
            entries = [(0x10, ".", 0), (0x10, "..", 0)] if folder != "C:/" else []
            entries += [(0x10, d.upper()[:8], 0) for d in self.folders]
            here = [k for k in self.files if resolve_folder(k, self.cwd) == folder]
            names = short_names([k.replace("\\", "/").rsplit("/", 1)[-1] for k in here])
            entries += [(0x20, names[k.replace("\\", "/").rsplit("/", 1)[-1]], len(self.files[k])) for k in here]
            handle = 0x80 | self.next_handle
            self.next_handle += 1
            self.handles[handle] = [entries, 0, "dir " + folder]
            m.a = handle
            return False
        if function == 0xAD:  # F_UNLINK
            name = self.string(m.hl).lower()
            key = name if m.a != ord("$") else "$" + name
            self.deleted.append(key)
            self.written.pop(key, None)
            return False
        entry = self.handles.get(m.a)
        if entry is None:
            self.problems.append(f"esxDOS call {function:#x} on a bad handle")
            return True
        if function == 0xA4:  # F_READDIR: attributes, the name, time and date (4), the length (4); A 0 at the end
            self.dir_reads += 1
            if entry[1] >= len(entry[0]):
                m.a = 0
                return False
            attr, name, size = entry[0][entry[1]]
            entry[1] += 1
            if m.hl + 22 > 0xC000:
                self.problems.append(f"F_READDIR into {m.hl:#06x}")
            m.set_memory_block(m.hl, bytes((attr,)) + name.encode() + b"\0" + bytes(4) + size.to_bytes(4, "little"))
            m.a = 1
            return False
        if isinstance(entry[0], list):
            if function != 0x9B:
                self.problems.append(f"esxDOS call {function:#x} on a folder's handle")
                return True
            del self.handles[m.a]
        elif function == 0xA1:  # F_FSTAT
            m.set_memory_block(m.hl, bytes(7) + len(entry[0]).to_bytes(4, "little"))
        elif function == 0x9F:  # F_SEEK
            if m.l != 0:
                self.problems.append("a seek not from the start")
            entry[1] = min(m.bc << 16 | m.de, len(entry[0]))
        elif function == 0x9D:  # F_READ
            self.reads += 1
            if self.fail_read is not None and self.reads == self.fail_read:
                m.a = 5
                return True
            if m.hl + m.bc > 0xC000:
                self.problems.append(f"F_READ into {m.hl:#06x}, {m.bc} bytes")
            data = bytes(entry[0][entry[1]:entry[1] + m.bc])
            m.set_memory_block(m.hl, data)
            entry[1] += len(data)
            m.bc = len(data)
            if m.a == OWN_HANDLE and entry[1] - len(data) == self.symbols.get("FILE_MNX_AT", -1):
                self.overlay_part = "mnx"
            if m.a == OWN_HANDLE and not self.overlay_read and entry[1] - len(data) == FIRST_PART:
                self.overlay_read = True
                for name in self.phases:
                    m.set_breakpoint(self.symbols[name])
        elif function == 0x9E:  # F_WRITE
            self.writes += 1
            if self.fail_write is not None and self.writes == self.fail_write:
                m.a = 5
                return True
            data = bytes(m.memory[m.hl:m.hl + m.bc])
            entry[0][entry[1]:entry[1] + len(data)] = data
            entry[1] += len(data)
        elif function == 0x9B:  # F_CLOSE
            if m.a == OWN_HANDLE:
                self.problems.append("the command's own file was closed: NextZXOS does that")
            del self.handles[m.a]
        else:
            raise AssertionError(f"esxDOS call {function:#x}")
        return False

    def by_short_name(self, key: str) -> str | None:
        """The file a path names by its 8.3 name, if any."""
        folder = resolve_folder(key, self.cwd)
        here = [k for k in self.files if resolve_folder(k, self.cwd) == folder]
        names = short_names([k.replace("\\", "/").rsplit("/", 1)[-1] for k in here])
        want = key.replace("\\", "/").rsplit("/", 1)[-1].upper()
        return next((k for k in here if names[k.replace("\\", "/").rsplit("/", 1)[-1]] == want), None)

    # ---- running

    def go(self, budget: int = 50_000_000) -> None:
        m = self.m
        m.ticks_to_stop = budget
        m.run()
        self.ticks += budget - m.ticks_to_stop

    def run(self, argument: str | None, limit_seconds: float = 30.0) -> tuple[bool, str]:
        m = self.m
        if argument is None:
            m.hl = 0
        else:
            m.set_memory_block(ARGS_AT, argument.encode("latin-1") + b"\r")
            m.hl = ARGS_AT
        self.host_hash[HOST_MMU[2]] = bytes(m.memory[0x4000:0x6000])
        for name in ("menu_draw", "mp_chosen"):
            if name in self.symbols:
                m.set_breakpoint(self.symbols[name])
        m.pc = LOAD_AT
        m.sp = ENTRY_SP - 2
        m.set_memory_block(m.sp, RETURN_AT.to_bytes(2, "little"))
        limit = int(limit_seconds * SPEED_MHZ * 1_000_000)
        last_phase = None
        phase_marks = {self.symbols[n]: n for n in self.phases}
        mark_at = 0
        while True:
            if self.ticks > limit:
                raise Hung(f"no return after {self.ticks} T-states, at {m.pc:#06x}")
            self.go()
            if m.pc == RETURN_AT:
                break
            if m.pc == 0x0010:
                self.rst10(m.a)
                m.pc = m.memory[m.sp] | m.memory[m.sp + 1] << 8
                m.sp += 2
                continue
            if m.pc == 0x0008:
                back = m.memory[m.sp] | m.memory[m.sp + 1] << 8
                m.sp += 2
                carry = self.esxdos(m.memory[back])
                m.f = (m.f | 1) if carry else (m.f & ~1)
                m.pc = back + 1
                continue
            if m.pc in (self.symbols.get("menu_draw"), self.symbols.get("mp_chosen")):
                if self.mmu[5] in self.allocated[:1]:
                    self.on_menu(m.pc == self.symbols.get("mp_chosen"))
                self.step()                  # an older loader's menu_draw is in its 8K: not this menu
                continue
            if m.pc in phase_marks and self.overlay_read:
                name = phase_marks[m.pc]
                if last_phase is not None:
                    self.phase_ticks[last_phase] = self.phase_ticks.get(last_phase, 0) + self.ticks - mark_at
                last_phase, mark_at = name, self.ticks
                if name in self.callbacks:
                    self.callbacks[name]()
                self.step()
                continue
            in_menu_page = self.allocated and ((0xA000 <= m.pc < 0xC000 and self.mmu[5] == self.allocated[0])
                                               or (0x6000 <= m.pc < 0x8000 and self.mmu[3] == self.allocated[0]))   # the big part (SET3), through big_call
            if m.halted or not (LOAD_AT <= m.pc < LOAD_AT + 0x2000 or in_menu_page):
                raise Hung(f"stopped at {m.pc:#06x}")
        if last_phase is not None:
            self.phase_ticks[last_phase] = self.phase_ticks.get(last_phase, 0) + self.ticks - mark_at
        self.screens.append("\n".join(self.screen))
        message = ""
        if m.f & 1:
            address = m.hl
            for _ in range(200):
                byte = m.memory[address]
                message += chr(byte & 0x7F)
                address += 1
                if byte & 0x80:
                    break
        return bool(m.f & 1), message

    def ula_text(self) -> str:
        """The ULA screen as text, each cell's glyph in the made-up font, '#' for anything else."""
        mem = self.pages.get(HOST_MMU[2]) if self.mmu[2] != HOST_MMU[2] else self.m.memory[0x4000:0x6000]
        rows = []
        for r in range(24):
            line = ""
            for c in range(32):
                g = bytes(mem[(r & 0x18) << 8 | (r & 7) << 5 | c | k << 8] for k in range(8))
                line += GLYPHS.get(g, "#")
            rows.append(line.rstrip())
        while rows and not rows[-1]:
            rows.pop()
        return "\n".join(rows)

    def ula_attrs(self) -> list[bytes]:
        return [bytes(self.m.memory[0x5800 + r * 32:0x5800 + r * 32 + 32]) for r in range(24)]

    def on_menu(self, chosen: bool) -> None:
        """At each drawing of the menu, the screen before it; when it is done, the last."""
        if self.menu_draws == 0 and not chosen:
            self.screens.append("\n".join(self.screen))
            self.screen = [""]
        elif self.menu_draws:
            self.screens.append(self.ula_text())
            self.menu_attrs.append(self.ula_attrs())
        if chosen:
            self.just_menu = True
        else:
            self.menu_draws += 1

    def step(self) -> None:
        m = self.m
        m.ticks_to_stop = 1000
        before = m.ticks_to_stop
        m.step_over_breakpoint()
        self.ticks += before - m.ticks_to_stop

    def clean(self) -> list[str]:
        """What a finished run must leave as it found it."""
        out = list(self.problems)
        left_open = {h: e[2] for h, e in self.handles.items() if h != OWN_HANDLE}
        if left_open:
            out.append(f"files left open: {left_open}")
        if self.allocated:
            out.append(f"pages not freed: {self.allocated}")
        if self.mmu != HOST_MMU:
            out.append(f"paging not restored: {self.mmu}")
        if self.nextregs.get(0x07, 0) != 0:
            out.append("the CPU speed was not restored")
        if self.layer != (0, 0):
            out.append(f"the display mode was not restored: {self.layer}")
        if self.bad_writes:
            out.append(f"{len(self.bad_writes)} writes out of range, first: pc {self.bad_writes[0][0]:#06x} "
                       f"to {self.bad_writes[0][1]:#06x}")
        if self.m.sp != ENTRY_SP:
            out.append(f"the stack was not restored: {self.m.sp:#06x}")
        for slot, page in HOST_MMU.items():
            start = slot * PAGE
            now = bytearray(self.m.memory[start:start + PAGE])
            if slot in (6, 7):
                continue    # the caller's stack lives there, and only its own words change
            if slot == 2:
                now[FLAGS - start] = self.host_hash[page][FLAGS - start]
                now[:6912] = self.host_hash[page][:6912]          # the screen the menu drew on
            if now != self.host_hash[page]:
                out.append(f"the caller's page {page} changed")
        return out

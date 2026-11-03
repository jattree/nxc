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


def assemble(replace: list[tuple[str, str]] | None = None) -> tuple[bytes, dict[str, int]]:
    """The binary and its symbols; replace: (old, new) text changes for a deliberately broken loader."""
    with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as directory:
        source = Path(directory) / "nexclash.asm"
        text = SOURCE.read_text()
        for old, new in replace or []:
            if old not in text:
                raise AssertionError(f"not in the source: {old!r}")
            text = text.replace(old, new, 1)
        source.write_text(text)
        out = Path(directory) / "NEXCLASH"
        sym = Path(directory) / "nexclash.sym"
        subprocess.run(["sjasmplus", "--nologo", f"--raw={out}", f"--sym={sym}", str(source)],
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
    for _i in range(5):
        KEYS[str(_i + 1)] = (0xF7, _i)
        KEYS[str(_i + 6)] = (0xEF, 4 - _i)
    KEYS["0"] = (0xEF, 0)

    def __init__(self, binary: bytes, symbols: dict[str, int], files: dict[str, bytes], keys=("enter",),
                 free_pages: int = 90, fail_read: int | None = None, os_mode: int = 0,
                 fail_write: int | None = None, fail_create: bool = False, cwd: str = "/",
                 total_pages: int | None = 224) -> None:
        self.symbols = symbols
        self.files = {name.lower(): bytes(data) for name, data in files.items()}
        self.keys = list(keys)
        self.free_pages = free_pages
        self.fail_read = fail_read
        self.fail_write = fail_write
        self.fail_create = fail_create
        self.total_pages = total_pages
        self.cwd = cwd
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
        m.mark_addrs(0x4000, 0x2000, m.WRITE_MARK)
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
                self.peak_pages = max(self.peak_pages, len(self.allocated))
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
                m.a = 5
                return True
            handle = self.next_handle
            self.next_handle += 1
            self.handles[handle] = [self.files[key], 0, key]
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
        if function == 0xA1:  # F_FSTAT
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
            if m.a == OWN_HANDLE and not self.overlay_read:
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
            if m.pc in phase_marks and self.overlay_read:
                name = phase_marks[m.pc]
                if last_phase is not None:
                    self.phase_ticks[last_phase] = self.phase_ticks.get(last_phase, 0) + self.ticks - mark_at
                last_phase, mark_at = name, self.ticks
                if name in self.callbacks:
                    self.callbacks[name]()
                self.step()
                continue
            if m.halted or not (LOAD_AT <= m.pc < LOAD_AT + 0x2000):
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
            if now != self.host_hash[page]:
                out.append(f"the caller's page {page} changed")
        return out

"""A .nex started as .nexload starts it, on a Z80 emulator (the `z80` package) with the Next's 8K paging, NextREGs
through ports 0x243B and 0x253B, NEXTREG (ED 91) where a menu .nex's last bytes use it, the keyboard, and a ROM whose
font is made up. Used to show that a .nex carrying its menu starts the game in exactly the state the bare .nex for the
same choices starts in: the same bytes in every bank the bare header lists, the same registers but R, the same IFF,
I, MMU and stack. What .nexload itself leaves in the registers is not modelled: both runs start from the same values,
and the stub must hand them on unchanged. JNext checks that against the real thing.
"""
from __future__ import annotations

import struct

try:
    import z80
except ImportError:
    z80 = None

PAGE = 8192
ORDER = [5, 2, 0, 1, 3, 4, 6, 7] + list(range(8, 112))
ROM_PAGE = 0xFF
FONT_AT = 0x3D00


def font_glyph(c: int) -> bytes:
    """The made-up ROM font: each character's 8 bytes differ from every other's."""
    return bytes(((c * 37 + k * 11) ^ (k << 4) ^ c) & 255 for k in range(8))


ROM = bytearray(16384)
for _c in range(32, 128):
    ROM[FONT_AT + (_c - 32) * 8:FONT_AT + (_c - 31) * 8] = font_glyph(_c)
GLYPHS = {font_glyph(c): chr(c) for c in range(32, 128)}
STRIPE = bytes((0x01, 0x03, 0x07, 0x0F, 0x1F, 0x3F, 0x7F, 0xFF))
GLYPHS[STRIPE] = "/"
GLYPHS[bytes(8)] = " "


class Reset(Exception):
    pass


class NexMachine:
    KEYS = {"enter": (0xBF, 0), "space": (0x7F, 0), "caps": (0xFE, 0)}
    for _i in range(5):
        KEYS[str(_i + 1)] = (0xF7, _i)
        KEYS[str(_i + 6)] = (0xEF, 4 - _i)
    KEYS["0"] = (0xEF, 0)

    def __init__(self, nex: bytes, regs: dict | None = None, keys=(), iff: bool = False):
        self.pages: dict[int, bytearray] = {}
        self.mmu = {0: ROM_PAGE, 1: ROM_PAGE, 2: 10, 3: 11, 4: 4, 5: 5}
        self.selected = 0
        self.keys = list(keys)
        self.key_state, self.key_count, self.key_now = "gap", 0, None
        self.screens: list[str] = []
        self.nextregs: dict[int, int] = {}
        header = nex[:512]
        self.header = header
        at = 512 + screen_size(header)
        for b in ORDER:
            if header[18 + b]:
                data = nex[at:at + 16384]
                at += 16384
                self.page(2 * b)[:] = data[:PAGE].ljust(PAGE, b"\0")
                self.page(2 * b + 1)[:] = data[PAGE:].ljust(PAGE, b"\0")
        if at != len(nex):
            raise AssertionError("the .nex is not the length its header says")
        entry = header[139]
        self.mmu[6], self.mmu[7] = 2 * entry, 2 * entry + 1
        m = z80.Z80Machine()
        self.m = m
        for slot, page in self.mmu.items():
            m.set_memory_block(slot * PAGE, bytes(self.view(page, slot)))
        self.mirrors: dict[int, list[int]] = {}
        m.set_write_callback(self.on_write)
        m.set_output_callback(self.output)
        m.set_input_callback(self.input)
        regs = regs or {}
        sp, pc = struct.unpack_from("<HH", header, 12)
        m.sp, m.pc = sp, pc
        for name, value in regs.items():
            setattr(m, name, value)
        m.iff1 = m.iff2 = int(iff)
        self.nextreg_at: set[int] = set()

    def page(self, n: int) -> bytearray:
        if n not in self.pages:
            self.pages[n] = bytearray(((i * 7 + n * 13) ^ (i >> 8)) & 255 for i in range(PAGE))
        return self.pages[n]

    def view(self, page: int, slot: int) -> bytes:
        if page == ROM_PAGE:
            return bytes(ROM[(slot & 1) * PAGE:(slot & 1) * PAGE + PAGE])
        return bytes(self.page(page))

    def map_slot(self, slot: int, page: int) -> None:
        old = self.mmu[slot]
        start = slot * PAGE
        if old != ROM_PAGE:
            self.pages[old] = bytearray(self.m.memory[start:start + PAGE])
        for other, p in self.mmu.items():      # the same page in another slot: take its live bytes
            if p == page and other != slot and page != ROM_PAGE:
                self.pages[page] = bytearray(self.m.memory[other * PAGE:other * PAGE + PAGE])
        self.m.set_memory_block(start, self.view(page, slot))
        self.mmu[slot] = page
        self.alias()

    def alias(self) -> None:
        """A page in two slots is one memory: writes through either are mirrored to the other."""
        m = self.m
        m.unmark_addrs(0, 0x10000, m.WRITE_MARK)
        self.mirrors = {}
        for slot, page in self.mmu.items():
            twins = [t for t, p in self.mmu.items() if p == page and t != slot]
            if twins and page != ROM_PAGE:
                self.mirrors[slot] = [(t - slot) * PAGE for t in twins]
                m.mark_addrs(slot * PAGE, PAGE, m.WRITE_MARK)

    def on_write(self, addr: int, value: int) -> None:
        self.m.memory[addr] = value
        for delta in self.mirrors.get(addr >> 13, ()):
            self.m.memory[addr + delta] = value

    def sync(self) -> None:
        for slot, page in self.mmu.items():
            if page != ROM_PAGE:
                self.pages[page] = bytearray(self.m.memory[slot * PAGE:slot * PAGE + PAGE])

    def nextreg(self, reg: int, value: int) -> None:
        if 0x50 <= reg <= 0x57:
            self.map_slot(reg - 0x50, value)
        elif reg == 0x02 and value & 1:
            raise Reset()
        else:
            self.nextregs[reg] = value

    def output(self, port: int, value: int) -> None:
        if port == 0x243B:
            self.selected = value
        elif port == 0x253B:
            self.nextreg(self.selected, value)
        elif port & 0xFF == 0xFE:
            raise AssertionError("the stub wrote port 0xFE")

    def input(self, port: int) -> int:
        if port & 0xFF == 0xFE:
            return self.keyboard(port >> 8)
        if port == 0x253B:
            raise AssertionError("the stub read a NextREG")
        return 0xFF

    def keyboard(self, row_mask: int) -> int:
        self.key_count += 1
        if self.key_state == "gap" and self.key_count > 6000:
            if self.keys:
                self.screens.append(self.screen_text())
                self.key_now = self.keys.pop(0)
                self.key_state, self.key_count = "down", 0
            elif self.key_count > 400000:
                raise AssertionError("the menu is still polling after the last key")
        elif self.key_state == "down" and self.key_count > 200:
            self.key_now, self.key_state, self.key_count = None, "gap", 0
        value = 0x1F
        if self.key_now:
            for name in self.key_now.split("+"):
                row, bit = self.KEYS[name]
                if row_mask & (row ^ 0xFF):
                    continue
                value &= ~(1 << bit)
        return value | 0xE0

    def run_to(self, pc: int, budget: int = 400_000_000) -> None:
        """Run until the game's first instruction, emulating the NEXTREGs of the last 57 bytes."""
        m = self.m
        m.set_breakpoint(pc)
        start = pc - 57
        for at in (start + 40, start + 44, start + 48, start + 53):
            m.set_breakpoint(at)
        spent = 0
        while True:
            m.ticks_to_stop = 5_000_000
            m.run()
            spent += 5_000_000 - m.ticks_to_stop
            if spent > budget:
                raise AssertionError(f"no start after {spent} T-states, at {m.pc:#06x}")
            if m.pc == pc and self.mmu[pc >> 13] == self.game_page(pc >> 13):
                break
            if m.memory[m.pc] == 0xED and m.memory[(m.pc + 1) & 0xFFFF] == 0x91:
                reg, value = m.memory[m.pc + 2], m.memory[m.pc + 3]
                m.pc = (m.pc + 4) & 0xFFFF
                self.nextreg(reg, value)
                continue
            if m.pc in (start + 40, start + 44, start + 48, start + 53, pc):
                m.step_over_breakpoint()      # a breakpoint on bytes that are not NEXTREG here
            elif m.halted:
                raise AssertionError(f"halted at {m.pc:#06x}")
        self.sync()

    def game_page(self, slot: int) -> int:
        entry = self.final_entry
        return {0: ROM_PAGE, 1: ROM_PAGE, 2: 10, 3: 11, 4: 4, 5: 5, 6: 2 * entry, 7: 2 * entry + 1}[slot]

    final_entry = 0

    def state(self, banks) -> dict:
        """Everything compared at the game's first instruction."""
        m = self.m
        regs = {k: getattr(m, k) for k in ("af", "bc", "de", "hl", "ix", "iy", "sp", "pc", "alt_af", "alt_bc", "alt_de",
                                             "alt_hl", "i", "iff1", "iff2")}
        mem = {b: bytes(self.page(2 * b)) + bytes(self.page(2 * b + 1)) for b in banks}
        return {"regs": regs, "mmu": dict(self.mmu), "banks": mem}

    def screen_text(self) -> str:
        """The ULA screen as text: each cell's glyph in the made-up font, or '#' for anything else."""
        mem = self.m.memory
        rows = []
        for r in range(24):
            line = ""
            for c in range(32):
                g = bytes(mem[0x4000 | (r & 0x18) << 8 | (r & 7) << 5 | c | k << 8] for k in range(8))
                line += GLYPHS.get(g, "#")
            rows.append(line.rstrip())
        return "\n".join(rows)

    def attrs(self) -> list[bytes]:
        return [bytes(self.m.memory[0x5800 + r * 32:0x5800 + r * 32 + 32]) for r in range(24)]


def screen_size(header: bytes) -> int:
    flags = header[10]
    n = 0
    if flags and not flags & 0x80 and not flags & 0x1A:
        n += 512
    for bit, size in ((1, 49152), (2, 6912), (4, 12288), (8, 12288), (16, 12288)):
        if flags & bit:
            n += size
    return n


def start_state(nex: bytes, regs: dict, keys=(), iff=False, bare_header: bytes | None = None) -> tuple[dict, "NexMachine"]:
    """The state at the game's first instruction: for a bare .nex at once; for a menu .nex after its stub, with keys."""
    machine = NexMachine(nex, regs, keys, iff)
    head = bare_header or nex[:512]
    pc = struct.unpack_from("<H", head, 14)[0]
    machine.final_entry = head[139]
    banks = [b for b in range(112) if head[18 + b]]
    if bare_header is not None:
        machine.run_to(pc)
    return machine.state(banks), machine

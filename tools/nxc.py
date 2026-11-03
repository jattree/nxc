#!/usr/bin/env python3
"""Make and apply .nxc v1 files; the reference the Z80 loader (firmware/nexclash.asm) must match
byte for byte. See spec/NXC-FORMAT.md.

    nxc.py PATCH [GAME] [-o OUT] [--trainer NAME_OR_NUMBER ...] [--original] [--colours NAME]
    nxc.py import-pok PATCH POK GAME -o OUT [--publisher "Ocean, 1986"] [--only "Name,Name"]
    nxc.py credit PATCH GAME -o OUT [--patch-by NAME] [--colours-by NAME]
    nxc.py handoff-bas -o NXCHAND.BAS

Set NEXCLASH_REPO to a NexClash checkout (its snapshot reader is imported), and NXC_ZX0_DIR to the folder
holding the zx0 compressor if patches are to be made here; applying needs neither compressor nor decompressor.
"""
import hashlib, os, re, struct, subprocess, sys, tempfile, zlib
HERE = os.path.dirname(os.path.abspath(__file__))
ZX0_DIR = os.environ.get('NXC_ZX0_DIR', os.path.join(HERE, 'zx0bin'))
sys.path.insert(0, os.environ.get('NEXCLASH_REPO', os.path.join(HERE, 'nexclash-latest')))
from nexclash.z80tonex import Z80Snapshot
MAGIC = b'NXC1'; KEYCHECK = b'NXC1-KEY'; ORDER = [5, 2, 0, 1, 3, 4, 6, 7] + list(range(8, 112)); BANK = 16384; DROP = 256; KEY_BYTES = 20; LOADER_LEVEL = 1
SITE_TABLE_MAX = 24576  # what a Next loader holds: three 8K pages
TRAINER_NAME_MAX = 25; TRAINER_POKES_MAX = 255; TRAINERS_SHOWN = 8; POKES_HELD = 128
SET_NAME_MAX = 25; SETS_MAX = 255  # a set's table is held in three pages too: SITE_TABLE_MAX
TEXT_READ = 252; MENU_COLUMNS = 41; CREDIT_NAME = 32  # what a loader reads of INF1, shows, and keeps of a name
CREDIT = "Inspired by Bleugh.biz's nexclash (bleughb/nexclash, GPL-3.0-or-later)"

class Wrong(ValueError):
    """The file cannot be applied to this snapshot."""

class Stream:
    """RC4-style state keyed by absorbing the nonce, then the whole game file. Each encrypted block
    has its own stream from that state, so a loader can skip a block it does not know."""
    def __init__(self, nonce, game):
        s = list(range(256)); i = j = 0
        for b in nonce + game + nonce:
            i = (i + 1) & 255; j = (j + s[i] + b) & 255; s[i], s[j] = s[j], s[i]
        self.base = (s, i, j)
    def block(self, tag, index=0):
        """The xor function for one block: tag + index absorbed into a copy of the state."""
        s, i, j = list(self.base[0]), self.base[1], self.base[2]
        for b in tag + bytes((index,)):
            i = (i + 1) & 255; j = (j + s[i] + b) & 255; s[i], s[j] = s[j], s[i]
        st = [s, i, j]
        def xor(data, st=st):
            s, i, j = st; out = bytearray(len(data))
            for n, b in enumerate(data):
                i = (i + 1) & 255; j = (j + s[i]) & 255; s[i], s[j] = s[j], s[i]
                out[n] = b ^ s[(s[i] + s[j]) & 255]
            st[1], st[2] = i, j
            return bytes(out)
        xor(bytes(DROP))
        return xor

def zx0(data):
    with tempfile.TemporaryDirectory() as d:
        a, b = os.path.join(d, 'i'), os.path.join(d, 'o')
        open(a, 'wb').write(data)
        subprocess.run([os.path.join(ZX0_DIR, 'zx0'), '-f', a, b], check=True, capture_output=True)
        return open(b, 'rb').read()

def unzx0(src, limit=BANK):
    """Decode a ZX0 (version 2) stream, as firmware/nexclash.asm does, with the same checks: at most limit bytes
    out, no copy from before the start of the output, no read past the input, and the input used up exactly."""
    out = bytearray(); i = 0; a = 0x80; last = 1
    def byte():
        nonlocal i
        if i >= len(src): raise Wrong('compressed block is damaged')
        i += 1
        return src[i - 1]
    def bit():
        nonlocal a
        carry = a >> 7; a = a << 1 & 255
        if a == 0:
            b = byte(); carry = b >> 7; a = (b << 1 | 1) & 255
        return carry
    def elias(n=1):
        while not bit():
            n = n << 1 | bit()
            if n > 0xFFFF: raise Wrong('compressed block is damaged')
        return n
    def copy(n):
        if last > len(out) or len(out) + n > limit: raise Wrong('compressed block is damaged')
        for _ in range(n): out.append(out[-last])
    while True:
        n = elias()                                 # literals
        if len(out) + n > limit or i + n > len(src): raise Wrong('compressed block is damaged')
        out += src[i:i + n]; i += n
        if not bit():
            copy(elias())                           # the last offset again
            if not bit(): continue
        while True:                                 # a new offset
            c = 0xFE
            while not bit():
                c = (c << 1 | bit()) & 255
            c = (c + 1) & 255
            if c == 0:
                if i != len(src): raise Wrong('compressed block is damaged')
                return bytes(out)
            low = byte(); last = 0x10000 - (0x8000 | c >> 1 << 8 | (c & 1) << 7 | low >> 1)
            n = (1 if low & 1 else elias(1 << 1 | bit())) + 1
            if n > 0xFFFF: raise Wrong('compressed block is damaged')
            copy(n)
            if not bit(): break

def snapshot_banks(path):
    try:
        return {k: bytes(v) for k, v in Z80Snapshot(path).banks.items()}
    except (ValueError, IndexError) as e:
        raise Wrong('the game file is damaged: %s' % e)

# ---------------------------------------------------------------- trainers

def parse_pok(text):
    """The trainers of a .pok: [(name, [(bank field, address, value, original)])]. Y ends the file."""
    out = []; name = None; pokes = []
    for line in text.splitlines():
        line = line.strip()
        if not line: continue
        if line[0] == 'Y': break
        if line[0] == 'N':
            name = line[1:].strip(); pokes = []
        elif line[0] in 'MZ':
            f = line[1:].split()
            if name is None or len(f) != 4: raise ValueError('bad .pok line: %r' % line)
            pokes.append(tuple(int(x) for x in f))
            if line[0] == 'Z':
                out.append((name, pokes)); name = None
        else:
            raise ValueError('bad .pok line: %r' % line)
    return out

def sentence_case(name):
    """"Infinite Lives" as the menu shows it: "Infinite lives". All-capital words stay."""
    words = name.split(' ')
    return ' '.join(w if i == 0 or w.isupper() else w.lower() for i, w in enumerate(words))

def poke_bank(bank, address, snap):
    """(16K bank, offset) for a .pok line. Bank field 0 to 7: that bank paged at 0xC000. 8: no paging, so the address
    means what it does in the snapshot as it stands, with 7FFD deciding 0xC000 on a 128K game and bank 0 on a 48K one."""
    if not 0x4000 <= address <= 0xFFFF: raise Wrong('a POKE at %d is not in RAM' % address)
    if address < 0x8000: return 5, address - 0x4000
    if address < 0xC000: return 2, address - 0x8000
    if bank == 8: bank = (snap.port7ffd & 7) if snap.is128 else 0
    if not 0 <= bank <= 7: raise Wrong('a POKE names bank %d' % bank)
    return bank, address - 0xC000

def trn1(name, pokes, flags=0):
    """One TRN1 block's data. pokes: (bank, offset, value)."""
    label = name.encode('ascii')
    if not 1 <= len(label) <= TRAINER_NAME_MAX: raise ValueError('trainer name %r must be 1 to %d characters' % (name, TRAINER_NAME_MAX))
    if not 1 <= len(pokes) <= TRAINER_POKES_MAX: raise ValueError('trainer %r must have 1 to %d POKEs' % (name, TRAINER_POKES_MAX))
    return bytes((flags, len(label))) + label + bytes((len(pokes),)) + b''.join(struct.pack('<BHB', *p) for p in pokes)

def parse_trn1(d):
    """(flags, name, [(bank, offset, value)]) from a TRN1 block's data, or Wrong."""
    if len(d) < 3: raise Wrong('a trainer block is damaged')
    size = d[1]
    if size < 1 or size > TRAINER_NAME_MAX or len(d) < 3 + size: raise Wrong('a trainer block is damaged')
    name = d[2:2 + size].decode('ascii', 'replace'); n = d[2 + size]
    if n < 1 or len(d) != 3 + size + 4 * n: raise Wrong('a trainer block is damaged')
    pokes = [struct.unpack_from('<BHB', d, 3 + size + 4 * k) for k in range(n)]
    for b, o, _ in pokes:
        if b >= 112 or o >= BANK: raise Wrong('a trainer POKE is out of range')
    return d[0], name, pokes

def trainers(f):
    """The patch's trainers, readable without the game: [(flags, name, pokes)]."""
    return [parse_trn1(d) for t, d in blocks(f)[1] if t == b'TRN1']

def chosen_pokes(f, chosen):
    """The POKEs of the chosen trainers (their 1-based numbers or names), in the order of the file."""
    every = trainers(f); out = []; want = []
    for c in chosen or ():
        numbers = [k for k, t in enumerate(every) if t[1] == c or str(k + 1) == str(c)]
        if not numbers: raise Wrong('this patch has no trainer %s' % c)
        want += numbers
    for k, t in enumerate(every):
        if k in want: out += t[2]
    return out

def patched_bytes(f, game):
    """What the patch itself decides in the finished build: {bank: None for a whole bank, or the set of offsets}."""
    nonce, bl = blocks(f); st = Stream(nonce, game); d = dict(bl); out = {}
    if d[b'SIT1']:
        table = unzx0(st.block(b'SIT1')(d[b'SIT1']), SITE_TABLE_MAX); i = 2
        for _ in range(struct.unpack_from('<H', table)[0]):
            b, o, l = struct.unpack_from('<BHH', table, i); i += 5 + l
            out.setdefault(b, set()).update(range(o, o + l))
    for t, body in bl:
        if t == b'PAL1':
            table = unzx0(st.block(b'PAL1', body[0])(body[2 + body[1]:]), SITE_TABLE_MAX); i = 8
            while i < len(table):
                b, o, l = struct.unpack_from('<BHH', table, i); i += 5 + l
                out.setdefault(b, set()).update(range(o, o + l))
    for t, body in bl:
        if t == b'BNK1': out[body[0]] = None
    return out

def select_trainers(entries, only):
    """The entries of a .pok named in only, a list of names as the .pok or the menu spells them, in the .pok's order.
    It selects and orders nothing else. A name it does not have, or cannot use, is an error."""
    usable = [e for e in entries if not any(v == 256 for _, _, v, _ in e[1])]
    for name in only:
        if not any(name in (e[0], sentence_case(e[0])) for e in entries):
            raise Wrong('this .pok has no trainer called %r' % name)
        if not any(name in (e[0], sentence_case(e[0])) for e in usable):
            raise Wrong('trainer %r asks the player for a value, which a patch cannot hold' % name)
    return [e for e in entries if e[0] in only or sentence_case(e[0]) in only]

def import_pok(f, game_path, pok_text, publisher=None, skipped=None, only=None):
    """The patch with the trainers of a .pok added and INF1's publisher set: the same nonce and encrypted blocks, with
    a new KEY1 since the file's checksum changes. Refuses a POKE that lands on a byte the patch changes, or on a bank
    the patch supplies: its target there is not the game's code. Original values in the .pok are not stored.
    only: names of the trainers to import; none: all of them."""
    game = open(game_path, 'rb').read(); snap = Z80Snapshot(game_path)
    nonce, bl = blocks(f); st = Stream(nonce, game); d = dict(bl)
    key = st.block(b'KEY1')(d[b'KEY1'])
    if key[:8] != KEYCHECK: raise Wrong('this is not the game file this patch was made for')
    header = unzx0(st.block(b'NEX1')(d[b'NEX1']), 512); touched = patched_bytes(f, game)
    made = []; entries = parse_pok(pok_text)
    for name, lines in (entries if only is None else select_trainers(entries, only)):
        if any(v == 256 for _, _, v, _ in lines):
            if skipped is not None: skipped.append((name, 'asks the player for a value'))
            continue
        pokes = []
        for bank_field, address, value, original in lines:
            b, o = poke_bank(bank_field, address, snap)
            if not header[18 + b]: raise Wrong('%s: POKE %d is in bank %d, which the build does not have' % (name, address, b))
            if b in touched and (touched[b] is None or o in touched[b]):
                raise Wrong('%s: POKE %d lands on a byte the patch changes' % (name, address))
            have = snap.banks[b][o]
            if original not in (0, have) and skipped is not None:
                skipped.append((name, 'POKE %d: .pok expects %d, this file has %d' % (address, original, have)))
            pokes.append((b, o, value))
        made.append(trn1(sentence_case(name)[:TRAINER_NAME_MAX], pokes))
    head = f[:22]; before = b''; after = b''; seen_key = False
    for t, body in bl:
        if t == b'KEY1': seen_key = True; continue
        if t == b'TRN1': continue
        if t == b'INF1' and publisher:
            text_ = b''.join(l + b'\n' for l in body.split(b'\n') if l and not l.startswith(b'publisher='))
            body = b'publisher=%s\n' % publisher.encode() + text_
        if seen_key: after += block(t, body)
        else: before += block(t, body)
    before += b''.join(block(b'TRN1', m) for m in made)
    plain = KEYCHECK + struct.pack('<I', zlib.crc32(head + before + after)) + key[12:20]
    return head + before + block(b'KEY1', st.block(b'KEY1')(plain)) + after

def original_with_pokes(f, game, chosen, path=None):
    """The player's game with the chosen trainers applied, as a .z80 version 2 or 3 file with its pages stored whole;
    what the loader writes with the clash fix off and a trainer on. The header is the game's own. A version 1 file
    becomes version 2 (48K). Pages other than the RAM banks (ROM images) are not kept."""
    check_key(f, game)
    with tempfile.NamedTemporaryFile(suffix='.z80', dir=os.environ.get('TMPDIR')) as t:
        t.write(game); t.flush(); snap = Z80Snapshot(t.name)
    banks = {k: bytearray(v) for k, v in snap.banks.items()}
    for b, o, v in chosen_pokes(f, chosen):
        if b not in banks: raise Wrong('a trainer POKE is in a bank the game does not have')
        banks[b][o] = v
    if snap.version == 1:
        head = bytearray(game[:30]); pc = game[6:8]; head[6:8] = b'\0\0'
        head[12] = (1 if head[12] == 255 else head[12]) & ~0x20 & 255
        head += struct.pack('<H', 23) + pc + bytes(21)
    else:
        head = bytearray(game[:32 + (game[30] | game[31] << 8)])
    out = bytes(head)
    pages = ((3 + b, b) for b in range(8)) if snap.is128 else ((8, 5), (4, 2), (5, 0))
    for page, b in pages:
        out += b'\xff\xff' + bytes((page,)) + bytes(banks[b])
    return out


def nex_banks(d):
    off = 512; out = {}
    for b in ORDER:
        if d[18 + b]:
            out[b] = d[off:off + BANK]; off += BANK
    if off != len(d):
        raise ValueError('.nex has %d bytes past its banks' % (len(d) - off))
    return out

def block(tag, data):
    return tag + struct.pack('<I', len(data)) + data

def text(fields):
    return ''.join('%s=%s\n' % kv for kv in fields.items() if kv[1] not in (None, '')).encode()

def make(z80, nex, target, info, nonce=None, level=1, rom=0, proof=None, colours=None, trainer_blocks=()):
    game = open(z80, 'rb').read(); out = open(nex, 'rb').read()
    have = snapshot_banks(z80); want = nex_banks(out)
    sites = bytearray(); count = 0; whole = []
    for b, data in want.items():
        if b in have and len(have[b]) == BANK:
            old = have[b]; i = 0
            while i < BANK:
                if old[i] != data[i]:
                    j = i
                    while j < BANK and old[j] != data[j]: j += 1
                    sites += struct.pack('<BHH', b, i, j - i) + data[i:j]; count += 1; i = j
                else:
                    i += 1
        else:
            whole.append((b, data.rstrip(b'\0')))
    if count and 2 + len(sites) > SITE_TABLE_MAX: raise ValueError('the patch site table is too big for a loader')
    nonce = nonce or os.urandom(16)
    st = Stream(nonce, game)
    head = st.block(b'NEX1')(zx0(out[:512]))
    table = st.block(b'SIT1')(zx0(struct.pack('<H', count) + bytes(sites))) if count else b''
    info = dict(info); info.setdefault('credit', CREDIT)
    before = MAGIC + bytes((1, 0)) + nonce + block(b'OPT1', bytes((level, 0)))
    before += block(b'TGT1', text(target)) + block(b'INF1', text(info)) + block(b'PRF1', text(proof or {}))
    before += block(b'ROM1', bytes((rom,)))
    before += b''.join(block(b'TRN1', t) for t in trainer_blocks)
    after = block(b'NEX1', head) + block(b'SIT1', table)
    for b, data in whole:
        body = struct.pack('<BH', b, len(data))
        if data: body += st.block(b'BNK1', b)(zx0(data))
        after += block(b'BNK1', body)
    # Colour sets: changes to the finished banks, each with its own checksum.
    if len(colours or ()) > SETS_MAX: raise ValueError('a patch can have at most %d colour sets' % SETS_MAX)
    for index, (name, path) in enumerate((colours or {}).items()):
        painted = open(path, 'rb').read()
        if painted[:512] != out[:512] or len(painted) != len(out):
            raise ValueError('a colour set must only change banks of the same build')
        paint = nex_banks(painted); changes = bytearray(struct.pack('<II', zlib.crc32(painted), len(painted)))
        for b, data in want.items():
            old = data; i = 0; new = paint[b]
            while i < BANK:
                if old[i] != new[i]:
                    j = i
                    while j < BANK and old[j] != new[j]: j += 1
                    changes += struct.pack('<BHH', b, i, j - i) + new[i:j]; i = j
                else:
                    i += 1
        label = name.encode('ascii')
        if not 1 <= len(label) <= SET_NAME_MAX: raise ValueError('colour set name %r must be 1 to %d characters' % (name, SET_NAME_MAX))
        if len(changes) > SITE_TABLE_MAX: raise ValueError('colour set %r is too big for a loader' % name)
        after += block(b'PAL1', bytes((index, len(label))) + label + st.block(b'PAL1', index)(zx0(bytes(changes))))
    plain = KEYCHECK + struct.pack('<III', zlib.crc32(before + after), zlib.crc32(out), len(out))
    key = st.block(b'KEY1')(plain)
    f = before + block(b'KEY1', key) + after
    return f, dict(sites=count, site_bytes=len(sites), whole=[b for b, _ in whole], whole_bytes=sum(len(d) for _, d in whole))

def blocks(f):
    if f[:4] != MAGIC or f[4] != 1:
        raise Wrong('not a .nxc v1 file')
    nonce = f[6:22]; i = 22; out = []
    while i < len(f):
        if i + 8 > len(f): raise Wrong('file ends inside a block header')
        tag = f[i:i + 4]; n = struct.unpack_from('<I', f, i + 4)[0]; i += 8
        if i + n > len(f): raise Wrong('file ends inside a block')
        out.append((tag, f[i:i + n])); i += n
    return nonce, out

def colour_sets(f):
    """The names of a patch's colour sets, readable without the game."""
    _, bl = blocks(f)
    return [d[2:2 + d[1]].decode() for t, d in bl if t == b'PAL1']

def check_key(f, game):
    """Every check before anything is decompressed. Returns (stream, blocks, file CRC-checked KEY1 values)."""
    nonce, bl = blocks(f)
    tags = [t for t, _ in bl]
    for need in (b'OPT1', b'TGT1', b'INF1', b'KEY1', b'NEX1', b'SIT1'):
        if tags.count(need) != 1: raise Wrong('a required block is missing')
    opt = dict(bl)[b'OPT1']
    if len(opt) < 2: raise Wrong('the options block is too short')
    if opt[0] > LOADER_LEVEL: raise Wrong('this patch needs a newer loader')
    i = 22
    for t, d in bl:
        if t == b'KEY1': break
        i += 8 + len(d)
    keydata = dict(bl)[b'KEY1']
    if len(keydata) != KEY_BYTES: raise Wrong('the key block has the wrong length')
    st = Stream(nonce, game)
    k = st.block(b'KEY1')(keydata)
    if k[:8] != KEYCHECK: raise Wrong('this is not the game file this patch was made for')
    file_crc, crc, size = struct.unpack('<III', k[8:20])
    if zlib.crc32(f[:i] + f[i + 8 + KEY_BYTES:]) != file_crc:
        raise Wrong('this patch file is damaged')
    for t, d in bl:
        if t == b'TRN1': parse_trn1(d)
        if t == b'PAL1' and (len(d) < 2 or not 1 <= d[1] <= SET_NAME_MAX or len(d) < 2 + d[1]):
            raise Wrong('a colour set is damaged')
    return st, bl, crc, size

def apply(f, z80=None, game=None, banks=None, colours=None, chosen=None):
    """The .nex, from the patch and the player's snapshot; raises Wrong otherwise.
    Nothing is decompressed or written until the key and the file's checksum pass, which
    is what keeps a damaged file away from a decompressor with no bounds checks.
    chosen: trainers to apply, by number from 1 or by name, after the base build's checksum."""
    game = game if game is not None else open(z80, 'rb').read()
    st, bl, crc, size = check_key(f, game)
    header = None; table = b''; whole = {}
    for tag, d in bl:
        if tag == b'NEX1': header = unzx0(st.block(b'NEX1')(d), 512)
        elif tag == b'SIT1': table = unzx0(st.block(b'SIT1')(d), SITE_TABLE_MAX) if d else b''
        elif tag == b'BNK1':
            if len(d) < 3: raise Wrong('a bank block is too short')
            b, n = struct.unpack_from('<BH', d)
            if n > BANK or b >= 112 or b in whole: raise Wrong('a bank block is out of range')
            if not n and len(d) != 3: raise Wrong('a bank block is the wrong length')
            whole[b] = (unzx0(st.block(b'BNK1', b)(d[3:]), n) if n else b'')
            if len(whole[b]) != n: raise Wrong('a bank has the wrong length')
    chosen_set = None
    if colours is not None:
        for tag, d in bl:
            if chosen_set is None and tag == b'PAL1' and d[2:2 + d[1]] == colours.encode():
                chosen_set = unzx0(st.block(b'PAL1', d[0])(d[2 + d[1]:]), SITE_TABLE_MAX)
        if chosen_set is None: raise Wrong('this patch has no colour set called %s' % colours)
    if header is None or len(header) != 512: raise Wrong('the .nex header is damaged')
    if banks is None and z80 is None:
        with tempfile.NamedTemporaryFile(suffix='.z80', dir=os.environ.get('TMPDIR')) as t:
            t.write(game); t.flush(); banks = snapshot_banks(t.name)
    have = {k_: bytearray(v) for k_, v in (banks if banks is not None else snapshot_banks(z80)).items()}
    if table:
        if len(table) < 2: raise Wrong('the patch site table is damaged')
        count = struct.unpack_from('<H', table)[0]; i = 2
        for _ in range(count):
            if i + 5 > len(table): raise Wrong('the patch site table is damaged')
            b, o, l = struct.unpack_from('<BHH', table, i); i += 5
            if b not in have or o + l > BANK or i + l > len(table):
                raise Wrong('a patch site is out of range')
            have[b][o:o + l] = table[i:i + l]; i += l
        if i != len(table): raise Wrong('the patch site table is damaged')
    out = bytearray(header); offs = {}
    for b in ORDER:
        if header[18 + b]:
            offs[b] = len(out)
            if b in whole: out += whole[b] + bytes(BANK - len(whole[b]))
            elif b in have and len(have[b]) == BANK: out += have[b]
            else: raise Wrong('bank %d is in neither the patch nor the snapshot' % b)
    if len(out) != size or zlib.crc32(bytes(out)) != crc:
        raise Wrong('the rebuilt .nex fails its checksum')
    if chosen_set is not None:
        if len(chosen_set) < 8: raise Wrong('a colour set is damaged')
        want_crc, want_size = struct.unpack_from('<II', chosen_set); i = 8
        while i < len(chosen_set):
            if i + 5 > len(chosen_set): raise Wrong('a colour set is damaged')
            b, o, l = struct.unpack_from('<BHH', chosen_set, i); i += 5
            if b not in offs or o + l > BANK or i + l > len(chosen_set): raise Wrong('a colour set is out of range')
            out[offs[b] + o:offs[b] + o + l] = chosen_set[i:i + l]; i += l
        if len(out) != want_size or zlib.crc32(bytes(out)) != want_crc:
            raise Wrong('the colour set fails its checksum')
    for b, o, v in chosen_pokes(f, chosen):
        if b not in offs: raise Wrong('a trainer POKE is in a bank the build does not have')
        out[offs[b] + o] = v
    return bytes(out)

def inf1_value(f, key):
    """An INF1 line as a loader takes it: from the first TEXT_READ bytes, ended by a newline; otherwise None."""
    text = dict(blocks(f)[1]).get(b'INF1', b'')[:TEXT_READ]
    start = 0
    while True:
        end = text.find(b'\n', start)
        if end < 0: return None
        if text[start:end].startswith(key.encode() + b'='): return text[start + len(key) + 1:end]
        start = end + 1

def credit_line(f):
    """The menu's credit line, or None: "Patch: a     Colours: b" in MENU_COLUMNS columns, the colours only if the patch has
    a colour set. With both, the gap closes from 5 to 2 before a name is cut, then a keeps at least 11, b what is left."""
    def name(key):
        v = inf1_value(f, key) or b''
        return ''.join(chr(c) if 32 <= c < 127 else '?' for c in v[:CREDIT_NAME])
    a = name('patch_by'); b = name('colours_by') if colour_sets(f) else ''
    if not a and not b: return None
    if not b: return 'Patch: ' + a
    if not a: return 'Colours: ' + b
    a = a[:23 - min(len(b), 12)]; b = b[:23 - len(a)]
    return 'Patch: ' + a + ' ' * min(5, 25 - len(a) - len(b)) + 'Colours: ' + b

def set_credits(f, game, patch_by=None, colours_by=None):
    """The patch with INF1's patch_by and colours_by set, or removed if '': the same nonce and encrypted blocks, with a
    new KEY1 since the file's checksum changes. They go right after any publisher line, and must end within the first
    TEXT_READ bytes, or a loader would never see them. None leaves a key as it is."""
    nonce, bl = blocks(f); st = Stream(nonce, game)
    key = st.block(b'KEY1')(dict(bl)[b'KEY1'])
    if key[:8] != KEYCHECK: raise Wrong('this is not the game file this patch was made for')
    def line(k, v):
        if v is not None and ('\n' in v or not v.isascii() or not v.isprintable()): raise Wrong('a name must be printable ASCII')
        return b'' if not v else b'%s=%s\n' % (k, v.encode())
    head = f[:22]; before = b''; after = b''; seen_key = False
    for t, body in bl:
        if t == b'KEY1': seen_key = True; continue
        if t == b'INF1':
            lines = [l + b'\n' for l in body.split(b'\n') if l]
            old = {k: next((l for l in lines if l.startswith(k + b'=')), b'') for k in (b'patch_by', b'colours_by')}
            new = [line(b'patch_by', patch_by) if patch_by is not None else old[b'patch_by'],
                   line(b'colours_by', colours_by) if colours_by is not None else old[b'colours_by']]
            rest = [l for l in lines if not l.startswith((b'patch_by=', b'colours_by='))]
            first = [l for l in rest if l.startswith(b'publisher=')]
            body = b''.join(first + new + [l for l in rest if l not in first])
            if len(b''.join(first + new)) > TEXT_READ: raise Wrong('the credit lines must end within the first %d bytes of INF1' % TEXT_READ)
        if seen_key: after += block(t, body)
        else: before += block(t, body)
    plain = KEYCHECK + struct.pack('<I', zlib.crc32(head + before + after)) + key[12:20]
    return head + before + block(b'KEY1', st.block(b'KEY1')(plain)) + after

def handoff_bas():
    """The one-line BASIC program browser.cfg merges into the snapshot loader: line 0, IF %x=1 THEN CLS:.nexload
    nexclash.nex. A browser.cfg line cannot branch by itself: IF ... ELSE and ON both fell through to the menu when
    tried from a browser line under JNext, so the branch has to be in a program. A +3DOS file, tokenised by hand."""
    code = b'\xfa%x=1\xcb\xfb:.nexload nexclash.nex\r'
    program = bytes((0, 0)) + struct.pack('<H', len(code)) + code
    head = bytearray(128)
    head[0:11] = b'PLUS3DOS\x1a\x01\x00'
    head[11:15] = struct.pack('<I', 128 + len(program))
    head[15] = 0
    head[16:22] = struct.pack('<HHH', len(program), 0x8000, len(program))
    head[127] = sum(head[:127]) & 255
    return bytes(head) + program

def main(argv):
    import argparse
    if argv[:1] == ['handoff-bas']:
        ap = argparse.ArgumentParser(prog='nxc.py handoff-bas', description='Write NXCHAND.BAS, for browser.cfg.')
        ap.add_argument('-o', '--output', required=True)
        a = ap.parse_args(argv[1:])
        open(a.output, 'wb').write(handoff_bas()); print('wrote', a.output)
        return
    if argv[:1] == ['import-pok']:
        ap = argparse.ArgumentParser(prog='nxc.py import-pok', description="Add a .pok's trainers to a patch.")
        ap.add_argument('patch'); ap.add_argument('pok'); ap.add_argument('game'); ap.add_argument('-o', '--output', required=True)
        ap.add_argument('--publisher', help='INF1 publisher line for the menu, such as "Ocean, 1986"')
        ap.add_argument('--only', help='import only these trainers, comma-separated, as the .pok names them: "Name,Name"')
        a = ap.parse_args(argv[1:]); notes = []
        only = [n.strip() for n in a.only.split(',')] if a.only is not None else None
        try:
            f = import_pok(open(a.patch, 'rb').read(), a.game, open(a.pok, encoding='latin-1').read(), a.publisher, notes, only)
        except Wrong as e:
            raise SystemExit('Refused: %s' % e)
        open(a.output, 'wb').write(f)
        for n, why in notes: print('note: %s: %s' % (n, why))
        for k, t in enumerate(trainers(f)):
            print('%d  %-25s %s' % (k + 1, t[1], ' '.join('bank %d +%d=%d' % p for p in t[2])))
        print('wrote', a.output, len(f), 'bytes')
        return
    if argv[:1] == ['credit']:
        ap = argparse.ArgumentParser(prog='nxc.py credit', description="Set the names on the menu's credit line, in INF1.")
        ap.add_argument('patch'); ap.add_argument('game'); ap.add_argument('-o', '--output', required=True)
        ap.add_argument('--patch-by', help="who made the patch; an empty name removes it")
        ap.add_argument('--colours-by', help="who painted the colours, shown only if the patch has a colour set; an empty name removes it")
        a = ap.parse_args(argv[1:])
        try:
            f = set_credits(open(a.patch, 'rb').read(), open(a.game, 'rb').read(), a.patch_by, a.colours_by)
        except Wrong as e:
            raise SystemExit('Refused: %s' % e)
        open(a.output, 'wb').write(f)
        print('menu line:', credit_line(f)); print('wrote', a.output, len(f), 'bytes')
        return
    ap = argparse.ArgumentParser(description='Apply or list a .nxc patch.')
    ap.add_argument('patch'); ap.add_argument('game', nargs='?'); ap.add_argument('-o', '--output')
    ap.add_argument('--colours', help='a colour set by name; omit for the default; has no effect with --original')
    ap.add_argument('--trainer', action='append', help='a trainer by number from 1 or by name; repeatable')
    ap.add_argument('--original', action='store_true', help='no patch: write the game as a .z80 with the trainers applied')
    a = ap.parse_args(argv); f = open(a.patch, 'rb').read()
    print('colour sets:', ', '.join(['(default)'] + colour_sets(f)))
    print('trainers:', ', '.join(t[1] for t in trainers(f)) or '(none)')
    for t, d in blocks(f)[1]:
        if t in (b'TGT1', b'INF1', b'PRF1'): print(d.decode(errors='replace'), end='')
    if a.game:
        try:
            if a.original: d = original_with_pokes(f, open(a.game, 'rb').read(), a.trainer)
            else: d = apply(f, a.game, colours=a.colours, chosen=a.trainer)
        except Wrong as e: raise SystemExit('Refused: %s' % e)
        open(a.output or 'out.nex', 'wb').write(d); print('wrote', a.output or 'out.nex', hashlib.md5(d).hexdigest())

if __name__ == '__main__':
    main(sys.argv[1:])

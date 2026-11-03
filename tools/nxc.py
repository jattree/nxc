#!/usr/bin/env python3
"""Make and apply .nxc v1 files; the reference the Z80 loader (firmware/nexclash.asm) must match
byte for byte. See spec/NXC-FORMAT.md.

    nxc.py PATCH [GAME] [-o OUT] [--trainer NAME_OR_NUMBER ...] [--original] [--colours NAME]
    nxc.py make NEX GAME -o OUT [--zxdb ENTRY] [--title T] [--publisher "Ocean, 1986"] [--patch-by N] [--colours-by N]
                 [--rom 0|1|2] [--highest-bank N] [--proof KEY=VALUE ...] [--proof-file F] [--colours NAME=NEX ...] [--language NAME=NEX ...]
    nxc.py add-dump PATCH KNOWN_GAME NEW_DUMP -o OUT [--file NAME] [--zxdb ENTRY] [--title TITLE]
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
MAGIC = b'NXC1'; ORDER = [5, 2, 0, 1, 3, 4, 6, 7] + list(range(8, 112)); BANK = 16384; DROP = 256
HEADER = 38; NONCE_AT = 6; CHECK_AT = 22; CHECK_SIZE = 16; MASTER_SIZE = 16
WRAP_CHECK = b'NXC1-KEY'; WRAP_SIZE = 24; TARGET_FIXED = 30; KEY_ROUNDS = 16
KIND_Z80 = 1; KIND_SNA = 2; KIND_NAMES = {KIND_Z80: 'z80', KIND_SNA: 'sna'}
LOADER_LEVEL = 3                                   # this tool does all there is; the Z80 loader is level 2
SCREEN_SIZES = ((1, 49152), (2, 6912), (4, 12288), (8, 12288), (16, 12288)); SCREEN_MAX = 92928; SCREEN_CHUNK = BANK
TARGETS_MAX = 32; FILE_NAME_MAX = 127
SITE_TABLE_MAX = 24576  # what a Next loader holds: three 8K pages
TRAINER_NAME_MAX = 25; TRAINER_POKES_MAX = 255; TRAINERS_SHOWN = 8; POKES_HELD = 128
SET_NAME_MAX = 25; SETS_MAX = 256  # a set's table is held in three pages too: SITE_TABLE_MAX
KIND_COLOURS = 1; KIND_LANGUAGE = 2; KIND_NAMES_SET = {KIND_COLOURS: 'colours', KIND_LANGUAGE: 'language'}
BASE_SPRITE = 1; BASE_PLAIN = 2                    # the sprite build; the plain game, reserved
SET_FIXED = 5; SET_CRC = 4
TEXT_READ = 252; MENU_COLUMNS = 41; CREDIT_NAME = 32  # what a loader reads of INF1, shows, and keeps of a name
CREDIT = "Inspired by Bleugh.biz's nexclash (bleughb/nexclash, GPL-3.0-or-later)"
PROOF_KEYS = ('replay', 'replay_when', 'emulator', 'emulator_when', 'hardware', 'hardware_when', 'coverage', 'coverage_when',
              'display_samples', 'display_exact', 'display_misses', 'display_approved', 'display_model', 'display_when',
              'timing', 'timing_when')

class Wrong(ValueError):
    """The file cannot be applied to this snapshot."""

def absorb(state, data):
    """The one mixing step. state: [s, i, j]."""
    s, i, j = state
    for b in data:
        i = (i + 1) & 255; j = (j + s[i] + b) & 255; s[i], s[j] = s[j], s[i]
    state[1], state[2] = i, j

class Stream:
    """An RC4-style state and the streams made from it. The base is keyed by dump_state or key_state. Each use has its
    own tag and index absorbed into a copy of the base, so a loader can skip a block it does not know."""
    def __init__(self, base):
        self.base = base
    def start(self, tag, index=0):
        """A copy of the base with tag and index absorbed: [s, i, j]."""
        st = [list(self.base[0]), self.base[1], self.base[2]]
        absorb(st, tag + bytes((index,)))
        return st
    @staticmethod
    def output(st, data):
        """data XORed with the state's next output bytes."""
        s, i, j = st; out = bytearray(len(data))
        for n, b in enumerate(data):
            i = (i + 1) & 255; j = (j + s[i]) & 255; s[i], s[j] = s[j], s[i]
            out[n] = b ^ s[(s[i] + s[j]) & 255]
        st[1], st[2] = i, j
        return bytes(out)
    def block(self, tag, index=0):
        """The xor function for one use: tag and index absorbed, 256 bytes dropped."""
        st = self.start(tag, index)
        self.output(st, bytes(DROP))
        return lambda data: self.output(st, data)

def fresh_state():
    return [list(range(256)), 0, 0]

def dump_state(nonce, game):
    """Keyed by one whole dump: nonce, the file, nonce."""
    st = fresh_state(); absorb(st, nonce + game + nonce)
    return Stream(st)

def key_state(nonce, master):
    """Keyed by the patch's master key: nonce, key, nonce, 16 times. One pass of 48 bytes would leave about 173 of the
    256 entries at their starting values, measured; 8 passes reach what a random permutation shows, and 16 is double that."""
    st = fresh_state(); absorb(st, (nonce + master + nonce) * KEY_ROUNDS)
    return Stream(st)

def check_value(f, st):
    """The file's keyed check: all of it but the check field, absorbed after CHK1 and index 0 under the master state."""
    s = st.start(b'CHK1')
    absorb(s, f[:CHECK_AT]); absorb(s, f[HEADER:])
    Stream.output(s, bytes(DROP))
    return Stream.output(s, bytes(CHECK_SIZE))

def zx0(data):
    if not os.path.exists(os.path.join(ZX0_DIR, 'zx0')):
        raise Wrong('making a patch needs the zx0 compressor: set NXC_ZX0_DIR to its folder')
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

def sna_places(data):
    """(is128, 7FFD, {bank: its offsets in the file}) of a .sna: 27 bytes of registers, then 48K as banks 5, 2 and the one
    paged at 0xC000. A 128K file adds PC, 7FFD and a TR-DOS byte, then the banks in rising order other than 5, 2 and the
    paged one. A paged bank 5 or 2 is in the file twice, which is why there are two 128K lengths."""
    if len(data) == 27 + 3 * BANK:
        return False, 0, {5: [27], 2: [27 + BANK], 0: [27 + 2 * BANK]}
    if len(data) not in (131103, 147487): raise ValueError('a .sna is 49179, 131103 or 147487 bytes, not %d' % len(data))
    port = data[27 + 3 * BANK + 2]; top = port & 7; places = {5: [27], 2: [27 + BANK]}
    places.setdefault(top, []).append(27 + 2 * BANK)
    rest = [b for b in range(8) if b not in (2, 5, top)]
    if 27 + 3 * BANK + 4 + len(rest) * BANK != len(data): raise ValueError('a .sna of this length cannot page bank %d' % top)
    for n, b in enumerate(rest): places[b] = [27 + 3 * BANK + 4 + n * BANK]
    return True, port, places

class SnaSnapshot:
    """The banks of a .sna, as the same attributes NexClash's Z80Snapshot has."""
    version = 0
    def __init__(self, data):
        self.is128, self.port7ffd, places = sna_places(data)
        self.banks = {b: data[at[0]:at[0] + BANK] for b, at in places.items()}

def kind_of_name(name):
    ext = os.path.splitext(name)[1].lower()
    if ext == '.z80': return KIND_Z80
    if ext == '.sna': return KIND_SNA
    raise Wrong('%s: a game file is .z80 or .sna' % name)

def snapshot_of(game, kind):
    """The snapshot object for a dump's bytes, of the kind its target entry names."""
    try:
        if kind == KIND_SNA: return SnaSnapshot(game)
        with tempfile.NamedTemporaryFile(suffix='.z80', dir=os.environ.get('TMPDIR')) as t:
            t.write(game); t.flush()
            return Z80Snapshot(t.name)
    except (ValueError, IndexError) as e:
        raise Wrong('the game file is damaged: %s' % e)

def snapshot_banks(path):
    with open(path, 'rb') as g:
        return {k: bytes(v) for k, v in snapshot_of(g.read(), kind_of_name(path)).banks.items()}

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

def trn1(name, pokes):
    """One TRN1 block's data, flags 0. pokes: (bank, offset, value)."""
    label = name.encode('ascii')
    if not 1 <= len(label) <= TRAINER_NAME_MAX: raise ValueError('trainer name %r must be 1 to %d characters' % (name, TRAINER_NAME_MAX))
    if not 1 <= len(pokes) <= TRAINER_POKES_MAX: raise ValueError('trainer %r must have 1 to %d POKEs' % (name, TRAINER_POKES_MAX))
    return bytes((0, len(label))) + label + bytes((len(pokes),)) + b''.join(struct.pack('<BHB', *p) for p in pokes)

def parse_trn1(d):
    """(flags, name, [(bank, offset, value)]) from a TRN1 block's data, or Wrong."""
    if len(d) < 3: raise Wrong('a trainer block is damaged')
    size = d[1]
    if size < 1 or size > TRAINER_NAME_MAX or len(d) < 3 + size: raise Wrong('a trainer block is damaged')
    if d[0]: raise Wrong('a trainer block has flags this reader does not know')
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
    st, bl = check_key(f, game)[:2]; out = {}
    sit = dict(bl)[b'SIT1']
    if sit:
        table = unzx0(st.block(b'SIT1')(sit), SITE_TABLE_MAX); i = 2
        for _ in range(struct.unpack_from('<H', table)[0]):
            b, o, l = struct.unpack_from('<BHH', table, i); i += 5 + l
            out.setdefault(b, set()).update(range(o, o + l))
    for t, body in bl:
        if t == b'SET1':
            e = parse_set(body)
            for b, o, data in set_entries(unzx0(st.block(b'SET1', e['stream'])(e['data']), SITE_TABLE_MAX)):
                out.setdefault(b, set()).update(range(o, o + len(data)))
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
    a new check value. Refuses a POKE that lands on a byte the patch changes, or on a bank the patch supplies: its target
    there is not the game's own code. Original values in the .pok are not stored.
    only: names of the trainers to import; none: all of them."""
    with open(game_path, 'rb') as g: game = g.read()
    opened = check_key(f, game); st, bl = opened[:2]
    snap = snapshot_of(game, opened.target['kind'])
    header = unzx0(st.block(b'NEX1')(dict(bl)[b'NEX1']), 512); touched = patched_bytes(f, game)
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
    names = [parse_trn1(m)[1] for m in made]
    if len(set(names)) != len(names): raise Wrong('two trainers would have one name on the menu')
    out = []
    for t, body in bl:
        if t == b'TRN1': continue
        if t == b'OUT1': out += [[b'TRN1', m] for m in made]
        if t == b'INF1' and publisher:
            text_ = b''.join(l + b'\n' for l in body.split(b'\n') if l and not l.startswith(b'publisher='))
            body = b'publisher=%s\n' % publisher.encode() + text_
        out.append([t, body])
    return seal(f[:CHECK_AT], out, st)

def original_with_pokes(f, game, chosen, path=None):
    """The player's game with the chosen trainers applied; what the loader writes with the clash fix off. With no trainer it
    is the game file itself, unchecked, as the format says. With one, the game must unlock the patch, and a .z80 becomes
    version 2 or 3 with its pages stored whole, under its own header (a version 1 file becomes version 2, 48K; pages other
    than the RAM banks are not kept), and a .sna keeps its layout."""
    if not chosen: return game
    opened = check_key(f, game); kind = opened.target['kind']
    snap = snapshot_of(game, kind)
    banks = {k: bytearray(v) for k, v in snap.banks.items()}
    pokes = chosen_pokes(f, chosen)
    for b, o, v in pokes:
        if b not in banks: raise Wrong('a trainer POKE is in a bank the game does not have')
        banks[b][o] = v
    if kind == KIND_SNA: return sna_with(game, snap, pokes)
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

def sna_with(game, snap, pokes):
    """A .sna with POKEs in place, in every place a bank is held."""
    out = bytearray(game); places = sna_places(game)[2]
    for b, o, v in pokes:
        for at in places[b]: out[at + o] = v
    return bytes(out)

def screen_size(flags):
    """The bytes between a .nex's header and its banks, from its byte 10, as .nexload reads them: a palette of 512 unless
    bit 7 is set or a ULA, hi-res or hi-colour screen is there; then each screen listed. Bits 5 and 6 are V1.3's screens."""
    if not flags: return 0
    if flags & 0x60: raise Wrong('a .nex loading screen of V1.3 (byte 10 has bit 5 or 6 set) cannot be packaged')
    return (0 if flags & 0x9A else 512) + sum(n for bit, n in SCREEN_SIZES if flags & bit)

def check_nex(d):
    """What a patch can hold: a .nex V1.0 to V1.2 with, between its header and banks, a loading screen and nothing else."""
    if len(d) < 512 or d[:4] != b'Next' or d[4:8] not in (b'V1.0', b'V1.1', b'V1.2'): raise ValueError('not a .nex V1.0 to V1.2')
    screen_size(d[10])
    if any(v > 1 for v in d[18:130]): raise ValueError('a .nex bank flag must be 0 or 1')
    if sum(d[18:130]) != d[9]: raise ValueError('a .nex must count the banks it lists')

def nex_screen(d):
    return d[512:512 + screen_size(d[10])]

def nex_banks(d):
    off = 512 + screen_size(d[10]); out = {}
    for b in ORDER:
        if d[18 + b]:
            out[b] = d[off:off + BANK]; off += BANK
    if off != len(d):
        raise ValueError('.nex has %d bytes past its banks' % (len(d) - off))
    return out

def block(tag, data):
    return tag + struct.pack('<I', len(data)) + data

def text(fields):
    made = ''.join('%s=%s\n' % kv for kv in fields.items() if kv[1] not in (None, ''))
    for line in made.split('\n'):
        if not line.isascii() or not (line.isprintable() or not line): raise ValueError('text must be printable ASCII: %r' % line)
    return made.encode()

def check_file_name(name):
    """A target's file: a bare name, or Wrong. name: bytes. It is never a path, so it can never open another path."""
    if not 1 <= len(name) <= FILE_NAME_MAX: raise Wrong('a game file name must be 1 to %d bytes' % FILE_NAME_MAX)
    if any(c < 32 or c > 126 or c in b'/\\:*?"<>|' for c in name) or b'..' in name or name[:1] == b' ' or name[-1:] in (b' ', b'.'):
        raise Wrong('a game file name must be a bare name, not %r' % name)

def target_block(index, kind, game, nonce, master, fields):
    """One TGT1 block's data for one accepted dump."""
    if kind not in KIND_NAMES: raise ValueError('unknown container kind')
    name = str(fields.get('file') or '')
    check_file_name(name.encode('latin-1', 'replace'))
    lines = {k: fields.get(k) for k in ('file', 'title', 'zxdb_entry')}
    lines['md5'] = hashlib.md5(game).hexdigest()
    body = text(lines)
    if not parse_target_text(body)[0]: raise Wrong('the file name must end within the first %d bytes' % TEXT_READ)
    wrap = dump_state(nonce, game).block(b'TGT1', index)(WRAP_CHECK + master)
    return struct.pack('<BBI', index, kind, len(game)) + wrap + body

def parse_target_text(body):
    """(file, title) from a TGT1 block's text as a reader takes them: within TEXT_READ bytes, ended by a newline."""
    window = body[:TEXT_READ]; found = {}
    for line in window.split(b'\n')[:-1]:
        k, _, v = line.partition(b'=')
        found.setdefault(k, v)
    return found.get(b'file'), found.get(b'title')

def parse_target(d):
    """A TGT1 block's fields, or Wrong: index, kind, length, wrap, file, title and its text."""
    if len(d) < TARGET_FIXED: raise Wrong('a target block is too short')
    index, kind, length = struct.unpack_from('<BBI', d)
    body = d[TARGET_FIXED:]; name, title = parse_target_text(body)
    if name is None: raise Wrong('a target block has no file name')
    check_file_name(name)
    return dict(index=index, kind=kind, length=length, wrap=d[6:TARGET_FIXED], file=name.decode('ascii'), title=title, text=body)

def targets(f):
    """Every target entry, readable without the game."""
    return [parse_target(d) for t, d in blocks(f)[1] if t == b'TGT1']

def proof_text(proof):
    """PRF1's text: only the keys the format defines. Nothing merged: a replay is not an emulator run, and neither is hardware."""
    for k in proof or ():
        if k not in PROOF_KEYS: raise ValueError('%s is not a PRF1 key' % k)
    return text(proof or {})

def seal(head, bl, st):
    """The file from its header's first 22 bytes and its blocks, with the check value worked out."""
    f = bytes(head) + bytes(CHECK_SIZE) + b''.join(block(t, d) for t, d in bl)
    return f[:CHECK_AT] + check_value(f, st) + f[HEADER:]

def language_info(game_language=None, codes=(), text_by=None, sets=()):
    """INF1's language keys: game_language, language_codes, text_by. codes: 'NAME=CODE' of sets the patch has, by name."""
    code = re.compile(r'[a-z]{2,3}\Z'); out = {}
    if game_language:
        if not code.match(game_language): raise Wrong('%s is not an ISO 639 code' % game_language)
        out['game_language'] = game_language
    pairs = []
    for item in codes:
        if '=' not in item: raise Wrong('%s is not NAME=CODE' % item)
        name, value = item.split('=', 1)
        if not code.match(value): raise Wrong('%s is not an ISO 639 code' % value)
        if name not in sets: raise Wrong('the patch has no language set %s' % name)
        if any(c in name for c in ',='): raise Wrong('a language with a code cannot have , or = in its name')
        pairs.append('%s=%s' % (name, value))
    if pairs: out['language_codes'] = ','.join(pairs)
    if text_by:
        if not text_by.isascii() or not text_by.isprintable(): raise Wrong('a name must be printable ASCII')
        out['text_by'] = text_by
    return out

def make(z80, nex, target, info, nonce=None, level=None, rom=0, proof=None, colours=None, trainer_blocks=(), master=None, more_dumps=(), languages=None, highest_bank=None):
    """A patch from a game file (.z80 or .sna) and the .nex built from it. colours and languages: {name: path of the .nex
    with it, or (path, choice)}. more_dumps: (path, target fields) of others accepted. Before anything is returned, every
    dump named must rebuild exactly that .nex."""
    with open(z80, 'rb') as g: game = g.read()
    with open(nex, 'rb') as g: out = g.read()
    check_nex(out)
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
    nonce = nonce or os.urandom(16); master = master or os.urandom(MASTER_SIZE)
    st = key_state(nonce, master)
    head = st.block(b'NEX1')(zx0(out[:512]))
    table = st.block(b'SIT1')(zx0(struct.pack('<H', count) + bytes(sites))) if count else b''
    info = dict(info); info.setdefault('credit', CREDIT)
    bl = [[b'TGT1', target_block(0, kind_of_name(z80), game, nonce, master, target)], [b'INF1', text(info)], [b'PRF1', proof_text(proof)], [b'ROM1', bytes((rom,))]]
    names = [parse_trn1(t)[1] for t in trainer_blocks]
    if len(set(names)) != len(names): raise ValueError('two trainers have one name')
    bl += [[b'TRN1', t] for t in trainer_blocks]
    bl += [[b'OUT1', st.block(b'OUT1')(struct.pack('<II', zlib.crc32(out), len(out)))], [b'NEX1', head], [b'SIT1', table]]
    for b, data in whole:
        body = struct.pack('<BH', b, len(data))
        if data: body += st.block(b'BNK1', b)(zx0(data))
        bl.append([b'BNK1', body])
    # Sets: changes to the finished banks, each with the CRC of the whole file with it alone.
    screen_of_out = nex_screen(out)
    chosen = [(KIND_COLOURS, n, v) for n, v in (colours or {}).items()] + [(KIND_LANGUAGE, n, v) for n, v in (languages or {}).items()]
    if len(chosen) > SETS_MAX: raise ValueError('a patch can have at most %d sets' % SETS_MAX)
    made = []; next_choice = {}
    for stream_index, (kind, name, source) in enumerate(chosen):
        path, choice = source if isinstance(source, tuple) else (source, None)
        next_choice[kind] = next_choice.get(kind, 0) + 1
        choice = next_choice[kind] if choice is None else choice
        with open(path, 'rb') as g: painted = g.read()
        if painted[:512] != out[:512] or len(painted) != len(out) or nex_screen(painted) != screen_of_out:
            raise ValueError('a set must only change banks of the same build')
        paint = nex_banks(painted); changes = bytearray(struct.pack('<I', zlib.crc32(painted))); ranges = []
        for b in sorted(want):
            data = want[b]; i = 0; new = paint[b]
            while i < BANK:
                if data[i] != new[i]:
                    j = i
                    while j < BANK and data[j] != new[j]: j += 1
                    changes += struct.pack('<BHH', b, i, j - i) + new[i:j]; ranges.append((b, i, j)); i = j
                else:
                    i += 1
        label = name.encode('ascii')
        if not 1 <= len(label) <= SET_NAME_MAX: raise ValueError('set name %r must be 1 to %d characters' % (name, SET_NAME_MAX))
        if len(changes) > SITE_TABLE_MAX: raise ValueError('set %r is too big for a loader' % name)
        made.append((kind, name, ranges))
        body = bytes((stream_index, kind, choice, BASE_SPRITE, len(label))) + label + st.block(b'SET1', stream_index)(zx0(bytes(changes)))
        bl.append([b'SET1', body])
    for one in made:
        for other in made:
            if one[0] < other[0]:
                clash = first_overlap(one[2], other[2])
                if clash: raise ValueError('sets %r and %r can be chosen together but both change bank %d offset %d' % (one[1], other[1], clash[0], clash[1]))
    if len({(e[0], e[1]) for e in made}) != len(made): raise ValueError('two sets of one kind have one name')
    screen = nex_screen(out)
    for k in range(0, len(screen), SCREEN_CHUNK):
        part = screen[k:k + SCREEN_CHUNK]; index = k // SCREEN_CHUNK; plain = part.rstrip(b'\0')
        bl.append([b'SCR1', struct.pack('<BH', index, len(plain)) + (st.block(b'SCR1', index)(zx0(plain)) if plain else b'')])
    wanted = level if level is not None else level_for([kind_of_name(z80)], bool(screen))
    least = lowest_memory(out)
    if highest_bank is None: highest_bank = least
    if not least <= highest_bank <= 111: raise ValueError('the highest bank must be from %d, which the .nex needs, to 111' % least)
    bl.insert(0, [b'OPT1', bytes((wanted, 0, highest_bank))])
    f = seal(MAGIC + bytes((1, 0)) + nonce, bl, st)
    if apply(f, game=game) != out: raise Wrong('the patch does not rebuild the build it was made from')
    for path, fields in more_dumps:
        with open(path, 'rb') as g: f = add_target(f, game, g.read(), kind_of_name(path), fields)
    return f, dict(sites=count, site_bytes=len(sites), whole=[b for b, _ in whole], whole_bytes=sum(len(d) for _, d in whole))

def lowest_memory(nex):
    """The highest 16K bank a .nex is known to need: the highest it lists, or past a 1MB Next's 47 if its header asks for 1792K.
    Pages used only at run time, such as Layer 2 buffers, are not in the file: an author can only raise this."""
    listed = [b for b in range(112) if nex[18 + b]]
    return max(listed + ([48] if nex[8] else []) + [0])

def memory_text(bank):
    return '%dK of RAM, up to 16K bank %d: %s' % ((bank + 1) * 16, bank, 'a 1MB Next has it' if bank <= 47 else 'needs a 2MB Next')

def level_for(kinds, screen=False):
    """OPT1's level: 3 with only .sna targets, otherwise 2 with a loading screen, otherwise 1."""
    return 3 if KIND_Z80 not in kinds else 2 if screen else 1

def add_target(f, known_game, new_game, kind, fields):
    """The patch accepting one more dump. known_game unlocks it. Refused unless the new dump rebuilds the same .nex, byte
    for byte; only the banks matter, as the .nex carries its own start-up state."""
    opened = check_key(f, known_game); st, bl = opened[:2]
    have = targets(f)
    if len(have) >= TARGETS_MAX: raise Wrong('a patch can accept at most %d dumps' % TARGETS_MAX)
    digest = hashlib.md5(new_game).hexdigest().encode()
    if any(b'md5=' + digest + b'\n' in t['text'] for t in have): raise Wrong('this patch already accepts that dump')
    name = str(fields.get('file') or '').encode('latin-1', 'replace')
    if any(t['file'].lower().encode() == name.lower() for t in have): raise Wrong('this patch already has a target with that file name')
    if not fields.get('title') and have and have[0]['title']: fields = dict(fields, title=have[0]['title'].decode('ascii', 'replace'))
    nonce = f[NONCE_AT:CHECK_AT]
    entry = target_block(len(have), kind, new_game, nonce, opened.master, fields)
    out = []; last = max(i for i, (t, _) in enumerate(bl) if t == b'TGT1')
    for i, (t, d) in enumerate(bl):
        out.append([t, d])
        if i == last: out.append([b'TGT1', entry])
    kinds = [t['kind'] for t in have] + [kind]
    for e in out:
        if e[0] == b'OPT1': e[1] = bytes((level_for(kinds, any(t == b'SCR1' for t, _ in bl)), 0, e[1][2]))
    made = seal(f[:CHECK_AT], out, st)
    check_structure(blocks(made)[1])
    try:
        same = apply(made, game=new_game) == apply(f, game=known_game)
    except Wrong as e:
        raise Wrong('that dump does not rebuild the same banks: %s' % e)
    if not same: raise Wrong('that dump does not rebuild the same banks')
    return made

def blocks(f):
    """The nonce and blocks, or Wrong: every length is checked against the file."""
    if len(f) < HEADER or f[:4] != MAGIC or f[4] != 1 or f[5] != 0:
        raise Wrong('not a .nxc v1 file')
    nonce = f[NONCE_AT:CHECK_AT]; i = HEADER; out = []
    while i < len(f):
        if i + 8 > len(f): raise Wrong('file ends inside a block header')
        tag = f[i:i + 4]; n = struct.unpack_from('<I', f, i + 4)[0]; i += 8
        if i + n > len(f): raise Wrong('file ends inside a block')
        out.append((tag, f[i:i + n])); i += n
    return nonce, out

def parse_set(d):
    """The clear part of a SET1 block, or Wrong."""
    if len(d) < SET_FIXED or not 1 <= d[4] <= SET_NAME_MAX or len(d) < SET_FIXED + d[4]: raise Wrong('a set block is damaged')
    return dict(stream=d[0], kind=d[1], choice=d[2], base=d[3], name=d[SET_FIXED:SET_FIXED + d[4]], data=d[SET_FIXED + d[4]:])

def set_entries(table):
    """The replacements in a set's table: (bank, offset, bytes). They must be in rising order with none overlapping."""
    if len(table) < SET_CRC: raise Wrong('a set is damaged')
    i = SET_CRC; out = []; last = (0, 0)
    while i < len(table):
        if i + 5 > len(table): raise Wrong('a set is damaged')
        b, o, l = struct.unpack_from('<BHH', table, i); i += 5
        if not l or b >= 112 or o + l > BANK or i + l > len(table): raise Wrong('a set is out of range')
        if (b, o) < last: raise Wrong('a set is not in order, or overlaps itself')
        out.append((b, o, table[i:i + l])); i += l; last = (b, o + l)
    return out

def first_overlap(a, b):
    """The first place two sorted lists of (bank, start, end) overlap, or None. One pass of each."""
    i = j = 0
    while i < len(a) and j < len(b):
        x, y = a[i], b[j]
        if x[0] < y[0] or (x[0] == y[0] and x[2] <= y[1]): i += 1
        elif y[0] < x[0] or (y[0] == x[0] and y[2] <= x[1]): j += 1
        else: return x[0], max(x[1], y[1])
    return None

def sets(f):
    """Every set block, readable without the game: stream, kind, choice, base, name, data."""
    return [parse_set(d) for t, d in blocks(f)[1] if t == b'SET1']

def offered(f, kind):
    """The sets of a kind a loader offers, in file order: those whose base is the sprite build."""
    return [e for e in sets(f) if e['kind'] == kind and e['base'] == BASE_SPRITE]

def colour_sets(f):
    """The names of a patch's colour sets, readable without the game."""
    return [e['name'].decode('ascii', 'replace') for e in offered(f, KIND_COLOURS)]

def languages(f):
    """The names of a patch's language sets, readable without the game."""
    return [e['name'].decode('ascii', 'replace') for e in offered(f, KIND_LANGUAGE)]

def check_structure(bl):
    """Everything that can be checked without the game, in the order a loader meets it: the first step of every route."""
    tags = [t for t, _ in bl]; indices = set()
    for need in (b'OPT1', b'INF1', b'OUT1', b'NEX1', b'SIT1'):
        if tags.count(need) != 1: raise Wrong('a required block is missing or repeated')
    d = dict(bl)
    opt = d[b'OPT1']
    if len(opt) != 3: raise Wrong('the options block must be 3 bytes')
    if opt[2] > 111: raise Wrong('the options block names a bank that cannot be')
    if opt[0] > LOADER_LEVEL or opt[1]: raise Wrong('this patch needs a newer loader')
    if len(d[b'OUT1']) != 8: raise Wrong('the output block has the wrong length')
    count = kinds = 0
    for t, data in bl:
        if t == b'TGT1':
            e = parse_target(data)
            if e['index'] != count or count >= TARGETS_MAX: raise Wrong('a target block is out of place')
            count += 1; kinds += e['kind'] in KIND_NAMES
        elif t == b'TRN1': parse_trn1(data)
        elif t == b'SET1':
            index = parse_set(data)['stream']
            if index in indices: raise Wrong('a set repeats a stream index')
            indices.add(index)
    if not kinds: raise Wrong('this patch needs a newer loader' if count else 'a required block is missing or repeated')
    if b'SCR1' in tags and opt[0] < 2: raise Wrong('a patch with a loading screen must say level 2 or above')

class Opened(tuple):
    """What check_key found: (stream, blocks, .nex CRC, .nex length), with .master and .target."""
    master = None; target = None

def check_key(f, game):
    """The one validation route: every check before anything is decompressed. The file's shape, then the game against each
    target entry of its length, the master key, the keyed check over the file. Returns an Opened."""
    nonce, bl = blocks(f)
    check_structure(bl)
    base = None; found = None; master = None
    for t, d in bl:
        if t != b'TGT1': continue
        e = parse_target(d)
        if e['kind'] not in KIND_NAMES or e['length'] != len(game): continue
        if base is None: base = dump_state(nonce, game)
        plain = base.block(b'TGT1', e['index'])(e['wrap'])
        if plain[:8] == WRAP_CHECK:
            found, master = e, plain[8:]
            break
    if found is None: raise Wrong('this is not the game file this patch was made for')
    st = key_state(nonce, master)
    if check_value(f, st) != f[CHECK_AT:HEADER]: raise Wrong('this patch file is damaged')
    crc, size = struct.unpack('<II', st.block(b'OUT1')(dict(bl)[b'OUT1']))
    done = Opened((st, bl, crc, size)); done.master = master; done.target = found
    return done

def read_screen(bl, st, header):
    """What lies between the .nex's header and its banks, from its SCR1 blocks: one for each 16K, as the header sizes it."""
    size = screen_size(header[10]); chunks = (size + SCREEN_CHUNK - 1) // SCREEN_CHUNK; parts = {}
    for tag, d in bl:
        if tag != b'SCR1': continue
        if len(d) < 3: raise Wrong('a screen block is too short')
        k, n = struct.unpack_from('<BH', d)
        if k >= chunks or k in parts: raise Wrong('a screen block is out of range')
        room = min(SCREEN_CHUNK, size - k * SCREEN_CHUNK)
        if n > room or (not n and len(d) != 3): raise Wrong('a screen block is the wrong length')
        plain = unzx0(st.block(b'SCR1', k)(d[3:]), n) if n else b''
        if len(plain) != n: raise Wrong('a screen block is the wrong length')
        parts[k] = plain + bytes(room - n)
    if len(parts) != chunks: raise Wrong('a screen block is missing')
    return b''.join(parts[k] for k in range(chunks))

def apply(f, z80=None, game=None, banks=None, colours=None, chosen=None, language=None):
    """The .nex, from the patch and the player's snapshot; raises Wrong otherwise.
    Nothing is decompressed or written until the key and the keyed check pass, which is
    what keeps a damaged file away from a decompressor with no bounds checks.
    colours, language: a set of each kind, by name. chosen: trainers to apply, by number from 1 or by name, after the
    output's checksum."""
    if game is None:
        with open(z80, 'rb') as g: game = g.read()
    opened = check_key(f, game); st, bl, crc, size = opened[:4]
    header = unzx0(st.block(b'NEX1')(dict(bl)[b'NEX1']), 512)
    if len(header) != 512 or header[:4] != b'Next': raise Wrong('the .nex header is damaged')
    if any(header[18 + b] for b in range(dict(bl)[b'OPT1'][2] + 1, 112)): raise Wrong('the options block says less memory than the .nex lists')
    d = dict(bl)[b'SIT1']
    table = unzx0(st.block(b'SIT1')(d), SITE_TABLE_MAX) if d else b''
    whole = {}
    for tag, d in bl:
        if tag == b'BNK1':
            if len(d) < 3: raise Wrong('a bank block is too short')
            b, n = struct.unpack_from('<BH', d)
            if n > BANK or b >= 112 or b in whole: raise Wrong('a bank block is out of range')
            if not header[18 + b]: raise Wrong('a bank block is for a bank the .nex does not list')
            if not n and len(d) != 3: raise Wrong('a bank block is the wrong length')
            whole[b] = (unzx0(st.block(b'BNK1', b)(d[3:]), n) if n else b'')
            if len(whole[b]) != n: raise Wrong('a bank has the wrong length')
    selected = []
    for kind, wanted in ((KIND_COLOURS, colours), (KIND_LANGUAGE, language)):
        if wanted is None: continue
        found = [e for e in offered(f, kind) if e['name'] == wanted.encode()]
        if not found: raise Wrong('this patch has no %s set called %s' % (KIND_NAMES_SET[kind], wanted))
        one = unzx0(st.block(b'SET1', found[0]['stream'])(found[0]['data']), SITE_TABLE_MAX)
        selected.append((one, set_entries(one)))
    if len(selected) == 2:
        spans = [[(b, o, o + len(data)) for b, o, data in entries] for _, entries in selected]
        if first_overlap(*spans): raise Wrong('two sets chosen together change the same bytes')
    if banks is None: banks = snapshot_of(game, opened.target['kind']).banks
    have = {k_: bytearray(v) for k_, v in banks.items()}
    if table:
        if len(table) < 2: raise Wrong('the patch site table is damaged')
        count = struct.unpack_from('<H', table)[0]; i = 2
        for _ in range(count):
            if i + 5 > len(table): raise Wrong('the patch site table is damaged')
            b, o, l = struct.unpack_from('<BHH', table, i); i += 5
            if b not in have or b >= 112 or not header[18 + b] or b in whole or o + l > BANK or i + l > len(table):
                raise Wrong('a patch site is out of range')
            have[b][o:o + l] = table[i:i + l]; i += l
        if i != len(table): raise Wrong('the patch site table is damaged')
    out = bytearray(header) + read_screen(bl, st, header); offs = {}
    for b in ORDER:
        if header[18 + b]:
            offs[b] = len(out)
            if b in whole: out += whole[b] + bytes(BANK - len(whole[b]))
            elif b in have and len(have[b]) == BANK: out += have[b]
            else: raise Wrong('bank %d is in neither the patch nor the snapshot' % b)
    if len(out) != size: raise Wrong('the rebuilt .nex fails its checksum')
    expected = crc
    for one, entries in selected:
        expected ^= struct.unpack_from('<I', one)[0] ^ crc
        for b, o, data in entries:
            if b not in offs: raise Wrong('a set is out of range')
            out[offs[b] + o:offs[b] + o + len(data)] = data
    if zlib.crc32(bytes(out)) != expected: raise Wrong('the rebuilt .nex fails its checksum')
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
    new check value. They go right after any publisher line, and must end within the first TEXT_READ bytes, or a loader
    would never see them. None leaves a key as it is."""
    st, bl = check_key(f, game)[:2]
    def line(k, v):
        if v is not None and ('\n' in v or not v.isascii() or not v.isprintable()): raise Wrong('a name must be printable ASCII')
        return b'' if not v else b'%s=%s\n' % (k, v.encode())
    out = []
    for t, body in bl:
        if t == b'INF1':
            lines = [l + b'\n' for l in body.split(b'\n') if l]
            old = {k: next((l for l in lines if l.startswith(k + b'=')), b'') for k in (b'patch_by', b'colours_by')}
            new = [line(b'patch_by', patch_by) if patch_by is not None else old[b'patch_by'],
                   line(b'colours_by', colours_by) if colours_by is not None else old[b'colours_by']]
            rest = [l for l in lines if not l.startswith((b'patch_by=', b'colours_by='))]
            first = [l for l in rest if l.startswith(b'publisher=')]
            body = b''.join(first + new + [l for l in rest if l not in first])
            if len(b''.join(first + new)) > TEXT_READ: raise Wrong('the credit lines must end within the first %d bytes of INF1' % TEXT_READ)
        out.append([t, body])
    return seal(f[:CHECK_AT], out, st)

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

def refuse_same(output, *inputs):
    """An output path must not be any of its own inputs."""
    for path in inputs:
        if path and os.path.exists(output) and os.path.samefile(output, path):
            raise Wrong('the output %s is one of the inputs' % output)

def read_file(path):
    with open(path, 'rb') as g: return g.read()

def main(argv):
    try:
        run(argv)
    except (Wrong, OSError) as e:
        raise SystemExit('Refused: %s' % e)
    except (ValueError, subprocess.CalledProcessError) as e:
        raise SystemExit('Cannot make that: %s' % e)

def run(argv):
    import argparse
    if argv[:1] == ['handoff-bas']:
        ap = argparse.ArgumentParser(prog='nxc.py handoff-bas', description='Write NXCHAND.BAS, for browser.cfg.')
        ap.add_argument('-o', '--output', required=True)
        a = ap.parse_args(argv[1:])
        with open(a.output, 'wb') as g: g.write(handoff_bas())
        print('wrote', a.output)
        return
    if argv[:1] == ['import-pok']:
        ap = argparse.ArgumentParser(prog='nxc.py import-pok', description="Add a .pok's trainers to a patch.")
        ap.add_argument('patch'); ap.add_argument('pok'); ap.add_argument('game'); ap.add_argument('-o', '--output', required=True)
        ap.add_argument('--publisher', help='INF1 publisher line for the menu, such as "Ocean, 1986"')
        ap.add_argument('--only', help='import only these trainers, comma-separated, as the .pok names them: "Name,Name"')
        a = ap.parse_args(argv[1:]); notes = []
        only = [n.strip() for n in a.only.split(',')] if a.only is not None else None
        refuse_same(a.output, a.game, a.pok)
        with open(a.pok, encoding='latin-1') as g: pok = g.read()
        f = import_pok(read_file(a.patch), a.game, pok, a.publisher, notes, only)
        with open(a.output, 'wb') as g: g.write(f)
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
        refuse_same(a.output, a.game)
        f = set_credits(read_file(a.patch), read_file(a.game), a.patch_by, a.colours_by)
        with open(a.output, 'wb') as g: g.write(f)
        print('menu line:', credit_line(f)); print('wrote', a.output, len(f), 'bytes')
        return
    if argv[:1] == ['make']:
        ap = argparse.ArgumentParser(prog='nxc.py make', description="Package a finished .nex and the game it was built from as a patch.")
        ap.add_argument('nex'); ap.add_argument('game', help='the .z80 or .sna the .nex was built from'); ap.add_argument('-o', '--output', required=True)
        ap.add_argument('--file', help='the name a player has the game under; its own name by default')
        ap.add_argument('--zxdb', help='its ZXDB entry'); ap.add_argument('--title'); ap.add_argument('--publisher', help='for the menu, such as "Ocean, 1986"')
        ap.add_argument('--patch-by'); ap.add_argument('--colours-by'); ap.add_argument('--credit', help="INF1's credit; a patch from NexClash keeps the default")
        ap.add_argument('--build', help="what INF1 calls the build; the .nex's own name by default")
        ap.add_argument('--rom', type=int, choices=(0, 1, 2), default=0, help='0 not stated; 1 runs on the Next\'s own ROM; 2 needs the Sinclair 48K ROM, carried in the alt ROM')
        ap.add_argument('--highest-bank', type=int, help='the highest 16K bank the build uses at run time, if above the highest it lists')
        ap.add_argument('--proof', action='append', default=[], metavar='KEY=VALUE', help='a PRF1 field; repeatable')
        ap.add_argument('--proof-file', help='PRF1 fields, as lines of KEY=VALUE')
        ap.add_argument('--colours', action='append', default=[], metavar='NAME=NEX', help='a colour set: the same build with it applied; repeatable')
        ap.add_argument('--language', action='append', default=[], metavar='NAME=NEX', help='a language set, the same way; repeatable')
        ap.add_argument('--game-language', metavar='CODE', help="the language the game itself is in, as an ISO 639 code such as en")
        ap.add_argument('--language-code', action='append', default=[], metavar='NAME=CODE', help="a language set's ISO 639 code; repeatable")
        ap.add_argument('--text-by', help='who translated the text; kept in INF1, not on the menu')
        a = ap.parse_args(argv[1:])
        refuse_same(a.output, a.nex, a.game)
        def named(items):
            out = {}
            for item in items:
                if '=' not in item: raise Wrong('%s is not NAME=NEX' % item)
                name, path = item.split('=', 1)
                refuse_same(a.output, path)
                out[name] = path
            return out
        lines = list(a.proof)
        if a.proof_file:
            with open(a.proof_file, encoding='ascii') as g: lines += [l.rstrip('\n') for l in g if l.strip() and not l.startswith('#')]
        proof = {}
        for line in lines:
            if '=' not in line: raise Wrong('%s is not KEY=VALUE' % line)
            k, v = line.split('=', 1)
            proof[k.strip()] = v.strip()
        target = dict(file=a.file or os.path.basename(a.game), title=a.title, zxdb_entry=a.zxdb)
        with open(a.nex, 'rb') as g: built = g.read()
        info = dict(publisher=a.publisher, patch_by=a.patch_by, colours_by=a.colours_by,
                    build=a.build or os.path.splitext(os.path.basename(a.nex))[0], nex_md5=hashlib.md5(built).hexdigest())
        if a.credit: info['credit'] = a.credit
        info.update(language_info(a.game_language, a.language_code, a.text_by, named(a.language)))
        f, _ = make(a.game, a.nex, target, info, rom=a.rom, proof=proof, colours=named(a.colours), languages=named(a.language), highest_bank=a.highest_bank)
        for key, value in (('publisher', a.publisher), ('patch_by', a.patch_by), ('colours_by', a.colours_by)):
            if value and inf1_value(f, key) is None: raise Wrong('the menu names must end within the first %d bytes of INF1' % TEXT_READ)
        with open(a.output, 'wb') as g: g.write(f)
        print('rebuilds it exactly, MD5', info['nex_md5']); print(memory_text(dict(blocks(f)[1])[b'OPT1'][2]))
        print('wrote', a.output, len(f), 'bytes')
        return
    if argv[:1] == ['add-dump']:
        ap = argparse.ArgumentParser(prog='nxc.py add-dump', description='Accept one more dump, if it rebuilds the same banks.')
        ap.add_argument('patch'); ap.add_argument('known'); ap.add_argument('new'); ap.add_argument('-o', '--output', required=True)
        ap.add_argument('--file', help='the name a player has it under; the new file\'s own name by default')
        ap.add_argument('--zxdb', help='its ZXDB entry'); ap.add_argument('--title')
        a = ap.parse_args(argv[1:])
        refuse_same(a.output, a.known, a.new)
        fields = dict(file=a.file or os.path.basename(a.new), zxdb_entry=a.zxdb, title=a.title)
        f = add_target(read_file(a.patch), read_file(a.known), read_file(a.new), kind_of_name(a.new), fields)
        with open(a.output, 'wb') as g: g.write(f)
        print('accepts', len(targets(f)), 'dumps; wrote', a.output, len(f), 'bytes')
        return
    ap = argparse.ArgumentParser(description='Apply or list a .nxc patch.')
    ap.add_argument('patch'); ap.add_argument('game', nargs='?'); ap.add_argument('-o', '--output')
    ap.add_argument('--colours', help='a colour set by name; omit for the default; has no effect with --original')
    ap.add_argument('--language', help='a language set by name; has no effect with --original')
    ap.add_argument('--trainer', action='append', help='a trainer by number from 1 or by name; repeatable')
    ap.add_argument('--original', action='store_true', help='no patch: write the game itself, or with trainers a snapshot of it with them in')
    a = ap.parse_args(argv); f = read_file(a.patch)
    print('colour sets:', ', '.join(['(default)'] + colour_sets(f)))
    if languages(f): print('languages:', ', '.join(['(default)'] + languages(f)))
    print('trainers:', ', '.join(t[1] for t in trainers(f)) or '(none)')
    print('needs', memory_text(dict(blocks(f)[1]).get(b'OPT1', bytes(3))[2:3][0] if len(dict(blocks(f)[1]).get(b'OPT1', b'')) == 3 else 0))
    for t in targets(f):
        print('accepts %s, %s, %d bytes' % (t['file'], KIND_NAMES.get(t['kind'], 'unknown kind'), t['length']))
    for t, d in blocks(f)[1]:
        if t in (b'INF1', b'PRF1'): print(d.decode(errors='replace'), end='')
    if a.game:
        output = a.output or 'out.nex'
        refuse_same(output, a.patch, a.game)
        if a.original: d = original_with_pokes(f, read_file(a.game), a.trainer)
        else: d = apply(f, a.game, colours=a.colours, chosen=a.trainer, language=a.language)
        with open(output, 'wb') as g: g.write(d)
        print('wrote', output, hashlib.md5(d).hexdigest())

if __name__ == '__main__':
    main(sys.argv[1:])

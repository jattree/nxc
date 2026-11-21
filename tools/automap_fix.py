#!/usr/bin/env python3
"""A published .nxc -> the same patch whose every .nex starts with DivMMC automap turned off.

NextZXOS and .nexload leave DivMMC automap on (NextReg $0A bit 4; they clear only $06 bit 4, its place up to core
3.01.05), so every IM 1 interrupt maps DivMMC over 0000-3FFF under the game. NexClash builds made before 2026-11-20
did not turn it off: Bubbler jumped to 0 seconds after its title on a Tang board, and played with automap off.

NexClash now ends every build with z80tonex.automap_off: 19 bytes at entry-bank offset 0x1E00 (DI, $0A bit 4 off,
JP the old start) with the header's start address on them. This tool does the same to a patch's builds without
rebuilding them: the header (NEX1) and the entry bank (BNK1) are written again under the patch's own key, and every
stored CRC (OUT1, each set's, a SET3's carrier and table) is worked out again from what the old patch rebuilds for
that choice, each checked against the old value first. Every other block is kept byte for byte.

    python tools/automap_fix.py PATCH GAME [--also TAPE ...] -o OUT
"""
import argparse
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nxc  # noqa: E402

AT = 0x1E00                 # entry-bank offset: 0xDE00, below a build's stack at 0xDFFE
HERE = 0xC000 + AT


def code(target):
    """DI, NextReg $0A AND $EF (read through ports 0x243B / 0x253B), JP target: as z80tonex.automap_off_code."""
    return bytes([0xF3, 0x01, 0x3B, 0x24, 0x3E, 0x0A, 0xED, 0x79, 0x04, 0xED, 0x78, 0xE6, 0xEF, 0xED, 0x92, 0x0A,
                  0xC3, target & 0xFF, target >> 8])


def offsets(nex):
    """{bank: file offset} of a .nex, in .nex order after its header and screen."""
    at, out = 512 + nxc.screen_size(nex[10]), {}
    for b in nxc.ORDER:
        if nex[18 + b]:
            out[b] = at
            at += nxc.BANK
    return out


def automap_off(nex):
    """A .nex -> the same .nex starting with DivMMC automap off; already so: unchanged. Refuses a window that is not zero."""
    d = bytearray(nex)
    if len(d) < 512 or d[:4] != b'Next':
        raise nxc.Wrong('not a .nex')
    entry, pc = d[139], d[14] | d[15] << 8
    offs = offsets(d)
    if entry not in offs or len(d) < offs[entry] + nxc.BANK:
        raise nxc.Wrong('the entry bank is not in the .nex')
    at = offs[entry] + AT
    if pc == HERE:
        if d[at:at + 17] != code(0)[:17]:
            raise nxc.Wrong('the start is 0x%04X but the automap code is not there' % HERE)
        return bytes(d)
    c = code(pc)
    if any(d[at:at + len(c)]):
        raise nxc.Wrong('the entry bank is not zero at 0x%04X: no room for the automap code' % AT)
    d[at:at + len(c)] = c
    d[14:16] = struct.pack('<H', HERE)
    return bytes(d)


def with_chunks(nex, chunks, header=None):
    """nex with set chunks [(bank, chunk)] written over it (a header with more banks: those banks zero first)."""
    out = bytearray(nex)
    if header is not None:
        base = offsets(nex)
        out = bytearray(header) + nex[512:512 + nxc.screen_size(nex[10])]
        for b in nxc.ORDER:
            if header[18 + b]:
                out += nex[base[b]:base[b] + nxc.BANK] if b in base else bytes(nxc.BANK)
    offs = offsets(out)
    for b, chunk in chunks:
        for place, o in enumerate(nxc.chunk_offsets(chunk), nxc.BITMAP):
            out[offs[b] + o] = chunk[place]
    return bytes(out)


def rewrite(f, game, transform, place, done, what):
    """The patch f for game with every .nex it builds passed through transform(nex) -> nex, which may change the header
    and one BNK1 bank. place(old) -> (that bank, the offsets in it the change writes); done(old) -> True when old is
    already transform's (it must then be transform(old) itself). The header and that bank are written again under the
    patch's own key and every stored CRC worked out again from transform of what the old patch builds for that choice,
    each old CRC checked first; all other blocks are kept byte for byte. A set chunk or a trainer POKE over the
    changed offsets is refused: it would undo the change after the checksum. Each set alone, each two sets that can
    go together, a big option with each set of its table and its carrier must have the change in the same place
    (and be done when the base is); three or more sets together are not built: prove those choices by applying the
    old and new patches (as the release check does). -> (new patch, report)."""
    opened = nxc.check_key(f, game)
    st, bl, crc, size = opened[:4]
    old = nxc.apply(f, game=game)
    if zlib.crc32(old) != crc or len(old) != size:
        raise nxc.Wrong('the patch does not rebuild its own OUT1')
    bank, window = place(old)
    sets_old = {}
    for t, d in bl:
        if t in (nxc.SET_TAG, nxc.BIG_TAG):
            e = nxc.parse_set(d, big=(t == nxc.BIG_TAG))
            sets_old[e['stream']] = (e, nxc.read_set(st, e))
    for e, (_, chunks) in sets_old.values():
        for b, chunk in chunks:
            if b == bank and any(o in window for o in nxc.chunk_offsets(chunk)):
                raise nxc.Wrong('set %s writes into the %s\'s bytes' % (e['name'].decode('ascii', 'replace'), what))
    for b, o, _ in nxc.chosen_pokes(f, list(range(1, len(nxc.trainers(f)) + 1))):
        if b == bank and o in window:
            raise nxc.Wrong('a trainer POKEs into the %s\'s bytes' % what)
    variants = []                                      # each set alone, and each two sets that can go together
    small = [(e, ch) for e, (_, ch) in sets_old.values() if not e.get('big')]
    for e, (_, chunks) in sets_old.values():
        variants.append((e['name'], with_chunks(old, chunks) if not e.get('big') else
                         with_chunks(old, chunks, nxc.extended_header(old[:512], e))))
    for i, (e1, c1) in enumerate(small):
        for e2, c2 in small[i + 1:]:
            other = dict(c2)                           # disjoint, as apply() requires of two sets chosen together
            if not any(b in other and any(x & y for x, y in zip(ch[:nxc.BITMAP], other[b][:nxc.BITMAP])) for b, ch in c1):
                variants.append((e1['name'] + b' + ' + e2['name'], with_chunks(with_chunks(old, c1), c2)))
    for e, (_, chunks) in sets_old.values():           # a big option with each set its table names
        if e.get('big'):
            painted = with_chunks(old, chunks, nxc.extended_header(old[:512], e))
            variants.append((e['name'] + b' carrier', with_chunks(old, [(b, c) for b, c in chunks if b in e['added']],
                                                                  nxc.extended_header(old[:512], e))))
            for other in e['table']:
                o, (_, oc) = sets_old[other]
                variants.append((e['name'] + b' + ' + o['name'], with_chunks(painted, [(b, c) for b, c in oc if old[18 + b]])))
    for name, v in variants:                           # the change in the same place in each, and a valid one
        if place(v) != (bank, window):
            raise nxc.Wrong('set %s moves the %s' % (name.decode('ascii', 'replace'), what))
        if transform(v) != v and done(old):
            raise nxc.Wrong('set %s is not done like the base' % name.decode('ascii', 'replace'))
    if done(old):
        if transform(old) != old:
            raise nxc.Wrong('the build looks done but is not the %s\'s' % what)
        return f, 'already done'
    new = transform(old)
    if not any(t == b'BNK1' and d[0] == bank for t, d in bl):
        raise nxc.Wrong('bank %d comes from the game, not a BNK1: not handled' % bank)
    e_off = offsets(new)[bank]
    data = new[e_off:e_off + nxc.BANK].rstrip(b'\0')
    report = []
    out = []
    for t, d in bl:
        if t == b'NEX1':
            d = st.block(b'NEX1')(nxc.zx0(new[:512]))
        elif t == b'OUT1':
            d = st.block(b'OUT1')(struct.pack('<II', zlib.crc32(new), len(new)))
        elif t == b'BNK1' and d[0] == bank:
            d = struct.pack('<BH', bank, len(data)) + st.block(b'BNK1', bank)(nxc.zx0(data))
        elif t == nxc.SET_TAG:
            e = nxc.parse_set(d)
            set_crc, chunks = sets_old[e['stream']][1]
            painted = with_chunks(old, chunks)
            if zlib.crc32(painted) != set_crc:
                raise nxc.Wrong('set %s does not rebuild its own CRC' % e['name'].decode('ascii', 'replace'))
            head = len(d) - len(e['data'])
            d = d[:head] + nxc.set_use(st, e['stream'], nxc.SET_CRC_INDEX)(struct.pack('<I', zlib.crc32(transform(painted)))) \
                + d[head + nxc.SET_CRC:]
            report.append('set %s' % e['name'].decode('ascii', 'replace'))
        elif t == nxc.BIG_TAG:
            e = sets_old[nxc.parse_set(d, big=True)['stream']][0]        # read_set filled in its carrier and table
            set_crc, chunks = sets_old[e['stream']][1]
            header = nxc.extended_header(old[:512], e)
            painted = with_chunks(old, chunks, header)
            carrier = with_chunks(old, [(b, c) for b, c in chunks if b in e['added']], header)
            table = []
            for other in e['table']:
                both = with_chunks(painted, [(b, c) for b, c in sets_old[other][1][1] if old[18 + b]])
                if zlib.crc32(both) != e['crcs'][other]:
                    raise nxc.Wrong('option %s with set %d does not rebuild its CRC' % (e['name'].decode('ascii', 'replace'), other))
                table.append(zlib.crc32(transform(both)))
            if zlib.crc32(painted) != set_crc or zlib.crc32(carrier) != e['carrier']:
                raise nxc.Wrong('option %s does not rebuild its own CRCs' % e['name'].decode('ascii', 'replace'))
            m = len(e['table'])
            head = len(d) - len(e['data'])
            use = lambda i: nxc.set_use(st, e['stream'], i)
            d = (d[:head] + use(nxc.SET_CRC_INDEX)(struct.pack('<I', zlib.crc32(transform(painted))))
                 + use(nxc.BIG_CARRIER_INDEX)(struct.pack('<I', zlib.crc32(transform(carrier))))
                 + use(nxc.BIG_TABLE_INDEX)(struct.pack('<%dI' % m, *table)) + d[head + nxc.SET_CRC * (2 + m):])
            report.append('option %s' % e['name'].decode('ascii', 'replace'))
        out.append([t, d])
    return nxc.seal(f[:nxc.CHECK_AT], out, st), 'bank %d; CRCs: base%s' % (bank, ''.join(', ' + r for r in report))


def fix(f, game):
    """The patch f (bytes) for game (bytes, or an nxc.FileSet) with automap off at every start. -> (new patch, report)."""
    g, report = rewrite(f, game, automap_off, lambda old: (old[139], range(AT, AT + len(code(0)))),
                        lambda old: (old[14] | old[15] << 8) == HERE, 'automap code')
    return g, report if report == 'already done' else 'start -> 0x%04X, %s' % (HERE, report)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('patch')
    ap.add_argument('game')
    ap.add_argument('--also', action='append', default=[], metavar='TAPE')
    ap.add_argument('-o', '--output', required=True)
    a = ap.parse_args(argv)
    f = open(a.patch, 'rb').read()
    try:
        g, report = fix(f, nxc.game_arg(a.game, a.also))
    except nxc.Wrong as e:
        sys.exit('Refused: %s' % e)
    open(a.output, 'wb').write(g)
    print(report)
    return 0


if __name__ == '__main__':
    sys.exit(main())

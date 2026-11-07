#!/usr/bin/env python3
"""Write a patch's .nfo, the text file a player reads beside it, from the patch alone: the game file it needs, what it
does, its menu, credits and how it was tested. Everything comes from the patch's own clear fields (INF1, PRF1, TGT1,
TRN1, SET2, SET3), so the two cannot disagree, and the game is not needed. See spec/NXC-FORMAT.md, "INF1's notes" and "PRF1".

    make_nfo.py PATCH.nxc [PATCH.nxc ...]        writes NAME.nfo beside each
    make_nfo.py PATCH.nxc -o OUT.nfo             one, to OUT ('-' for standard output)

Lines are at most 78 characters, with CRLF endings, in plain ASCII.
"""
import os, sys, textwrap, unicodedata
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nxc

W = 78

HEAD = r"""
     _   _ __  __  ____
    | \ | |\ \/ / / ___|   .nxc patch for the ZX Spectrum Next
    |  \| | \  / | |       colour clash removed with hardware sprites
    | |\  | /  \ | |___    (built with NexClash)
    |_| \_|/_/\_\ \____|
"""

def asc(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    return s.replace('\t', ' ')

def fields(b):
    """A text block's lines as a reader takes them: the first of a key wins."""
    out = {}
    for line in b.decode('latin-1').splitlines():
        k, eq, v = line.partition('=')
        if eq: out.setdefault(k, v)
    return out

def para(label, text, out):
    text = asc(text).strip()
    if not text:
        return
    lines = textwrap.wrap(text, W - 14) or ['']
    out.append('  %-11s %s' % (label, lines[0]))
    out.extend('  %-11s %s' % ('', l) for l in lines[1:])

def rule(out, title=''):
    out.append('')
    out.append(('-- %s ' % title if title else '').ljust(W, '-'))

def pace_line(prf):
    """The .nfo's one line for PRF1's pace, or '' without it: the target, then the first measured figure and where."""
    target = nxc.PACE_TARGETS.get(prf.get('pace', ''))
    if not target: return ''
    measured = nxc.pace_entries(prf.get('pace_measured', ''))
    if not measured: return target
    where = prf.get('pace_where', '')
    return '%s (%s measured%s)' % (target, measured[0][1], ' in ' + where if where else '')

def nfo(d, base):
    """The .nfo text of patch d, whose file is base.nxc."""
    _, bl = nxc.blocks(d)
    inf, prf = {}, {}
    for t, b in bl:
        if t == b'INF1' and not inf: inf = fields(b)
        if t == b'PRF1' and not prf: prf = fields(b)
    tg = nxc.targets(d)
    tt = fields(tg[0]['text'])
    trainers = [x[1] for x in nxc.trainers(d)]
    colours = nxc.offered(d, nxc.KIND_COLOURS, big=True)
    big = nxc.big_offered(d)
    o = [l.rstrip() for l in HEAD.strip('\n').splitlines()]
    rule(o, 'GAME')
    para('Title', tt.get('title', base), o)
    para('Publisher', inf.get('publisher', ''), o)
    if inf.get('zxdb_entry'): para('ZXDB', inf['zxdb_entry'], o)
    if inf.get('version'): para('Version', inf['version'], o)
    rule(o, 'YOU NEED')
    multi = any('file_2' in fields(t['text']) for t in tg)
    o.append('  Your own copy of the original game, saved beside this patch' + (':' if not multi and len(tg) == 1 else ''))
    if multi and len(tg) > 1: o.append('  (one of these sets, every file of the set together):')
    elif multi: o.append('  (all of these files together):')
    elif len(tg) > 1: o.append('  (one of these files):')
    for n, t in enumerate(tg):
        f = fields(t['text'])
        o.append('')
        if multi and len(tg) > 1:
            o.append('  Set %d' % (n + 1))
        k = 1
        while True:
            sfx = '' if k == 1 else '_%d' % k
            if 'file' + sfx not in f:
                break
            para('File', f['file' + sfx], o)
            para('MD5', f.get('md5' + sfx, ''), o)
            k += 1
    o.append('')
    o.append('  The patch carries none of the game\'s code. It only works with that exact')
    o.append('  dump, under that name or any other: anything else is refused, with a')
    o.append('  message naming the file it wants.')
    if big:                                         # only a patch with a SET3 says more about memory than before
        o.append('')
        base_top = dict(bl)[b'OPT1'][2]
        para('Memory', '%s. %s.' % ('Any Next: a 1MB Next has the memory for the game' if base_top <= nxc.NEXT_1MB else 'A 2MB Next',
                                    '; '.join('%s needs a %s Next, and is not offered on a smaller one' % (e['name'].decode('ascii', 'replace'), '2MB' if e['top'] > nxc.NEXT_1MB else '1MB')
                                              for e in big)), o)
    rule(o, 'WHAT IT DOES')
    o.append('  Moving figures become Next hardware sprites, so they keep their own colours')
    o.append('  and no longer take on the scenery\'s (colour clash). Game logic is unchanged.')
    if colours:
        names = [e['name'].decode('ascii', 'replace') for e in colours]
        o.append('')
        need = ['%s (needs a 2MB Next)' % n if e.get('big') and e['top'] > nxc.NEXT_1MB else n for e, n in zip(colours, names)]
        para('Colours', 'Default (the game\'s own) plus: ' + ', '.join(need) + ', chosen on the menu, off by default.', o)
        src = (inf.get('credit', '').split('; ', 1) + [''])[1]
        for e, name in zip(colours, names):
            look = inf.get('enhanced_%d' % e['choice'], '')
            if look:
                para('Enhanced' if len(colours) == 1 else name[:11], look + (' Source: ' + src + '.' if src else ' A painted set, colourist not named.'), o)
    pace = pace_line(prf)
    if pace:
        o.append('')
        para('Pace', pace, o)
    changes = nxc.change_entries(inf.get('changes', ''))
    if changes:
        o.append('')
        for k, (version, text) in enumerate(changes):
            para('Changes' if k == 0 else '', '%s: %s' % (version, text), o)
    if inf.get('notes'):
        o.append('')
        para('Note', inf['notes'], o)
    rule(o, 'MENU')
    if trainers:
        for i, t in enumerate(trainers, 1):
            o.append('  %2d  %s' % (i, asc(t)))
        o.append('')
        if inf.get('cheats_source'):
            o.extend('  ' + l for l in textwrap.wrap(asc(inf['cheats_source']).strip(), W - 2))
        else:
            o.append('  Cheats come from the archive\'s POKEs for this release.')
    else:
        o.append('  No cheats.')
    rule(o, 'CREDITS')
    para('Patch by', inf.get('patch_by', ''), o)
    para('Credit', inf.get('credit', '') or inf.get('nexclash', ''), o)
    para('Original', '%s, by its original authors. All rights to the game remain theirs.' % inf.get('publisher', 'the publisher'), o)
    rule(o, 'TESTING')
    para('Tested', inf.get('tested', ''), o)
    for k in ('replay', 'emulator', 'coverage', 'hardware'):
        if prf.get(k):
            o.append('')
            para(k.capitalize(), prf[k], o)
    o.append('')
    o.append('  Nothing here claims a result on real hardware unless the line above says so.')
    rule(o, 'HOW TO USE')
    o.append('  Put this .nxc and the game file in the same folder on the Next\'s card and')
    o.append('  choose the .nxc in the Browser. See README.txt.')
    o.append('-' * W)
    return '\r\n'.join(l.rstrip() for l in o) + '\r\n'

def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Write a patch's .nfo from the patch alone.")
    ap.add_argument('patch', nargs='+'); ap.add_argument('-o', '--output', help="with one patch: where to write it; '-' for standard output")
    a = ap.parse_args(argv)
    if a.output and len(a.patch) != 1: ap.error('-o takes one patch')
    for path in a.patch:
        with open(path, 'rb') as g: d = g.read()
        text = nfo(d, os.path.splitext(os.path.basename(path))[0])
        out = a.output or os.path.splitext(path)[0] + '.nfo'
        if out == '-':
            sys.stdout.write(text.replace('\r\n', '\n'))
            continue
        with open(out, 'w', newline='') as g: g.write(text)
        print('wrote', out)

if __name__ == '__main__':
    main(sys.argv[1:])

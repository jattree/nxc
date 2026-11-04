#!/usr/bin/env python3
"""Sets up a NextZXOS SD card for .nxc patches, once. Python 3 and its standard library only; Windows, macOS or Linux.

    python3 tools/setup_card.py SDCARD_ROOT [--dry-run]

SDCARD_ROOT is the card's top folder, as your computer mounts it: E:\\ on Windows, /Volumes/NEXT on a Mac,
/media/you/NEXT on Linux. The script:

1. checks it is a NextZXOS card: NEXTZXOS/BROWSER.CFG and MACHINES/NEXT/ENNEXTZX.ROM are there;
2. copies the loader, DOT/NEXCLASH, and its hand-off, NEXTZXOS/NXCHAND.BAS, from this repository's sdcard/ folder,
   overwriting those two files and nothing else;
3. keeps a copy of BROWSER.CFG as BROWSER.CFG.bak-pre-nxc, the first time only;
4. adds the NXC line to BROWSER.CFG just before the first Z80,SNA line, or replaces the NXC line already there;
5. makes the NXC/ folder, for one folder per game, and TMP/ if the card lacks it.

--dry-run says what it would do and changes nothing. Names on the card are matched without regard to case, as FAT does.
The same steps by hand are in README.md, "One-time card setup".
"""
import argparse, os, shutil, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SDCARD = os.path.join(os.path.dirname(HERE), 'sdcard')

# The browser.cfg line, as firmware/README.md's "Card setup" gives it: each 0x7F byte is replaced by the Browser
# with c:/nextzxos/. CRLF ends it, as it ends every line of the card's own file.
NXC_LINE = (b'NXC:clear 65367:load "\x7fsnapload.bas":f$="c:/tmp/nexclash.z80":adj=0:merge "\x7fnxchand.bas":'
            b'.nexclash "|":cd "c:/tmp":goto 0')
BACKUP_SUFFIX = '.bak-pre-nxc'
COPIED = (('dot', 'NEXCLASH'), ('nextzxos', 'NXCHAND.BAS'))


class Refused(Exception):
    pass


def find(root, *parts):
    """The path of root/parts on the card, matching each name without regard to case, or None if it is not there."""
    path = root
    for part in parts:
        if not os.path.isdir(path): return None
        hit = os.path.join(path, part)
        if not os.path.exists(hit):
            hit = next((os.path.join(path, n) for n in sorted(os.listdir(path)) if n.lower() == part.lower()), None)
            if hit is None: return None
        path = hit
    return path


def place(root, *parts):
    """Where root/parts is or would go: the card's own spelling of each name that exists, ours for the rest."""
    path = root
    for part in parts:
        path = find(path, part) or os.path.join(path, part)
    return path


def extensions(line):
    """The upper-cased extensions a browser.cfg line is for: those before its first ':'."""
    head = line.split(b':', 1)[0] if b':' in line else b''
    return [e.strip().upper() for e in head.split(b',')]


def with_nxc_line(cfg):
    """browser.cfg's bytes with the NXC line in: in place of the NXC line already there (any others dropped), or else
    just before the first Z80,SNA line. Every other line, and its ending, is kept as it was."""
    lines = cfg.splitlines(keepends=True)
    new = NXC_LINE + b'\r\n'
    nxc = [i for i, line in enumerate(lines) if b'NXC' in extensions(line)]
    if nxc:
        out = [line for i, line in enumerate(lines) if i not in nxc[1:]]
        out[nxc[0]] = new
        return b''.join(out)
    for i, line in enumerate(lines):
        if b'Z80' in extensions(line) and b'SNA' in extensions(line):
            return b''.join(lines[:i] + [new] + lines[i:])
    raise Refused('browser.cfg has no Z80,SNA line to put the NXC line before: add it by hand (README.md, '
                  '"One-time card setup")')


def write_atomic(path, data):
    folder = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix='.nxc-')
    try:
        with os.fdopen(fd, 'wb') as g: g.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp): os.remove(tmp)
        raise


def setup(root, dry_run=False, source=SDCARD, say=print):
    """Sets up the card at root. Returns the list of what was done (or, dry, what would be)."""
    done = []
    def do(what, act):
        done.append(what); say(('would ' if dry_run else '') + what)
        if not dry_run: act()
    if not os.path.isdir(root): raise Refused('%s is not a folder' % root)
    cfg_path = find(root, 'nextzxos', 'browser.cfg'); rom = find(root, 'machines', 'next', 'enNextZX.rom')
    if cfg_path is None or rom is None:
        raise Refused('%s does not look like a NextZXOS card: it needs NEXTZXOS/BROWSER.CFG and '
                      'MACHINES/NEXT/ENNEXTZX.ROM. Give the card\'s top folder.' % root)
    for folder, name in COPIED:
        src = os.path.join(source, folder, name)
        if not os.path.isfile(src): raise Refused('%s is missing from this repository' % src)
    with open(cfg_path, 'rb') as g: cfg = g.read()
    new = with_nxc_line(cfg)                    # refuses before anything is changed
    for folder in ('dot', 'nxc', 'tmp'):
        if find(root, folder) is None:
            do('make %s' % os.path.join(root, folder), lambda f=folder: os.makedirs(os.path.join(root, f)))
    for folder, name in COPIED:
        src = os.path.join(source, folder, name); dst = place(root, folder, name)
        with open(src, 'rb') as g: want = g.read()
        if os.path.isfile(dst):
            with open(dst, 'rb') as g:
                if g.read() == want: say('%s is up to date' % dst); continue
        do('copy %s to %s' % (src, dst), lambda s=src, d=dst: shutil.copyfile(s, d))
    readme = place(root, 'nxc', 'README.txt')
    if not os.path.exists(readme):
        do('copy the nxc folder\'s README.txt to %s' % readme,
           lambda: shutil.copyfile(os.path.join(source, 'nxc', 'README.txt'), readme))
    backup = cfg_path + BACKUP_SUFFIX
    if not os.path.exists(backup):
        do('keep a copy of %s as %s' % (cfg_path, backup), lambda: shutil.copyfile(cfg_path, backup))
    if new == cfg: say('%s already has the NXC line' % cfg_path)
    else:
        had = any(b'NXC' in extensions(line) for line in cfg.splitlines())
        do('%s the NXC line in %s' % ('replace' if had else 'add', cfg_path), lambda: write_atomic(cfg_path, new))
    return done


def main(argv=None):
    ap = argparse.ArgumentParser(prog='setup_card.py', description='Set up a NextZXOS SD card for .nxc patches.')
    ap.add_argument('root', metavar='SDCARD_ROOT', help="the card's top folder, such as E:\\ or /Volumes/NEXT")
    ap.add_argument('--dry-run', action='store_true', help='say what would be done, and change nothing')
    a = ap.parse_args(argv)
    try:
        setup(a.root, a.dry_run)
    except (Refused, OSError) as e:
        print('Refused: %s' % e, file=sys.stderr); return 1
    print('Nothing was changed (dry run).' if a.dry_run else
          'Done. Put each game\'s folder in NXC/ on the card, with your own game file beside its .nxc.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

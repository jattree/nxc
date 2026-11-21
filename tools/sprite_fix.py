#!/usr/bin/env python3
"""A published .nxc whose set-up hides only 4 sprites -> the same patch with all 128 hidden.

NexClash's generic TID / Dizzy set-up hid sprites 0 to 3 (Dizzy's four) and left the other 124 as the previous
program had them, so after another game that used sprites their leftovers showed over the room (Fantasy World Dizzy
on a Tang board, 2026-11-21). NexClash now loops over all 128 (LD B,128 for LD B,4, one byte). This tool makes the
same one-byte change in a published patch's builds, through automap_fix.rewrite: the bank is written again under
the patch's own key and every stored CRC worked out again; all other blocks are kept byte for byte.

    python tools/sprite_fix.py PATCH GAME [--also TAPE ...] -o OUT
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nxc            # noqa: E402
import automap_fix    # noqa: E402

# the set-up's sprite loop, as NexClash's build.py / dizzy_patch.py hold it: NEXTREG $4B,0; LD B,n; XOR A; NEXTREG $34,A; ...
OLD = bytes.fromhex('ed914b000604afed9234ed913800ed9139003c10f2')
NEW = bytes.fromhex('ed914b000680afed9234ed913800ed9139003c10f2')
AT = 5                # the count's offset in those bytes


def hide_all(nex):
    """A .nex -> the same .nex whose set-up hides all 128 sprites; already so: unchanged."""
    n_old, n_new = nex.count(OLD), nex.count(NEW)
    if n_old == 0 and n_new == 1:
        return bytes(nex)
    if n_old != 1 or n_new:
        raise nxc.Wrong('the 4-sprite set-up is not there exactly once (%d old, %d new)' % (n_old, n_new))
    return nex.replace(OLD, NEW)


def place(nex):
    """(bank, offsets) of the count byte in a .nex holding the set-up, either way."""
    at = nex.find(OLD) if OLD in nex else nex.find(NEW)
    if at < 0:
        raise nxc.Wrong('no TID / Dizzy set-up in this build')
    for b, off in automap_fix.offsets(nex).items():
        if off <= at + AT < off + nxc.BANK:
            return b, range(at + AT - off, at + AT - off + 1)
    raise nxc.Wrong('the set-up is not inside a bank')


def fix(f, game):
    """The patch f for game with its set-up hiding all 128 sprites. -> (new patch, report)."""
    g, report = automap_fix.rewrite(f, game, hide_all, place, lambda old: NEW in old and OLD not in old, 'sprite count')
    return g, report if report == 'already done' else 'sprites 4 -> 128, %s' % report


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

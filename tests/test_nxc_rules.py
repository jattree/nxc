"""OPR1, which options go together, through tools/nxc.py on the made-up tape game: a patch without it is unchanged and its
menu still holds two at once; with it, any options the rules allow are on together; excludes, needs and implies, in apply,
in the menu's own steps (menu_settle) and in the description; the writer's checks, among them the flag that keeps a
reader without OPR1 from a combination it could not refuse; and the damage a reader refuses. Needs the zx0 compressor
(NXC_ZX0_DIR)."""
from __future__ import annotations

import unittest

import test_nexclash_dot as T
import test_nxc_tape as TT
import test_nxc_toggle as TG

nxc = T.nxc
SMOOTH = [(0x2100, 0x11), (0x2101, 0x22)]
CENTRED = [(0x2110, 0x44)]
KEYS = [(0x2120, 0x55)]
WIDE = [(0x2100, 0x66), (0x2130, 0x77)]       # overlaps SMOOTH
PAINT = [(0x2050, 0x5A)]
LIVES = [(2, 0x2010, 0xAB)]


def build(toggles, colours=None, rules=None, trainers=(("Lives", LIVES),)):
    patch, nex, tap = TG.build(toggles, colours=colours, trainers=list(trainers),
                               proof={"toggle_%d" % (n + 1): "checked" for n in range(4)}, rules=rules)
    return patch, nex, tap


def opt1(f):
    return dict(nxc.blocks(f)[1])[b"OPT1"]


@TT.needs
class Rules(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.toggles = {"Smooth scrolling": (SMOOTH, False), "Centred view": (CENTRED, True), "Cursor keys": (KEYS, True)}
        cls.plain, cls.nex, cls.tap = build(cls.toggles, colours={"Colour": PAINT})
        cls.free = nxc.set_rules(cls.plain, cls.tap, [])
        cls.linked = nxc.set_rules(cls.plain, cls.tap, [(nxc.RULE_NEEDS | nxc.RULE_MENU_ONLY, "Centred view", "Smooth scrolling")])

    def want(self, *changes):
        return TG.variant(self.nex, [c for ch in changes for c in ch])

    def test_without_the_block_nothing_changes(self):
        self.assertIsNone(nxc.rules_of(self.plain))
        self.assertEqual(nxc.set_rules(self.plain, self.tap, None), self.plain)
        desc = nxc.menu_description(self.plain)[0]
        self.assertEqual(desc[:2], bytes((nxc.DESC_FIXED, nxc.MENU_HOLD)))
        with self.assertRaises(nxc.Wrong):
            nxc.menu_presets(self.plain, colours="Colour", toggles=["Smooth scrolling", "Cursor keys"])
        self.assertIn(nxc.stub_binary()[:-nxc.STUB_PARAMS], nxc.apply_menu(self.plain, self.tap))
        self.assertNotIn(nxc.stub_binary(rules=True)[:-nxc.STUB_PARAMS], nxc.apply_menu(self.plain, self.tap))

    def test_no_rules_lifts_the_limit(self):
        self.assertEqual(nxc.rules_of(self.free), [])
        self.assertEqual(opt1(self.free)[1] & nxc.OPT_RULES, 0)
        on = dict(colours="Colour", toggles=["Smooth scrolling", "Centred view", "Cursor keys"])
        self.assertEqual(nxc.apply(self.free, game=self.tap, **on), self.want(PAINT, SMOOTH, CENTRED, KEYS))
        menu = nxc.apply_menu(self.free, self.tap, **on)
        self.assertIn(nxc.stub_binary(rules=True)[:-nxc.STUB_PARAMS], menu)
        desc = nxc.menu_description(self.free)[0]
        self.assertEqual(desc[0] & nxc.DESC_RULES, nxc.DESC_RULES)
        self.assertEqual(desc[1], nxc.NO_CAP)
        self.assertEqual(desc[-1:], b"\0")                      # no rules after the lines' offsets
        self.assertEqual(len(set_rules_report(self.free)["allowed"]), 16)

    def test_implies(self):
        rules = nxc.rules_of(self.linked)
        self.assertEqual(nxc.rule_text(self.linked, rules[0]), "Centred view implies Smooth scrolling")
        self.assertEqual(opt1(self.linked)[1] & nxc.OPT_RULES, 0)      # Centred view alone still plays: no flag
        self.assertEqual(nxc.apply(self.linked, game=self.tap, toggles=["Centred view"]), self.want(CENTRED))
        with self.assertRaises(nxc.Wrong):                               # but the menu never starts like that
            nxc.menu_presets(self.linked, toggles=["Centred view"])
        lines = nxc.line_rules(self.linked, rules)
        states = [0] * len(nxc.menu_lines(self.linked))
        counts = {i: 1 for i, l in enumerate(nxc.menu_lines(self.linked)) if l[0] == 3}
        centred = [i for i, l in enumerate(nxc.menu_lines(self.linked)) if l[1] == "Centred view"][0]
        smooth = [i for i, l in enumerate(nxc.menu_lines(self.linked)) if l[1] == "Smooth scrolling"][0]
        self.assertEqual(nxc.menu_key(states, centred, counts, lines), [(smooth, True)])
        self.assertEqual((states[centred], states[smooth]), (1, 1))
        self.assertEqual(nxc.menu_key(states, smooth, counts, lines), [(centred, False)])
        self.assertEqual((states[centred], states[smooth]), (0, 0))
        desc = nxc.menu_description(self.linked)[0]
        self.assertEqual(desc[-6:], bytes((1, nxc.RULE_NEEDS, centred, 1, smooth, 1)))

    def test_needs_sets_the_flag_for_older_readers(self):
        f = nxc.set_rules(self.plain, self.tap, [(nxc.RULE_NEEDS, "Centred view", "Smooth scrolling")])
        self.assertEqual(opt1(f)[1] & nxc.OPT_RULES, nxc.OPT_RULES)
        with self.assertRaises(nxc.Wrong):
            nxc.apply(f, game=self.tap, toggles=["Centred view"])
        self.assertEqual(nxc.apply(f, game=self.tap, toggles=["Centred view", "Smooth scrolling"]), self.want(SMOOTH, CENTRED))
        old_flags = nxc.LOADER_FLAGS
        try:                                                              # a reader before OPR1 refuses it
            nxc.LOADER_FLAGS = nxc.OPT_TAPE | nxc.OPT_TAPE_SET
            with self.assertRaises(nxc.Wrong) as e:
                nxc.apply(f, game=self.tap)
            self.assertIn("newer loader", str(e.exception))
            self.assertEqual(nxc.apply(self.linked, game=self.tap, toggles=["Centred view"]), self.want(CENTRED))
        finally:
            nxc.LOADER_FLAGS = old_flags

    def test_excludes_lets_two_options_change_the_same_bytes(self):
        toggles = dict(self.toggles, Wide=(WIDE, False))
        with self.assertRaises(ValueError):
            build(toggles)
        f, nex, tap = build(toggles, rules=[(nxc.RULE_EXCLUDES, "Wide", "Smooth scrolling")])
        self.assertEqual(opt1(f)[1] & nxc.OPT_RULES, 0)      # a reader without OPR1 refuses the pair: they overlap
        self.assertEqual(nxc.apply(f, game=tap, toggles=["Wide", "Centred view", "Cursor keys"]),
                         TG.variant(nex, WIDE + CENTRED + KEYS))
        with self.assertRaises(nxc.Wrong):
            nxc.apply(f, game=tap, toggles=["Wide", "Smooth scrolling"])
        lines = nxc.menu_lines(f)
        at = {l[1]: i for i, l in enumerate(lines)}
        states = [0] * len(lines); counts = {i: 1 for i, l in enumerate(lines) if l[0] == 3}
        lr = nxc.line_rules(f, nxc.rules_of(f))
        nxc.menu_key(states, at["Smooth scrolling"], counts, lr)
        self.assertEqual(nxc.menu_key(states, at["Wide"], counts, lr), [(at["Smooth scrolling"], False)])
        self.assertEqual(nxc.menu_key(states, at["Smooth scrolling"], counts, lr), [(at["Wide"], False)])

    def test_excludes_of_options_apart_sets_the_flag(self):
        f = nxc.set_rules(self.plain, self.tap, [(nxc.RULE_EXCLUDES, "Colour", "Cursor keys")])
        self.assertEqual(opt1(f)[1] & nxc.OPT_RULES, nxc.OPT_RULES)

    def test_a_cascade(self):
        """Keying A, which needs B, which excludes C that was on: B on, C off, both said."""
        f = nxc.set_rules(self.plain, self.tap, [(nxc.RULE_NEEDS, "Centred view", "Smooth scrolling"),
                                                 (nxc.RULE_EXCLUDES, "Smooth scrolling", "Cursor keys")])
        lines = nxc.menu_lines(f); at = {l[1]: i for i, l in enumerate(lines)}
        states = [0] * len(lines); counts = {i: 1 for i, l in enumerate(lines) if l[0] == 3}
        lr = nxc.line_rules(f, nxc.rules_of(f))
        nxc.menu_key(states, at["Cursor keys"], counts, lr)
        also = nxc.menu_key(states, at["Centred view"], counts, lr)
        self.assertEqual(also, [(at["Smooth scrolling"], True), (at["Cursor keys"], False)])
        self.assertEqual([states[at[n]] for n in ("Smooth scrolling", "Centred view", "Cursor keys")], [1, 1, 0])

    def test_the_writer_refuses(self):
        for rules, why in (([(nxc.RULE_EXCLUDES, "Centred view", "Smooth scrolling"), (nxc.RULE_NEEDS, "Centred view", "Smooth scrolling")], "cannot be kept"),
                           ([(nxc.RULE_NEEDS, "Centred view", "Centred view")], "twice"),
                           ([(nxc.RULE_NEEDS, "Nothing", "Centred view")], "no option"),
                           ([(3, "Cursor keys", "Centred view")], "excludes, needs"),
                           ([(nxc.RULE_NEEDS, "Cursor keys", "Centred view")] * 2, "twice")):
            with self.subTest(why):
                with self.assertRaises(nxc.Wrong) as e:
                    nxc.set_rules(self.plain, self.tap, rules)
                self.assertIn(why, str(e.exception))

    def test_a_reader_refuses_damage(self):
        st = nxc.check_key(self.free, self.tap)[0]
        def reseal(edit):
            nonce, bl = nxc.blocks(self.free)
            return nxc.seal(self.free[:nxc.CHECK_AT], edit([[t, d] for t, d in bl]), st)
        def rules_body(body):
            return lambda bl: [[t, body if t == nxc.RULES_TAG else d] for t, d in bl]
        cs = {(e["kind"], e["choice"]) for e in nxc.sets(self.free)}
        tk = sorted(o for o in cs if o[0] in nxc.TOGGLE_KINDS)
        good = bytes((1, nxc.RULE_NEEDS)) + bytes(tk[0]) + bytes(tk[1])
        self.assertEqual(len(nxc.rules_of(reseal(rules_body(good)))), 1)
        for name, edit in (("empty", rules_body(b"")), ("short", rules_body(good[:-1])), ("long", rules_body(good + b"\0")),
                           ("a type", rules_body(bytes((1, 3)) + good[2:])), ("a high bit", rules_body(bytes((1, 0x42)) + good[2:])),
                           ("no such option", rules_body(good[:2] + bytes((3, 99)) + good[4:])),
                           ("one option twice", rules_body(good[:2] + good[2:4] * 2)),
                           ("twice", lambda bl: bl + [[nxc.RULES_TAG, good]]),
                           ("the flag alone", lambda bl: [[t, bytes((d[0], d[1] | nxc.OPT_RULES, d[2])) if t == b"OPT1" else d] for t, d in bl if t != nxc.RULES_TAG])):
            with self.subTest(name):
                with self.assertRaises(nxc.Wrong):
                    nxc.apply(reseal(edit), game=self.tap, toggles=["Smooth scrolling"])

    def test_a_later_version_is_skipped(self):
        st = nxc.check_key(self.free, self.tap)[0]
        nonce, bl = nxc.blocks(self.linked)
        f = nxc.seal(self.linked[:nxc.CHECK_AT], [[b"OPR2" if t == nxc.RULES_TAG else t, d] for t, d in bl], st)
        self.assertIsNone(nxc.rules_of(f))
        with self.assertRaises(nxc.Wrong):                      # read as a patch without rules: two at once
            nxc.menu_presets(f, colours="Colour", toggles=["Smooth scrolling", "Cursor keys"])

    def test_the_command_line(self):
        import os, subprocess, sys, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as d:
            d = Path(d)
            (d / "p.nxc").write_bytes(self.plain); (d / "game.tap").write_bytes(self.tap)
            tool = [sys.executable, str(T.ROOT / "tools" / "nxc.py")]
            out = subprocess.run(tool + ["rules", str(d / "p.nxc"), str(d / "game.tap"), "-o", str(d / "r.nxc"), "--implies", "Centred view=Smooth scrolling"],
                                 capture_output=True, text=True, check=True).stdout
            self.assertIn("rule: Centred view implies Smooth scrolling", out)
            self.assertEqual((d / "r.nxc").read_bytes(), self.linked)
            subprocess.run(tool + [str(d / "r.nxc"), str(d / "game.tap"), "-o", str(d / "m.nex"), "--colours", "Colour",
                                   "--toggle", "Smooth scrolling", "--toggle", "Centred view", "--toggle", "Cursor keys"], capture_output=True, check=True)
            self.assertEqual((d / "m.nex").read_bytes(), nxc.apply_menu(self.linked, self.tap, colours="Colour",
                                                                       toggles=["Smooth scrolling", "Centred view", "Cursor keys"]))


def set_rules_report(f):
    st = nxc.check_key(f, Rules.tap)[0]
    return nxc.rules_report(f, st, nxc.rules_of(f))


if __name__ == "__main__":
    unittest.main()

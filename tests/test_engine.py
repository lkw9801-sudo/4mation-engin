"""Tests for the native core and the reference engine.

The ground truth is the original rules engine (rules.py) plus a plain
memoised minimax written directly on top of it (`brute`), which shares no
code with the native search.
"""
import random
import unittest

from fourmation import native as nv
from fourmation.rules import (
    P1, P2, RuleConfig, State, TRANSFORMS, apply_move, legal_moves, new_game, parse_coord,
    to_coord, transform_state,
)

MATE = nv.MATE


def brute(st, memo):
    """Exact negamax value: a win completed at cube count k scores MATE-k."""
    if st.winner is not None:
        return 0 if st.winner == 0 else -(MATE - st.ply)
    k = st.key()
    if k in memo:
        return memo[k]
    v = max(-brute(apply_move(st, m, validate=False), memo) for m in legal_moves(st))
    memo[k] = v
    return v


def random_position(rng, lo, hi, rules=None):
    while True:
        st = new_game(rules) if rules else new_game()
        target = rng.randrange(lo, hi)
        while not st.is_terminal and st.ply < target:
            st = apply_move(st, rng.choice(legal_moves(st)))
        if not st.is_terminal:
            return st


def perft_py(st, d):
    if st.is_terminal or d == 0:
        return 1
    return sum(perft_py(apply_move(st, m, validate=False), d - 1) for m in legal_moves(st))


@unittest.skipUnless(nv.AVAILABLE, "native core not built")
class NativeRules(unittest.TestCase):
    def test_legal_and_status_match_rules_py(self):
        L = nv.lib()
        L.fm_set_rules(1, 1)
        rng = random.Random(3)
        for _ in range(300):
            st = new_game()
            while True:
                enc = nv.encode(st.board, st.last, st.to_move)
                status = L.fm_status(*enc)
                if st.is_terminal:
                    self.assertEqual(status, {P1: 1, P2: 2, 0: 3}[st.winner], st.to_compact())
                    break
                self.assertEqual(status, 0, st.to_compact())
                self.assertEqual(nv.mask_to_indices(L.fm_legal(*enc)), sorted(legal_moves(st)))
                st = apply_move(st, rng.choice(legal_moves(st)))

    def test_perft(self):
        L = nv.lib()
        L.fm_set_rules(1, 1)
        st = new_game()
        self.assertEqual([L.fm_perft(*nv.encode(st.board, st.last, st.to_move), d) for d in (1, 2, 3, 4)],
                         [49, 312, 1824, 9984])
        rng = random.Random(8)
        for _ in range(15):
            st = random_position(rng, 5, 35)
            self.assertEqual(L.fm_perft(*nv.encode(st.board, st.last, st.to_move), 3), perft_py(st, 3))

    def test_no_move_fallback_config(self):
        rows = [".......", ".......", ".......", ".......", ".......", "XX.....", "OX....."]
        L = nv.lib()
        for fb, expect in ((1, 45), (0, 0)):
            L.fm_set_rules(fb, 1)
            st = State.from_rows(rows, to_move=P1, last="a1")
            got = L.fm_legal(*nv.encode(st.board, st.last, st.to_move))
            self.assertEqual(bin(got).count("1"), expect)
        L.fm_set_rules(1, 1)

    def test_dead_end_sackgasse(self):
        st = State.from_rows([".......", ".......", ".......", ".......", "....O..", "XO.....", "OX....."],
                             to_move=P1, last="a1")
        got = nv.mask_to_indices(nv.lib().fm_legal(*nv.encode(st.board, st.last, st.to_move)))
        self.assertEqual(got, sorted(legal_moves(st)))
        self.assertNotIn(parse_coord("g7"), got)


@unittest.skipUnless(nv.AVAILABLE, "native core not built")
class ExactSolve(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fourmation.engine import Engine
        cls.eng = Engine(tt_mb=32)

    def test_solve_matches_brute_force_with_distance(self):
        rng = random.Random(21)
        for _ in range(40):
            st = random_position(rng, 36, 45)
            ev = brute(st, {})
            sol = self.eng.solve(st)
            self.assertEqual(sol["score"], ev, st.to_compact())
            self.assertTrue(sol["distance_exact"])
            want = "EXACT_DRAW" if ev == 0 else ("EXACT_WIN" if ev > 0 else "EXACT_LOSS")
            self.assertEqual(sol["result"], want)
            if ev:
                self.assertEqual(sol["distance"], (MATE - abs(ev)) - st.ply)

    def test_full_depth_search_equals_brute_force_for_all_option_sets(self):
        rng = random.Random(4)
        cases = [random_position(rng, 37, 45) for _ in range(25)]
        exact = [brute(st, {}) for st in cases]
        opt_sets = [{}, {"sym": 0}, {"tt": 0}, {"pvs": 0}, {"safe_prune": 0}, {"mdp": 0},
                    {"dead_prune": 0}, {"etc": 1, "reply_order": 1}, {"ext_forced": 1, "leaf_win3": 1}]
        from fourmation.engine import Engine
        for opts in opt_sets:
            eng = Engine(tt_mb=16, options=opts)
            eng.clear()
            for st, ev in zip(cases, exact):
                r = eng.search(st, 100)
                self.assertFalse(r.aborted)
                self.assertEqual(r.score, ev, (opts, st.to_compact()))
                w = eng.search(st, 100, -1, 1).score
                self.assertEqual((w > 0) - (w < 0), (ev > 0) - (ev < 0), (opts, st.to_compact()))

    def test_analyze_every_move_exact_late(self):
        rng = random.Random(77)
        for _ in range(8):
            st = random_position(rng, 38, 45)
            rows = self.eng.analyze(st, time=3.0)
            self.assertEqual(sorted(parse_coord(r["move"]) for r in rows), sorted(legal_moves(st)))
            for r in rows:
                self.assertTrue(r["exact"], r)
                c = apply_move(st, parse_coord(r["move"]))
                cv = (0 if c.winner == 0 else MATE - c.ply) if c.is_terminal else -brute(c, {})
                self.assertEqual(r["score"], cv, (st.to_compact(), r))
            self.assertEqual(rows[0]["score"], brute(st, {}))

    def test_symmetry_invariance(self):
        rng = random.Random(9)
        for _ in range(6):
            st = random_position(rng, 30, 40)
            base = self.eng.solve(st)["score"]
            for k in range(8):
                t = transform_state(st, k)
                self.eng.clear()
                self.assertEqual(self.eng.solve(t)["score"], base)
                # and with the TT still holding the untransformed position's entries
                self.assertEqual(self.eng.solve(st)["score"], base)
                self.assertEqual(self.eng.solve(t)["score"], base)

    def test_rule_sensitivity_flag(self):
        st = State.from_rows([".......", ".......", ".......", ".......", ".......", "XX.....", "OX....."],
                             to_move=P1, last="a1")
        info = self.eng.think(st, depth=2)
        self.assertTrue(info.rule_sensitive)
        st2 = random_position(random.Random(1), 20, 30)
        self.assertFalse(self.eng.think(st2, depth=4).rule_sensitive)


TACTICS = [
    # (compact position, winning moves, distance in plies)
    ("XOOX...OXOXO..X.OX.X.O...XOXX....O..OX........... O c6", {"d7"}, 7),
    ("..XO.....XOXOOOO.OXXXXX......O.....X............. O a6", {"a5"}, 5),
    ("......X.....OO...OX.X..XXOO..OOX.X...X.O......... X e6", {"d7"}, 5),
    ("....XO.....XO.....XX.....OOO.....XX..OXO...X.XO.. O b7", {"c7"}, 5),
]


@unittest.skipUnless(nv.AVAILABLE, "native core not built")
class Tactics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fourmation.engine import Engine
        cls.eng = Engine(tt_mb=32)

    def test_forced_wins_found_with_exact_distance(self):
        for comp, wins, dist in TACTICS:
            st = State.from_compact(comp)
            sol = self.eng.solve(st)
            self.assertEqual(sol["result"], "EXACT_WIN", comp)
            self.assertEqual(sol["distance"], dist, comp)
            info = self.eng.think(st, time=1.0)
            self.assertIn(info.move, wins, comp)
            self.assertEqual(info.result, "EXACT_WIN")
            rows = self.eng.analyze(st, time=2.0)
            winners = {r["move"] for r in rows if r["result"] == "EXACT_WIN" and r["distance"] == dist}
            self.assertEqual(winners, wins, comp)

    def test_takes_immediate_win(self):
        st = State.from_rows([".......", ".......", ".......", ".......", ".......", "OOO....", "XXX...."],
                             to_move=P1, last="c2")
        info = self.eng.think(st, time=0.2)
        self.assertEqual(info.move, "d1")
        self.assertEqual(info.distance, 1)

    def test_never_allows_immediate_loss_when_avoidable(self):
        rng = random.Random(31)
        checked = 0
        while checked < 60:
            st = random_position(rng, 8, 40)
            safe = [m for m in legal_moves(st)
                    if not any(apply_move(apply_move(st, m), r).winner == 3 - st.to_move
                               for r in legal_moves(apply_move(st, m)) if not apply_move(st, m).is_terminal)]
            if not safe:
                continue
            checked += 1
            m = self.eng.think(st, time=0.05).move_index
            after = apply_move(st, m)
            if after.is_terminal:
                continue
            for r in legal_moves(after):
                self.assertNotEqual(apply_move(after, r).winner, 3 - st.to_move, st.to_compact())

    def test_blocks_forced_single_defence(self):
        # X has e1 f1 g1 and threatens d1; O (to move next to e1) must take d1
        st = State.from_compact("....XXX.....OO................................... O e1")
        info = self.eng.think(st, time=0.5)
        self.assertEqual(info.move, "d1")


@unittest.skipUnless(nv.AVAILABLE, "native core not built")
class PythonMirror(unittest.TestCase):
    def test_pyengine_matches_native_on_exact_positions(self):
        from fourmation.engine import Engine
        from fourmation.pyengine import PyEngine
        eng = Engine(tt_mb=16)
        rng = random.Random(55)
        for _ in range(12):
            st = random_position(rng, 38, 45)
            r = PyEngine().think(st, depth=48)
            self.assertEqual(r["score"], brute(st, {}), st.to_compact())
            self.assertEqual(r["score"], eng.search(st, 100).score)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(nv.AVAILABLE, "native core not built")
class PlayKeepsValue(unittest.TestCase):
    def test_play_never_throws_away_a_proven_result(self):
        from fourmation.engine import Engine
        eng = Engine(tt_mb=64)
        rng = random.Random(123)
        seen = {"EXACT_WIN": 0, "EXACT_DRAW": 0, "EXACT_LOSS": 0}
        tries = 0
        while min(seen["EXACT_WIN"], seen["EXACT_DRAW"]) < 5 and tries < 400:
            tries += 1
            st = random_position(rng, 14, 36)
            sol = eng.solve(st, time=2.0, distance=False)
            if sol is None:
                continue
            info = eng.play(st, time=0.3)
            self.assertIn(info.move_index, legal_moves(st))
            seen[sol["result"]] += 1
            c = apply_move(st, info.move_index)
            if c.is_terminal:
                cv = "EXACT_WIN" if c.winner == st.to_move else "EXACT_DRAW"
            else:
                cs = eng.solve(c, time=5.0, distance=False)
                cv = {"EXACT_WIN": "EXACT_LOSS", "EXACT_LOSS": "EXACT_WIN", "EXACT_DRAW": "EXACT_DRAW"}[cs["result"]]
            self.assertEqual(cv, sol["result"], st.to_compact())
        self.assertGreaterEqual(seen["EXACT_WIN"], 5)
        self.assertGreaterEqual(seen["EXACT_DRAW"], 5)


@unittest.skipUnless(nv.AVAILABLE, "native core not built")
class PersistentTT(unittest.TestCase):
    """Regression: a shallow search used to overwrite the best move of a deeper
    (exact) TT entry, so a later TT cutoff returned a proven value together with
    a heuristic move. Values were right, moves were not."""

    def test_moves_keep_proven_values_across_searches(self):
        from fourmation.engine import Engine
        rng = random.Random(2024)
        checker = Engine(tt_mb=16)
        claims = 0
        for g in range(12):
            eng = Engine(tt_mb=32)  # one engine per game: TT persists across moves
            st = new_game()
            for _ in range(rng.randint(4, 7)):
                st = apply_move(st, rng.choice(legal_moves(st)))
            while not st.is_terminal:
                # mix the three entry points so the TT holds heuristic, exact and
                # null-window entries of the same positions
                eng.think(st, depth=rng.randint(4, 12))
                if rng.random() < 0.5:
                    eng.solve(st, time=0.2, distance=False)
                info = eng.play(st, time=0.05)
                if info.result in ("EXACT_WIN", "EXACT_DRAW") and st.ply >= 10:
                    c = apply_move(st, info.move_index)
                    if c.is_terminal:
                        got = "EXACT_WIN" if c.winner == st.to_move else "EXACT_DRAW"
                    else:
                        checker.clear()
                        s = checker.solve(c, time=10, distance=False)
                        got = {"EXACT_WIN": "EXACT_LOSS", "EXACT_LOSS": "EXACT_WIN", "EXACT_DRAW": "EXACT_DRAW"}[s["result"]]
                    self.assertEqual(got, info.result, (st.to_compact(), info.move))
                    claims += 1
                st = apply_move(st, info.move_index if rng.random() < 0.7 else rng.choice(legal_moves(st)))
        self.assertGreater(claims, 50)


@unittest.skipUnless(nv.AVAILABLE, "native core not built")
class GradeMove(unittest.TestCase):
    def test_grades_on_solved_position(self):
        from fourmation.engine import Engine
        eng = Engine(tt_mb=64)
        st = State.from_compact(".XO....XO.....OXO....OOXX...XX.OX..O............. X c1")  # bench 'mid'
        rows = eng.analyze(st, time=5.0)
        g = {m: eng.grade_move(st, m, rows=rows) for m in ("d2", "c2", "d1")}
        self.assertEqual(g["d2"]["verdict"], "BEST")
        self.assertEqual(g["d2"]["move_distance"], 15)
        self.assertEqual(g["c2"]["verdict"], "SLOWER_WIN")
        self.assertEqual(g["c2"]["plies_lost"], 10)
        self.assertEqual(g["d1"]["verdict"], "WIN_TO_DRAW")
        self.assertEqual(eng.grade_move(st, "a7", rows=rows)["verdict"], "ILLEGAL")


@unittest.skipUnless(nv.AVAILABLE, "native core not built")
class EngineIsolation(unittest.TestCase):
    """Regression: the native TT used to be one global table, so a second Engine
    wiped/resized the first one's TT and engines with different evaluations
    reused each other's entries (changing scores and even moves)."""

    @staticmethod
    def _positions():
        rng = random.Random(17)
        return [random_position(rng, 6, 14) for _ in range(10)]

    def test_engines_with_different_weights_do_not_mix(self):
        from fourmation.engine import Engine
        from fourmation.engine_defaults import LEGACY_WEIGHTS
        pos = self._positions()
        clean_a, clean_b = [], []
        for st in pos:
            i = Engine(tt_mb=32).think(st, depth=9)
            clean_a.append((i.move, i.score, i.nodes))
            i = Engine(tt_mb=32, weights=LEGACY_WEIGHTS).think(st, depth=9)
            clean_b.append((i.move, i.score, i.nodes))
        a = Engine(tt_mb=32)
        b = Engine(tt_mb=1, weights=LEGACY_WEIGHTS)
        for st, ca, cb in zip(pos, clean_a, clean_b):
            a.clear()
            b.clear()
            b.think(st, depth=9)  # B fills its own table first
            ia = a.think(st, depth=9)
            self.assertEqual((ia.move, ia.score, ia.nodes), ca)  # identical to a lone engine
            b.clear()
            a.think(st, depth=9)  # and the other way round
            ib = b.think(st, depth=9)
            self.assertEqual((ib.move, ib.score), cb[:2])

    def test_table_survives_other_engines(self):
        from fourmation.engine import Engine
        st = self._positions()[0]
        a = Engine(tt_mb=32)
        first = a.think(st, depth=10).nodes
        warm = a.think(st, depth=10).nodes
        self.assertLess(warm, first)
        others = [Engine(tt_mb=4) for _ in range(5)]
        for o in others:
            o.think(st, depth=6)
        del others
        self.assertEqual(a.think(st, depth=10).nodes, warm)

    def test_threads_give_sequential_results(self):
        import threading
        from fourmation.engine import Engine
        pos = self._positions()
        expect = []
        for st in pos:
            e = Engine(tt_mb=16)
            expect.append(e.search(st, 100, -1, 1, time=20).score if st.ply >= 12 else e.think(st, depth=8).score)
        got = {}

        def worker(k):
            e = Engine(tt_mb=16)
            got[k] = [e.search(st, 100, -1, 1, time=20).score if st.ply >= 12 else e.think(st, depth=8).score
                      for st in pos]

        ts = [threading.Thread(target=worker, args=(k,)) for k in range(3)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        for k in range(3):
            self.assertEqual(got[k], expect)

import os
import random
import tempfile
import unittest

from fourmation import native as nv
from fourmation.book import Book, canonical, prove
from fourmation.rules import TRANSFORMS, apply_move, legal_moves, new_game, parse_coord, to_coord, transform_state


def rand_pos(rng, lo, hi):
    while True:
        st = new_game()
        t = rng.randrange(lo, hi)
        while not st.is_terminal and st.ply < t:
            st = apply_move(st, rng.choice(legal_moves(st)))
        if not st.is_terminal:
            return st


class Canonical(unittest.TestCase):
    def test_invariant_under_symmetry(self):
        rng = random.Random(2)
        for _ in range(20):
            st = rand_pos(rng, 1, 30)
            c = canonical(st)[0]
            for k in range(8):
                self.assertEqual(canonical(transform_state(st, k))[0], c)

    def test_book_move_orientation(self):
        rng = random.Random(3)
        for _ in range(20):
            st = rand_pos(rng, 3, 30)
            m = rng.choice(legal_moves(st))
            b = Book()
            b.put(st, "WIN", to_coord(m))
            for k in range(8):
                t = transform_state(st, k)
                e = b.get(t)
                self.assertEqual(parse_coord(e["best"]), TRANSFORMS[k][m])
                self.assertIn(parse_coord(e["best"]), legal_moves(t))


@unittest.skipUnless(nv.AVAILABLE, "native core not built")
class Prove(unittest.TestCase):
    def test_prove_matches_direct_solve(self):
        from fourmation.engine import Engine
        eng = Engine(tt_mb=32)
        rng = random.Random(5)
        with tempfile.TemporaryDirectory() as d:
            for i in range(4):
                st = rand_pos(rng, 30, 38)
                book = Book(os.path.join(d, f"b{i}.json"))
                v = prove(st, 2, book, procs=1, tt_mb=32, log=lambda *a: None)
                want = {"EXACT_WIN": "WIN", "EXACT_LOSS": "LOSS", "EXACT_DRAW": "DRAW"}[eng.solve(st)["result"]]
                self.assertEqual(v, want, st.to_compact())
                e = Book(book.path).get(st)
                self.assertEqual(e["result"], want)
                if want != "LOSS":
                    # the stored move keeps the value
                    c = apply_move(st, parse_coord(e["best"]))
                    cv = "WIN" if c.winner == st.to_move else ("DRAW" if c.winner == 0 else None)
                    if cv is None:
                        cv = {"EXACT_WIN": "LOSS", "EXACT_LOSS": "WIN", "EXACT_DRAW": "DRAW"}[eng.solve(c)["result"]]
                    self.assertEqual(cv, want)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(nv.AVAILABLE, "native core not built")
class StrategyBook(unittest.TestCase):
    def test_default_book_moves_are_proven_wins(self):
        import os
        from fourmation.engine import Engine
        from fourmation.rules import State
        path = os.path.join(os.path.dirname(__import__("fourmation").__file__), "data", "x_strategy_book.json")
        book = Book(path)
        eng = Engine(tt_mb=64)
        rng = random.Random(0)
        wins = [(k, e) for k, e in book.data.items() if e["result"] == "WIN" and e.get("best")]
        self.assertGreater(len(wins), 1000)
        sample = [w for w in wins if State.from_compact(w[0]).ply >= 8]
        for key, e in rng.sample(sample, 25):
            st = State.from_compact(key)
            self.assertEqual(st.to_move, 1)  # the winner is the first player
            child = apply_move(st, parse_coord(e["best"]))
            if child.is_terminal:
                self.assertEqual(child.winner, 1)
                continue
            sol = eng.solve(child, time=20, distance=False)
            self.assertEqual(sol["result"], "EXACT_LOSS", key)
        # the root entry is the proven first move
        self.assertEqual(book.get(new_game())["best"], "d4")

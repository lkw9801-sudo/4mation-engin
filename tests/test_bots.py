import unittest

from fourmation.arena import play_game, random_opening
from fourmation.bots import AlphaBetaBot, RandomBot, make_bot
from fourmation.rules import P1, P2, State, legal_moves, parse_coord, to_coord


class AlphaBeta(unittest.TestCase):
    def test_takes_immediate_win(self):
        # X has a1 b1 c1; O's last cube is c2 so d1 is reachable.
        st = State.from_rows([
            ". . . . . . .",
            ". . . . . . .",
            ". . . . . . .",
            ". . . . . . .",
            ". . . . . . .",
            "O O O . . . .",
            "X X X . . . .",
        ], to_move=P1, last="c2")
        self.assertIn(parse_coord("d1"), legal_moves(st))
        for depth in (1, 2, 4):
            self.assertEqual(to_coord(AlphaBetaBot(depth, seed=0).select(st)), "d1")

    def test_avoids_handing_opponent_a_win(self):
        # O threatens d2 (a2 b2 c2 + d2). X must not play next to d2.
        st = State.from_rows([
            ". . . . . . .",
            ". . . . . . .",
            ". . . . . . .",
            ". . . . . . .",
            ". . . . . . .",
            "O O O . . . .",
            "X X . . . . X",
        ], to_move=P1, last="c2")
        from fourmation.rules import apply_move
        for depth in (2, 3, 4):
            m = AlphaBetaBot(depth, seed=0).select(st)
            after = apply_move(st, m)
            for reply in legal_moves(after):
                self.assertNotEqual(apply_move(after, reply).winner, P2, (depth, to_coord(m)))

    def test_analyze_scores_every_legal_move(self):
        st = State.from_rows(["." * 7] * 6 + ["X......"], to_move=P2, last="a1")
        scores = AlphaBetaBot(2, seed=0).analyze(st)
        self.assertEqual(sorted(m for m, _ in scores), sorted(legal_moves(st)))

    def test_make_bot(self):
        self.assertIsInstance(make_bot("random"), RandomBot)
        self.assertEqual(make_bot("ab3").depth, 3)
        with self.assertRaises(ValueError):
            make_bot("minimax")


class Games(unittest.TestCase):
    def test_alphabeta_beats_random(self):
        import random
        rng = random.Random(0)
        wins = 0
        for g in range(10):
            ab_col = P1 if g % 2 == 0 else P2
            bots = {ab_col: AlphaBetaBot(2, seed=g), 3 - ab_col: RandomBot(seed=g)}
            rec = play_game(bots, random_opening(2, rng))
            wins += rec.winner == ab_col
        self.assertGreaterEqual(wins, 9)


if __name__ == "__main__":
    unittest.main()

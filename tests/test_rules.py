import random
import unittest

from fourmation.rules import (
    CUBES_PER_PLAYER,
    N,
    NEIGHBORS,
    P1,
    P2,
    WINDOWS,
    RuleConfig,
    State,
    TRANSFORMS,
    apply_move,
    legal_moves,
    line_length_through,
    new_game,
    parse_coord,
    to_coord,
    transform_state,
)


def coords(moves):
    return sorted(to_coord(m) for m in moves)


def play(*cs, st=None):
    st = st or new_game()
    for c in cs:
        st = apply_move(st, parse_coord(c))
    return st


class Geometry(unittest.TestCase):
    def test_coordinates_roundtrip(self):
        for i in range(N):
            self.assertEqual(parse_coord(to_coord(i)), i)
        self.assertEqual(to_coord(0), "a1")
        self.assertEqual(to_coord(48), "g7")

    def test_neighbour_counts(self):
        self.assertEqual(len(NEIGHBORS[parse_coord("a1")]), 3)
        self.assertEqual(len(NEIGHBORS[parse_coord("a4")]), 5)
        self.assertEqual(len(NEIGHBORS[parse_coord("d4")]), 8)

    def test_window_count(self):
        # 7 rows x 4 + 7 cols x 4 + 2 diagonals x 4 x 4
        self.assertEqual(len(WINDOWS), 88)

    def test_transforms_are_permutations(self):
        self.assertEqual(len(set(TRANSFORMS)), 8)
        for p in TRANSFORMS:
            self.assertEqual(sorted(p), list(range(N)))


class Placement(unittest.TestCase):
    def test_first_move_anywhere(self):
        self.assertEqual(len(legal_moves(new_game())), 49)

    def test_must_touch_last_cube_incl_diagonal(self):
        st = play("d4")
        self.assertEqual(coords(legal_moves(st)),
                         ["c3", "c4", "c5", "d3", "d5", "e3", "e4", "e5"])

    def test_corner_last_cube(self):
        st = play("a1")
        self.assertEqual(coords(legal_moves(st)), ["a2", "b1", "b2"])

    def test_adjacency_is_to_last_cube_not_own(self):
        st = play("d4", "e5")  # X to move, must touch O's e5
        self.assertEqual(coords(legal_moves(st)),
                         ["d5", "d6", "e4", "e6", "f4", "f5", "f6"])

    def test_illegal_move_rejected(self):
        st = play("d4")
        with self.assertRaises(ValueError):
            apply_move(st, parse_coord("g7"))

    def test_dead_end_any_cell_next_to_opponent(self):
        # O's last cube a1 is fully surrounded; X may play next to any O cube.
        st = State.from_rows([
            ". . . . . . .",
            ". . . . . . .",
            ". . . . . . .",
            ". . . . . . .",
            ". . . . O . .",
            "X O . . . . .",
            "O X . . . . .",
        ], to_move=P1, last="a1")
        self.assertIsNone(st.winner)
        expect = {"a3", "b3", "c1", "c2", "c3"}  # free cells next to O at a1, b2
        expect |= {"d2", "d3", "d4", "e2", "e4", "f2", "f3", "f4"}  # next to O at e3
        self.assertEqual(set(coords(legal_moves(st))), expect)

    def test_no_move_fallback_any_empty(self):
        # Last cube (O at a1) surrounded and no free cell touches any O cube.
        rows = [
            ". . . . . . .",
            ". . . . . . .",
            ". . . . . . .",
            ". . . . . . .",
            ". . . . . . .",
            "X X . . . . .",
            "O X . . . . .",
        ]
        st = State.from_rows(rows, to_move=P1, last="a1")
        self.assertEqual(len(legal_moves(st)), 49 - 4)
        st2 = State.from_rows(rows, to_move=P1, last="a1",
                              rules=RuleConfig(no_move_fallback="draw"))
        self.assertEqual(st2.winner, 0)


class Winning(unittest.TestCase):
    def _win(self, rows, last):
        st = State.from_rows(rows, last=last)
        self.assertEqual(st.winner, P1)
        self.assertEqual(legal_moves(st), [])

    def test_horizontal(self):
        # X: a1 b1 c1 d1 via legal sequence
        st = play("a1", "a2", "b1", "b2", "c1", "c2")
        self.assertIsNone(st.winner)
        st = apply_move(st, parse_coord("d1"))
        self.assertEqual(st.winner, P1)
        self.assertTrue(st.is_terminal)
        self.assertEqual(legal_moves(st), [])

    def test_vertical_diagonal_antidiagonal(self):
        for cells in (["c2", "c3", "c4", "c5"], ["a1", "b2", "c3", "d4"], ["g1", "f2", "e3", "d4"]):
            board = [["."] * 7 for _ in range(7)]
            for c in cells:
                i = parse_coord(c)
                r, col = divmod(i, 7)
                board[6 - r][col] = "X"
            # give O three scattered cubes so counts are consistent
            for c in ("a7", "c7", "e7"):
                i = parse_coord(c)
                r, col = divmod(i, 7)
                board[6 - r][col] = "O"
            st = State.from_rows([" ".join(r) for r in board], last=cells[-1])
            self.assertEqual(st.winner, P1, cells)

    def test_five_in_a_row_counts(self):
        board = ["X X . X X . .", ". . . . . . .", ". . . . . . .", ". . . . . . .",
                 ". . . . . . .", ". . . . . . .", "O O O . . . ."]
        st = State.from_rows(board, to_move=P1, last="b7")
        self.assertIsNone(st.winner)
        st = apply_move(st, parse_coord("c7"), validate=False)
        self.assertEqual(line_length_through(st.board, parse_coord("c7")), 5)
        self.assertEqual(st.winner, P1)


class Draw(unittest.TestCase):
    def test_draw_when_no_open_line(self):
        # Rows alternate so every horizontal/vertical/diagonal window is mixed,
        # leaving one empty cell.
        pattern = ["XXOOXXO", "OOXXOOX", "XXOOXXO", "OOXXOOX", "XXOOXXO", "OOXXOOX", "OXOOXX."]
        st = State.from_rows(pattern)
        self.assertEqual(st.winner, 0)

    def test_exhaustion_rule_keeps_playing(self):
        pattern = ["XXOOXXO", "OOXXOOX", "XXOOXXO", "OOXXOOX", "XXOOXXO", "OOXXOOX", "OXOOXX."]
        st = State.from_rows(pattern, rules=RuleConfig(draw_rule="exhaustion"))
        # 24 X and 24 O placed: nobody has cubes left -> draw by exhaustion too
        self.assertEqual(st.placed, (CUBES_PER_PLAYER, CUBES_PER_PLAYER))
        self.assertEqual(st.winner, 0)


class RandomPlayouts(unittest.TestCase):
    def test_invariants(self):
        rng = random.Random(0)
        outcomes = {0: 0, P1: 0, P2: 0}
        for _ in range(500):
            st = new_game()
            while not st.is_terminal:
                ms = legal_moves(st)
                self.assertTrue(ms)
                self.assertEqual(len(set(ms)), len(ms))
                for m in ms:
                    self.assertEqual(st.board[m], 0)
                st = apply_move(st, rng.choice(ms))
                self.assertLessEqual(st.ply, 48)
                self.assertEqual(st.placed, (st.board.count(P1), st.board.count(P2)))
            # winner consistency with a full board scan
            full = {p for p in (P1, P2) for w in WINDOWS if all(st.board[i] == p for i in w)}
            if st.winner in (P1, P2):
                self.assertEqual(full, {st.winner})
            else:
                self.assertEqual(full, set())
            outcomes[st.winner] += 1
        self.assertGreater(outcomes[P1] + outcomes[P2], 0)

    def test_symmetry_preserves_legality(self):
        rng = random.Random(1)
        st = new_game()
        for _ in range(10):
            st = apply_move(st, rng.choice(legal_moves(st)))
        base = set(legal_moves(st))
        for k in range(8):
            t = transform_state(st, k)
            self.assertEqual(set(legal_moves(t)), {TRANSFORMS[k][m] for m in base})


if __name__ == "__main__":
    unittest.main()

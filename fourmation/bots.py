"""Baseline players: random and alpha-beta (negamax with a transposition table)."""
from __future__ import annotations

import math
import random
from typing import Dict, List, Optional, Tuple

from .rules import (
    EMPTY,
    N,
    WINDOWS,
    WINDOWS_THROUGH,
    State,
    apply_move,
    legal_moves,
)

WIN_SCORE = 1_000_000
# Value of a still-open 4-window holding k own cubes and no opponent cube.
WINDOW_WEIGHTS = (0, 1, 8, 64)
CELL_WEIGHT = tuple(len(WINDOWS_THROUGH[i]) for i in range(N))


class Bot:
    name = "bot"

    def select(self, st: State) -> int:
        raise NotImplementedError


class RandomBot(Bot):
    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)
        self.name = "random"

    def select(self, st: State) -> int:
        return self.rng.choice(legal_moves(st))


def evaluate(st: State, player: int) -> int:
    """Static score from `player`'s point of view (window counting)."""
    opp = 3 - player
    score = 0
    b = st.board
    for w in WINDOWS:
        mine = theirs = 0
        for i in w:
            v = b[i]
            if v == player:
                mine += 1
            elif v == opp:
                theirs += 1
        if theirs == 0 and mine:
            score += WINDOW_WEIGHTS[mine]
        elif mine == 0 and theirs:
            score -= WINDOW_WEIGHTS[theirs]
    return score


_EXACT, _LOWER, _UPPER = 0, 1, 2


class AlphaBetaBot(Bot):
    """Fixed-depth negamax alpha-beta.

    Scores are from the side to move: +WIN_SCORE - ply for a forced win.
    Ties between equally scored root moves are broken randomly (seeded) so
    that repeated games differ.
    """

    def __init__(self, depth: int = 4, seed: Optional[int] = None):
        self.depth = depth
        self.rng = random.Random(seed)
        self.name = f"ab{depth}"
        self.nodes = 0
        self.tt: Dict[Tuple, Tuple[int, int, int, Optional[int]]] = {}

    # -- public ---------------------------------------------------------
    def select(self, st: State) -> int:
        scores = self.analyze(st, full=False)
        best = max(s for _, s in scores)
        return self.rng.choice([m for m, s in scores if s == best])

    def analyze(self, st: State, full: bool = True) -> List[Tuple[int, int]]:
        """Root move scores. full=True searches every move with an open window
        (exact values, for explanations); full=False only proves the best."""
        self.tt.clear()
        moves = self._ordered(st, legal_moves(st), None)
        out: List[Tuple[int, int]] = []
        alpha = -math.inf
        for m in moves:
            child = apply_move(st, m, validate=False)
            if full:
                v = -self._negamax(child, self.depth - 1, -math.inf, math.inf, 1)
            else:
                # search one point below alpha so ties with the best move stay visible
                v = -self._negamax(child, self.depth - 1, -math.inf, -(alpha - 1), 1)
                alpha = max(alpha, v)
            out.append((m, int(v)))
        return out

    # -- search ---------------------------------------------------------
    def _negamax(self, st: State, depth: int, alpha: float, beta: float, ply: int) -> float:
        self.nodes += 1
        if st.winner is not None:
            if st.winner == 0:
                return 0
            return -(WIN_SCORE - ply)  # the side to move has lost
        if depth == 0:
            return evaluate(st, st.to_move)

        key = st.key()
        tt_move = None
        hit = self.tt.get(key)
        if hit is not None:
            d, flag, val, tt_move = hit
            if d >= depth:
                if flag == _EXACT:
                    return val
                if flag == _LOWER and val >= beta:
                    return val
                if flag == _UPPER and val <= alpha:
                    return val

        alpha0 = alpha
        best_val = -math.inf
        best_move = None
        for m in self._ordered(st, legal_moves(st), tt_move):
            v = -self._negamax(apply_move(st, m, validate=False), depth - 1, -beta, -alpha, ply + 1)
            if v > best_val:
                best_val, best_move = v, m
            if v > alpha:
                alpha = v
            if alpha >= beta:
                break

        flag = _EXACT
        if best_val <= alpha0:
            flag = _UPPER
        elif best_val >= beta:
            flag = _LOWER
        self.tt[key] = (depth, flag, best_val, best_move)
        return best_val

    @staticmethod
    def _ordered(st: State, moves: List[int], first: Optional[int]) -> List[int]:
        ms = sorted(moves, key=lambda m: -CELL_WEIGHT[m])
        if first is not None and first in ms:
            ms.remove(first)
            ms.insert(0, first)
        return ms


def make_bot(spec: str, seed: Optional[int] = None) -> Bot:
    """'random', 'greedy' or 'ab<depth>' (e.g. ab4)."""
    spec = spec.strip().lower()
    if spec == "random":
        return RandomBot(seed)
    if spec == "greedy":
        return GreedyBot(seed)
    if spec.startswith("ab") and spec[2:].isdigit():
        return AlphaBetaBot(int(spec[2:]), seed)
    raise ValueError(f"unknown bot spec {spec!r}")


class GreedyBot(Bot):
    """Simple tactical baseline: win at once if possible, otherwise never hand
    the opponent an immediate win (if avoidable), otherwise the move with the
    best static window count. No search beyond two plies."""

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)
        self.name = "greedy"

    def select(self, st: State) -> int:
        moves = legal_moves(st)
        me = st.to_move
        scored = []
        for m in moves:
            c = apply_move(st, m, validate=False)
            if c.winner == me:
                return m
            loses = (not c.is_terminal) and any(
                apply_move(c, r, validate=False).winner == 3 - me for r in legal_moves(c))
            scored.append((0 if loses else 1, evaluate(c, me), self.rng.random(), m))
        return max(scored)[3]

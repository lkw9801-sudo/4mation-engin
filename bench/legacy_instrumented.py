"""The ORIGINAL AlphaBetaBot with counters added (algorithm unchanged).

Used only to measure the baseline. `test_legacy_instrumented_matches_original`
checks that node counts and chosen moves equal the untouched original.
"""
from __future__ import annotations

import math
import time
from typing import List, Optional, Tuple

from fourmation.bots import WIN_SCORE, AlphaBetaBot, evaluate
from fourmation.rules import State, apply_move, legal_moves, to_coord

_EXACT, _LOWER, _UPPER = 0, 1, 2


class Timeout(Exception):
    pass


class InstrumentedLegacy(AlphaBetaBot):
    def __init__(self, depth: int, seed: Optional[int] = 0, time_limit: float = math.inf):
        super().__init__(depth, seed)
        self.time_limit = time_limit
        self.reset_counters()

    def reset_counters(self):
        self.nodes = 0
        self.tt_probes = 0
        self.tt_hits = 0
        self.tt_cutoffs = 0
        self.interior = 0
        self.beta_cutoffs = 0
        self.first_move_cutoffs = 0
        self.evals = 0
        self._t0 = time.perf_counter()

    def _negamax(self, st: State, depth: int, alpha: float, beta: float, ply: int) -> float:
        self.nodes += 1
        if (self.nodes & 4095) == 0 and time.perf_counter() - self._t0 > self.time_limit:
            raise Timeout()
        if st.winner is not None:
            if st.winner == 0:
                return 0
            return -(WIN_SCORE - ply)
        if depth == 0:
            self.evals += 1
            return evaluate(st, st.to_move)

        key = st.key()
        tt_move = None
        self.tt_probes += 1
        hit = self.tt.get(key)
        if hit is not None:
            self.tt_hits += 1
            d, flag, val, tt_move = hit
            if d >= depth:
                if flag == _EXACT or (flag == _LOWER and val >= beta) or (flag == _UPPER and val <= alpha):
                    self.tt_cutoffs += 1
                    return val

        self.interior += 1
        alpha0 = alpha
        best_val = -math.inf
        best_move = None
        for k, m in enumerate(self._ordered(st, legal_moves(st), tt_move)):
            v = -self._negamax(apply_move(st, m, validate=False), depth - 1, -beta, -alpha, ply + 1)
            if v > best_val:
                best_val, best_move = v, m
            if v > alpha:
                alpha = v
            if alpha >= beta:
                self.beta_cutoffs += 1
                if k == 0:
                    self.first_move_cutoffs += 1
                break

        flag = _EXACT
        if best_val <= alpha0:
            flag = _UPPER
        elif best_val >= beta:
            flag = _LOWER
        self.tt[key] = (depth, flag, best_val, best_move)
        return best_val

    def pv(self, st: State, first: int, max_len: int = 30) -> List[str]:
        out = [to_coord(first)]
        st = apply_move(st, first, validate=False)
        seen = set()
        while not st.is_terminal and len(out) < max_len:
            hit = self.tt.get(st.key())
            if hit is None or hit[3] is None or st.key() in seen:
                break
            seen.add(st.key())
            out.append(to_coord(hit[3]))
            st = apply_move(st, hit[3], validate=False)
        return out


def run(st: State, depth: int, time_limit: float) -> dict:
    """One fixed-depth search exactly as AlphaBetaBot.select() does it (full=False)."""
    bot = InstrumentedLegacy(depth, 0, time_limit)
    t0 = time.perf_counter()
    try:
        scores = bot.analyze(st, full=False)
    except Timeout:
        return {"depth": depth, "timeout": True, "elapsed": time.perf_counter() - t0, "nodes": bot.nodes}
    el = time.perf_counter() - t0
    best = max(s for _, s in scores)
    bm = next(m for m, s in scores if s == best)  # deterministic: first best in search order
    mate = abs(best) >= WIN_SCORE - 100
    return {
        "depth": depth,
        "timeout": False,
        "best": to_coord(bm),
        "score": best,
        "elapsed": el,
        "nodes": bot.nodes,
        "nps": bot.nodes / el if el > 0 else 0.0,
        "tt_hit_rate": bot.tt_hits / max(bot.tt_probes, 1),
        "tt_cutoff_rate": bot.tt_cutoffs / max(bot.tt_probes, 1),
        "beta_cutoffs": bot.beta_cutoffs,
        "cutoff_rate": bot.beta_cutoffs / max(bot.interior, 1),
        "first_move_cutoff_rate": bot.first_move_cutoffs / max(bot.beta_cutoffs, 1),
        "evals": bot.evals,
        "proven": mate or bot.evals == 0,
        "result": ("WIN" if best > 0 else "LOSS") if mate else ("DRAW(exact)" if bot.evals == 0 and best == 0 else "HEURISTIC"),
        "pv": bot.pv(st, bm),
    }

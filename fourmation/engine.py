"""High-level 4Mation reference engine.

    from fourmation.engine import Engine
    eng = Engine()
    info = eng.think(state, time=1.0)          # play: best move + PV
    sol = eng.solve(state, time=5.0)           # exact WIN/DRAW/LOSS (+ distance) or None
    rows = eng.analyze(state, time=5.0)        # every legal move, exact or heuristic

Result types
------------
EXACT_WIN / EXACT_LOSS  proven by search to the end of the game (mate score)
EXACT_DRAW              proven: every line was searched to a terminal position
HEURISTIC               depth-limited value; the score is an evaluation, not a probability

`distance` is the number of plies until the game ends under perfect play (the
winner takes the fastest win, the loser the slowest loss). `distance_exact`
says whether it was verified to be minimal/maximal or is only an upper bound.

`rule_sensitive` is True when the search met a position where the rulebook does
not say what happens (no free cell next to the last cube and none next to any
cube of that colour); such results depend on RuleConfig.no_move_fallback.
"""
from __future__ import annotations

import ctypes
import time as _time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import native as nv
from .engine_defaults import DEFAULT_OPTIONS, DEFAULT_SOLVER_OPTIONS, DEFAULT_WEIGHTS
from .rules import State, apply_move, legal_moves, to_coord

EXACT_WIN = "EXACT_WIN"
EXACT_DRAW = "EXACT_DRAW"
EXACT_LOSS = "EXACT_LOSS"
HEURISTIC = "HEURISTIC"

MATE = nv.MATE
MATE_BOUND = nv.MATE_BOUND
INF = nv.INF
TOTAL_PLIES = 48


def is_mate(v: int) -> bool:
    return v >= MATE_BOUND or v <= -MATE_BOUND


def mate_distance(v: int, cubes: int) -> int:
    """Plies from a position with `cubes` cubes until the game ends."""
    return (MATE - v) - cubes if v > 0 else (MATE + v) - cubes


def classify(v: int, complete: bool) -> str:
    if v >= MATE_BOUND:
        return EXACT_WIN
    if v <= -MATE_BOUND:
        return EXACT_LOSS
    if complete and v == 0:
        return EXACT_DRAW
    return HEURISTIC


@dataclass
class Iteration:
    depth: int
    move: str
    score: int
    nodes: int
    time: float


@dataclass
class SearchInfo:
    move: Optional[str]
    move_index: Optional[int]
    score: int
    depth: int
    result: str
    distance: Optional[int]
    pv: List[str]
    nodes: int
    time: float
    nps: float
    tt_hit_rate: float
    beta_cutoffs: int
    first_move_cutoff_rate: float
    iterations: List[Iteration] = field(default_factory=list)
    rule_sensitive: bool = False
    source: str = "search"  # "book", "solve" (exact solver), "search" (iterative deepening)

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["iterations"] = [it.__dict__ for it in self.iterations]
        return d


def _rules_to_native(st: State) -> None:
    lib = nv.lib()
    lib.fm_set_rules(1 if st.rules.no_move_fallback == "any_empty" else 0,
                     1 if st.rules.draw_rule == "open_line" else 0)


class Engine:
    """Reference engine on top of the native core."""

    def __init__(self, tt_mb: int = 128, weights: Optional[List[int]] = None,
                 options: Optional[Dict[str, int]] = None,
                 solver_options: Optional[Dict[str, int]] = None, book=None):
        if not nv.AVAILABLE:
            raise RuntimeError("native core unavailable (no C compiler?); use fourmation.pyengine")
        self.lib = nv.lib()
        self.lib.fm_init(tt_mb)
        self.weights = list(weights) if weights is not None else list(DEFAULT_WEIGHTS)
        self.options = dict(DEFAULT_OPTIONS)
        if options:
            self.options.update(options)
        # options used for searches to the end of the game (exact solving)
        self.solver_options = dict(self.options)
        self.solver_options.update(DEFAULT_SOLVER_OPTIONS)
        if solver_options:
            self.solver_options.update(solver_options)
        if isinstance(book, str):
            from .book import Book
            if book == "default":
                import os
                book = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "x_strategy_book.json")
            book = Book(book)
        self.book = book
        self._apply_config()

    # -- configuration --------------------------------------------------
    def _apply_config(self, solver: bool = False) -> None:
        arr = (ctypes.c_int * len(self.weights))(*self.weights)
        self.lib.fm_set_weights(arr, len(self.weights))
        for k, v in (self.solver_options if solver else self.options).items():
            if k == "sym_max_n":
                self.lib.fm_set_sym_max_n(int(v))
            elif k == "reply_min_depth":
                self.lib.fm_set_reply_order_min_depth(int(v))
            else:
                self.lib.fm_set_option(nv.OPTIONS[k], int(v))

    def clear(self) -> None:
        self.lib.fm_tt_clear()

    # -- low level ------------------------------------------------------
    def _enc(self, st: State, solver: bool = False):
        _rules_to_native(st)
        self._apply_config(solver)
        return nv.encode(st.board, st.last, st.to_move)

    def search(self, st: State, depth: int, alpha: int = -INF, beta: int = INF,
               time: float = 0.0, nodes: int = 0, keep: bool = True) -> nv.Result:
        """One alpha-beta search. depth >= 100 searches to the end of the game
        (exact; uses solver_options)."""
        r = nv.Result()
        self.lib.fm_search(*self._enc(st, depth >= 100), depth, alpha, beta, float(time), int(nodes),
                           1 if keep else 0, ctypes.byref(r))
        return r

    # -- play -----------------------------------------------------------
    def think(self, st: State, time: Optional[float] = None, depth: Optional[int] = None,
              nodes: Optional[int] = None, soft: float = 0.45) -> SearchInfo:
        """Iterative deepening PVS. `time` in seconds is a hard limit; a new
        iteration is not started after soft*time."""
        if st.is_terminal:
            raise ValueError("game is over")
        r = nv.Result()
        md = depth if depth is not None else 100
        t = float(time) if time else 0.0
        self.lib.fm_think(*self._enc(st), md, t, int(nodes or 0), soft if time else 0.0, ctypes.byref(r))
        return self._info(st, r)

    def _info(self, st: State, r: nv.Result) -> SearchInfo:
        mv = nv.idx(r.best_move) if r.best_move >= 0 else None
        pv = [to_coord(nv.idx(r.pv[i])) for i in range(r.pv_len)]
        if mv is None:  # should not happen: depth 1 always completes
            mv = legal_moves(st)[0]
        res = classify(r.score, bool(r.complete))
        dist = mate_distance(r.score, st.ply) if is_mate(r.score) else (
            None if res != EXACT_DRAW else None)
        its = [Iteration(r.it_depth[i], to_coord(nv.idx(r.it_move[i])) if r.it_move[i] >= 0 else "-",
                         r.it_score[i], r.it_nodes[i], r.it_time[i]) for i in range(r.iters)]
        return SearchInfo(
            move=to_coord(mv), move_index=mv, score=r.score, depth=r.depth, result=res,
            distance=dist, pv=pv, nodes=r.nodes, time=r.elapsed,
            nps=r.nodes / r.elapsed if r.elapsed > 0 else 0.0,
            tt_hit_rate=r.tt_hits / max(r.tt_probes, 1), beta_cutoffs=r.beta_cuts,
            first_move_cutoff_rate=r.first_cuts / max(r.beta_cuts, 1), iterations=its,
            rule_sensitive=r.fallback_hits > 0)

    def best_move(self, st: State, time: float = 1.0) -> int:
        return self.play(st, time=time).move_index

    def play(self, st: State, time: float = 1.0, solve_share: float = 0.5,
             resist: bool = False) -> SearchInfo:
        """Move for actual play: book -> exact solve (time-boxed) -> iterative deepening.

        Won positions: a move that keeps the proven win. Drawn: a move that keeps
        the draw. Lost or unsolved: the iterative-deepening choice (longest
        resistance when the loss is within its horizon)."""
        if st.is_terminal:
            raise ValueError("game is over")
        t0 = _time.perf_counter()
        if self.book is not None:
            e = self.book.get(st)
            if e is not None and e.get("best") and e["result"] in ("WIN", "DRAW"):
                from .rules import parse_coord
                m = parse_coord(e["best"])
                res = EXACT_WIN if e["result"] == "WIN" else EXACT_DRAW
                return SearchInfo(e["best"], m, 1 if res == EXACT_WIN else 0, 0, res, None, [e["best"]],
                                  0, 0.0, 0.0, 0.0, 0, 0.0, source="book")
        self.lib.fm_new_generation()
        r = self.search(st, 100, -1, 1, time=max(time * solve_share, 1e-3))
        solved_nodes = r.nodes
        if not r.aborted and r.score > 0 and r.pv_len > 0 and self._keeps(st, nv.idx(r.pv[0]), 1):
            info = self._info(st, r)
            info.result = EXACT_WIN
            info.depth = TOTAL_PLIES - st.ply
            info.source = "solve"
            return info
        left = max(time - (_time.perf_counter() - t0), 1e-3)
        if not r.aborted and r.score <= 0 and resist:
            # proven draw or loss: first the ordinary search (its move is the
            # fallback and tie-break), then the practical choice
            info = self.think(st, time=left * 0.3)
            info.nodes += solved_nodes
            deadline = t0 + time
            m = self._practical_choice(st, "DRAW" if r.score == 0 else "LOSS", deadline, info.move_index,
                                       r.pv[0] if r.score == 0 and r.pv_len else None)
            if m is not None and m != info.move_index:
                info.move_index, info.move = m, to_coord(m)
                info.pv = [info.move]
            info.result = EXACT_DRAW if r.score == 0 else EXACT_LOSS
            return info
        if not r.aborted and r.score == 0 and r.pv_len > 0 and self._keeps(st, nv.idx(r.pv[0]), 0):
            info = self._info(st, r)
            info.result = EXACT_DRAW
            info.depth = TOTAL_PLIES - st.ply
            info.source = "solve"
            return info
        info = self.think(st, time=left)
        info.nodes += solved_nodes
        if not r.aborted and r.score < 0 and info.result == HEURISTIC:
            info.result = EXACT_LOSS  # proven lost; the move is the best resistance found
        return info

    def _keeps(self, st: State, m: int, want: int) -> bool:
        """Defensive check that move m keeps the proven value `want` (1 win, 0 draw)
        for the side to move: re-solve the child (usually instant from the TT)."""
        c = apply_move(st, m, validate=False)
        if c.is_terminal:
            return (1 if c.winner == st.to_move else 0 if c.winner == 0 else -1) == want
        rr = self.search(c, 100, -1, 1, time=5.0)
        if rr.aborted:
            return True  # cannot check quickly; trust the search
        v = -((rr.score > 0) - (rr.score < 0))
        if v != want:
            self.inconsistencies = getattr(self, "inconsistencies", 0) + 1
            return False
        return True

    def _tactical_flag(self, st: State) -> int:
        """1: side to move wins at once; -1: every move allows an immediate win; 0 otherwise."""
        out = (ctypes.c_int * (nv.NFEAT + 1))()
        self.lib.fm_features(*nv.encode(st.board, st.last, st.to_move), out)
        return out[nv.NFEAT]

    def _practical_choice(self, st: State, target: str, deadline: float, fallback: Optional[int],
                          draw_move_sq: Optional[int]) -> Optional[int]:
        """Practical move in a proven draw or loss (all moves are equal against
        perfect play). Candidates: moves that keep `target` and, if possible,
        do not allow an immediate win. They are ranked by
          1. replies of the opponent that win/keep their result by force within
             3 plies ("easy" replies: an immediate win, or leaving us no safe move),
          2. the fraction of the opponent's replies that keep their result,
          3. the ordinary search's choice.
        Values the solver could not settle in time count in the opponent's favour.
        Returns None if no move could be examined."""
        moves = legal_moves(st)
        if fallback in moves:
            moves.remove(fallback)
            moves.insert(0, fallback)

        def left():
            return deadline - _time.perf_counter()

        def wdl(s: State) -> Optional[int]:  # value for the side to move of s
            if s.is_terminal:
                return 0 if s.winner == 0 else -1
            if left() <= 0.002:
                return None
            rr = self.search(s, 100, -1, 1, time=max(min(left(), 0.25 * left() + 0.01), 0.001))
            return None if rr.aborted else (rr.score > 0) - (rr.score < 0)

        children = []
        for m in moves:
            c = apply_move(st, m, validate=False)
            if c.is_terminal:
                continue
            children.append((m, c, self._tactical_flag(c) == 1))
        if any(not unsafe for _, _, unsafe in children):
            children = [x for x in children if not x[2]]
        best = None
        for m, c, _ in children:
            if target == "DRAW":
                v = wdl(c)
                if v is None:
                    break
                if v != 0:  # this move does not keep the draw
                    continue
            replies = legal_moves(c)
            good = easy = 0
            complete = True
            for rep in replies:
                g = apply_move(c, rep, validate=False)
                if g.is_terminal:
                    gv = 0 if g.winner == 0 else -1
                    if gv < 0:
                        easy += 1
                else:
                    gv = wdl(g)  # value for us (side to move at g)
                    if gv is not None and gv < 0 and self._tactical_flag(g) == -1:
                        easy += 1
                if gv is None:
                    complete = False
                    good += 1
                    continue
                if (target == "LOSS" and gv < 0) or (target == "DRAW" and gv <= 0):
                    good += 1
            key = (easy, good / max(len(replies), 1), 0 if m == fallback else 1)
            if complete and (best is None or key < best[0]):
                best = (key, m)
            if left() <= 0.002:
                break
        if best is None:
            if target == "LOSS":
                return fallback
            return None if draw_move_sq is None else nv.idx(draw_move_sq)
        return best[1]

    # -- exact solving ----------------------------------------------------
    def solve(self, st: State, time: Optional[float] = None, nodes: Optional[int] = None,
              distance: bool = True) -> Optional[dict]:
        """Game-theoretic value of `st` for the side to move, or None if the
        budget ran out. Returns {result, score, distance, distance_exact, nodes, time, pv}."""
        if st.is_terminal:
            raise ValueError("game is over")
        t0 = _time.perf_counter()
        self.lib.fm_new_generation()
        deadline = t0 + time if time else None
        total_nodes = 0
        sens = False

        def left():
            return max(deadline - _time.perf_counter(), 1e-3) if deadline else 0.0

        r = self.search(st, 100, -1, 1, time=left(), nodes=nodes or 0)
        total_nodes += r.nodes
        sens |= r.fallback_hits > 0
        if r.aborted:
            return None
        v = r.score
        pv = [to_coord(nv.idx(r.pv[i])) for i in range(r.pv_len)]
        out = {"result": EXACT_DRAW if v == 0 else (EXACT_WIN if v > 0 else EXACT_LOSS),
               "score": v, "distance": None, "distance_exact": v == 0, "pv": pv}
        if v != 0:
            out["distance"] = mate_distance(v, st.ply)
            if distance:
                ex = self._exact_mate(st, v, left, nodes)
                if ex is not None:
                    v2, pv2, nn, s2 = ex
                    total_nodes += nn
                    sens |= s2
                    out.update(score=v2, distance=mate_distance(v2, st.ply), distance_exact=True,
                               pv=pv2 or pv)
        out["nodes"] = total_nodes
        out["time"] = _time.perf_counter() - t0
        out["rule_sensitive"] = sens
        return out

    def _exact_mate(self, st: State, v: int, left, nodes):
        """Tighten a proven win/loss bound to the exact mate score with
        null-window tests (each test is depth-limited by mate-distance pruning)."""
        n = st.ply
        total = 0
        sens = False

        def test(target):  # is the exact value >= target ?
            nonlocal total, sens
            r = self.search(st, 100, target - 1, target, time=left(), nodes=nodes or 0)
            total += r.nodes
            sens |= r.fallback_hits > 0
            return None if r.aborted else r.score >= target

        if v > 0:
            # v = MATE - k_found is a proven lower bound. Wins can only come on our
            # moves (cube counts n+1, n+3, ...): test the fastest first.
            k_found = MATE - v
            val = v
            for k in range(n + 1, k_found, 2):
                ok = test(MATE - k)
                if ok is None:
                    return None
                if ok:
                    val = MATE - k
                    break
        else:
            # v = -(MATE - k_ub) is a proven upper bound (lost by cube count k_ub at
            # the latest). Find the longest resistance k* in n+2, n+4, ..., k_ub.
            k_ub = MATE + v
            best_k = n + 2
            for k in range(n + 4, k_ub + 1, 2):
                ok = test(-(MATE - k))
                if ok is None:
                    return None
                if not ok:
                    break
                best_k = k
            val = -(MATE - best_k)
        # exact value known: one full-window pass around it gives a PV with best defence
        r = self.search(st, 100, val - 1, val + 1, time=left(), nodes=nodes or 0)
        total += r.nodes
        pv = [to_coord(nv.idx(r.pv[i])) for i in range(r.pv_len)] if not r.aborted else []
        if not r.aborted and r.score != val:
            raise AssertionError(f"mate verification failed: {r.score} != {val}")
        return val, pv, total, sens

    # -- analysis of every candidate -------------------------------------
    def analyze(self, st: State, time: float = 5.0, solve_share: float = 0.5,
                max_depth: int = 100) -> List[dict]:
        """Evaluate every legal move. Moves are first tried with the exact
        solver (within `solve_share` of the time); the rest get a
        depth-limited value from a full-window search of the same depth for
        every unresolved move. Sorted best first for the side to move."""
        if st.is_terminal:
            raise ValueError("game is over")
        t0 = _time.perf_counter()
        self.lib.fm_new_generation()
        deadline = t0 + time
        moves = legal_moves(st)
        rows: Dict[int, dict] = {}
        children = {m: apply_move(st, m, validate=False) for m in moves}

        # immediate terminal children
        pending = []
        for m in moves:
            c = children[m]
            if c.is_terminal:
                if c.winner == 0:
                    rows[m] = self._row(m, 0, EXACT_DRAW, 1, [to_coord(m)], 0, True, depth=None)
                else:
                    rows[m] = self._row(m, MATE - c.ply, EXACT_WIN, 1, [to_coord(m)], 0, True, depth=None)
            else:
                pending.append(m)

        # phase 1: exact solve per move (shared budget, easiest first after a quick pass)
        solve_deadline = t0 + time * solve_share
        unresolved = []
        for i, m in enumerate(pending):
            budget = (solve_deadline - _time.perf_counter()) / max(len(pending) - i, 1)
            if budget <= 0.002:
                unresolved.append(m)
                continue
            sol = self.solve(children[m], time=budget)
            if sol is None:
                unresolved.append(m)
                continue
            res = {EXACT_WIN: EXACT_LOSS, EXACT_LOSS: EXACT_WIN, EXACT_DRAW: EXACT_DRAW}[sol["result"]]
            dist = None if sol["distance"] is None else sol["distance"] + 1
            rows[m] = self._row(m, -sol["score"], res, dist, [to_coord(m)] + sol["pv"], sol["nodes"],
                                True, depth=None, distance_exact=sol["distance_exact"],
                                rule_sensitive=sol["rule_sensitive"])

        # phase 2: iterative deepening, full window per unresolved move
        if unresolved:
            last_complete: Dict[int, dict] = {}
            d = 1
            while d <= max_depth and _time.perf_counter() < deadline:
                cur = {}
                aborted = False
                for m in unresolved:
                    c = children[m]
                    r = self.search(c, d - 1 if d > 1 else 0, -INF, INF,
                                    time=max(deadline - _time.perf_counter(), 1e-3))
                    if r.aborted:
                        aborted = True
                        break
                    v = -r.score
                    comp = bool(r.complete)
                    res = classify(v, comp)
                    dist = mate_distance(v, st.ply) if is_mate(v) else None
                    pv = [to_coord(m)] + [to_coord(nv.idx(r.pv[i])) for i in range(r.pv_len)]
                    cur[m] = self._row(m, v, res, dist, pv, r.nodes, res != HEURISTIC, depth=d,
                                       distance_exact=False, rule_sensitive=r.fallback_hits > 0)
                if aborted:
                    break
                last_complete = cur
                if all(row["exact"] for row in cur.values()) or d >= TOTAL_PLIES - st.ply:
                    break
                d += 1
            for m in unresolved:
                if m in last_complete:
                    rows[m] = last_complete[m]
                else:
                    rows[m] = self._row(m, 0, HEURISTIC, None, [to_coord(m)], 0, False, depth=0)
        out = sorted(rows.values(), key=lambda r: -r["score"])
        for row in out:
            row["elapsed"] = _time.perf_counter() - t0
        return out

    def grade_move(self, st: State, move, time: float = 10.0, rows: Optional[List[dict]] = None) -> dict:
        """Grade one move against the engine's analysis of every move.

        verdict (exact results only):
          BEST            same result as the best move (and, for a win, the fastest
                          win; for a loss, the longest resistance)
          SLOWER_WIN      still a proven win, but N plies slower than the fastest
          FASTER_LOSS     lost anyway, but gives up N plies of resistance
          WIN_TO_DRAW / WIN_TO_LOSS / DRAW_TO_LOSS   throws away a proven result
          UNCERTAIN       the move or the best move is only heuristically evaluated;
                          `score_loss` is the evaluation difference (not a probability)
        `rows` may be passed to reuse one analyze() call for several moves."""
        from .rules import parse_coord
        m = parse_coord(move) if isinstance(move, str) else move
        if m not in legal_moves(st):
            return {"move": to_coord(m) if isinstance(m, int) else move, "verdict": "ILLEGAL"}
        rows = rows if rows is not None else self.analyze(st, time=time)
        best = rows[0]
        row = next(r for r in rows if r["move"] == to_coord(m))
        rank = {EXACT_LOSS: 0, EXACT_DRAW: 1, EXACT_WIN: 2}
        out = {"move": row["move"], "move_result": row["result"], "move_distance": row["distance"],
               "best_move": best["move"], "best_result": best["result"], "best_distance": best["distance"],
               "best_moves": [r["move"] for r in rows if r["score"] == best["score"]],
               "score_loss": best["score"] - row["score"]}
        if row["result"] == HEURISTIC or best["result"] == HEURISTIC:
            # a proven win among the moves still dominates any heuristic value
            if best["result"] == EXACT_WIN and row["result"] == HEURISTIC:
                out["verdict"] = "UNCERTAIN"
            elif row["result"] == EXACT_LOSS and best["result"] == HEURISTIC:
                out["verdict"] = "UNCERTAIN"
            else:
                out["verdict"] = "BEST" if row["score"] >= best["score"] else "UNCERTAIN"
            return out
        a, b = rank[row["result"]], rank[best["result"]]
        if a < b:
            out["verdict"] = {(2, 1): "WIN_TO_DRAW", (2, 0): "WIN_TO_LOSS", (1, 0): "DRAW_TO_LOSS"}[(b, a)]
        elif row["result"] == EXACT_WIN and row["distance"] is not None and best["distance"] is not None \
                and row["distance"] > best["distance"]:
            out["verdict"] = "SLOWER_WIN"
            out["plies_lost"] = row["distance"] - best["distance"]
        elif row["result"] == EXACT_LOSS and row["distance"] is not None and best["distance"] is not None \
                and row["distance"] < best["distance"]:
            out["verdict"] = "FASTER_LOSS"
            out["plies_lost"] = best["distance"] - row["distance"]
        else:
            out["verdict"] = "BEST"
        return out

    @staticmethod
    def _row(m, score, result, distance, pv, nodes, exact, depth, distance_exact=True,
             rule_sensitive=False) -> dict:
        return {"move": to_coord(m), "score": int(score), "result": result, "distance": distance,
                "distance_exact": bool(distance_exact) if distance is not None else None,
                "depth": depth, "pv": pv, "nodes": int(nodes), "exact": bool(exact),
                "rule_sensitive": bool(rule_sensitive)}



"""Solved-position book (persistent, symmetry-reduced) and AND/OR prover.

A retrograde tablebase is not realistic for 4Mation (see bench/README.md: the
number of positions with k empty cells explodes long before the endgame gets
trivial), but the forward solver is fast after ~10-12 plies. The book stores
exact results of positions that were expensive to solve (openings), keyed by
the canonical form under the 8 board symmetries, so they never have to be
solved twice.

    python -m fourmation.book prove --expand 2 --book book.json   # prove the initial position
    python -m fourmation.book show  --book book.json

Values in the book are for the side to move: WIN / DRAW / LOSS, and are exact.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import time
from typing import Dict, List, Optional, Tuple

from .rules import State, TRANSFORMS, apply_move, legal_moves, new_game, parse_coord, to_coord, transform_state

INV = [None] * 8
for _k in range(8):
    _p = TRANSFORMS[_k]
    _inv = [0] * len(_p)
    for _i, _j in enumerate(_p):
        _inv[_j] = _i
    INV[_k] = tuple(_inv)


def canonical(st: State) -> Tuple[str, int]:
    """(canonical compact string, k) with transform_state(st, k) being canonical."""
    best = None
    for k in range(8):
        c = transform_state(st, k).to_compact()
        if best is None or c < best[0]:
            best = (c, k)
    return best


class Book:
    def __init__(self, path: Optional[str] = None):
        self.path = path
        self.data: Dict[str, dict] = {}
        if path and os.path.exists(path):
            with open(path) as f:
                self.data = json.load(f)

    def save(self) -> None:
        if not self.path:
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=0, sort_keys=True)
        os.replace(tmp, self.path)

    def get(self, st: State) -> Optional[dict]:
        key, k = canonical(st)
        e = self.data.get(key)
        if e is None:
            return None
        out = dict(e)
        if e.get("best") is not None:  # map the move back to st's orientation
            out["best"] = to_coord(INV[k][parse_coord(e["best"])])
        return out

    def put(self, st: State, result: str, best: Optional[str] = None, **extra) -> None:
        key, k = canonical(st)
        e = {"result": result}
        if best is not None:
            e["best"] = to_coord(TRANSFORMS[k][parse_coord(best)])
        e.update(extra)
        old = self.data.get(key)
        if old is None or (old.get("best") is None and best is not None):
            self.data[key] = e

    def __len__(self):
        return len(self.data)


# ---- solving leaves in worker processes ------------------------------------

_ENG = None


def _worker_init(tt_mb):
    global _ENG
    from .engine import Engine
    _ENG = Engine(tt_mb=tt_mb, options=SOLVER_OPTIONS)


def _solve_leaf(compact: str) -> Tuple[str, Optional[str], Optional[str], int, float]:
    st = State.from_compact(compact)
    t0 = time.time()
    r = _ENG.search(st, 100, -1, 1)
    res = "WIN" if r.score > 0 else ("LOSS" if r.score < 0 else "DRAW")
    from . import native as nv
    best = to_coord(nv.idx(r.pv[0])) if r.pv_len > 0 and res != "LOSS" else None
    return compact, res, best, r.nodes, time.time() - t0


SOLVER_OPTIONS = {"reply_order": 1, "killer": 0, "history": 0, "counter": 0}


def children(st: State) -> List[Tuple[int, State]]:
    """Legal moves with symmetric duplicates removed."""
    seen = set()
    out = []
    for m in legal_moves(st):
        c = apply_move(st, m, validate=False)
        key = canonical(c)[0]
        if key in seen:
            continue
        seen.add(key)
        out.append((m, c))
    return out


def prove(root: State, expand: int, book: Book, procs: int = 2, tt_mb: int = 1024,
          log=print) -> str:
    """Exact value of `root` by expanding `expand` plies in Python (with
    symmetry reduction) and solving the frontier with the native solver in
    parallel. Every solved node is stored in the book."""
    # collect frontier positions not already in the book
    frontier: Dict[str, State] = {}

    def collect(st: State, d: int):
        if st.is_terminal or book.get(st) is not None:
            return
        if d == 0:
            frontier.setdefault(canonical(st)[0], st)
            return
        for _, c in children(st):
            collect(c, d - 1)

    collect(root, expand)
    log(f"frontier: {len(frontier)} positions to solve at depth {expand}")
    if frontier:
        ctx = mp.get_context("fork")
        with ctx.Pool(procs, initializer=_worker_init, initargs=(tt_mb,)) as pool:
            done = 0
            t0 = time.time()
            for compact, res, best, nodes, secs in pool.imap_unordered(_solve_leaf, list(frontier)):
                st = State.from_compact(compact)
                book.put(st, res, best, nodes=nodes, seconds=round(secs, 2))
                done += 1
                log(f"[{done}/{len(frontier)}] {compact} -> {res} {best or ''} "
                    f"{nodes / 1e6:.1f}M nodes {secs:.1f}s (total {time.time() - t0:.0f}s)")
                book.save()

    # back up through the expanded plies (negamax over WIN/DRAW/LOSS)
    rank = {"LOSS": 0, "DRAW": 1, "WIN": 2}
    flip = {"WIN": "LOSS", "LOSS": "WIN", "DRAW": "DRAW"}

    def value(st: State, d: int) -> str:
        if st.is_terminal:
            # the side to move lost if the previous mover won
            return "DRAW" if st.winner == 0 else "LOSS"
        e = book.get(st)
        if e is not None:
            return e["result"]
        best, bm = None, None
        for m, c in children(st):
            v = flip[value(c, d - 1)]
            if best is None or rank[v] > rank[best]:
                best, bm = v, to_coord(m)
                if best == "WIN":
                    break
        book.put(st, best, bm if best != "LOSS" else None, derived=True)
        return best

    v = value(root, expand)
    book.save()
    return v


def build_strategy(book: Book, root: State, max_ply: int, tt_mb: int = 2048,
                   first_move: Optional[str] = None, log=print, save_every: int = 20) -> dict:
    """Walk the winning side's proof tree from `root` (side to move must be
    winning) down to `max_ply` cubes: at the winner's nodes store one proven
    winning move, at the loser's nodes expand every reply (symmetry-reduced).
    The result is a book that lets the winner play perfectly without search
    until the solver is fast enough (see Engine.play)."""
    from . import native as nv
    from .engine import Engine
    eng = Engine(tt_mb=tt_mb)
    winner = root.to_move
    stats = {"winner_nodes": 0, "loser_nodes": 0, "solved": 0, "solve_seconds": 0.0, "not_win": 0}
    seen = set()
    stack = [root]
    t0 = time.time()
    while stack:
        st = stack.pop()
        if st.is_terminal or st.ply > max_ply:
            continue
        key = canonical(st)[0]
        if key in seen:
            continue
        seen.add(key)
        if st.to_move == winner:
            stats["winner_nodes"] += 1
            e = book.get(st)
            if (e is None or not e.get("best")) and st is root and first_move:
                book.put(st, "WIN", first_move, given=True)
                e = book.get(st)
            if e is None or not e.get("best"):
                ts = time.time()
                r = eng.search(st, 100, -1, 1)
                res = "WIN" if r.score > 0 else ("LOSS" if r.score < 0 else "DRAW")
                best = to_coord(nv.idx(r.pv[0])) if r.pv_len and res != "LOSS" else None
                dt = time.time() - ts
                stats["solved"] += 1
                stats["solve_seconds"] += dt
                book.put(st, res, best, nodes=r.nodes, seconds=round(dt, 2))
                e = book.get(st)
                if stats["solved"] % save_every == 0:
                    book.save()
                    log(f"solved {stats['solved']}  winner nodes {stats['winner_nodes']}  "
                        f"loser nodes {stats['loser_nodes']}  book {len(book)}  {time.time() - t0:.0f}s")
            if e["result"] != "WIN":
                stats["not_win"] += 1
                continue
            stack.append(apply_move(st, parse_coord(e["best"])))
        else:
            stats["loser_nodes"] += 1
            if book.get(st) is None:
                book.put(st, "LOSS", None, derived=True)
            for _, c in children(st):
                stack.append(c)
    book.save()
    stats["seconds"] = time.time() - t0
    return stats


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("strategy")
    b.add_argument("--max-ply", type=int, default=8)
    b.add_argument("--first", default="d4", help="proven first move (skips the root solve)")
    b.add_argument("--book", default="book.json")
    b.add_argument("--tt", type=int, default=2048)
    p = sub.add_parser("prove")
    p.add_argument("--position", default="", help="compact position (default: initial)")
    p.add_argument("--moves", default="", help="moves from the initial position, e.g. d4,d5")
    p.add_argument("--expand", type=int, default=2)
    p.add_argument("--book", default="book.json")
    p.add_argument("--procs", type=int, default=2)
    p.add_argument("--tt", type=int, default=1024)
    s = sub.add_parser("show")
    s.add_argument("--book", default="book.json")
    a = ap.parse_args()
    if a.cmd == "strategy":
        book = Book(a.book)
        stats = build_strategy(book, new_game(), a.max_ply, a.tt, first_move=a.first or None)
        print("STRATEGY", json.dumps(stats), "book", len(book))
    elif a.cmd == "prove":
        st = State.from_compact(a.position) if a.position else new_game()
        for mv in filter(None, a.moves.split(",")):
            st = apply_move(st, parse_coord(mv))
        book = Book(a.book)
        t0 = time.time()
        v = prove(st, a.expand, book, a.procs, a.tt)
        print(f"RESULT {st.to_compact()} : {v} for side to move  ({time.time() - t0:.0f}s, book {len(book)})")
    elif a.cmd == "show":
        book = Book(a.book)
        for k, e in sorted(book.data.items(), key=lambda kv: kv[0].count(".")):
            print(k, e)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()

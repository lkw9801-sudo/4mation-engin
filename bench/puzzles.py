"""Exact-labelled tactical test set ("puzzles") and accuracy of engines on it.

A puzzle is a position where every legal move has an exact value (solver) and
the best result (WIN, else DRAW) is kept by at most `max_frac` of the moves,
so a random or careless move is wrong. The label is the set of correct moves.

    python -m bench.puzzles gen  --games 200 --out bench/puzzles.json
    python -m bench.puzzles eval --players old:ab8,greedy,new:t=0.1 --file bench/puzzles.json

The same file can serve as an LLM benchmark: show the position, ask for a
move, score it against `correct` (and `values` for partial credit).
"""
from __future__ import annotations

import argparse
import json
import random
import time

from fourmation.engine import Engine
from fourmation.rules import State, apply_move, legal_moves, new_game, parse_coord, to_coord

from .match import make_player

RANK = {"EXACT_LOSS": 0, "EXACT_DRAW": 1, "EXACT_WIN": 2}


def exact_values(eng: Engine, st: State, solve_time: float):
    """{move: (result, distance)} for the side to move, or None if unsolved."""
    out = {}
    for m in legal_moves(st):
        c = apply_move(st, m, validate=False)
        if c.is_terminal:
            out[to_coord(m)] = ("EXACT_WIN", 1) if c.winner else ("EXACT_DRAW", None)
            continue
        sol = eng.solve(c, time=solve_time)
        if sol is None:
            return None
        flip = {"EXACT_WIN": "EXACT_LOSS", "EXACT_LOSS": "EXACT_WIN", "EXACT_DRAW": "EXACT_DRAW"}
        out[to_coord(m)] = (flip[sol["result"]], None if sol["distance"] is None else sol["distance"] + 1)
    return out


def gen(a):
    rng = random.Random(a.seed)
    eng = Engine(tt_mb=512)
    puzzles = []
    seen = set()
    t0 = time.time()
    for g in range(a.games):
        st = new_game()
        for _ in range(rng.randint(2, 5)):
            st = apply_move(st, rng.choice(legal_moves(st)))
        while not st.is_terminal:
            if a.min_ply <= st.ply <= a.max_ply and rng.random() < a.sample and st.to_compact() not in seen:
                seen.add(st.to_compact())
                vals = exact_values(eng, st, a.solve_time)
                if vals:
                    best = max(RANK[v[0]] for v in vals.values())
                    correct = [m for m, v in vals.items() if RANK[v[0]] == best]
                    if best > 0 and len(correct) <= a.max_frac * len(vals) and len(vals) >= 2:
                        cat = "win" if best == 2 else "hold_draw"
                        puzzles.append({"position": st.to_compact(), "ply": st.ply, "category": cat,
                                        "correct": sorted(correct),
                                        "values": {m: v[0] for m, v in vals.items()},
                                        "distances": {m: v[1] for m, v in vals.items()}})
            if st.ply > a.max_ply:
                break
            m = rng.choice(legal_moves(st)) if rng.random() < 0.25 else eng.think(st, depth=8).move_index
            st = apply_move(st, m)
        if (g + 1) % 20 == 0:
            print(f"games {g + 1} puzzles {len(puzzles)} {time.time() - t0:.0f}s", flush=True)
    json.dump(puzzles, open(a.out, "w"), indent=0)
    print("puzzles", len(puzzles))


def evaluate(a):
    puzzles = json.load(open(a.file))
    for spec in a.players.split(";"):
        p = make_player(spec, 0)
        ok = 0
        by = {}
        t = 0.0
        for pz in puzzles:
            st = State.from_compact(pz["position"])
            t0 = time.perf_counter()
            m = to_coord(p.select(st))
            t += time.perf_counter() - t0
            good = m in pz["correct"]
            ok += good
            key = (pz["category"], "ply<16" if pz["ply"] < 16 else ("ply<28" if pz["ply"] < 28 else "ply>=28"))
            c = by.setdefault(key, [0, 0])
            c[0] += good
            c[1] += 1
        detail = ", ".join(f"{k[0]}/{k[1]} {v[0]}/{v[1]}" for k, v in sorted(by.items()))
        print(f"| {spec} | {ok}/{len(puzzles)} ({100 * ok / len(puzzles):.1f}%) | {t / len(puzzles):.3f} | {detail} |",
              flush=True)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    g = sub.add_parser("gen")
    g.add_argument("--games", type=int, default=200)
    g.add_argument("--min-ply", type=int, default=8)
    g.add_argument("--max-ply", type=int, default=48)
    g.add_argument("--sample", type=float, default=0.25)
    g.add_argument("--max-frac", type=float, default=0.5)
    g.add_argument("--solve-time", type=float, default=5.0)
    g.add_argument("--seed", type=int, default=11)
    g.add_argument("--out", default="bench/puzzles.json")
    e = sub.add_parser("eval")
    e.add_argument("--players", default="old:ab4;old:ab8;greedy;new:t=0.1")
    e.add_argument("--file", default="bench/puzzles.json")
    a = ap.parse_args()
    if a.cmd == "gen":
        gen(a)
    elif a.cmd == "eval":
        print("| player | correct | s/move | by category |\n|---|---|---|---|")
        evaluate(a)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()

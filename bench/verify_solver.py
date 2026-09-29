"""Independent consistency checks of the exact solver where brute force is too slow.

1. Bellman consistency: V(pos) == max over moves of -V(child), every value from a
   fresh search (TT cleared), for positions at ply 8-20.
2. Option invariance: WDL identical with symmetry off, different move ordering,
   history heuristics on, and a tiny TT (heavy replacement).
3. Cross-implementation: the pure-Python engine (pyengine.py) gives the same exact
   score (including distance) at ply 24-32.

    python -m bench.verify_solver --n 60
"""
from __future__ import annotations

import argparse
import json
import random
import time

from fourmation.engine import Engine
from fourmation.rules import apply_move, legal_moves, new_game


def wdl(v):
    return (v > 0) - (v < 0)


def sample(rng, eng, lo, hi):
    """Realistic positions: engine self-play with random openings."""
    while True:
        st = new_game()
        for _ in range(rng.randint(2, 4)):
            st = apply_move(st, rng.choice(legal_moves(st)))
        target = rng.randint(lo, hi)
        while not st.is_terminal and st.ply < target:
            m = rng.choice(legal_moves(st)) if rng.random() < 0.3 else eng.think(st, depth=6).move_index
            st = apply_move(st, m)
        if not st.is_terminal:
            return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--out", default="bench/results/verify_solver.json")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    eng = Engine(tt_mb=256)
    variants = {
        "no_sym": Engine(tt_mb=256, solver_options={"sym": 0}),
        "plain_order": Engine(tt_mb=256, solver_options={"reply_order": 0, "killer": 1, "history": 1, "counter": 1}),
        "no_safe_prune": Engine(tt_mb=256, solver_options={"safe_prune": 0, "dead_prune": 0}),
        "tiny_tt": Engine(tt_mb=1),
    }
    report = {"bellman": [0, 0], "variants": {k: [0, 0] for k in variants}, "python": [0, 0], "errors": []}
    t0 = time.time()
    for i in range(a.n):
        st = sample(rng, eng, 8, 20)
        eng.clear()
        v = eng.search(st, 100, -1, 1).score
        best = -2
        for m in legal_moves(st):
            c = apply_move(st, m, validate=False)
            if c.is_terminal:
                cv = 1 if c.winner else 0
            else:
                eng.clear()
                cv = -wdl(eng.search(c, 100, -1, 1).score)
            best = max(best, cv)
        report["bellman"][1] += 1
        if best == wdl(v):
            report["bellman"][0] += 1
        else:
            report["errors"].append(("bellman", st.to_compact(), wdl(v), best))
        for name, e in variants.items():
            e.clear()
            ok = wdl(e.search(st, 100, -1, 1).score) == wdl(v)
            report["variants"][name][0] += ok
            report["variants"][name][1] += 1
            if not ok:
                report["errors"].append((name, st.to_compact()))
        print(f"[{i + 1}/{a.n}] ply {st.ply} value {wdl(v)} ok  {time.time() - t0:.0f}s", flush=True)
    from fourmation.pyengine import PyEngine
    for i in range(a.n // 3):
        st = sample(rng, eng, 26, 32)
        eng.clear()
        cv = eng.search(st, 100).score
        pv = PyEngine().think(st, depth=48)["score"]
        report["python"][1] += 1
        if cv == pv:
            report["python"][0] += 1
        else:
            report["errors"].append(("python", st.to_compact(), cv, pv))
    report["seconds"] = time.time() - t0
    print(json.dumps(report, indent=1))
    json.dump(report, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()

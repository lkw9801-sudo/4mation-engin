"""Heuristic-search ablation: nodes/time to a fixed depth and depth reached in a
fixed time, over a set of opening/middlegame positions.

    python -m bench.bench_search --depth 14 --time 0.3
"""
from __future__ import annotations

import argparse
import json

from fourmation.engine import Engine
from fourmation.rules import State

from .positions import ORDER, POSITIONS

CONFIGS = {
    "default": {},
    "no_killer_hist_counter": {"killer": 0, "history": 0, "counter": 0},
    "reply_order": {"reply_order": 1},
    "reply_order_no_khc": {"reply_order": 1, "killer": 0, "history": 0, "counter": 0},
    "no_threat_order": {"threat_order": 0},
    "no_pvs": {"pvs": 0},
    "no_aspiration": {"aspiration": 0},
    "no_tt": {"tt": 0},
    "no_sym": {"sym": 0},
    "no_safe_prune": {"safe_prune": 0},
    "no_dead_prune": {"dead_prune": 0},
    "etc": {"etc": 1},
    "legacy_eval": "legacy",
}


def positions():
    """Opening positions (ply 0-6) where a depth-18 search stays heuristic."""
    import random
    from fourmation.rules import apply_move, legal_moves, new_game
    out = [State.from_compact(POSITIONS["initial"]), State.from_compact(POSITIONS["early"])]
    rng = random.Random(12)
    while len(out) < 12:
        st = new_game()
        for _ in range(rng.choice([2, 3, 4, 5, 6])):
            st = apply_move(st, rng.choice(legal_moves(st)))
        if not st.is_terminal:
            out.append(st)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=18)
    ap.add_argument("--time", type=float, default=0.3)
    ap.add_argument("--configs", default=",".join(CONFIGS))
    a = ap.parse_args()
    pos = positions()
    print(f"{len(pos)} positions")
    print("| config | nodes to d%d | time to d%d (s) | avg depth in %.1fs |" % (a.depth, a.depth, a.time))
    print("|---|---|---|---|")
    for name in a.configs.split(","):
        if CONFIGS[name] == "legacy":
            from fourmation.engine_defaults import LEGACY_WEIGHTS
            eng = Engine(tt_mb=128, weights=LEGACY_WEIGHTS)
        else:
            eng = Engine(tt_mb=128, options=CONFIGS[name])
        nodes = t = 0
        for st in pos:
            eng.clear()
            i = eng.think(st, depth=a.depth)
            nodes += i.nodes
            t += i.time
        dsum = 0
        for st in pos:
            eng.clear()
            i = eng.think(st, time=a.time, soft=1.0)
            dsum += i.depth
        print(f"| {name} | {nodes / 1e6:.1f}M | {t:.2f} | {dsum / len(pos):.2f} |", flush=True)


if __name__ == "__main__":
    main()

"""New engine on the benchmark positions, same metrics as bench_legacy.py.

    python -m bench.bench_new --depths 2,4,...,30 --out bench/results/new_engine.jsonl

Each depth is a fresh iterative-deepening search (TT cleared) to that depth.
The search stops early when the result is proven (exact), as in real use.
"""
from __future__ import annotations

import argparse
import json
import os

from fourmation.engine import Engine
from fourmation.rules import State

from .positions import ORDER, POSITIONS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depths", default=",".join(str(d) for d in range(2, 31, 2)))
    ap.add_argument("--time-limit", type=float, default=300.0)
    ap.add_argument("--positions", default=",".join(ORDER))
    ap.add_argument("--out", default="bench/results/new_engine.jsonl")
    ap.add_argument("--tt", type=int, default=512)
    a = ap.parse_args()
    eng = Engine(tt_mb=a.tt)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        for name in a.positions.split(","):
            st = State.from_compact(POSITIONS[name])
            for d in map(int, a.depths.split(",")):
                eng.clear()
                i = eng.think(st, depth=d, time=a.time_limit)
                r = {"position": name, "depth": d, "reached_depth": i.depth, "best": i.move, "score": i.score,
                     "result": i.result, "distance": i.distance, "elapsed": i.time, "nodes": i.nodes,
                     "nps": i.nps, "tt_hit_rate": i.tt_hit_rate, "beta_cutoffs": i.beta_cutoffs,
                     "first_move_cutoff_rate": i.first_move_cutoff_rate, "pv": i.pv,
                     "timeout": i.depth < min(d, 48 - st.ply) and i.result == "HEURISTIC"}
                f.write(json.dumps(r) + "\n")
                f.flush()
                print(f"{name} d{d}: {i.move} {i.score} {i.result} {i.time:.3f}s {i.nodes} nodes", flush=True)
                if i.result != "HEURISTIC" or r["timeout"]:
                    break


if __name__ == "__main__":
    main()

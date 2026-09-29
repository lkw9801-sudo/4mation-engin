"""Exact (WDL) solve cost on the benchmark sets, per ply.

    python -m bench.solvebench --set bench/solve_set_b.json --ply 12 --limit 60
    python -m bench.solvebench --set bench/solve_set_b.json --ply 12 --options '{"reply_order":0}'

Solver options given with --options override the engine's solver defaults
(fourmation/engine_defaults.py DEFAULT_SOLVER_OPTIONS). Prints totals, the
W/D/L string of the positions (side to move) and the time distribution.
"""
from __future__ import annotations

import argparse
import json
import statistics

from fourmation.engine import Engine
from fourmation.rules import State


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="bench/solve_set_b.json")
    ap.add_argument("--ply", default="12")
    ap.add_argument("--limit", type=float, default=60.0, help="seconds per position")
    ap.add_argument("--options", default="{}", help="JSON solver options")
    ap.add_argument("--n", type=int, default=0)
    ap.add_argument("--tt", type=int, default=512)
    a = ap.parse_args()
    opts = json.loads(a.options)
    eng = Engine(tt_mb=a.tt, solver_options=opts)
    positions = json.load(open(a.set))[a.ply]
    if a.n:
        positions = positions[:a.n]
    nodes = 0
    times, res = [], []
    for c in positions:
        st = State.from_compact(c)
        if st.is_terminal:
            continue
        eng.clear()
        r = eng.search(st, 100, -1, 1, time=a.limit)
        nodes += r.nodes
        times.append(r.elapsed)
        res.append("?" if r.aborted else ("W" if r.score > 0 else ("L" if r.score < 0 else "D")))
    times.sort()
    print(f"ply {a.ply} {opts} solved {sum(x != '?' for x in res)}/{len(res)} nodes {nodes / 1e6:.3g}M "
          f"time {sum(times):.1f}s median {statistics.median(times):.3f}s max {times[-1]:.2f}s "
          f"nps {nodes / max(sum(times), 1e-9) / 1e6:.2g}M  {''.join(res)}")


if __name__ == "__main__":
    main()

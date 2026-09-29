"""Baseline: the original fixed-depth alpha-beta on the benchmark positions.

    python -m bench.bench_legacy --depths 2,4,6,8,10,12 --time-limit 300 --out bench/results/legacy.jsonl
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os

from fourmation.rules import State

from .legacy_instrumented import run
from .positions import ORDER, POSITIONS


def bench_position(args):
    name, depths, limit = args
    st = State.from_compact(POSITIONS[name])
    rows = []
    for d in depths:
        r = run(st, d, limit)
        r["position"] = name
        rows.append(r)
        print(json.dumps(r), flush=True)
        if r["timeout"]:
            break
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depths", default="2,4,6,8,10,12")
    ap.add_argument("--time-limit", type=float, default=300.0)
    ap.add_argument("--positions", default=",".join(ORDER))
    ap.add_argument("--out", default="bench/results/legacy.jsonl")
    ap.add_argument("--procs", type=int, default=2)
    a = ap.parse_args()
    depths = [int(x) for x in a.depths.split(",")]
    names = a.positions.split(",")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with mp.Pool(a.procs) as pool:
        allrows = pool.map(bench_position, [(n, depths, a.time_limit) for n in names])
    with open(a.out, "w") as f:
        for rows in allrows:
            for r in rows:
                f.write(json.dumps(r) + "\n")


if __name__ == "__main__":
    main()

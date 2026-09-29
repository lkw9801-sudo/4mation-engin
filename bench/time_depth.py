"""What does the engine reach with 1 s / 5 s / 30 s of thinking?

For each benchmark position: iterative deepening only (think) and the play
pipeline (exact solve first). Reports depth, nodes, result type, move.

    python -m bench.time_depth --times 1,5,30
"""
from __future__ import annotations

import argparse
import json

from fourmation.engine import Engine
from fourmation.rules import State

from .positions import ORDER, POSITIONS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--times", default="1,5,30")
    ap.add_argument("--positions", default=",".join(ORDER))
    ap.add_argument("--tt", type=int, default=1024)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    eng = Engine(tt_mb=a.tt)
    rows = []
    print("| position | ply | time | think: move / score / depth / nodes / result | solve (exact) within time |")
    print("|---|---|---|---|---|")
    for name in a.positions.split(","):
        st = State.from_compact(POSITIONS[name])
        for t in map(float, a.times.split(",")):
            eng.clear()
            i = eng.think(st, time=t, soft=1.0)
            eng.clear()
            s = eng.solve(st, time=t, distance=True)
            sol = "unsolved" if s is None else f"{s['result']} d={s['distance']} ({s['time']:.2f}s)"
            print(f"| {name} | {st.ply} | {t:g}s | {i.move} / {i.score} / d{i.depth} / {i.nodes / 1e6:.1f}M / "
                  f"{i.result} | {sol} |", flush=True)
            rows.append({"position": name, "time": t, "think": i.as_dict(), "solve": s})
    if a.out:
        json.dump(rows, open(a.out, "w"), indent=1)


if __name__ == "__main__":
    main()

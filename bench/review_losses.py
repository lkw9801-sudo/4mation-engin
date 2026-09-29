"""Classify every non-won game of the new engine with the exact solver.

For each move of the new engine: value before the move vs value after it.
  blunder     = before is WIN/DRAW, after is worse          (engine's fault)
  lost_start  = the first position it faced was already a proven LOSS
  unresolved  = the solver could not settle the positions in the budget
Positions whose value is unknown are re-solved with a larger budget if the
value after the move is a loss (that is where a blunder could hide).

    python -m bench.review_losses --games bench/results/match_losses.jsonl --t1 20 --t2 900
"""
from __future__ import annotations

import argparse
import json
import time

from fourmation.engine import Engine
from fourmation.rules import apply_move, new_game, to_coord

FLIP = {"EXACT_WIN": "EXACT_LOSS", "EXACT_LOSS": "EXACT_WIN", "EXACT_DRAW": "EXACT_DRAW"}
RANK = {"EXACT_LOSS": 0, "EXACT_DRAW": 1, "EXACT_WIN": 2}


def value(eng, st, t, cache):
    key = st.to_compact()
    if key in cache and (cache[key] is not None or cache.get(key + "#t", 0) >= t):
        return cache[key]
    if st.is_terminal:
        v = "EXACT_DRAW" if st.winner == 0 else "EXACT_LOSS"  # side to move lost
    else:
        s = eng.solve(st, time=t, distance=False)
        v = None if s is None else s["result"]
    cache[key] = v
    cache[key + "#t"] = t
    return v


def review_game(eng, g, t1, t2, cache):
    st = new_game()
    rows = []
    for i, m in enumerate(g["moves"]):
        mine = (st.to_move == 1) == g["first"]
        if mine and i >= g.get("start", 0):
            before = value(eng, st, t1, cache)
            after_st = apply_move(st, m)
            a = value(eng, after_st, t1, cache)
            after = None if a is None else FLIP[a]
            if before is None and after == "EXACT_LOSS":
                before = value(eng, st, t2, cache)
            rows.append({"ply": i, "move": to_coord(m), "before": before, "after": after})
        st = apply_move(st, m)
    blunders = [r for r in rows if r["before"] and r["after"] and RANK[r["after"]] < RANK[r["before"]]]
    first_known = next((r["before"] for r in rows if r["before"]), None)
    if blunders:
        cls = "blunder"
    elif rows and rows[0]["before"] == "EXACT_LOSS":
        cls = "lost_start"
    elif first_known == "EXACT_LOSS" and all(r["after"] in (None, "EXACT_LOSS") for r in rows):
        # unknown at the start, but no move of ours was shown to throw anything away
        cls = "unresolved_start"
    else:
        cls = "unresolved"
    return {"id": g["id"], "winner": g.get("winner"), "class": cls, "blunders": blunders, "moves": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", default="bench/results/match_losses.jsonl")
    ap.add_argument("--t1", type=float, default=20.0)
    ap.add_argument("--t2", type=float, default=900.0)
    ap.add_argument("--out", default="bench/results/loss_review.jsonl")
    a = ap.parse_args()
    eng = Engine(tt_mb=1024)
    cache = {}
    summary = {}
    t0 = time.time()
    with open(a.out, "w") as f:
        for line in open(a.games):
            g = json.loads(line)
            if g["id"].split(" vs ")[0].startswith("new:") is False:
                continue
            r = review_game(eng, g, a.t1, a.t2, cache)
            f.write(json.dumps(r) + "\n")
            f.flush()
            summary.setdefault(g["id"].split(" #")[0], {}).setdefault(r["class"], 0)
            summary[g["id"].split(" #")[0]][r["class"]] += 1
            print(f"{r['id']}: {r['class']} {[(b['ply'], b['move'], b['before'], b['after']) for b in r['blunders']]}"
                  f"  ({time.time() - t0:.0f}s)", flush=True)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()

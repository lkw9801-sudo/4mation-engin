"""Solve one position (given as moves from the start) exactly, WDL only.
    python -m bench.solve_line d4,d5 --tt 2048 --time 3600"""
import argparse, json, time
from fourmation.engine import Engine
from fourmation.rules import new_game, apply_move, parse_coord, to_coord
from fourmation import native as nv

ap = argparse.ArgumentParser()
ap.add_argument("moves")
ap.add_argument("--tt", type=int, default=2048)
ap.add_argument("--time", type=float, default=0)
ap.add_argument("--window", default="-1,1")
ap.add_argument("--fallback", default="any_empty", choices=["any_empty", "draw"],
                help="rule for the (rulebook-undefined) double dead end")
a = ap.parse_args()
from fourmation.rules import RuleConfig
st = new_game(RuleConfig(no_move_fallback=a.fallback))
for m in filter(None, a.moves.split(",")):
    st = apply_move(st, parse_coord(m))
eng = Engine(tt_mb=a.tt)
lo, hi = map(int, a.window.split(","))
t0 = time.time()
r = eng.search(st, 100, lo, hi, time=a.time)
out = {"moves": a.moves, "position": st.to_compact(), "side_to_move": "X" if st.to_move == 1 else "O",
       "aborted": bool(r.aborted), "score": r.score, "window": [lo, hi],
       "result": None if r.aborted else ("WIN" if r.score > 0 else ("LOSS" if r.score < 0 else "DRAW")),
       "best": to_coord(nv.idx(r.pv[0])) if r.pv_len else None,
       "pv": [to_coord(nv.idx(r.pv[i])) for i in range(r.pv_len)],
       "nodes": r.nodes, "seconds": round(time.time() - t0, 1), "tt_mb": a.tt,
       "fallback_hits": r.fallback_hits, "fallback_rule": a.fallback}
print(json.dumps(out), flush=True)

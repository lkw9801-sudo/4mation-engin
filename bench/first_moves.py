"""Exact value of every first move (symmetry classes).
Fast path: "does X force a win by cube k?" tests (mate-distance bounded);
otherwise a full WDL solve.  Results appended to solve_runs/first_moves_all.jsonl."""
import json, sys, time
from fourmation.engine import Engine, MATE
from fourmation.rules import new_game, apply_move, parse_coord

moves = sys.argv[1].split(",")
limit = float(sys.argv[2]) if len(sys.argv) > 2 else 3600
eng = Engine(tt_mb=2048)
for mv in moves:
    st = apply_move(new_game(), parse_coord(mv))  # O to move
    t0 = time.time()
    res = None
    tests = []
    for k in (31, 35, 39):
        # O's value <= -(MATE-k)  <=>  X wins by cube k
        target = -(MATE - k)
        r = eng.search(st, 100, target, target + 1, time=max(limit - (time.time() - t0), 1))
        tests.append({"k": k, "proved": (not r.aborted) and r.score <= target, "nodes": r.nodes,
                      "seconds": round(r.elapsed, 1), "fallback_hits": r.fallback_hits, "aborted": bool(r.aborted)})
        if r.aborted:
            break
        if r.score <= target:
            res = "X_WINS"
            break
    wdl = None
    if res is None and time.time() - t0 < limit:
        r = eng.search(st, 100, -1, 1, time=max(limit - (time.time() - t0), 1))
        if not r.aborted:
            res = "X_WINS" if r.score < 0 else ("DRAW" if r.score == 0 else "O_WINS")
        wdl = {"score": r.score, "nodes": r.nodes, "seconds": round(r.elapsed, 1), "aborted": bool(r.aborted),
               "fallback_hits": r.fallback_hits}
    out = {"first_move": mv, "result": res, "tests": tests, "wdl": wdl, "seconds": round(time.time() - t0, 1)}
    print(json.dumps(out), flush=True)
    with open("solve_runs/first_moves_all.jsonl", "a") as f:
        f.write(json.dumps(out) + "\n")

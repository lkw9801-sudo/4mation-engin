"""Exact shortest forced win from the initial position, by null-window tests
"can X force a win by cube k?" (mate-distance pruning makes each test depth-limited)."""
import json, time
from fourmation.engine import Engine, MATE
from fourmation.rules import new_game
eng = Engine(tt_mb=2048)
st = new_game()
out = []
for k in (27, 29):
    t0 = time.time()
    r = eng.search(st, 100, MATE - k - 1, MATE - k)
    ok = r.score >= MATE - k
    out.append({"win_by_cube": k, "proved": ok, "score": r.score, "nodes": r.nodes, "seconds": round(time.time() - t0, 1),
                "aborted": bool(r.aborted), "fallback_hits": r.fallback_hits})
    print(json.dumps(out[-1]), flush=True)
json.dump(out, open("bench/results/initial_distance.json", "w"), indent=1)

"""Verify every winner entry of a strategy book with an independent solver:
the stored move must leave the loser in a proven LOSS.
    python -m bench.verify_book fourmation/data/x_strategy_book.json"""
import json, sys, time
from fourmation.book import Book
from fourmation.engine import Engine
from fourmation.rules import State, apply_move, parse_coord

book = Book(sys.argv[1])
eng = Engine(tt_mb=1024)
bad, ok, t0 = [], 0, time.time()
entries = sorted(((k, e) for k, e in book.data.items() if e.get("best") and e["result"] == "WIN"),
                 key=lambda ke: -State.from_compact(ke[0]).ply)  # deep first: warms the TT for the early ones
for i, (k, e) in enumerate(entries):
    st = State.from_compact(k)
    c = apply_move(st, parse_coord(e["best"]))
    if c.is_terminal:
        good = c.winner == st.to_move
    else:
        s = eng.solve(c, distance=False)
        good = s["result"] == "EXACT_LOSS"
    if good:
        ok += 1
    else:
        bad.append((k, e["best"]))
    if (i + 1) % 1000 == 0:
        print(f"{i + 1}/{len(entries)} ok {ok} bad {len(bad)} {time.time() - t0:.0f}s", flush=True)
print(json.dumps({"entries": len(entries), "ok": ok, "bad": len(bad), "bad_list": bad[:20], "seconds": time.time() - t0}))

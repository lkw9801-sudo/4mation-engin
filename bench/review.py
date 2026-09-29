"""Blunder review: replay games and classify every move of a player with the
exact solver (value before the move vs value after it)."""
from __future__ import annotations
import json, sys
from fourmation.engine import Engine
from fourmation.rules import apply_move, new_game, to_coord

ORDER = {"EXACT_LOSS": 0, "EXACT_DRAW": 1, "EXACT_WIN": 2}

def review(moves, player_is_first, eng, solve_time=10.0, start=0):
    """Returns a list of (ply, move, value_before, value_after) for the player's moves."""
    st = new_game()
    out = []
    for i, m in enumerate(moves):
        mine = (st.to_move == 1) == player_is_first
        if mine and i >= start:
            before = eng.solve(st, time=solve_time, distance=False)
            after_st = apply_move(st, m)
            if after_st.is_terminal:
                after = "EXACT_WIN" if after_st.winner else "EXACT_DRAW"
            else:
                a = eng.solve(after_st, time=solve_time, distance=False)
                after = None if a is None else {"EXACT_WIN": "EXACT_LOSS", "EXACT_LOSS": "EXACT_WIN",
                                                 "EXACT_DRAW": "EXACT_DRAW"}[a["result"]]
            out.append((i, to_coord(m), before["result"] if before else None, after))
        st = apply_move(st, m)
    return out

if __name__ == "__main__":
    eng = Engine(tt_mb=512)
    for line in open(sys.argv[1]):
        g = json.loads(line)
        rows = review(g["moves"], g["first"], eng, float(sys.argv[2]) if len(sys.argv) > 2 else 10.0,
                      start=g.get("start", 0))
        blunders = [r for r in rows if r[2] and r[3] and ORDER[r[3]] < ORDER[r[2]]]
        print(json.dumps({"game": g.get("id"), "moves": len(g["moves"]), "reviewed": rows, "blunders": blunders}))

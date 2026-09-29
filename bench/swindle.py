"""How often does the engine escape from proven-lost positions against a
fallible opponent? Compares play() with resist on/off.

    python -m bench.swindle --n 60 --opp old:ab8
"""
from __future__ import annotations
import argparse, json, random, time
from fourmation.engine import Engine
from fourmation.rules import apply_move, legal_moves, new_game
from .match import make_player, NewEnginePlayer


def lost_positions(n, seed, lo=6, hi=14):
    rng = random.Random(seed)
    eng = Engine(tt_mb=256)
    out = []
    while len(out) < n:
        st = new_game()
        target = rng.randint(lo, hi)
        while not st.is_terminal and st.ply < target:
            st = apply_move(st, rng.choice(legal_moves(st)))
        if st.is_terminal:
            continue
        s = eng.solve(st, time=3.0, distance=False)
        if s and s["result"] == "EXACT_LOSS":
            out.append(st)
    return out


def playout(st, loser, winner_bot):
    side = st.to_move
    while not st.is_terminal:
        p = loser if st.to_move == side else winner_bot
        st = apply_move(st, p.select(st))
    return "loss" if st.winner == 3 - side else ("draw" if st.winner == 0 else "win")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--opp", default="old:ab8")
    ap.add_argument("--t", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=3)
    a = ap.parse_args()
    pos = lost_positions(a.n, a.seed)
    for resist in (1, 0):
        res = {"loss": 0, "draw": 0, "win": 0}
        t0 = time.time()
        for i, st in enumerate(pos):
            me = NewEnginePlayer(f"new:t={a.t},resist={resist}")
            opp = make_player(a.opp, 1000 + i)
            res[playout(st, me, opp)] += 1
        print(f"| resist={resist} | vs {a.opp} | {a.n} lost positions (ply 6-14) | escaped: {res['win']} wins, "
              f"{res['draw']} draws, {res['loss']} losses | {time.time() - t0:.0f}s |", flush=True)


if __name__ == "__main__":
    main()

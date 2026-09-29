"""Generate realistic positions for solver benchmarks: new-engine self-play at
fixed depth with random 2-ply openings; positions sampled at given plies."""
import json, random, sys
from fourmation.rules import new_game, apply_move, legal_moves
from fourmation.engine import Engine

def main(out="bench/solve_set.json", games=16, plies=(8, 10, 12, 14, 16, 18), depth=10, seed=2024):
    rng = random.Random(seed)
    eng = Engine(tt_mb=64)
    res = {str(p): [] for p in plies}
    for g in range(games):
        st = new_game()
        for _ in range(2):
            st = apply_move(st, rng.choice(legal_moves(st)))
        while not st.is_terminal and st.ply <= max(plies):
            if st.ply in plies:
                res[str(st.ply)].append(st.to_compact())
            info = eng.think(st, depth=depth)
            st = apply_move(st, info.move_index)
    json.dump(res, open(out, "w"), indent=1)
    print({k: len(v) for k, v in res.items()})

if __name__ == "__main__":
    main()

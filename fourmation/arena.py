"""Round-robin matches between bots, for the baseline table.

    python -m fourmation.arena --bots random,ab2,ab4 --games 50 --opening 2

Each pairing plays `games` games with colours alternating. The first
`--opening` plies are random legal moves (shared by both colour swaps) so that
deterministic bots don't replay the same game.
"""
from __future__ import annotations

import argparse
import itertools
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .bots import Bot, make_bot
from .rules import P1, P2, State, apply_move, legal_moves, new_game, to_coord


@dataclass
class GameRecord:
    players: Dict[int, str]
    moves: List[int]
    winner: int  # 0 draw, 1/2
    seconds: Dict[int, float]
    bot_moves: Dict[int, int]
    illegal: Dict[int, int] = field(default_factory=lambda: {P1: 0, P2: 0})


def play_game(bots: Dict[int, Bot], opening: List[int], max_illegal_retries: int = 0) -> GameRecord:
    st = new_game()
    moves: List[int] = []
    secs = {P1: 0.0, P2: 0.0}
    counted = {P1: 0, P2: 0}
    illegal = {P1: 0, P2: 0}
    for m in opening:
        if st.is_terminal:
            break
        st = apply_move(st, m)
        moves.append(m)
    while not st.is_terminal:
        p = st.to_move
        t0 = time.perf_counter()
        m = bots[p].select(st)
        secs[p] += time.perf_counter() - t0
        counted[p] += 1
        if m not in legal_moves(st):
            # a bot that returns an illegal move loses the game
            illegal[p] += 1
            return GameRecord({k: b.name for k, b in bots.items()}, moves, 3 - p, secs, counted, illegal)
        st = apply_move(st, m)
        moves.append(m)
    return GameRecord({k: b.name for k, b in bots.items()}, moves, st.winner, secs, counted, illegal)


def random_opening(n: int, rng: random.Random) -> List[int]:
    st = new_game()
    out = []
    for _ in range(n):
        ms = legal_moves(st)
        if not ms:
            break
        m = rng.choice(ms)
        out.append(m)
        st = apply_move(st, m)
    return out


def run_match(make_a: Callable[[int], Bot], make_b: Callable[[int], Bot], games: int,
              opening_plies: int, seed: int) -> dict:
    rng = random.Random(seed)
    res = {"win": 0, "draw": 0, "loss": 0, "a_sec": 0.0, "a_moves": 0, "b_sec": 0.0,
           "b_moves": 0, "a_illegal": 0, "b_illegal": 0, "plies": 0}
    opening: List[int] = []
    for g in range(games):
        if g % 2 == 0:
            opening = random_opening(opening_plies, rng)
        a, b = make_a(seed * 1000 + g), make_b(seed * 1000 + g + 500)
        a_col = P1 if g % 2 == 0 else P2
        bots = {a_col: a, 3 - a_col: b}
        rec = play_game(bots, opening)
        if rec.winner == 0:
            res["draw"] += 1
        elif rec.winner == a_col:
            res["win"] += 1
        else:
            res["loss"] += 1
        res["a_sec"] += rec.seconds[a_col]
        res["a_moves"] += rec.bot_moves[a_col]
        res["b_sec"] += rec.seconds[3 - a_col]
        res["b_moves"] += rec.bot_moves[3 - a_col]
        res["a_illegal"] += rec.illegal[a_col]
        res["b_illegal"] += rec.illegal[3 - a_col]
        res["plies"] += len(rec.moves)
    res["games"] = games
    return res


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description="4Mation bot round robin")
    ap.add_argument("--bots", default="random,ab1,ab2,ab4")
    ap.add_argument("--games", type=int, default=20, help="games per pairing (even)")
    ap.add_argument("--opening", type=int, default=2, help="random opening plies")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    specs = [s.strip() for s in args.bots.split(",") if s.strip()]
    rows = []
    for sa, sb in itertools.combinations(specs, 2):
        r = run_match(lambda s, x=sa: make_bot(x, s), lambda s, x=sb: make_bot(x, s),
                      args.games, args.opening, args.seed)
        rows.append((sa, sb, r))
        print(f"{sa} vs {sb}: {r['win']}W {r['draw']}D {r['loss']}L", flush=True)

    print()
    print("| A | B | games | A win | draw | A loss | A score % | A sec/move | B sec/move | avg plies |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for sa, sb, r in rows:
        score = 100 * (r["win"] + 0.5 * r["draw"]) / r["games"]
        a_t = r["a_sec"] / max(r["a_moves"], 1)
        b_t = r["b_sec"] / max(r["b_moves"], 1)
        print(f"| {sa} | {sb} | {r['games']} | {r['win']} | {r['draw']} | {r['loss']} | "
              f"{score:.1f} | {a_t:.4f} | {b_t:.4f} | {r['plies'] / r['games']:.1f} |")


if __name__ == "__main__":
    main()

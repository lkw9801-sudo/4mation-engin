"""Data for the "can 4Mation be solved?" question.

    python -m bench.solvability            # prints tables used in REPORT.md

1. perft: number of move sequences from the start (native core)
2. distinct positions per ply (exact BFS) with and without symmetry -> transposition factor
3. branching: legal / safe moves per ply in engine self-play
4. upper bounds on the number of boards with k cubes (why retrograde tablebases are infeasible)
"""
from __future__ import annotations

import json
import math
import random
import time

from fourmation import native as nv
from fourmation.pyengine import NB, VALID, dilate, wincells

SYM = None


def sym_tables():
    # 8-stride symmetry maps, same convention as rules.TRANSFORMS
    maps = []
    for k in range(8):
        t = {}
        for r in range(7):
            for c in range(7):
                rr, cc = r, c
                for _ in range(k % 4):
                    rr, cc = cc, 6 - rr
                if k >= 4:
                    cc = 6 - cc
                t[r * 8 + c] = rr * 8 + cc
        maps.append(t)
    return maps


def tbits(b, t):
    out = 0
    while b:
        low = b & -b
        out |= 1 << t[low.bit_length() - 1]
        b ^= low
    return out


def legal(b0, b1, last, side):
    empty = VALID & ~(b0 | b1)
    if last < 0:
        return empty
    m = NB[last] & empty
    if m:
        return m
    m = dilate(b1 if side == 0 else b0) & empty
    return m if m else empty


def four(b):
    for s in (1, 8, 9, 7):
        y = b & (b >> s)
        if y & (y >> (2 * s)):
            return True
    return False


def distinct_positions(max_ply):
    maps = sym_tables()
    level = {(0, 0, -1)}
    rows = []
    for ply in range(1, max_ply + 1):
        side = (ply - 1) % 2
        nxt = set()
        seq = 0
        for b0, b1, last in level:
            lm = legal(b0, b1, last, side)
            while lm:
                low = lm & -lm
                m = low.bit_length() - 1
                lm ^= low
                seq += 1
                nb0, nb1 = (b0 | low, b1) if side == 0 else (b0, b1 | low)
                if four(nb0 if side == 0 else nb1):
                    continue  # terminal
                nxt.add((nb0, nb1, m))
        canon = set()
        for b0, b1, last in nxt:
            canon.add(min((tbits(b0, t), tbits(b1, t), t[last]) for t in maps))
        rows.append({"ply": ply, "distinct": len(nxt), "distinct_sym": len(canon)})
        print(json.dumps(rows[-1]), flush=True)
        level = nxt
    return rows


def branching(games=100, seed=3):
    from fourmation.engine import Engine
    from fourmation.rules import apply_move, legal_moves, new_game
    rng = random.Random(seed)
    eng = Engine(tt_mb=64)
    by = {}
    lengths = []
    for _ in range(games):
        st = new_game()
        for _ in range(2):
            st = apply_move(st, rng.choice(legal_moves(st)))
        while not st.is_terminal:
            b0, b1, last, side = nv.encode(st.board, st.last, st.to_move)
            empty = VALID & ~(b0 | b1)
            lm = legal(b0, b1, last, side)
            own, opp = (b0, b1) if side == 0 else (b1, b0)
            wO = wincells(opp) & empty
            safe = 0
            x = lm
            while x:
                low = x & -x
                m = low.bit_length() - 1
                x ^= low
                e2 = empty & ~low
                r = NB[m] & e2 or dilate(own | low) & e2 or e2
                if not (r & wO):
                    safe += 1
            d = by.setdefault(st.ply, [0, 0, 0])
            d[0] += bin(lm).count("1")
            d[1] += safe
            d[2] += 1
            st = apply_move(st, eng.think(st, depth=8).move_index)
        lengths.append(st.ply)
    return by, lengths


def main():
    L = nv.lib()
    L.fm_set_rules(1, 1)
    print("## perft from the initial position")
    for d in range(1, 10):
        t = time.time()
        n = L.fm_perft(0, 0, -1, 0, d)
        print(f"| {d} | {n} | {time.time() - t:.2f}s |", flush=True)
    print("## distinct positions per ply")
    distinct_positions(7)
    print("## branching in self-play (depth 8, 2 random plies)")
    by, lengths = branching()
    for p in sorted(by):
        a, s, n = by[p]
        if n >= 10:
            print(f"| {p} | {a / n:.2f} | {s / n:.2f} | {n} |")
    print("game length avg", sum(lengths) / len(lengths), "max", max(lengths))
    print("## upper bound on boards with k cubes: C(49,k) * C(k,ceil(k/2))")
    for k in (4, 8, 12, 16, 24, 32, 40, 44, 47):
        print(f"| {k} | {math.comb(49, k) * math.comb(k, (k + 1) // 2):.2e} |")


if __name__ == "__main__":
    main()

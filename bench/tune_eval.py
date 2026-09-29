"""Evaluation tuning with exact labels ("Texel tuning" on solved positions).

1. positions: engine self-play (depth-limited, random 2-4 ply openings, a little
   randomness), sampled at plies >= --min-ply
2. labels: exact WDL from the solver (win=1, draw=0.5, loss=0 for side to move)
3. features: core.c features() for quiet positions (no immediate win, some safe move)
4. fit: logistic regression  P(win) = sigmoid(w . f / K)  by gradient descent (numpy)
5. weights are rounded to integers (score units) and printed

    python -m bench.tune_eval gen  --games 300 --out bench/results/tune_data.json
    python -m bench.tune_eval fit  --data bench/results/tune_data.json

The weights are only accepted if they also win games (bench/match.py).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import random
import time

import numpy as np

from fourmation import native as nv
from fourmation.engine import Engine
from fourmation.rules import State, apply_move, legal_moves, new_game

NF = nv.NFEAT


def features(st: State):
    out = (ctypes.c_int * (NF + 1))()
    nv.lib().fm_features(*nv.encode(st.board, st.last, st.to_move), out)
    return list(out[:NF]), out[NF]


def gen(args):
    rng = random.Random(args.seed)
    eng = Engine(tt_mb=256)
    data = []
    t0 = time.time()
    for g in range(args.games):
        st = new_game()
        for _ in range(rng.randint(2, 4)):
            st = apply_move(st, rng.choice(legal_moves(st)))
        seq = []
        while not st.is_terminal:
            seq.append(st)
            if rng.random() < 0.15:
                m = rng.choice(legal_moves(st))
            else:
                m = eng.think(st, depth=args.play_depth).move_index
            st = apply_move(st, m)
        for s in seq:
            if s.ply < args.min_ply or rng.random() > args.sample:
                continue
            f, tact = features(s)
            if tact != 0:
                continue
            sol = eng.solve(s, time=args.solve_time, distance=False)
            if sol is None:
                continue
            y = {"EXACT_WIN": 1.0, "EXACT_DRAW": 0.5, "EXACT_LOSS": 0.0}[sol["result"]]
            data.append({"pos": s.to_compact(), "ply": s.ply, "f": f, "y": y})
        if (g + 1) % 20 == 0:
            print(f"games {g + 1}  samples {len(data)}  {time.time() - t0:.0f}s", flush=True)
    json.dump(data, open(args.out, "w"))
    print("samples", len(data))


def fit(args):
    data = json.load(open(args.data))
    X = np.array([d["f"] for d in data], dtype=float)
    y = np.array([d["y"] for d in data])
    ply = np.array([d["ply"] for d in data])
    rng = np.random.default_rng(0)
    idx = rng.permutation(len(y))
    ntest = len(y) // 5
    te, tr = idx[:ntest], idx[ntest:]
    use = [i for i in range(NF) if X[:, i].std() > 0 or i == NF - 1]
    mu = X[tr].mean(0)
    sd = X[tr].std(0)
    sd[sd == 0] = 1
    mu[NF - 1] = 0
    sd[NF - 1] = 1
    Z = (X - mu) / sd
    mask = np.zeros(NF)
    mask[use] = 1
    if args.features:
        mask[:] = 0
        for i in map(int, args.features.split(",")):
            mask[i] = 1
        mask[NF - 1] = 1

    def loss_grad(w, Zs, ys, l2):
        p = 1 / (1 + np.exp(-(Zs @ w)))
        loss = np.mean((p - ys) ** 2) + l2 * np.sum(w[:-1] ** 2)
        g = Zs.T @ ((p - ys) * p * (1 - p)) * 2 / len(ys) + 2 * l2 * np.r_[w[:-1], 0]
        return loss, g

    w = np.zeros(NF)
    lr = 0.5
    for it in range(args.iters):
        l, g = loss_grad(w, Z[tr], y[tr], args.l2)
        w -= lr * g * mask
    ltr, _ = loss_grad(w, Z[tr], y[tr], 0)
    lte, _ = loss_grad(w, Z[te], y[te], 0)
    base = np.mean((y[te] - y[tr].mean()) ** 2)

    def acc(Zs, ys):
        p = 1 / (1 + np.exp(-(Zs @ w)))
        dec = ys != 0.5
        return np.mean((p[dec] > 0.5) == (ys[dec] > 0.5))

    print(f"samples {len(y)} (test {ntest})  win {np.mean(y == 1):.2f} draw {np.mean(y == 0.5):.2f}")
    print(f"MSE train {ltr:.4f} test {lte:.4f}  (constant baseline {base:.4f})  "
          f"decisive accuracy test {acc(Z[te], y[te]):.3f}")
    # current engine weights for comparison, fitted scale only
    from fourmation.engine_defaults import DEFAULT_WEIGHTS
    raw = X @ np.array(DEFAULT_WEIGHTS, dtype=float)
    best = None
    for K in (5, 10, 20, 40, 80, 160, 320):
        p = 1 / (1 + np.exp(-raw[te] / K))
        m = np.mean((p - y[te]) ** 2)
        if best is None or m < best[0]:
            best = (m, K)
    print(f"default weights: best-scale MSE test {best[0]:.4f} (K={best[1]})")
    # back to raw feature units, scaled so that one logistic unit = args.scale points
    wr = w / sd * args.scale
    bias = w[NF - 1] * args.scale - np.sum(w[:-1] / sd[:-1] * mu[:-1]) * args.scale
    wr[NF - 1] = bias
    ints = [int(round(v)) for v in wr]
    print("weights:", ints)
    for lo, hi in ((10, 16), (16, 22), (22, 30), (30, 49)):
        sel = te[(ply[te] >= lo) & (ply[te] < hi)]
        if len(sel):
            print(f"  ply {lo}-{hi - 1}: n={len(sel)} decisive acc {acc(Z[sel], y[sel]):.3f}")
    return ints


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    g = sub.add_parser("gen")
    g.add_argument("--games", type=int, default=200)
    g.add_argument("--min-ply", type=int, default=10)
    g.add_argument("--sample", type=float, default=0.5)
    g.add_argument("--play-depth", type=int, default=8)
    g.add_argument("--solve-time", type=float, default=3.0)
    g.add_argument("--seed", type=int, default=1)
    g.add_argument("--out", default="bench/results/tune_data.json")
    f = sub.add_parser("fit")
    f.add_argument("--data", default="bench/results/tune_data.json")
    f.add_argument("--iters", type=int, default=4000)
    f.add_argument("--l2", type=float, default=1e-4)
    f.add_argument("--scale", type=float, default=100.0)
    f.add_argument("--features", default="")
    a = ap.parse_args()
    if a.cmd == "gen":
        gen(a)
    elif a.cmd == "fit":
        fit(a)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()

"""Engine-vs-engine matches with alternating colours.

    python -m bench.match --a new:t=0.1 --b old:ab8 --games 100 --opening 2 --procs 2

Player specs
    old:ab<d>          the original AlphaBetaBot (fixed depth, Python)
    greedy             tactical 2-ply baseline (fourmation.bots.GreedyBot)
    random             RandomBot
    new:t=<sec>        new engine, time limit per move (exact solve first, then iterative deepening)
    new:t=<sec>,mode=think   iterative deepening only
    new:d=<depth>      new engine, fixed depth
    extra keys for new:  w=<json list of 16 weights>  opt=<json dict of options>
                         tt=<MB>  soft=<fraction>  book=<file>  resist=1  ss=<solve share>
                         (e.g. new:t=0.1,opt={"reply_order":1})

Each opening (random legal plies) is played twice with colours swapped.
"""
from __future__ import annotations

import argparse
import json
import math
import multiprocessing as mp
import random
import time
from typing import Dict, List

from fourmation.bots import make_bot
from fourmation.rules import P1, P2, apply_move, legal_moves, new_game


class NewEnginePlayer:
    def __init__(self, spec: str):
        from fourmation.engine import Engine
        kv = {}
        body = spec.split(":", 1)[1]
        # split on commas that are not inside brackets/braces
        part, depth_b, parts = "", 0, []
        for ch in body:
            if ch in "[{":
                depth_b += 1
            elif ch in "]}":
                depth_b -= 1
            if ch == "," and depth_b == 0:
                parts.append(part)
                part = ""
            else:
                part += ch
        if part:
            parts.append(part)
        for p in parts:
            k, v = p.split("=", 1)
            kv[k] = v
        self.time = float(kv["t"]) if "t" in kv else None
        self.depth = int(kv["d"]) if "d" in kv else None
        self.soft = float(kv.get("soft", 0.45))
        self.mode = kv.get("mode", "play")  # play = exact solve first, then ID; think = ID only
        self.resist = kv.get("resist", "0") == "1"
        self.solve_share = float(kv.get("ss", 0.5))
        weights = json.loads(kv["w"]) if "w" in kv else None
        opts = json.loads(kv["opt"]) if "opt" in kv else None
        book = None
        if "book" in kv:
            from fourmation.book import Book
            book = Book(kv["book"])
        self.eng = Engine(tt_mb=int(kv.get("tt", 128)), weights=weights, options=opts, book=book)
        self.name = spec
        self.last_nodes = 0
        self.last_depth = 0

    def select(self, st):
        if self.mode == "play" and self.time and not self.depth:
            info = self.eng.play(st, time=self.time, resist=self.resist, solve_share=self.solve_share)
        else:
            info = self.eng.think(st, time=self.time, depth=self.depth, soft=self.soft)
        self.last_nodes = info.nodes
        self.last_depth = info.depth
        return info.move_index


def make_player(spec: str, seed: int):
    if spec.startswith("new:"):
        return NewEnginePlayer(spec)
    if spec.startswith("old:"):
        return make_bot(spec[4:], seed)
    return make_bot(spec, seed)


def random_opening(n: int, rng: random.Random) -> List[int]:
    st = new_game()
    out = []
    for _ in range(n):
        m = rng.choice(legal_moves(st))
        out.append(m)
        st = apply_move(st, m)
    return out


def play(job):
    a_spec, b_spec, opening, a_first, seed = job
    a = make_player(a_spec, seed)
    b = make_player(b_spec, seed + 7919)
    col = {P1: a, P2: b} if a_first else {P1: b, P2: a}
    st = new_game()
    for m in opening:
        st = apply_move(st, m)
    stats = {"a": {"t": [], "nodes": [], "depth": []}, "b": {"t": [], "nodes": [], "depth": []}}
    moves = list(opening)
    while not st.is_terminal:
        p = col[st.to_move]
        who = "a" if p is a else "b"
        t0 = time.perf_counter()
        m = p.select(st)
        stats[who]["t"].append(time.perf_counter() - t0)
        stats[who]["nodes"].append(getattr(p, "last_nodes", 0) or getattr(p, "nodes", 0))
        stats[who]["depth"].append(getattr(p, "last_depth", 0))
        if m not in legal_moves(st):
            return {"winner": "b" if who == "a" else "a", "illegal": who, "stats": stats, "moves": moves,
                    "a_first": a_first}
        st = apply_move(st, m)
        moves.append(m)
    if st.winner == 0:
        w = "draw"
    else:
        w = "a" if col[st.winner] is a else "b"
    return {"winner": w, "stats": stats, "moves": moves, "a_first": a_first, "plies": st.ply}


def run(a_spec, b_spec, games, opening, procs, seed, dump=""):
    rng = random.Random(seed)
    jobs = []
    for g in range(0, games, 2):
        op = random_opening(opening, rng)
        jobs.append((a_spec, b_spec, op, True, seed * 100000 + g))
        jobs.append((a_spec, b_spec, op, False, seed * 100000 + g + 1))
    jobs = jobs[:games]
    if procs > 1:
        with mp.Pool(procs) as pool:
            res = pool.map(play, jobs, chunksize=1)
    else:
        res = [play(j) for j in jobs]
    if dump:
        with open(dump, "a") as f:
            for i, r in enumerate(res):
                if r["winner"] != "a":
                    f.write(json.dumps({"id": f"{a_spec} vs {b_spec} #{i}", "moves": r["moves"],
                                        "first": r["a_first"], "start": opening, "winner": r["winner"]}) + "\n")
    return summarize(a_spec, b_spec, res)


def summarize(a_spec, b_spec, res):
    w = sum(r["winner"] == "a" for r in res)
    l = sum(r["winner"] == "b" for r in res)
    d = sum(r["winner"] == "draw" for r in res)
    n = len(res)
    score = (w + 0.5 * d) / n
    # Elo with a 95% interval from the score's standard error (only meaningful for larger n)
    def elo(s):
        s = min(max(s, 1e-3), 1 - 1e-3)
        return -400 * math.log10(1 / s - 1)
    var = sum(((1 if r["winner"] == "a" else (0.5 if r["winner"] == "draw" else 0)) - score) ** 2
              for r in res) / max(n - 1, 1)
    se = math.sqrt(var / n)
    out = {"a": a_spec, "b": b_spec, "games": n, "a_win": w, "draw": d, "a_loss": l, "a_score": score,
           "elo": elo(score), "elo_lo": elo(score - 1.96 * se), "elo_hi": elo(score + 1.96 * se),
           "a_win_as_first": sum(r["winner"] == "a" and r["a_first"] for r in res),
           "a_win_as_second": sum(r["winner"] == "a" and not r["a_first"] for r in res),
           "b_win_as_first": sum(r["winner"] == "b" and not r["a_first"] for r in res),
           "b_win_as_second": sum(r["winner"] == "b" and r["a_first"] for r in res),
           "illegal": sum(1 for r in res if "illegal" in r),
           "avg_plies": sum(len(r["moves"]) for r in res) / n}
    for who in ("a", "b"):
        ts = [t for r in res for t in r["stats"][who]["t"]]
        ns = [x for r in res for x in r["stats"][who]["nodes"]]
        ds = [x for r in res for x in r["stats"][who]["depth"]]
        out[f"{who}_avg_time"] = sum(ts) / max(len(ts), 1)
        out[f"{who}_max_time"] = max(ts) if ts else 0
        out[f"{who}_avg_nodes"] = sum(ns) / max(len(ns), 1)
        out[f"{who}_avg_depth"] = sum(ds) / max(len(ds), 1)
    return out


def fmt(r):
    return (f"| {r['a']} | {r['b']} | {r['games']} | {r['a_win']} | {r['draw']} | {r['a_loss']} | "
            f"{100 * r['a_score']:.1f}% | {r['elo']:+.0f} [{r['elo_lo']:+.0f},{r['elo_hi']:+.0f}] | "
            f"{r['a_avg_time']:.3f} / {r['a_max_time']:.2f} | {r['b_avg_time']:.3f} / {r['b_max_time']:.2f} | "
            f"{r['a_avg_nodes']:.0f} | {r['a_avg_depth']:.1f} | {r['avg_plies']:.1f} |")


HEADER = ("| A | B | games | A win | draw | A loss | A score | Elo diff [95%] | A s/move avg / max | "
          "B s/move avg / max | A nodes/move | A depth | plies |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--opening", type=int, default=2)
    ap.add_argument("--procs", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="")
    ap.add_argument("--dump-losses", default="", help="append games A did not win (JSONL, for bench.review)")
    a = ap.parse_args()
    t0 = time.time()
    r = run(a.a, a.b, a.games, a.opening, a.procs, a.seed, a.dump_losses)
    r["wall"] = time.time() - t0
    print(HEADER)
    print(fmt(r))
    print(json.dumps(r))
    if a.out:
        with open(a.out, "a") as f:
            f.write(json.dumps(r) + "\n")


if __name__ == "__main__":
    main()

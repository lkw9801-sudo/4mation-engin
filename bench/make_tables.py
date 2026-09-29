"""Markdown tables for REPORT.md from bench/results/*.jsonl."""
from __future__ import annotations

import json
import os
import sys

R = "bench/results"


def load(name):
    p = os.path.join(R, name)
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p) if l.strip().startswith("{")]


def legacy_table():
    rows = load("legacy_d2_12.jsonl") + load("legacy_d14plus.jsonl")
    mem = {(m["position"], m["depth"]): m["max_rss_mb"] for m in load("legacy_memory.jsonl")}
    out = ["| position | depth | best | score | result | time s | nodes | nodes/s | TT hit | TT cut | beta-cut / interior | 1st-move cut | RSS MB | PV (TT walk) |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for pos in ("initial", "early", "mid", "tactical", "late"):
        for r in sorted((r for r in rows if r["position"] == pos), key=lambda r: r["depth"]):
            if r.get("timeout"):
                out.append(f"| {pos} | {r['depth']} | timeout | | | >{r['elapsed']:.0f} | {r['nodes']} | | | | | | | |")
                continue
            out.append(f"| {pos} | {r['depth']} | {r['best']} | {r['score']} | {r['result']} | {r['elapsed']:.2f} | "
                       f"{r['nodes']:,} | {r['nps']:,.0f} | {r['tt_hit_rate']:.2f} | {r['tt_cutoff_rate']:.2f} | "
                       f"{r['cutoff_rate']:.2f} | {r['first_move_cutoff_rate']:.2f} | "
                       f"{int(mem[(pos, r['depth'])]) if (pos, r['depth']) in mem else ''} | {' '.join(r['pv'][:8])} |")
    return "\n".join(out)


def new_table():
    rows = load("new_engine.jsonl")
    out = ["| position | depth | best | score | result | dist | time s | nodes | nodes/s | TT hit | 1st-move cut | PV |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['position']} | {r['depth']} | {r['best']} | {r['score']} | {r['result']} | "
                   f"{r['distance'] if r['distance'] is not None else ''} | {r['elapsed']:.3f} | {r['nodes']:,} | "
                   f"{r['nps']:,.0f} | {r['tt_hit_rate']:.2f} | {r['first_move_cutoff_rate']:.2f} | {' '.join(r['pv'][:10])} |")
    return "\n".join(out)


def convergence():
    old = load("legacy_d2_12.jsonl") + load("legacy_d14plus.jsonl")
    new = load("new_engine.jsonl")
    out = ["| position | old engine: depth -> best (score) | new engine: depth -> best (score / result) |", "|---|---|---|"]
    for pos in ("initial", "early", "mid", "tactical", "late"):
        o = " , ".join(f"D{r['depth']} {r['best']} ({r['score']})" for r in sorted(
            (r for r in old if r["position"] == pos and not r.get("timeout")), key=lambda r: r["depth"]))
        n = " , ".join(f"D{r['depth']} {r['best']} ({r['score']}{'' if r['result'] == 'HEURISTIC' else ' ' + r['result']})"
                       for r in new if r["position"] == pos)
        out.append(f"| {pos} | {o} | {n} |")
    return "\n".join(out)


def matches(name="matches.jsonl"):
    rows = load(name)
    out = ["| A | B | games | A W-D-L | A score | Elo diff [95%] | A win as 1st / 2nd | B win as 1st / 2nd | A s/move avg (max) | B s/move avg (max) | A nodes/move | plies |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(f"| {r['a']} | {r['b']} | {r['games']} | {r['a_win']}-{r['draw']}-{r['a_loss']} | {100 * r['a_score']:.1f}% | "
                   f"{r['elo']:+.0f} [{r['elo_lo']:+.0f}, {r['elo_hi']:+.0f}] | {r['a_win_as_first']} / {r['a_win_as_second']} | "
                   f"{r['b_win_as_first']} / {r['b_win_as_second']} | {r['a_avg_time']:.3f} ({r['a_max_time']:.2f}) | "
                   f"{r['b_avg_time']:.3f} ({r['b_max_time']:.2f}) | {r['a_avg_nodes']:,.0f} | {r['avg_plies']:.1f} |")
    return "\n".join(out)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    for name, fn in (("legacy", legacy_table), ("new", new_table), ("convergence", convergence), ("matches", matches)):
        if what in ("all", name):
            print(f"### {name}\n")
            print(fn())
            print()

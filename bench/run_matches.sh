#!/bin/bash
# Match suite used in REPORT.md section 9 (v2 engine).
# Colours alternate; each random 2-ply opening is played twice (same seeds as the original arena run).
# Non-won games of A are appended to results/match_losses.jsonl for bench.review_losses.
OUT=bench/results/matches.jsonl
P=${PROCS:-1}
m() { timeout 14400 python3 -m bench.match --a "$1" --b "$2" --games $3 --opening 2 --procs $P --seed ${4:-1} \
        --out $OUT --dump-losses bench/results/match_losses.jsonl | sed -n 3p; }
m new:t=0.1 random 100
m new:t=0.1 greedy 100
m new:t=0.1 old:ab8 100
m new:t=0.1 old:ab10 60
m new:t=0.5 old:ab10 60
m new:t=1 old:ab10 40
m new:t=5 old:ab10 20
# baselines among the old players (engine independent)
m old:ab8 greedy 100
m old:ab10 old:ab8 60

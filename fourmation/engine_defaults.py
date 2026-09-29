"""Default search options and evaluation weights (shared by engine.py and pyengine.py).

Feature order (side to move = S, opponent = O), see core.c features():
 0-2  open 4-windows holding 1/2/3 cubes of S (no O cube)
 3-5  same for O
 6/7  threat cells of S / O (empty cell completing a 4-row)
 8    safe moves of S (moves after which O cannot win at once)
 9/10 empty cells next to S's / O's threat cells (no-go zone for the other side)
 11   legal moves of S
 12   safe moves of S that create a new threat cell
 13   S threat cells touching an O cube (reachable through a dead end)
 14   O threat cells touching an S cube
 15   constant (tempo)
"""
DEFAULT_OPTIONS = {
    "tt": 1, "sym": 1, "pvs": 1, "killer": 1, "history": 1, "threat_order": 1,
    "safe_prune": 1, "ext_forced": 0, "leaf_win3": 0, "aspiration": 1, "counter": 1, "mdp": 1,
    "dead_prune": 1, "etc": 0, "reply_order": 0,
    "sym_max_n": 48, "reply_min_depth": 2,
}
# Fitted by logistic regression on 4,932 positions labelled with exact WDL by the
# solver (bench/tune_eval.py, bench/results/tune_all.json) and accepted only after
# winning matches: +27..+54 Elo at depth 8 / depth 12 / 0.05 s (bench/results/eval_matches.jsonl).
DEFAULT_WEIGHTS = [14, 34, 24, -13, -35, -45, -16, -4, 7, 22, -16, 3, 44, 27, 5, 11]
# the original window-count weights (1/8/64), kept for ablations
LEGACY_WEIGHTS = [1, 8, 64, -1, -8, -64, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

# Overrides for searches to the end of the game (bench/results/solver_ablation_*):
# history-style heuristics hurt proofs, ordering by opponent reply mobility helps.
DEFAULT_SOLVER_OPTIONS = {"reply_order": 1, "killer": 0, "history": 0, "counter": 0}

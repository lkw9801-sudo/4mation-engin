"""Representative benchmark positions (compact notation: 49 cells a1..g7, side, last).

Positions were taken from seeded ab4 self-play games (2 random opening plies);
see bench/README.md. `tactical` is a forced win for the side to move (O) in
7 plies that ab3 does not see.
"""

POSITIONS = {
    "initial": "................................................. X -",
    "early": "....X.....XOO...O.X.............................. X c3",
    "mid": ".XO....XO.....OXO....OOXX...XX.OX..O............. X c1",
    "tactical": "XOOX...OXOXO..X.OX.X.O...XOXX....O..OX........... O c6",
    "late": "OXOOOX.OXOXX.OOXX....XOX....XOXO...OXOX....XOXO.. X g2",
}

ORDER = ["initial", "early", "mid", "tactical", "late"]

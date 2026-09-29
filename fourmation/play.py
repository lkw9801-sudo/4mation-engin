"""Play against a bot in the terminal.

    python -m fourmation.play --bot ab4 --first human          # original alpha-beta bot
    python -m fourmation.play --bot new --time 1 --first human # reference engine (1 s per move)
"""
from __future__ import annotations

import argparse

from .bots import AlphaBetaBot, make_bot
from .rules import P1, SYMBOLS, apply_move, legal_moves, new_game, parse_coord, to_coord


class _NewBot:
    def __init__(self, time: float, book: bool):
        from .engine import Engine
        self.eng = Engine(tt_mb=256, book="default" if book else None)
        self.time = time
        self.name = f"new({time:g}s)"
        self.last = None

    def select(self, st):
        self.last = self.eng.play(st, time=self.time)
        return self.last.move_index


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bot", default="ab4", help="random | greedy | ab<depth> | new")
    ap.add_argument("--time", type=float, default=1.0, help="seconds per move for --bot new")
    ap.add_argument("--no-book", action="store_true", help="new engine without the opening book")
    ap.add_argument("--first", choices=["human", "bot"], default="human")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    bot = _NewBot(args.time, not args.no_book) if args.bot == "new" else make_bot(args.bot, args.seed)
    human = P1 if args.first == "human" else 3 - P1
    st = new_game()
    while not st.is_terminal:
        print()
        print(st.to_text())
        legal = legal_moves(st)
        if st.to_move == human:
            print(f"you are {SYMBOLS[human]}; legal: {' '.join(to_coord(m) for m in legal)}")
            try:
                m = parse_coord(input("move> "))
            except ValueError as e:
                print(e)
                continue
            if m not in legal:
                print("illegal move")
                continue
        else:
            m = bot.select(st)
            print(f"{bot.name} plays {to_coord(m)}")
            if isinstance(bot, AlphaBetaBot):
                print(f"  (nodes searched: {bot.nodes})")
            elif isinstance(bot, _NewBot):
                i = bot.last
                extra = f", distance {i.distance}" if i.distance is not None else ""
                how = "book" if i.source == "book" else f"{i.source}, depth {i.depth}, {i.nodes} nodes"
                print(f"  ({i.result}{extra}; {how})")
        st = apply_move(st, m)
    print()
    print(st.to_text())
    print("draw" if st.winner == 0 else f"{SYMBOLS[st.winner]} wins")


if __name__ == "__main__":
    main()

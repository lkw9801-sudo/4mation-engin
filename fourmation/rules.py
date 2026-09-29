"""4Mation rules engine (Piatnik rulebook).

Board: 7x7, cells indexed r*7+c with r=0 as row 1 (bottom) and c=0 as column a.
Notation: "d4" = column d, row 4.

Rules implemented (from the official Piatnik rulebook):
- Each player has 24 cubes. The starting player may place anywhere.
- Every cube must touch an edge or corner (8-neighbourhood) of the last placed cube.
- Dead end ("Sackgasse"): if no free cell touches the last cube, the player may
  place on any free cell that touches any cube of the opponent's colour.
- A player wins immediately with 4 (or more) own cubes in a row horizontally,
  vertically or diagonally.
- The game is a draw when no player can still form a valid 4-row.

Two situations the rulebook does not define are configurable in RuleConfig.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

SIZE = 7
N = SIZE * SIZE
CUBES_PER_PLAYER = 24
WIN_LEN = 4

EMPTY, P1, P2 = 0, 1, 2
SYMBOLS = {EMPTY: ".", P1: "X", P2: "O"}
FROM_SYMBOL = {".": EMPTY, "X": P1, "O": P2}
COLS = "abcdefg"
_LINE_DIRS = ((0, 1), (1, 0), (1, 1), (1, -1))


def idx(r: int, c: int) -> int:
    return r * SIZE + c


def rc(i: int) -> Tuple[int, int]:
    return divmod(i, SIZE)


def to_coord(i: int) -> str:
    r, c = rc(i)
    return f"{COLS[c]}{r + 1}"


def parse_coord(s: str) -> int:
    s = s.strip().lower()
    if len(s) != 2 or s[0] not in COLS or s[1] not in "1234567":
        raise ValueError(f"bad coordinate: {s!r}")
    return idx(int(s[1]) - 1, COLS.index(s[0]))


def _in_bounds(r: int, c: int) -> bool:
    return 0 <= r < SIZE and 0 <= c < SIZE


NEIGHBORS: Tuple[Tuple[int, ...], ...] = tuple(
    tuple(
        idx(r + dr, c + dc)
        for dr in (-1, 0, 1)
        for dc in (-1, 0, 1)
        if (dr, dc) != (0, 0) and _in_bounds(r + dr, c + dc)
    )
    for r, c in (rc(i) for i in range(N))
)

# Every set of 4 consecutive cells in a line (88 windows on a 7x7 board).
WINDOWS: Tuple[Tuple[int, ...], ...] = tuple(
    tuple(idx(r + k * dr, c + k * dc) for k in range(WIN_LEN))
    for dr, dc in _LINE_DIRS
    for r in range(SIZE)
    for c in range(SIZE)
    if _in_bounds(r + (WIN_LEN - 1) * dr, c + (WIN_LEN - 1) * dc)
)
WINDOWS_THROUGH: Tuple[Tuple[int, ...], ...] = tuple(
    tuple(w for w, cells in enumerate(WINDOWS) if i in cells) for i in range(N)
)


@dataclass(frozen=True)
class RuleConfig:
    # No free cell touches the last cube AND no free cell touches any opponent
    # cube (not covered by the rulebook): "any_empty" lets the player use any
    # free cell, "draw" ends the game as a draw.
    no_move_fallback: str = "any_empty"
    # "open_line": draw as soon as neither player has a 4-window that is still
    # completable (no opponent cube, enough cubes left) - the rulebook wording.
    # "exhaustion": play on until someone wins or nobody can move.
    draw_rule: str = "open_line"


DEFAULT_RULES = RuleConfig()


@dataclass(frozen=True)
class State:
    board: Tuple[int, ...] = (EMPTY,) * N
    to_move: int = P1
    last: Optional[int] = None
    placed: Tuple[int, int] = (0, 0)
    winner: Optional[int] = None  # None = ongoing, 0 = draw, 1/2 = player
    ply: int = 0
    rules: RuleConfig = field(default=DEFAULT_RULES, compare=False)

    # ---- queries -------------------------------------------------------
    @property
    def is_terminal(self) -> bool:
        return self.winner is not None

    def cubes_left(self, player: int) -> int:
        return CUBES_PER_PLAYER - self.placed[player - 1]

    def key(self) -> Tuple:
        """Hashable identity for search (legal moves depend on `last`)."""
        return (self.board, self.to_move, self.last)

    # ---- construction --------------------------------------------------
    @classmethod
    def from_rows(
        cls,
        rows: Sequence[str],
        to_move: Optional[int] = None,
        last: Optional[str] = None,
        rules: RuleConfig = DEFAULT_RULES,
    ) -> "State":
        """Build a position from 7 strings written top row (row 7) first.

        Winner/draw status is recomputed from the board.
        """
        if len(rows) != SIZE or any(len(r.replace(" ", "")) != SIZE for r in rows):
            raise ValueError("need 7 rows of 7 cells")
        board = [EMPTY] * N
        for k, row in enumerate(rows):
            r = SIZE - 1 - k
            for c, ch in enumerate(row.replace(" ", "")):
                board[idx(r, c)] = FROM_SYMBOL[ch.upper()]
        b = tuple(board)
        placed = (b.count(P1), b.count(P2))
        if to_move is None:
            to_move = P1 if placed[0] == placed[1] else P2
        last_i = parse_coord(last) if last else None
        st = cls(b, to_move, last_i, placed, None, sum(placed), rules)
        return _with_status(st)

    @classmethod
    def from_compact(cls, s: str, rules: RuleConfig = DEFAULT_RULES) -> "State":
        """Inverse of to_compact(): '<49 cells a1..g7> <X|O> <last|->'."""
        parts = s.split()
        if len(parts) != 3 or len(parts[0]) != N:
            raise ValueError(f"bad compact state: {s!r}")
        cells, side, last = parts
        b = tuple(FROM_SYMBOL[ch.upper()] for ch in cells)
        placed = (b.count(P1), b.count(P2))
        last_i = None if last == "-" else parse_coord(last)
        if last_i is not None and b[last_i] != 3 - FROM_SYMBOL[side.upper()]:
            raise ValueError("last move must be a cube of the player who just moved")
        st = cls(b, FROM_SYMBOL[side.upper()], last_i, placed, None, sum(placed), rules)
        return _with_status(st)

    # ---- display -------------------------------------------------------
    def to_text(self) -> str:
        lines = []
        for r in range(SIZE - 1, -1, -1):
            cells = []
            for c in range(SIZE):
                i = idx(r, c)
                s = SYMBOLS[self.board[i]]
                cells.append(s.lower() if i == self.last else s)
            lines.append(f"{r + 1} " + " ".join(cells))
        lines.append("  " + " ".join(COLS))
        return "\n".join(lines)

    def to_compact(self) -> str:
        """Single-line encoding: 49 cells (a1..g7), side to move, last move."""
        cells = "".join(SYMBOLS[v] for v in self.board)
        last = to_coord(self.last) if self.last is not None else "-"
        return f"{cells} {SYMBOLS[self.to_move]} {last}"


# ---- rules --------------------------------------------------------------

def legal_moves(st: State) -> List[int]:
    if st.winner is not None:
        return []
    return _raw_moves(st.board, st.to_move, st.last, st.placed, st.rules)


def _raw_moves(board, to_move, last, placed, rules) -> List[int]:
    if placed[to_move - 1] >= CUBES_PER_PLAYER:
        return []
    if last is None:
        return [i for i in range(N) if board[i] == EMPTY]
    adj = [n for n in NEIGHBORS[last] if board[n] == EMPTY]
    if adj:
        return adj
    opp = 3 - to_move
    cand = sorted(
        {n for i in range(N) if board[i] == opp for n in NEIGHBORS[i] if board[n] == EMPTY}
    )
    if cand:
        return cand
    if rules.no_move_fallback == "any_empty":
        return [i for i in range(N) if board[i] == EMPTY]
    return []


def line_length_through(board: Sequence[int], i: int) -> int:
    """Longest run of board[i]'s colour through cell i."""
    p = board[i]
    r0, c0 = rc(i)
    best = 0
    for dr, dc in _LINE_DIRS:
        n = 1
        for sign in (1, -1):
            r, c = r0 + sign * dr, c0 + sign * dc
            while _in_bounds(r, c) and board[idx(r, c)] == p:
                n += 1
                r, c = r + sign * dr, c + sign * dc
        best = max(best, n)
    return best


def has_open_line(board: Sequence[int], placed: Tuple[int, int]) -> bool:
    """True if some player can still complete a 4-window (ignoring placement order)."""
    left = (CUBES_PER_PLAYER - placed[0], CUBES_PER_PLAYER - placed[1])
    for w in WINDOWS:
        vals = [board[i] for i in w]
        empties = vals.count(EMPTY)
        if P2 not in vals and empties <= left[0]:
            return True
        if P1 not in vals and empties <= left[1]:
            return True
    return False


def apply_move(st: State, move: int, validate: bool = True) -> State:
    if validate:
        if st.winner is not None:
            raise ValueError("game is over")
        if move not in legal_moves(st):
            raise ValueError(f"illegal move {to_coord(move)}")
    p = st.to_move
    board = st.board[:move] + (p,) + st.board[move + 1:]
    placed = (st.placed[0] + (p == P1), st.placed[1] + (p == P2))
    nxt = State(board, 3 - p, move, placed, None, st.ply + 1, st.rules)
    if line_length_through(board, move) >= WIN_LEN:
        return State(board, 3 - p, move, placed, p, st.ply + 1, st.rules)
    return _with_status(nxt, check_wins=False)


def _with_status(st: State, check_wins: bool = True) -> State:
    """Set winner/draw for a freshly built position."""
    if check_wins:
        for p in (P1, P2):
            for w in WINDOWS:
                if all(st.board[i] == p for i in w):
                    return _replace_winner(st, p)
    if st.rules.draw_rule == "open_line" and not has_open_line(st.board, st.placed):
        return _replace_winner(st, 0)
    if not _raw_moves(st.board, st.to_move, st.last, st.placed, st.rules):
        return _replace_winner(st, 0)
    return st


def _replace_winner(st: State, w: int) -> State:
    return State(st.board, st.to_move, st.last, st.placed, w, st.ply, st.rules)


def new_game(rules: RuleConfig = DEFAULT_RULES) -> State:
    return State(rules=rules)


# ---- symmetry (8 dihedral transforms, for data augmentation) ------------

def _transform_rc(k: int, r: int, c: int) -> Tuple[int, int]:
    m = SIZE - 1
    for _ in range(k % 4):
        r, c = c, m - r
    if k >= 4:
        c = m - c
    return r, c


TRANSFORMS: Tuple[Tuple[int, ...], ...] = tuple(
    tuple(idx(*_transform_rc(k, *rc(i))) for i in range(N)) for k in range(8)
)


def transform_state(st: State, k: int) -> State:
    perm = TRANSFORMS[k]
    board = [EMPTY] * N
    for i, v in enumerate(st.board):
        board[perm[i]] = v
    last = perm[st.last] if st.last is not None else None
    return State(tuple(board), st.to_move, last, st.placed, st.winner, st.ply, st.rules)

"""Pure-Python bitboard engine: the same search as the native core, used
(a) as a fallback when no C compiler is available and (b) to measure what
Python-level optimisation alone achieves (see bench/README.md).

Differences from core.c: no symmetry keys (too slow in Python), no ETC and no
reply-mobility ordering; everything else (bitboards, immediate-win /
safe-move pruning, mate scores by absolute cube count, TT with bounds,
iterative deepening, PVS, killers, history, threat ordering, same evaluation
features) follows core.c.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from .rules import CUBES_PER_PLAYER, State, to_coord

VALID = 0x007F7F7F7F7F7F7F
MATE = 30000
MATE_BOUND = MATE - 100
INF = 32000
TOTAL = 48
NONE = 64
COMPLETE = 127
EVAL_CAP = 20000

NB = [0] * 65
for _r in range(7):
    for _c in range(7):
        _m = 0
        for _dr in (-1, 0, 1):
            for _dc in (-1, 0, 1):
                if (_dr or _dc) and 0 <= _r + _dr < 7 and 0 <= _c + _dc < 7:
                    _m |= 1 << ((_r + _dr) * 8 + _c + _dc)
        NB[_r * 8 + _c] = _m

WINS: List[int] = []
for _dr, _dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
    for _r in range(7):
        for _c in range(7):
            if 0 <= _r + 3 * _dr < 7 and 0 <= _c + 3 * _dc < 7:
                WINS.append(sum(1 << ((_r + k * _dr) * 8 + _c + k * _dc) for k in range(4)))

WSTART = ((1, 0x000F0F0F0F0F0F0F), (8, 0x000000007F7F7F7F), (9, 0x000000000F0F0F0F),
          (7, 0x0000000078787878))
M64 = (1 << 64) - 1


def popc(x: int) -> int:
    return bin(x).count("1")


def bits(x: int):
    while x:
        low = x & -x
        yield low.bit_length() - 1
        x ^= low


def dilate(x: int) -> int:
    h = x | (x << 1) | (x >> 1)
    return (h | (h << 8) | (h >> 8)) & VALID


def wincells(b: int) -> int:
    r = 0
    for s in (1, 8, 9, 7):
        p = (b << s) & (b << (2 * s))
        r |= p & (b << (3 * s))
        r |= p & (b >> s)
        p = (b >> s) & (b >> (2 * s))
        r |= p & (b >> (3 * s))
        r |= p & (b << s)
    return r & VALID


def has_open(opp: int, empty: int, left: int) -> bool:
    if left <= 0:
        return False
    if left >= 4:
        f = VALID & ~opp
        for s in (1, 8, 9, 7):
            y = f & (f >> s)
            if y & (y >> (2 * s)):
                return True
        return False
    return any(not (w & opp) and popc(w & empty) <= left for w in WINS)


def window_counts(own: int, opp: int) -> Tuple[int, int, int]:
    a1 = a2 = a3 = 0
    for s, start in WSTART:
        o0, o1, o2, o3 = own, own >> s, own >> (2 * s), own >> (3 * s)
        blk = opp | (opp >> s) | (opp >> (2 * s)) | (opp >> (3 * s))
        F = start & ~blk
        a = o0 ^ o1
        ca = o0 & o1
        b = o2 ^ o3
        cb = o2 & o3
        low = a ^ b
        c = a & b
        mid = ca ^ cb ^ c
        high = (ca & cb) | (c & (ca ^ cb))
        a1 += popc(F & low & ~mid & ~high)
        a2 += popc(F & ~low & mid & ~high)
        a3 += popc(F & low & mid)
    return a1, a2, a3


def sq(i: int) -> int:
    return (i // 7) * 8 + i % 7


def idx(s: int) -> int:
    return (s >> 3) * 7 + (s & 7)


class PyEngine:
    def __init__(self, weights: Optional[List[int]] = None, fallback_any_empty: bool = True):
        from .engine_defaults import DEFAULT_WEIGHTS
        self.w = list(weights) if weights is not None else list(DEFAULT_WEIGHTS)
        self.fallback_any = fallback_any_empty
        self.tt: Dict[Tuple[int, int, int, int], Tuple[int, int, int, int]] = {}
        self.nodes = 0
        self.fallback_hits = 0

    # ---- rules on bitboards ---------------------------------------------
    def legal(self, b: List[int], last: int, side: int, empty: int) -> int:
        if popc(b[side]) >= CUBES_PER_PLAYER:
            return 0
        if last == NONE:
            return empty
        m = NB[last] & empty
        if m:
            return m
        m = dilate(b[side ^ 1]) & empty
        if m:
            return m
        self.fallback_hits += 1
        return empty if self.fallback_any else 0

    def replies_after(self, m: int, own_with_m: int, e2: int) -> int:
        r = NB[m] & e2
        if r:
            return r
        r = dilate(own_with_m) & e2
        if r:
            return r
        self.fallback_hits += 1
        return e2 if self.fallback_any else 0

    def evaluate(self, b, side, empty, legal, safe, wS, wO) -> int:
        own, opp = b[side], b[side ^ 1]
        a1, a2, a3 = window_counts(own, opp)
        b1, b2, b3 = window_counts(opp, own)
        w = self.w
        f12 = 0
        if w[12]:
            for m in bits(safe):
                bm = 1 << m
                if wincells(own | bm) & empty & ~bm & ~wS:
                    f12 += 1
        f = (a1, a2, a3, b1, b2, b3, popc(wS), popc(wO), popc(safe), popc(dilate(wS) & empty),
             popc(dilate(wO) & empty), popc(legal), f12, popc(wS & dilate(opp)),
             popc(wO & dilate(own)), 1)
        v = sum(x * y for x, y in zip(w, f))
        return max(-EVAL_CAP, min(EVAL_CAP, v))

    # ---- search -----------------------------------------------------------
    def _search(self, b: List[int], last: int, side: int, n: int, depth: int, alpha: int,
                beta: int, ply: int) -> Tuple[int, List[int]]:
        self.nodes += 1
        if (self.nodes & 2047) == 0 and self.deadline and time.perf_counter() > self.deadline:
            raise TimeoutError
        own, opp = b[side], b[side ^ 1]
        empty = VALID & ~(own | opp)
        canS = has_open(opp, empty, CUBES_PER_PLAYER - popc(own))
        canO = has_open(own, empty, CUBES_PER_PLAYER - popc(opp))
        if not canS and not canO:
            return 0, []
        legal = self.legal(b, last, side, empty)
        if not legal:
            return 0, []
        if not canS and alpha >= 0:
            return 0, []
        if not canO and beta <= 0:
            return 0, []
        hi, lo = MATE - (n + 1), -(MATE - (n + 2))
        if hi <= alpha:
            return hi, []
        if lo >= beta:
            return lo, []
        wS = wincells(own) & empty
        if legal & wS:
            m = (legal & wS & -(legal & wS)).bit_length() - 1
            return MATE - (n + 1), [m]
        wO = wincells(opp) & empty
        safe = legal
        if wO and popc(opp) < CUBES_PER_PLAYER:
            safe = 0
            for m in bits(legal):
                bm = 1 << m
                if not (self.replies_after(m, own | bm, empty & ~bm) & wO):
                    safe |= bm
        if not safe:
            return -(MATE - (n + 2)), [(legal & -legal).bit_length() - 1]
        if depth >= TOTAL - n:
            depth = COMPLETE
        if depth <= 0:
            v = self.evaluate(b, side, empty, legal, safe, wS, wO)
            if not canS and v > 0:
                v = 0
            if not canO and v < 0:
                v = 0
            return v, []

        key = (b[0], b[1], last, side)
        e = self.tt.get(key)
        ttm = NONE
        if e is not None:
            ed, ef, ev, em = e
            ttm = em
            cut = False
            if ed >= depth:
                cut = ef == 3 or (ef == 1 and ev >= beta) or (ef == 2 and ev <= alpha)
            else:
                cut = ((ef & 1) and ev >= MATE_BOUND and ev >= beta) or \
                      ((ef & 2) and ev <= -MATE_BOUND and ev <= alpha)
            if cut and ply > 0:
                return ev, ([em] if em != NONE else [])
            if ttm != NONE and not (safe >> ttm) & 1:
                ttm = NONE

        newdepth = COMPLETE if depth == COMPLETE else depth - 1
        k = self.killers[ply]
        hist = self.hist[side]
        scored = []
        for m in bits(safe):
            if m == ttm:
                v = 1 << 28
            else:
                v = 0
                if m == k[0]:
                    v += 1 << 22
                elif m == k[1]:
                    v += 1 << 21
                bm = 1 << m
                nw = wincells(own | bm) & empty & ~bm & ~wS
                if nw:
                    v += (1 << 23) + (popc(nw) << 16)
                if bm & wO:
                    v += 1 << 19
                v += min(hist[m], 65535)
            scored.append((v, m))
        scored.sort(reverse=True)

        alpha0 = alpha
        best, bestm, bestpv = -INF, NONE, []
        for i, (_, m) in enumerate(scored):
            nb = [b[0], b[1]]
            nb[side] |= 1 << m
            if i == 0:
                v, cpv = self._search(nb, m, side ^ 1, n + 1, newdepth, -beta, -alpha, ply + 1)
                v = -v
            else:
                v, cpv = self._search(nb, m, side ^ 1, n + 1, newdepth, -alpha - 1, -alpha, ply + 1)
                v = -v
                if alpha < v < beta:
                    v, cpv = self._search(nb, m, side ^ 1, n + 1, newdepth, -beta, -alpha, ply + 1)
                    v = -v
            if v > best:
                best, bestm = v, m
                if v > alpha:
                    alpha = v
                    bestpv = [m] + cpv
            if alpha >= beta:
                if m != k[0]:
                    k[1], k[0] = k[0], m
                hist[m] += depth * depth if depth != COMPLETE else 16
                break
        flag = 2 if best <= alpha0 else (1 if best >= beta else 3)
        old = self.tt.get(key)
        if old is None or depth >= old[0]:
            self.tt[key] = (depth, flag, best, bestm)
        return best, bestpv or ([bestm] if bestm != NONE else [])

    def think(self, st: State, time_limit: Optional[float] = None, depth: Optional[int] = None,
              soft: float = 0.45) -> dict:
        b = [0, 0]
        for i, v in enumerate(st.board):
            if v:
                b[v - 1] |= 1 << sq(i)
        last = sq(st.last) if st.last is not None else NONE
        side = st.to_move - 1
        n = st.ply
        self.nodes = 0
        self.killers = [[NONE, NONE] for _ in range(64)]
        self.hist = [[0] * 64, [0] * 64]
        t0 = time.perf_counter()
        self.deadline = t0 + time_limit if time_limit else None
        maxd = min(depth or 100, TOTAL - n)
        best = None
        its = []
        for d in range(1, max(maxd, 1) + 1):
            try:
                dl = self.deadline
                if d == 1:
                    self.deadline = None
                v, pv = self._search(b, last, side, n, d, -INF, INF, 0)
                self.deadline = dl
            except TimeoutError:
                break
            best = (v, pv, d)
            its.append((d, to_coord(idx(pv[0])) if pv else "-", v, self.nodes, time.perf_counter() - t0))
            if abs(v) >= MATE_BOUND and ((MATE - abs(v)) - n) <= d:
                break
            if time_limit and time.perf_counter() - t0 >= time_limit * soft:
                break
        v, pv, d = best
        el = time.perf_counter() - t0
        return {"move": to_coord(idx(pv[0])), "move_index": idx(pv[0]), "score": v, "depth": d,
                "pv": [to_coord(idx(s)) for s in pv], "nodes": self.nodes, "time": el,
                "nps": self.nodes / el if el > 0 else 0.0, "iterations": its}

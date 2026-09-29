/*
 * 4Mation native search core.
 *
 * Board: 7x7 cells in a 64-bit word with stride 8 (bit = row*8 + col); column 7
 * and rows 7 are always zero, which makes shift-based line detection wrap-free.
 *
 * Scores are from the side to move. A win completed when the board holds k
 * cubes scores MATE - k (absolute cube count, so TT values never need
 * ply adjustment: every move adds exactly one cube, a position is always at
 * the same distance from any root that reaches it).
 *
 * Exactness: a search whose depth is >= the remaining plies (48 - cubes) never
 * reaches the evaluation function, so its value is the game-theoretic value.
 * Mate scores (|v| >= MATE_BOUND) are always proofs, at any depth.
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if defined(_WIN32)
#define EXPORT __declspec(dllexport)
#include <windows.h>
#else
#define EXPORT __attribute__((visibility("default")))
#endif

#if defined(_MSC_VER)
#include <intrin.h>
static __inline int popcount64(uint64_t x) { return (int)__popcnt64(x); }
static __inline int ctz64(uint64_t x) { unsigned long i; _BitScanForward64(&i, x); return (int)i; }
static __inline int clz64(uint64_t x) { unsigned long i; _BitScanReverse64(&i, x); return 63 - (int)i; }
#define inline __inline
#else
#define popcount64(x) __builtin_popcountll(x)
#define ctz64(x) __builtin_ctzll(x)
#define clz64(x) __builtin_clzll(x)
#endif

typedef uint64_t u64;
typedef int64_t i64;

#define VALID 0x007F7F7F7F7F7F7FULL
#define CUBES 24
#define TOTAL_PLIES 48
#define MATE 30000
#define MATE_BOUND (MATE - 100)
#define INF 32000
#define DEPTH_COMPLETE 127
#define MAXPLY 64
#define NONE 64
#define EVAL_CAP 20000

/* ------------------------------------------------------------------ tables */
static u64 NB[65];
static u64 WINS[88];
static int NWINS = 0;
static int T[8][65];
static int TINV[8][65];
static u64 ZC[2][64], ZL[65], ZSIDE;
static int initialized = 0;

/* ------------------------------------------------------------------- rules */
static int R_fallback_any = 1; /* both dead ends: 1 = any empty cell, 0 = draw */
static int R_draw_open = 1;    /* 1 = draw when nobody has an open 4-window */

/* ----------------------------------------------------------------- options */
enum {
    OPT_TT = 0, OPT_SYM, OPT_PVS, OPT_KILLER, OPT_HISTORY, OPT_THREAT_ORDER,
    OPT_SAFE_PRUNE, OPT_EXT_FORCED, OPT_LEAF_WIN3, OPT_ASPIRATION, OPT_COUNTER,
    OPT_EVAL_ORDER, OPT_MDP, OPT_REPLY_ORDER, OPT_DEAD_PRUNE, OPT_ETC, NOPT
};
static int OPT[NOPT] = {1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0, 1, 0};

#define NFEAT 16
/* weights are x1 (integer); set from Python */
static int W[NFEAT] = {1, 8, 64, -1, -8, -64, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0};

/* ------------------------------------------------------------------- stats */
typedef struct {
    i64 nodes, tt_probes, tt_hits, tt_cuts, beta_cuts, first_cuts, interior, evals;
    i64 fallback_hits, safe_pruned, win1, loss2, win3;
} Stats;
static Stats ST;

static volatile int stop_flag = 0;
static int root_tt_cut = 0; /* the root is always expanded so its move comes from a real search */
static int reply_order_min_depth = 2;
static int sym_max_n = 48; /* canonical symmetric keys only for positions with <= this many cubes */
static i64 node_limit = 0;
static double time_limit = 0.0, t_start = 0.0;

static double now_sec(void) {
#if defined(_WIN32)
    static LARGE_INTEGER freq;
    LARGE_INTEGER c;
    if (!freq.QuadPart) QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&c);
    return (double)c.QuadPart / (double)freq.QuadPart;
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
#endif
}

/* ----------------------------------------------------------------- helpers */
static inline int popc(u64 x) { return popcount64(x); }
static inline int lsb(u64 x) { return ctz64(x); }

static inline u64 dilate(u64 x) {
    u64 h = x | (x << 1) | (x >> 1);
    return (h | (h << 8) | (h >> 8)) & VALID;
}

static inline int has_four(u64 b) {
    u64 y;
    y = b & (b >> 1); if (y & (y >> 2)) return 1;
    y = b & (b >> 8); if (y & (y >> 16)) return 1;
    y = b & (b >> 9); if (y & (y >> 18)) return 1;
    y = b & (b >> 7); if (y & (y >> 14)) return 1;
    return 0;
}

/* empty cells that would complete >=4 in a row for b */
static inline u64 wincells(u64 b) {
    u64 r = 0, p;
#define WC(s)                                                   \
    p = (b << (s)) & (b << (2 * (s)));                          \
    r |= p & (b << (3 * (s)));                                  \
    r |= p & (b >> (s));                                        \
    p = (b >> (s)) & (b >> (2 * (s)));                          \
    r |= p & (b >> (3 * (s)));                                  \
    r |= p & (b << (s));
    WC(1) WC(8) WC(9) WC(7)
#undef WC
    return r & VALID;
}

/* player with opponent cubes `opp` and `left` cubes can still fill a 4-window */
static inline int has_open(u64 opp, u64 empty, int left) {
    if (left <= 0) return 0;
    if (left >= 4) {
        u64 f = VALID & ~opp, y;
        y = f & (f >> 1); if (y & (y >> 2)) return 1;
        y = f & (f >> 8); if (y & (y >> 16)) return 1;
        y = f & (f >> 9); if (y & (y >> 18)) return 1;
        y = f & (f >> 7); if (y & (y >> 14)) return 1;
        return 0;
    }
    for (int w = 0; w < NWINS; w++)
        if (!(WINS[w] & opp) && popc(WINS[w] & empty) <= left) return 1;
    return 0;
}

/* ---------------------------------------------------------------- position */
typedef struct {
    u64 bb[2];
    int last;  /* 0..63 or NONE */
    int side;  /* 0 = X (first player), 1 = O */
    int n;     /* cubes on board */
    u64 z[8];
} Pos;

static void pos_keys(Pos *p) {
    for (int k = 0; k < 8; k++) {
        u64 z = 0;
        for (int c = 0; c < 2; c++) {
            u64 b = p->bb[c];
            while (b) { int s = lsb(b); b &= b - 1; z ^= ZC[c][T[k][s]]; }
        }
        z ^= ZL[T[k][p->last]];
        if (p->side) z ^= ZSIDE;
        p->z[k] = z;
    }
}

static inline void make(const Pos *p, int m, Pos *c) {
    int s = p->side;
    c->bb[0] = p->bb[0];
    c->bb[1] = p->bb[1];
    c->bb[s] |= 1ULL << m;
    c->last = m;
    c->side = s ^ 1;
    c->n = p->n + 1;
    int nk = (OPT[OPT_SYM] && c->n <= sym_max_n) ? 8 : 1;
    for (int k = 0; k < nk; k++)
        c->z[k] = p->z[k] ^ ZC[s][T[k][m]] ^ ZL[T[k][p->last]] ^ ZL[T[k][m]] ^ ZSIDE;
}

static inline u64 canon_key(const Pos *p, int *sym) {
    if (!OPT[OPT_SYM] || p->n > sym_max_n) { *sym = 0; return p->z[0]; }
    int best = 0;
    u64 z = p->z[0];
    for (int k = 1; k < 8; k++) if (p->z[k] < z) { z = p->z[k]; best = k; }
    *sym = best;
    return z;
}

/* legal moves; *fb set when the unspecified double-dead-end fallback is used */
static inline u64 gen_legal(const Pos *p, u64 empty, int *fb) {
    *fb = 0;
    if (popc(p->bb[p->side]) >= CUBES) return 0;
    if (p->last == NONE) return empty;
    u64 m = NB[p->last] & empty;
    if (m) return m;
    m = dilate(p->bb[p->side ^ 1]) & empty; /* Sackgasse: next to any cube of the last mover */
    if (m) return m;
    *fb = 1;
    return R_fallback_any ? empty : 0;
}

/* opponent replies after side-to-move plays m (own = mover's cubes incl. m) */
static inline u64 replies_after(int m, u64 own_with_m, u64 empty_after, int *fb) {
    *fb = 0;
    u64 r = NB[m] & empty_after;
    if (r) return r;
    r = dilate(own_with_m) & empty_after;
    if (r) return r;
    *fb = 1;
    return R_fallback_any ? empty_after : 0;
}

static inline int is_draw_by_rule(const Pos *p, u64 empty) {
    if (!R_draw_open) return 0;
    int l0 = CUBES - popc(p->bb[0]), l1 = CUBES - popc(p->bb[1]);
    return !has_open(p->bb[1], empty, l0) && !has_open(p->bb[0], empty, l1);
}

/* ------------------------------------------------------------------ TT */
typedef struct {
    u64 key;
    int16_t val;
    uint8_t depth;
    uint8_t flag; /* bits0-1: 1 lower, 2 upper, 3 exact; bits2-7 generation */
    uint8_t move; /* canonical coordinates, NONE if unknown */
    uint8_t work; /* log2 of the nodes searched below this entry */
    uint8_t pad[2];
} TTE;
#define BUCKET 4
static TTE *tt = NULL;
static u64 tt_mask = 0; /* number of buckets - 1 */
static int tt_gen = 0;
#define F_LOWER 1
#define F_UPPER 2
#define F_EXACT 3

static int tt_alloc(u64 mb) {
    u64 bytes = mb * 1024ULL * 1024ULL;
    u64 nb = 1;
    while (nb * 2 * BUCKET * sizeof(TTE) <= bytes) nb *= 2;
    free(tt);
    tt = (TTE *)calloc(nb * BUCKET, sizeof(TTE));
    if (!tt) { tt_mask = 0; return -1; }
    tt_mask = nb - 1;
    return 0;
}

static inline TTE *tt_probe(u64 key) {
    TTE *b = tt + (key & tt_mask) * BUCKET;
    for (int i = 0; i < BUCKET; i++) if (b[i].key == key && b[i].flag) return &b[i];
    return NULL;
}

static inline void tt_store(u64 key, int val, int depth, int flag, int move, int work) {
    TTE *b = tt + (key & tt_mask) * BUCKET;
    TTE *rep = NULL;
    int worst = 1 << 30;
    if (work > 63) work = 63;
    for (int i = 0; i < BUCKET; i++) {
        if (b[i].key == key && b[i].flag) {
            /* same position: never replace a deeper result (in particular an exact
             * DEPTH_COMPLETE one) by a shallower one. The stored move must stay the
             * move that established the stored value (it is returned as the PV on a
             * TT cutoff), so a shallower search must not overwrite it. */
            if (depth < b[i].depth && !(flag == F_EXACT && b[i].depth != DEPTH_COMPLETE &&
                                        depth + 2 >= b[i].depth)) {
                return;
            }
            rep = &b[i];
            break;
        }
        /* replacement priority: search effort, depth, age */
        int age = (tt_gen - (b[i].flag >> 2)) & 63;
        int d = b[i].depth > 40 ? 40 : b[i].depth;
        int score = b[i].flag ? (2 * b[i].work + d - 4 * age) : -1000;
        if (score < worst) { worst = score; rep = &b[i]; }
    }
    if (move == NONE && rep->key == key) move = rep->move;
    rep->key = key;
    rep->val = (int16_t)val;
    rep->depth = (uint8_t)depth;
    rep->flag = (uint8_t)(flag | (tt_gen << 2));
    rep->move = (uint8_t)move;
    rep->work = (uint8_t)work;
}

static inline int ilog2(i64 x) { return x <= 1 ? 0 : 63 - clz64((u64)x); }

/* ---------------------------------------------------------------- ordering */
static int killer[MAXPLY][2];
static int hist[2][64];
static int counter[2][65];

/* ---------------------------------------------------------------- eval */
static const u64 WSTART[4] = {0x000F0F0F0F0F0F0FULL, 0x000000007F7F7F7FULL,
                              0x000000000F0F0F0FULL, 0x0000000078787878ULL};
static const int WDIR[4] = {1, 8, 9, 7};

static inline void window_counts(u64 own, u64 opp, int *c1, int *c2, int *c3) {
    int a1 = 0, a2 = 0, a3 = 0;
    for (int d = 0; d < 4; d++) {
        int s = WDIR[d];
        u64 o0 = own, o1 = own >> s, o2 = own >> (2 * s), o3 = own >> (3 * s);
        u64 blk = opp | (opp >> s) | (opp >> (2 * s)) | (opp >> (3 * s));
        u64 F = WSTART[d] & ~blk;
        u64 a = o0 ^ o1, ca = o0 & o1, b = o2 ^ o3, cb = o2 & o3;
        u64 low = a ^ b, c = a & b;
        u64 mid = ca ^ cb ^ c;
        u64 high = (ca & cb) | (c & (ca ^ cb));
        a1 += popc(F & low & ~mid & ~high);
        a2 += popc(F & ~low & mid & ~high);
        a3 += popc(F & low & mid);
    }
    *c1 = a1; *c2 = a2; *c3 = a3;
}

static int eval_fast = 0;
/* features from the side to move; called only at non-terminal nodes where the
 * side to move has no immediate win and at least one safe move */
static void features(const Pos *p, u64 empty, u64 legal, u64 safe, u64 wS, u64 wO, int *f) {
    int S = p->side;
    u64 own = p->bb[S], opp = p->bb[S ^ 1];
    int a1, a2, a3, b1, b2, b3;
    window_counts(own, opp, &a1, &a2, &a3);
    window_counts(opp, own, &b1, &b2, &b3);
    f[0] = a1; f[1] = a2; f[2] = a3;
    f[3] = b1; f[4] = b2; f[5] = b3;
    f[6] = popc(wS);
    f[7] = popc(wO);
    f[8] = popc(safe);
    f[9] = popc(dilate(wS) & empty);  /* cells the opponent cannot safely use */
    f[10] = popc(dilate(wO) & empty); /* cells we cannot safely use */
    f[11] = popc(legal);
    /* safe moves that create a new threat cell (skipped when unweighted) */
    int tm = 0;
    u64 s = W[12] || !eval_fast ? safe : 0;
    while (s) {
        int m = lsb(s); s &= s - 1;
        u64 nw = wincells(own | (1ULL << m)) & empty & ~(1ULL << m) & ~wS;
        if (nw) tm++;
    }
    f[12] = tm;
    /* threat cells of each side that the other side's cubes touch (dead-end access) */
    f[13] = popc(wS & dilate(opp));
    f[14] = popc(wO & dilate(own));
    f[15] = 1; /* tempo / bias */
}

static inline int evaluate(const Pos *p, u64 empty, u64 legal, u64 safe, u64 wS, u64 wO) {
    int f[NFEAT];
    eval_fast = 1;
    features(p, empty, legal, safe, wS, wO, f);
    eval_fast = 0;
    int v = 0;
    for (int i = 0; i < NFEAT; i++) v += W[i] * f[i];
    if (v > EVAL_CAP) v = EVAL_CAP;
    if (v < -EVAL_CAP) v = -EVAL_CAP;
    return v;
}

/* ---------------------------------------------------------------- search */
static int pv_table[MAXPLY][MAXPLY];
static int pv_len[MAXPLY];

static inline int is_mate(int v) { return v >= MATE_BOUND || v <= -MATE_BOUND; }

/* safe moves: those after which the opponent has no immediate win */
static inline u64 safe_moves(const Pos *p, u64 empty, u64 legal, u64 wO) {
    int S = p->side;
    if (!wO) return legal;
    if (CUBES - popc(p->bb[S ^ 1]) <= 0) return legal;
    u64 safe = 0, l = legal;
    while (l) {
        int m = lsb(l); l &= l - 1;
        u64 bm = 1ULL << m;
        u64 e2 = empty & ~bm;
        int fb;
        u64 r = replies_after(m, p->bb[S] | bm, e2, &fb);
        if (fb) ST.fallback_hits++;
        if (!(r & wO)) safe |= bm;
    }
    return safe;
}

/* does side to move have a move after which the opponent has no safe reply
 * (and no immediate win)?  returns the move or -1.  exact "win in 3" test. */
static int find_win3(const Pos *p, u64 empty, u64 safe, u64 wS) {
    int S = p->side, O = S ^ 1;
    u64 own = p->bb[S], opp = p->bb[O];
    if (CUBES - popc(own) < 2) return -1; /* need two more cubes */
    if (CUBES - popc(opp) < 1) return -1; /* opponent cannot move: game ends drawn */
    if (p->n + 3 > TOTAL_PLIES) return -1;
    u64 wO = wincells(opp) & empty;
    u64 s = safe;
    while (s) {
        int m = lsb(s); s &= s - 1;
        u64 bm = 1ULL << m, e2 = empty & ~bm, own2 = own | bm;
        u64 w2 = wincells(own2) & e2;
        if (!w2) continue;
        int fb;
        u64 R = replies_after(m, own2, e2, &fb);
        if (fb) ST.fallback_hits++;
        if (!R) continue; /* game ends (draw fallback) */
        if (R & wO) continue; /* opponent wins at once (not possible for safe m) */
        /* draw by rule after m? the opponent has an open line only if ... check */
        int all_bad = 1;
        u64 rr = R;
        while (rr) {
            int r = lsb(rr); rr &= rr - 1;
            u64 br = 1ULL << r, e3 = e2 & ~br;
            u64 w3 = w2 & ~br;
            if (!w3) { all_bad = 0; break; }
            u64 M = replies_after(r, opp | br, e3, &fb);
            if (fb) ST.fallback_hits++;
            if (!(M & w3)) { all_bad = 0; break; }
        }
        if (all_bad) return m;
    }
    return -1;
}

static int search(const Pos *p, int depth, int alpha, int beta, int ply) {
    i64 nodes0 = ST.nodes;
    ST.nodes++;
    pv_len[ply] = 0;
    if ((ST.nodes & 1023) == 0) {
        if ((node_limit > 0 && ST.nodes >= node_limit) ||
            (time_limit > 0 && now_sec() - t_start >= time_limit))
            stop_flag = 1;
    }
    if (stop_flag) return 0;

    u64 occ = p->bb[0] | p->bb[1];
    u64 empty = VALID & ~occ;
    int n = p->n, S = p->side;
    /* can each side still complete a 4-window at all? (cubes are never removed) */
    int canS = has_open(p->bb[S ^ 1], empty, CUBES - popc(p->bb[S]));
    int canO = has_open(p->bb[S], empty, CUBES - popc(p->bb[S ^ 1]));
    if (!canS && !canO) return 0; /* draw (by rule, or inevitably under "exhaustion") */
    int fb;
    u64 legal = gen_legal(p, empty, &fb);
    if (fb) ST.fallback_hits++;
    if (!legal) return 0;
    if (OPT[OPT_DEAD_PRUNE]) {
        /* one side can never win: value is <= 0 (resp. >= 0) */
        if (!canS && alpha >= 0) return 0;
        if (!canO && beta <= 0) return 0;
    }

    /* mate distance pruning */
    if (OPT[OPT_MDP]) {
        int hi = MATE - (n + 1), lo = -(MATE - (n + 2));
        if (hi <= alpha) return hi;
        if (lo >= beta) return lo;
    }
    u64 wS = wincells(p->bb[S]) & empty;
    if (legal & wS) {
        ST.win1++;
        pv_table[ply][0] = lsb(legal & wS);
        pv_len[ply] = 1;
        return MATE - (n + 1);
    }
    u64 wO = wincells(p->bb[S ^ 1]) & empty;
    u64 safe = OPT[OPT_SAFE_PRUNE] ? safe_moves(p, empty, legal, wO) : legal;
    if (!safe) {
        ST.loss2++;
        pv_table[ply][0] = lsb(legal);
        pv_len[ply] = 1;
        return -(MATE - (n + 2));
    }
    ST.safe_pruned += popc(legal) - popc(safe);

    int remaining = TOTAL_PLIES - n;
    if (depth >= remaining) depth = DEPTH_COMPLETE; /* can never reach a leaf: exact */

    if (depth <= 0) {
        if (OPT[OPT_LEAF_WIN3]) {
            int m3 = find_win3(p, empty, safe, wS);
            if (m3 >= 0) {
                ST.win3++;
                pv_table[ply][0] = m3;
                pv_len[ply] = 1;
                return MATE - (n + 3);
            }
        }
        ST.evals++;
        int ev = evaluate(p, empty, legal, safe, wS, wO);
        if (!canS && ev > 0) ev = 0; /* we can never win */
        if (!canO && ev < 0) ev = 0; /* we can never lose */
        return ev;
    }

    /* transposition table */
    int sym = 0, ttm = NONE;
    u64 key = 0;
    if (OPT[OPT_TT]) {
        key = canon_key(p, &sym);
        ST.tt_probes++;
        TTE *e = tt_probe(key);
        if (e) {
            ST.tt_hits++;
            int v = e->val, fl = e->flag & 3;
            if (e->move != NONE) ttm = TINV[sym][e->move];
            int cut = 0;
            if (e->depth >= depth) {
                cut = fl == F_EXACT || (fl == F_LOWER && v >= beta) || (fl == F_UPPER && v <= alpha);
            } else {
                /* shallower entry: a mate score is still a proof, but only in its
                 * own direction (a win is a lower bound, a loss an upper bound) */
                cut = ((fl & F_LOWER) && v >= MATE_BOUND && v >= beta) ||
                      ((fl & F_UPPER) && v <= -MATE_BOUND && v <= alpha);
            }
            if (cut && (ply > 0 || root_tt_cut)) {
                ST.tt_cuts++;
                if (ttm != NONE && ((safe >> ttm) & 1)) { pv_table[ply][0] = ttm; pv_len[ply] = 1; }
                return v;
            }
            if (ttm != NONE && !((safe >> ttm) & 1)) ttm = NONE;
        }
    }

    ST.interior++;

    /* forced-move extension */
    int newdepth = depth - 1;
    if (depth != DEPTH_COMPLETE) {
        if (OPT[OPT_EXT_FORCED] && popc(safe) == 1 && ply < 2 * MAXPLY / 3) newdepth = depth;
    } else {
        newdepth = DEPTH_COMPLETE;
    }

    /* order moves */
    int moves[64], sc[64], nm = 0;
    u64 s = safe;
    u64 own = p->bb[S], opp_bb = p->bb[S ^ 1];
    int cm = OPT[OPT_COUNTER] ? counter[S][p->last] : NONE;
    while (s) {
        int m = lsb(s); s &= s - 1;
        int v = 0;
        if (m == ttm) v = 1 << 28;
        else {
            if (OPT[OPT_KILLER]) {
                if (m == killer[ply][0]) v += 1 << 22;
                else if (m == killer[ply][1]) v += 1 << 21;
            }
            if (OPT[OPT_COUNTER] && m == cm) v += 1 << 20;
            if (OPT[OPT_THREAT_ORDER]) {
                u64 bm = 1ULL << m;
                u64 nw = wincells(own | bm) & empty & ~bm & ~wS;
                if (nw) v += (1 << 23) + (popc(nw) << 16);
                if (bm & wO) v += 1 << 19; /* blocks an opponent threat cell */
            }
            if (OPT[OPT_HISTORY]) v += hist[S][m] > ((1 << 16) - 1) ? ((1 << 16) - 1) : hist[S][m];
            if (OPT[OPT_REPLY_ORDER] && depth >= reply_order_min_depth) {
                /* prefer moves that leave the opponent few safe replies */
                u64 bm = 1ULL << m, e2 = empty & ~bm, own2 = own | bm;
                u64 w2 = wincells(own2) & e2;
                int fb2;
                u64 R = replies_after(m, own2, e2, &fb2);
                int safeR = 0;
                u64 rr = R;
                while (rr) {
                    int r = lsb(rr); rr &= rr - 1;
                    u64 br = 1ULL << r, w3 = w2 & ~br;
                    if (!w3) { safeR++; continue; }
                    u64 M = replies_after(r, opp_bb | br, e2 & ~br, &fb2);
                    if (!(M & w3)) safeR++;
                }
                if (R && !safeR && CUBES - popc(opp_bb) >= 1 && CUBES - popc(own) >= 2) v += 1 << 27; /* win in 3 */
                v += (16 - (safeR > 16 ? 16 : safeR)) << 12;
            }
        }
        moves[nm] = m;
        sc[nm] = v;
        nm++;
    }
    /* insertion sort by score desc */
    for (int i = 1; i < nm; i++) {
        int mv = moves[i], v = sc[i], j = i - 1;
        while (j >= 0 && sc[j] < v) { moves[j + 1] = moves[j]; sc[j + 1] = sc[j]; j--; }
        moves[j + 1] = mv; sc[j + 1] = v;
    }

    int alpha0 = alpha, best = -INF, bestm = NONE;
    Pos c;
    if (OPT[OPT_ETC] && OPT[OPT_TT] && depth >= 2) {
        /* enhanced transposition cutoff: a child already known to refute */
        for (int i = 0; i < nm; i++) {
            make(p, moves[i], &c);
            int cs;
            u64 ck = canon_key(&c, &cs);
            TTE *e = tt_probe(ck);
            if (!e) continue;
            int cv = e->val, cf = e->flag & 3;
            int usable = e->depth >= newdepth || (cv <= -MATE_BOUND);
            if (usable && (cf & F_UPPER) && -cv >= beta) {
                ST.tt_cuts++;
                pv_table[ply][0] = moves[i];
                pv_len[ply] = 1;
                return -cv;
            }
        }
    }
    for (int i = 0; i < nm; i++) {
        int m = moves[i];
        make(p, m, &c);
        int v;
        if (i == 0 || !OPT[OPT_PVS]) {
            v = -search(&c, newdepth, -beta, -alpha, ply + 1);
        } else {
            v = -search(&c, newdepth, -alpha - 1, -alpha, ply + 1);
            if (!stop_flag && v > alpha && v < beta) v = -search(&c, newdepth, -beta, -alpha, ply + 1);
        }
        if (stop_flag) return 0;
        if (v > best) {
            best = v;
            bestm = m;
            if (v > alpha) {
                alpha = v;
                pv_table[ply][0] = m;
                int l = pv_len[ply + 1];
                if (l > MAXPLY - ply - 2) l = MAXPLY - ply - 2;
                memcpy(&pv_table[ply][1], pv_table[ply + 1], sizeof(int) * l);
                pv_len[ply] = l + 1;
            }
        }
        if (alpha >= beta) {
            ST.beta_cuts++;
            if (i == 0) ST.first_cuts++;
            if (OPT[OPT_KILLER] && m != killer[ply][0]) { killer[ply][1] = killer[ply][0]; killer[ply][0] = m; }
            if (OPT[OPT_HISTORY]) {
                hist[S][m] += depth != DEPTH_COMPLETE ? depth * depth : 16;
                if (hist[S][m] > (1 << 20))
                    for (int a = 0; a < 2; a++) for (int q = 0; q < 64; q++) hist[a][q] >>= 1;
            }
            if (OPT[OPT_COUNTER]) counter[S][p->last] = m;
            break;
        }
    }

    if (OPT[OPT_TT]) {
        int fl = best <= alpha0 ? F_UPPER : (best >= beta ? F_LOWER : F_EXACT);
        tt_store(key, best, depth, fl, bestm == NONE ? NONE : T[sym][bestm], ilog2(ST.nodes - nodes0));
    }
    return best;
}

/* ----------------------------------------------------------- public API */
typedef struct {
    int best_move;   /* stride-8 square or -1 */
    int score;
    int depth;       /* last completed depth (DEPTH_COMPLETE if exact) */
    int complete;    /* 1 if value is game-theoretic (no heuristic leaf influence) */
    int aborted;     /* 1 if stopped before completing the requested work */
    int pv_len;
    int pv[MAXPLY];
    i64 nodes, tt_probes, tt_hits, tt_cuts, beta_cuts, first_cuts, interior, evals;
    i64 fallback_hits, safe_pruned, win1, loss2, win3;
    double elapsed;
    int iters;
    int it_depth[MAXPLY], it_move[MAXPLY], it_score[MAXPLY];
    i64 it_nodes[MAXPLY];
    double it_time[MAXPLY];
} Result;

static u64 splitmix(u64 *s) {
    u64 z = (*s += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static void init_tables(void) {
    if (initialized) return;
    for (int s = 0; s < 65; s++) NB[s] = 0;
    for (int r = 0; r < 7; r++)
        for (int c = 0; c < 7; c++) {
            u64 m = 0;
            for (int dr = -1; dr <= 1; dr++)
                for (int dc = -1; dc <= 1; dc++) {
                    if (!dr && !dc) continue;
                    int rr = r + dr, cc = c + dc;
                    if (rr >= 0 && rr < 7 && cc >= 0 && cc < 7) m |= 1ULL << (rr * 8 + cc);
                }
            NB[r * 8 + c] = m;
        }
    int dirs[4][2] = {{0, 1}, {1, 0}, {1, 1}, {1, -1}};
    NWINS = 0;
    for (int d = 0; d < 4; d++)
        for (int r = 0; r < 7; r++)
            for (int c = 0; c < 7; c++) {
                int er = r + 3 * dirs[d][0], ec = c + 3 * dirs[d][1];
                if (er < 0 || er >= 7 || ec < 0 || ec >= 7) continue;
                u64 m = 0;
                for (int k = 0; k < 4; k++) m |= 1ULL << ((r + k * dirs[d][0]) * 8 + c + k * dirs[d][1]);
                WINS[NWINS++] = m;
            }
    /* symmetries: k%4 rotations (r,c)->(c,6-r), k>=4 then mirror c->6-c (same as rules.py) */
    for (int k = 0; k < 8; k++) {
        for (int s = 0; s < 65; s++) T[k][s] = NONE;
        for (int r = 0; r < 7; r++)
            for (int c = 0; c < 7; c++) {
                int rr = r, cc = c;
                for (int i = 0; i < k % 4; i++) { int t = rr; rr = cc; cc = 6 - t; }
                if (k >= 4) cc = 6 - cc;
                T[k][r * 8 + c] = rr * 8 + cc;
            }
        for (int s = 0; s < 65; s++) TINV[k][s] = NONE;
        for (int s = 0; s < 64; s++) if (T[k][s] != NONE) TINV[k][T[k][s]] = s;
        TINV[k][NONE] = NONE;
        T[k][NONE] = NONE;
    }
    u64 seed = 0x4D4154494F4E3431ULL;
    for (int c = 0; c < 2; c++) for (int s = 0; s < 64; s++) ZC[c][s] = splitmix(&seed);
    for (int s = 0; s < 65; s++) ZL[s] = splitmix(&seed);
    ZSIDE = splitmix(&seed);
    if (!tt) tt_alloc(64);
    initialized = 1;
}

static int load_pos(Pos *p, u64 b0, u64 b1, int last, int side) {
    p->bb[0] = b0 & VALID;
    p->bb[1] = b1 & VALID;
    p->last = (last < 0 || last >= 64) ? NONE : last;
    p->side = side & 1;
    p->n = popc(p->bb[0]) + popc(p->bb[1]);
    pos_keys(p);
    return 0;
}

static void clear_stats(void) { memset(&ST, 0, sizeof(ST)); }

static void copy_stats(Result *r) {
    r->nodes = ST.nodes; r->tt_probes = ST.tt_probes; r->tt_hits = ST.tt_hits;
    r->tt_cuts = ST.tt_cuts; r->beta_cuts = ST.beta_cuts; r->first_cuts = ST.first_cuts;
    r->interior = ST.interior; r->evals = ST.evals; r->fallback_hits = ST.fallback_hits;
    r->safe_pruned = ST.safe_pruned; r->win1 = ST.win1; r->loss2 = ST.loss2; r->win3 = ST.win3;
}

static void reset_heuristics(void) {
    for (int i = 0; i < MAXPLY; i++) killer[i][0] = killer[i][1] = NONE;
    memset(hist, 0, sizeof(hist));
    for (int s = 0; s < 2; s++) for (int i = 0; i < 65; i++) counter[s][i] = NONE;
}

EXPORT int fm_init(int tt_mb) {
    init_tables();
    if (tt_mb > 0) return tt_alloc((u64)tt_mb);
    return 0;
}

EXPORT void fm_tt_clear(void) {
    init_tables();
    memset(tt, 0, (tt_mask + 1) * BUCKET * sizeof(TTE));
    tt_gen = 0;
}

EXPORT void fm_set_rules(int fallback_any_empty, int draw_open_line) {
    R_fallback_any = fallback_any_empty ? 1 : 0;
    R_draw_open = draw_open_line ? 1 : 0;
}

EXPORT int fm_set_option(int id, int value) {
    if (id < 0 || id >= NOPT) return -1;
    OPT[id] = value;
    return 0;
}
EXPORT void fm_set_reply_order_min_depth(int d) { reply_order_min_depth = d; }
EXPORT void fm_set_sym_max_n(int n) { sym_max_n = n; }
EXPORT int fm_get_option(int id) { return (id < 0 || id >= NOPT) ? -1 : OPT[id]; }

EXPORT int fm_set_weights(const int *w, int n) {
    if (n > NFEAT) n = NFEAT;
    for (int i = 0; i < n; i++) W[i] = w[i];
    return NFEAT;
}
EXPORT int fm_num_features(void) { return NFEAT; }

EXPORT u64 fm_legal(u64 b0, u64 b1, int last, int side) {
    init_tables();
    Pos p; load_pos(&p, b0, b1, last, side);
    u64 empty = VALID & ~(p.bb[0] | p.bb[1]);
    int fb;
    return gen_legal(&p, empty, &fb);
}

/* status of a position: 0 ongoing, 1 X won, 2 O won, 3 draw (by rule or no moves) */
EXPORT int fm_status(u64 b0, u64 b1, int last, int side) {
    init_tables();
    Pos p; load_pos(&p, b0, b1, last, side);
    if (has_four(p.bb[0])) return 1;
    if (has_four(p.bb[1])) return 2;
    u64 empty = VALID & ~(p.bb[0] | p.bb[1]);
    if (is_draw_by_rule(&p, empty)) return 3;
    int fb;
    if (!gen_legal(&p, empty, &fb)) return 3;
    return 0;
}

static i64 perft_rec(const Pos *p, int depth) {
    u64 empty = VALID & ~(p->bb[0] | p->bb[1]);
    if (is_draw_by_rule(p, empty)) return 1;
    int fb;
    u64 legal = gen_legal(p, empty, &fb);
    if (!legal) return 1;
    if (depth == 0) return 1;
    i64 cnt = 0;
    Pos c;
    while (legal) {
        int m = lsb(legal); legal &= legal - 1;
        make(p, m, &c);
        if (has_four(c.bb[p->side])) cnt += 1; /* terminal: counts as a leaf */
        else cnt += perft_rec(&c, depth - 1);
    }
    return cnt;
}

/* number of leaf sequences of length <= depth (terminal positions end a sequence early) */
EXPORT i64 fm_perft(u64 b0, u64 b1, int last, int side, int depth) {
    init_tables();
    Pos p; load_pos(&p, b0, b1, last, side);
    return perft_rec(&p, depth);
}

EXPORT int fm_features(u64 b0, u64 b1, int last, int side, int *out) {
    init_tables();
    Pos p; load_pos(&p, b0, b1, last, side);
    u64 empty = VALID & ~(p.bb[0] | p.bb[1]);
    int fb;
    u64 legal = gen_legal(&p, empty, &fb);
    u64 wS = wincells(p.bb[p.side]) & empty, wO = wincells(p.bb[p.side ^ 1]) & empty;
    u64 safe = safe_moves(&p, empty, legal, wO);
    features(&p, empty, legal, safe, wS, wO, out);
    /* flags for the caller: out[NFEAT] = tactical state */
    out[NFEAT] = (legal & wS) ? 1 : (!safe ? -1 : 0);
    return NFEAT;
}

EXPORT int fm_eval(u64 b0, u64 b1, int last, int side) {
    init_tables();
    Pos p; load_pos(&p, b0, b1, last, side);
    u64 empty = VALID & ~(p.bb[0] | p.bb[1]);
    int fb;
    u64 legal = gen_legal(&p, empty, &fb);
    u64 wS = wincells(p.bb[p.side]) & empty, wO = wincells(p.bb[p.side ^ 1]) & empty;
    u64 safe = safe_moves(&p, empty, legal, wO);
    return evaluate(&p, empty, legal, safe, wS, wO);
}

/* one search of fixed depth and window (no iterative deepening).
 * depth >= 100 means "to the end" (exact solve). */
EXPORT int fm_search(u64 b0, u64 b1, int last, int side, int depth, int alpha, int beta,
              double tlimit, i64 nlimit, int keep_heuristics, Result *res) {
    init_tables();
    Pos p; load_pos(&p, b0, b1, last, side);
    clear_stats();
    if (!keep_heuristics) reset_heuristics();
    stop_flag = 0;
    node_limit = nlimit;
    time_limit = tlimit;
    t_start = now_sec();
    if (depth >= 100) depth = DEPTH_COMPLETE;
    int v = search(&p, depth, alpha, beta, 0);
    memset(res, 0, sizeof(*res));
    res->aborted = stop_flag;
    res->score = v;
    res->elapsed = now_sec() - t_start;
    int remaining = TOTAL_PLIES - p.n;
    res->complete = !stop_flag && (depth >= remaining || depth == DEPTH_COMPLETE || is_mate(v));
    res->depth = depth;
    res->pv_len = stop_flag ? 0 : pv_len[0];
    for (int i = 0; i < res->pv_len; i++) res->pv[i] = pv_table[0][i];
    res->best_move = res->pv_len ? res->pv[0] : -1;
    copy_stats(res);
    stop_flag = 0;
    return v;
}

/* iterative deepening with aspiration windows. Returns score. */
EXPORT int fm_think(u64 b0, u64 b1, int last, int side, int max_depth, double tlimit, i64 nlimit,
             double soft_frac, Result *res) {
    init_tables();
    Pos p; load_pos(&p, b0, b1, last, side);
    clear_stats();
    reset_heuristics();
    memset(res, 0, sizeof(*res));
    stop_flag = 0;
    node_limit = nlimit;
    time_limit = tlimit;
    t_start = now_sec();
    tt_gen = (tt_gen + 1) & 63;
    int remaining = TOTAL_PLIES - p.n;
    int best_move = -1, best_score = 0, done_depth = 0;
    int prev = 0;
    res->best_move = -1;
    if (max_depth > remaining) max_depth = remaining;
    if (max_depth < 1) max_depth = 1;
    root_tt_cut = 0;
    for (int d = 1; d <= max_depth; d++) {
        int v;
        int a = -INF, b = INF;
        if (OPT[OPT_ASPIRATION] && d >= 4 && !is_mate(prev)) { a = prev - 40; b = prev + 40; }
        /* depth 1 always completes so there is always a move */
        i64 sv_n = node_limit; double sv_t = time_limit;
        if (d == 1) { node_limit = 0; time_limit = 0; }
        for (;;) {
            v = search(&p, d, a, b, 0);
            if (stop_flag) break;
            if (v <= a && a > -INF) { a = -INF; continue; }
            if (v >= b && b < INF) { b = INF; continue; }
            break;
        }
        if (d == 1) { node_limit = sv_n; time_limit = sv_t; }
        if (stop_flag) {
            /* partial iteration: trust its move only if it already proved better */
            break;
        }
        prev = v;
        best_score = v;
        done_depth = d;
        if (pv_len[0] > 0) {
            best_move = pv_table[0][0];
            res->pv_len = pv_len[0];
            for (int i = 0; i < pv_len[0]; i++) res->pv[i] = pv_table[0][i];
        }
        int k = res->iters < MAXPLY ? res->iters : MAXPLY - 1;
        res->it_depth[k] = d; res->it_move[k] = best_move; res->it_score[k] = v;
        res->it_nodes[k] = ST.nodes; res->it_time[k] = now_sec() - t_start;
        res->iters = k + 1;
        if (d >= remaining) break; /* exact */
        if (is_mate(v)) {
            /* a mate within the horizon is exact (distance included) */
            int dist = v > 0 ? (MATE - v) - p.n : (MATE + v) - p.n;
            if (dist <= d) break;
        }
        if (tlimit > 0 && soft_frac > 0 && now_sec() - t_start >= tlimit * soft_frac) break;
    }
    root_tt_cut = 0;
    res->aborted = stop_flag && done_depth < max_depth;
    res->best_move = best_move;
    res->score = best_score;
    res->depth = done_depth;
    res->complete = done_depth >= remaining || is_mate(best_score);
    res->elapsed = now_sec() - t_start;
    copy_stats(res);
    stop_flag = 0;
    return best_score;
}

EXPORT void fm_new_generation(void) { tt_gen = (tt_gen + 1) & 63; }

EXPORT int fm_version(void) { return 2; }

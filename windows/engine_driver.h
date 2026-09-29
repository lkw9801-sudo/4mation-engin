/*
 * Move selection for the Windows app: a C port of fourmation.engine.Engine.play
 * (book -> time-boxed exact solve -> iterative deepening) plus two weaker,
 * slightly randomised levels. Included by 4mation_gui.c and by the Linux test
 * harness test_driver.c, together with the search core itself.
 */
#include "../fourmation/native/core.c"
#include "book_data.h"

/* evaluation weights = fourmation/engine_defaults.py DEFAULT_WEIGHTS */
static const int TUNED_W[16] = {14, 34, 24, -13, -35, -45, -16, -4, 7, 22, -16, 3, 44, 27, 5, 11};

enum { K_HEUR = 0, K_WIN = 1, K_DRAW = 2, K_LOSS = 3 };
enum { LVL_EASY = 0, LVL_NORMAL = 1, LVL_STRONG = 2, LVL_MAX = 3, LVL_COUNT = 4 };

typedef struct {
    int move;      /* stride-8 square */
    int kind;      /* K_* : what the engine knows about the position it moved from */
    int dist;      /* plies to the end if known (0 otherwise) */
    int score;     /* heuristic score when kind == K_HEUR */
    int depth;     /* iterative-deepening depth reached */
    int from_book;
} Choice;

static volatile int g_cancel = 0;   /* set by the UI to abandon a search */
static double g_time_scale = 1.0;   /* test harness shortens thinking times */

static double level_time(int level) {
    return (level == LVL_STRONG ? 1.0 : level == LVL_MAX ? 5.0 : 0.0) * g_time_scale;
}

static void heuristic_opts(void) {
    OPT[OPT_REPLY_ORDER] = 0; OPT[OPT_KILLER] = 1; OPT[OPT_HISTORY] = 1; OPT[OPT_COUNTER] = 1;
}
static void solver_opts(void) { /* engine_defaults.py DEFAULT_SOLVER_OPTIONS */
    OPT[OPT_REPLY_ORDER] = 1; OPT[OPT_KILLER] = 0; OPT[OPT_HISTORY] = 0; OPT[OPT_COUNTER] = 0;
}

static int book_lookup(u64 b0, u64 b1, int last) {
    int lo = 0, hi = BOOK_N - 1;
    if (last < 0 || last > 64) last = 64;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;
        const BookEntry *e = &BOOK[mid];
        int c = e->b0 < b0 ? -1 : e->b0 > b0 ? 1 : e->b1 < b1 ? -1 : e->b1 > b1 ? 1 :
                (int)e->last - last;
        if (c == 0) return e->move;
        if (c < 0) lo = mid + 1; else hi = mid - 1;
    }
    return -1;
}

static unsigned xrand(unsigned *s) {
    unsigned x = *s ? *s : 2463534242u;
    x ^= x << 13; x ^= x >> 17; x ^= x << 5;
    return *s = x;
}

/* position after `m`; *won is set if the move completes four in a row */
static void child_of(u64 b0, u64 b1, int side, int m, u64 *c0, u64 *c1, int *won) {
    *c0 = b0; *c1 = b1;
    if (side == 0) *c0 |= 1ULL << m; else *c1 |= 1ULL << m;
    *won = has_four(side == 0 ? *c0 : *c1);
}

/* levels 0/1: shallow full-window search of every move, random pick among the
 * near-best; takes immediate wins and avoids moves that lose by force */
static Choice weak_choice(u64 b0, u64 b1, int last, int side, int level, unsigned *rng) {
    Choice c = {-1, K_HEUR, 0, 0, 0, 0};
    int depth = level == LVL_EASY ? 2 : 6, margin = level == LVL_EASY ? 160 : 40;
    int fb, moves[64], vals[64], nm = 0, best = -INF;
    Pos p; load_pos(&p, b0, b1, last, side);
    u64 legal = gen_legal(&p, VALID & ~(b0 | b1), &fb);
    heuristic_opts();
    while (legal && !g_cancel) {
        int m = lsb(legal); legal &= legal - 1;
        u64 c0, c1; int won;
        child_of(b0, b1, side, m, &c0, &c1, &won);
        int v;
        if (won) v = MATE;
        else {
            Result r;
            v = -fm_search(c0, c1, m, side ^ 1, depth - 1, -INF, INF, 0.0, 0, 0, &r);
        }
        moves[nm] = m; vals[nm] = v; nm++;
        if (v > best) best = v;
    }
    if (!nm) return c;
    int cand[64], nc = 0;
    for (int i = 0; i < nm; i++) {
        if (best >= MATE_BOUND && vals[i] < best) continue;           /* forced win: take it */
        if (vals[i] <= -MATE_BOUND && best > -MATE_BOUND) continue;   /* never walk into a forced loss */
        if (vals[i] >= best - margin) cand[nc++] = i;
    }
    int k = nc ? cand[xrand(rng) % nc] : 0;
    c.move = moves[k];
    c.score = vals[k];
    c.depth = depth;
    if (vals[k] >= MATE_BOUND) c.kind = K_WIN;
    else if (vals[k] <= -MATE_BOUND) c.kind = K_LOSS;
    return c;
}

static Choice engine_choose(u64 b0, u64 b1, int last, int side, int level, unsigned *rng) {
    Choice c = {-1, K_HEUR, 0, 0, 0, 0};
    init_tables();
    fm_set_weights(TUNED_W, 16);
    fm_set_rules(1, 1);
    if (level < LVL_STRONG) return weak_choice(b0, b1, last, side, level, rng);

    int n = popc(b0) + popc(b1);
    if (side == 0) {
        int m = book_lookup(b0, b1, last);
        if (m >= 0) { c.move = m; c.kind = K_WIN; c.from_book = 1; return c; }
    }
    double T = level_time(level), t0 = now_sec();
    Result r;
    solver_opts();
    fm_new_generation();
    fm_search(b0, b1, last, side, 100, -1, 1, T * 0.5, 0, 1, &r);
    int solved = !r.aborted && !g_cancel;
    int solved_score = r.score;
    if (solved && r.score >= 0 && r.pv_len > 0) {
        /* defensive check that the move keeps the proven result (Engine._keeps) */
        int m = r.pv[0], ok, won;
        u64 c0, c1;
        child_of(b0, b1, side, m, &c0, &c1, &won);
        if (won) ok = 1;
        else {
            Result rc;
            double left = T - (now_sec() - t0);
            fm_search(c0, c1, m, side ^ 1, 100, -1, 1, left > 0.005 ? left : 0.005, 0, 1, &rc);
            ok = rc.aborted || (r.score > 0 ? rc.score < 0 : rc.score == 0);
        }
        if (ok) {
            c.move = m;
            c.kind = r.score > 0 ? K_WIN : K_DRAW;
            return c;
        }
    }
    if (g_cancel) return c;
    heuristic_opts();
    double left = T - (now_sec() - t0);
    if (left < 0.05) left = 0.05;
    fm_think(b0, b1, last, side, 100, left, 0, 0.45, &r);
    c.move = r.best_move;
    c.score = r.score;
    c.depth = r.depth;
    if (is_mate(r.score)) {
        c.kind = r.score > 0 ? K_WIN : K_LOSS;
        c.dist = r.score > 0 ? (MATE - r.score) - n : (MATE + r.score) - n;
    } else if (solved && solved_score < 0) {
        c.kind = K_LOSS;
    }
    return c;
}

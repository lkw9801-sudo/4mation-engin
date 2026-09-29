/*
 * Linux test harness for engine_driver.h (the Windows app's move selection).
 *   ./test_driver selftest          book legality + sample re-proof + games vs random
 *   ./test_driver book < file       one "b0 b1 last" per line -> book move or -1
 */
#include <stdio.h>
#include <string.h>
#include "engine_driver.h"

static int legal_has(u64 b0, u64 b1, int last, int side, int m) {
    Pos p; load_pos(&p, b0, b1, last, side);
    int fb;
    return (gen_legal(&p, VALID & ~(b0 | b1), &fb) >> m) & 1;
}

/* play one game; engine plays `eng_side` at `level`, the other side plays random legal moves.
 * returns 1 X won, 2 O won, 3 draw; -1 on an illegal engine move */
static int game_vs_random(int eng_side, int level, unsigned *rng, int *eng_moves, int opening) {
    u64 b[2] = {0, 0};
    int last = 64, side = 0;
    for (int ply = 0; ply < 48; ply++) {
        int st = fm_status(b[0], b[1], last, side);
        if (st) return st;
        int m;
        if (side == eng_side && ply >= opening) {
            Choice c = engine_choose(b[0], b[1], last, side, level, rng);
            m = c.move;
            (*eng_moves)++;
            if (m < 0 || !legal_has(b[0], b[1], last, side, m)) return -1;
        } else {
            Pos p; load_pos(&p, b[0], b[1], last, side);
            int fb;
            u64 L = gen_legal(&p, VALID & ~(b[0] | b[1]), &fb);
            int cnt = popc(L), k = xrand(rng) % cnt;
            while (k--) L &= L - 1;
            m = lsb(L);
        }
        b[side] |= 1ULL << m;
        last = m;
        side ^= 1;
    }
    return fm_status(b[0], b[1], last, side);
}

int main(int argc, char **argv) {
    init_tables();
    if (argc > 1 && !strcmp(argv[1], "book")) {
        unsigned long long b0, b1;
        int last;
        while (scanf("%llx %llx %d", &b0, &b1, &last) == 3) printf("%d\n", book_lookup(b0, b1, last));
        return 0;
    }
    int bad = 0;
    /* 1. every book move is legal in its position, and X is to move there */
    for (int i = 0; i < BOOK_N; i++) {
        const BookEntry *e = &BOOK[i];
        if (popc(e->b0) != popc(e->b1) || !legal_has(e->b0, e->b1, e->last, 0, e->move)) bad++;
    }
    printf("book entries %d, illegal/inconsistent %d\n", BOOK_N, bad);
    /* 2. a sample of book moves (ply >= 8) re-proved: after the move, O is lost */
    int checked = 0, proven = 0;
    for (int i = 0; i < BOOK_N && checked < 300; i += 97) {
        const BookEntry *e = &BOOK[i];
        if (popc(e->b0) + popc(e->b1) < 8) continue;
        u64 c0 = e->b0 | (1ULL << e->move);
        checked++;
        if (has_four(c0)) { proven++; continue; }
        Result r;
        solver_opts();
        fm_search(c0, e->b1, e->move, 1, 100, -1, 1, 30.0, 0, 0, &r);
        if (!r.aborted && r.score < 0) proven++;
    }
    printf("book sample re-proved %d/%d\n", proven, checked);
    /* 3. games against a random mover */
    unsigned rng = 12345;
    g_time_scale = 0.1; /* strong 0.1 s, max 0.5 s per move */
    int res[4][2][4] = {{{0}}}, illegal = 0, moves = 0;
    for (int level = 0; level < LVL_COUNT; level++)
        for (int eng_side = 0; eng_side < 2; eng_side++)
            for (int g = 0; g < (level >= LVL_STRONG ? 10 : 20); g++) {
                int r = game_vs_random(eng_side, level, &rng, &moves, 0);
                if (r < 0) illegal++;
                else res[level][eng_side][r]++;
            }
    const char *names[] = {"easy", "normal", "strong", "max"};
    for (int level = 0; level < LVL_COUNT; level++)
        for (int s = 0; s < 2; s++)
            printf("%-6s engine as %s: X wins %d, O wins %d, draws %d\n", names[level], s ? "O" : "X",
                   res[level][s][1], res[level][s][2], res[level][s][3]);
    printf("engine moves %d, illegal %d\n", moves, illegal);
    /* 4. weak levels vary: first moves of 20 games as X at easy */
    int first[64] = {0}, distinct = 0;
    for (int g = 0; g < 20; g++) {
        Choice c = engine_choose(0, 0, 64, 0, LVL_EASY, &rng);
        if (c.move >= 0 && !first[c.move]++) distinct++;
    }
    printf("easy level: %d distinct first moves in 20 games\n", distinct);
    int fail = bad || illegal || proven != checked || res[2][0][1] != 10 || res[3][0][1] != 10;
    printf(fail ? "SELFTEST FAILED\n" : "SELFTEST OK\n");
    return fail;
}

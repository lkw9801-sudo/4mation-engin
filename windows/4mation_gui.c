/*
 * 4Mation — play against the reference engine (Windows, Win32 + GDI).
 *
 * Single executable: the search core (fourmation/native/core.c), the first
 * player's proven strategy book and this UI are compiled together. The engine
 * runs on a worker thread so the window stays responsive.
 *
 * Build (from Linux or MSYS2):  windows/build.sh   ->  windows/dist/4Mation.exe
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <windowsx.h>
#include <stdio.h>
#include <wchar.h>

#include "engine_driver.h"

#define WM_ENGINE_DONE (WM_APP + 1)

enum {
    IDM_NEW_HUMAN_X = 101, IDM_NEW_HUMAN_O, IDM_UNDO, IDM_HINT, IDM_SHOW_LEGAL, IDM_EXIT,
    IDM_LVL0 = 200, IDM_LVL1, IDM_LVL2, IDM_LVL3,
    IDM_RULES = 300, IDM_ABOUT
};

static const wchar_t *LEVEL_NAME[LVL_COUNT] = {L"입문", L"보통", L"강함 (1초)", L"최강 (5초)"};

/* ------------------------------------------------------------------ game */
typedef struct {
    u64 bb[2];
    int last;       /* stride-8 square or 64 (none) */
    int side;       /* 0 = X (blue, moves first), 1 = O (pink) */
    int hist[64];
    int nhist;
    int human;      /* side the human plays */
    int level;
    int over;       /* 0 ongoing, 1 X won, 2 O won, 3 draw */
    int thinking;   /* engine computing its move */
    int hinting;    /* engine computing a hint */
    int hint;       /* suggested square or -1 */
    int show_legal;
    u64 win_cells;
    wchar_t info[256];
} Game;

static Game G;
static HWND g_hwnd;
static HANDLE g_worker = NULL;
static LONG g_token = 0;
static unsigned g_rng = 1;

typedef struct { u64 b0, b1; int last, side, level, token, hint; } Job;
typedef struct { Choice c; int token, hint; double secs; } Done;

static void sqname(int s, wchar_t *out) {
    out[0] = (wchar_t)(L'a' + (s & 7));
    out[1] = (wchar_t)(L'1' + (s >> 3));
    out[2] = 0;
}

static u64 legal_mask(void) {
    if (G.over) return 0;
    Pos p;
    load_pos(&p, G.bb[0], G.bb[1], G.last, G.side);
    int fb;
    return gen_legal(&p, VALID & ~(G.bb[0] | G.bb[1]), &fb);
}

static int dead_end_now(void) {
    if (G.last >= 64 || G.over) return 0;
    return (NB[G.last] & VALID & ~(G.bb[0] | G.bb[1])) == 0;
}

static void update_over(void) {
    G.over = fm_status(G.bb[0], G.bb[1], G.last, G.side);
    G.win_cells = 0;
    if (G.over == 1 || G.over == 2) {
        u64 b = G.bb[G.over - 1];
        for (int w = 0; w < NWINS; w++)
            if ((b & WINS[w]) == WINS[w]) G.win_cells |= WINS[w];
    }
}

static void rebuild(void) {
    G.bb[0] = G.bb[1] = 0;
    G.last = 64;
    G.side = 0;
    for (int i = 0; i < G.nhist; i++) {
        G.bb[G.side] |= 1ULL << G.hist[i];
        G.last = G.hist[i];
        G.side ^= 1;
    }
    update_over();
}

static void play_move(int s) {
    G.hist[G.nhist++] = s;
    G.bb[G.side] |= 1ULL << s;
    G.last = s;
    G.side ^= 1;
    G.hint = -1;
    update_over();
}

/* ---------------------------------------------------------------- worker */
static DWORD WINAPI worker_proc(LPVOID arg) {
    Job j = *(Job *)arg;
    free(arg);
    double t0 = now_sec();
    Choice c = engine_choose(j.b0, j.b1, j.last, j.side, j.level, &g_rng);
    Done *d = (Done *)malloc(sizeof(Done));
    if (!d) return 0;
    d->c = c;
    d->token = j.token;
    d->hint = j.hint;
    d->secs = now_sec() - t0;
    if (!PostMessageW(g_hwnd, WM_ENGINE_DONE, 0, (LPARAM)d)) free(d);
    return 0;
}

/* stop a running search (if any) and wait for the thread to end */
static void stop_worker(void) {
    if (!g_worker) return;
    g_cancel = 1;
    while (WaitForSingleObject(g_worker, 10) == WAIT_TIMEOUT) stop_flag = 1;
    CloseHandle(g_worker);
    g_worker = NULL;
    g_cancel = 0;
    stop_flag = 0;
    G.thinking = G.hinting = 0;
    InterlockedIncrement(&g_token); /* a result it may already have posted is now stale */
}

static void start_worker(int hint) {
    stop_worker();
    Job *j = (Job *)malloc(sizeof(Job));
    if (!j) return;
    j->b0 = G.bb[0]; j->b1 = G.bb[1]; j->last = G.last; j->side = G.side;
    j->level = hint ? LVL_STRONG : G.level;
    j->hint = hint;
    j->token = (int)InterlockedIncrement(&g_token);
    if (hint) G.hinting = 1; else G.thinking = 1;
    g_worker = CreateThread(NULL, 0, worker_proc, j, 0, NULL);
    if (!g_worker) { free(j); G.thinking = G.hinting = 0; }
}

static void maybe_engine_move(void) {
    if (!G.over && G.side != G.human) start_worker(0);
}

/* heuristic score from the mover's point of view, in words */
static const wchar_t *lean(int score) {
    return score >= 300 ? L"크게 유리" : score >= 80 ? L"유리" : score > -80 ? L"비슷" :
           score > -300 ? L"불리" : L"크게 불리";
}

static void describe(const Choice *c, int hint, wchar_t *out, size_t n) {
    wchar_t mv[4] = L"-";
    if (c->move >= 0) sqname(c->move, mv);
    const wchar_t *who = hint ? L"힌트" : L"엔진";
    if (hint) {
        if (c->kind == K_WIN)
            _snwprintf(out, n, L"힌트: %ls — 이 수로 당신의 필승이 끝까지 계산됐습니다.", mv);
        else if (c->kind == K_DRAW)
            _snwprintf(out, n, L"힌트: %ls — 서로 최선이면 무승부입니다(끝까지 계산됨).", mv);
        else if (c->kind == K_LOSS)
            _snwprintf(out, n, L"힌트: %ls — 이미 진 국면이라 가장 오래 버티는 수입니다.", mv);
        else
            _snwprintf(out, n, L"힌트: %ls — 끝까지 계산 전, 당신 기준 %ls (평가 %+d)", mv, lean(c->score), c->score);
    } else if (c->from_book) {
        _snwprintf(out, n, L"%ls: %ls (선공 필승 전략표의 수)", who, mv);
    } else if (c->kind == K_WIN) {
        if (c->dist > 0)
            _snwprintf(out, n, L"%ls: %ls — 엔진 필승이 끝까지 계산됐습니다(%d수 안에 끝남).", who, mv, c->dist);
        else
            _snwprintf(out, n, L"%ls: %ls — 엔진 필승이 끝까지 계산됐습니다.", who, mv);
    } else if (c->kind == K_DRAW) {
        _snwprintf(out, n, L"%ls: %ls — 서로 최선이면 무승부입니다(끝까지 계산됨).", who, mv);
    } else if (c->kind == K_LOSS) {
        _snwprintf(out, n, L"%ls: %ls — 당신의 필승 국면이 증명됐습니다. 엔진은 최대한 버팁니다.", who, mv);
    } else {
        _snwprintf(out, n, L"%ls: %ls — 끝까지 계산 전, 엔진 기준 %ls (평가 %+d, 깊이 %d)", who, mv,
                   lean(c->score), c->score, c->depth);
    }
    out[n - 1] = 0;
}

static void new_game(int human) {
    stop_worker();
    int level = G.level, show = G.show_legal;
    memset(&G, 0, sizeof(G));
    G.level = level;
    G.show_legal = show;
    G.human = human;
    G.hint = -1;
    G.last = 64;
    wcscpy(G.info, human == 0 ? L"새 게임: 당신이 파랑(선공)입니다. 아무 칸에나 첫 수를 두세요."
                              : L"새 게임: 엔진이 파랑(선공)입니다.");
    maybe_engine_move();
    InvalidateRect(g_hwnd, NULL, FALSE);
}

static int human_moves(void) {
    int k = 0;
    for (int i = 0; i < G.nhist; i++) if ((i & 1) == G.human) k++;
    return k;
}

static void undo(void) {
    if (!human_moves()) return;
    stop_worker();
    do { G.nhist--; } while (G.nhist > 0 && (G.nhist & 1) != G.human);
    rebuild();
    G.hint = -1;
    wcscpy(G.info, L"한 수 물렀습니다.");
    InvalidateRect(g_hwnd, NULL, FALSE);
}

static void set_level(HWND h, int level) {
    G.level = level;
    CheckMenuRadioItem(GetMenu(h), IDM_LVL0, IDM_LVL3, IDM_LVL0 + level, MF_BYCOMMAND);
    InvalidateRect(h, NULL, FALSE);
}

/* ---------------------------------------------------------------- drawing */
typedef struct { int ox, oy, cell, board, status_y; } Layout;
static Layout L;
static HFONT f_label = NULL, f_status = NULL, f_status_b = NULL;
static int f_cell = 0;

static void layout(RECT rc, HDC dc) {
    int W = rc.right - rc.left, H = rc.bottom - rc.top;
    int dpi = GetDeviceCaps(dc, LOGPIXELSY);
    int line = MulDiv(22, dpi, 96);
    int status_h = line * 3 + MulDiv(18, dpi, 96);
    int margin = MulDiv(14, dpi, 96);
    /* the board is 7 cells; the frame (cell/6) and the coordinate labels (cell/2)
     * add about 0.7 cell on the left and at the bottom */
    int cw = (int)((W - 2 * margin) / 7.8), ch = (int)((H - status_h - 2 * margin) / 7.8);
    L.cell = cw < ch ? cw : ch;
    if (L.cell < 20) L.cell = 20;
    L.board = L.cell * 7;
    int lab = L.cell * 2 / 3;
    L.ox = margin + lab + (W - 2 * margin - lab - L.board) / 2;
    L.oy = margin + L.cell / 6;
    L.status_y = L.oy + L.board + L.cell / 6 + L.cell / 2 + MulDiv(6, dpi, 96);
    if (f_cell != L.cell) {
        if (f_label) DeleteObject(f_label);
        if (f_status) DeleteObject(f_status);
        if (f_status_b) DeleteObject(f_status_b);
        f_label = CreateFontW(-(L.cell * 28 / 100 > 12 ? L.cell * 28 / 100 : 12), 0, 0, 0, FW_SEMIBOLD, 0, 0, 0,
                              DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0, L"Malgun Gothic");
        f_status = CreateFontW(-MulDiv(15, dpi, 96), 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET, 0, 0,
                               CLEARTYPE_QUALITY, 0, L"Malgun Gothic");
        f_status_b = CreateFontW(-MulDiv(17, dpi, 96), 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET, 0, 0,
                                 CLEARTYPE_QUALITY, 0, L"Malgun Gothic");
        f_cell = L.cell;
    }
}

static void fill_round(HDC dc, int x0, int y0, int x1, int y1, int r, COLORREF col) {
    HBRUSH b = CreateSolidBrush(col);
    HGDIOBJ ob = SelectObject(dc, b), op = SelectObject(dc, GetStockObject(NULL_PEN));
    RoundRect(dc, x0, y0, x1, y1, r, r);
    SelectObject(dc, ob);
    SelectObject(dc, op);
    DeleteObject(b);
}

static void ring(HDC dc, int cx, int cy, int rad, int width, COLORREF col) {
    HPEN p = CreatePen(PS_SOLID, width, col);
    HGDIOBJ op = SelectObject(dc, p), ob = SelectObject(dc, GetStockObject(NULL_BRUSH));
    Ellipse(dc, cx - rad, cy - rad, cx + rad, cy + rad);
    SelectObject(dc, op);
    SelectObject(dc, ob);
    DeleteObject(p);
}

static void dot(HDC dc, int cx, int cy, int rad, COLORREF col) {
    HBRUSH b = CreateSolidBrush(col);
    HGDIOBJ ob = SelectObject(dc, b), op = SelectObject(dc, GetStockObject(NULL_PEN));
    Ellipse(dc, cx - rad, cy - rad, cx + rad, cy + rad);
    SelectObject(dc, ob);
    SelectObject(dc, op);
    DeleteObject(b);
}

static void cube(HDC dc, int x, int y, int size, int who) {
    COLORREF main = who == 0 ? RGB(40, 104, 214) : RGB(224, 76, 148);
    COLORREF light = who == 0 ? RGB(118, 166, 242) : RGB(246, 156, 198);
    COLORREF dark = who == 0 ? RGB(20, 60, 140) : RGB(150, 36, 96);
    int pad = size / 9, r = size / 5, sh = size / 22 + 1;
    fill_round(dc, x + pad + sh, y + pad + sh, x + size - pad + sh, y + size - pad + sh, r, dark);
    fill_round(dc, x + pad, y + pad, x + size - pad, y + size - pad, r, main);
    int in = size / 4;
    fill_round(dc, x + pad + in / 3, y + pad + in / 3, x + size - pad - in, y + size - pad - in, r, light);
    fill_round(dc, x + pad + in / 2, y + pad + in / 2, x + size - pad - in / 2 - in / 3,
               y + size - pad - in / 2 - in / 3, r, main);
}

static void cell_xy(int s, int *x, int *y) {
    *x = L.ox + (s & 7) * L.cell;
    *y = L.oy + (6 - (s >> 3)) * L.cell;
}

static void draw_text(HDC dc, HFONT f, COLORREF col, RECT r, const wchar_t *t, UINT fmt) {
    HGDIOBJ of = SelectObject(dc, f);
    SetTextColor(dc, col);
    DrawTextW(dc, t, -1, &r, fmt);
    SelectObject(dc, of);
}

static void paint_all(HDC dc, RECT rc) {
    layout(rc, dc);
    HBRUSH bg = CreateSolidBrush(RGB(245, 240, 232));
    FillRect(dc, &rc, bg);
    DeleteObject(bg);
    SetBkMode(dc, TRANSPARENT);
    int frame = L.cell / 6;
    fill_round(dc, L.ox - frame, L.oy - frame, L.ox + L.board + frame, L.oy + L.board + frame, L.cell / 3,
               RGB(128, 98, 66));
    fill_round(dc, L.ox - frame / 3, L.oy - frame / 3, L.ox + L.board + frame / 3, L.oy + L.board + frame / 3,
               L.cell / 4, RGB(224, 202, 168));
    u64 legal = (!G.thinking && G.side == G.human && G.show_legal) ? legal_mask() : 0;
    for (int r = 0; r < 7; r++)
        for (int c = 0; c < 7; c++) {
            int s = r * 8 + c, x, y;
            cell_xy(s, &x, &y);
            int g = L.cell / 14 + 1;
            fill_round(dc, x + g, y + g, x + L.cell - g, y + L.cell - g, L.cell / 4, RGB(208, 184, 148));
            u64 bit = 1ULL << s;
            if (G.bb[0] & bit) cube(dc, x, y, L.cell, 0);
            else if (G.bb[1] & bit) cube(dc, x, y, L.cell, 1);
            else if (legal & bit) dot(dc, x + L.cell / 2, y + L.cell / 2, L.cell / 9, RGB(160, 128, 92));
            if (G.win_cells & bit) ring(dc, x + L.cell / 2, y + L.cell / 2, L.cell * 36 / 100, L.cell / 12 + 1,
                                        RGB(255, 200, 0));
            if (s == G.last) dot(dc, x + L.cell / 2, y + L.cell / 2, L.cell / 10 + 1, RGB(255, 255, 255));
            if (s == G.hint) ring(dc, x + L.cell / 2, y + L.cell / 2, L.cell * 38 / 100, L.cell / 14 + 2,
                                  RGB(30, 160, 80));
        }
    /* coordinates */
    for (int i = 0; i < 7; i++) {
        wchar_t t[2] = {(wchar_t)(L'a' + i), 0};
        RECT r = {L.ox + i * L.cell, L.oy + L.board + frame, L.ox + (i + 1) * L.cell,
                  L.oy + L.board + frame + L.cell / 2};
        draw_text(dc, f_label, RGB(110, 92, 70), r, t, DT_CENTER | DT_TOP | DT_SINGLELINE);
        wchar_t u[2] = {(wchar_t)(L'1' + i), 0};
        RECT q = {L.ox - frame - L.cell / 2, L.oy + (6 - i) * L.cell, L.ox - frame, L.oy + (7 - i) * L.cell};
        draw_text(dc, f_label, RGB(110, 92, 70), q, u, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
    }
    /* status lines */
    wchar_t l1[160], l2[200];
    const wchar_t *hc = G.human == 0 ? L"파랑" : L"분홍";
    if (G.over == 3) wcscpy(l1, L"무승부입니다.");
    else if (G.over) wcscpy(l1, (G.over - 1) == G.human ? L"당신이 이겼습니다!" : L"엔진이 이겼습니다.");
    else if (G.thinking) wcscpy(l1, L"엔진이 생각하는 중입니다…");
    else if (G.hinting) wcscpy(l1, L"힌트를 계산하는 중입니다…");
    else if (dead_end_now()) _snwprintf(l1, 160, L"당신 차례(%ls) — 막힘! 상대 색 큐브 옆 빈칸 어디에나 둘 수 있습니다.", hc);
    else if (G.nhist == 0) _snwprintf(l1, 160, L"당신 차례(%ls) — 첫 수는 아무 칸에나 둘 수 있습니다.", hc);
    else _snwprintf(l1, 160, L"당신 차례(%ls) — 상대가 방금 둔 큐브(흰 점) 주변 8칸에 두세요.", hc);
    l1[159] = 0;
    _snwprintf(l2, 200, L"난이도: %ls  ·  %d수째  ·  당신: %ls(%ls)  ·  Ctrl+N 새 게임, Ctrl+Z 무르기, H 힌트",
               LEVEL_NAME[G.level], G.nhist, hc, G.human == 0 ? L"선공" : L"후공");
    l2[199] = 0;
    int dpi = GetDeviceCaps(dc, LOGPIXELSY), line = MulDiv(22, dpi, 96), x0 = MulDiv(16, dpi, 96);
    RECT r1 = {x0, L.status_y, rc.right - x0, L.status_y + line + 4};
    COLORREF c1 = G.over ? ((G.over - 1) == G.human ? RGB(30, 140, 70) : G.over == 3 ? RGB(90, 80, 70)
                                                                                      : RGB(190, 40, 60))
                         : RGB(40, 34, 28);
    draw_text(dc, f_status_b, c1, r1, l1, DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS);
    RECT r2 = {x0, r1.bottom, rc.right - x0, r1.bottom + line};
    draw_text(dc, f_status, RGB(40, 34, 28), r2, G.info, DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS);
    RECT r3 = {x0, r2.bottom, rc.right - x0, r2.bottom + line};
    draw_text(dc, f_status, RGB(120, 104, 86), r3, l2, DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS);
}

/* ------------------------------------------------------------ window proc */
static void on_click(int x, int y) {
    if (G.over || G.thinking || G.side != G.human) return;
    if (x < L.ox || y < L.oy || x >= L.ox + L.board || y >= L.oy + L.board) return;
    int c = (x - L.ox) / L.cell, r = 6 - (y - L.oy) / L.cell, s = r * 8 + c;
    if (!((legal_mask() >> s) & 1)) {
        MessageBeep(MB_ICONWARNING);
        return;
    }
    if (G.hinting) stop_worker();
    play_move(s);
    wchar_t mv[4];
    sqname(s, mv);
    _snwprintf(G.info, 256, L"당신: %ls", mv);
    G.info[255] = 0;
    maybe_engine_move();
    InvalidateRect(g_hwnd, NULL, FALSE);
}

static void on_engine_done(Done *d) {
    if (g_worker) {
        WaitForSingleObject(g_worker, INFINITE);
        CloseHandle(g_worker);
        g_worker = NULL;
    }
    if (d->token != g_token) { free(d); return; }  /* stale: game changed meanwhile */
    if (d->hint) {
        G.hinting = 0;
        if (!G.over && G.side == G.human && d->c.move >= 0) {
            G.hint = d->c.move;
            describe(&d->c, 1, G.info, 256);
        }
    } else {
        G.thinking = 0;
        int m = d->c.move;
        if (m < 0 || !((legal_mask() >> m) & 1)) {  /* should not happen; never stall */
            u64 lm = legal_mask();
            m = lm ? lsb(lm) : -1;
        }
        if (m >= 0 && !G.over) {
            play_move(m);
            describe(&d->c, 0, G.info, 256);
        }
    }
    free(d);
    InvalidateRect(g_hwnd, NULL, FALSE);
}

static const wchar_t *RULES_TEXT =
    L"4Mation 규칙 (Piatnik 공식 규칙서 기준)\n\n"
    L"• 7×7 판, 각자 큐브 24개. 파랑이 먼저 둡니다.\n"
    L"• 첫 수는 아무 칸에나 둘 수 있습니다.\n"
    L"• 그다음부터는 상대가 방금 둔 큐브와 변이나 꼭짓점이 닿는 칸(주변 8칸)에만 둘 수 있습니다.\n"
    L"• 막힘: 그 8칸이 모두 차 있으면, 상대 색 큐브 아무 것의 주변 빈칸에 둘 수 있습니다.\n"
    L"• 가로·세로·대각선으로 자기 큐브 4개 이상을 이으면 바로 이깁니다.\n"
    L"• 아무도 4줄을 만들 수 없게 되면 무승부입니다.\n\n"
    L"화면: 흰 점 = 방금 둔 수, 갈색 점 = 둘 수 있는 칸, 초록 원 = 힌트, 노란 원 = 이긴 줄.\n\n"
    L"참고: 이 게임은 선공 필승으로 증명돼 있습니다(1.d4, 29수). "
    L"'강함'·'최강'에서 엔진이 먼저 두면 이론상 이길 수 없습니다.";

static const wchar_t *ABOUT_TEXT =
    L"4Mation 레퍼런스 엔진\n\n"
    L"• 비트보드 C 탐색 코어(반복 심화 PVS, 치환표, 4Mation 전용 전술 가지치기)\n"
    L"• 끝까지 푸는 exact solver: 중반 이후는 대부분 1초 안에 승/무/패가 확정됩니다\n"
    L"• 선공 필승 전략표(1.d4부터 ply 16까지, 8,454국면, 전수 검증)\n\n"
    L"난이도\n"
    L"  입문: 얕은 탐색 + 무작위성\n"
    L"  보통: 중간 깊이 탐색 + 약간의 무작위성\n"
    L"  강함: 수당 1초, 전략표 + exact solver + 탐색\n"
    L"  최강: 수당 5초, 같은 방식\n\n"
    L"소스: github.com/lkw9801-sudo/4mation-engin";

static HMENU build_menu(void) {
    HMENU bar = CreateMenu(), game = CreatePopupMenu(), lvl = CreatePopupMenu(), help = CreatePopupMenu();
    AppendMenuW(game, MF_STRING, IDM_NEW_HUMAN_X, L"새 게임 - 내가 먼저 (파랑)\tCtrl+N");
    AppendMenuW(game, MF_STRING, IDM_NEW_HUMAN_O, L"새 게임 - 엔진이 먼저");
    AppendMenuW(game, MF_SEPARATOR, 0, NULL);
    AppendMenuW(game, MF_STRING, IDM_UNDO, L"한 수 무르기\tCtrl+Z");
    AppendMenuW(game, MF_STRING, IDM_HINT, L"힌트\tH");
    AppendMenuW(game, MF_STRING | MF_CHECKED, IDM_SHOW_LEGAL, L"둘 수 있는 칸 표시");
    AppendMenuW(game, MF_SEPARATOR, 0, NULL);
    AppendMenuW(game, MF_STRING, IDM_EXIT, L"끝내기");
    for (int i = 0; i < LVL_COUNT; i++) AppendMenuW(lvl, MF_STRING, IDM_LVL0 + i, LEVEL_NAME[i]);
    AppendMenuW(help, MF_STRING, IDM_RULES, L"규칙");
    AppendMenuW(help, MF_STRING, IDM_ABOUT, L"엔진 정보");
    AppendMenuW(bar, MF_POPUP, (UINT_PTR)game, L"게임(&G)");
    AppendMenuW(bar, MF_POPUP, (UINT_PTR)lvl, L"난이도(&L)");
    AppendMenuW(bar, MF_POPUP, (UINT_PTR)help, L"도움말(&H)");
    return bar;
}

static LRESULT CALLBACK wndproc(HWND h, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CREATE:
        g_hwnd = h;
        SetMenu(h, build_menu());
        CheckMenuRadioItem(GetMenu(h), IDM_LVL0, IDM_LVL3, IDM_LVL0 + G.level, MF_BYCOMMAND);
        return 0;
    case WM_ERASEBKGND:
        return 1;
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(h, &ps);
        RECT rc;
        GetClientRect(h, &rc);
        HDC mem = CreateCompatibleDC(hdc);
        HBITMAP bmp = CreateCompatibleBitmap(hdc, rc.right > 1 ? rc.right : 1, rc.bottom > 1 ? rc.bottom : 1);
        HGDIOBJ old = SelectObject(mem, bmp);
        paint_all(mem, rc);
        BitBlt(hdc, 0, 0, rc.right, rc.bottom, mem, 0, 0, SRCCOPY);
        SelectObject(mem, old);
        DeleteObject(bmp);
        DeleteDC(mem);
        EndPaint(h, &ps);
        return 0;
    }
    case WM_SIZE:
        InvalidateRect(h, NULL, FALSE);
        return 0;
    case WM_GETMINMAXINFO: {
        MINMAXINFO *mm = (MINMAXINFO *)lp;
        mm->ptMinTrackSize.x = 420;
        mm->ptMinTrackSize.y = 520;
        return 0;
    }
    case WM_LBUTTONDOWN:
        on_click(GET_X_LPARAM(lp), GET_Y_LPARAM(lp));
        return 0;
    case WM_KEYDOWN: {
        int ctrl = GetKeyState(VK_CONTROL) & 0x8000;
        if (ctrl && wp == 'N') new_game(0);
        else if (ctrl && wp == 'Z') undo();
        else if (wp == 'H') SendMessageW(h, WM_COMMAND, IDM_HINT, 0);
        else if (wp == VK_F2) new_game(G.human);
        return 0;
    }
    case WM_ENGINE_DONE:
        on_engine_done((Done *)lp);
        return 0;
    case WM_COMMAND:
        switch (LOWORD(wp)) {
        case IDM_NEW_HUMAN_X: new_game(0); break;
        case IDM_NEW_HUMAN_O: new_game(1); break;
        case IDM_UNDO: undo(); break;
        case IDM_HINT:
            if (!G.over && !G.thinking && G.side == G.human) {
                start_worker(1);
                InvalidateRect(h, NULL, FALSE);
            }
            break;
        case IDM_SHOW_LEGAL:
            G.show_legal = !G.show_legal;
            CheckMenuItem(GetMenu(h), IDM_SHOW_LEGAL, G.show_legal ? MF_CHECKED : MF_UNCHECKED);
            InvalidateRect(h, NULL, FALSE);
            break;
        case IDM_EXIT: DestroyWindow(h); break;
        case IDM_RULES: MessageBoxW(h, RULES_TEXT, L"규칙", MB_OK | MB_ICONINFORMATION); break;
        case IDM_ABOUT: MessageBoxW(h, ABOUT_TEXT, L"엔진 정보", MB_OK | MB_ICONINFORMATION); break;
        default:
            if (LOWORD(wp) >= IDM_LVL0 && LOWORD(wp) <= IDM_LVL3) set_level(h, LOWORD(wp) - IDM_LVL0);
        }
        return 0;
    case WM_DESTROY:
        stop_worker();
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(h, msg, wp, lp);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmd, int show) {
    (void)prev;
    (void)cmd;
    HMODULE u32 = GetModuleHandleW(L"user32.dll");
    if (u32) {
        typedef BOOL(WINAPI * DpiFn)(void);
        DpiFn f = (DpiFn)(void *)GetProcAddress(u32, "SetProcessDPIAware");
        if (f) f();
    }
    init_tables();
    fm_init(256); /* 256 MB transposition table */
    g_rng = (unsigned)GetTickCount() | 1u;
    G.level = LVL_STRONG;
    G.show_legal = 1;
    G.human = 0;
    G.hint = -1;
    G.last = 64;
    wcscpy(G.info, L"당신이 파랑(선공)입니다. 아무 칸에나 첫 수를 두세요. 난이도는 메뉴에서 바꿀 수 있습니다.");

    WNDCLASSEXW wc = {0};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = wndproc;
    wc.hInstance = inst;
    wc.hCursor = LoadCursor(NULL, IDC_HAND);
    wc.hIcon = LoadIconW(inst, MAKEINTRESOURCEW(1));
    if (!wc.hIcon) wc.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    wc.hIconSm = wc.hIcon;
    wc.lpszClassName = L"FourMationWnd";
    RegisterClassExW(&wc);

    HDC sdc = GetDC(NULL);
    int dpi = GetDeviceCaps(sdc, LOGPIXELSY);
    ReleaseDC(NULL, sdc);
    int w = MulDiv(640, dpi, 96), hgt = MulDiv(780, dpi, 96);
    HWND h = CreateWindowExW(0, wc.lpszClassName, L"4Mation — 레퍼런스 엔진과 대국", WS_OVERLAPPEDWINDOW,
                             CW_USEDEFAULT, CW_USEDEFAULT, w, hgt, NULL, NULL, inst, NULL);
    if (!h) return 1;
    ShowWindow(h, show);
    UpdateWindow(h);
    MSG m;
    while (GetMessageW(&m, NULL, 0, 0) > 0) {
        TranslateMessage(&m);
        DispatchMessageW(&m);
    }
    return 0;
}

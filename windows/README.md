# 4Mation for Windows

This is a single-file Windows program (`4Mation.exe`) for playing against the
reference engine. It needs no installation, no Python, and no network.

It uses the same C search core as the Python package
(`../fourmation/native/core.c`), the tuned weights from `engine_defaults.py`,
and the first-player strategy book embedded as a table.

| Level  | What it does |
|--------|--------------|
| 입문 (easy) | depth-2 search, random choice within 160 points of the best |
| 보통 (normal) | depth-6 search, random choice within 40 points of the best |
| 강함 (strong, default) | 1 s per move: book, then time-boxed exact solve, then iterative deepening (same as `Engine.play`) |
| 최강 (max) | 5 s per move, same as strong |

The weak levels always take a forced win when they see one and never play into
a forced loss.

## Build (Linux, mingw-w64)

```
sudo apt install mingw-w64
./build.sh                    # -> dist/4Mation.exe
```

`build.sh` regenerates `book_data.h` from `../fourmation/data/x_strategy_book.json`.
That keeps the WIN entries with X to move, expands them to all 8 symmetries
(52,325 entries), and cross-compiles a static exe that imports only GDI32,
USER32, KERNEL32 and msvcrt. The exe needs a CPU with POPCNT (2008 or later).

## Test

```
gcc -O2 -mpopcnt -std=gnu99 test_driver.c -o test_driver && ./test_driver selftest
```

The self-test checks four things:

- every book move is legal;
- 300 sampled book moves are re-proved as wins by the solver;
- every level wins its games against a random mover, and no level ever plays an illegal move;
- the easy level varies its opening.

`x86_64-w64-mingw32-gcc` builds the same harness as a Windows console exe.

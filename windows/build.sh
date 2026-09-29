#!/bin/bash
# Build windows/dist/4Mation.exe (64-bit, single file, no DLLs besides Windows itself).
# Needs mingw-w64 (Linux: apt install mingw-w64; Windows: MSYS2 "mingw-w64-x86_64-gcc").
set -e
cd "$(dirname "$0")"
CC=${CC:-x86_64-w64-mingw32-gcc}
WINDRES=${WINDRES:-x86_64-w64-mingw32-windres}
python3 gen_book.py
mkdir -p dist
$WINDRES app.rc -O coff -o app.res.o
# -mpopcnt: needs a CPU from 2008 or later (every PC that runs Windows 11 qualifies)
$CC -O2 -mpopcnt -std=gnu99 -municode -mwindows -static -s -Wall -Wno-unused-function -Wno-unused-parameter \
    4mation_gui.c app.res.o -o dist/4Mation.exe -lgdi32 -luser32
rm -f app.res.o
ls -la dist/4Mation.exe

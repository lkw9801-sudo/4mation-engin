"""ctypes binding for the native search core (core.c).

The shared library is compiled on first import (needs a C compiler: gcc/clang/cc,
or MinGW gcc / MSVC cl on Windows).
If compilation fails, `AVAILABLE` is False and the pure-Python engine is used.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from typing import List, Optional, Sequence, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "core.c")
_LIB = os.path.join(_HERE, "_core.dll" if sys.platform == "win32" else "_core.so")

MAXPLY = 64
MATE = 30000
MATE_BOUND = MATE - 100
INF = 32000
NFEAT = 16
DEPTH_COMPLETE = 127

OPTIONS = {
    "tt": 0, "sym": 1, "pvs": 2, "killer": 3, "history": 4, "threat_order": 5,
    "safe_prune": 6, "ext_forced": 7, "leaf_win3": 8, "aspiration": 9, "counter": 10,
    "eval_order": 11, "mdp": 12, "reply_order": 13, "dead_prune": 14, "etc": 15,
}


class Result(ctypes.Structure):
    _fields_ = [
        ("best_move", ctypes.c_int),
        ("score", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("complete", ctypes.c_int),
        ("aborted", ctypes.c_int),
        ("pv_len", ctypes.c_int),
        ("pv", ctypes.c_int * MAXPLY),
        ("nodes", ctypes.c_int64),
        ("tt_probes", ctypes.c_int64),
        ("tt_hits", ctypes.c_int64),
        ("tt_cuts", ctypes.c_int64),
        ("beta_cuts", ctypes.c_int64),
        ("first_cuts", ctypes.c_int64),
        ("interior", ctypes.c_int64),
        ("evals", ctypes.c_int64),
        ("fallback_hits", ctypes.c_int64),
        ("safe_pruned", ctypes.c_int64),
        ("win1", ctypes.c_int64),
        ("loss2", ctypes.c_int64),
        ("win3", ctypes.c_int64),
        ("elapsed", ctypes.c_double),
        ("iters", ctypes.c_int),
        ("it_depth", ctypes.c_int * MAXPLY),
        ("it_move", ctypes.c_int * MAXPLY),
        ("it_score", ctypes.c_int * MAXPLY),
        ("it_nodes", ctypes.c_int64 * MAXPLY),
        ("it_time", ctypes.c_double * MAXPLY),
    ]


def _compiler() -> Optional[str]:
    for c in (os.environ.get("CC"), "gcc", "clang", "cc", "cl" if sys.platform == "win32" else None):
        if c and shutil.which(c):
            return c
    return None


def build(force: bool = False, march_native: bool = True) -> bool:
    """Compile core.c into a shared library next to it (gcc/clang/cc, or MSVC cl on Windows)."""
    if not force and os.path.exists(_LIB) and os.path.getmtime(_LIB) >= os.path.getmtime(_SRC):
        return True
    cc = _compiler()
    if cc is None:
        return False
    tmp = _LIB + f".{os.getpid()}.tmp"
    if os.path.basename(cc).lower().startswith("cl"):
        cmd = [cc, "/nologo", "/O2", "/LD", _SRC, f"/Fe:{tmp}"]
    else:
        flags = ["-O3", "-shared", "-std=c99", "-D_POSIX_C_SOURCE=199309L"]
        if sys.platform != "win32":
            flags.append("-fPIC")
        if march_native:
            flags.append("-march=native")
        cmd = [cc, *flags, _SRC, "-o", tmp]
    try:
        subprocess.run(cmd, check=True, capture_output=True, cwd=_HERE)
    except (subprocess.CalledProcessError, OSError):
        if march_native and not os.path.basename(cc).lower().startswith("cl"):
            return build(force=True, march_native=False)
        return False
    os.replace(tmp, _LIB)
    return True


_lib = None
AVAILABLE = False
if os.environ.get("FOURMATION_NO_NATIVE") != "1":
    try:
        if build():
            _lib = ctypes.CDLL(_LIB)
            AVAILABLE = True
    except OSError:
        _lib = None
        AVAILABLE = False

if AVAILABLE:
    u64 = ctypes.c_uint64
    _lib.fm_init.argtypes = [ctypes.c_int]
    _lib.fm_set_rules.argtypes = [ctypes.c_int, ctypes.c_int]
    _lib.fm_set_option.argtypes = [ctypes.c_int, ctypes.c_int]
    _lib.fm_get_option.argtypes = [ctypes.c_int]
    _lib.fm_set_weights.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
    _lib.fm_legal.argtypes = [u64, u64, ctypes.c_int, ctypes.c_int]
    _lib.fm_legal.restype = u64
    _lib.fm_status.argtypes = [u64, u64, ctypes.c_int, ctypes.c_int]
    _lib.fm_perft.argtypes = [u64, u64, ctypes.c_int, ctypes.c_int, ctypes.c_int]
    _lib.fm_perft.restype = ctypes.c_int64
    _lib.fm_features.argtypes = [u64, u64, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    _lib.fm_eval.argtypes = [u64, u64, ctypes.c_int, ctypes.c_int]
    _lib.fm_search.argtypes = [u64, u64, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_double, ctypes.c_int64, ctypes.c_int,
                               ctypes.POINTER(Result)]
    _lib.fm_think.argtypes = [u64, u64, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_double,
                              ctypes.c_int64, ctypes.c_double, ctypes.POINTER(Result)]
    _lib.fm_set_reply_order_min_depth.argtypes = [ctypes.c_int]
    _lib.fm_ctx_new.argtypes = [ctypes.c_int]
    _lib.fm_ctx_new.restype = ctypes.c_void_p
    _lib.fm_ctx_select.argtypes = [ctypes.c_void_p]
    _lib.fm_ctx_free.argtypes = [ctypes.c_void_p]
    _lib.fm_set_sym_max_n.argtypes = [ctypes.c_int]
    _lib.fm_init(0)


# ---- coordinate conversion (rules.py index r*7+c  <->  core square r*8+c) ----

def sq(i: int) -> int:
    r, c = divmod(i, 7)
    return r * 8 + c


def idx(s: int) -> int:
    r, c = divmod(s, 8)
    return r * 7 + c


def mask_to_indices(m: int) -> List[int]:
    out = []
    while m:
        low = m & -m
        out.append(idx(low.bit_length() - 1))
        m ^= low
    return sorted(out)


def encode(board: Sequence[int], last: Optional[int], to_move: int) -> Tuple[int, int, int, int]:
    b0 = b1 = 0
    for i, v in enumerate(board):
        if v == 1:
            b0 |= 1 << sq(i)
        elif v == 2:
            b1 |= 1 << sq(i)
    return b0, b1, (sq(last) if last is not None else -1), to_move - 1


def lib():
    if not AVAILABLE:
        raise RuntimeError("native core not available")
    return _lib

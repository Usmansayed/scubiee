"""Stat many files without a GIL handoff per file (Windows).

``os.stat`` releases the GIL around the syscall. With another Python thread
busy (a /v1/search, a rerank), every release has to win the GIL back, which
costs about one switch interval / timer tick (~15ms on Windows): the "convoy
effect" (bpo-7946, cpython#89977). The keeper's change poll stats every indexed
file each second; measured here that loop took 78ms idle and 18.3s with one
busy thread (1167 files), which is what stalled saves for 6-11s (issue 4).

``ctypes.PyDLL`` calls do not release the GIL, so ``GetFileAttributesExW``
through it is a few microseconds with no handoff. It returns the same
FILETIME ``os.stat`` converts, and the float is built the way CPython builds
``st_mtime`` (``sec + nsec * 1e-9``), so stored mtimes compare equal.

Everything else (POSIX, 32-bit, reparse points, long paths, odd errors) falls
back to ``os.stat``.
"""

from __future__ import annotations

import os
import stat as stat_mod
import sys
from pathlib import Path
from typing import NamedTuple


class FastStat(NamedTuple):
    st_mtime: float
    st_mtime_ns: int
    st_size: int
    is_file: bool
    is_dir: bool


_FILE_ATTRIBUTE_DIRECTORY = 0x10
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_EPOCH_AS_FILETIME = 116444736000000000  # 1601-01-01 -> 1970-01-01, 100ns units
_NOT_FOUND = {2, 3}  # ERROR_FILE_NOT_FOUND, ERROR_PATH_NOT_FOUND

_impl = None


def _load_win32():
    import ctypes
    from ctypes import wintypes

    class _FILETIME(ctypes.Structure):
        _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    class _ATTR_DATA(ctypes.Structure):
        _fields_ = [
            ("attrs", wintypes.DWORD),
            ("ctime", _FILETIME),
            ("atime", _FILETIME),
            ("mtime", _FILETIME),
            ("size_hi", wintypes.DWORD),
            ("size_lo", wintypes.DWORD),
        ]

    # PyDLL: the GIL stays held for the call (that is the whole point).
    k32 = ctypes.PyDLL("kernel32", use_last_error=True)
    fn = k32.GetFileAttributesExW
    fn.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p]
    fn.restype = wintypes.BOOL
    buf = _ATTR_DATA()
    ref = ctypes.byref(buf)
    get_err = ctypes.get_last_error

    def _stat(path: str) -> FastStat | None | bool:
        """FastStat, None for missing, False for "ask os.stat"."""
        if not fn(path, 0, ref):
            return None if get_err() in _NOT_FOUND else False
        attrs = buf.attrs
        if attrs & _FILE_ATTRIBUTE_REPARSE_POINT:
            return False  # os.stat follows links; keep its semantics
        ft = (buf.mtime.hi << 32) | buf.mtime.lo
        ns = (ft - _EPOCH_AS_FILETIME) * 100
        sec, nsec = divmod(ns, 1_000_000_000)
        is_dir = bool(attrs & _FILE_ATTRIBUTE_DIRECTORY)
        return FastStat(
            st_mtime=sec + nsec * 1e-9,
            st_mtime_ns=ns,
            st_size=(buf.size_hi << 32) | buf.size_lo,
            is_file=not is_dir,
            is_dir=is_dir,
        )

    return _stat


def _impl_or_none():
    global _impl
    if _impl is None:
        _impl = False
        enabled = (os.environ.get("CTX_FAST_STAT") or "1").strip().lower() not in {"0", "false", "off", "no"}
        if enabled and os.name == "nt" and sys.maxsize > 2**32:
            try:
                _impl = _load_win32()
            except Exception:  # noqa: BLE001
                _impl = False
    return _impl or None


def _os_stat(path: str) -> FastStat | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return FastStat(
        st_mtime=st.st_mtime,
        st_mtime_ns=st.st_mtime_ns,
        st_size=st.st_size,
        is_file=stat_mod.S_ISREG(st.st_mode),
        is_dir=stat_mod.S_ISDIR(st.st_mode),
    )


_RESOLVED: dict[str, Path] = {}


def cached_resolve(path: str | Path) -> Path:
    """``Path.resolve()`` memoised per input string.

    On Windows ``resolve`` is two ``GetFinalPathNameByHandle`` calls, each a
    GIL release; the change poll resolved the same repo root ~19 times a second
    (1.2s of a 3.1s poll with one busy thread). Only for long-lived roots (the
    repo, the store dir), which do not move while the process runs.
    """
    key = os.fspath(path)
    hit = _RESOLVED.get(key)
    if hit is None:
        hit = Path(key).resolve()
        if len(_RESOLVED) < 256:
            _RESOLVED[key] = hit
    return hit


def fast_stat(path: str | Path) -> FastStat | None:
    """Like ``os.stat`` (follows links) but GIL-held on Windows. None if missing."""
    p = os.fspath(path)
    impl = _impl_or_none()
    if impl is not None:
        out = impl(p)
        if out is not False:
            return out  # FastStat or None (missing)
    return _os_stat(p)

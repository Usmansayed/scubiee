"""Process-lifetime thread pool for the three independent retrieve channels."""

from __future__ import annotations

import atexit
from concurrent.futures import ThreadPoolExecutor

_POOL: ThreadPoolExecutor | None = None


def channel_pool() -> ThreadPoolExecutor:
    global _POOL
    if _POOL is None:
        _POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="ce-chan")
        atexit.register(_shutdown)
    return _POOL


def _shutdown() -> None:
    global _POOL
    pool = _POOL
    _POOL = None
    if pool is not None:
        pool.shutdown(wait=False)

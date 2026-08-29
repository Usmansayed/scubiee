"""Cross-process exclusive lock for on-disk index stores (Windows-safe)."""

from __future__ import annotations

import os
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

_LOCK_NAME = ".scubiee-write.lock"
_HELD: threading.local = threading.local()


def store_lock_file(store_dir: Path) -> Path:
    return Path(store_dir).resolve() / _LOCK_NAME


def _held_dirs() -> set[Path]:
    raw = getattr(_HELD, "dirs", None)
    if raw is None:
        raw = set()
        _HELD.dirs = raw
    return raw


def _acquire_fd(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX)


def _release_fd(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        return
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def store_write_lock(store_dir: Path, *, timeout: float = 120.0) -> Iterator[None]:
    """Exclusive lock for all artifact writes under *store_dir*."""
    store_dir = Path(store_dir).resolve()
    held = _held_dirs()
    if store_dir in held:
        yield
        return

    store_dir.mkdir(parents=True, exist_ok=True)
    lock_path = store_lock_file(store_dir)
    deadline = time.monotonic() + timeout
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    acquired = False
    try:
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"timed out waiting for store lock ({lock_path}); "
                        "another scubiee process may be indexing — "
                        "run: scubiee engine stop"
                    ) from None
                time.sleep(0.1)
        held.add(store_dir)
        try:
            yield
        finally:
            held.discard(store_dir)
    finally:
        if acquired:
            _release_fd(fd)
        os.close(fd)


def quiesce_background_indexing(*, store_dir: Path | None = None) -> dict[str, Any]:
    """Stop engine/watchdog workers so init/rebuild can write store artifacts."""
    out: dict[str, Any] = {"ok": True}
    try:
        from pipeline.watchdog import stop_watchdog

        out["watchdog"] = stop_watchdog()
    except Exception as exc:  # noqa: BLE001
        out["watchdog"] = {"ok": False, "error": str(exc)}
        out["ok"] = False
    try:
        from pipeline.daemon import stop_daemon

        out["daemon"] = stop_daemon()
    except Exception as exc:  # noqa: BLE001
        out["daemon"] = {"ok": False, "error": str(exc)}
        out["ok"] = False
    try:
        from pipeline.process_control import stop_engine_worker_processes

        out["workers"] = stop_engine_worker_processes()
        if not out["workers"].get("ok", True):
            out["ok"] = False
    except Exception as exc:  # noqa: BLE001
        out["workers"] = {"ok": False, "error": str(exc)}
    if store_dir is not None:
        out["store_dir"] = str(Path(store_dir).resolve())
    # Windows needs a beat after terminate before handles drop.
    time.sleep(0.75)
    return out

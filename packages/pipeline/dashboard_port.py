"""Stable localhost port selection and dashboard process state."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Iterator
from urllib.parse import urlparse

from .project_id import context_engine_home


PRIVATE_PORT_MIN = 49152
PRIVATE_PORT_MAX = 65535
PRIVATE_PORT_COUNT = PRIVATE_PORT_MAX - PRIVATE_PORT_MIN + 1
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def preferred_dashboard_port(seed: str) -> int:
    """Return a deterministic port in the dynamic/private range."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    offset = int.from_bytes(digest[:8], "big") % PRIVATE_PORT_COUNT
    return PRIVATE_PORT_MIN + offset


def _port_free(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))
    except OSError:
        return False
    return True


def allocate_dashboard_port(seed: str, *, preferred: int | None = None) -> int:
    """Find a free private port, probing upward and wrapping once."""
    first = preferred_dashboard_port(seed) if preferred is None else preferred
    if not PRIVATE_PORT_MIN <= first <= PRIVATE_PORT_MAX:
        raise ValueError(
            f"preferred port must be between {PRIVATE_PORT_MIN} and {PRIVATE_PORT_MAX}"
        )

    start_offset = first - PRIVATE_PORT_MIN
    for step in range(PRIVATE_PORT_COUNT):
        port = PRIVATE_PORT_MIN + ((start_offset + step) % PRIVATE_PORT_COUNT)
        if _port_free(port):
            return port
    raise RuntimeError("no free dashboard port in the dynamic/private range")


def _default_dashboard_path() -> Path:
    return context_engine_home() / "dashboard.json"


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _thread_lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.RLock())


def _lock_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _state_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    with _thread_lock_for(lock_path):
        with lock_path.open("a+b") as handle:
            _lock_file(handle)
            try:
                yield
            finally:
                _unlock_file(handle)


def _read_state(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


@dataclass(slots=True)
class DashboardLock:
    """Atomic dashboard process lock/state stored as JSON."""

    path: Path = field(default_factory=_default_dashboard_path)

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def acquire(self, url: str, pid: int) -> dict[str, Any]:
        parsed = urlparse(url)
        if parsed.hostname is None or parsed.port is None:
            raise ValueError("dashboard URL must include a host and port")
        state: dict[str, Any] = {
            "host": parsed.hostname,
            "port": parsed.port,
            "url": url,
            "pid": pid,
            "started_at": time.time(),
        }
        with _state_lock(self.path):
            _atomic_write_json(self.path, state)
        return state

    def read(self) -> dict[str, Any] | None:
        with _state_lock(self.path):
            return _read_state(self.path)

    def release_if_owner(self, pid: int) -> bool:
        with _state_lock(self.path):
            state = _read_state(self.path)
            if state is None or state.get("pid") != pid:
                return False
            try:
                self.path.unlink()
            except FileNotFoundError:
                return False
            return True

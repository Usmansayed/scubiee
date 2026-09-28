"""Cross-process index generation stamp — keys MCP map caches on the live index.

The engine bumps ``RepoRuntime.generation`` on every publish. MCP locate
workers are separate processes and cache map results in memory and in the
session store, so the engine cannot clear those caches directly. Instead it
writes ``<store>/generation.json`` after every bump, and the MCP side keys its
caches on the stamp's token (runtime epoch + generation). A publish changes
the token, so the next map misses and re-queries (Elasticsearch invalidates its
shard request cache on refresh the same way).

Reading the stamp is one small file read: the repeat-map fast path does not
wait on the engine's HTTP server, which can lag under embed load.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

STAMP_NAME = "generation.json"

_WRITE_LOCK = threading.Lock()
# project_id -> (epoch, generation) last written by this process.
_WRITTEN: dict[str, tuple[str, int]] = {}
# normalized repo -> project_id (reader side; ids do not change under a live repo).
_PID_CACHE: dict[str, str] = {}


def stamp_path(project_id: str) -> Path:
    from pipeline.project_id import projects_root

    return projects_root() / project_id / STAMP_NAME


def make_token(epoch: str, generation: int) -> str:
    return f"{epoch}:{int(generation)}"


def write_stamp(project_id: str | None, generation: int, *, epoch: str) -> bool:
    """Publish the served generation for ``project_id``. Never raises.

    Monotonic per epoch: an older publish that finishes late cannot move the
    stamp backwards and re-validate cache entries from before a newer publish.
    """
    if not project_id or not epoch:
        return False
    gen = int(generation)
    with _WRITE_LOCK:
        prev = _WRITTEN.get(project_id)
        if prev is not None and prev[0] == epoch and prev[1] >= gen:
            return False
        path = stamp_path(project_id)
        body = json.dumps(
            {
                "token": make_token(epoch, gen),
                "epoch": epoch,
                "generation": gen,
                "pid": os.getpid(),
                "ts": time.time(),
            }
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{STAMP_NAME}.{os.getpid()}.tmp")
            tmp.write_text(body, encoding="utf-8")
            for attempt in range(5):
                try:
                    os.replace(tmp, path)
                    break
                except PermissionError:
                    # Windows: a reader holding the file open blocks the rename.
                    if attempt == 4:
                        tmp.unlink(missing_ok=True)
                        path.write_text(body, encoding="utf-8")
                        break
                    time.sleep(0.005)
        except OSError:
            return False
        _WRITTEN[project_id] = (epoch, gen)
        return True


def _norm_repo(repo: Path | str) -> str:
    return str(repo or "").replace("\\", "/").rstrip("/").lower()


def _project_id_for(repo: Path | str) -> str | None:
    key = _norm_repo(repo)
    pid = _PID_CACHE.get(key)
    if pid:
        return pid
    try:
        from pipeline.project_id import read_id_file

        pid = read_id_file(Path(repo))
    except Exception:  # noqa: BLE001
        pid = None
    if pid:
        _PID_CACHE[key] = pid
    return pid or None


def read_token(repo: Path | str) -> str | None:
    """Current index token for ``repo``, or None when unknown (callers skip caching)."""
    pid = _project_id_for(repo)
    if not pid:
        return None
    try:
        data = json.loads(stamp_path(pid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Missing (engine not loaded yet / older build) or torn mid-write.
        return None
    token = data.get("token") if isinstance(data, dict) else None
    return str(token) if token else None


def reset_for_tests() -> None:
    with _WRITE_LOCK:
        _WRITTEN.clear()
    _PID_CACHE.clear()

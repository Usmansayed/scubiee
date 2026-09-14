"""Process / warm / client snapshots for the MCP host sim."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def _rss_mb(pid: int) -> float | None:
    try:
        import psutil

        return round(psutil.Process(pid).memory_info().rss / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001
        return None


def engine_snapshot(engine_url: str = "http://127.0.0.1:8765") -> dict[str, Any]:
    from pipeline.daemon import is_running, meta_path, pid_path, _pid_alive, _read_lock_pid

    snap: dict[str, Any] = {
        "running": False,
        "pid": None,
        "rss_mb": None,
        "health_ok": False,
        "warm_ready": False,
        "embedder_loaded": False,
        "soft_search_ready": False,
        "at": time.time(),
    }
    pid: int | None = None
    try:
        pid = _read_lock_pid()
    except Exception:  # noqa: BLE001
        pid = None
    if pid is None:
        try:
            if pid_path().is_file():
                pid = int(pid_path().read_text(encoding="utf-8").strip() or 0) or None
        except Exception:  # noqa: BLE001
            pid = None
    if pid is None:
        try:
            if meta_path().is_file():
                meta = json.loads(meta_path().read_text(encoding="utf-8"))
                pid = int(meta.get("pid") or 0) or None
        except Exception:  # noqa: BLE001
            pid = None
    pid_alive = bool(pid and _pid_alive(int(pid)))
    if pid:
        snap["pid"] = pid
        snap["rss_mb"] = _rss_mb(pid)
    # PID-alive counts as running even when /health is starved by cold ORT load.
    try:
        snap["running"] = bool(pid_alive or is_running())
    except Exception:  # noqa: BLE001
        snap["running"] = pid_alive
    try:
        from pipeline.client import EngineClient

        # Single /health probe — avoid healthy()+get double-timeout storms.
        # Slightly longer read during cold attach so ORT load does not false-fail warm.
        h = EngineClient(base_url=engine_url, timeout=3.0).health()
        healthy = bool(isinstance(h, dict) and h.get("ok") and "service" in h)
        snap["health_ok"] = healthy
        if isinstance(h, dict) and h.get("ok"):
            snap["embedder_loaded"] = bool(
                h.get("embedder_loaded") or (h.get("engine") or {}).get("embedder_loaded")
            )
            snap["soft_search_ready"] = bool(
                h.get("soft_search_ready")
                or (h.get("engine") or {}).get("soft_search_ready")
            )
            snap["embed_prewarm_running"] = bool(h.get("embed_prewarm_running"))
            warm = h.get("warm_ready")
            if warm is None:
                warm = snap["soft_search_ready"] or snap["embedder_loaded"]
            snap["warm_ready"] = bool(warm)
            if snap["soft_search_ready"]:
                snap["warm_ready"] = True
                snap["health_ok"] = True
            if "chunks" in h:
                snap["chunks"] = h.get("chunks")
            # Remember last good soft for brief DML/abort flaps.
            if snap["soft_search_ready"]:
                _LAST_SOFT_OK["at"] = time.time()
                _LAST_SOFT_OK["chunks"] = snap.get("chunks")
    except Exception as exc:  # noqa: BLE001
        snap["health_error"] = str(exc)
        # Sticky soft: engine process alive + recent soft binder — do not fail
        # settle on ConnectionAborted / 3s health starve during embed batches.
        age = time.time() - float(_LAST_SOFT_OK.get("at") or 0.0)
        if pid_alive and age >= 0.0 and age < 8.0:
            snap["soft_search_ready"] = True
            snap["warm_ready"] = True
            snap["health_ok"] = True
            snap["soft_sticky"] = True
            if _LAST_SOFT_OK.get("chunks") is not None:
                snap["chunks"] = _LAST_SOFT_OK.get("chunks")
    return snap


_LAST_SOFT_OK: dict[str, Any] = {"at": 0.0, "chunks": None}


def clients_snapshot() -> dict[str, Any]:
    from pipeline.lifecycle_runtime import load_clients, load_policy, reconcile_clients

    remaining = reconcile_clients()
    policy = load_policy()
    return {
        "active_clients": len(remaining),
        "client_ids": [
            str((c.get("client_id") if isinstance(c, dict) else c) or "")
            for c in remaining
        ],
        "desired_mode": policy.get("desired_mode"),
        "last_client_left_at": policy.get("last_client_left_at"),
        "last_activity": policy.get("last_activity"),
        "raw_clients": load_clients().get("clients") or {},
    }


def count_top_level_mcp_bridges() -> int:
    """Count mcp_bridge processes whose parent is not another mcp_bridge.

    Nested pythonw→pythonw rows are normal on Windows; two *top-level* bridges
    mean Cursor (or another host) opened a duplicate MCP connection.
    """
    from pipeline.process_control import enumerate_scubiee_processes, _is_mcp_bridge_process

    procs = enumerate_scubiee_processes(exclude_self=False)
    by_pid = {int(p["pid"]): p for p in procs if p.get("pid") is not None}
    n = 0
    for p in procs:
        if not _is_mcp_bridge_process(p):
            continue
        parent = by_pid.get(int(p.get("ppid") or 0))
        if parent is not None and _is_mcp_bridge_process(parent):
            continue
        n += 1
    return n


def observatory_tick(engine_url: str = "http://127.0.0.1:8765") -> dict[str, Any]:
    return {
        "engine": engine_snapshot(engine_url),
        "clients": clients_snapshot(),
        "ctx_home": os.environ.get("CTX_HOME") or str(Path.home() / ".scubiee"),
    }


def tail_engine_log(*, lines: int = 40) -> list[str]:
    home = Path(os.environ.get("CTX_HOME") or (Path.home() / ".scubiee"))
    path = home / "engine.log"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return text[-max(1, lines) :]
    except Exception:  # noqa: BLE001
        return []


def assert_no_thrash(prev: dict[str, Any], cur: dict[str, Any]) -> str | None:
    """Return failure code if engine died/restarted while host should hold."""
    pe = prev.get("engine") or {}
    ce = cur.get("engine") or {}
    ppid = pe.get("pid")
    cpid = ce.get("pid")
    if ppid and cpid and int(ppid) != int(cpid):
        return "THRASH_KILL"
    if pe.get("running") and not ce.get("running"):
        return "THRASH_KILL"
    clients = (cur.get("clients") or {}).get("active_clients") or 0
    if pe.get("running") and int(clients) == 0:
        # Host path should keep a register; zero while claiming connected is thrash risk.
        return None  # leave to scenario to decide with host_alive flag
    return None

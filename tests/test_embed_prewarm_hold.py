"""Embed prewarm + disconnect hold semantics."""

from __future__ import annotations

import time
from pathlib import Path


def test_alive_mcp_client_not_stale(monkeypatch) -> None:
    from pipeline import lifecycle_runtime as lr

    meta = {
        "client_id": "mcp:test",
        "pid": 12345,
        "kind": "mcp",
        "registered_at": time.time() - 3600,
        "last_seen_at": time.time() - 3600,
    }
    monkeypatch.setattr(lr, "_client_pid_trustworthy", lambda _m: True)
    assert lr._client_is_stale(meta, now=time.time()) is False
    monkeypatch.setattr(lr, "_client_pid_trustworthy", lambda _m: False)
    assert lr._client_is_stale(meta, now=time.time()) is True


def test_prewarm_async_skips_when_disabled(monkeypatch) -> None:
    from pipeline.engine import prewarm_embedder_async

    monkeypatch.setenv("CTX_EMBED_PREWARM", "0")
    out = prewarm_embedder_async(Path("."))
    assert out.get("ok") is True
    assert out.get("skipped") is True


def test_prewarm_status_shape() -> None:
    from pipeline.engine import prewarm_status

    st = prewarm_status()
    assert "running" in st
    assert "done" in st
    assert "embedder_loaded" in st


def test_ensure_embedder_ready_short_circuits_when_loaded(monkeypatch) -> None:
    from pipeline import engine as eng

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: True)
    monkeypatch.setattr(
        eng,
        "prewarm_status",
        lambda: {
            "running": False,
            "done": True,
            "error": None,
            "ms": 1.0,
            "embedder_loaded": True,
        },
    )
    out = eng.ensure_embedder_ready(Path("."))
    assert out.get("already_warm") is True
    assert out.get("ok") is True


def test_ensure_embedder_ready_joins_inflight(monkeypatch) -> None:
    from pipeline import engine as eng

    state = {"loaded": False, "kicks": 0}

    def _loaded() -> bool:
        return bool(state["loaded"])

    def _async(_root=None):
        state["kicks"] += 1

        def _finish() -> None:
            import time as _t

            _t.sleep(0.05)
            state["loaded"] = True

        import threading

        threading.Thread(target=_finish, daemon=True).start()
        return {"ok": True, "started": True}

    monkeypatch.setattr(eng, "embedder_is_loaded", _loaded)
    monkeypatch.setattr(eng, "prewarm_embedder_async", _async)
    monkeypatch.setattr(
        eng,
        "prewarm_status",
        lambda: {
            "running": not state["loaded"],
            "done": state["loaded"],
            "error": None,
            "ms": None,
            "embedder_loaded": state["loaded"],
        },
    )
    monkeypatch.setattr(
        eng,
        "prewarm_embedder",
        lambda _r=None: (_ for _ in ()).throw(AssertionError("should join, not sync")),
    )
    out = eng.ensure_embedder_ready(Path("."), wait_s=2.0)
    assert out.get("ok") is True
    assert state["kicks"] == 1
    assert state["loaded"] is True

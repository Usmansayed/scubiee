"""Universal MCP connect/disconnect lifecycle (host/OS agnostic)."""

from __future__ import annotations

from pathlib import Path


def test_warm_engine_for_mcp_waits_for_embedder(monkeypatch, tmp_path: Path) -> None:
    from pipeline import mcp_lifecycle as ml

    calls: list[str] = []

    class _Client:
        def __init__(self, **_kw):
            pass

        def open_repo(self, *_a, **_k):
            calls.append("open")
            return {"ok": True, "status": "activated", "warm_state": "ready"}

        def post(self, path, body=None):
            calls.append(path)
            if path == "/v1/client/register":
                return {"ok": True, "prewarm": {"ok": True, "embedder_loaded": True}}
            if path == "/v1/embed/prewarm":
                assert body and (body.get("wait") or body.get("sync"))
                return {"ok": True, "already_warm": True, "embedder_loaded": True}
            return {"ok": True}

    monkeypatch.setattr("pipeline.daemon.ensure_daemon", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr("pipeline.client.EngineClient", _Client)
    monkeypatch.setattr(
        "pipeline.session_isolation.mcp_client_name", lambda: "test-host"
    )
    monkeypatch.setattr(
        "pipeline.session_isolation.effective_session_id", lambda _x: "sid"
    )

    out = ml.warm_engine_for_mcp(tmp_path, client_id="mcp:test")
    assert out.get("ok") is True
    assert out.get("embedder_loaded") is True
    assert "/v1/embed/prewarm" in calls
    assert "/v1/client/register" in calls


def test_leave_mcp_client_unregisters_once(monkeypatch, tmp_path: Path) -> None:
    from pipeline import mcp_lifecycle as ml

    posts: list[tuple[str, dict]] = []

    class _Client:
        def __init__(self, **_kw):
            pass

        def post(self, path, body=None):
            posts.append((path, body or {}))
            return {"ok": True, "idle": {"action": "none"}}

    monkeypatch.setattr("pipeline.client.EngineClient", _Client)
    ml._CLIENT_ID = "mcp:once"
    ml._REPO = tmp_path
    ml._LEFT = False

    a = ml.leave_mcp_client(tmp_path, "mcp:once")
    b = ml.leave_mcp_client(tmp_path, "mcp:once")
    assert a.get("ok") is True
    assert b.get("already_left") is True
    assert len([p for p in posts if p[0] == "/v1/client/unregister"]) == 1


def test_attach_installs_leave_hooks(monkeypatch, tmp_path: Path) -> None:
    from pipeline import mcp_lifecycle as ml

    monkeypatch.setattr(
        ml,
        "warm_engine_for_mcp",
        lambda *_a, **_k: {"ok": True, "prewarm_wait": {"ms": 1}},
    )
    spawned: list[object] = []
    monkeypatch.setattr(ml, "_start_heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr(ml, "_install_process_signals", lambda *_a, **_k: None)
    monkeypatch.setattr(
        ml, "spawn_trace_graph_preload", lambda root: spawned.append(root)
    )
    monkeypatch.setattr(
        "pipeline.session_isolation.default_process_session_id",
        lambda: "proc-xyz",
    )
    registered: list[object] = []
    monkeypatch.setattr(
        ml.atexit,
        "register",
        lambda fn: registered.append(fn),
    )

    out = ml.attach_mcp_session(tmp_path)
    assert out["client_id"] == "mcp:proc-xyz"
    assert registered  # leave hooked for any host process exit
    assert spawned  # AST graph warms in the background, not on first map

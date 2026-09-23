"""First MCP request must return warming+retry; never hang or flash consoles."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_client_for_returns_warming_without_force_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setattr(
        "pipeline.mcp_lifecycle.ensure_mcp_runtime",
        lambda *_a, **k: {"ok": True, "deferred": True, "blocking": k.get("blocking")},
    )
    monkeypatch.setattr("pipeline.mcp_lifecycle.current_client_id", lambda: "mcp:t")
    monkeypatch.setattr(
        "pipeline.session_isolation.mcp_client_name", lambda: "cursor"
    )
    monkeypatch.setattr(
        "pipeline.session_isolation.effective_session_id", lambda _x: "s"
    )
    restarts: list[str] = []
    monkeypatch.setattr(
        "pipeline.daemon.force_restart_daemon",
        lambda *_a, **_k: restarts.append("restart") or {"ok": True},
    )

    class _Probe:
        def __init__(self, *a, **k) -> None:  # noqa: ANN002
            pass

        def healthy(self) -> bool:
            return False

        def open_repo(self, *_a, **_k):
            raise AssertionError("open_repo must not run when /health is down")

    monkeypatch.setattr("pipeline.client.EngineClient", _Probe)
    from pipeline.mcp_locate import _client_for

    client = _client_for(tmp_path)
    assert restarts == []
    payload = client.search("where is map")
    assert payload.get("warming") is True
    assert payload.get("should_retry") is True
    assert payload.get("retry_after_s") == 3
    assert payload.get("error") == "engine_warming"


def test_engine_call_tries_search_even_if_health_flaps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Brief /health false must not skip search — soft BM25 can still answer."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setattr(
        "pipeline.mcp_lifecycle.ensure_mcp_runtime",
        lambda *_a, **_k: {"ok": True, "deferred": True},
    )
    monkeypatch.setattr("pipeline.mcp_lifecycle.current_client_id", lambda: None)

    class _Client:
        def __init__(self, *a, **k) -> None:  # noqa: ANN002
            pass

        def healthy(self) -> bool:
            return False

        def search(self, *_a, **_k):
            return {"ok": True, "hits": [{"file": "a.py", "score": 1.0}]}

    monkeypatch.setattr("pipeline.client.EngineClient", _Client)
    from pipeline.context_agent.tools import _engine_call

    out = _engine_call(tmp_path, lambda c: c.search("q"))
    assert out.get("ok") is True
    assert out.get("hits")


def test_engine_call_returns_warming_on_unreachable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setattr(
        "pipeline.mcp_lifecycle.ensure_mcp_runtime",
        lambda *_a, **_k: {"ok": True, "deferred": True},
    )
    monkeypatch.setattr("pipeline.mcp_lifecycle.current_client_id", lambda: None)

    class _Client:
        def __init__(self, *a, **k) -> None:  # noqa: ANN002
            pass

        def search(self, *_a, **_k):
            return {
                "ok": False,
                "error": "Scubiee unreachable at http://127.0.0.1:8765: timed out",
                "should_retry": True,
            }

    monkeypatch.setattr("pipeline.client.EngineClient", _Client)
    from pipeline.context_agent.tools import _engine_call

    out = _engine_call(tmp_path, lambda c: c.search("q"))
    assert out.get("ok") is False
    assert out.get("should_retry") is True
    assert out.get("warming") is True

def test_search_returns_warming_without_blocking_embedder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipeline.ce_service import RuntimeManager

    mgr = RuntimeManager()
    monkeypatch.setattr(mgr, "_gate", lambda *_a, **_k: None)
    monkeypatch.setattr("pipeline.engine.embedder_is_loaded", lambda: False)

    def _boom(*_a, **_k):
        raise AssertionError("ensure_embedder_ready must not block search")

    monkeypatch.setattr("pipeline.engine.ensure_embedder_ready", _boom)
    monkeypatch.setattr(mgr, "_ensure_engine", lambda *_a, **_k: None)
    out = mgr.search("where is map", root=".")
    assert out.get("warming") is True
    assert out.get("should_retry") is True
    assert out.get("error") == "engine_warming"

def test_admit_wait_false_uses_background_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.ce_service import RuntimeManager

    repo = tmp_path / "r"
    repo.mkdir()
    mgr = RuntimeManager()
    runtime = MagicMock()
    runtime.engine = None
    runtime.warm_state = "idle"
    runtime.project_id = "ce_test"
    monkeypatch.setattr(
        "pipeline.repo_lifecycle.activate_repo",
        lambda _root: {
            "ok": True,
            "status": "activated",
            "project_id": "ce_test",
            "root": str(repo),
            "state": "active",
        },
    )
    monkeypatch.setattr(mgr, "_activate_runtime", lambda *_a, **_k: runtime)
    monkeypatch.setattr(mgr, "_auto_limits", lambda: (8, 10_000))
    monkeypatch.setattr(mgr, "_save_active_runtime", lambda: None)
    warmed: list[str] = []
    monkeypatch.setattr(
        mgr,
        "_warm_registered",
        lambda _root: warmed.append("sync") or {"ok": True, "warm_state": "ready"},
    )
    bg: list[bool] = []
    monkeypatch.setattr(
        mgr,
        "open_repo",
        lambda _root, background=False: bg.append(bool(background))
        or {"ok": True, "warming": True, "async": True},
    )
    out = mgr.admit_request(repo, explicit=True, wait=False)
    assert out["status"] == "activated"
    assert bg == [True]
    assert warmed == []


def test_backend_error_warming_payload(tmp_path: Path) -> None:
    from pipeline.mcp_locate import _backend_error

    raw = _backend_error(
        "map",
        tmp_path,
        {
            "ok": False,
            "status": "warming",
            "error": "engine_warming",
            "warming": True,
            "should_retry": True,
            "retry_after_s": 3,
        },
        hint="unused",
    )
    import json

    payload = json.loads(raw)
    assert payload["ok"] is False
    assert payload["warming"] is True
    assert payload["should_retry"] is True
    assert payload["retry_after_s"] == 3
    assert "wait" in str(payload.get("hint") or "").lower()


def test_resolve_child_command_never_uses_uv_console_shim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pipeline.mcp_bridge as bridge

    monkeypatch.setattr(bridge.os, "name", "nt")
    monkeypatch.delenv("CTX_MCP_BRIDGE_SPAWN_JSON", raising=False)
    monkeypatch.delenv("CTX_MCP_BRIDGE_SPAWN", raising=False)
    shim = str(tmp_path / "scubiee-mcp.exe")
    monkeypatch.setattr(bridge.shutil, "which", lambda _name: shim)
    monkeypatch.setattr(
        "pipeline.process_job.background_python",
        lambda: r"C:\fake\pythonw.exe",
    )
    cmd, args = bridge.resolve_child_command()
    assert "scubiee-mcp" not in Path(cmd).name.lower()
    assert Path(cmd).name.lower() == "pythonw.exe"
    assert args == ["-u", "-m", "pipeline.mcp_locate"]


def test_resolve_child_command_rewrites_spawn_json_shim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    import pipeline.mcp_bridge as bridge

    monkeypatch.setattr(bridge.os, "name", "nt")
    monkeypatch.setenv(
        "CTX_MCP_BRIDGE_SPAWN_JSON",
        json.dumps([str(tmp_path / "scubiee-mcp.exe")]),
    )
    monkeypatch.setattr(
        "pipeline.process_job.background_python",
        lambda: r"C:\fake\pythonw.exe",
    )
    cmd, args = bridge.resolve_child_command()
    assert Path(cmd).name.lower() == "pythonw.exe"
    assert args == ["-u", "-m", "pipeline.mcp_locate"]

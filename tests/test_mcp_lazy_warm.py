"""Agent-warm: MCP stdio connect must not spawn engine/watchdog."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


def test_main_engine_run_uses_fast_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import pipeline.__main__ as m

    calls: list[dict] = []
    monkeypatch.setattr("pipeline.lifecycle_guard.guard_engine_action", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "pipeline.server.run_server",
        lambda path, host="127.0.0.1", port=8765, open_on_start=False: calls.append(
            {
                "path": str(path),
                "host": host,
                "port": port,
                "open_on_start": open_on_start,
            }
        ),
    )
    rc = m.main(["engine", "run", str(tmp_path), "--no-open", "--host", "127.0.0.1", "--port", "8765"])
    assert rc == 0
    assert calls == [
        {
            "path": str(tmp_path.resolve()),
            "host": "127.0.0.1",
            "port": 8765,
            "open_on_start": False,
        }
    ]
    monkeypatch.delenv("CTX_WATCHDOG_AUTO_START", raising=False)
    from pipeline.watchdog import watchdog_auto_start_enabled

    assert watchdog_auto_start_enabled() is False
    monkeypatch.setenv("CTX_WATCHDOG_AUTO_START", "1")
    assert watchdog_auto_start_enabled() is True


def test_warm_engine_for_mcp_uses_direct_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import mcp_lifecycle as ml

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    owners: list[str] = []
    monkeypatch.setattr(ml, "_ENSURE_READY_UNTIL", 0.0)
    monkeypatch.setattr("pipeline.daemon.is_running", lambda: False)
    monkeypatch.setattr(
        "pipeline.daemon.ensure_daemon",
        lambda *_a, **k: owners.append(str(k.get("spawn_owner"))) or {"ok": True},
    )

    class _Client:
        def __init__(self, *a, **k) -> None:  # noqa: ANN002
            pass

        def open_repo(self, *_a, **_k):
            return {"ok": True, "warm_state": "ready"}

        def post(self, *_a, **_k):
            return {"ok": True, "embedder_loaded": True, "prewarm": {"ok": True}}

    monkeypatch.setattr("pipeline.client.EngineClient", _Client)
    monkeypatch.setattr("pipeline.session_isolation.mcp_client_name", lambda: "cursor")
    monkeypatch.setattr("pipeline.session_isolation.effective_session_id", lambda _x: "s")
    out = ml.warm_engine_for_mcp(tmp_path, client_id="mcp:x", blocking=True)
    assert owners == ["direct"]
    assert out.get("ok") is True


def test_attach_lazy_does_not_warm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import mcp_lifecycle as ml

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.delenv("CTX_MCP_AUTO_WARM", raising=False)
    # Opt out of attach-warm so this test still covers pure agent-first connect.
    monkeypatch.setenv("CTX_MCP_ATTACH_WARM", "0")
    calls: list[dict] = []
    monkeypatch.setattr(
        ml,
        "warm_engine_for_mcp",
        lambda *_a, **k: calls.append(dict(k)) or {"ok": True},
    )
    monkeypatch.setattr(ml, "_spawn_background_warm", lambda *_a, **_k: None)
    monkeypatch.setattr(ml, "_start_heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr(ml, "_install_process_signals", lambda *_a, **_k: None)
    monkeypatch.setattr(ml.atexit, "register", lambda fn: None)
    monkeypatch.setattr(
        "pipeline.session_isolation.default_process_session_id",
        lambda: "lazy",
    )
    out = ml.attach_mcp_session(tmp_path)
    assert calls == []
    assert out.get("warm_started") is False
    assert out["warm"].get("skipped") == "agent_warm"


def test_attach_warm_default_kicks_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import mcp_lifecycle as ml
    from pipeline.runtime_controller import RuntimeController, ReadySnapshot

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.delenv("CTX_MCP_AUTO_WARM", raising=False)
    monkeypatch.setenv("CTX_MCP_ATTACH_WARM", "1")
    RuntimeController.reset_for_tests()
    kicks: list[str] = []

    def fake_ensure(repo, reason, **kwargs):
        kicks.append(reason)
        return ReadySnapshot(
            state="STARTING",
            engine_ok=False,
            embedder_loaded=False,
            ast_ready=False,
        )

    monkeypatch.setattr(RuntimeController.get(), "ensure", fake_ensure)
    monkeypatch.setattr(ml, "_start_heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr(ml, "_heartbeat_alive", lambda: False)
    monkeypatch.setattr(ml, "_install_process_signals", lambda *_a, **_k: None)
    monkeypatch.setattr(ml.atexit, "register", lambda fn: None)
    monkeypatch.setattr(
        "pipeline.session_isolation.default_process_session_id",
        lambda: "attach",
    )
    out = ml.attach_mcp_session(tmp_path)
    assert kicks == ["attach"]
    assert out.get("warm_started") is True
    assert out["warm"].get("attach_warm", {}).get("started") is True


def test_ensure_mcp_runtime_warms_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import mcp_lifecycle as ml

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.delenv("CTX_MCP_AUTO_WARM", raising=False)
    monkeypatch.setattr(ml, "_CLIENT_ID", "mcp:lazy")
    monkeypatch.setattr(ml, "_HEARTBEAT_THREAD", None)
    hearts: list[str] = []
    monkeypatch.setattr(
        ml,
        "_start_heartbeat",
        lambda root, cid: hearts.append(cid),
    )
    monkeypatch.setattr(ml, "_heartbeat_alive", lambda: False)
    spawned: list[str] = []
    monkeypatch.setattr(
        ml,
        "_spawn_background_warm",
        lambda *_a, **_k: spawned.append("bg"),
    )
    calls: list[dict] = []
    monkeypatch.setattr(
        ml,
        "warm_engine_for_mcp",
        lambda *_a, **k: calls.append(dict(k)) or {"ok": True, "embedder_loaded": True},
    )
    out = ml.ensure_mcp_runtime(tmp_path, client_id="mcp:lazy", blocking=True)
    assert calls and calls[0].get("blocking") is True
    assert spawned == []
    assert hearts == ["mcp:lazy"]
    assert out.get("ok") is True


def test_ensure_mcp_runtime_defaults_nonblocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import mcp_lifecycle as ml

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setattr(ml, "_CLIENT_ID", "mcp:lazy")
    monkeypatch.setattr(ml, "_HEARTBEAT_THREAD", None)
    monkeypatch.setattr(ml, "_start_heartbeat", lambda *_a, **_k: None)
    monkeypatch.setattr(ml, "_heartbeat_alive", lambda: True)
    spawned: list[str] = []
    monkeypatch.setattr(
        ml,
        "_spawn_background_warm",
        lambda *_a, **_k: spawned.append("bg"),
    )
    calls: list[dict] = []
    monkeypatch.setattr(
        ml,
        "warm_engine_for_mcp",
        lambda *_a, **k: calls.append(dict(k)) or {"ok": True, "deferred": True},
    )
    out = ml.ensure_mcp_runtime(tmp_path, client_id="mcp:lazy")
    assert calls and calls[0].get("blocking") is False
    assert spawned == ["bg"]
    assert out.get("ok") is True


def test_boot_mcp_worker_skips_ensure_when_lazy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.delenv("CTX_MCP_AUTO_WARM", raising=False)
    import pipeline.mcp_locate as loc

    ensures: list[str] = []
    monkeypatch.setattr(
        "pipeline.mcp_hot_reload.adopt_installed_package_on_connect",
        lambda **k: {"ok": True, "restart_stale": k.get("restart_stale")},
    )
    monkeypatch.setattr(
        "pipeline.daemon.ensure_daemon",
        lambda *_a, **_k: ensures.append("ensure") or {"ok": True},
    )
    monkeypatch.setattr(loc, "_register_mcp_client", lambda repo: "mcp:x")
    out = loc.boot_mcp_worker(tmp_path)
    assert out.get("auto_warm") is False
    assert ensures == []
    assert out.get("adopt", {}).get("restart_stale") is False


def test_adopt_lazy_does_not_restart_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.mcp_hot_reload import adopt_installed_package_on_connect

    monkeypatch.setattr(
        "pipeline.upgrade.installed_version", lambda: "0.3.70"
    )
    monkeypatch.setattr(
        "pipeline.mcp_hot_reload.read_active_build_stamp",
        lambda: {"version": "0.3.70"},
    )
    monkeypatch.setattr(
        "pipeline.mcp_hot_reload.current_build_id", lambda: "x"
    )
    restarted: list[str] = []
    monkeypatch.setattr(
        "pipeline.upgrade.restart_daemon_if_stale",
        lambda: restarted.append("restart") or {"ok": True},
    )
    monkeypatch.setattr("pipeline.upgrade.daemon_version_matches", lambda: False)
    out = adopt_installed_package_on_connect(restart_stale=False)
    assert restarted == []
    assert out["daemon"].get("action") == "deferred_agent_warm"

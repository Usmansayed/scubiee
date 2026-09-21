"""Locate-worker prewarm — first map ≤1s after attach settle."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _reset_prewarm(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import pipeline.mcp_lifecycle as life

    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.delenv("CTX_MCP_BRIDGE", raising=False)
    life._LOCATE_PREWARM_DONE.clear()
    life._LOCATE_PREWARM_RESULT = {}
    life._LOCATE_PREWARM_THREAD = None
    life._SOFT_READY_UNTIL = 0.0
    life._LOCATE_DUMMY_SEARCH_ARMED = False
    life._LAST_SEARCH_PROBE_OK_AT = 0.0
    yield
    life._LOCATE_PREWARM_DONE.clear()
    life._LOCATE_DUMMY_SEARCH_ARMED = False
    life._LAST_SEARCH_PROBE_OK_AT = 0.0


def test_prewarm_locate_worker_marks_soft_and_imports(monkeypatch, tmp_path: Path) -> None:
    import pipeline.mcp_lifecycle as life

    monkeypatch.setattr(life, "_preload_locate_imports", lambda: {"ok": True, "elapsed_ms": 1.0})
    monkeypatch.setattr(
        life,
        "warm_engine_for_mcp",
        lambda *_a, **_k: {"ok": True, "soft_search_ready": True},
    )

    client = MagicMock()
    client.health.return_value = {
        "ok": True,
        "service": True,
        "soft_search_ready": True,
        "chunks": 12,
    }
    client.post.return_value = {"ok": True, "started": True}
    client.search.return_value = {"ok": True, "hits": [{"file": "a.py"}]}

    import pipeline.client as cli

    monkeypatch.setattr(cli, "EngineClient", lambda **_k: client)
    # AST hydrate may import context_trace — keep soft path free of dense search.
    monkeypatch.setattr(
        "pipeline.context_trace.hydrate_ast_bundle",
        lambda *_a, **_k: {"ok": True, "source": "test"},
    )

    out = life.prewarm_locate_worker(tmp_path, deadline_s=2.0)
    assert out.get("ok") is True
    assert life.soft_ready_cached() is True
    assert life.locate_worker_prewarm_done() is True
    assert client.health.called
    assert not client.search.called  # soft-only probe (dense search would GIL-starve settle)
    assert (out.get("probe") or {}).get("soft_only") is True
    assert client.post.called  # async /v1/embed/prewarm kick
    # AST is deferred until dense is up (health had no embedder_loaded).
    assert (out.get("ast") or {}).get("skipped") is True or (out.get("ast") or {}).get(
        "reason"
    ) == "defer_until_dense"


def test_prewarm_skipped_in_bridge(monkeypatch, tmp_path: Path) -> None:
    import pipeline.mcp_lifecycle as life

    monkeypatch.setenv("CTX_MCP_BRIDGE", "1")
    out = life.prewarm_locate_worker(tmp_path)
    assert out.get("skipped") == "bridge"
    assert life.locate_worker_prewarm_done() is True


def test_mark_soft_ready_default_ttl_long(monkeypatch) -> None:
    import pipeline.mcp_lifecycle as life
    import time

    monkeypatch.setattr(life, "_SOFT_READY_TTL_S", 300.0)
    life.mark_soft_ready()
    assert life._SOFT_READY_UNTIL >= time.time() + 290.0


def test_kick_dummy_search_once_is_idempotent(monkeypatch, tmp_path: Path) -> None:
    import pipeline.mcp_lifecycle as life

    calls: list[int] = []

    class _Client:
        def __init__(self, **_k):
            pass

        def post(self, *_a, **_k):
            return {"ok": True, "tick": False, "status": {"last_retrieve_ok": False}}

        def search(self, *_a, **_k):
            calls.append(1)
            return {"ok": True, "hits": []}

    class _InlineThread:
        def __init__(self, target=None, **_k):
            self._target = target

        def start(self):
            if self._target is not None:
                self._target()

    monkeypatch.setattr("pipeline.client.EngineClient", _Client)
    monkeypatch.setattr(life.threading, "Thread", _InlineThread)
    life._kick_dummy_search_once(tmp_path)
    life._kick_dummy_search_once(tmp_path)
    assert calls == [1]


def test_kick_dummy_search_skipped_in_bridge(monkeypatch, tmp_path: Path) -> None:
    import pipeline.mcp_lifecycle as life

    monkeypatch.setenv("CTX_MCP_BRIDGE", "1")
    calls: list[int] = []

    class _Client:
        def __init__(self, **_k):
            pass

        def search(self, *_a, **_k):
            calls.append(1)
            return {"ok": True}

    monkeypatch.setattr("pipeline.client.EngineClient", _Client)
    life._kick_dummy_search_once(tmp_path)
    assert calls == []
    assert life._LOCATE_DUMMY_SEARCH_ARMED is False


def test_kick_dummy_search_skips_when_keepalive_retrieve_warm(
    monkeypatch, tmp_path: Path
) -> None:
    import time

    import pipeline.mcp_lifecycle as life

    monkeypatch.delenv("CTX_MCP_BRIDGE", raising=False)
    life._LOCATE_DUMMY_SEARCH_ARMED = False
    life._LAST_SEARCH_PROBE_OK_AT = 0.0
    searches: list[int] = []

    class _Client:
        def __init__(self, **_k):
            pass

        def post(self, path, _body=None):
            assert "keepalive" in path
            return {
                "ok": True,
                "tick": False,
                "status": {
                    "last_retrieve_ok": True,
                    "last_at": time.time(),
                },
            }

        def search(self, *_a, **_k):
            searches.append(1)
            return {"ok": True}

    monkeypatch.setattr("pipeline.client.EngineClient", _Client)
    life._kick_dummy_search_once(tmp_path)
    assert searches == []
    assert life._LOCATE_DUMMY_SEARCH_ARMED is True
    assert life.search_probe_fresh(max_age_s=30.0) is True
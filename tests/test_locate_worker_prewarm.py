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
    yield
    life._LOCATE_PREWARM_DONE.clear()


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

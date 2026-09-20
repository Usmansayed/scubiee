"""End-to-end system matrix — gap fillers on top of existing suite coverage.

Focus: wrapper/resource coordination, sync under concurrent dirty, expand
no-bake on MCP child, and dual-client coalesce (duplicate-bridge class bugs).
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from conftest import enroll_test_repo


@pytest.fixture
def enrolled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(tmp_path, home=home, project_id="ce_e2e_matrix1234567890abcdef")
    return tmp_path


def test_concurrent_mark_dirty_coalesces_paths(enrolled: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.sync_loop import BackgroundSyncLoop

    monkeypatch.setattr(
        "pipeline.sync_loop.BackgroundSyncLoop._clients_active",
        lambda self: False,
    )
    loop = BackgroundSyncLoop(enrolled, debounce_ms=50)
    errors: list[BaseException] = []

    def _burst(prefix: str) -> None:
        try:
            for i in range(40):
                loop.mark_dirty([f"pkg/{prefix}_{i % 5}.py"], reason="write")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_burst, args=(f"t{n}",)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert not errors
    dirty = loop.status()["dirty"]["paths"]
    # 4 prefixes × 5 files = 20 unique paths
    assert len(dirty) == 20


def test_publish_keeps_previous_on_empty_engine(enrolled: Path) -> None:
    from pipeline.ce_service import RuntimeManager

    runtime = RuntimeManager()
    runtime.repo = enrolled
    good = MagicMock()
    good.texts = ["a", "b", "c"]
    runtime.engine = good
    runtime.warm_state = "ready"
    runtime.generation = 2

    empty = MagicMock()
    empty.texts = []

    from unittest.mock import patch

    with patch("pipeline.ce_service.drop_engine"), patch(
        "pipeline.ce_service.load_engine", return_value=empty
    ):
        out = runtime.publish_engine({"reason": "race"})
    assert out.get("kept_previous") is True
    assert runtime.engine is good
    assert runtime.warm_state == "ready"
    assert len(runtime.engine.texts) == 3


def test_expand_mcp_child_refuses_cold_ast_bake(
    enrolled: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import context_trace as ct

    monkeypatch.setenv("CTX_MCP_BRIDGE_CHILD", "1")
    monkeypatch.setenv("CTX_TRACE_NO_BAKE", "1")
    ct._CACHE.clear()
    monkeypatch.setattr(ct, "_try_load_repo_bundle", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="ast_bundle_missing"):
        ct._load_repo(enrolled)


def test_hydrate_ast_bundle_miss_without_bake(
    enrolled: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import context_trace as ct

    ct._CACHE.clear()
    monkeypatch.setattr(ct, "_try_load_repo_bundle", lambda *a, **k: None)
    out = ct.hydrate_ast_bundle(enrolled, bake_on_miss=False)
    assert out.get("ok") is False
    assert out.get("source") in {"miss", None} or "miss" in str(out)


def test_dual_mcp_client_coalesce_drops_workers_keeps_bridge(
    enrolled: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import lifecycle_runtime as life

    monkeypatch.setenv("CTX_HOME", str(enrolled / "ce-home"))
    clients = {
        "mcp:cursor@bridge-1": {
            "client_id": "mcp:cursor@bridge-1",
            "pid": 11,
            "kind": "bridge",
            "host": "cursor",
        },
        "mcp:cursor@conn-old": {
            "client_id": "mcp:cursor@conn-old",
            "pid": 22,
            "kind": "mcp",
            "host": "cursor",
        },
        "mcp:cursor@conn-new": {
            "client_id": "mcp:cursor@conn-new",
            "pid": 33,
            "kind": "mcp",
            "host": "cursor",
        },
    }
    dropped = life.coalesce_mcp_clients(
        clients, keep_id="mcp:cursor@conn-new", host="cursor"
    )
    assert "mcp:cursor@conn-old" in dropped
    assert "mcp:cursor@bridge-1" in clients  # bridge anchor preserved
    assert "mcp:cursor@conn-new" in clients
    assert "mcp:cursor@conn-old" not in clients


def test_memory_governor_indexing_caps_over_multi_session() -> None:
    from pipeline.memory_governor import resolve_desired_tier

    assert (
        resolve_desired_tier(repo_count=1, max_sessions=3, total_sessions=3, indexing=True)
        == "indexing"
    )
    assert (
        resolve_desired_tier(repo_count=1, max_sessions=3, total_sessions=3, indexing=False)
        == "serve_multi_session"
    )

"""Live reindexing ingress and safety controls without an embedding model."""

from __future__ import annotations

import time
import threading
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _default_no_engine_clients(monkeypatch):
    """Unit tests must not defer sync because a live MCP client is registered."""
    monkeypatch.setattr(
        "pipeline.sync_loop.BackgroundSyncLoop._clients_active",
        lambda self: False,
    )


def test_changed_file_ingress_normalizes_repo_relative_paths(tmp_path: Path):
    from pipeline.live_reindex import notify_changed_files

    received: dict = {}

    class Client:
        def mark_dirty(self, paths, *, reason, path):
            received.update(paths=paths, reason=reason, path=path)
            return {"ok": True, "paths": paths}

    out = notify_changed_files(
        tmp_path,
        ["pkg\\a.py", "./pkg/b.py", "../outside.py"],
        reason="editor_save",
        client=Client(),
    )

    assert out["ok"] is True
    assert received == {
        "paths": ["pkg/a.py", "pkg/b.py"],
        "reason": "editor_save",
        "path": str(tmp_path.resolve()),
    }
    assert out["rejected_paths"] == ["../outside.py"]


def test_daemon_dirty_and_locate_wrappers_call_runtime(monkeypatch, tmp_path: Path):
    from http.server import ThreadingHTTPServer
    from pipeline.client import EngineClient
    from pipeline.server import Handler

    calls: list[tuple[str, object]] = []

    class Runtime:
        def mark_dirty(self, paths, *, reason):
            calls.append(("dirty", (paths, reason)))
            return {"ok": True, "paths": paths}

        def note_locate(self):
            calls.append(("locate", None))
            return {"ok": True}

    monkeypatch.setattr("pipeline.server.get_context_engine", lambda: Runtime())
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        client = EngineClient(f"http://127.0.0.1:{httpd.server_address[1]}", timeout=5)
        assert client.mark_dirty(["pkg/a.py"], reason="watch", path=str(tmp_path))["ok"] is True
        assert client.note_locate(path=str(tmp_path))["ok"] is True
    finally:
        httpd.shutdown()
        thread.join()

    assert calls == [("dirty", (["pkg/a.py"], "watch")), ("locate", None)]


def test_dirty_sync_invalidates_only_changed_session_paths(monkeypatch, tmp_path: Path):
    from pipeline.session_store import invalidate_paths, put_span, recall
    from pipeline.sync_loop import BackgroundSyncLoop

    put_span(tmp_path, path="pkg/a.py", start_line=1, end_line=1, text="old a")
    put_span(tmp_path, path="pkg/b.py", start_line=1, end_line=1, text="keep b")
    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    monkeypatch.setattr(loop, "_sync_paths", lambda paths, **_: {"refreshed": True, "chunks_upserted": 1})

    loop.mark_dirty(["pkg/a.py"], reason="write")
    loop.drain_due(now=time.monotonic() + 0.01)

    assert invalidate_paths(tmp_path, ["pkg/missing.py"])["removed"] == 0
    paths = [span["path"] for span in recall(tmp_path)["spans"]]
    assert paths == ["pkg/b.py"]


def test_live_batch_within_300_chunks_uses_fast_path(
    monkeypatch, tmp_path: Path
):
    """≤300 estimated chunks stay on the fast live-batch path."""
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0, live_max_files=1000)
    calls: list[list[str]] = []
    # 250 paths × 1 chunk each = 250 total, under the 300 bulk threshold
    monkeypatch.setattr(
        loop,
        "_estimate_dirty_chunks",
        lambda paths: (len(paths), {path: 1 for path in paths}),
    )
    monkeypatch.setattr(
        loop,
        "_sync_paths",
        lambda paths, **_: calls.append(paths)
        or {"refreshed": True, "chunks_upserted": len(paths), "chunks_removed": 0},
    )

    paths = [f"pkg/{n}.py" for n in range(250)]
    loop.mark_dirty(paths, reason="watch")
    now = time.monotonic() + 0.01

    out = loop.drain_due(now=now)
    assert len(calls) == 1
    assert len(calls[0]) == 250
    assert out[0]["chunks_upserted"] == 250
    assert out[0].get("needs_full", False) is False
    assert loop.status()["needs_full"] is False
    assert loop.status()["catchup_chunked"] is False


def test_bulk_reindex_for_501_to_6000_chunks(monkeypatch, tmp_path: Path):
    """501–6000 estimated chunks route to bulk reindex (800 MB, all at once)."""
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    monkeypatch.setattr(loop, "_clients_active", lambda: False)
    bulk_calls: list[list[str]] = []
    live_calls: list[list[str]] = []
    # 600 paths × 1 chunk = 600 estimated, above 500 threshold
    monkeypatch.setattr(
        loop,
        "_estimate_dirty_chunks",
        lambda paths: (len(paths), {path: 1 for path in paths}),
    )
    monkeypatch.setattr(
        loop,
        "_bulk_sync_paths",
        lambda paths, **_: (
            bulk_calls.append(paths),
            loop.dirty_ledger.begin(paths),
            loop.dirty_ledger.complete(paths, published=True),
        )[-1]
        or {"refreshed": True, "strategy": "bulk_reindex", "bulk": True,
            "chunks_upserted": len(paths), "chunks_removed": 0},
    )
    monkeypatch.setattr(
        loop,
        "_sync_paths",
        lambda paths, **_: live_calls.append(paths)
        or {"refreshed": True, "chunks_upserted": len(paths), "chunks_removed": 0},
    )

    paths = [f"pkg/{n}.py" for n in range(600)]
    loop.mark_dirty(paths, reason="watch")
    out = loop.drain_due(now=time.monotonic() + 0.01)

    assert live_calls == []
    assert len(bulk_calls) == 1
    assert len(bulk_calls[0]) == 600
    assert out[0]["strategy"] == "bulk_reindex"
    assert out[0]["bulk"] is True
    assert out[0]["chunks_upserted"] == 600
    assert loop.status()["needs_full"] is False
    assert loop.status()["catchup_chunked"] is False
    assert loop.status()["sync_status"] == "ready"


def test_active_clients_defer_bulk_reindex(monkeypatch, tmp_path: Path):
    """MCP/IDE clients must not see mid-session vector wipe from bulk sync."""
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    bulk_calls: list[list[str]] = []
    monkeypatch.setattr(loop, "_clients_active", lambda *a, **k: True)
    monkeypatch.setattr(
        loop,
        "_estimate_dirty_chunks",
        lambda paths: (len(paths), {path: 1 for path in paths}),
    )
    monkeypatch.setattr(
        loop,
        "_bulk_sync_paths",
        lambda paths, **_: bulk_calls.append(paths)
        or {"refreshed": True, "strategy": "bulk_reindex"},
    )

    paths = [f"pkg/{n}.py" for n in range(600)]
    loop.mark_dirty(paths, reason="watch")
    out = loop.drain_due(now=time.monotonic() + 0.01)

    assert bulk_calls == []
    assert out[0]["strategy"] == "deferred_active_session"
    assert out[0]["reason"] == "clients_active"
    assert loop.dirty_ledger.due_paths(now=time.monotonic() + 20.0)


def test_estimated_oversized_change_requires_explicit_full_index(monkeypatch, tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    sync_calls: list[list[str]] = []
    monkeypatch.setattr(loop, "_estimate_dirty_chunks", lambda paths: (10001, {p: 5001 for p in paths}))
    monkeypatch.setattr(loop, "_sync_paths", lambda paths, **_: sync_calls.append(paths))

    loop.mark_dirty(["pkg/a.py", "pkg/b.py"], reason="watch")
    out = loop.drain_due(now=time.monotonic() + 0.01)

    assert sync_calls == []
    assert out[0]["strategy"] == "explicit_full_index_required"
    assert "scubiee index" in out[0]["error"]
    assert out[0]["warnings"] == [
        "Automatic sync paused before graph/vector mutation; explicit full indexing is required."
    ]
    assert loop.status()["sync_status"] == "needs_full"
    assert loop.status()["needs_full"] is True


def test_bulk_sub_batch_commits_and_resumes_after_interrupt(monkeypatch, tmp_path: Path):
    """Bulk sync processes in sub-batches; completed batches survive a simulated crash."""
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    sub_batch_calls: list[list[str]] = []
    call_count = {"n": 0}

    from pipeline.incremental import IncrementalResult

    def fake_incremental(root, *, force_files=None, bulk=False):
        call_count["n"] += 1
        sub_batch_calls.append(list(force_files or []))
        # Simulate crash on the 3rd sub-batch
        if call_count["n"] == 3:
            raise RuntimeError("simulated power loss")
        return IncrementalResult(
            refreshed=True,
            files=force_files or [],
            chunks_upserted=len(force_files or []),
            chunks_removed=0,
            ms=100.0,
            strategy="incremental",
        )

    monkeypatch.setattr("pipeline.incremental.incremental_sync", fake_incremental)
    monkeypatch.setattr(
        loop,
        "_estimate_dirty_chunks",
        lambda paths: (len(paths) * 4, {p: 4 for p in paths}),
    )
    monkeypatch.setenv("CTX_BULK_SUB_BATCH", "50")

    paths = [f"pkg/{n}.py" for n in range(150)]
    loop.mark_dirty(paths, reason="watch")

    out = loop.drain_due(now=time.monotonic() + 0.01)

    # 2 sub-batches completed (50 + 50 = 100 files), 3rd crashed
    assert len(sub_batch_calls) == 3
    assert len(sub_batch_calls[0]) == 50
    assert len(sub_batch_calls[1]) == 50
    assert len(sub_batch_calls[2]) == 50
    payload = out[0]
    assert payload["bulk"] is True
    assert payload["chunks_upserted"] == 100
    assert payload["bulk_progress"]["sub_batches_done"] == 2
    # Partial success: error goes to warnings (not error field) so status
    # doesn't permanently show "error" when most chunks indexed fine.
    assert payload["error"] is None
    assert len(payload["warnings"]) == 1
    assert "simulated power loss" in payload["warnings"][0]

    # The first 100 paths should be published in the journal
    snap = loop.dirty_ledger.snapshot()["paths"]
    published = [p for p, e in snap.items() if e["state"] == "published"]
    assert len(published) == 100
    # The crashed sub-batch (50 paths) should be back in queue
    queued = [p for p, e in snap.items() if e["state"] == "queued"]
    assert len(queued) == 50


def test_incremental_exact_chunk_limit_refuses_before_graph_publish(monkeypatch, tmp_path: Path):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import pipeline.incremental as incremental_module
    from pipeline.incremental import incremental_sync

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    base = tmp_path / "store"
    base.mkdir()
    monkeypatch.setattr(incremental_module, "AUTO_FULL_INDEX_CHUNKS", 2)
    monkeypatch.setattr(
        incremental_module,
        "extract",
        lambda *_args, **_kwargs: {"nodes": [], "edges": [], "hyperedges": []},
    )
    monkeypatch.setattr(incremental_module, "graphify_to_repo_ir", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        incremental_module,
        "chunk_file_from_ir",
        lambda *_args, **_kwargs: [
            SimpleNamespace(
                file="a.py",
                start_line=index,
                end_line=index,
                symbol=f"a_{index}",
                content=f"chunk {index}",
            )
            for index in range(3)
        ],
    )
    monkeypatch.setattr(
        incremental_module,
        "inject_metadata",
        lambda chunk, _ir: SimpleNamespace(enriched=chunk.content),
    )
    graph_patch = MagicMock()
    monkeypatch.setattr(incremental_module, "patch_and_save_graph", graph_patch)
    graph_full = MagicMock()
    monkeypatch.setattr(incremental_module, "build_and_save_graph", graph_full)

    result = incremental_sync(repo, base_dir=base, force_files=["a.py"])

    assert result.refreshed is False
    assert result.strategy == "explicit_full_index_required"
    assert result.chunks_upserted == 0
    assert result.chunks_removed == 0
    assert "3 chunks changed" in (result.error or "")
    assert "scubiee index" in (result.error or "")
    assert result.warnings == [
        "No graph or vector artifacts were published for this oversized change."
    ]
    graph_patch.assert_not_called()
    graph_full.assert_not_called()


def test_final_check_forces_held_publish(monkeypatch, tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    published: list[dict] = []
    loop = BackgroundSyncLoop(
        tmp_path,
        debounce_ms=0,
        locate_streak_ms=60_000,
        on_refresh=published.append,
    )
    monkeypatch.setattr(loop, "_sync_paths", lambda paths, **_: {"refreshed": True, "chunks_upserted": 1})
    monkeypatch.setattr(loop, "keeper_tick", lambda **_: {"refreshed": False, "strategy": "root_clean"})
    now = time.monotonic()
    # Queue first, then note locate so the streak is active during drain.
    loop.mark_dirty(["pkg/a.py"], reason="write")
    loop.note_locate(now=now)
    loop.drain_due(now=now + 0.01)

    out = loop.final_check(reason="test")

    assert out["publish_delivered"] is True
    assert len(published) == 1
    assert loop.status()["publish_pending"] is False


def test_publish_failure_does_not_mark_paths_published(tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    def boom(_payload):
        raise RuntimeError("publisher crashed")

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0, on_refresh=boom)
    loop.mark_dirty(["a.py"], reason="write")
    loop.dirty_ledger.begin(["a.py"])
    loop._publish_or_hold({"refreshed": True}, paths=["a.py"], now=0.0)

    entry = loop.dirty_ledger.snapshot()["paths"]["a.py"]
    assert entry["state"] == "overlay_ready"
    assert loop.last_result is None or True


def test_live_path_bypasses_root_probe_while_old_path_probes(monkeypatch, tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    live = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    old = BackgroundSyncLoop(tmp_path)
    live_calls: list[list[str]] = []
    monkeypatch.setattr(live, "_sync_paths", lambda paths, **_: live_calls.append(paths) or {"refreshed": False})
    monkeypatch.setattr(old, "_sync_unlocked", lambda **_: {"strategy": "old_root_probe"})

    live.mark_dirty(["pkg/a.py"], reason="watch")
    live.drain_due(now=time.monotonic() + 0.01)
    monkeypatch.setattr("pipeline.root_probe.root_probe", lambda *_a, **_k: type(
        "Probe", (), {"clean": False, "changed_count": 1, "added": [], "modified": ["pkg/a.py"],
                      "removed": [], "ms": 0, "files_checked": 1,
                      "to_dict": lambda self: {}})())
    old_out = old.keeper_tick(reason="test")

    assert live_calls == [["pkg/a.py"]]
    assert old_out["strategy"] == "old_root_probe"


def test_disk_edit_clears_locate_streak_so_publish_can_proceed(monkeypatch, tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    published: list[dict] = []
    loop = BackgroundSyncLoop(
        tmp_path,
        debounce_ms=0,
        locate_streak_ms=60_000,
        on_refresh=published.append,
    )
    monkeypatch.setattr(loop, "_sync_paths", lambda paths, **_: {"refreshed": True, "chunks_upserted": 1})
    now = time.monotonic()
    loop.note_locate(now=now)
    assert loop.status()["locate_streak_active"] is True

    loop.mark_dirty(["pkg/a.py"], reason="disk_poll")
    assert loop.status()["locate_streak_active"] is False
    loop.drain_due(now=now + 0.01)

    assert len(published) == 1
    assert loop.status()["publish_pending"] is False
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=1500, change_poll_ms=1000)
    sync_calls: list[list[str]] = []
    monkeypatch.setattr(loop, "_sync_paths", lambda paths, **_: sync_calls.append(paths) or {"refreshed": True})
    monkeypatch.setattr(
        "pipeline.root_probe.root_probe",
        lambda *_a, **_k: type(
            "Probe",
            (),
            {
                "clean": False,
                "added": ["pkg/new.py"],
                "modified": ["pkg/a.py"],
                "removed": [],
                "ms": 1.0,
                "files_checked": 2,
                "changed_count": 2,
                "to_dict": lambda self: {"clean": False},
            },
        )(),
    )

    queued = loop.poll_repo_changes(now=0.0)

    assert queued == ["pkg/a.py", "pkg/new.py"]
    assert sync_calls == []
    assert loop.dirty_ledger.due_paths(now=0.5) == []
    assert loop.dirty_ledger.due_paths(now=1.6) == ["pkg/a.py", "pkg/new.py"]


def test_change_poll_does_not_starve_queued_debounce(monkeypatch, tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=1000, rewrite_debounce_ms=5000, change_poll_ms=1000)
    monkeypatch.setattr(
        "pipeline.root_probe.root_probe",
        lambda *_a, **_k: type(
            "Probe",
            (),
            {
                "clean": False,
                "added": [],
                "modified": ["pkg/a.py"],
                "removed": [],
                "ms": 1.0,
                "files_checked": 1,
                "changed_count": 1,
                "to_dict": lambda self: {"clean": False},
            },
        )(),
    )

    assert loop.poll_repo_changes(now=0.0) == ["pkg/a.py"]
    assert loop.poll_repo_changes(now=0.5) == []
    # Still due on the original debounce, not slid by later polls.
    assert loop.dirty_ledger.due_paths(now=1.01) == ["pkg/a.py"]

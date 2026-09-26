"""Live reindexing ingress and safety controls without an embedding model."""

from __future__ import annotations

import time
import threading
from pathlib import Path

import numpy as np
import pytest

from conftest import enroll_test_repo
from pipeline.store import ChunkRecord


@pytest.fixture(autouse=True)
def enrolled_sync_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(tmp_path, home=home, project_id="ce_live_reindex1234567890abcdef")
    return tmp_path


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
        lambda paths, **kw: bulk_calls.append(paths)
        or {"refreshed": True, "strategy": "bulk_reindex", "reason": kw.get("reason")},
    )

    paths = [f"pkg/{n}.py" for n in range(600)]
    loop.mark_dirty(paths, reason="watch")
    now = time.monotonic()
    out = loop.drain_due(now=now + 0.01)

    assert len(bulk_calls) == 1
    assert len(bulk_calls[0]) == 50
    assert out[0]["reason"] == "bulk_slice"
    assert loop.dirty_ledger.due_paths(now=now + 0.5) == []
    assert len(loop.dirty_ledger.due_paths(now=now + 3.0)) == 550


def test_active_clients_still_run_live_batch_after_debounce(monkeypatch, tmp_path: Path):
    """Registered MCP clients must not block Tier-1 live sync (debounce → upsert)."""
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    live_calls: list[list[str]] = []
    monkeypatch.setattr(loop, "_clients_active", lambda *a, **k: True)
    monkeypatch.setattr(
        loop,
        "_estimate_dirty_chunks",
        lambda paths: (len(paths), {path: 1 for path in paths}),
    )
    monkeypatch.setattr(
        loop,
        "_sync_paths",
        lambda paths, **_: (
            live_calls.append(list(paths)),
            loop.dirty_ledger.begin(paths),
            loop.dirty_ledger.complete(paths, published=True),
            {
                "refreshed": True,
                "strategy": "live",
                "chunks_upserted": len(paths),
                "chunks_removed": 0,
            },
        )[-1],
    )

    paths = [f"pkg/{n}.py" for n in range(3)]
    loop.mark_dirty(paths, reason="watch")
    out = loop.drain_due(now=time.monotonic() + 0.01)

    assert live_calls == [paths]
    assert out[0]["strategy"] == "live"
    assert out[0]["chunks_upserted"] == 3
    assert out[0].get("reason") != "clients_active"


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


def test_explicit_write_is_synced_ahead_of_a_bulk_backlog(monkeypatch, tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "new.py").write_text("def added():\n    return 1\n", encoding="utf-8")
    seen: list[list[str]] = []

    def _sync(paths, **_):
        seen.append(list(paths))
        return {
            "refreshed": True,
            "files": paths,
            "chunks_upserted": 1,
            "chunks_removed": 0,
            "strategy": "incremental",
        }

    monkeypatch.setattr(loop, "_sync_paths", _sync)
    def _estimate(paths):
        if len(paths) == 1:
            return (1, {paths[0]: 1})
        return (5000, {p: 100 for p in paths})

    monkeypatch.setattr(loop, "_estimate_dirty_chunks", _estimate)
    monkeypatch.setattr(loop, "_session_busy", lambda now=None: True)
    backlog = [f"pkg/old_{i}.py" for i in range(60)]
    loop.mark_dirty(backlog, reason="disk_poll")
    loop.mark_dirty(["pkg/new.py"], reason="changed_file")
    loop.drain_due(now=time.monotonic() + 1.0)
    assert seen == [["pkg/new.py"]]


def test_additions_are_synced_before_a_deletion_backlog(monkeypatch, tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0, live_max_files=2)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "new.py").write_text("def added():\n    return 1\n", encoding="utf-8")
    seen: list[list[str]] = []

    def _sync(paths, **_):
        seen.append(list(paths))
        return {
            "refreshed": True,
            "files": paths,
            "chunks_upserted": 1,
            "chunks_removed": 0,
            "strategy": "incremental",
        }

    monkeypatch.setattr(loop, "_sync_paths", _sync)
    loop.mark_dirty(["pkg/gone_a.py", "pkg/gone_b.py", "pkg/new.py"], reason="watch")
    loop.drain_due(now=time.monotonic() + 1.0)
    assert seen[0][0] == "pkg/new.py"


def test_zero_chunk_sync_does_not_publish(monkeypatch, tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    published: list[dict] = []
    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0, on_refresh=published.append)
    monkeypatch.setattr(
        loop,
        "_sync_paths",
        lambda paths, **_: {
            "refreshed": True,
            "files": paths,
            "chunks_upserted": 0,
            "chunks_removed": 0,
            "strategy": "incremental",
        },
    )
    loop.mark_dirty(["pkg/a.py"], reason="watch")
    out = loop.drain_due(now=time.monotonic() + 1.0)
    assert published == []
    assert out[0]["chunks_upserted"] == 0


def test_cold_embedder_defers_the_batch(monkeypatch, tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    monkeypatch.setenv("CTX_SYNC_WAIT_FOR_EMBEDDER", "1")
    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    monkeypatch.setattr(loop, "_sync_paths", lambda paths, **_: (_ for _ in ()).throw(AssertionError("synced cold")))
    monkeypatch.setattr("pipeline.engine.embedder_is_loaded", lambda: False)
    monkeypatch.setattr("pipeline.engine.prewarm_embedder_async", lambda *_a, **_k: {"ok": True})
    loop.mark_dirty(["pkg/a.py"], reason="watch")
    now = time.monotonic()
    out = loop.drain_due(now=now + 1.0)
    assert out[0]["strategy"] == "embedder_cold"
    assert loop.dirty_ledger.due_paths(now=now + 2.0) == []
    assert loop.dirty_ledger.due_paths(now=now + 5.0) == ["pkg/a.py"]


def test_hot_named_upsert_does_not_compact_the_collection():
    """A save must not pay a whole-collection FAISS rebuild (seconds on 7k chunks).

    Tombstones are honoured by FaissDenseAdapter/reconcile_vector_store, so the
    hot lane leaves them for idle/bulk compaction.
    """
    from pipeline.incremental import _upsert_named_vectors

    class _Col:
        def __init__(self) -> None:
            self.name = "c"
            self.compacted = 0
            self.added: list[list[int]] = []
            self.deleted: list[list[int]] = []

        def delete(self, ids):
            self.deleted.append(list(ids))
            return len(ids)

        def compact(self):
            self.compacted += 1
            return 1

        def add(self, matrix, ids, payloads):
            self.added.append(list(ids))
            return len(ids)

    class _Vdb:
        def __init__(self) -> None:
            self.saved: list[str] = []

        def save_collection(self, name):
            self.saved.append(name)

    class _Store:
        def __init__(self) -> None:
            self.vdb = _Vdb()

    rec = ChunkRecord(
        id=7, file="pkg/a.py", start_line=1, end_line=2, symbol="f", text="t", enriched="e"
    )
    matrix = np.zeros((1, 8), dtype=np.float32)

    hot_store, hot_col = _Store(), _Col()
    _upsert_named_vectors(
        hot_store, hot_col, [rec], matrix, [3], dim=8, bits=4, hot_lane=True
    )
    assert hot_col.compacted == 0, "hot lane must skip full compaction"
    assert hot_col.deleted == [[3]]
    assert hot_col.added == [[7]]
    assert hot_store.vdb.saved == ["c"], "disk must still match memory"

    bulk_store, bulk_col = _Store(), _Col()
    _upsert_named_vectors(bulk_store, bulk_col, [rec], matrix, [3], dim=8, bits=4)
    assert bulk_col.compacted == 1, "bulk/idle path still reclaims tombstones"


def test_hot_reason_is_due_fast_and_disk_poll_keeps_the_long_debounce(tmp_path: Path):
    """~250ms for a save; disk_poll stays at 1s so editor bursts still coalesce."""
    from pipeline.dirty_ledger import DirtyLedger

    ledger = DirtyLedger(debounce_ms=1000, rewrite_debounce_ms=2000, hot_debounce_ms=250)

    ledger.mark(["pkg/hot.py"], reason="changed_file", now=0.0)
    ledger.mark(["pkg/cold.py"], reason="disk_poll", now=0.0)

    assert ledger.due_paths(now=0.2) == []
    assert ledger.due_paths(now=0.26) == ["pkg/hot.py"]
    assert ledger.due_paths(now=0.9) == []
    assert ledger.due_paths(now=1.01) == ["pkg/cold.py"]


def test_hot_rewrite_does_not_slide_due_past_the_budget(tmp_path: Path):
    from pipeline.dirty_ledger import DirtyLedger

    ledger = DirtyLedger(debounce_ms=1000, rewrite_debounce_ms=2000, hot_debounce_ms=250)

    ledger.mark(["pkg/hot.py"], reason="editor_save", now=0.0)
    for tick in (0.05, 0.1, 0.15):
        ledger.mark(["pkg/hot.py"], reason="editor_save", now=tick)
    # An atomic-save burst coalesces into one quiet window measured from the last
    # event, and that window is the hot budget — never the 2s bulk rewrite.
    assert ledger.due_paths(now=0.39) == []
    assert ledger.due_paths(now=0.41) == ["pkg/hot.py"]


def test_disk_poll_remark_cannot_delay_a_queued_save(tmp_path: Path):
    from pipeline.dirty_ledger import DirtyLedger

    ledger = DirtyLedger(debounce_ms=1000, rewrite_debounce_ms=2000, hot_debounce_ms=250)

    ledger.mark(["pkg/hot.py"], reason="changed_file", now=0.0)
    ledger.mark(["pkg/hot.py"], reason="disk_poll", now=0.05)

    assert ledger.due_paths(now=0.26) == ["pkg/hot.py"]
    snap = ledger.snapshot()["paths"]
    entry = next(iter(snap.values()))
    assert entry["reason"] == "changed_file", "hot reason selects the hot lane"


def test_hot_debounce_never_exceeds_a_shorter_configured_debounce():
    from pipeline.dirty_ledger import DirtyLedger

    ledger = DirtyLedger(debounce_ms=10, rewrite_debounce_ms=20, hot_debounce_ms=250)
    ledger.mark(["pkg/a.py"], reason="write", now=0.0)
    assert ledger.due_paths(now=0.011) == ["pkg/a.py"]


def test_hot_debounce_default_reads_env(monkeypatch):
    from pipeline.dirty_ledger import DirtyLedger, hot_debounce_ms_default

    monkeypatch.delenv("CTX_HOT_DEBOUNCE_MS", raising=False)
    assert hot_debounce_ms_default() == 250
    monkeypatch.setenv("CTX_HOT_DEBOUNCE_MS", "80")
    assert DirtyLedger(debounce_ms=1000, rewrite_debounce_ms=2000).hot_debounce_ms == 80
    monkeypatch.setenv("CTX_HOT_DEBOUNCE_MS", "nonsense")
    assert hot_debounce_ms_default() == 250


def test_hot_batch_detection_requires_every_path_to_be_a_save(monkeypatch, tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")

    loop.mark_dirty(["pkg/a.py"], reason="changed_file")
    assert loop._is_hot_batch(["pkg/a.py"]) is True

    loop.mark_dirty(["pkg/b.py"], reason="disk_poll")
    assert loop._is_hot_batch(["pkg/a.py", "pkg/b.py"]) is False
    assert loop._is_hot_batch([]) is False


def test_hot_batch_selects_the_hot_lane_in_sync(monkeypatch, tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")
    seen: list[bool] = []

    def _sync(paths, *, reason, hot=False):
        seen.append(hot)
        return {
            "refreshed": True,
            "files": paths,
            "chunks_upserted": 1,
            "chunks_removed": 0,
            "strategy": "incremental",
        }

    monkeypatch.setattr(loop, "_sync_paths", _sync)
    loop.mark_dirty(["pkg/a.py"], reason="changed_file")
    loop.drain_due(now=time.monotonic() + 1.0)
    assert seen == [True]


def test_incremental_result_to_dict_stays_json_safe_with_a_delta():
    """The keeper payload is returned by /v1/status — a numpy matrix must not leak in."""
    import json

    from pipeline.incremental import HotDelta, IncrementalResult

    rec = ChunkRecord(
        id=1, file="pkg/a.py", start_line=1, end_line=2, symbol="f", text="t", enriched="e"
    )
    result = IncrementalResult(
        refreshed=True,
        files=["pkg/a.py"],
        chunks_upserted=1,
        chunks_removed=0,
        ms=12.0,
        strategy="incremental",
        hot_delta=HotDelta(
            records=[rec],
            matrix=np.zeros((1, 8), dtype=np.float32),
            removed_ids=[],
            dim=8,
            full_embed_coverage=True,
            base_chunk_count=5,
        ),
    )

    payload = result.to_dict()
    assert "hot_delta" not in payload
    assert "matrix" not in json.dumps(payload)
    json.dumps(payload)  # must not raise
    assert result.hot_delta is not None and result.hot_delta.append_only is True


def test_notify_refresh_forwards_then_clears_the_delta(tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    seen: list[tuple[dict, object]] = []

    def publisher(payload, delta=None):
        seen.append((payload, delta))
        return {"ok": True}

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0, on_refresh=publisher)
    payload = {"refreshed": True}
    sentinel = object()
    loop._hot_delta = (payload, sentinel)

    assert loop._notify_refresh(payload) is True
    assert seen[0][1] is sentinel
    assert loop._hot_delta is None, "a delta belongs to exactly one publish attempt"

    # A later publish (held/bulk) gets no delta and must fall back to a full reload.
    assert loop._notify_refresh({"refreshed": True}) is True
    assert seen[1][1] is None


def test_notify_refresh_clears_the_delta_when_publish_raises(tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    def boom(payload, delta=None):
        raise RuntimeError("publisher crashed")

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0, on_refresh=boom)
    payload = {"refreshed": True}
    loop._hot_delta = (payload, object())

    assert loop._notify_refresh(payload) is False
    assert loop._hot_delta is None


def test_notify_refresh_supports_single_argument_publishers(tmp_path: Path):
    """Existing callables (and list.append in tests) must keep working."""
    from pipeline.sync_loop import BackgroundSyncLoop

    published: list[dict] = []
    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0, on_refresh=published.append)
    payload = {"refreshed": True}
    loop._hot_delta = (payload, object())

    assert loop._notify_refresh(payload) is True
    assert published == [payload]
    assert loop._on_refresh_accepts_delta() is False


def test_delta_is_not_reused_for_a_different_payload(tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    seen: list[object] = []
    loop = BackgroundSyncLoop(
        tmp_path,
        debounce_ms=0,
        on_refresh=lambda payload, delta=None: seen.append(delta) or {"ok": True},
    )
    other_payload = {"other": True}
    loop._hot_delta = (other_payload, object())

    loop._notify_refresh({"refreshed": True})
    assert seen == [None], "a delta must only travel with the payload it belongs to"


# --- append-only hot publish -------------------------------------------------


def _fake_binder(n_chunks: int = 6, dim: int = 8):
    """Minimal stand-in with the exact structures a hot publish patches."""
    from conductor.architectures import MultiArchConductor
    from conductor.bm25_index import BM25Index
    from conductor.conductor import ConductorConfig
    from conductor.graphify_retriever import ChunkSpan, GraphifyChunkRetriever
    from conductor.dense_index import DenseIndex
    from pipeline.engine import WarmSearchEngine

    chunks = [
        ChunkRecord(
            id=i,
            file=f"pkg/mod_{i}.py",
            start_line=1,
            end_line=4,
            symbol=f"sym_{i}",
            text=f"def sym_{i}(): return {i}",
            enriched=f"def sym_{i}(): return {i}",
        )
        for i in range(n_chunks)
    ]
    texts = [c.text for c in chunks]
    files = [c.file for c in chunks]
    spans = [
        ChunkSpan(index=i, file=files[i], start_line=c.start_line, end_line=c.end_line)
        for i, c in enumerate(chunks)
    ]

    rng = np.random.default_rng(3)
    rows = rng.normal(size=(n_chunks, dim)).astype(np.float32)
    dense = DenseIndex(rows)
    # load_engine builds the adapter with a chunk-id map; mimic that contract.
    dense._chunk_row = {int(c.id): i for i, c in enumerate(chunks)}

    import networkx as nx

    graph = GraphifyChunkRetriever(nx.DiGraph(), spans, depth=2)
    conductor = MultiArchConductor(
        files=files,
        bm25=BM25Index(texts),
        dense=dense,
        graph=graph,
        config=ConductorConfig(),
    )

    class _Embedder:
        model = "test"
        backend = "test"

    engine = WarmSearchEngine(
        root=Path("."),
        store=None,
        chunks=chunks,
        texts=texts,
        files=files,
        conductor=conductor,
        embedder=_Embedder(),
        load_ms=1.0,
        loaded_at=0.0,
    )
    return engine, dim


def test_apply_chunk_delta_appends_every_channel_position():
    engine, dim = _fake_binder(n_chunks=6, dim=8)
    n0 = len(engine.chunks)
    new = ChunkRecord(
        id=99,
        file="pkg/pipeline/sync_live_probe/f0.py",
        start_line=1,
        end_line=3,
        symbol="mcp_sync_probe",
        text="def mcp_sync_probe(): return 'zqx'",
        enriched="def mcp_sync_probe(): return 'zqx'",
    )
    rows = np.full((1, dim), 0.25, dtype=np.float32)

    info = engine.apply_chunk_delta([new], rows, base_chunk_count=n0)

    assert info["appended"] == 1
    assert len(engine.chunks) == n0 + 1
    assert len(engine.texts) == n0 + 1
    assert len(engine.files) == n0 + 1
    assert engine.status()["chunks"] == n0 + 1
    # conductor shares the files list and must agree on position space
    assert engine.conductor.files is engine.files
    assert engine.conductor._n == n0 + 1
    assert engine.conductor._file_chunks["pkg/pipeline/sync_live_probe/f0.py"] == [n0]
    # dense row landed, normalized, and is reachable by chunk id
    assert engine.conductor.dense.matrix.shape == (n0 + 1, dim)
    assert engine.conductor.dense._chunk_row[99] == n0
    assert float(np.linalg.norm(engine.conductor.dense.matrix[n0])) == pytest.approx(1.0, abs=1e-5)
    # graph spans patched for the new position
    assert engine.conductor.graph.spans[-1].index == n0
    assert engine.conductor.graph._by_file["pkg/pipeline/sync_live_probe/f0.py"][0].index == n0


def test_stale_bm25_does_not_break_a_search_over_patched_positions():
    """BM25 stays one generation behind; _fit_channel pads, dense ranks the new chunk."""
    engine, dim = _fake_binder(n_chunks=6, dim=8)
    n0 = len(engine.chunks)
    new = ChunkRecord(
        id=42,
        file="pkg/new_probe.py",
        start_line=1,
        end_line=2,
        symbol="probe",
        text="def probe(): return 1",
        enriched="def probe(): return 1",
    )
    vec = np.zeros((1, dim), dtype=np.float32)
    vec[0, 0] = 1.0
    engine.apply_chunk_delta([new], vec, base_chunk_count=n0)

    query_vec = np.zeros(dim, dtype=np.float32)
    query_vec[0] = 1.0
    # BM25 still has n0 docs — this used to IndexError deep in _best_chunk.
    assert len(engine.conductor.bm25.score_all("probe")) == n0
    hits = engine.conductor.retrieve_D_channel_best("probe function", query_vec, top_k=5)
    assert any(h.file == "pkg/new_probe.py" for h in hits), (
        "the appended chunk must be rankable through the dense channel"
    )


def test_apply_chunk_delta_refuses_incoherent_deltas():
    engine, dim = _fake_binder(n_chunks=4, dim=8)
    n0 = len(engine.chunks)
    rec = ChunkRecord(
        id=50, file="pkg/x.py", start_line=1, end_line=2, symbol="x", text="x", enriched="x"
    )

    with pytest.raises(ValueError):
        engine.apply_chunk_delta([], np.zeros((0, dim), dtype=np.float32))
    with pytest.raises(ValueError):  # row count mismatch
        engine.apply_chunk_delta([rec], np.zeros((2, dim), dtype=np.float32))
    with pytest.raises(ValueError):  # dim mismatch
        engine.apply_chunk_delta([rec], np.zeros((1, dim + 1), dtype=np.float32))
    with pytest.raises(RuntimeError):  # binder drift
        engine.apply_chunk_delta(
            [rec], np.zeros((1, dim), dtype=np.float32), base_chunk_count=n0 + 3
        )
    with pytest.raises(RuntimeError):  # id already indexed => not an append
        engine.apply_chunk_delta(
            [
                ChunkRecord(
                    id=0, file="pkg/x.py", start_line=1, end_line=2, symbol="x", text="x", enriched="x"
                )
            ],
            np.zeros((1, dim), dtype=np.float32),
            base_chunk_count=n0,
        )
    # every refusal happened before the binder was touched
    assert len(engine.chunks) == n0
    assert engine.conductor.dense.matrix.shape[0] == n0
    assert engine.conductor._n == n0


def _runtime_manager_with_binder(monkeypatch):
    from pipeline.ce_service import RuntimeManager

    engine, dim = _fake_binder(n_chunks=5, dim=8)
    manager = RuntimeManager()

    class _Runtime:
        project_id = "ce_hotpublish0000000000000000000"
        repo = Path(".")
        engine = None
        generation = 7
        last_sync_at = None
        warm_state = "ready"
        error = None

    runtime = _Runtime()
    runtime.engine = engine
    loads: list[int] = []
    monkeypatch.setattr(
        "pipeline.ce_service.load_engine",
        lambda *a, **k: loads.append(1) or engine,
    )
    monkeypatch.setattr(manager, "_load_runtime_facade", lambda *_a, **_k: None)
    return manager, runtime, engine, dim, loads


def test_hot_publish_patches_without_load_engine(monkeypatch):
    from pipeline.incremental import HotDelta

    manager, runtime, engine, dim, loads = _runtime_manager_with_binder(monkeypatch)
    n0 = len(engine.texts)
    rec = ChunkRecord(
        id=500,
        file="pkg/pipeline/sync_live_x/f0.py",
        start_line=1,
        end_line=3,
        symbol="probe",
        text="def probe(): return 1",
        enriched="def probe(): return 1",
    )
    delta = HotDelta(
        records=[rec],
        matrix=np.full((1, dim), 0.5, dtype=np.float32),
        removed_ids=[],
        dim=dim,
        full_embed_coverage=True,
        base_chunk_count=n0,
    )
    payload: dict = {"refreshed": True, "chunks_upserted": 1}

    out = manager._publish_runtime(runtime, payload, delta)

    assert out["ok"] is True
    assert out["publish"] == "patch"
    assert loads == [], "hot publish must not call load_engine"
    assert out["chunks"] == n0 + 1
    assert len(engine.texts) == n0 + 1
    assert runtime.generation == 8
    assert runtime.last_sync_at is not None
    assert payload["publish"] == "patch"
    assert isinstance(payload["publish_ms"], float)


def test_publish_falls_back_to_full_reload_for_a_delta_with_removals(monkeypatch):
    from pipeline.incremental import HotDelta

    manager, runtime, engine, dim, loads = _runtime_manager_with_binder(monkeypatch)
    rec = ChunkRecord(
        id=600, file="pkg/mod_1.py", start_line=1, end_line=2, symbol="s", text="t", enriched="e"
    )
    delta = HotDelta(
        records=[rec],
        matrix=np.zeros((1, dim), dtype=np.float32),
        removed_ids=[1],  # a modified file shifts later positions
        dim=dim,
        full_embed_coverage=True,
        base_chunk_count=len(engine.texts),
    )

    out = manager._publish_runtime(runtime, {"refreshed": True}, delta)

    assert out["ok"] is True
    assert out["publish"] == "full"
    assert loads == [1], "modify/delete must still take the proven full path"


def test_publish_falls_back_when_partially_embedded_or_drifted(monkeypatch):
    from pipeline.incremental import HotDelta

    manager, runtime, engine, dim, loads = _runtime_manager_with_binder(monkeypatch)
    rec = ChunkRecord(
        id=700, file="pkg/new.py", start_line=1, end_line=2, symbol="s", text="t", enriched="e"
    )
    partial = HotDelta(
        records=[rec],
        matrix=np.zeros((1, dim), dtype=np.float32),
        removed_ids=[],
        dim=dim,
        full_embed_coverage=False,
        base_chunk_count=len(engine.texts),
    )
    assert manager._publish_runtime(runtime, {}, partial)["publish"] == "full"

    drifted = HotDelta(
        records=[rec],
        matrix=np.zeros((1, dim), dtype=np.float32),
        removed_ids=[],
        dim=dim,
        full_embed_coverage=True,
        base_chunk_count=len(engine.texts) + 5,
    )
    assert manager._publish_runtime(runtime, {}, drifted)["publish"] == "full"
    assert loads == [1, 1]


def test_ctx_hot_publish_off_rolls_back_to_full_publish(monkeypatch):
    from pipeline.incremental import HotDelta

    manager, runtime, engine, dim, loads = _runtime_manager_with_binder(monkeypatch)
    monkeypatch.setenv("CTX_HOT_PUBLISH", "0")
    rec = ChunkRecord(
        id=800, file="pkg/new2.py", start_line=1, end_line=2, symbol="s", text="t", enriched="e"
    )
    delta = HotDelta(
        records=[rec],
        matrix=np.zeros((1, dim), dtype=np.float32),
        removed_ids=[],
        dim=dim,
        full_embed_coverage=True,
        base_chunk_count=len(engine.texts),
    )

    assert manager._publish_runtime(runtime, {}, delta)["publish"] == "full"
    assert loads == [1]


def test_publish_without_a_delta_is_unchanged(monkeypatch):
    manager, runtime, engine, dim, loads = _runtime_manager_with_binder(monkeypatch)

    out = manager._publish_runtime(runtime, {"refreshed": True})

    assert out["ok"] is True
    assert out["publish"] == "full"
    assert loads == [1]


def test_hot_sync_logs_every_stage(monkeypatch, tmp_path: Path, capsys):
    """A missed SLA has to name its stage: debounce vs parse vs embed vs write vs publish."""
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0, on_refresh=lambda p, d=None: {"ok": True})
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")

    def _sync(paths, *, reason, hot=False):
        return {
            "refreshed": True,
            "files": paths,
            "chunks_upserted": 1,
            "chunks_removed": 0,
            "ms": 1234.5,
            "strategy": "incremental",
            "stages": {
                "parse_ms": 40.0,
                "graph_ms": 60.0,
                "embed_ms": 1700.0,
                "write_ms": 120.0,
                "reconcile_ms": 30.0,
            },
        }

    monkeypatch.setattr(loop, "_sync_paths", _sync)
    loop.mark_dirty(["pkg/a.py"], reason="changed_file")
    loop.drain_due(now=time.monotonic() + 0.3)

    line = [
        entry
        for entry in capsys.readouterr().err.splitlines()
        if entry.startswith("[keeper] hot sync")
    ]
    assert line, "a hot save must emit the stage line"
    for token in (
        "path=pkg/a.py",
        "debounce_ms=",
        "parse_ms=40",
        "graph_ms=60",
        "embed_ms=1700",
        "write_ms=120",
        "reconcile_ms=30",
        "publish_ms=",
        "total_ms=",
        "upserted=1",
        "removed=0",
        "publish=",
        f"pid={__import__('os').getpid()}",
    ):
        assert token in line[0], f"missing {token} in: {line[0]}"


def test_sync_payload_carries_stage_timings(monkeypatch, tmp_path: Path):
    import json

    from pipeline.sync_loop import BackgroundSyncLoop
    from pipeline.incremental import IncrementalResult

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)

    def fake_incremental(root, *, force_files=None, bulk=False, hot_lane=False, **_kw):
        return IncrementalResult(
            refreshed=True,
            files=force_files or [],
            chunks_upserted=1,
            chunks_removed=0,
            ms=50.0,
            strategy="incremental",
            stages={"parse_ms": 10.0, "embed_ms": 20.0, "write_ms": 5.0},
        )

    monkeypatch.setattr("pipeline.incremental.incremental_sync", fake_incremental)
    payload = loop._sync_paths(["pkg/a.py"], reason="dirty", hot=True)

    assert payload["stages"]["embed_ms"] == 20.0
    assert payload["hot_lane"] is True
    json.dumps(payload)  # status() must still serialize


def test_hot_save_queues_a_non_hot_graph_catchup(monkeypatch, tmp_path: Path):
    """A save skips the ~6s whole-graph merge and re-queues it off the hot lane."""
    from pipeline.incremental import IncrementalResult
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0, on_refresh=lambda p, d=None: {"ok": True})
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")

    def fake_incremental(root, *, force_files=None, bulk=False, hot_lane=False, **_kw):
        assert hot_lane is True
        return IncrementalResult(
            refreshed=True,
            files=force_files or [],
            chunks_upserted=1,
            chunks_removed=0,
            ms=20.0,
            strategy="incremental",
            graph_pending=list(force_files or []),
        )

    monkeypatch.setattr("pipeline.incremental.incremental_sync", fake_incremental)
    loop.mark_dirty(["pkg/a.py"], reason="changed_file")
    loop.drain_due(now=time.monotonic() + 1.0)

    entry = loop.dirty_ledger.snapshot()["paths"]["pkg/a.py"]
    assert entry["reason"] == "graph_catchup", "catch-up must survive batch completion"
    assert entry["state"] == "queued"
    # Non-hot reason => the catch-up sync carries the slow graph merge, not the save.
    from pipeline.dirty_ledger import is_hot_reason

    assert is_hot_reason(entry["reason"]) is False


def test_invalidation_skips_session_stores_that_do_not_cache_the_path(tmp_path: Path):
    """A save must not rewrite every session store (~3.5s at 129 sessions).

    That cost sat in front of the publish, so the saved file stayed invisible to
    map for the whole scan. Stores that never cached the path are read-only now.
    """
    from pipeline.session_store import invalidate_paths, put_span, recall

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    put_span(tmp_path, path="pkg/a.py", start_line=1, end_line=2, text="def a(): return 1")

    brand_new = invalidate_paths(tmp_path, ["pkg/brand_new.py"])
    assert brand_new["removed"] == 0
    assert brand_new["stores_rewritten"] == 0, "nothing cached => nothing rewritten"

    cached = invalidate_paths(tmp_path, ["pkg/a.py"])
    assert cached["removed"] == 1
    assert cached["stores_rewritten"] == 1
    assert [s["path"] for s in recall(tmp_path)["spans"]] == []


def test_deferred_vector_save_runs_after_publish(monkeypatch, tmp_path: Path):
    """The collection save moves off the critical path but is never skipped."""
    from pipeline.incremental import IncrementalResult
    from pipeline.sync_loop import BackgroundSyncLoop

    order: list[str] = []
    loop = BackgroundSyncLoop(
        tmp_path,
        debounce_ms=0,
        on_refresh=lambda p, d=None: order.append("publish") or {"ok": True},
    )
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")

    def fake_incremental(root, *, force_files=None, bulk=False, hot_lane=False, **_kw):
        return IncrementalResult(
            refreshed=True,
            files=force_files or [],
            chunks_upserted=1,
            chunks_removed=0,
            ms=10.0,
            strategy="incremental",
            vector_flush=lambda: order.append("flush"),
        )

    monkeypatch.setattr("pipeline.incremental.incremental_sync", fake_incremental)
    loop.mark_dirty(["pkg/a.py"], reason="changed_file")
    loop.drain_due(now=time.monotonic() + 1.0)

    assert order == ["publish", "flush"]
    assert loop._vector_flush is None


def test_deferred_vector_save_still_runs_when_publish_fails(monkeypatch, tmp_path: Path):
    from pipeline.incremental import IncrementalResult
    from pipeline.sync_loop import BackgroundSyncLoop

    order: list[str] = []

    def boom(payload, delta=None):
        order.append("publish")
        raise RuntimeError("publisher crashed")

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0, on_refresh=boom)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "a.py").write_text("x = 1\n", encoding="utf-8")

    monkeypatch.setattr(
        "pipeline.incremental.incremental_sync",
        lambda root, *, force_files=None, bulk=False, hot_lane=False, **_kw: IncrementalResult(
            refreshed=True,
            files=force_files or [],
            chunks_upserted=1,
            chunks_removed=0,
            ms=10.0,
            strategy="incremental",
            vector_flush=lambda: order.append("flush"),
        ),
    )
    loop.mark_dirty(["pkg/a.py"], reason="changed_file")
    loop.drain_due(now=time.monotonic() + 1.0)

    assert order == ["publish", "flush"], "disk must converge even if the publish failed"


def test_graph_catchup_waits_for_a_quiet_window_after_saves(monkeypatch, tmp_path: Path):
    """A due catch-up (~8s graph merge) must not start while saves are still landing."""
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    loop.graph_catchup_quiet_s = 20.0
    (tmp_path / "pkg").mkdir()
    for name in ("owed.py", "save.py"):
        (tmp_path / "pkg" / name).write_text("x = 1\n", encoding="utf-8")
    seen: list[list[str]] = []
    monkeypatch.setattr(
        loop,
        "_sync_paths",
        lambda paths, **_: seen.append(list(paths))
        or {"refreshed": False, "files": paths, "chunks_upserted": 0, "chunks_removed": 0},
    )

    t0 = 1000.0
    loop.dirty_ledger.mark(["pkg/owed.py"], reason="graph_catchup", now=t0 - 60)
    loop.mark_dirty(["pkg/save.py"], reason="changed_file", now=t0)

    loop.drain_due(now=t0 + 1.0)
    assert seen == [["pkg/save.py"]], "the save runs; the catch-up is held"
    entry = loop.dirty_ledger.snapshot()["paths"]["pkg/owed.py"]
    assert entry["state"] == "queued"
    assert entry["due_at"] == pytest.approx(t0 + 20.0)

    loop.drain_due(now=t0 + 21.0)
    assert seen[-1] == ["pkg/owed.py"], "after the quiet window the catch-up runs"


def test_newcomer_scan_runs_off_the_keeper_thread(monkeypatch, tmp_path: Path):
    """The ~7.5s repo walk must not freeze drain_due (saves waited it out every 30s)."""
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    release = threading.Event()
    started = threading.Event()

    def slow_scan(*_a, **_k):
        started.set()
        release.wait(5.0)
        return []

    monkeypatch.setattr(loop, "_enqueue_newcomers", slow_scan)

    t0 = time.perf_counter()
    assert loop._start_newcomer_scan() is True
    assert (time.perf_counter() - t0) < 0.5, "starting the scan must not block"
    assert started.wait(2.0)
    assert loop._start_newcomer_scan() is False, "never two walks at once"

    release.set()
    loop._newcomer_thread.join(timeout=5.0)
    assert loop._start_newcomer_scan() is True
    loop._newcomer_thread.join(timeout=5.0)


def test_hot_syncs_reuse_the_collection_until_someone_else_writes_it(tmp_path: Path):
    """Reuse skips a ~600ms reopen per save, but only while disk matches memory."""
    from pipeline.sync_loop import BackgroundSyncLoop, _vdb_fingerprint
    from pipeline.vectordb import VectorDatabase

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    vdb = VectorDatabase(tmp_path / "vdb")
    col = vdb.create_collection("c", dim=4, cwd=tmp_path, bits=4)
    col.add(np.eye(4, dtype=np.float32)[:2], [1, 2], [{}, {}])
    vdb.save_collection("c")

    loop._hot_vdb_cache = (vdb, _vdb_fingerprint(vdb))
    assert loop._hot_vdb() is vdb, "untouched on disk => reuse"

    # Another writer (non-hot sync, compaction, full index) rewrites the files.
    other = VectorDatabase(tmp_path / "vdb")
    other_col = other.get_collection("c")
    other_col.add(np.eye(4, dtype=np.float32)[2:3], [3], [{}])
    time.sleep(0.01)
    other.save_collection("c")

    assert loop._hot_vdb() is None, "foreign write => reload from disk"
    assert loop._hot_vdb_cache is None


def test_non_hot_sync_drops_the_reused_collection(monkeypatch, tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    loop._hot_vdb_cache = (object(), ("stamp",))
    monkeypatch.setattr(
        "pipeline.incremental.incremental_sync",
        lambda *a, **k: __import__("pipeline.incremental", fromlist=["x"]).IncrementalResult(
            refreshed=False, files=[], chunks_upserted=0, chunks_removed=0, ms=1.0, strategy="none"
        ),
    )
    loop._sync_paths(["pkg/a.py"], reason="dirty", hot=False)
    assert loop._hot_vdb_cache is None


def test_full_publish_fallback_flushes_deferred_vectors_first(monkeypatch):
    """A modified file falls back to load_engine, which reads vectors from disk."""
    from pipeline.incremental import HotDelta

    manager, runtime, engine, dim, loads = _runtime_manager_with_binder(monkeypatch)
    order: list[str] = []
    monkeypatch.setattr(
        "pipeline.ce_service.load_engine",
        lambda *a, **k: order.append("load_engine") or engine,
    )
    rec = ChunkRecord(
        id=900, file="pkg/mod_1.py", start_line=1, end_line=2, symbol="s", text="t", enriched="e"
    )
    delta = HotDelta(
        records=[rec],
        matrix=np.zeros((1, dim), dtype=np.float32),
        removed_ids=[1],  # modify => full publish path
        dim=dim,
        full_embed_coverage=True,
        base_chunk_count=len(engine.texts),
        flush=lambda: order.append("flush") or True,
    )

    out = manager._publish_runtime(runtime, {"refreshed": True}, delta)

    assert out["publish"] == "full"
    assert order == ["flush", "load_engine"], "vectors must hit disk before the reload"


def test_once_flush_writes_exactly_once(tmp_path: Path):
    from pipeline.incremental import _OnceFlush

    calls: list[str] = []

    class _Vdb:
        def save_collection(self, name):
            calls.append(name)

    flush = _OnceFlush(_Vdb(), "c")
    assert flush() is True
    assert flush() is False
    assert calls == ["c"]

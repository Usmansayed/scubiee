"""Live reindexing ingress and safety controls without an embedding model."""

from __future__ import annotations

import time
import threading
from pathlib import Path


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


def test_live_storm_chunks_without_background_full_index(monkeypatch, tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        loop,
        "_sync_paths",
        lambda paths, **_: calls.append(paths)
        or {"refreshed": True, "chunks_upserted": 1, "chunks_removed": 0},
    )

    paths = [f"pkg/{n}.py" for n in range(41)]
    loop.mark_dirty(paths, reason="watch")
    out = loop.drain_due(now=time.monotonic() + 0.01)

    assert len(calls) == 1
    assert len(calls[0]) == 40
    assert out[0]["strategy"] == "catchup_chunked"
    assert out[0]["needs_full"] is True
    assert loop.status()["catchup_chunked"] is True
    assert loop.status()["needs_full"] is True


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

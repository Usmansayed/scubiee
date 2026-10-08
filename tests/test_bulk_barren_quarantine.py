"""Bulk-sync barren-path quarantine (adversarial finding: huge-file retry loop).

A file that keeps producing 0 chunks (a pathologically huge file, a parser that
always fails on it, an empty-delta ghost) used to re-queue FOREVER in the bulk
lane: `_bulk_sync_paths` only escalated on strategy=='explicit_full_index_required'
and re-marked every other non-refresh as 'bulk_deferred' indefinitely, pinning the
keeper ("0 upserted, 0 removed" every ~5 min forever). The fix caps barren
attempts and quarantines the path so the ledger drains.

Offline; no live engine/embedder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import enroll_test_repo


@pytest.fixture(autouse=True)
def enrolled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(tmp_path, home=home, project_id="ce_barren1234567890abcdef00")
    monkeypatch.setattr(
        "pipeline.sync_loop.BackgroundSyncLoop._clients_active", lambda self: False
    )
    return tmp_path


def _barren_result(_repo=None, **_kw):
    """incremental_sync stand-in: always refreshes nothing (the huge-file case)."""
    from pipeline.incremental import IncrementalResult

    return IncrementalResult(
        refreshed=False, files=["pkg/huge.py"], chunks_upserted=0, chunks_removed=0,
        ms=1.0, strategy="incremental", error=None,
    )


def test_barren_file_is_quarantined_after_cap_not_looped(tmp_path, monkeypatch):
    from pipeline.sync_loop import BackgroundSyncLoop

    monkeypatch.setenv("CTX_BULK_BARREN_CAP", "3")
    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    monkeypatch.setattr("pipeline.incremental.incremental_sync", _barren_result)

    # a real on-disk file so _inside_repo + is_file pass (not dropped as gone)
    (tmp_path / "pkg").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pkg" / "huge.py").write_text("x = 1\n", encoding="utf-8")

    # mark ONCE; the keeper re-drives the same ledger entry each poll (defer
    # keeps it, so fail_attempts accumulates — re-marking would reset it).
    loop.dirty_ledger.mark(["pkg/huge.py"], reason="bulk_reindex", now=0.0)
    for attempt in range(1, 6):
        loop._bulk_sync_paths(["pkg/huge.py"], reason="bulk_reindex")
        snap = loop.dirty_ledger.snapshot()["paths"]
        entry = snap.get("pkg/huge.py") or {}
        state = str(entry.get("state") or "")
        if attempt < 3:
            # still retrying within the cap
            assert state in {"queued", "due", "processing"}, f"attempt {attempt}: {state}"
        else:
            # at/after the cap: quarantined (published => drained from the work set)
            assert state == "published", f"attempt {attempt}: expected quarantined, got {state}"
            assert loop.needs_full is True
            break


def test_resource_deferral_does_not_count_toward_barren_cap(tmp_path, monkeypatch):
    """A clean resource-pressure deferral must keep retrying, never quarantine."""
    from pipeline.incremental import IncrementalResult
    from pipeline.sync_loop import BackgroundSyncLoop

    monkeypatch.setenv("CTX_BULK_BARREN_CAP", "2")
    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)

    def _deferred(_repo=None, **_kw):
        return IncrementalResult(
            refreshed=False, files=["pkg/x.py"], chunks_upserted=0, chunks_removed=0,
            ms=1.0, strategy="deferred", error="resource pressure",
        )

    monkeypatch.setattr("pipeline.incremental.incremental_sync", _deferred)
    (tmp_path / "pkg").mkdir(parents=True, exist_ok=True)
    (tmp_path / "pkg" / "x.py").write_text("x = 1\n", encoding="utf-8")

    loop.dirty_ledger.mark(["pkg/x.py"], reason="bulk_reindex", now=0.0)
    for attempt in range(1, 6):
        loop._bulk_sync_paths(["pkg/x.py"], reason="bulk_reindex")
        entry = loop.dirty_ledger.snapshot()["paths"].get("pkg/x.py") or {}
        # resource deferral always re-queues, never quarantines
        assert str(entry.get("state") or "") in {"queued", "due", "processing"}
    assert loop.needs_full is False

from __future__ import annotations

import json

import pytest

from pipeline.dirty_ledger import DirtyLedger
from pipeline.dirty_journal import (
    JournalingLedger,
    clear_dirty_journal,
    load_dirty_journal,
    restore_ledger_from_journal,
)
from pipeline.sync_status import derive_sync_status


@pytest.fixture
def journal_root(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.dirty_journal.projects_root", lambda: tmp_path)
    return tmp_path


@pytest.mark.parametrize("state", ["queued", "processing", "overlay_ready"])
def test_crash_restore_replays_unpublished_paths_immediately(journal_root, state):
    ledger = JournalingLedger("ce_crash", DirtyLedger(debounce_ms=1500))
    ledger.mark(["pkg/live.py"], reason="write", now=10.0)
    if state in {"processing", "overlay_ready"}:
        ledger.begin(["pkg/live.py"])
    if state == "overlay_ready":
        ledger.complete(["pkg/live.py"], published=False)

    restored = JournalingLedger("ce_crash", DirtyLedger(debounce_ms=1500), now=20.0)

    assert restored.due_paths(now=20.0) == ["pkg/live.py"]


def test_corrupt_journal_is_reported_and_restores_empty(journal_root):
    journal = journal_root / "ce_corrupt" / "dirty_journal.json"
    journal.parent.mkdir(parents=True)
    journal.write_text("{not-json", encoding="utf-8")

    loaded = load_dirty_journal("ce_corrupt")
    ledger = DirtyLedger()
    restored = restore_ledger_from_journal(ledger, "ce_corrupt", now=0.0)

    assert loaded["ok"] is False
    assert loaded["reason"] == "corrupt"
    assert restored["ok"] is False
    assert restored["restored"] == 0
    assert ledger.snapshot() == {"paths": {}}


def test_restore_drops_published_paths_from_the_journal(journal_root):
    ledger = JournalingLedger("ce_published", DirtyLedger())
    ledger.mark(["done.py"], reason="write", now=0.0)
    ledger.complete(["done.py"], published=True)

    restored = JournalingLedger("ce_published", DirtyLedger(), now=5.0)

    assert restored.due_paths(now=5.0) == []
    assert restored.restore_result["dropped_published"] == 1
    assert load_dirty_journal("ce_published")["snapshot"] == {"paths": {}}


def test_lost_journal_allows_merkle_recovery_to_mark_paths(journal_root):
    ledger = JournalingLedger("ce_lost", DirtyLedger())
    ledger.mark(["old.py"], reason="write", now=0.0)
    clear_dirty_journal("ce_lost")

    recovered = JournalingLedger("ce_lost", DirtyLedger(), now=5.0)
    assert recovered.restore_result == {
        "ok": True,
        "reason": "missing",
        "restored": 0,
        "dropped_published": 0,
    }

    # A Merkle/root probe can repopulate an empty lost journal.
    recovered.mark(["from-merkle.py"], reason="disk_poll", now=5.0)
    assert "from-merkle.py" in recovered.snapshot()["paths"]


def test_rewrite_during_indexing_schedules_follow_up_through_journal(journal_root):
    ledger = JournalingLedger(
        "ce_rewrite",
        DirtyLedger(debounce_ms=1500, rewrite_debounce_ms=2500),
    )
    ledger.mark(["a.py"], reason="write", now=0.0)
    assert ledger.due_paths(now=1.6) == ["a.py"]
    ledger.begin(["a.py"])

    ledger.mark(["a.py"], reason="write", now=2.0)

    assert ledger.due_paths(now=3.4) == []
    assert ledger.due_paths(now=3.6) == ["a.py"]
    persisted = json.loads(
        (journal_root / "ce_rewrite" / "dirty_journal.json").read_text(encoding="utf-8")
    )
    assert persisted["snapshot"]["paths"]["a.py"]["rewrites"] == 0


def test_branch_storm_and_resource_pressure_statuses():
    dirty = {"paths": {"a.py": {"state": "queued"}}}

    assert derive_sync_status(dirty=dirty, needs_full=True, catchup_chunked=True) == "needs_full"
    assert derive_sync_status(dirty=dirty, resource_deferred=True) == "deferred"
    assert derive_sync_status(dirty=dirty, dense_pending=True) == "dense_pending"


def test_normal_stale_window_maps_overlay_then_ready():
    """Debounce plus publication targets <=5 seconds in the normal live path."""
    overlay = {"paths": {"a.py": {"state": "overlay_ready"}}}
    published = {"paths": {"a.py": {"state": "published"}}}

    assert derive_sync_status(dirty=overlay, publish_pending=True) == "overlay_ready"
    assert derive_sync_status(dirty=published) == "ready"


def test_background_loop_exposes_derived_status(tmp_path, monkeypatch):
    from pipeline.sync_loop import BackgroundSyncLoop

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    loop = BackgroundSyncLoop(repo)

    loop.mark_dirty(["a.py"], reason="write")

    status = loop.status()
    assert status["sync_status"] == "syncing"
    assert status["project_id"].startswith("ce_")

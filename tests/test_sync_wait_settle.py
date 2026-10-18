"""`scubiee sync` must wait for the requested poll to be indexed, not return "deferred".

Offline; no live engine/embedder.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import enroll_test_repo


@pytest.fixture
def loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(tmp_path, home=home, project_id="ce_syncwait1234567890abcdef0")
    from pipeline.sync_loop import BackgroundSyncLoop

    return BackgroundSyncLoop(tmp_path, debounce_ms=0)


def test_request_poll_returns_increasing_sequence(loop) -> None:
    first = loop.request_poll()
    second = loop.request_poll()
    assert second == first + 1
    assert loop.wait_settled(second, timeout=0.05) is False


def test_settles_only_after_polled_changes_are_published(loop) -> None:
    seq = loop.request_poll()
    loop._last_poll_paths = ["src/a.py"]
    loop.dirty_ledger.mark(["src/a.py"], reason="disk_save", now=0.0)
    loop._note_polled(seq)

    loop._settle_if_idle()
    assert loop.wait_settled(seq, timeout=0.05) is False

    loop.dirty_ledger.begin(["src/a.py"])
    loop._settle_if_idle()
    assert loop.wait_settled(seq, timeout=0.05) is False

    loop.dirty_ledger.complete(["src/a.py"], published=True)
    loop._settle_if_idle()
    assert loop.wait_settled(seq, timeout=0.05) is True

    report = loop.settle_report(seq, settled=True)
    assert report["ok"] is True
    assert report["refreshed"] is True
    assert report["files_synced"] == 1
    assert report["strategy"] != "deferred"


def test_pending_publish_blocks_settle(loop) -> None:
    seq = loop.request_poll()
    loop._last_poll_paths = []
    loop._note_polled(seq)
    loop._pending_publish = {"strategy": "incremental"}
    loop._settle_if_idle()
    assert loop.wait_settled(seq, timeout=0.05) is False
    loop._pending_publish = None
    loop._settle_if_idle()
    assert loop.wait_settled(seq, timeout=0.05) is True
    report = loop.settle_report(seq, settled=True)
    assert report["refreshed"] is False
    assert report["files_synced"] == 0


def test_request_made_before_poll_is_not_settled_by_older_poll(loop) -> None:
    old = loop.request_poll()
    loop._last_poll_paths = []
    loop._note_polled(old)
    new = loop.request_poll()
    loop._settle_if_idle()
    assert loop.wait_settled(old, timeout=0.05) is True
    assert loop.wait_settled(new, timeout=0.05) is False


def test_graph_catchup_does_not_block_settle(loop) -> None:
    """Search is fresh once chunks publish; the delayed graph merge is background work."""
    seq = loop.request_poll()
    loop._last_poll_paths = []
    loop.dirty_ledger.mark(["src/new.py"], reason="graph_catchup", now=1e9)
    loop._note_polled(seq)
    loop._settle_if_idle()
    assert loop.wait_settled(seq, timeout=0.05) is True
    assert loop.settle_report(seq, settled=True)["graph_pending"] == 1


def test_in_flight_paths_count_as_synced(loop) -> None:
    """A periodic poll can queue the file just before the requested poll runs."""
    loop.dirty_ledger.mark(["src/new.py"], reason="disk_save", now=0.0)
    seq = loop.request_poll()
    loop._last_poll_paths = []
    loop._note_polled(seq)
    loop.dirty_ledger.complete(["src/new.py"], published=True)
    loop._settle_if_idle()
    assert loop.wait_settled(seq, timeout=0.05) is True
    report = loop.settle_report(seq, settled=True)
    assert report["files"] == ["src/new.py"]
    assert report["refreshed"] is True


def test_timeout_report_is_honest(loop) -> None:
    seq = loop.request_poll()
    report = loop.settle_report(seq, settled=False)
    assert report["ok"] is False
    assert report["error"] == "sync_timeout"

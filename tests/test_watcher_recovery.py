from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_context_engine_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    return home


def test_event_overflow_marks_full_and_reconciles_immediately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path)
    calls: list[str] = []

    def reconcile(reason: str = "manual") -> dict:
        calls.append(reason)
        assert loop.needs_full is True
        loop.mark_dirty(["pkg/recovered.py"], reason=reason)
        return {"reason": reason, "marked": 1}

    monkeypatch.setattr(loop, "reconcile", reconcile)

    out = loop.note_watcher_overflow()

    assert out == {"reason": "watcher_overflow", "marked": 1}
    assert calls == ["watcher_overflow"]
    assert "pkg/recovered.py" in loop.status()["dirty"]["paths"]


def test_atomic_save_rename_burst_uses_one_rewrite_quiet_window(tmp_path: Path) -> None:
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=100, rewrite_debounce_ms=500)
    loop.mark_dirty(["pkg/a.py"], reason="watch", now=1.0)
    loop.mark_dirty(["pkg/a.py"], reason="watch", now=1.1)
    loop.mark_dirty(["pkg/a.py"], reason="watch", now=1.2)

    entry = loop.status()["dirty"]["paths"]["pkg/a.py"]
    assert entry["rewrites"] == 2
    assert entry["due_at"] == pytest.approx(1.7)
    assert loop.dirty_ledger.due_paths(now=1.69) == []
    assert loop.dirty_ledger.due_paths(now=1.71) == ["pkg/a.py"]


def test_watcher_unavailable_does_not_block_merkle_reconcile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path)
    monkeypatch.setattr(loop, "poll_repo_changes", lambda **_: ["pkg/recovered.py"])

    out = loop.reconcile(reason="watcher_unavailable")

    assert out["dirty_paths"] == ["pkg/recovered.py"]
    assert out["marked"] == 1


def test_sleep_time_jump_reconciles_and_updates_watcher_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, wake_gap_ms=1_000)
    calls: list[str] = []
    monkeypatch.setattr(
        loop,
        "reconcile",
        lambda reason="manual": calls.append(reason) or {"reason": reason, "marked": 0},
    )

    assert loop.check_time_gap(now=10.0) is None
    out = loop.check_time_gap(now=12.5)

    assert out == {"reason": "sleep_wake", "marked": 0}
    assert calls == ["sleep_wake"]
    watcher = loop.status()["watcher"]
    assert watcher["last_wake_reconcile"] == pytest.approx(12.5)
    assert watcher["last_error"] is None
    assert watcher["restart_count"] == 0


def test_watchdog_status_reports_durable_recovery_fields() -> None:
    from pipeline.watchdog import watchdog_state_path, watchdog_status

    path = watchdog_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "restart_count": 3,
                "last_wake_reconcile": 11.0,
                "last_reconcile": 12.0,
                "last_error": "watcher unavailable",
            }
        ),
        encoding="utf-8",
    )

    status = watchdog_status()

    assert status["restart_count"] == 3
    assert status["last_wake_reconcile"] == 11.0
    assert status["last_reconcile"] == 12.0
    assert status["last_error"] == "watcher unavailable"


def test_reboot_registry_recovery_reconciles_every_managed_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.daemon import reconcile_managed_repositories
    from pipeline.project_id import save_registry
    from pipeline.sync_loop import BackgroundSyncLoop

    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    repo_a.mkdir()
    repo_b.mkdir()
    save_registry(
        {
            "version": 1,
            "projects": {
                "ce_a": {"managed": True, "paths": [str(repo_a.resolve())]},
                "ce_b": {"managed": True, "paths": [str(repo_b.resolve())]},
                "ce_ignored": {"managed": False, "paths": [str(tmp_path / "ignored")]},
            },
        }
    )
    calls: list[Path] = []
    monkeypatch.setattr(
        BackgroundSyncLoop,
        "reconcile",
        lambda self, reason="manual": calls.append(self.repo)
        or {"reason": reason, "marked": 0},
    )

    out = reconcile_managed_repositories(reason="daemon_recovery")

    assert calls == [repo_a.resolve(), repo_b.resolve()]
    assert out["managed"] == 2
    assert out["reconciled"] == 2
    assert out["errors"] == []


def test_5000_event_storm_processes_only_configured_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0, live_max_files=37)
    batches: list[list[str]] = []
    monkeypatch.setattr(
        loop,
        "_sync_paths",
        lambda paths, **_: batches.append(paths)
        or {"refreshed": False, "chunks_upserted": 0, "chunks_removed": 0},
    )
    loop.mark_dirty((f"pkg/{index}.py" for index in range(5_000)), reason="watch")

    out = loop.drain_due(now=time.monotonic() + 1)

    assert len(batches) == 1
    assert len(batches[0]) == 37
    assert out[0]["needs_full"] is True
    assert out[0]["live_limits"]["deferred_paths"] == 4_963
    status = loop.status()
    assert status["needs_full"] is True
    assert status["catchup_chunked"] is True

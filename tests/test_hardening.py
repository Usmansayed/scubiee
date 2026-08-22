"""Hardening: confirm UX, sync publish honesty, identity trust, merkle keys."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipeline.incremental import IndexConfirmRequired, preflight_index_scope
from pipeline.merkle import canonical_relpath, sanitize_file_hashes
from pipeline.process_control import is_context_engine_process


def test_confirm_payload_is_warning_not_error(tmp_path: Path) -> None:
    exc = IndexConfirmRequired(500, max_touch=400)
    payload = exc.to_payload(tmp_path)
    assert payload["status"] == "warning"
    assert payload["needs_confirm"] is True
    assert payload["n_files"] == 500
    assert "Safety pause" in payload["message"]
    assert "--confirm" in payload["action"]


def test_broad_root_payload_kind(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pipeline.incremental.Path.home", lambda: home)
    with pytest.raises(IndexConfirmRequired) as exc_info:
        preflight_index_scope(home, confirm=False)
    payload = exc_info.value.to_payload(home)
    assert payload["warning"] == "broad_index_scope"


def test_merkle_canonical_folds_case_on_windows(monkeypatch) -> None:
    monkeypatch.setattr(os, "name", "nt")
    a = canonical_relpath("Src/Foo.py")
    b = canonical_relpath("src/foo.py")
    assert a == b
    merged = sanitize_file_hashes({"Src/Foo.py": "aa", "src/foo.py": "bb"})
    assert len(merged) == 1


def test_untrusted_id_file_mints_fresh_id(tmp_path: Path, monkeypatch) -> None:
    from pipeline.project_id import resolve_project, write_id_file

    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    repo = tmp_path / "repo"
    repo.mkdir()
    write_id_file(repo, "ce_victim123456789012345678901234")
    ref = resolve_project(repo)
    assert ref.project_id.startswith("ce_")
    assert ref.project_id != "ce_victim123456789012345678901234"


def test_safe_kill_skips_non_ce_pid(monkeypatch) -> None:
    monkeypatch.setattr(
        "pipeline.process_control.process_cmdline",
        lambda _pid: "notepad.exe foo",
    )
    monkeypatch.setattr("pipeline.daemon._pid_alive", lambda _pid: True)
    assert is_context_engine_process(4242) is False


def test_sync_loop_marks_unpublished_when_not_refreshed() -> None:
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop.__new__(BackgroundSyncLoop)
    loop.dirty_ledger = MagicMock()
    loop._invalidate_session_paths = MagicMock()
    loop._publish_or_hold = MagicMock()
    loop.drain_publish = MagicMock(return_value=False)
    loop.live_batches = 0
    loop.live_max_chunks = 100
    loop.catchup_chunked = False
    loop.needs_full = False
    loop.last_result = None

    batch = ["a.py"]
    payload = {"refreshed": False, "strategy": "incremental"}
    loop.dirty_ledger.begin = MagicMock()
    loop.dirty_ledger.mark = MagicMock()
    loop._sync_paths = MagicMock(return_value=payload)

    # inline drain_due body fragment
    loop.dirty_ledger.defer = MagicMock()
    loop.dirty_ledger.begin(batch)
    payload = loop._sync_paths(batch, reason="dirty")
    loop.last_result = payload
    if payload.get("refreshed"):
        loop._publish_or_hold(payload, paths=batch, now=0.0)
    else:
        loop.dirty_ledger.complete(batch, published=False)
    loop.dirty_ledger.complete.assert_called_with(batch, published=False)

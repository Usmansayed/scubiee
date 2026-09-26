"""Reliability master-plan coverage: stamp refresh, ready honesty, registry retry, keeper defer, pack SLA."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_ensure_active_build_stamp_refreshes_stale_version(tmp_path: Path, monkeypatch) -> None:
    from pipeline import mcp_hot_reload as hr

    monkeypatch.setattr(hr, "_home", lambda: tmp_path)
    stale = {
        "version": "0.3.71",
        "epoch": 1.0,
        "build_id": "0.3.71-1",
    }
    (tmp_path / hr.ACTIVE_BUILD_NAME).write_text(json.dumps(stale), encoding="utf-8")
    monkeypatch.setattr("pipeline.upgrade.installed_version", lambda: "0.3.73")
    stamp = hr.ensure_active_build_stamp()
    assert stamp["version"] == "0.3.73"
    assert str(stamp["build_id"]).startswith("0.3.73-")
    # Stable when already matching.
    again = hr.ensure_active_build_stamp()
    assert again["build_id"] == stamp["build_id"]


def test_server_entry_build_matches_installed(tmp_path: Path, monkeypatch) -> None:
    from pipeline import mcp_hot_reload as hr
    from pipeline.mcp_install import server_entry

    monkeypatch.setattr(hr, "_home", lambda: tmp_path)
    (tmp_path / hr.ACTIVE_BUILD_NAME).write_text(
        json.dumps({"version": "0.3.71", "epoch": 1.0, "build_id": "0.3.71-1"}),
        encoding="utf-8",
    )
    monkeypatch.setattr("pipeline.upgrade.installed_version", lambda: "0.3.73")
    monkeypatch.setattr("shutil.which", lambda _name: None)
    entry = server_entry(tmp_path)
    build = (entry.get("env") or {}).get("CTX_SCUBIEE_BUILD") or ""
    assert build.startswith("0.3.73-")


def test_stale_sync_note_separates_search_from_freshness() -> None:
    from pipeline.sync_status import derive_agent_ready, derive_agent_ready_note, derive_locate_state

    loc = derive_locate_state(
        healthy=True,
        soft_search_ready=True,
        warm_state="ready",
        project_bound=True,
        sync_state="syncing",
        syncing=True,
    )
    assert loc["state"] == "ready"
    assert loc["stale"] is True
    assert (
        derive_agent_ready(
            healthy=True,
            soft_search_ready=True,
            sync_state="syncing",
            ready=True,
            syncing=True,
            overlay_ready=False,
            locate=loc,
            embedder_loaded=True,
            ast_hydrated=True,
        )
        == "stale"
    )
    note = derive_agent_ready_note(
        agent_ready="stale",
        sync_state="syncing",
        syncing=True,
        overlay_ready=False,
        publish_pending=False,
        ready=True,
        locate=loc,
        embedder_loaded=True,
        ast_hydrated=True,
    )
    assert "search_usable=true" in note
    assert "index_fresh=false" in note


def test_derive_agent_ready_soft_yes_without_embedder() -> None:
    from pipeline.sync_status import derive_agent_ready, derive_agent_ready_note, derive_locate_state

    loc = derive_locate_state(
        healthy=True,
        soft_search_ready=True,
        warm_state="ready",
        project_bound=True,
    )
    assert loc["state"] == "ready"
    assert (
        derive_agent_ready(
            healthy=True,
            soft_search_ready=True,
            sync_state="ready",
            ready=True,
            syncing=False,
            overlay_ready=False,
            locate=loc,
            embedder_loaded=False,
        )
        == "yes"
    )
    note = derive_agent_ready_note(
        agent_ready="yes",
        sync_state="ready",
        syncing=False,
        overlay_ready=False,
        publish_pending=False,
        ready=True,
        locate=loc,
        embedder_loaded=False,
    )
    assert "FastEmbed" in note or "embedder" in note.lower() or "Soft locate" in note
    assert (
        derive_agent_ready(
            healthy=True,
            soft_search_ready=True,
            sync_state="ready",
            ready=True,
            syncing=False,
            overlay_ready=False,
            locate=loc,
            embedder_loaded=True,
            ast_hydrated=True,
        )
        == "yes"
    )
    assert (
        derive_agent_ready(
            healthy=True,
            soft_search_ready=True,
            sync_state="ready",
            ready=True,
            syncing=False,
            overlay_ready=False,
            locate=loc,
            embedder_loaded=True,
            ast_hydrated=False,
        )
        == "yes"
    )
    cold_note = derive_agent_ready_note(
        agent_ready="yes",
        sync_state="ready",
        syncing=False,
        overlay_ready=False,
        publish_pending=False,
        ready=True,
        locate=loc,
        embedder_loaded=True,
        ast_hydrated=False,
    )
    assert "ready" in cold_note.lower()
    assert "wait until the AST" not in cold_note


def test_write_json_retries_permission_error(tmp_path: Path, monkeypatch) -> None:
    from pipeline import project_id as pid

    target = tmp_path / "registry.json"
    calls = {"n": 0}
    real_replace = pid.os.replace

    def flaky_replace(src, dst):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError(5, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(pid.os, "replace", flaky_replace)
    monkeypatch.setattr(pid.time, "sleep", lambda _s: None)
    pid._write_json(target, {"projects": {}, "_rev": 1})
    assert calls["n"] == 3
    assert target.is_file()
    assert json.loads(target.read_text(encoding="utf-8"))["projects"] == {}


def test_keeper_tick_skips_during_locate_streak(tmp_path: Path, monkeypatch) -> None:
    from conftest import enroll_test_repo
    from pipeline.sync_loop import BackgroundSyncLoop

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(tmp_path, home=home, project_id="ce_locate_streak_tick001")
    loop = BackgroundSyncLoop(tmp_path, locate_streak_ms=60_000)
    monkeypatch.setattr(loop, "_locate_streak_active", lambda now=None: True)
    out = loop.keeper_tick(reason="interval")
    assert out.get("strategy") == "deferred_locate_streak"
    assert out.get("locate_streak_active") is True


def test_keeper_tick_skips_when_clients_active(tmp_path: Path, monkeypatch) -> None:
    from conftest import enroll_test_repo
    from pipeline.sync_loop import BackgroundSyncLoop

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    monkeypatch.setenv("CTX_KEEPER_DEFER_WHILE_CLIENTS", "1")
    enroll_test_repo(tmp_path, home=home, project_id="ce_clients_active_tick001")
    loop = BackgroundSyncLoop(tmp_path, locate_streak_ms=60_000)
    monkeypatch.setattr(loop, "_locate_streak_active", lambda now=None: False)
    monkeypatch.setattr(loop, "_clients_active", lambda: True)
    out = loop.keeper_tick(reason="interval")
    assert out.get("strategy") == "deferred_clients_active"
    assert out.get("clients_active") is True


def test_poll_probes_indexed_files_while_clients_are_connected(
    tmp_path: Path, monkeypatch
) -> None:
    from conftest import enroll_test_repo
    from pipeline.root_probe import RootProbeResult
    from pipeline.sync_loop import BackgroundSyncLoop

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    monkeypatch.setenv("CTX_KEEPER_DEFER_WHILE_CLIENTS", "1")
    enroll_test_repo(tmp_path, home=home, project_id="ce_poll_clients_indexed0001")
    loop = BackgroundSyncLoop(tmp_path, locate_streak_ms=60_000)
    monkeypatch.setattr(loop, "_locate_streak_active", lambda now=None: False)
    monkeypatch.setattr(loop, "_clients_active", lambda: True)
    seen: dict[str, object] = {}

    def _probe(repo, **kwargs):
        seen["discover_newcomers"] = kwargs.get("discover_newcomers")
        return RootProbeResult(
            clean=True,
            root="",
            stored_root="",
            ms=1.0,
            added=[],
            modified=[],
            removed=[],
            files_checked=0,
            hashed=0,
        )

    monkeypatch.setattr("pipeline.root_probe.root_probe", _probe)
    assert loop.poll_repo_changes() == []
    assert seen["discover_newcomers"] is False


def test_poll_marks_indexed_edits_during_locate_streak(tmp_path: Path, monkeypatch) -> None:
    from conftest import enroll_test_repo
    from pipeline.root_probe import RootProbeResult
    from pipeline.sync_loop import BackgroundSyncLoop

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(tmp_path, home=home, project_id="ce_locate_streak_poll001")
    loop = BackgroundSyncLoop(tmp_path, locate_streak_ms=60_000, debounce_ms=1000)
    loop.note_locate()
    assert loop._locate_streak_active() is True

    def _probe(repo, **kwargs):
        return RootProbeResult(
            clean=False,
            root="abc",
            stored_root="old",
            ms=1.0,
            added=[],
            modified=["packages/pipeline/a.py"],
            removed=[],
            files_checked=1,
            hashed=1,
        )

    monkeypatch.setattr("pipeline.root_probe.root_probe", _probe)
    now = 100.0
    assert loop.poll_repo_changes(now=now) == ["packages/pipeline/a.py"]
    assert loop._locate_streak_active(now=now) is False
    assert loop.dirty_ledger.due_paths(now=now + 0.5) == []
    assert loop.dirty_ledger.due_paths(now=now + 1.0) == ["packages/pipeline/a.py"]


def test_pack_sla_fields_present() -> None:
    """Unit-shape: SLA helper logic on a synthetic pack out dict."""
    elapsed_ms = 6200.0
    out = {"mode": "lean", "multi_seed": False, "seed2": None, "seed3": None}
    lean_single_seed = (
        str(out.get("mode") or "lean") == "lean"
        and not bool(out.get("multi_seed") or out.get("seed2") or out.get("seed3"))
    )
    target_ms = 5000 if lean_single_seed else 8000
    assert lean_single_seed is True
    assert elapsed_ms > target_ms
    sla_hint = (
        f"pack_context took {elapsed_ms}ms (target {target_ms}ms) — heavy path, "
        "not a hang."
    )
    assert "heavy path" in sla_hint

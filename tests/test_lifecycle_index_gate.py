"""Idle-stop gate on the authoritative index state (spec task 6).

The engine must NOT idle-stop while the durable index_state says work is owed
(indexing / reconciling / interrupted) even with zero clients — otherwise an
offline-reconcile detected on start (no client attached) could be stopped before
it drains. When the state is fresh and the disconnect debounce has elapsed with
no clients, idle-stop proceeds. Guarded by CTX_UNIFIED_STATE.

Offline; CTX_HOME tmp; no live engine.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pipeline import lifecycle_runtime as life


PID = "ce_gate"


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_UNIFIED_STATE", "1")
    import pipeline.index_state as ix

    ix.reset_for_tests()
    yield
    ix.reset_for_tests()


def _bind_project(monkeypatch, repo):
    """Point lifecycle's index-state probe at project PID bound to `repo`."""
    import pipeline.lifecycle_runtime as L

    monkeypatch.setattr(
        "pipeline.ce_service.get_context_engine",
        lambda: SimpleNamespace(repo=repo, warm_state="ready"),
    )
    monkeypatch.setattr(
        "pipeline.project_id.peek_project",
        lambda _r: SimpleNamespace(project_id=PID),
    )
    return L


def _set_state(state, pending=None):
    from pipeline.index_state import IndexStateDoc, write_index_state

    write_index_state(PID, IndexStateDoc(state=state, pending=pending))


def test_reconciling_blocks_idle_stop_with_zero_clients(tmp_path, monkeypatch):
    L = _bind_project(monkeypatch, tmp_path / "repo")
    _set_state("reconciling")

    reason = L._index_state_busy_reason()
    assert reason == "index_state:reconciling"
    # and the top-level gate reflects it
    assert L._idle_busy_reason() == "index_state:reconciling"


def test_interrupted_blocks_idle_stop(tmp_path, monkeypatch):
    L = _bind_project(monkeypatch, tmp_path / "repo")
    _set_state("interrupted")
    assert L._index_state_busy_reason() == "index_state:interrupted"


def test_indexing_blocks_idle_stop(tmp_path, monkeypatch):
    L = _bind_project(monkeypatch, tmp_path / "repo")
    _set_state("indexing")
    assert L._index_state_busy_reason() == "index_state:indexing"


def test_fresh_does_not_block(tmp_path, monkeypatch):
    L = _bind_project(monkeypatch, tmp_path / "repo")
    _set_state("fresh")
    assert L._index_state_busy_reason() is None


def test_stale_small_catchup_does_not_block(tmp_path, monkeypatch):
    # stale = small background catch-up; it is NOT a busy state (not in
    # BUSY_STATES) so idle-stop may proceed. The keeper drains it on next start.
    L = _bind_project(monkeypatch, tmp_path / "repo")
    _set_state("stale")
    assert L._index_state_busy_reason() is None


def test_rollback_switch_disables_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_UNIFIED_STATE", "0")
    L = _bind_project(monkeypatch, tmp_path / "repo")
    _set_state("reconciling")
    # with the unified model off, the index_state gate is a no-op
    assert L._index_state_busy_reason() is None


def test_full_idle_stop_allowed_when_fresh_and_debounce_elapsed(tmp_path, monkeypatch):
    L = _bind_project(monkeypatch, tmp_path / "repo")
    _set_state("fresh")
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "30")
    L.set_desired_mode(L.DESIRED_RUN)
    L.register_client("mcp:1", pid=1, now=100.0)
    L.unregister_client("mcp:1", now=100.0)
    # debounce elapsed, no clients, index fresh -> idle-stop proceeds
    assert L.should_idle_stop(now=131.0) is True


def test_reconciling_blocks_should_idle_stop_even_after_debounce(tmp_path, monkeypatch):
    L = _bind_project(monkeypatch, tmp_path / "repo")
    _set_state("reconciling")
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "30")
    L.set_desired_mode(L.DESIRED_RUN)
    L.register_client("mcp:1", pid=1, now=100.0)
    L.unregister_client("mcp:1", now=100.0)
    # debounce elapsed and no clients, but reconcile is owed -> still blocked
    assert L.should_idle_stop(now=131.0) is False

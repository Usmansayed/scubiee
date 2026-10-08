"""Agent-facing pending-contract tests (spec task 5.3).

Covers the derivation in ``index_state.agent_pending`` (what the agent is told)
and the ``tool_status`` formatting that renders it. The contract rule: pending is
surfaced ONLY when the index state is actionable (reconciling / interrupted) AND
the work is substantial — small catch-up stays silent — and the current index
keeps serving (``search_usable=true``) throughout a reconcile.

Offline; CTX_HOME tmp; no live engine/embedder.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    import pipeline.index_state as ix

    ix.reset_for_tests()
    yield
    ix.reset_for_tests()


PID = "ce_pending"


def _write(state, pending=None, build=None):
    from pipeline.index_state import IndexStateDoc, write_index_state

    write_index_state(PID, IndexStateDoc(state=state, pending=pending, build=build))


# ---- agent_pending derivation ----------------------------------------------

def test_fresh_has_no_pending():
    from pipeline.index_state import agent_pending

    _write("fresh")
    assert agent_pending(PID) is None


def test_stale_small_catchup_is_silent():
    from pipeline.index_state import PendingSummary, agent_pending

    # a small incremental drift recorded as stale -> NOT surfaced
    _write("stale", pending=PendingSummary(substantial=False, reason="incremental"))
    assert agent_pending(PID) is None


def test_reconciling_non_substantial_is_silent():
    from pipeline.index_state import PendingSummary, agent_pending

    # even in reconciling, a non-substantial summary must not nag the agent
    _write("reconciling", pending=PendingSummary(substantial=False))
    assert agent_pending(PID) is None


def test_reconciling_substantial_is_surfaced():
    from pipeline.index_state import PendingSummary, agent_pending

    _write(
        "reconciling",
        pending=PendingSummary(
            substantial=True,
            reason="offline_batch",
            estimated_units=318,
            estimated_seconds=42.0,
            total_units=318,
            search_usable=True,
        ),
    )
    p = agent_pending(PID)
    assert p is not None
    assert p["substantial"] is True
    assert p["state"] == "reconciling"
    assert p["reason"] == "offline_batch"
    assert p["estimated_seconds"] == 42.0
    assert p["total_units"] == 318
    assert p["search_usable"] is True
    assert p["action"] is None


def test_needs_full_sets_action():
    from pipeline.index_state import PendingSummary, agent_pending

    _write(
        "reconciling",
        pending=PendingSummary(
            substantial=True,
            reason="full_reindex",
            action="scubiee index . --force",
        ),
    )
    p = agent_pending(PID)
    assert p is not None
    assert p["action"] == "scubiee index . --force"


def test_interrupted_is_always_surfaced_even_without_summary():
    from pipeline.index_state import agent_pending

    _write("interrupted", pending=None)
    p = agent_pending(PID)
    assert p is not None
    assert p["substantial"] is True
    assert p["state"] == "interrupted"
    assert p["reason"] == "resuming_interrupted"
    assert p["search_usable"] is True


def test_search_usable_true_during_reconcile():
    from pipeline.index_state import PendingSummary, agent_pending

    # the current generation keeps serving while reconcile runs
    _write(
        "reconciling",
        pending=PendingSummary(substantial=True, reason="offline_batch", search_usable=True),
    )
    assert agent_pending(PID)["search_usable"] is True


def test_missing_project_is_none():
    from pipeline.index_state import agent_pending

    assert agent_pending("") is None
    assert agent_pending("ce_never_written") is None


# ---- tool_status formatting -------------------------------------------------

def _patch_health(monkeypatch, health):
    import pipeline.map_v3_helpers as mv

    monkeypatch.setattr(mv, "_http", lambda *a, **k: health)


def test_tool_status_omits_pending_when_none(monkeypatch):
    import pipeline.map_v3_helpers as mv

    _patch_health(
        monkeypatch,
        {"ok": True, "warm_ready": True, "dense_ready": True,
         "warm_phase": "dense", "chunks": 100, "version": "0.3.143", "pending": None},
    )
    line = mv.tool_status({})
    assert "pending=" not in line
    assert "ok=True" in line


def test_tool_status_omits_pending_when_not_substantial(monkeypatch):
    import pipeline.map_v3_helpers as mv

    _patch_health(
        monkeypatch,
        {"ok": True, "warm_ready": True, "dense_ready": True, "chunks": 10,
         "pending": {"substantial": False, "state": "stale"}},
    )
    assert "pending=" not in mv.tool_status({})


def test_tool_status_renders_substantial_pending(monkeypatch):
    import pipeline.map_v3_helpers as mv

    _patch_health(
        monkeypatch,
        {"ok": True, "warm_ready": True, "dense_ready": True, "chunks": 10,
         "pending": {
             "substantial": True, "state": "reconciling", "reason": "offline_batch",
             "estimated_seconds": 42.0, "search_usable": True, "action": None,
         }},
    )
    line = mv.tool_status({})
    assert "pending=reconciling(offline_batch)" in line
    assert "~42s" in line
    assert "search_usable=true" in line


def test_tool_status_renders_action_when_full_reindex(monkeypatch):
    import pipeline.map_v3_helpers as mv

    _patch_health(
        monkeypatch,
        {"ok": True, "chunks": 10,
         "pending": {
             "substantial": True, "state": "reconciling", "reason": "full_reindex",
             "estimated_seconds": 0, "search_usable": True,
             "action": "scubiee index . --force",
         }},
    )
    line = mv.tool_status({})
    assert "action='scubiee index . --force'" in line


def test_tool_status_has_no_dirty_count(monkeypatch):
    import pipeline.map_v3_helpers as mv

    _patch_health(
        monkeypatch,
        {"ok": True, "warm_ready": True, "chunks": 10, "pending": None},
    )
    assert "dirty_count" not in mv.tool_status({})

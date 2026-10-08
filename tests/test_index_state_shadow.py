"""Shadow-write integration (spec task 1.3/1.4).

Verifies that RuntimeManager._stamp_generation writes index_state.json tracking
the live generation, WITHOUT changing any existing behavior (it is best-effort
and swallows all errors). Offline — fabricates a RepoRuntime + store, no engine.
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


def test_stamp_generation_shadow_tracks_generation(tmp_path, monkeypatch):
    from pipeline.index_state import load_index_state
    from pipeline.repo_runtime import RepoRuntime

    pid = "ce_shadowtest"

    # peek_project returns None here (repo not enrolled), so the shadow write
    # takes the best-effort path with indexed_head/merkle_root = None. That is
    # exactly the "never raises, still records generation" guarantee we want.
    monkeypatch.setattr("pipeline.project_id.peek_project", lambda *_a, **_k: None)

    from pipeline.ce_service import RuntimeManager

    rt = RepoRuntime(project_id=pid, repo=tmp_path, generation=5, epoch="ep-xyz")
    RuntimeManager._stamp_generation(rt)

    doc = load_index_state(pid)
    assert doc.state == "fresh"
    assert doc.generation_counter == 5
    assert doc.generation_epoch == "ep-xyz"


def test_stamp_generation_shadow_advances_monotonically(tmp_path, monkeypatch):
    from pipeline.index_state import load_index_state
    from pipeline.ce_service import RuntimeManager
    from pipeline.repo_runtime import RepoRuntime

    monkeypatch.setattr("pipeline.project_id.peek_project", lambda *_a, **_k: None)
    pid = "ce_shadowmono"
    rt = RepoRuntime(project_id=pid, repo=tmp_path, generation=1, epoch="ep1")

    RuntimeManager._stamp_generation(rt)
    rt.generation = 2
    RuntimeManager._stamp_generation(rt)
    rt.generation = 3
    RuntimeManager._stamp_generation(rt)

    assert load_index_state(pid).generation_counter == 3


def test_stamp_generation_never_raises_on_bad_runtime():
    from pipeline.ce_service import RuntimeManager

    # None runtime, and a runtime with no project_id — both must be no-ops.
    RuntimeManager._stamp_generation(None)
    from pipeline.repo_runtime import RepoRuntime
    from pathlib import Path

    rt = RepoRuntime(project_id="", repo=Path("."), generation=1)
    RuntimeManager._stamp_generation(rt)  # must not raise

"""Reconciler tests (spec task 3.5).

Builds a real tmp repo + persisted merkle baseline, mutates the working tree,
and asserts reconcile() detects the drift, enqueues it durably, and records the
index state — idempotently. Offline; CTX_HOME tmp; no live engine/embedder.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_UNIFIED_STATE", "1")
    import pipeline.index_state as ix

    ix.reset_for_tests()
    yield
    ix.reset_for_tests()


def _make_store(repo, project_id="ce_recon"):
    """A PipelineStore whose base is under CTX_HOME projects/<id>."""
    from pipeline.project_id import projects_root
    from pipeline.store import PipelineStore

    base = projects_root() / project_id
    base.mkdir(parents=True, exist_ok=True)
    return PipelineStore(repo, base_dir=base, project_id=project_id, resolve=False)


def _index_file(repo, rel, text):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _persist_baseline(store, repo, rels):
    """Persist a merkle snapshot covering `rels` as the 'indexed' baseline."""
    from pipeline.merkle import file_sha256

    hashes = {rel: file_sha256(repo / rel) for rel in rels}
    store.save_merkle(hashes)
    # minimal meta so load paths don't choke
    store.save_meta({"chunks": len(rels)})


class _FakeJournal:
    """Captures enqueued (paths, reason) — stands in for keeper.mark_dirty."""

    def __init__(self):
        self.calls: list[tuple[list[str], str]] = []

    def __call__(self, paths, reason):
        self.calls.append((sorted(paths), reason))

    @property
    def all_paths(self):
        out: set[str] = set()
        for paths, _r in self.calls:
            out.update(paths)
        return out


def test_detects_and_enqueues_modified_file(tmp_path):
    from pipeline.reconciler import reconcile

    repo = tmp_path / "repo"
    repo.mkdir()
    _index_file(repo, "a.py", "def a():\n    return 1\n")
    _index_file(repo, "b.py", "def b():\n    return 2\n")
    store = _make_store(repo)
    _persist_baseline(store, repo, ["a.py", "b.py"])

    # modify a.py on disk after the baseline
    _index_file(repo, "a.py", "def a():\n    return 999\n")

    jr = _FakeJournal()
    plan = reconcile(repo, trigger="start", store=store, project_id="ce_recon", enqueue=jr)

    assert "a.py" in plan.modified
    assert "a.py" in jr.all_paths
    assert plan.enqueued and "a.py" in plan.enqueued
    assert plan.index_state in {"stale", "reconciling"}


def test_detects_added_and_removed(tmp_path):
    from pipeline.reconciler import reconcile

    repo = tmp_path / "repo"
    repo.mkdir()
    _index_file(repo, "keep.py", "x = 1\n")
    _index_file(repo, "gone.py", "y = 2\n")
    store = _make_store(repo)
    _persist_baseline(store, repo, ["keep.py", "gone.py"])

    # add a new file, remove an indexed one
    _index_file(repo, "new.py", "def new():\n    return 3\n")
    (repo / "gone.py").unlink()

    jr = _FakeJournal()
    plan = reconcile(repo, trigger="start", store=store, project_id="ce_recon", enqueue=jr)

    assert "new.py" in plan.added
    assert "gone.py" in plan.removed
    assert {"new.py", "gone.py"} <= jr.all_paths


def test_clean_tree_is_fresh_no_enqueue(tmp_path):
    from pipeline.reconciler import reconcile

    repo = tmp_path / "repo"
    repo.mkdir()
    _index_file(repo, "a.py", "def a():\n    return 1\n")
    store = _make_store(repo)
    _persist_baseline(store, repo, ["a.py"])

    jr = _FakeJournal()
    plan = reconcile(repo, trigger="start", store=store, project_id="ce_recon", enqueue=jr)

    assert plan.clean is True
    assert plan.drift_count == 0
    assert jr.calls == []
    assert plan.index_state == "fresh"


def test_idempotent_same_drift_same_result(tmp_path):
    from pipeline.index_state import load_index_state
    from pipeline.reconciler import reconcile

    repo = tmp_path / "repo"
    repo.mkdir()
    _index_file(repo, "a.py", "def a():\n    return 1\n")
    store = _make_store(repo)
    _persist_baseline(store, repo, ["a.py"])
    _index_file(repo, "a.py", "def a():\n    return 2\n")  # drift

    jr1 = _FakeJournal()
    p1 = reconcile(repo, trigger="start", store=store, project_id="ce_recon", enqueue=jr1)
    s1 = load_index_state("ce_recon").state

    jr2 = _FakeJournal()
    p2 = reconcile(repo, trigger="poll", store=store, project_id="ce_recon", enqueue=jr2)
    s2 = load_index_state("ce_recon").state

    # same drift set both times; state stable (not flapping)
    assert p1.modified == p2.modified == ["a.py"]
    assert jr1.all_paths == jr2.all_paths == {"a.py"}
    assert s1 == s2


def test_folder_of_many_files_added_offline_all_detected(tmp_path):
    from pipeline.reconciler import reconcile

    repo = tmp_path / "repo"
    repo.mkdir()
    _index_file(repo, "root.py", "r = 1\n")
    store = _make_store(repo)
    _persist_baseline(store, repo, ["root.py"])

    # a whole new folder of files appears while "offline"
    for i in range(25):
        _index_file(repo, f"pkg/mod_{i}.py", f"def f{i}():\n    return {i}\n")

    jr = _FakeJournal()
    plan = reconcile(repo, trigger="start", store=store, project_id="ce_recon", enqueue=jr)

    found = {p for p in plan.added if p.startswith("pkg/mod_")}
    assert len(found) == 25, f"only detected {len(found)}/25 newcomers"
    assert found <= jr.all_paths


def test_interrupted_build_sets_interrupted_state(tmp_path):
    from pipeline.index_state import (
        BuildRecord, IndexStateDoc, write_index_state,
    )
    from pipeline.reconciler import reconcile

    repo = tmp_path / "repo"
    repo.mkdir()
    _index_file(repo, "a.py", "x=1\n")
    store = _make_store(repo)
    _persist_baseline(store, repo, ["a.py"])

    # a build record owned by a dead pid
    write_index_state(
        "ce_recon",
        IndexStateDoc(
            state="indexing",
            build=BuildRecord(build_id="b", pid=2_000_000_000, kind="full", started_at=1.0),
        ),
    )

    jr = _FakeJournal()
    plan = reconcile(repo, trigger="start", store=store, project_id="ce_recon", enqueue=jr)

    assert plan.interrupted_build is not None
    assert plan.index_state == "interrupted"


def test_disabled_switch_makes_reconcile_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_UNIFIED_STATE", "0")
    from pipeline.reconciler import reconcile

    repo = tmp_path / "repo"
    repo.mkdir()
    _index_file(repo, "a.py", "x=1\n")
    store = _make_store(repo)
    _persist_baseline(store, repo, ["a.py"])
    _index_file(repo, "a.py", "x=2\n")

    jr = _FakeJournal()
    plan = reconcile(repo, trigger="start", store=store, project_id="ce_recon", enqueue=jr)

    assert plan.skipped == "unified_state_disabled"
    assert jr.calls == []  # no enqueue when the rollback switch is off

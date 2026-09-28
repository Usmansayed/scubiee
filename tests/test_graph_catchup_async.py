"""Issue 6: graph catch-ups merge in a child process; the keeper keeps serving saves."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import graph_merge_worker as gmw


# ---------------------------------------------------------------- worker ----


def _seed_graph(repo: Path, store: Path) -> Path:
    from conductor.graphify_retriever import build_and_save_graph
    from graphify.extract import extract

    raw = extract([repo / "pkg" / "a.py"], root=repo, cache_root=store)
    graph = store / "graph.json"
    build_and_save_graph(raw, repo, graph)
    return graph


def _sources(graph: Path) -> set[str]:
    data = json.loads(graph.read_text(encoding="utf-8"))
    return {str(n.get("source_file") or "").replace("\\", "/") for n in data.get("nodes") or []}


@pytest.fixture()
def graph_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    store = tmp_path / "store"
    store.mkdir()
    graph = _seed_graph(repo, store)
    (repo / "pkg" / "b.py").write_text(
        "from pkg.a import alpha\n\n\ndef beta_catchup():\n    return alpha()\n", encoding="utf-8"
    )
    return repo, store, graph


def test_worker_merges_into_a_temp_file_and_leaves_graph_json_alone(graph_repo) -> None:
    repo, store, graph = graph_repo
    before = graph.read_bytes()
    out = store / ".graph_catchup.t.json"
    result = store / ".graph_catchup.t.result"
    spec = store / ".graph_catchup.t.paths"
    spec.write_text(json.dumps({"paths": ["pkg/b.py"]}), encoding="utf-8")

    rc = gmw.main(
        ["--root", str(repo), "--graph", str(graph), "--out", str(out),
         "--result", str(result), "--paths-file", str(spec)]
    )

    assert rc == 0
    info = json.loads(result.read_text(encoding="utf-8"))
    assert info["ok"] is True and info["files"] == 1
    assert graph.read_bytes() == before, "the worker must never write graph.json"
    merged = _sources(out)
    assert any(s.endswith("pkg/b.py") for s in merged), merged
    assert any(s.endswith("pkg/a.py") for s in merged), "unchanged files are carried forward"
    assert not spec.exists(), "the paths file is consumed"


def test_worker_prunes_a_file_deleted_before_its_catchup(graph_repo) -> None:
    repo, store, graph = graph_repo
    assert any(s.endswith("pkg/a.py") for s in _sources(graph))
    (repo / "pkg" / "a.py").unlink()
    out = store / ".graph_catchup.g.json"
    result = store / ".graph_catchup.g.result"
    spec = store / ".graph_catchup.g.paths"
    spec.write_text(json.dumps({"paths": ["pkg/a.py"]}), encoding="utf-8")

    rc = gmw.main(
        ["--root", str(repo), "--graph", str(graph), "--out", str(out),
         "--result", str(result), "--paths-file", str(spec)]
    )

    assert rc == 0, result.read_text(encoding="utf-8")
    assert not any(s.endswith("pkg/a.py") for s in _sources(out)), "deleted file left ghost nodes"


def test_hold_keeps_a_gone_graph_catchup_so_it_can_prune(monkeypatch, tmp_path: Path) -> None:
    from conftest import enroll_test_repo
    from pipeline.sync_loop import BackgroundSyncLoop

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(tmp_path, home=home, project_id="ce_graphgone1234567890abcdef00")
    loop = BackgroundSyncLoop(tmp_path, debounce_ms=0)
    loop.dirty_ledger.mark(["pkg/gone.py"], reason="graph_catchup", now=0.0)
    loop._last_hot_mark_at = None

    kept = loop._hold_graph_catchups(["pkg/gone.py"], now=100.0)

    assert kept == ["pkg/gone.py"]
    assert loop.dirty_ledger.snapshot()["paths"]["pkg/gone.py"]["state"] != "published"


def test_worker_reports_failure_without_an_output(graph_repo) -> None:
    repo, store, _graph = graph_repo
    bad = store / "not-json.json"
    bad.write_text("{", encoding="utf-8")
    out = store / ".graph_catchup.f.json"
    result = store / ".graph_catchup.f.result"
    spec = store / ".graph_catchup.f.paths"
    spec.write_text(json.dumps({"paths": ["pkg/b.py"]}), encoding="utf-8")

    rc = gmw.main(
        ["--root", str(repo), "--graph", str(bad), "--out", str(out),
         "--result", str(result), "--paths-file", str(spec)]
    )

    assert rc == 1
    assert json.loads(result.read_text(encoding="utf-8"))["ok"] is False
    assert not out.exists()


def test_start_graph_merge_runs_a_real_child_process(graph_repo) -> None:
    repo, store, graph = graph_repo
    job = gmw.start_graph_merge(repo, store, ["pkg/b.py"])
    deadline = time.monotonic() + 120
    info = None
    while time.monotonic() < deadline:
        info = job.poll()
        if info is not None:
            break
        time.sleep(0.1)
    log = job.log_path.read_text(encoding="utf-8", errors="replace") if job.log_path else ""
    assert info is not None and info.get("ok"), f"{info} log={log[-2000:]}"
    assert job.graph_unchanged()
    assert any(s.endswith("pkg/b.py") for s in _sources(job.out))
    job.discard()
    assert not job.out.exists()


def test_sweep_removes_only_old_temps(tmp_path: Path) -> None:
    old = tmp_path / ".graph_catchup.1.json"
    stale_atomic = tmp_path / ".graph.json.abc123.tmp"
    fresh = tmp_path / ".graph_catchup.2.json"
    for p in (old, stale_atomic, fresh):
        p.write_text("{}", encoding="utf-8")
    past = time.time() - 3600
    os.utime(old, (past, past))
    os.utime(stale_atomic, (past, past))

    removed = gmw.sweep_stale_temps(tmp_path)

    assert sorted(removed) == sorted([old.name, stale_atomic.name])
    assert fresh.exists()


# ---------------------------------------------------------------- keeper ----


class _FakeJob:
    def __init__(self, paths: list[str], store: Path):
        self.paths = list(paths)
        self.out = store / ".graph_catchup.fake.json"
        self.out.write_text("{}", encoding="utf-8")
        self.started_at = time.monotonic()
        self.proc = SimpleNamespace(pid=4242)
        self.result: dict | None = None
        self.unchanged = True
        self.discarded = False
        self.killed = False

    def poll(self):
        return self.result

    def graph_unchanged(self):
        return self.unchanged

    def discard(self):
        self.discarded = True

    def kill(self):
        self.killed = True


@pytest.fixture()
def keeper(monkeypatch, tmp_path: Path):
    from pipeline.sync_loop import BackgroundSyncLoop

    from conftest import enroll_test_repo

    monkeypatch.setenv("CTX_GRAPH_CATCHUP_ASYNC", "1")
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(repo, home=home, project_id="ce_graphasync1234567890abcdef0")
    monkeypatch.setattr(
        "pipeline.sync_loop.BackgroundSyncLoop._clients_active", lambda self: False
    )
    for name in ("a.py", "b.py"):
        (repo / "pkg" / name).write_text(f"def {name[0]}():\n    return 1\n", encoding="utf-8")
    store = tmp_path / "store"
    store.mkdir()
    (store / "graph.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "pipeline.sync_loop.peek_project",
        lambda _repo: SimpleNamespace(store_dir=store, project_id="ce_test"),
    )
    loop = BackgroundSyncLoop(repo, debounce_ms=0, hot_debounce_ms=0)
    loop.graph_catchup_quiet_s = 0.0
    jobs: list[_FakeJob] = []

    def _start(_root, _store, paths, **_k):
        job = _FakeJob(paths, store)
        jobs.append(job)
        return job

    monkeypatch.setattr(gmw, "start_graph_merge", _start)
    calls: list[dict] = []

    def _sync(paths, *, reason, hot=False, graph_precomputed=None):
        calls.append({"paths": list(paths), "hot": hot, "graph": graph_precomputed, "reason": reason})
        return {"refreshed": False, "chunks_upserted": 0, "chunks_removed": 0, "files": list(paths)}

    monkeypatch.setattr(loop, "_sync_paths", _sync)
    monkeypatch.setattr(loop, "_invalidate_session_paths", lambda _p: None)
    return loop, jobs, calls, store


def _state(loop, path: str) -> dict:
    from pipeline.dirty_ledger import normalize_dirty_path

    return loop.dirty_ledger.snapshot()["paths"][normalize_dirty_path(path)]


def test_catchup_is_handed_to_a_child_and_a_save_runs_meanwhile(keeper) -> None:
    loop, jobs, calls, _store = keeper
    loop.dirty_ledger.mark(["pkg/a.py"], reason="graph_catchup", now=0.0)

    out = loop.drain_due(now=10.0)

    assert out and out[0]["strategy"] == "graph_catchup_async"
    assert len(jobs) == 1 and jobs[0].paths == ["pkg/a.py"]
    assert calls == [], "the keeper must not run the merge inline"
    assert _state(loop, "pkg/a.py")["state"] == "processing"

    # A save lands while the child merges: it is synced right away (hot).
    loop.mark_dirty(["pkg/b.py"], reason="changed_file", now=10.5)
    loop.drain_due(now=11.0)
    assert [c["paths"] for c in calls] == [["pkg/b.py"]]
    assert calls[0]["hot"] is True and calls[0]["graph"] is None

    # The child finishes: the next tick commits its graph for A only.
    jobs[0].result = {"ok": True, "ms": 9000, "wall_ms": 9100, "nodes": 10}
    loop.drain_due(now=20.0)
    commit = calls[-1]
    assert commit["paths"] == ["pkg/a.py"] and commit["graph"] == jobs[0].out
    assert commit["hot"] is False
    assert _state(loop, "pkg/a.py")["state"] == "published"
    assert loop._graph_job is None and jobs[0].discarded


def test_a_second_catchup_waits_for_the_running_job(keeper) -> None:
    loop, jobs, calls, _store = keeper
    loop.dirty_ledger.mark(["pkg/a.py"], reason="graph_catchup", now=0.0)
    loop.drain_due(now=10.0)
    loop.dirty_ledger.mark(["pkg/b.py"], reason="graph_catchup", now=0.0)

    out = loop.drain_due(now=11.0)

    assert out[0]["strategy"] == "graph_catchup_waiting"
    assert len(jobs) == 1 and calls == []
    assert _state(loop, "pkg/b.py")["state"] == "queued"


def test_graph_changed_under_the_job_discards_and_requeues(keeper) -> None:
    loop, jobs, calls, _store = keeper
    loop.dirty_ledger.mark(["pkg/a.py"], reason="graph_catchup", now=0.0)
    loop.drain_due(now=10.0)
    jobs[0].result = {"ok": True, "wall_ms": 1}
    jobs[0].unchanged = False

    loop._poll_graph_job(now=20.0)

    assert calls == [], "a stale merge must never be committed"
    assert jobs[0].discarded
    entry = _state(loop, "pkg/a.py")
    assert entry["state"] == "queued" and entry["reason"] == "graph_catchup"


def test_a_file_resaved_during_the_merge_keeps_its_newer_entry(keeper) -> None:
    loop, jobs, calls, _store = keeper
    loop.dirty_ledger.mark(["pkg/a.py"], reason="graph_catchup", now=0.0)
    loop.drain_due(now=10.0)
    # A new save of A while its merge runs: a fresh hot entry replaces "processing".
    loop.mark_dirty(["pkg/a.py"], reason="changed_file", now=10.5)
    jobs[0].result = {"ok": True, "wall_ms": 1}

    loop._poll_graph_job(now=10.6)

    entry = _state(loop, "pkg/a.py")
    assert entry["state"] == "queued" and entry["reason"] != "graph_catchup", (
        "committing the older merge must not swallow the newer save"
    )


def test_repeated_worker_failures_fall_back_to_the_inline_merge(keeper) -> None:
    loop, jobs, calls, _store = keeper
    for i in range(2):
        loop.dirty_ledger.mark(["pkg/a.py"], reason="graph_catchup", now=0.0)
        loop.drain_due(now=10.0 + i * 10)
        jobs[-1].result = {"ok": False, "error": "boom", "wall_ms": 1}
        loop._poll_graph_job(now=11.0 + i * 10)
    assert len(jobs) == 2 and calls == []

    loop.dirty_ledger.mark(["pkg/a.py"], reason="graph_catchup", now=0.0)
    loop.drain_due(now=100.0)

    assert len(jobs) == 2, "no third child after two failures"
    assert calls and calls[-1]["paths"] == ["pkg/a.py"] and calls[-1]["graph"] is None


def test_stop_kills_a_running_job(keeper) -> None:
    loop, jobs, _calls, _store = keeper
    loop.dirty_ledger.mark(["pkg/a.py"], reason="graph_catchup", now=0.0)
    loop.drain_due(now=10.0)

    loop.stop()

    assert jobs[0].killed and loop._graph_job is None


def test_async_is_off_by_env(keeper, monkeypatch) -> None:
    loop, jobs, calls, _store = keeper
    monkeypatch.setenv("CTX_GRAPH_CATCHUP_ASYNC", "0")
    loop.dirty_ledger.mark(["pkg/a.py"], reason="graph_catchup", now=0.0)

    loop.drain_due(now=10.0)

    assert jobs == [] and calls and calls[0]["graph"] is None


# ----------------------------------------------------------- incremental ----


def test_precomputed_graph_replaces_graph_json_and_clears_only_its_debt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_sync_corpus_alignment import _hot_lane_repo

    from pipeline.incremental import incremental_sync

    repo, base, vdb, store, graph = _hot_lane_repo(tmp_path, monkeypatch)
    for rel in ("pkg/one.py", "pkg/two.py"):
        (repo / rel).write_text(f"def {Path(rel).stem}():\n    return 1\n", encoding="utf-8")
        incremental_sync(repo, base_dir=base, vdb=vdb, force_files=[rel], hot_lane=True,
                         capacity_wait_s=0.05).vector_flush()
    assert sorted(store.load_meta().get("graph_pending") or []) == ["pkg/one.py", "pkg/two.py"]

    def _no_inline(*_a, **_k):
        raise AssertionError("a precomputed graph must not be merged again")

    monkeypatch.setattr("pipeline.incremental.patch_and_save_graph", _no_inline)
    pre = base / ".graph_catchup.x.json"
    pre.write_text(json.dumps({"nodes": [{"id": "one", "source_file": "pkg/one.py"}],
                               "links": [], "hyperedges": []}), encoding="utf-8")

    result = incremental_sync(repo, base_dir=base, vdb=vdb, force_files=["pkg/one.py"],
                              capacity_wait_s=0.05, graph_precomputed=pre)

    assert result.error is None, result.error
    assert not pre.exists(), "renamed into place"
    assert json.loads(graph.read_text(encoding="utf-8"))["nodes"][0]["id"] == "one"
    assert store.load_meta().get("graph_pending") == ["pkg/two.py"], (
        "only the paths the child merged are paid off"
    )


# ------------------------------------------------ id reuse after a delete ----


def test_new_file_after_deleting_the_newest_file_does_not_compact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Found while proving issue 6: the first save after a delete took 7s in
    ``col.add`` because the new chunks reused the deleted file's (tombstoned)
    ids, which sends ``add`` down the upsert path: ``compact()`` of every vector.
    """
    from test_sync_corpus_alignment import _hot_lane_repo

    from pipeline.incremental import incremental_sync
    from pipeline.vectordb import FaissCollection

    repo, base, vdb, store, _graph = _hot_lane_repo(tmp_path, monkeypatch)

    def _sync(rel: str) -> None:
        r = incremental_sync(repo, base_dir=base, vdb=vdb, force_files=[rel], hot_lane=True,
                             capacity_wait_s=0.05)
        assert r.error is None, r.error
        if callable(r.vector_flush):
            r.vector_flush()

    (repo / "pkg" / "first.py").write_text("def first():\n    return 1\n", encoding="utf-8")
    _sync("pkg/first.py")
    first_ids = {c.id for c in store.load_chunks() if c.file == "pkg/first.py"}
    (repo / "pkg" / "first.py").unlink()
    _sync("pkg/first.py")

    compacts: list[int] = []
    real = FaissCollection.compact

    def _count(self):
        compacts.append(1)
        return real(self)

    monkeypatch.setattr(FaissCollection, "compact", _count)
    (repo / "pkg" / "second.py").write_text("def second():\n    return 2\n", encoding="utf-8")
    _sync("pkg/second.py")

    assert compacts == [], "a new file must not trigger a whole-collection compact"
    second = [c for c in store.load_chunks() if c.file == "pkg/second.py"]
    assert second and not ({c.id for c in second} & first_ids), "tombstoned ids are not reused"
    col = vdb.get_collection(store.collection_name)
    live = {int(i) for i in col.ids} - {int(i) for i in col.meta.dead_ids}
    assert {c.id for c in store.load_chunks()} <= live, "every chunk still has a live vector"


def test_avoid_tombstoned_ids_only_touches_clashing_records() -> None:
    from pipeline.incremental import _avoid_tombstoned_ids

    col = SimpleNamespace(ids=[1, 2, 3, 7])
    recs = [SimpleNamespace(id=3), SimpleNamespace(id=4), SimpleNamespace(id=7)]
    stages: dict[str, float] = {}

    assert _avoid_tombstoned_ids(col, recs, stages) == 2
    assert [r.id for r in recs] == [8, 4, 9]
    assert stages["id_remap"] == 2.0
    assert _avoid_tombstoned_ids(SimpleNamespace(ids=[]), recs, None) == 0

"""Property 2: Preservation - non-buggy inputs behave as before (beta-open-issues-fix task 2).

Observation-first: every golden in ``tests/fixtures/open_preservation/goldens.json``
was recorded on the UNFIXED code (``CTX_OPEN_PRESERVATION_RECORD=1``), then asserted.
The fixes for OPEN-A..K must keep these green.

Forward-compat rules (the planned fixes add fields):
- key sets are asserted as ``observed ⊆ actual`` (never the absence of new keys such
  as ``warm_deadline_source``, ``empty_reason`` on empty deltas, extra timings keys);
- the warm-deadline default (30000 today, the OPEN-B bug) is never asserted; only
  env-pinned values are.

Seeded generators (no Hypothesis): a module-level ``random.Random(SEED + n)`` builds
the cases, fed through ``pytest.mark.parametrize``; the case id carries the seed and
the index so a failing counterexample reproduces.

No real processes are touched (fake psutil table) and no live HTTP reaches :8765
(``CTX_ENGINE_URL`` points at a closed port; HTTP handler tests bind 127.0.0.1:0).

**Validates: Requirements 3.1, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 3.11, 3.12, 3.14, 3.15, 3.18, 3.19**
"""

from __future__ import annotations

import hashlib
import http.client
import itertools
import json
import os
import random
import sys
import threading
import time
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from conftest import enroll_test_repo

ROOT = Path(__file__).resolve().parents[1]
GOLDEN_FILE = Path(__file__).parent / "fixtures" / "open_preservation" / "goldens.json"
SEED = 20260926
_RECORD = (os.environ.get("CTX_OPEN_PRESERVATION_RECORD") or "").strip() == "1"
_GOLDEN_LOCK = threading.Lock()


# --------------------------------------------------------------------------- goldens


def _load_goldens() -> dict[str, Any]:
    if GOLDEN_FILE.is_file():
        return json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
    return {}


def _golden(key: str, observed: Any) -> Any:
    """Record mode stores *observed*; normal mode returns the stored golden."""
    observed = json.loads(json.dumps(observed, default=str))
    with _GOLDEN_LOCK:
        data = _load_goldens()
        if _RECORD:
            data[key] = observed
            GOLDEN_FILE.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN_FILE.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            return observed
    if key not in data:
        pytest.fail(f"golden {key!r} missing; record on unfixed code with CTX_OPEN_PRESERVATION_RECORD=1")
    return data[key]


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _assert_subset(expected_keys, actual: dict, ctx: str) -> None:
    missing = sorted(set(expected_keys) - set(actual))
    assert not missing, f"{ctx}: keys dropped vs unfixed golden: {missing}"


# --------------------------------------------------------------------------- common env


@pytest.fixture(autouse=True)
def _no_live_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    # Closed port: any stray EngineClient fails fast instead of hitting :8765.
    monkeypatch.setenv("CTX_ENGINE_URL", "http://127.0.0.1:9")
    for key in (
        "CTX_WARM_DEADLINE_MS",
        "CTX_HOT_PUBLISH",
        "CTX_HOT_VDB_CACHE",
        "CTX_HOT_DELETE_MASK",
        "CTX_SYNC_WAIT_FOR_EMBEDDER",
        "CTX_MCP_PACK_CLASS_BODY_MAX_LINES",
        "CTX_PACK_LOC_MAX_LINES",
        "CTX_PACK_LOC_HEAD_LINES",
        "CTX_MCP_PACK_BODIES",
        "CTX_MCP_FULL_LOCATE",
        "CTX_MCP_ECHO_GUIDANCE",
    ):
        monkeypatch.delenv(key, raising=False)


# =========================================================================== 3.6 status


_READY_TUPLES = list(itertools.product((False, True), repeat=4))  # healthy, soft, dense, ast


def _stage_rule(healthy: bool, soft: bool, dense: bool, ast: bool) -> str:
    """Stage order engine_down → soft_loading → dense_loading → pack_ast_loading → ready."""
    if not healthy:
        return "engine_down"
    if not soft:
        return "soft_loading"
    if not dense:
        return "dense_loading"
    if not ast:
        return "pack_ast_loading"
    return "ready"


def _status_tool(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tup: tuple[bool, bool, bool, bool]):
    pytest.importorskip("mcp")
    healthy, soft, dense, ast = tup
    repo = tmp_path / "st"
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("CTX_REPO", str(repo))
    monkeypatch.chdir(repo)

    class FakeEng:
        base = "http://127.0.0.1:9"
        project_id = "ce_fakestatus"

        def __init__(self, *a, **k) -> None:
            pass

        def healthy(self) -> bool:
            return healthy

        def health(self) -> dict:
            # Real client: healthy() == health()["ok"]. status_impl now derives
            # healthy from a single health() call, so ``ok`` must track ``healthy``
            # (an engine that is down does not report ok:true).
            return {
                "ok": healthy,
                "soft_search_ready": soft,
                "embedder_loaded": dense,
                "project_id": "ce_fakestatus",
                "warm_state": "ready" if soft else "warming",
                "chunks": 5,
            }

        def open_repo(self, *a, **k) -> dict:
            return {
                "ok": soft,
                "project_id": "ce_fakestatus" if soft else None,
                "warm_state": "ready" if soft else "warming",
            }

        def status(self, *a, **k) -> dict:
            return {"ok": True}

    from pipeline.runtime_controller import ReadySnapshot, RuntimeController

    monkeypatch.setattr("pipeline.client.EngineClient", FakeEng)
    monkeypatch.setattr("pipeline.mcp_lifecycle.ensure_mcp_runtime", lambda *a, **k: None)
    monkeypatch.setattr("pipeline.mcp_lifecycle.start_ast_hydrate_bg", lambda *a, **k: {})
    monkeypatch.setattr("pipeline.mcp_lifecycle.soft_ready_cached", lambda: False)
    monkeypatch.setattr("pipeline.mcp_lifecycle.mark_soft_ready", lambda *a, **k: None)
    monkeypatch.setattr("pipeline.context_trace.ast_cache_ready", lambda *a, **k: ast)
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)
    monkeypatch.setattr(
        RuntimeController,
        "snapshot",
        lambda self, repo=None, **_k: ReadySnapshot(
            state="READY" if soft else "WARMING",
            engine_ok=healthy,
            embedder_loaded=dense,
            ast_ready=ast,
            soft_search_ready=soft,
        ),
    )
    from pipeline.mcp_locate import create_mcp

    return create_mcp()._tool_manager._tools["status"].fn


_WARM_WAIT_FIELDS = (
    "done",
    "stage",
    "wait_for",
    "soft_ready",
    "dense_ready",
    "pack_ready",
    "elapsed_s",
    "retry_after_s",
    "note",
)


@pytest.mark.parametrize(
    "tup", _READY_TUPLES, ids=[f"h{int(a)}s{int(b)}d{int(c)}a{int(d)}" for a, b, c, d in _READY_TUPLES]
)
def test_status_warm_wait_stage_and_keys_preserved(monkeypatch, tmp_path, tup):
    fn = _status_tool(monkeypatch, tmp_path, tup)
    out = json.loads(fn())
    case = "h{}s{}d{}a{}".format(*[int(x) for x in tup])
    ww = out.get("warm_wait")
    assert isinstance(ww, dict), f"case={case}: warm_wait missing"
    _assert_subset(_WARM_WAIT_FIELDS, ww, f"case={case} warm_wait")
    observed = {
        "stage": ww["stage"],
        "done": ww["done"],
        "soft_ready": ww["soft_ready"],
        "dense_ready": ww["dense_ready"],
        "pack_ready": ww["pack_ready"],
        "retry_after_s": ww["retry_after_s"],
        "top_pack_ready": out.get("pack_ready"),
        "top_ast_hydrated": out.get("ast_hydrated"),
    }
    gold = _golden(f"status.warm_wait.{case}", observed)
    assert observed == gold, f"case={case}: warm_wait drifted from unfixed golden"
    assert ww["stage"] == _stage_rule(*tup), f"case={case}: stage order changed"
    assert ww["done"] is (ww["stage"] == "ready")
    assert isinstance(ww["note"], str) and ww["note"]
    keys = _golden(f"status.keys.{case}", sorted(out))
    _assert_subset(keys, out, f"case={case} status")
    for must in ("pack_ready", "ast_hydrated", "warm_wait"):
        assert must in out


def _gen_status_field_cases(n: int = 12):
    rng = random.Random(SEED + 6)
    cases = []
    for i in range(n):
        cases.append(
            pytest.param(
                {
                    "engine_healthy": rng.random() < 0.7,
                    "embedder_loaded": rng.choice([None, False, True]),
                    "need_ast": rng.random() < 0.5,
                    "soft_search_ready": rng.choice([None, False, True]),
                    "ast": rng.random() < 0.5,
                    "state": rng.choice(["DOWN", "WARMING", "READY"]),
                },
                id=f"seed{SEED + 6}-case{i}",
            )
        )
    return cases


@pytest.mark.parametrize("case", _gen_status_field_cases())
def test_status_field_key_sets_are_superset(monkeypatch, case):
    from pipeline import warm_contract as wc
    from pipeline.runtime_controller import ReadySnapshot

    # warm_status_fields freezes module timers; keep them per-test.
    monkeypatch.setattr(wc, "_READY_AT", None, raising=False)
    monkeypatch.setattr(wc, "_STARTED_AT", None, raising=False)
    monkeypatch.setattr(wc, "_AST_HYDRATED", bool(case["ast"]), raising=False)
    snap = ReadySnapshot(
        state=case["state"],
        engine_ok=bool(case["engine_healthy"]),
        embedder_loaded=bool(case["embedder_loaded"]),
        ast_ready=bool(case["ast"]),
        soft_search_ready=bool(case["soft_search_ready"]),
    )
    fields = snap.as_status_fields()
    gold = _golden("status.as_status_fields.keys", sorted(fields))
    _assert_subset(gold, fields, f"as_status_fields case={case}")
    wsf = wc.warm_status_fields(
        engine_healthy=case["engine_healthy"],
        embedder_loaded=case["embedder_loaded"],
        need_ast=case["need_ast"],
        soft_search_ready=case["soft_search_ready"],
    )
    gold2 = _golden("status.warm_status_fields.keys", sorted(wsf))
    _assert_subset(gold2, wsf, f"warm_status_fields case={case}")


def _gen_pinned_deadlines(n: int = 10):
    rng = random.Random(SEED + 2)
    vals = [90000, 1000, 120000] + [rng.randint(1000, 400000) for _ in range(n)]
    return [pytest.param(v, id=f"seed{SEED + 2}-ms{v}") for v in vals]


@pytest.mark.parametrize("pinned", _gen_pinned_deadlines())
def test_pinned_warm_deadline_is_reported_as_pinned(monkeypatch, pinned):
    """Non-bug input: env already pins the deadline → every surface reports it."""
    from pipeline import runtime_controller as rc
    from pipeline import warm_contract as wc
    from pipeline.runtime_controller import ReadySnapshot

    monkeypatch.setattr(wc, "_READY_AT", None, raising=False)
    monkeypatch.setattr(wc, "_STARTED_AT", None, raising=False)
    monkeypatch.setenv("CTX_WARM_DEADLINE_MS", str(pinned))
    want = max(1000, pinned)
    snap = ReadySnapshot(state="READY", engine_ok=True, embedder_loaded=True, ast_ready=True, soft_search_ready=True)
    got = {
        "warm_contract": wc.warm_deadline_ms(),
        "runtime_controller": rc.warm_deadline_ms(),
        "as_status_fields": snap.as_status_fields()["warm_deadline_ms"],
        "warm_status_fields": wc.warm_status_fields(engine_healthy=False, embedder_loaded=False)[
            "warm_deadline_ms"
        ],
    }
    assert all(v == want for v in got.values()), f"pinned={pinned}: {got}"


# =========================================================================== sync loop


@pytest.fixture
def sync_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(tmp_path, home=home, project_id="ce_openpreserve1234567890abcd")
    monkeypatch.setattr("pipeline.sync_loop.BackgroundSyncLoop._clients_active", lambda self: False)
    (tmp_path / "pkg").mkdir(exist_ok=True)
    for name in ("a.py", "b.py", "c.py", "d.py"):
        (tmp_path / "pkg" / name).write_text(f"def {name[0]}():\n    return 1\n", encoding="utf-8")
    return tmp_path


class _FakeVdb:
    """Only what ``_vdb_fingerprint`` needs."""

    def __init__(self, root: Path) -> None:
        self.collections_dir = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "c.bin").write_bytes(b"x" * 16)


class _FakeBinder:
    def __init__(self, n: int = 5) -> None:
        self.texts = [f"t{i}" for i in range(n)]
        self.applied: list[int] = []

    def apply_chunk_delta(self, records, matrix, *, base_chunk_count: int = -1) -> dict:
        if base_chunk_count != len(self.texts):
            raise RuntimeError("binder drift")
        before = len(self.texts)
        self.texts.extend(str(r.text) for r in records)
        self.applied.append(len(records))
        return {"chunks_before": before, "chunks_after": len(self.texts), "appended": len(records)}


_HOT_LINE_TOKENS = (
    "path=",
    "debounce_ms=",
    "slice_ms=",
    "parse_ms=",
    "graph_ms=",
    "embed_ms=",
    "write_ms=",
    "vectors_ms=",
    "(open=",
    "mutate=",
    "save=",
    "chunkfile_ms=",
    "reconcile_ms=",
    "publication_ms=",
    "cards_ms=",
    "sync_ms=",
    "sync_call_ms=",
    "invalidate_ms=",
    "publish_call_ms=",
    "publish_ms=",
    "total_ms=",
    "upserted=",
    "removed=",
    "publish=",
    "pid=",
)


def _run_idle_hot_save(monkeypatch, repo: Path, capsys) -> dict[str, Any]:
    from pipeline.ce_service import RuntimeManager
    from pipeline.incremental import HotDelta, IncrementalResult
    from pipeline.store import ChunkRecord
    from pipeline.sync_loop import BackgroundSyncLoop, _vdb_fingerprint

    engine = _FakeBinder(5)
    manager = RuntimeManager()
    runtime = SimpleNamespace(
        project_id="ce_openpreserve1234567890abcd",
        repo=repo,
        engine=engine,
        generation=1,
        last_sync_at=None,
        warm_state="ready",
        error=None,
    )
    loads: list[int] = []
    monkeypatch.setattr("pipeline.ce_service.load_engine", lambda *a, **k: loads.append(1) or engine)
    monkeypatch.setattr(manager, "_load_runtime_facade", lambda *_a, **_k: None)
    monkeypatch.setattr("pipeline.storage_policy.compact_collection", lambda *a, **k: None)
    fresh_vdbs: list[_FakeVdb] = []

    def _fresh_vdb(*_a, **_k):
        v = _FakeVdb(repo / f"vdb_fresh{len(fresh_vdbs)}")
        fresh_vdbs.append(v)
        return v

    monkeypatch.setattr("pipeline.vectordb.VectorDatabase", _fresh_vdb)

    cached = _FakeVdb(repo / "vdb_cached")
    loop = BackgroundSyncLoop(
        repo,
        debounce_ms=0,
        on_refresh=lambda payload, delta=None: manager._publish_runtime(runtime, payload, delta),
    )
    loop._hot_vdb_cache = (cached, _vdb_fingerprint(cached))
    seen_vdb: list[Any] = []
    flushed: list[int] = []

    def fake_incremental(root, *, force_files=None, bulk=False, hot_lane=False, vdb=None, **_kw):
        seen_vdb.append(vdb)
        rec = ChunkRecord(
            id=9001,
            file="pkg/a.py",
            start_line=1,
            end_line=2,
            symbol="a",
            text="def a(): return 1",
            enriched="def a(): return 1",
        )
        delta = HotDelta(
            records=[rec],
            matrix=np.full((1, 8), 0.5, dtype=np.float32),
            removed_ids=[],
            dim=8,
            full_embed_coverage=True,
            base_chunk_count=5,
        )
        return IncrementalResult(
            refreshed=True,
            files=list(force_files or []),
            chunks_upserted=1,
            chunks_removed=0,
            ms=12.0,
            strategy="incremental",
            stages={"parse_ms": 5.0, "embed_ms": 7.0, "write_ms": 3.0},
            hot_delta=delta,
            vector_flush=lambda: flushed.append(1) or True,
        )

    monkeypatch.setattr("pipeline.incremental.incremental_sync", fake_incremental)
    t0 = time.monotonic()
    capsys.readouterr()
    loop.mark_dirty(["pkg/a.py"], reason="probe_write", now=t0)
    loop.drain_due(now=t0 + 1.0)
    err = capsys.readouterr().err
    lines = [ln for ln in err.splitlines() if ln.startswith("[keeper] hot sync")]
    entry = loop.dirty_ledger.snapshot()["paths"]["pkg/a.py"]
    cache = loop._hot_vdb_cache
    return {
        "publish": (loop.last_result or {}).get("publish"),
        "loads": len(loads),
        "applied": list(engine.applied),
        "vdb_reused": bool(seen_vdb) and seen_vdb[0] is cached,
        "fresh_vdb_opened": len(fresh_vdbs),
        "cache_kept_after_flush": cache is not None and cache[0] is seen_vdb[0],
        "flushed": len(flushed),
        "state": entry["state"],
        "hot_lines": len(lines),
        "hot_line": lines[0] if lines else "",
        "n_sync": len(seen_vdb),
    }


def _assert_token_order(line: str, ctx: str) -> None:
    pos = -1
    for tok in _HOT_LINE_TOKENS:
        nxt = line.find(tok, pos + 1)
        assert nxt > pos, f"{ctx}: stage token {tok!r} missing/out of order in {line!r}"
        pos = nxt


def test_idle_hot_save_patches_and_reuses_hot_vdb(monkeypatch, sync_repo, capsys):
    """3.7: single existing-file probe_write on an idle ledger → publish=patch, vdb reused."""
    obs = _run_idle_hot_save(monkeypatch, sync_repo, capsys)
    line = obs.pop("hot_line")
    gold = _golden("sync.idle_hot_save", obs)
    assert obs == gold
    assert obs["publish"] == "patch" and obs["loads"] == 0 and obs["vdb_reused"] is True
    _assert_token_order(line, "idle hot save")
    assert "publish=patch" in line


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({"CTX_HOT_PUBLISH": "0"}, id="hot_publish_off"),
        pytest.param({"CTX_HOT_VDB_CACHE": "0"}, id="hot_vdb_cache_off"),
        pytest.param({"CTX_HOT_DELETE_MASK": "0"}, id="hot_delete_mask_off"),
        pytest.param({"CTX_HOT_PUBLISH": "0", "CTX_HOT_VDB_CACHE": "0"}, id="both_off"),
    ],
)
def test_kill_switches_fall_back_as_before(monkeypatch, sync_repo, capsys, env):
    """3.9: kill switches keep today's fallback (CTX_HOT_PUBLISH=0 → full publish)."""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    obs = _run_idle_hot_save(monkeypatch, sync_repo, capsys)
    line = obs.pop("hot_line")
    case = ",".join(f"{k}={v}" for k, v in sorted(env.items()))
    gold = _golden(f"sync.kill_switch.{case}", obs)
    assert obs == gold, f"env={case}"
    if env.get("CTX_HOT_PUBLISH") == "0":
        assert obs["publish"] == "full" and obs["loads"] == 1 and obs["applied"] == []
    _assert_token_order(line, f"env={case}")


_PATHS = ["pkg/a.py", "pkg/b.py", "pkg/c.py", "pkg/d.py"]
_HOT = ("probe_write", "write", "changed_file")
_REASONS = ("probe_write", "write", "changed_file", "disk_poll", "graph_catchup")


def _gen_ledger_cases(n: int = 30):
    rng = random.Random(SEED + 1)
    cases = []
    for i in range(n):
        ops: list[tuple] = []
        t = 0.0
        for _ in range(rng.randint(3, 14)):
            t = round(t + rng.choice([0.1, 0.3, 0.6, 1.0, 2.5, 6.0]), 2)
            kind = rng.choices(["mark", "drain", "ext"], weights=[5, 4, 1])[0]
            if kind == "mark":
                ops.append(("mark", t, sorted(rng.sample(_PATHS, rng.randint(1, 3))), rng.choice(_REASONS)))
            elif kind == "drain":
                ops.append(("drain", t))
            else:
                ops.append(("ext", t, sorted(rng.sample(_PATHS, rng.randint(1, 2)))))
        owe_graph = rng.random() < 0.6
        cases.append(pytest.param(ops, owe_graph, id=f"seed{SEED + 1}-case{i}"))
    return cases


@pytest.mark.parametrize("ops,owe_graph", _gen_ledger_cases())
def test_ledger_interleavings_publish_all_and_catchup_after_quiet(monkeypatch, sync_repo, ops, owe_graph):
    """3.8/3.10/3.11: no newcomer overlap, no deletion-only batch → all published;
    graph catch-up only outside the quiet window, and graph_pending is cleared."""
    from pipeline.dirty_ledger import normalize_dirty_path
    from pipeline.sync_loop import BackgroundSyncLoop

    loop = BackgroundSyncLoop(sync_repo, debounce_ms=0)
    loop.graph_catchup_delay_s = 3.0
    loop.graph_catchup_quiet_s = 5.0
    now_box = [0.0]
    calls: list[tuple[float, list[str], list[str], bool]] = []

    def fake_sync(paths, *, reason, hot=False):
        snap = loop.dirty_ledger.snapshot()["paths"]
        reasons = [str((snap.get(normalize_dirty_path(p)) or {}).get("reason")) for p in paths]
        calls.append((now_box[0], list(paths), reasons, bool(hot)))
        payload = {
            "refreshed": True,
            "files": list(paths),
            "chunks_upserted": 1,
            "chunks_removed": 0,
            "ms": 1.0,
            "strategy": "incremental",
        }
        if hot and owe_graph:
            payload["graph_pending"] = list(paths)
        return payload

    monkeypatch.setattr(loop, "_sync_paths", fake_sync)
    t0 = time.monotonic() + 5.0
    hot_marks: list[float] = []
    marked: set[str] = set()
    last_t = 0.0
    for op in ops:
        now = t0 + op[1]
        last_t = op[1]
        now_box[0] = now
        if op[0] == "mark":
            loop.mark_dirty(op[2], reason=op[3], now=now)
            marked.update(op[2])
            if op[3] in _HOT:
                hot_marks.append(now)
        elif op[0] == "drain":
            loop.drain_due(now=now)
        else:
            loop.dirty_ledger.begin(op[2])
            loop.dirty_ledger.complete(op[2], published=True)
    for step in range(1, 300):
        now = t0 + last_t + step * 0.5
        now_box[0] = now
        loop.drain_due(now=now)
        entries = loop.dirty_ledger.snapshot()["paths"].values()
        if all(e["state"] == "published" for e in entries):
            break
    snap = loop.dirty_ledger.snapshot()["paths"]
    ctx = f"seed={SEED + 1} ops={ops} owe_graph={owe_graph}"
    for p in marked:
        e = snap.get(normalize_dirty_path(p))
        assert e is not None and e["state"] == "published", f"{ctx}: {p} not published: {e}"
    assert not [
        k for k, e in snap.items() if e["reason"] == "graph_catchup" and e["state"] != "published"
    ], f"{ctx}: graph_pending not cleared"
    for at, paths, reasons, _hot in calls:
        if "graph_catchup" not in reasons:
            continue
        prior = [h for h in hot_marks if h <= at]
        if prior:
            assert at >= max(prior) + loop.graph_catchup_quiet_s - 1e-6, (
                f"{ctx}: graph catch-up {paths} ran at +{at - t0:.2f}s inside the quiet window"
            )
    if owe_graph and any(h for (_a, _p, _r, h) in calls if h):
        assert any("graph_catchup" in r for (_a, _p, r, _h) in calls), f"{ctx}: owed catch-up never ran"


def test_newcomer_enqueue_marks_new_files_and_skips_junk(monkeypatch, sync_repo):
    """3.10: newcomers on an empty ledger are queued as disk_poll; junk/ignored skipped."""
    from pipeline.sync_loop import BackgroundSyncLoop

    (sync_repo / "pkg" / "fresh.py").write_text("x = 1\n", encoding="utf-8")
    (sync_repo / "node_modules").mkdir()
    (sync_repo / "node_modules" / "junk.js").write_text("x\n", encoding="utf-8")
    (sync_repo / "ignored_dir").mkdir()
    (sync_repo / "ignored_dir" / "y.py").write_text("y = 1\n", encoding="utf-8")
    (sync_repo / ".scubieeignore").write_text("ignored_dir/\n", encoding="utf-8")
    added = ["pkg/fresh.py", "node_modules/junk.js", "ignored_dir/y.py"]
    monkeypatch.setattr(
        "pipeline.root_probe.root_probe",
        lambda *a, **k: SimpleNamespace(added=list(added), modified=[], removed=[], clean=False),
    )
    loop = BackgroundSyncLoop(sync_repo, debounce_ms=0)
    loop._enqueue_newcomers(now=time.monotonic())
    snap = loop.dirty_ledger.snapshot()["paths"]
    obs = {k: [v["reason"], v["state"]] for k, v in sorted(snap.items())}
    gold = _golden("sync.newcomer_enqueue", obs)
    assert obs == gold
    assert obs.get("pkg/fresh.py") == ["disk_poll", "queued"]


# =========================================================================== 3.12 expand


def _write_fixture_repo(repo: Path, *, n_methods: int = 140) -> None:
    (repo / "pkg").mkdir(parents=True, exist_ok=True)
    (repo / ".git").mkdir(exist_ok=True)
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "store.py").write_text(
        "import json\n\n\n"
        "def save_record(path, rec):\n"
        "    with open(path, 'w') as fh:\n"
        "        fh.write(json.dumps(rec))\n"
        "    print('saved', path)\n\n\n"
        "def load_record(path):\n"
        "    with open(path) as fh:\n"
        "        return json.loads(fh.read())\n",
        encoding="utf-8",
    )
    methods = "\n".join(
        f"    def m{i}(self, key):\n        return self.get(key + '{i}')\n" for i in range(n_methods)
    )
    (repo / "pkg" / "service.py").write_text(
        "from pkg.store import save_record, load_record\n\n\n"
        "class RecordService:\n"
        "    def __init__(self, root):\n"
        "        self.root = root\n\n"
        "    def put(self, key, rec):\n"
        "        save_record(self.root + '/' + key, rec)\n\n"
        "    def get(self, key):\n"
        "        return load_record(self.root + '/' + key)\n\n"
        + methods
        + "\n\ndef handle_put(svc, key, rec):\n"
        "    svc.put(key, rec)\n"
        "    return True\n",
        encoding="utf-8",
    )
    (repo / "pkg" / "cli.py").write_text(
        "from pkg.service import RecordService, handle_put\n\n\n"
        "def main(argv):\n"
        "    svc = RecordService(argv[0])\n"
        "    handle_put(svc, argv[1], {'v': argv[2]})\n"
        "    print('done')\n",
        encoding="utf-8",
    )


@pytest.fixture
def trace_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CTX_TRACE_PARALLEL", "1")
    monkeypatch.setenv("CTX_TRACE_ENGINE", "composite_v1")
    repo = tmp_path / "fx"
    _write_fixture_repo(repo)
    from pipeline.context_trace import ast_cache_ready, hydrate_ast_bundle

    hydrate_ast_bundle(repo, bake_on_miss=True)
    assert ast_cache_ready(repo), "fixture AST must be hydrated (3.12 is the hydrated case)"
    return repo


_EXPAND_NODES = (
    "pkg/store.py::save_record",
    "pkg/store.py::load_record",
    "pkg/service.py::RecordService.put",
    "pkg/service.py::RecordService.get",
    "pkg/service.py::handle_put",
    "pkg/cli.py::main",
)
_EXPAND_DIRS = ("callers", "callees", "effects", "all")
_EXPAND_CASES = [(n, d) for n in _EXPAND_NODES for d in _EXPAND_DIRS]


@pytest.mark.parametrize("node,direction", _EXPAND_CASES, ids=[f"{n.split('::')[-1]}-{d}" for n, d in _EXPAND_CASES])
def test_hydrated_expand_deltas_match_golden(trace_repo, node, direction):
    from pipeline.context_trace import run_expand_context

    out = run_expand_context(trace_repo, node, query="save_record put handle_put", direction=direction, k=10)
    assert out.get("ok") is True, f"{node} {direction}: {out.get('error')}"
    delta = [[c.get("id"), c.get("why")] for c in (out.get("delta") or [])]
    gold = _golden(f"expand.{node}.{direction}", delta)
    assert delta == gold, f"{node} {direction}: delta drifted"
    if delta:
        assert "empty_reason" not in out, f"{node} {direction}: non-empty delta must not carry empty_reason"
        assert int(out.get("count") or 0) == len(delta)


def test_hydrated_expand_bodies_and_collect_match_golden(trace_repo):
    from pipeline.context_trace import run_collect_hot, run_expand_context

    out = run_expand_context(
        trace_repo,
        "pkg/store.py::save_record",
        query="save_record put",
        direction="callers",
        k=10,
        with_bodies=True,
    )
    assert out.get("ok") is True
    rows = out.get("pack") or out.get("bodies") or []
    bodies = [[b.get("id"), _sha(b.get("text") or b.get("code") or "")] for b in rows if isinstance(b, dict)]
    gold = _golden("expand.bodies.save_record.callers", bodies)
    assert bodies == gold
    ids = {"pkg/store.py::save_record", "pkg/service.py::handle_put"}
    col = run_collect_hot(trace_repo, [], only_ids=ids)
    got = sorted([b["id"], b["loc"], _sha(b["text"])] for b in col.get("bodies") or [])
    gold2 = _golden("collect.bodies.only_ids", got)
    assert col.get("ok") is True and got == gold2


# =========================================================================== 3.5 body clamp


def test_include_bodies_class_item_loc_clamped_text_identical(trace_repo):
    from pipeline.context_trace import run_pack_context
    from pipeline.mcp_response_lean import slim_locate_payload

    raw = run_pack_context(
        trace_repo,
        "RecordService put get save_record",
        seed_file="pkg/service.py",
        seed_symbol="RecordService",
        mode="lean",
        include_bodies=True,
        k=6,
    )
    assert raw.get("ok") is True
    raw_rows = {p.get("id"): p for p in (raw.get("pack") or []) if isinstance(p, dict)}
    cls_id = "pkg/service.py::RecordService"
    assert cls_id in raw_rows, f"class body missing from include_bodies pack: {sorted(raw_rows)}"
    raw_text = raw_rows[cls_id].get("text") or raw_rows[cls_id].get("body") or ""
    slim = slim_locate_payload(dict(raw))
    rows = {p.get("id"): p for p in (slim.get("pack") or []) if isinstance(p, dict)}
    item = rows[cls_id]
    obs = {
        "loc": item.get("loc"),
        "full_loc": item.get("full_loc"),
        "text_sha": _sha(item.get("text") or ""),
        "text_lines": len((item.get("text") or "").splitlines()),
    }
    gold = _golden("pack.include_bodies.class_item", obs)
    assert obs == gold
    assert item.get("full_loc"), "class item must keep full_loc"
    assert item.get("text") == raw_text, "body text must be byte-identical (cap unset)"
    start, end = (int(x) for x in item["loc"].rpartition(":")[2].split("-"))
    fstart, fend = (int(x) for x in item["full_loc"].rpartition(":")[2].split("-"))
    assert start == fstart and end < fend


# =========================================================================== 3.1 / 3.14 MCP


@pytest.fixture
def mcp_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pytest.importorskip("mcp")
    repo = tmp_path / "er"
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("CTX_REPO", str(repo))
    monkeypatch.chdir(repo)
    monkeypatch.setenv("CTX_MCP_PACK_AST_WAIT_S", "0")
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)
    monkeypatch.setattr("pipeline.daemon.ensure_daemon", lambda *a, **k: {"ok": True, "skipped": True})
    monkeypatch.setattr("pipeline.mcp_lifecycle.start_ast_hydrate_bg", lambda *a, **k: {"thread": None})
    return repo


def test_pack_ast_warming_payload_preserved(monkeypatch, mcp_repo):
    """3.1: pack keeps its ast_warming contract (should_retry, retry_after_s, ast_wait_ms)."""
    monkeypatch.setattr("pipeline.context_trace.ast_cache_ready", lambda *a, **k: False)
    monkeypatch.setattr(
        "pipeline.context_trace.hydrate_ast_bundle", lambda *a, **k: {"ok": False, "source": "miss", "ms": 0.0}
    )
    from pipeline.mcp_locate import create_mcp
    from pipeline.mcp_ship_check import parse_tool_json, tool_fn

    out = parse_tool_json(
        tool_fn(create_mcp(name="pres-warm"), "pack_context")(query="q", seed_file="pkg/a.py", seed_symbol="f")
    )
    keys = _golden("mcp.pack.ast_warming.keys", sorted(out))
    _assert_subset(keys, out, "pack ast_warming")
    vals = {k: out.get(k) for k in ("ok", "tool", "error", "status", "should_retry", "retry_after_s")}
    gold = _golden("mcp.pack.ast_warming.values", vals)
    assert vals == gold
    assert isinstance(out.get("ast_wait_ms"), (int, float))
    assert str(out.get("hint") or "").startswith("AST bundle is still loading")


def test_mcp_error_paths_ok_false_preserved(monkeypatch, mcp_repo):
    """3.14: empty seed, unknown direction, unknown handle → same ok=false payloads."""
    from pipeline.mcp_locate import create_mcp
    from pipeline.mcp_ship_check import parse_tool_json, tool_fn

    mcp = create_mcp(name="pres-err")
    cases = {
        "pack_empty_seed": parse_tool_json(tool_fn(mcp, "pack_context")(query="q", seed_file="", seed_symbol="")),
        "expand_bad_direction": parse_tool_json(
            tool_fn(mcp, "expand_context")(node="a.py::b", direction="sideways")
        ),
        "pack_k0": parse_tool_json(
            tool_fn(mcp, "pack_context")(query="q", seed_file="pkg/a.py", seed_symbol="f", k=0)
        ),
    }
    monkeypatch.setenv("CTX_MCP_SURFACE", "nav")
    nav = create_mcp(name="pres-err-nav")
    cases["nav_expand_unknown_handle"] = parse_tool_json(tool_fn(nav, "expand")(handle="h_does_not_exist"))
    for name, out in cases.items():
        vals = {k: out.get(k) for k in ("ok", "tool", "error")}
        gold = _golden(f"mcp.error.{name}.values", vals)
        assert vals == gold, name
        keys = _golden(f"mcp.error.{name}.keys", sorted(out))
        _assert_subset(keys, out, name)
        assert out["ok"] is False


def test_trace_error_paths_ok_false_preserved(trace_repo):
    from pipeline.context_trace import run_expand_context, run_pack_context

    cases = {
        "pack_empty_seed": run_pack_context(trace_repo, "q", seed_file="", seed_symbol="", mode="lean", k=5),
        "pack_underscore_seed": run_pack_context(trace_repo, "q", seed_file="_", seed_symbol="_", mode="lean", k=5),
        "pack_unknown_seed": run_pack_context(
            trace_repo, "q", seed_file="pkg/nope.py", seed_symbol="zzz", mode="lean", k=5
        ),
        "expand_unknown_node": run_expand_context(trace_repo, "pkg/nope.py::zzz", query="q", direction="callers", k=5),
    }
    for name, out in cases.items():
        vals = {k: out.get(k) for k in ("ok", "error")}
        gold = _golden(f"trace.error.{name}.values", vals)
        assert vals == gold, name
        keys = _golden(f"trace.error.{name}.keys", sorted(out))
        _assert_subset(keys, out, name)


# =========================================================================== 3.18 processes


class _FakeProc:
    def __init__(self, ps: "_FakePsutil", pid: int) -> None:
        self._ps = ps
        self.pid = pid
        row = ps.table[pid]
        self.info = {
            "pid": pid,
            "name": row["name"],
            "exe": row["exe"],
            "cmdline": list(row["cmdline"]),
            "ppid": row["ppid"],
            "create_time": row["create_time"],
            "memory_info": SimpleNamespace(rss=50 * 1024 * 1024),
        }

    def _row(self) -> dict:
        row = self._ps.table.get(self.pid)
        if row is None:
            raise self._ps.NoSuchProcess(self.pid)
        return row

    def name(self) -> str:
        return self._row()["name"]

    def exe(self) -> str:
        return self._row()["exe"]

    def cmdline(self) -> list[str]:
        return list(self._row()["cmdline"])

    def ppid(self) -> int:
        return int(self._row()["ppid"])

    def create_time(self) -> float:
        return float(self._row()["create_time"])

    def is_running(self) -> bool:
        return self.pid in self._ps.table

    def status(self) -> str:
        self._row()
        return "running"

    def memory_info(self):
        self._row()
        return SimpleNamespace(rss=50 * 1024 * 1024)

    def parents(self) -> list["_FakeProc"]:
        out, cur = [], self._row()["ppid"]
        while cur in self._ps.table and len(out) < 64:
            out.append(_FakeProc(self._ps, cur))
            cur = self._ps.table[cur]["ppid"]
        return out

    def children(self, recursive: bool = False) -> list["_FakeProc"]:
        direct = [p for p, r in self._ps.table.items() if r["ppid"] == self.pid]
        out = [_FakeProc(self._ps, p) for p in direct]
        if recursive:
            for p in direct:
                out.extend(_FakeProc(self._ps, p).children(recursive=True))
        return out

    def net_connections(self, kind: str = "inet") -> list:
        return [c for c in self._ps.net_connections(kind) if c.pid == self.pid]

    connections = net_connections

    def kill(self) -> None:
        self._row()
        self._ps.kills.append(self.pid)
        self._ps.table.pop(self.pid, None)

    terminate = kill

    def wait(self, timeout: float | None = None) -> None:
        return None


class _FakePsutil(types.ModuleType):
    class Error(Exception):
        pass

    class NoSuchProcess(Error):
        pass

    class AccessDenied(Error):
        pass

    class ZombieProcess(NoSuchProcess):
        pass

    class TimeoutExpired(Error):
        pass

    STATUS_ZOMBIE = "zombie"
    STATUS_RUNNING = "running"
    CONN_LISTEN = "LISTEN"

    def __init__(self, table: dict[int, dict], listener: int | None) -> None:
        super().__init__("psutil")
        self.table = table
        self.kills: list[int] = []
        self.listener = listener

    def process_iter(self, attrs=None, ad_value=None):
        for pid in list(self.table):
            if pid in self.table:
                yield _FakeProc(self, pid)

    def Process(self, pid: int | None = None) -> _FakeProc:  # noqa: N802
        pid = os.getpid() if pid is None else int(pid)
        if pid not in self.table:
            raise self.NoSuchProcess(pid)
        return _FakeProc(self, pid)

    def pid_exists(self, pid: int) -> bool:
        return int(pid) in self.table

    def pids(self) -> list[int]:
        return list(self.table)

    def wait_procs(self, procs, timeout=None, callback=None):
        return list(procs), []

    def net_connections(self, kind: str = "inet") -> list:
        if self.listener is None or self.listener not in self.table:
            return []
        return [
            SimpleNamespace(
                laddr=SimpleNamespace(ip="127.0.0.1", port=8765),
                raddr=(),
                status="LISTEN",
                pid=self.listener,
            )
        ]

    def virtual_memory(self):
        return SimpleNamespace(total=16 * 1024**3, available=8 * 1024**3, percent=50.0)


_UV_PY = "C:/Users/u/AppData/Roaming/uv/tools/scubiee/Scripts/pythonw.exe"


def _gen_process_tables(n: int = 16):
    rng = random.Random(SEED + 3)
    cases = []
    for i in range(n):
        pids = rng.sample(range(900_000, 999_999), 40)
        table: dict[int, dict] = {}
        chain: set[int] = set()
        orphans: set[int] = set()
        base = 1_700_000_000.0

        def add(pid, name, exe, cmd, ppid, ct):
            table[pid] = {"name": name, "exe": exe, "cmdline": cmd, "ppid": ppid, "create_time": ct}

        for k in range(rng.randint(1, 3)):
            ide, bridge, locate = pids.pop(), pids.pop(), pids.pop()
            ide_name = rng.choice(["Cursor.exe", "Kiro.exe", "Code.exe"])
            t = base + rng.randint(0, 5000)
            add(ide, ide_name, f"C:/Apps/{ide_name}", [f"C:/Apps/{ide_name}"], pids.pop(), t)
            if rng.random() < 0.5:
                add(bridge, "pythonw.exe", _UV_PY, [_UV_PY, "-u", "-m", "pipeline.mcp_bridge"], ide, t + 5)
            else:
                exe = "C:/Users/u/.local/bin/scubiee-mcp-bridge.exe"
                add(bridge, "scubiee-mcp-bridge.exe", exe, [exe], ide, t + 5)
            add(locate, "pythonw.exe", _UV_PY, [_UV_PY, "-u", "-m", "pipeline.mcp_locate"], bridge, t + 9)
            chain.update({ide, bridge, locate})
        engine, watchdog = pids.pop(), pids.pop()
        add(
            engine,
            "pythonw.exe",
            _UV_PY,
            [_UV_PY, "-m", "pipeline", "engine", "run", "--port", "8765"],
            pids.pop(),  # detached: parent long gone
            base - 100,
        )
        add(watchdog, "pythonw.exe", _UV_PY, [_UV_PY, "-m", "pipeline", "watchdog"], pids.pop(), base - 200)
        chain.update({engine, watchdog})
        for _ in range(rng.randint(0, 3)):
            noise = pids.pop()
            if rng.random() < 0.5:
                add(noise, "python.exe", "C:/Py/python.exe", ["C:/Py/python.exe", "-m", "http.server"], pids.pop(), base)
            else:
                add(noise, "notepad.exe", "C:/Windows/notepad.exe", ["notepad.exe"], pids.pop(), base)
        for _ in range(rng.randint(0, 2)):
            orphan = pids.pop()
            add(orphan, "pythonw.exe", _UV_PY, [_UV_PY, "-u", "-m", "pipeline.mcp_locate"], pids.pop(), base + 10)
            orphans.add(orphan)
        cases.append(pytest.param(table, chain, orphans, engine, id=f"seed{SEED + 3}-case{i}"))
    return cases


def _install_fake_psutil(monkeypatch, table: dict, listener: int) -> _FakePsutil:
    fake = _FakePsutil({pid: dict(row) for pid, row in table.items()}, listener)
    monkeypatch.setitem(sys.modules, "psutil", fake)
    monkeypatch.setattr("pipeline.daemon._pid_alive", lambda pid: int(pid) in fake.table)
    real_kills: list[Any] = []
    monkeypatch.setattr("pipeline.process_job.taskkill_silent", lambda *a, **k: real_kills.append(a))
    monkeypatch.setattr(os, "kill", lambda *a, **k: real_kills.append(a))
    fake.real_kills = real_kills  # type: ignore[attr-defined]
    return fake


@pytest.mark.parametrize("table,chain,orphans,engine", _gen_process_tables())
@pytest.mark.parametrize("sweeper", ["reap_orphaned_mcp_processes", "sweep_orphan_scubiee_frontends"])
def test_cleanup_never_kills_live_chain_or_watchdog(monkeypatch, table, chain, orphans, engine, sweeper):
    from pipeline import process_control as pc

    fake = _install_fake_psutil(monkeypatch, table, engine)
    getattr(pc, sweeper)()
    killed = set(fake.kills)
    ctx = f"seed={SEED + 3} sweeper={sweeper} chain={sorted(chain)} killed={sorted(killed)}"
    assert not (killed & chain), f"{ctx}: live IDE chain / engine / watchdog killed"
    assert orphans <= killed, f"{ctx}: parent-gone orphan workers no longer reaped"
    assert fake.real_kills == [], f"{ctx}: real kill primitive reached"  # type: ignore[attr-defined]


# =========================================================================== 3.15 HTTP


class _FakeCE:
    def __init__(self, admission_status: str = "activated") -> None:
        self.calls: list[tuple] = []
        self.sync_loop = None
        self._admission = admission_status

    def health(self) -> dict:
        return {
            "ok": True,
            "status": "ok",
            "project_id": "ce_fakehttp",
            "warm_state": "ready",
            "soft_search_ready": True,
            "embedder_loaded": True,
            "chunks": 3,
        }

    def admit_request(self, root, **kw) -> dict:
        self.calls.append(("admit", str(root)))
        return {
            "ok": self._admission == "activated",
            "status": self._admission,
            "client": kw.get("client"),
            "session_id": kw.get("session_id"),
        }

    def mark_dirty(self, paths, *, reason) -> dict:
        self.calls.append(("dirty", list(paths), reason))
        return {"ok": True, "paths": list(paths), "reason": reason, "queued": len(paths)}

    def note_locate(self) -> dict:
        self.calls.append(("locate",))
        return {"ok": True}

    def search(self, query, *, top_k=8, root=None) -> dict:
        self.calls.append(("search", query, top_k))
        return {"ok": True, "query": query, "top_k": top_k, "results": [{"file": "a.py", "score": 1.0}]}


def _serve(monkeypatch, ce):
    from http.server import ThreadingHTTPServer

    from pipeline.server import Handler

    monkeypatch.setattr("pipeline.server.get_context_engine", lambda: ce)
    monkeypatch.setattr("pipeline.server._note_user_activity", lambda *a, **k: None, raising=False)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    return httpd, th


def _req(port: int, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    conn.request(method, path, body=data, headers=headers)
    resp = conn.getresponse()
    raw = resp.read()
    conn.close()
    return resp.status, json.loads(raw.decode("utf-8") or "{}")


@pytest.mark.parametrize("admission", ["activated", "paused"])
def test_http_health_dirty_search_contracts_preserved(monkeypatch, tmp_path, admission):
    ce = _FakeCE(admission)
    httpd, th = _serve(monkeypatch, ce)
    port = httpd.server_address[1]
    root = str(tmp_path)
    try:
        results = {
            "get_health": _req(port, "GET", "/health"),
            "post_dirty": _req(port, "POST", "/v1/dirty", {"path": root, "paths": ["pkg/a.py"], "reason": "probe_write"}),
            "post_dirty_no_paths": _req(port, "POST", "/v1/dirty", {"path": root, "paths": []}),
            "post_dirty_no_root": _req(port, "POST", "/v1/dirty", {"paths": ["pkg/a.py"]}),
            "post_search": _req(port, "POST", "/v1/search", {"path": root, "query": "save record", "top_k": 3}),
            "post_search_no_query": _req(port, "POST", "/v1/search", {"path": root, "query": ""}),
            "post_pack": _req(port, "POST", "/v1/pack", {"path": root, "query": "q"}),
        }
    finally:
        httpd.shutdown()
        th.join(timeout=5)
    for name, (code, body) in results.items():
        gold = _golden(f"http.{admission}.{name}", {"code": code, "body": body})
        assert code == gold["code"], f"{admission} {name}: status {code} != {gold['code']}"
        _assert_subset(gold["body"], body, f"{admission} {name}")
        for key, value in gold["body"].items():
            assert body.get(key) == value, f"{admission} {name}: {key} {body.get(key)!r} != {value!r}"
    assert results["post_pack"][0] == 404, "pack stays MCP-only (no HTTP /v1/pack)"

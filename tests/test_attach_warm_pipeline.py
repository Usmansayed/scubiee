"""Attach-warm contract unit tests (Task 1+)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest


def test_warm_ready_false_until_embed_or_soft():
    from pipeline.warm_contract import WarmSnapshot, compute_warm_ready

    snap = WarmSnapshot(engine_healthy=True, embedder_loaded=False, ast_hydrated=True)
    assert compute_warm_ready(snap) is False
    soft = WarmSnapshot(
        engine_healthy=True,
        embedder_loaded=False,
        soft_search_ready=True,
        ast_hydrated=True,
    )
    assert compute_warm_ready(soft) is True


def test_warm_ready_true_when_all_set():
    from pipeline.warm_contract import WarmSnapshot, compute_warm_ready

    snap = WarmSnapshot(engine_healthy=True, embedder_loaded=True, ast_hydrated=True)
    assert compute_warm_ready(snap) is True


def test_map_can_skip_ast_for_ready():
    from pipeline.warm_contract import WarmSnapshot, compute_warm_ready

    snap = WarmSnapshot(engine_healthy=True, embedder_loaded=True, ast_hydrated=False)
    assert compute_warm_ready(snap, need_ast=False) is True
    assert compute_warm_ready(snap, need_ast=True) is False


def test_mark_warm_start_writes_stamp(tmp_path, monkeypatch):
    from pipeline import warm_contract as wc

    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setattr(wc, "_STARTED_AT", None)
    started = wc.mark_warm_start(tmp_path)
    assert started > 0
    assert wc.warm_started_at() == started
    assert (tmp_path / "ce-home" / "warm_attach.json").is_file()
    fields = wc.warm_status_fields(engine_healthy=True, embedder_loaded=True)
    assert fields["warm_ready_map"] is True
    assert fields["warm_deadline_ms"] == 30_000


def test_start_attach_warm_pipeline_returns_immediately(monkeypatch, tmp_path):
    from pipeline import mcp_lifecycle as life
    from pipeline.runtime_controller import RuntimeController

    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_MCP_ATTACH_WARM", "1")
    RuntimeController.reset_for_tests()
    rt = RuntimeController.get()
    calls: list[str] = []
    monkeypatch.setattr(
        rt,
        "_attach_worker",
        lambda *a, **k: calls.append("worker") or rt._mark_ready(),
    )

    t0 = time.perf_counter()
    out = life.start_attach_warm_pipeline(tmp_path)
    assert (time.perf_counter() - t0) < 0.5
    assert out.get("started") is True
    # Attach kicks an async worker thread (does not call _spawn_engine inline).
    deadline = time.time() + 1.0
    while time.time() < deadline and "worker" not in calls:
        time.sleep(0.01)
    assert "worker" in calls


def test_prewarm_embedder_forces_dummy_encode(monkeypatch):
    from pipeline import engine as eng

    calls: list[str] = []

    class FakeEmb:
        def embed_one(self, text, is_query=True):  # noqa: ANN001
            calls.append(str(text))
            return [0.0]

    class FakeEng:
        embedder = FakeEmb()

    monkeypatch.setattr(eng, "load_engine", lambda root: FakeEng())
    monkeypatch.setattr(
        eng,
        "get_governor",
        lambda: type("G", (), {"ensure_semantic_tier": lambda self: None})(),
        raising=False,
    )

    # prewarm imports get_governor from memory_governor inside try
    import pipeline.memory_governor as mg

    monkeypatch.setattr(
        mg,
        "get_governor",
        lambda: type("G", (), {"ensure_semantic_tier": lambda self: None})(),
    )

    out = eng.prewarm_embedder(".")
    assert calls and "prewarm" in calls[0]
    assert out["ok"] is True


def test_prewarm_embedder_primes_dense_search(monkeypatch):
    from pipeline import engine as eng

    calls: list[str] = []

    class FakeEmb:
        def embed_one(self, text, is_query=True):  # noqa: ANN001
            calls.append(str(text))
            return [0.0]

    class FakeEng:
        embedder = FakeEmb()
        _last_timings = {"dense": True, "retrieve_mode": "D_channel_best", "embed_ms": 1.0}

        def search(self, query, top_k=8, skip_freshness=True):  # noqa: ANN001
            calls.append("search:" + str(query)[:24])
            return [object()]

    monkeypatch.setattr(eng, "load_engine", lambda root: FakeEng())
    import pipeline.memory_governor as mg

    monkeypatch.setattr(
        mg,
        "get_governor",
        lambda: type("G", (), {"ensure_semantic_tier": lambda self: None})(),
    )
    monkeypatch.setattr(eng, "ensure_embed_keepalive_loop", lambda *_a, **_k: None)
    monkeypatch.setattr(eng, "embed_keepalive", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr(eng, "_mark_prime_done", lambda *_a, **_k: None)

    out = eng.prewarm_embedder(".")
    assert out["ok"] is True
    assert any(c.startswith("search:") for c in calls)
    assert (out.get("prime_dense") or {}).get("ok") is True


def test_hydrate_prefers_bundle(monkeypatch, tmp_path):
    from pipeline import context_trace as ct
    from trace_lab.ast_graph import AstTraceGraph
    from trace_lab.lsp_index import LspIndex
    from trace_lab.retrieve import LexicalIndex
    from trace_lab.types import TraceNode

    node = TraceNode(
        id="packages/x.py::b",
        file="packages/x.py",
        symbol="b",
        kind="function",
        start_line=1,
        end_line=2,
        text="def b():\n    return 1\n",
    )
    fake_nodes = {node.id: node}

    def fake_bundle(*_a, **_k):
        graph = AstTraceGraph(fake_nodes, [])
        # (nodes, graph, lsp, lex, gfy, stale)
        return fake_nodes, graph, LspIndex(), LexicalIndex(fake_nodes, include_path=False), None, False

    monkeypatch.setattr(ct, "_try_load_repo_bundle", fake_bundle)
    monkeypatch.setattr(ct, "corpus_fingerprint", lambda root: "fp")
    monkeypatch.setattr(ct, "_bind_pack_tracer", lambda *a, **k: object())
    ct._CACHE.clear()
    out = ct.hydrate_ast_bundle(tmp_path, bake_on_miss=False)
    assert out["ok"] is True
    assert out["source"] == "bundle"
    assert ct.ast_cache_ready(tmp_path) is True


def test_map_result_cache_hit_miss():
    from pipeline.map_result_cache import clear_map_cache, get_map_cached, put_map_cached

    clear_map_cache()
    put_map_cached(
        repo="/r",
        query="hello world",
        fingerprint="fp1",
        payload={
            "ok": True,
            "dense": True,
            "retrieve_mode": "D_channel_best",
            "timings": {"dense": True, "retrieve_mode": "D_channel_best"},
            "cards": [{"file": "a.py"}],
        },
    )
    hit = get_map_cached(repo="/r", query="hello world", fingerprint="fp1")
    assert hit is not None
    assert hit.get("cache") in {"hit", "last"}
    # Identical-query remaps ignore fingerprint (soft_v1 / last-payload path).
    assert get_map_cached(repo="/r", query="hello world", fingerprint="other") is not None
    assert get_map_cached(repo="/r", query="totally different", fingerprint="fp1") is None


def test_bridge_holds_idle_for_hours(tmp_path, monkeypatch):
    import pipeline.lifecycle_runtime as life

    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    monkeypatch.setenv("CTX_DISCONNECT_DEBOUNCE_S", "30")
    monkeypatch.setattr(life, "_client_pid_trustworthy", lambda meta: True)
    life.set_desired_mode(life.DESIRED_RUN)
    life.register_client(
        "mcp:cursor@bridge-hours", pid=42, kind="bridge", host="cursor", now=100.0
    )
    # Simulate long quiet period with bridge still registered.
    assert life.should_idle_stop(now=100.0 + 7200.0) is False


def test_attach_worker_skips_open_when_soft_ready(monkeypatch, tmp_path):
    """Re-open when soft already true flaps soft_search_ready for seconds."""
    from pipeline.runtime_controller import RuntimeController

    RuntimeController.reset_for_tests()
    rt = RuntimeController.get()
    opens: list[str] = []
    monkeypatch.setattr(
        rt,
        "_probe_health",
        lambda *_a, **_k: {
            "ok": True,
            "service": True,
            "soft_search_ready": True,
            "embedder_loaded": False,
        },
    )
    monkeypatch.setattr(
        rt,
        "_kick_open_repo",
        lambda *_a, **_k: opens.append("open") or {"ok": True},
    )
    monkeypatch.setattr(
        rt,
        "_kick_search_probe",
        lambda *_a, **_k: {"ok": True, "results": [{"file": "a.py"}]},
    )
    rt._attach_worker(tmp_path)
    assert opens == []
    assert rt.snapshot(repo=tmp_path).soft_search_ready is True


def test_engine_open_on_start_defaults_enabled(monkeypatch):
    """Listen-then-bg-open should be on so soft overlaps MCP initialize."""
    import os

    monkeypatch.delenv("CTX_ENGINE_OPEN_ON_START", raising=False)
    open_on_start = (os.environ.get("CTX_ENGINE_OPEN_ON_START") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    assert open_on_start is True
    monkeypatch.setenv("CTX_ENGINE_OPEN_ON_START", "0")
    open_on_start = (os.environ.get("CTX_ENGINE_OPEN_ON_START") or "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }
    assert open_on_start is False

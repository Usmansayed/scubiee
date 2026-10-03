"""Argument contracts that live probes caught before production."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_pack_k_one_is_only_the_seed() -> None:
    from pipeline.context_trace import run_pack_context

    out = run_pack_context(
        ROOT,
        "write_kiro_mcp merge_mcp_json mcp_install.py install Kiro MCP json",
        seed_file="packages/pipeline/mcp_install.py",
        seed_symbol="write_kiro_mcp",
        k=1,
        include_bodies=False,
    )
    assert out.get("ok") is True
    ids = [c.get("id") for c in out.get("heatmap") or []]
    assert ids == ["packages/pipeline/mcp_install.py::write_kiro_mcp"]


def test_fit_collect_text_honors_a_short_budget() -> None:
    from pipeline.context_trace import _fit_collect_text

    body = "x" * 500
    fitted = _fit_collect_text(body, used=0, max_chars=50)
    assert fitted is not None and len(fitted) == 50
    assert _fit_collect_text(body, used=50, max_chars=50) is None
    shared = _fit_collect_text(body, used=0, max_chars=8000, share=10)
    assert shared is not None and len(shared) == 10


def test_legacy_card_limit_honors_k_one() -> None:
    from pipeline.mcp_locate import _legacy_card_limit

    assert _legacy_card_limit(1) == 1
    assert _legacy_card_limit(0) == 16
    assert _legacy_card_limit(100) == 48


def test_rank_note_when_role_beats_score() -> None:
    from pipeline.context_trace import rank_soft_map_cards

    cards = rank_soft_map_cards(
        [
            {"file": "tests/test_a.py", "symbol": "helper", "kind": "def", "score": 9.0},
            {"file": "packages/pipeline/a.py", "symbol": "helper", "kind": "def", "score": 1.0},
        ]
    )
    assert cards[0]["file"].startswith("packages/")
    assert cards[0].get("rank_note") == "role_adjusted"
    assert cards[0]["score"] == 1.0


def test_force_files_skips_corpus_freshness(monkeypatch, tmp_path: Path) -> None:
    from pipeline.incremental import incremental_sync

    def _boom(*_a, **_k):
        raise AssertionError("named dirty set must not hash the corpus")

    monkeypatch.setattr("pipeline.incremental.check_freshness", _boom)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    result = incremental_sync(
        tmp_path,
        force_files=["a.py"],
        inline=False,
        capacity_wait_s=0.05,
    )
    assert result.strategy == "deferred"
    assert "a.py" in result.files


def test_request_sync_does_not_embed(monkeypatch, tmp_path: Path) -> None:
    from pipeline.incremental import incremental_sync

    def _boom(*_a, **_k):
        raise AssertionError("request sync must not extract")

    monkeypatch.setattr("pipeline.incremental.extract", _boom)
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    result = incremental_sync(
        tmp_path,
        force_files=["a.py"],
        inline=False,
        discover_newcomers=False,
        capacity_wait_s=0.05,
    )
    assert result.strategy == "deferred"
    assert result.chunks_upserted == 0


def test_sync_request_skips_newcomer_walk(monkeypatch, tmp_path: Path) -> None:
    from pipeline.incremental import incremental_sync

    walked = {"n": 0}
    real = __import__("pipeline.incremental", fromlist=["collect_index_relpaths"]).collect_index_relpaths

    def _count(*args, **kwargs):
        walked["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr("pipeline.incremental.collect_index_relpaths", _count)
    incremental_sync(tmp_path, discover_newcomers=False, capacity_wait_s=0.05)
    assert walked["n"] == 0


def test_pack_and_expand_reject_k_before_ast_warm(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    repo = tmp_path / "k0"
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("CTX_REPO", str(repo))
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)
    monkeypatch.setattr("pipeline.daemon.ensure_daemon", lambda *a, **k: {"ok": True, "skipped": True})

    def _boom(*_a, **_k):
        raise AssertionError("k=0 must not touch the AST gate")

    monkeypatch.setattr("pipeline.context_trace.ast_cache_ready", _boom)
    from pipeline.mcp_locate import create_mcp
    from pipeline.mcp_ship_check import parse_tool_json, tool_fn

    mcp = create_mcp(name="k-before-ast")
    pack = parse_tool_json(
        tool_fn(mcp, "pack_context")(
            query="write_kiro_mcp",
            seed_file="packages/pipeline/mcp_install.py",
            seed_symbol="write_kiro_mcp",
            k=0,
        )
    )
    expand = parse_tool_json(tool_fn(mcp, "expand_context")(node="a.py::b", k=0))
    assert pack.get("ok") is False
    assert "k must be >= 1" in str(pack.get("error") or "")
    assert expand.get("ok") is False
    assert "k must be >= 1" in str(expand.get("error") or "")


def test_collect_says_when_session_already_packed(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    repo = tmp_path / "col"
    repo.mkdir()
    (repo / ".git").mkdir()
    monkeypatch.setenv("CTX_REPO", str(repo))
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)
    monkeypatch.setattr("pipeline.daemon.ensure_daemon", lambda *a, **k: {"ok": True, "skipped": True})
    monkeypatch.setattr("pipeline.context_trace.ast_cache_ready", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "pipeline.context_trace.load_trace",
        lambda *_a, **_k: {
            "cards": [{"id": "a.py::f", "score": 1.0, "file": "a.py"}],
            "packed_ids": ["a.py::f"],
            "query": "f",
        },
    )
    monkeypatch.setattr(
        "pipeline.context_trace.run_collect_hot",
        lambda *_a, **_k: {"ok": True, "bodies": []},
    )
    from pipeline.mcp_locate import create_mcp
    from pipeline.mcp_ship_check import parse_tool_json, tool_fn

    mcp = create_mcp(name="already-packed")
    out = parse_tool_json(tool_fn(mcp, "collect_hot_context")())
    assert out.get("ok") is True
    assert out.get("already_packed") is True
    assert out.get("skipped_ids") == ["a.py::f"]


def test_bound_k_rejects_zero_and_honors_one() -> None:
    from pipeline.mcp_locate import _bound_budget, _bound_k

    assert _bound_k(1, hi=48) == 1
    assert _bound_k(16, hi=48) == 16
    assert _bound_k(99, hi=48) == 48
    with pytest.raises(ValueError, match="k must be >= 1"):
        _bound_k(0, hi=48)
    assert _bound_budget(50, default=8000) == 50
    assert _bound_budget(0, default=8000) == 8000
    assert _bound_budget(1, default=4000) == 1


def test_write_kiro_callers_are_not_its_callee() -> None:
    from pipeline.context_trace import run_expand_context

    node = "packages/pipeline/mcp_install.py::write_kiro_mcp"
    callers = run_expand_context(ROOT, node, direction="callers", k=8)
    assert callers.get("ok") is True
    ids = {c.get("id") for c in callers.get("delta") or []}
    assert "packages/pipeline/mcp_install.py::merge_mcp_json" not in ids

    callees = run_expand_context(ROOT, node, direction="callees", k=8)
    assert callees.get("ok") is True
    callee_ids = [c.get("id") for c in callees.get("delta") or []]
    assert callee_ids == ["packages/pipeline/mcp_install.py::merge_mcp_json"]

    effects = run_expand_context(ROOT, node, direction="effects", k=8)
    effect_ids = {c.get("id") for c in effects.get("delta") or []}
    assert "packages/pipeline/mcp_install.py::merge_mcp_json" in effect_ids

    config = run_expand_context(ROOT, node, direction="config", k=8)
    config_ids = {c.get("id") for c in config.get("delta") or []}
    assert "packages/pipeline/mcp_install.py::merge_mcp_json" in config_ids


def test_named_dirty_set_does_not_rewrite_the_corpus(monkeypatch, tmp_path: Path) -> None:
    import json
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import numpy as np

    import pipeline.incremental as incremental_module
    from pipeline.incremental import incremental_sync
    from pipeline.store import ChunkRecord, PipelineStore

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "keep.py").write_text("def keep():\n    return 1\n", encoding="utf-8")
    (repo / "new.py").write_text("def added():\n    return 2\n", encoding="utf-8")
    base = tmp_path / "store"
    base.mkdir()
    store = PipelineStore(repo, base_dir=base)
    old = ChunkRecord(
        id=7,
        file="keep.py",
        start_line=1,
        end_line=2,
        symbol="keep",
        text="def keep():\n    return 1\n",
        enriched="def keep():\n    return 1\n",
    )
    store.save_chunks([old])
    store.save_meta({"chunks": 1, "dim": 4, "bits": 4, "git_head": "abc"})
    store.save_merkle({"keep.py": "deadbeef"})

    def _boom_scan(*_a, **_k):
        raise AssertionError("named sync must not hash the corpus")

    monkeypatch.setattr("pipeline.merkle.scan_file_hashes", _boom_scan)
    monkeypatch.setattr(incremental_module, "extract", lambda *_a, **_k: {"nodes": [], "edges": [], "hyperedges": []})
    monkeypatch.setattr(incremental_module, "graphify_to_repo_ir", lambda *_a, **_k: object())
    monkeypatch.setattr(
        incremental_module,
        "chunk_file_from_ir",
        lambda *_a, **_k: [
            SimpleNamespace(
                file="new.py",
                start_line=1,
                end_line=2,
                symbol="added",
                content="def added():\n    return 2\n",
            )
        ],
    )
    monkeypatch.setattr(
        incremental_module,
        "inject_metadata",
        lambda chunk, _ir: SimpleNamespace(enriched=chunk.content),
    )
    monkeypatch.setattr(incremental_module, "patch_and_save_graph", MagicMock())
    monkeypatch.setattr(incremental_module, "build_and_save_graph", MagicMock())

    class _Emb:
        def embed_many(self, texts):
            return np.ones((len(texts), 4), dtype=np.float32)

    monkeypatch.setattr(incremental_module, "Embedder", lambda **_k: _Emb())
    monkeypatch.setattr("pipeline.engine.get_embedder", lambda *_a, **_k: _Emb())
    monkeypatch.setattr("pipeline.engine.clear_engines", lambda: None)
    monkeypatch.setattr(incremental_module, "_patch_capability_cards", lambda *_a, **_k: None)

    added = {"n": 0}

    class _Col:
        ntotal = 1
        name = "code"

        def delete(self, ids):
            return len(ids)

        def add(self, vectors, ids, payloads=None):
            added["n"] += len(list(ids))
            return len(list(ids))

        def replace_all(self, *_a, **_k):
            raise AssertionError("named sync must not replace the vector index")

    monkeypatch.setattr(PipelineStore, "get_collection", lambda self: _Col())
    monkeypatch.setattr(
        "pipeline.vectordb.VectorDatabase.save_collection", lambda *_a, **_k: None
    )

    result = incremental_sync(repo, base_dir=base, force_files=["new.py"], capacity_wait_s=0.05)
    assert result.refreshed is True, result.error
    assert result.chunks_upserted == 1
    assert added["n"] == 1
    lines = store.chunks_path.read_text(encoding="utf-8").splitlines()
    files = [json.loads(line)["file"] for line in lines if line.strip()]
    assert files == ["keep.py", "new.py"]
    meta = store.load_meta()
    assert meta["chunks"] == 2
    assert meta["git_head"] == "abc"


def test_realistic_add_noop_and_delete(monkeypatch, tmp_path: Path) -> None:
    """Parse real files: a new file lands, an unchanged sync is not a deletion, a delete drops it."""
    import json
    from unittest.mock import MagicMock

    import numpy as np

    import pipeline.incremental as incremental_module
    from pipeline.incremental import incremental_sync
    from pipeline.store import ChunkRecord, PipelineStore

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "keep.py").write_text("def keep():\n    return 1\n", encoding="utf-8")
    base = tmp_path / "store"
    base.mkdir()
    store = PipelineStore(repo, base_dir=base)
    keep = ChunkRecord(
        id=1,
        file="keep.py",
        start_line=1,
        end_line=2,
        symbol="keep",
        text="def keep():\n    return 1\n",
        enriched="def keep():\n    return 1\n",
    )
    store.save_chunks([keep])
    store.save_meta({"chunks": 1, "dim": 4, "bits": 4, "git_head": "abc"})
    store.save_merkle({"keep.py": "aa"})

    class _Emb:
        def embed_many(self, texts):
            return np.ones((len(texts), 4), dtype=np.float32)

    class _Col:
        ntotal = 1
        name = "code"
        deleted: list[int] = []

        def delete(self, ids):
            self.deleted.extend(ids)
            return len(list(ids))

        def add(self, vectors, ids, payloads=None):
            return len(list(ids))

        def replace_all(self, *_a, **_k):
            raise AssertionError("sim must not replace the whole index")

    monkeypatch.setattr(incremental_module, "Embedder", lambda **_k: _Emb())
    monkeypatch.setattr("pipeline.engine.get_embedder", lambda *_a, **_k: _Emb())
    monkeypatch.setattr("pipeline.engine.clear_engines", lambda: None)
    monkeypatch.setattr(incremental_module, "_patch_capability_cards", lambda *_a, **_k: None)
    monkeypatch.setattr(incremental_module, "patch_and_save_graph", MagicMock())
    monkeypatch.setattr("pipeline.vectordb.VectorDatabase.save_collection", lambda *_a, **_k: None)
    monkeypatch.setattr(PipelineStore, "get_collection", lambda self: _Col())

    seeded = incremental_sync(repo, base_dir=base, force_files=["keep.py"], capacity_wait_s=0.05)
    # The seeded chunk's source text matches the file, so since the chunk
    # digest hashes source text (issue 5) this first sync re-embeds nothing.
    assert seeded.error is None, seeded.error
    assert seeded.chunks_removed == 0

    (repo / "new.py").write_text("def added():\n    return 2\n", encoding="utf-8")
    added = incremental_sync(repo, base_dir=base, force_files=["new.py"], capacity_wait_s=0.05)
    assert added.refreshed is True, added.error
    assert added.chunks_upserted >= 1
    assert added.chunks_removed == 0
    files = [json.loads(line)["file"] for line in store.chunks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert files == ["keep.py", "new.py"]

    again = incremental_sync(repo, base_dir=base, force_files=["keep.py"], capacity_wait_s=0.05)
    assert again.refreshed is False, (again.chunks_upserted, again.chunks_removed, again.error)
    assert again.chunks_removed == 0
    assert again.chunks_upserted == 0

    (repo / "new.py").unlink()
    removed = incremental_sync(repo, base_dir=base, force_files=["new.py"], capacity_wait_s=0.05)
    assert removed.chunks_removed >= 1
    files = [json.loads(line)["file"] for line in store.chunks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert files == ["keep.py"]


def test_small_touch_uses_background_budget() -> None:
    from pipeline.memory_budget import resolve_index_memory_budget

    budget = resolve_index_memory_budget(touch_files=8)
    assert budget.mode == "background"

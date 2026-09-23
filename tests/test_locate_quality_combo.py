"""Locate quality combo regressions (Wave 1–2) from 2026-09-11 feedback."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _trace_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_TRACE_PARALLEL", "1")
    monkeypatch.setenv("CTX_TRACE_ENGINE", "composite_v1")


def test_vague_indexing_seed_not_cli_ui_progress() -> None:
    from pipeline.context_trace import pick_suggested_seed

    cards = [
        {
            "file": "packages/pipeline/cli_ui.py",
            "symbol": "indexing",
            "kind": "function",
            "role": "function",
            "score": 550.0,
            "start_line": 1226,
            "end_line": 1235,
            "loc": "packages/pipeline/cli_ui.py:1226-1235",
        },
        {
            "file": "packages/pipeline/__main__.py",
            "symbol": "cmd_index",
            "kind": "function",
            "role": "function",
            "score": 4.2,
            "start_line": 141,
            "end_line": 228,
            "loc": "packages/pipeline/__main__.py:141-228",
        },
        {
            "file": "packages/pipeline/indexer.py",
            "symbol": "index_repo",
            "kind": "function",
            "role": "function",
            "score": 3.4,
            "start_line": 105,
            "end_line": 543,
            "loc": "packages/pipeline/indexer.py:105-543",
        },
    ]
    seed = pick_suggested_seed(cards, query="how does indexing work")
    assert seed is not None
    assert "cli_ui" not in str(seed["file"])
    assert seed["symbol"] in {"index_repo", "cmd_index", "IndexManager"} or "index" in str(
        seed["symbol"]
    ).lower()
    assert seed["symbol"] != "indexing"


def test_vague_session_seed_not_e2e_script() -> None:
    from pipeline.context_trace import pick_suggested_seed

    cards = [
        {
            "file": "scripts/e2e_mcp_idle_reconnect.py",
            "symbol": "session",
            "kind": "function",
            "role": "function",
            "score": 430.0,
            "start_line": 123,
            "end_line": 140,
            "loc": "scripts/e2e_mcp_idle_reconnect.py:123-140",
        },
        {
            "file": "packages/pipeline/work_session.py",
            "symbol": "load_session",
            "kind": "function",
            "role": "function",
            "score": 4.1,
            "start_line": 32,
            "end_line": 56,
            "loc": "packages/pipeline/work_session.py:32-56",
        },
        {
            "file": "fixtures/ce-sim-repo/session.py",
            "symbol": "",
            "kind": "other",
            "role": "other",
            "score": 6.0,
            "start_line": 1,
            "end_line": 3,
        },
    ]
    seed = pick_suggested_seed(cards, query="how does session work")
    assert seed is not None
    assert "work_session" in str(seed["file"])
    assert "scripts/" not in str(seed["file"])
    assert "fixtures/" not in str(seed["file"])


def test_capability_seed_not_blob() -> None:
    from pipeline.context_trace import pick_suggested_seed

    cards = [
        {
            "file": "packages/pipeline/capability.py",
            "symbol": "promotable_cards",
            "kind": "function",
            "role": "function",
            "score": 12.0,
            "start_line": 10,
            "end_line": 40,
        },
        {
            "file": "packages/pipeline/capability.py",
            "symbol": "CapabilityCard.blob",
            "kind": "method",
            "role": "method",
            "score": 11.5,
            "start_line": 38,
            "end_line": 42,
        },
        {
            "file": "packages/pipeline/capability.py",
            "symbol": "CapabilityCard",
            "kind": "class",
            "role": "class",
            "score": 10.0,
            "start_line": 20,
            "end_line": 80,
        },
    ]
    seed = pick_suggested_seed(
        cards, query="capability locate promotable_cards CapabilityIndex"
    )
    assert seed is not None
    leaf = str(seed["symbol"]).rsplit(".", 1)[-1]
    assert leaf != "blob"
    assert leaf in {"promotable_cards", "CapabilityCard", "CapabilityIndex", "locate"} or (
        "Capability" in str(seed["symbol"])
    )


def test_capability_seed_prefers_index_not_locate_hit() -> None:
    from pipeline.context_trace import pick_suggested_seed

    cards = [
        {
            "file": "packages/pipeline/capability.py",
            "symbol": "LocateHit",
            "kind": "class",
            "role": "class",
            "score": 20.0,
            "start_line": 50,
            "end_line": 56,
            "why": "@dataclass\nclass LocateHit:",
        },
        {
            "file": "packages/pipeline/capability.py",
            "symbol": "CapabilityCard",
            "kind": "class",
            "role": "class",
            "score": 18.0,
            "start_line": 29,
            "end_line": 46,
        },
        {
            "file": "packages/pipeline/capability.py",
            "symbol": "CapabilityIndex",
            "kind": "class",
            "role": "class",
            "score": 9.0,
            "start_line": 425,
            "end_line": 464,
        },
        {
            "file": "packages/pipeline/engine.py",
            "symbol": "promotable_cards",
            "kind": "function",
            "role": "function",
            "score": 15.0,
            "start_line": 74,
            "end_line": 93,
        },
    ]
    seed = pick_suggested_seed(
        cards, query="capability locate promotable_cards blob cards"
    )
    assert seed is not None
    leaf = str(seed["symbol"]).rsplit(".", 1)[-1]
    assert leaf in {"CapabilityIndex", "promotable_cards"}
    assert leaf not in {"LocateHit", "CapabilityCard", "blob"}


def test_fill_does_not_paint_unrelated_cards_with_query_type() -> None:
    from pipeline.context_trace import fill_map_card_symbol

    q = "FaissDenseAdapter dense faiss searcher.py vector index adapter"
    guard = fill_map_card_symbol(
        {
            "file": "packages/pipeline/artifact_guard.py",
            "symbol": "invalidate_manifest",
            "kind": "function",
            "role": "function",
            "why": "def invalidate_manifest(store: Path) -> None:",
            "start_line": 92,
            "end_line": 101,
        },
        query=q,
    )
    assert guard["symbol"] == "invalidate_manifest"
    dense = fill_map_card_symbol(
        {
            "file": "packages/conductor/dense_index.py",
            "symbol": "load_cache",
            "kind": "function",
            "role": "function",
            "why": "def load_cache(path: Path) -> dict[str, list[float]]:",
            "start_line": 16,
            "end_line": 28,
        },
        query=q,
    )
    assert dense["symbol"] == "load_cache"
    searcher = fill_map_card_symbol(
        {
            "file": "packages/pipeline/searcher.py",
            "symbol": "",
            "kind": "other",
            "role": "other",
            "why": '"""Search using FAISS collection dense + BM25."""',
            "start_line": 1,
            "end_line": 32,
        },
        query=q,
    )
    assert searcher["symbol"] == "FaissDenseAdapter"


def test_faiss_module_card_without_class_in_why_uses_query_type() -> None:
    """Live soft hits often return searcher.py module docs (no class line in why)."""
    from pipeline.context_trace import pick_suggested_seed

    cards = [
        {
            "file": "packages/pipeline/artifact_guard.py",
            "symbol": "invalidate_manifest",
            "kind": "function",
            "role": "function",
            "score": 8.681,
            "start_line": 92,
            "end_line": 101,
            "why": "def invalidate_manifest(store: Path) -> None:",
        },
        {
            "file": "packages/pipeline/searcher.py",
            "symbol": "",
            "kind": "other",
            "role": "other",
            "score": 48.2722,
            "start_line": 1,
            "end_line": 32,
            "why": '"""Search using FAISS collection dense + BM25 + Graphify → Conductor D_rerank."""',
        },
        {
            "file": "packages/conductor/dense_index.py",
            "symbol": "load_cache",
            "kind": "function",
            "role": "function",
            "score": 8.1234,
            "start_line": 16,
            "end_line": 28,
            "why": "def load_cache(path: Path) -> dict[str, list[float]]:",
        },
    ]
    seed = pick_suggested_seed(
        cards,
        query="FaissDenseAdapter dense faiss searcher.py vector index adapter load search",
    )
    assert seed is not None
    assert "searcher.py" in str(seed["file"])
    assert "FaissDenseAdapter" in str(seed["symbol"])


def test_faiss_dense_adapter_query_prefers_named_class() -> None:
    from pipeline.context_trace import pick_suggested_seed

    cards = [
        {
            "file": "packages/pipeline/dense_index.py",
            "symbol": "load_cache",
            "kind": "function",
            "role": "function",
            "score": 18.0,
            "start_line": 40,
            "end_line": 55,
        },
        {
            "file": "packages/pipeline/searcher.py",
            "symbol": "FaissDenseAdapter",
            "kind": "class",
            "role": "class",
            "score": 9.0,
            "start_line": 30,
            "end_line": 120,
        },
        {
            "file": "packages/pipeline/dense_index.py",
            "symbol": "DenseIndex",
            "kind": "class",
            "role": "class",
            "score": 8.0,
            "start_line": 10,
            "end_line": 200,
        },
    ]
    seed = pick_suggested_seed(
        cards, query="FaissDenseAdapter dense FAISS search how embeddings stored"
    )
    assert seed is not None
    assert "FaissDenseAdapter" in str(seed["symbol"]) or "searcher.py" in str(seed["file"])


def test_resources_query_prefers_resources_module() -> None:
    from pipeline.context_trace import pick_suggested_seed

    cards = [
        {
            "file": "packages/pipeline/sync_loop.py",
            "symbol": "keeper_tick",
            "kind": "method",
            "role": "method",
            "score": 20.0,
            "start_line": 630,
            "end_line": 680,
        },
        {
            "file": "packages/pipeline/resources.py",
            "symbol": "ResourceManager",
            "kind": "class",
            "role": "class",
            "score": 8.0,
            "start_line": 81,
            "end_line": 416,
        },
        {
            "file": "packages/pipeline/resources.py",
            "symbol": "",
            "kind": "other",
            "role": "other",
            "score": 7.5,
            "start_line": 1,
            "end_line": 20,
        },
    ]
    seed = pick_suggested_seed(
        cards, query="ResourceManager wait_for_capacity resources.py memory gate"
    )
    assert seed is not None
    assert "resources.py" in str(seed["file"])
    assert "keeper_tick" not in str(seed["symbol"])


def test_project_id_prefers_resolve_over_collection_name() -> None:
    from pipeline.context_trace import pick_suggested_seed

    cards = [
        {
            "file": "packages/pipeline/project_id.py",
            "symbol": "collection_name_for_project",
            "kind": "function",
            "role": "function",
            "score": 15.0,
            "start_line": 742,
            "end_line": 760,
        },
        {
            "file": "packages/pipeline/project_id.py",
            "symbol": "resolve_project",
            "kind": "function",
            "role": "function",
            "score": 9.0,
            "start_line": 200,
            "end_line": 280,
        },
        {
            "file": "packages/pipeline/project_id.py",
            "symbol": "ProjectRef",
            "kind": "class",
            "role": "class",
            "score": 8.0,
            "start_line": 50,
            "end_line": 120,
        },
    ]
    seed = pick_suggested_seed(
        cards, query="resolve_project project_id enrollment ProjectRef"
    )
    assert seed is not None
    leaf = str(seed["symbol"]).rsplit(".", 1)[-1]
    assert leaf != "collection_name_for_project"
    assert leaf in {"resolve_project", "ProjectRef"}


def test_broad_never_empties_prior_heatmap() -> None:
    """If broad densify fails, keep prior cards — never empty heatmap."""
    from pipeline import context_trace as ct

    prior_cards = [
        {
            "id": "packages/pipeline/cli_ui.py::InitProgress.indexing",
            "file": "packages/pipeline/cli_ui.py",
            "symbol": "indexing",
            "kind": "method",
            "score": 0.9,
            "loc": "packages/pipeline/cli_ui.py:1226-1235",
            "start_line": 1226,
            "end_line": 1235,
            "heat": "hot",
        }
    ]

    def _fake_map(*_a, **_k):
        return {
            "ok": True,
            "query": "indexing",
            "seed": {
                "id": prior_cards[0]["id"],
                "file": prior_cards[0]["file"],
                "symbol": "indexing",
                "kind": "method",
            },
            "heatmap": list(prior_cards),
            "_persist": {},
        }

    # Force broad path but make subclass/class reseed return empty-ish failure by
    # patching enclosing class to None and polytrace map to empty on second call.
    calls = {"n": 0}

    def _fake_map_sometimes_empty(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return _fake_map(*a, **k)
        return {
            "ok": True,
            "query": "indexing",
            "seed": {"id": "x", "file": "packages/pipeline/cli_ui.py", "symbol": "indexing", "kind": "method"},
            "heatmap": [],
            "_persist": {},
        }

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("CTX_TRACE_ENGINE", "composite_v1")
    monkeypatch.setattr(ct, "run_map_context", _fake_map_sometimes_empty)
    monkeypatch.setattr(ct, "_enclosing_public_class", lambda *a, **k: None)
    monkeypatch.setattr(ct, "_find_richer_subclass", lambda *a, **k: None)
    try:
        out = ct.run_pack_context(
            ROOT,
            "how does indexing work",
            seed_file="packages/pipeline/cli_ui.py",
            seed_symbol="indexing",
            mode="lean",
            policy="broad",
            include_bodies=False,
            k=8,
            _allow_broad_reseed=True,
            _allow_subclass_hop=False,
        )
        assert out.get("ok") is True
        heat = out.get("heatmap") or []
        # Must not return empty after a non-empty lean prior
        assert len(heat) >= 1 or out.get("escape_helped") is False
        if out.get("escape_helped") is False:
            assert len(heat) >= 1
    finally:
        monkeypatch.undo()


def test_faiss_dense_query_without_exact_name_prefers_adapter() -> None:
    from pipeline.context_trace import pick_suggested_seed

    cards = [
        {
            "file": "packages/pipeline/searcher.py",
            "symbol": "",
            "kind": "other",
            "role": "other",
            "score": 5.4,
            "why": '"""Search using FAISS collection dense..."""\nclass FaissDenseAdapter(DenseIndex):',
            "start_line": 1,
            "end_line": 32,
        },
        {
            "file": "packages/pipeline/chunk_compress.py",
            "symbol": "compress_mix",
            "kind": "function",
            "role": "function",
            "score": 3.3,
            "start_line": 531,
            "end_line": 560,
        },
        {
            "file": "packages/pipeline/chunk_compress.py",
            "symbol": "CompressResult",
            "kind": "class",
            "role": "class",
            "score": 3.2,
            "start_line": 88,
            "end_line": 98,
        },
    ]
    seed = pick_suggested_seed(
        cards, query="dense adapter FAISS compress mix embeddings search"
    )
    assert seed is not None
    assert "searcher" in str(seed["file"])
    assert "FaissDenseAdapter" in str(seed["symbol"])


def test_resources_prefers_manager_not_cmd_or_to_dict() -> None:
    from pipeline.context_trace import pick_suggested_seed

    cards = [
        {
            "file": "packages/pipeline/resources.py",
            "symbol": "to_dict",
            "kind": "function",
            "role": "function",
            "score": 24.0,
            "why": "def to_dict(self) -> dict[str, Any]:\nclass ResourceManager:",
            "start_line": 77,
            "end_line": 83,
        },
        {
            "file": "packages/pipeline/__main__.py",
            "symbol": "cmd_resources",
            "kind": "function",
            "role": "function",
            "score": 10.0,
            "start_line": 229,
            "end_line": 260,
        },
        {
            "file": "packages/pipeline/memory_budget.py",
            "symbol": "rss_cap_mb",
            "kind": "function",
            "role": "function",
            "score": 6.0,
            "start_line": 236,
            "end_line": 245,
        },
    ]
    seed = pick_suggested_seed(
        cards, query="ResourceManager wait_for_capacity resources.py memory gate"
    )
    assert seed is not None
    assert "resources.py" in str(seed["file"])
    assert str(seed["symbol"]).rsplit(".", 1)[-1] == "ResourceManager"


def test_explicit_heatmap_is_thin_seed_not_swapped() -> None:
    from pipeline.context_trace import _load_repo, resolve_seed_node

    rt = _load_repo(ROOT)
    got = resolve_seed_node(
        rt.nodes,
        file="packages/pipeline/context_trace.py",
        symbol="heatmap_is_thin",
    )
    assert got is not None
    assert got.symbol == "heatmap_is_thin"


def test_resolve_missing_symbol_does_not_invent_largest_class() -> None:
    from pipeline.context_trace import _load_repo, finalize_suggested_seed, resolve_seed_node

    rt = _load_repo(ROOT)
    # CapabilityIndex does not live in engine.py — must not become WarmSearchEngine.
    assert (
        resolve_seed_node(rt.nodes, file="packages/pipeline/engine.py", symbol="CapabilityIndex")
        is None
    )
    final = finalize_suggested_seed(
        ROOT,
        {
            "file": "packages/pipeline/engine.py",
            "symbol": "promotable_cards",
            "start_line": 74,
            "score": 35.8,
            "kind": "function",
        },
        query="capability locate promotable_cards blob cards CapabilityIndex",
    )
    assert final is not None
    assert str(final.get("symbol")).rsplit(".", 1)[-1] == "promotable_cards"


def test_project_id_query_prefers_resolve_project() -> None:
    from pipeline.context_trace import pick_suggested_seed

    cards = [
        {
            "file": "packages/pipeline/artifact_guard.py",
            "symbol": "validate_manifest",
            "kind": "function",
            "role": "function",
            "score": 12.0,
            "start_line": 102,
            "end_line": 120,
        },
        {
            "file": "packages/pipeline/project_id.py",
            "symbol": "collection_name_for_project",
            "kind": "function",
            "role": "function",
            "score": 24.0,
            "start_line": 742,
            "end_line": 752,
        },
        {
            "file": "packages/pipeline/project_id.py",
            "symbol": "resolve_project",
            "kind": "function",
            "role": "function",
            "score": 8.0,
            "start_line": 588,
            "end_line": 640,
        },
        {
            "file": "packages/pipeline/project_id.py",
            "symbol": "ProjectRef",
            "kind": "class",
            "role": "class",
            "score": 40.0,
            "start_line": 40,
            "end_line": 80,
        },
    ]
    seed = pick_suggested_seed(
        cards, query="resolve_project project_id ce_ enroll id.json collection_name_for_project"
    )
    assert seed is not None
    assert str(seed["symbol"]).rsplit(".", 1)[-1] == "resolve_project"


def test_merkle_query_prefers_merkle_not_wipe() -> None:
    from pipeline.context_trace import pick_suggested_seed

    cards = [
        {
            "file": "packages/pipeline/wipe.py",
            "symbol": "wipe",
            "kind": "function",
            "role": "function",
            "score": 4.6,
            "start_line": 1122,
            "end_line": 1149,
        },
        {
            "file": "packages/pipeline/merkle.py",
            "symbol": "",
            "kind": "other",
            "role": "other",
            "score": 43.5,
            "start_line": 1,
            "end_line": 1,
            "why": "Merkle-style file synchronizer (Claude Context–compatible idea).",
        },
        {
            "file": "packages/pipeline/sync_loop.py",
            "symbol": "keeper_tick",
            "kind": "function",
            "role": "function",
            "score": 4.5,
            "start_line": 630,
            "end_line": 697,
        },
    ]
    seed = pick_suggested_seed(
        cards, query="merkle sync incremental dirty file hash root diff added modified"
    )
    assert seed is not None
    assert "wipe" not in str(seed["symbol"]).lower()
    assert "merkle.py" in str(seed["file"]) or str(seed["symbol"]).rsplit(".", 1)[-1] in {
        "scan_file_hashes",
        "diff_hashes",
        "root_hash",
        "SyncDiff",
        "keeper_tick",
    }


def test_turboquant_alias_resolves_codec() -> None:
    from pipeline.context_trace import fill_map_card_symbol, finalize_suggested_seed, pick_suggested_seed

    filled = fill_map_card_symbol(
        {
            "file": "packages/pipeline/turbo_quant.py",
            "symbol": "_codebook_centers",
            "kind": "function",
            "role": "function",
            "why": '"""Google TurboQuant-style online vector quantization."""',
            "start_line": 40,
            "end_line": 60,
            "score": 50.0,
        },
        query="TurboQuant compress FAISS bits quantization",
    )
    assert filled.get("symbol") == "TurboQuantCodec"
    seed = pick_suggested_seed(
        [
            {
                "file": "packages/pipeline/chunk_compress.py",
                "symbol": "compress_mix",
                "kind": "function",
                "role": "function",
                "score": 30.0,
                "start_line": 100,
                "end_line": 140,
            },
            filled,
        ],
        query="TurboQuant compress_mix FAISS bits online vector quantization TurboQuantCodec",
    )
    assert seed is not None
    assert str(seed["symbol"]).rsplit(".", 1)[-1] == "TurboQuantCodec"
    final = finalize_suggested_seed(
        ROOT,
        {
            "file": "packages/pipeline/turbo_quant.py",
            "symbol": "TurboQuant",
            "start_line": 1,
            "kind": "class",
        },
        query="TurboQuant compress FAISS bits",
    )
    assert final is not None
    assert "TurboQuantCodec" in str(final.get("symbol"))
    assert not final.get("seed_incomplete")


def test_multiarch_not_painted_on_searcher() -> None:
    from pipeline.context_trace import fill_map_card_symbol

    card = fill_map_card_symbol(
        {
            "file": "packages/pipeline/searcher.py",
            "symbol": "",
            "role": "other",
            "why": '"""Search using FAISS collection dense + BM25 + Graphify → Conductor D_rerank."""',
            "start_line": 1,
            "end_line": 32,
        },
        query="MultiArchConductor conductor subclass hop D_rerank",
    )
    assert card.get("symbol") != "MultiArchConductor"


def test_merkle_file_match_excludes_chunk_merkle() -> None:
    from pipeline.context_trace import _is_pipeline_merkle_file, _type_home_affinity, fill_map_card_symbol

    assert _is_pipeline_merkle_file("packages/pipeline/merkle.py")
    assert not _is_pipeline_merkle_file("packages/pipeline/chunk_merkle.py")
    assert _type_home_affinity("SyncDiff", "packages/pipeline/chunk_merkle.py") < 50.0
    assert _type_home_affinity("SyncDiff", "packages/pipeline/merkle.py") >= 50.0
    painted = fill_map_card_symbol(
        {
            "file": "packages/pipeline/chunk_merkle.py",
            "symbol": "",
            "role": "other",
            "why": "chunk merkle digest helpers",
            "start_line": 1,
            "end_line": 20,
        },
        query="merkle sync SyncDiff scan_file_hashes",
    )
    assert painted.get("symbol") != "SyncDiff"


def test_project_id_finalize_prefers_resolve_project() -> None:
    from pipeline.context_trace import finalize_suggested_seed

    final = finalize_suggested_seed(
        ROOT,
        {
            "file": "packages/pipeline/project_id.py",
            "symbol": "",
            "start_line": 1,
            "kind": "other",
        },
        query="resolve_project project_id ce_ enroll id.json",
    )
    assert final is not None
    assert str(final.get("symbol")).rsplit(".", 1)[-1] == "resolve_project"
    assert not final.get("seed_incomplete")


def test_graphify_prefers_load_store_over_conductor() -> None:
    from pipeline.context_trace import pick_suggested_seed

    seed = pick_suggested_seed(
        [
            {
                "file": "packages/conductor/conductor.py",
                "symbol": "Conductor",
                "kind": "class",
                "role": "class",
                "score": 11.0,
                "start_line": 47,
                "end_line": 193,
            },
            {
                "file": "packages/trace_lab/graphify_layer.py",
                "symbol": "load_store_graphify_graph",
                "kind": "function",
                "role": "function",
                "score": 24.0,
                "start_line": 77,
                "end_line": 120,
            },
        ],
        query="graphify_layer load_store_graphify_graph CALLS edges",
    )
    assert seed is not None
    assert str(seed["symbol"]).rsplit(".", 1)[-1] == "load_store_graphify_graph"


def test_fastembed_alias_resolves_embedder() -> None:
    from pipeline.context_trace import fill_map_card_symbol, finalize_suggested_seed

    filled = fill_map_card_symbol(
        {
            "file": "packages/pipeline/embedder.py",
            "symbol": "FastEmbed",
            "kind": "class",
            "role": "class",
            "why": "FastEmbed DML providers",
            "start_line": 94,
            "end_line": 153,
            "score": 15.0,
        },
        query="Embedder embed_many FastEmbed DML providers",
    )
    # Weak/missing FastEmbed should snap toward Embedder via finalize.
    final = finalize_suggested_seed(
        ROOT,
        {
            "file": "packages/pipeline/embedder.py",
            "symbol": "FastEmbed",
            "start_line": 94,
            "kind": "class",
        },
        query="Embedder embed_many FastEmbed DML",
    )
    assert final is not None
    assert str(final.get("symbol")).rsplit(".", 1)[-1] == "Embedder"
    assert not final.get("seed_incomplete")
    assert filled.get("symbol") in {"Embedder", "FastEmbed"}


def test_freshness_prefers_verify_over_syncdiff() -> None:
    from pipeline.context_trace import pick_suggested_seed

    seed = pick_suggested_seed(
        [
            {
                "file": "packages/pipeline/freshness.py",
                "symbol": "verify_merkle_leaves",
                "kind": "function",
                "role": "function",
                "score": 30.0,
                "start_line": 167,
                "end_line": 205,
            },
            {
                "file": "packages/pipeline/merkle.py",
                "symbol": "SyncDiff",
                "kind": "class",
                "role": "class",
                "score": 17.0,
                "start_line": 81,
                "end_line": 90,
            },
        ],
        query="verify_merkle_leaves freshness SyncDiff file_mtimes packages/pipeline/freshness.py",
    )
    assert seed is not None
    assert str(seed["symbol"]).rsplit(".", 1)[-1] == "verify_merkle_leaves"
    assert "freshness.py" in str(seed["file"])


def test_bm25_prefers_index_over_tokenize() -> None:
    from pipeline.context_trace import fill_map_card_symbol, pick_suggested_seed

    filled = fill_map_card_symbol(
        {
            "file": "packages/conductor/bm25_index.py",
            "symbol": "tokenize",
            "kind": "function",
            "role": "function",
            "why": "def tokenize(text: str) -> list[str]: return [t.lower() for t in _TOKEN.findall(text)] class BM25Index:",
            "start_line": 14,
            "end_line": 18,
            "score": 19.0,
        },
        query="bm25_index BM25Index tokenize search hybrid packages/conductor/bm25_index.py",
    )
    assert filled.get("symbol") == "BM25Index"
    seed = pick_suggested_seed(
        [
            filled,
            {
                "file": "packages/conductor/conductor.py",
                "symbol": "Conductor",
                "kind": "class",
                "role": "class",
                "score": 24.0,
                "start_line": 47,
                "end_line": 193,
            },
            {
                "file": "packages/trace_lab/strategies.py",
                "symbol": "hybrid",
                "kind": "function",
                "role": "function",
                "score": 8.0,
                "start_line": 117,
                "end_line": 148,
            },
        ],
        query="bm25_index BM25Index tokenize search hybrid packages/conductor/bm25_index.py",
    )
    assert seed is not None
    assert str(seed["symbol"]).rsplit(".", 1)[-1] == "BM25Index"
    assert "bm25_index.py" in str(seed["file"])


def test_polytrace_prefers_poly_trace_over_faction() -> None:
    from pipeline.context_trace import finalize_suggested_seed, pick_suggested_seed

    seed = pick_suggested_seed(
        [
            {
                "file": "packages/trace_lab/polytrace.py",
                "symbol": "_lex_confirm",
                "kind": "function",
                "role": "function",
                "score": 20.0,
                "start_line": 341,
                "end_line": 376,
            },
            {
                "file": "packages/trace_lab/polytrace.py",
                "symbol": "faction_of",
                "kind": "function",
                "role": "function",
                "score": 12.0,
                "start_line": 99,
                "end_line": 105,
            },
        ],
        query="polytrace composite_v1 channels faction graphify packages/trace_lab/polytrace.py",
    )
    assert seed is not None
    final = finalize_suggested_seed(
        ROOT,
        seed,
        query="polytrace composite_v1 channels faction graphify packages/trace_lab/polytrace.py",
    )
    assert final is not None
    assert str(final.get("symbol")).rsplit(".", 1)[-1] == "poly_trace"


def test_watchdog_prefers_status_over_private() -> None:
    from pipeline.context_trace import finalize_suggested_seed, pick_suggested_seed

    seed = pick_suggested_seed(
        [
            {
                "file": "packages/pipeline/watchdog.py",
                "symbol": "_update_watchdog_state",
                "kind": "function",
                "role": "function",
                "score": 20.0,
                "start_line": 53,
                "end_line": 71,
            },
            {
                "file": "packages/pipeline/lifecycle_runtime.py",
                "symbol": "ensure_supervisor",
                "kind": "function",
                "role": "function",
                "score": 7.5,
                "start_line": 1045,
                "end_line": 1060,
            },
        ],
        query="watchdog restart_count last_reconcile engine ensure packages/pipeline",
    )
    assert seed is not None
    final = finalize_suggested_seed(
        ROOT,
        seed,
        query="watchdog restart_count last_reconcile engine ensure packages/pipeline",
    )
    assert final is not None
    assert str(final.get("symbol")).rsplit(".", 1)[-1] in {
        "watchdog_status",
        "start_watchdog",
        "watchdog_loop",
    }
    assert "watchdog.py" in str(final["file"])


def test_fixture_only_map_suggested_seed_null() -> None:
    from pipeline.context_trace import pick_suggested_seed

    cards = [
        {
            "file": "fixtures/trace-lab/app/middleware/auth.py",
            "symbol": "authenticate",
            "kind": "function",
            "role": "function",
            "score": 20.0,
            "start_line": 1,
            "end_line": 20,
        },
        {
            "file": "fixtures/ce-sim-repo/session.py",
            "symbol": "login",
            "kind": "function",
            "role": "function",
            "score": 10.0,
            "start_line": 1,
            "end_line": 10,
        },
    ]
    seed = pick_suggested_seed(cards, query="where is auth")
    assert seed is None

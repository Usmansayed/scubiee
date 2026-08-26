from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from pipeline.memory_budget import (
    BACKGROUND_RSS_CAP_MB,
    BOOTSTRAP_RSS_CAP_MB,
    LARGE_REINDEX_CHUNK_THRESHOLD,
    LARGE_REINDEX_RSS_CAP_MB,
    apply_index_memory_budget,
    background_budget,
    bootstrap_budget,
    is_bootstrap_index,
    large_reindex_budget,
    process_rss_mb,
    process_rss_peak_mb,
    resolve_index_memory_budget,
)


def test_rss_helpers_work_without_unix_resource_module() -> None:
    rss = process_rss_mb()
    peak = process_rss_peak_mb()
    assert rss is None or rss > 0
    assert peak is None or peak > 0
    assert "resource" not in __import__("pipeline.memory_budget", fromlist=["*"]).__dict__


def test_bootstrap_budget_defaults() -> None:
    b = bootstrap_budget()
    assert b.mode == "bootstrap"
    assert b.rss_cap_mb == BOOTSTRAP_RSS_CAP_MB == 800
    assert b.mlx_batch == 48
    assert b.mlx_cache_mb == 256
    assert b.aggressive_unload is False


def test_background_budget_defaults() -> None:
    b = background_budget()
    assert b.mode == "background"
    assert b.rss_cap_mb == BACKGROUND_RSS_CAP_MB == 500
    assert b.mlx_batch == 24
    assert b.mlx_cache_mb == 128
    assert b.aggressive_unload is True


def test_large_reindex_budget_defaults() -> None:
    b = large_reindex_budget()
    assert b.mode == "large_reindex"
    assert b.rss_cap_mb == LARGE_REINDEX_RSS_CAP_MB == 1000
    assert b.aggressive_unload is False


def test_is_bootstrap_index_empty_store(tmp_path: Path) -> None:
    store = MagicMock()
    store.chunks_path = tmp_path / "chunks.jsonl"
    store.chunks_path.write_text("", encoding="utf-8")
    store.load_meta.return_value = {}
    assert is_bootstrap_index(store) is True


def test_resolve_background_vs_bootstrap(tmp_path: Path) -> None:
    chunks = tmp_path / "chunks.jsonl"
    chunks.write_text("{}\n", encoding="utf-8")
    store = MagicMock()
    store.chunks_path = chunks
    store.load_meta.return_value = {"chunks": 100, "indexed_at": 1.0}

    assert resolve_index_memory_budget(background=True, store=store).mode == "background"
    assert resolve_index_memory_budget(background=False).mode == "bootstrap"


def test_resolve_large_reindex_when_chunks_exceed_threshold(tmp_path: Path) -> None:
    chunks = tmp_path / "chunks.jsonl"
    chunks.write_text("{}\n", encoding="utf-8")
    store = MagicMock()
    store.chunks_path = chunks
    store.load_meta.return_value = {
        "chunks": LARGE_REINDEX_CHUNK_THRESHOLD + 1,
        "indexed_at": 1.0,
    }

    budget = resolve_index_memory_budget(background=True, store=store)
    assert budget.mode == "large_reindex"
    assert budget.rss_cap_mb == LARGE_REINDEX_RSS_CAP_MB


def test_apply_index_memory_budget_respects_existing_env(monkeypatch) -> None:
    import os

    monkeypatch.setenv("CTX_MLX_CACHE_MB", "128")
    monkeypatch.setenv("CTX_EMBED_BATCH", "8")
    leaked = (
        "CTX_CE_MEMORY_MODE",
        "CTX_CE_RSS_CAP_MB",
        "CTX_CE_EMB_BATCH_CEILING",
        "CTX_CE_AGGRESSIVE_UNLOAD",
        "CTX_MLX_DTYPE",
        "CTX_MLX_FAST_ATTN",
        "CTX_MLX_FAST_LN",
        "CTX_MLX_EVAL",
    )
    previous = {key: os.environ.get(key) for key in leaked}
    for key in leaked:
        os.environ.pop(key, None)
    try:
        apply_index_memory_budget(background_budget())
        assert os.environ["CTX_MLX_CACHE_MB"] == "128"
        assert os.environ["CTX_EMBED_BATCH"] == "8"
        assert os.environ["CTX_CE_MEMORY_MODE"] == "background"
        assert os.environ["CTX_CE_EMB_BATCH_CEILING"] == "24"
        assert os.environ["CTX_MLX_DTYPE"] == "float16"
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

"""Map/search must use real FastEmbed dense → D_channel_best (0.3.93+)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest


def test_dense_d_channel_helper_rejects_pseudo_and_warming() -> None:
    from pipeline.engine import is_dense_d_channel_result

    assert is_dense_d_channel_result(
        {"ok": True, "dense": True, "timings": {"dense": True, "retrieve_mode": "D_channel_best"}}
    )
    assert not is_dense_d_channel_result(
        {"ok": True, "timings": {"dense": False, "retrieve_mode": "D_channel_best:pseudo"}}
    )
    assert not is_dense_d_channel_result(
        {"ok": False, "warming": True, "error": "dense_embed_loading"}
    )
    assert not is_dense_d_channel_result(
        {"ok": True, "cards": [{"file": "a.py"}], "timings": {"retrieve_mode": "capability"}}
    )
    assert is_dense_d_channel_result(
        {"ok": True, "cards": [{"file": "a.py", "source": "D_channel_best:bm25+dense"}]}
    )


def test_map_result_cache_skips_non_dense() -> None:
    from pipeline.map_result_cache import clear_map_cache, get_map_cached, put_map_cached

    clear_map_cache()
    put_map_cached(
        repo="/r",
        query="bm25 only",
        fingerprint="fp1",
        payload={"ok": True, "cards": [{"file": "a.py"}]},
    )
    assert get_map_cached(repo="/r", query="bm25 only", fingerprint="fp1") is None


def test_search_uses_real_dense_even_with_skip_freshness(monkeypatch) -> None:
    from pipeline import engine as eng

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: True)
    monkeypatch.setattr(eng, "prewarm_status", lambda: {"running": False})
    monkeypatch.setattr(
        eng,
        "ensure_embedder_ready",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("already loaded")),
    )

    inner = MagicMock()
    inner.embed_one = MagicMock(return_value=np.ones(8, dtype=np.float32))
    lazy = MagicMock()
    lazy.dim = 8
    # Intentionally do NOT alias lazy.embed_one → search must unwrap via _ensure.
    lazy.embed_one = MagicMock(
        side_effect=AssertionError("must unwrap LazyEmbedder before encode")
    )
    lazy._ensure = MagicMock(return_value=inner)

    conductor = MagicMock()
    conductor.retrieve_D_channel_best = MagicMock(return_value=[])

    monkeypatch.setattr(eng, "run_embed_infer", lambda fn, timeout_s=None: fn())

    e = eng.WarmSearchEngine.__new__(eng.WarmSearchEngine)
    e.root = Path(".")
    e.embedder = lazy
    e.conductor = conductor
    e.chunks = []
    e.texts = []
    e.capability = None
    e.loaded_at = 0.0

    monkeypatch.setenv("CTX_ALLOW_PSEUDO_DENSE", "0")
    out = e.search("watchdog_loop heal", top_k=3, skip_freshness=True)
    assert out == []
    lazy._ensure.assert_called()
    lazy.embed_one.assert_not_called()
    inner.embed_one.assert_called_once()
    conductor.retrieve_D_channel_best.assert_called_once()
    assert e._last_timings.get("dense") is True
    assert "D_channel_best" in str(e._last_timings.get("retrieve_mode"))


def test_search_refuses_pseudo_dense_when_embed_fails(monkeypatch) -> None:
    from pipeline import engine as eng

    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: False)
    monkeypatch.setattr(
        eng,
        "ensure_embedder_ready",
        lambda *_a, **_k: {"ok": False, "error": "boom"},
    )
    monkeypatch.setattr(eng, "prewarm_status", lambda: {"running": False})
    monkeypatch.setenv("CTX_ALLOW_PSEUDO_DENSE", "0")

    monkeypatch.setattr(
        eng,
        "run_embed_infer",
        lambda fn, timeout_s=None: (_ for _ in ()).throw(RuntimeError("ort missing")),
    )

    emb = MagicMock(dim=8)
    emb.embed_one = MagicMock(side_effect=RuntimeError("ort missing"))

    e = eng.WarmSearchEngine.__new__(eng.WarmSearchEngine)
    e.root = Path(".")
    e.embedder = emb
    e.conductor = MagicMock()
    e.chunks = []
    e.texts = []
    e.capability = None
    e.loaded_at = 0.0

    with pytest.raises(RuntimeError, match="dense_embed_required"):
        e.search("q", top_k=2, skip_freshness=True)


def test_register_client_defers_prewarm_until_soft_ready(
    tmp_path: Path, monkeypatch
) -> None:
    from conftest import enroll_test_repo
    from pipeline import lifecycle_runtime as life

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(tmp_path, home=home, project_id="ce_dense_reg_defer001")
    monkeypatch.setattr(life, "is_engine_process", lambda: True)
    kicked: list[str] = []

    monkeypatch.setattr("pipeline.engine.embedder_is_loaded", lambda: False)
    monkeypatch.setattr(
        "pipeline.engine.prewarm_embedder_async",
        lambda *_a, **_k: kicked.append("prewarm") or {"ok": True, "started": True},
    )
    monkeypatch.setattr(
        "pipeline.engine.ensure_embedder_ready",
        lambda *_a, **_k: kicked.append("embed") or {"ok": True},
    )
    monkeypatch.setattr(
        "pipeline.engine.ensure_embed_keepalive_loop",
        lambda *_a, **_k: kicked.append("keepalive") or {"ok": True, "started": True},
    )
    monkeypatch.setattr(
        "pipeline.memory_governor.get_governor",
        lambda: MagicMock(ensure_semantic_tier=MagicMock()),
    )

    out = life.register_client("mcp:cursor@test-1", pid=1234, kind="mcp")
    assert out.get("ok") is True
    # Arm keepalive only — do not sync-load ORT / kick prewarm on register.
    assert kicked == ["keepalive"]
    prewarm = out.get("prewarm") or {}
    assert prewarm.get("keepalive_armed") is True
    assert prewarm.get("skipped") is None


def test_register_client_starts_keepalive_when_already_warm(
    tmp_path: Path, monkeypatch
) -> None:
    from conftest import enroll_test_repo
    from pipeline import lifecycle_runtime as life

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    enroll_test_repo(tmp_path, home=home, project_id="ce_dense_reg_keep001")
    monkeypatch.setattr(life, "is_engine_process", lambda: True)
    kept: list[str] = []

    monkeypatch.setattr("pipeline.engine.embedder_is_loaded", lambda: True)
    monkeypatch.setattr(
        "pipeline.engine.ensure_embed_keepalive_loop",
        lambda *_a, **_k: kept.append("keepalive") or {"ok": True},
    )
    monkeypatch.setattr(
        "pipeline.memory_governor.get_governor",
        lambda: MagicMock(ensure_semantic_tier=MagicMock()),
    )

    out = life.register_client("mcp:cursor@test-2", pid=1234, kind="mcp")
    assert out.get("ok") is True
    assert "keepalive" in kept
    assert (out.get("prewarm") or {}).get("already_warm") is True

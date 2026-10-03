"""Broad escape densify + honesty."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _trace_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_TRACE_PARALLEL", "1")
    monkeypatch.setenv("CTX_TRACE_ENGINE", "composite_v1")


def test_broad_on_thin_leaf_reseeds_or_sets_escape_helped_false() -> None:
    from pipeline.context_trace import heatmap_is_thin, run_pack_context

    q = "TurboQuant to_float32 compressed embedding decode"
    leaf = run_pack_context(
        ROOT,
        q,
        seed_file="packages/pipeline/turbo_quant.py",
        seed_symbol="to_float32",
        mode="lean",
        policy="strict",
        include_bodies=False,
        k=12,
    )
    assert leaf.get("ok") is True
    # Broad escape: either densifies via class reseed or honestly reports no help.
    broad = run_pack_context(
        ROOT,
        q,
        seed_file="packages/pipeline/turbo_quant.py",
        seed_symbol="to_float32",
        mode="lean",
        policy="broad",
        include_bodies=False,
        k=12,
    )
    assert broad.get("ok") is True
    assert "escape_helped" in broad
    if broad.get("escape_helped"):
        # Reseed should land on a class-ish seed or strictly more cards.
        seed_sym = str((broad.get("seed") or {}).get("symbol") or "")
        assert "to_float32" not in seed_sym.split(".")[-1] or int(broad.get("count") or 0) > int(
            leaf.get("count") or 0
        )
        assert broad.get("thin") is False or int(broad.get("count") or 0) > int(
            leaf.get("count") or 0
        )
    else:
        assert broad.get("thin") is True or heatmap_is_thin(broad.get("heatmap") or [])
        nxt = str(broad.get("next") or "").lower()
        assert "expand" in nxt or "read" in nxt
        assert "re-pack" in nxt or "repack" in nxt or "broad" in nxt


def test_strict_pack_has_no_escape_helped_false_noise() -> None:
    from pipeline.context_trace import run_pack_context

    out = run_pack_context(
        ROOT,
        "embed_many encode",
        seed_file="packages/pipeline/embedder.py",
        seed_symbol="embed_many",
        mode="lean",
        policy="strict",
        include_bodies=False,
        k=8,
    )
    assert out.get("ok") is True
    # strict path may omit the field or set None — never claim broad escape helped.
    assert out.get("escape_helped") in (None, False) or "escape" not in (
        out.get("escape") or {}
    ).get("reason", "policy=broad")

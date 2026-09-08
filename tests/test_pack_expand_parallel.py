"""Parallel pack/expand phases stay correct (dual-seed merge + expand merge)."""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _parallel_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_TRACE_PARALLEL", "1")
    monkeypatch.setenv("CTX_TRACE_ENGINE", "composite_v1")


def test_dual_seed_map_context_merges_both_seeds(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.context_trace import run_map_context

    out = run_map_context(
        ROOT,
        "merge_cursor_permissions prune stale allowlist ship locate",
        seed_file="packages/pipeline/mcp_permissions.py",
        seed_symbol="merge_cursor_permissions",
        seed2_file="packages/pipeline/mcp_permissions.py",
        seed2_symbol="_prune_stale_scubiee_allowlist_entries",
        k=16,
    )
    assert out.get("ok") is True
    ids = {c.get("id") for c in (out.get("heatmap") or [])}
    assert "packages/pipeline/mcp_permissions.py::merge_cursor_permissions" in ids


def test_expand_callees_parallel_returns_delta() -> None:
    from pipeline.context_trace import run_expand_context

    out = run_expand_context(
        ROOT,
        "packages/pipeline/mcp_permissions.py::merge_cursor_permissions",
        query="merge_cursor_permissions callers callees",
        direction="callees",
        k=12,
    )
    assert out.get("ok") is True
    assert isinstance(out.get("delta"), list)


def test_parallel_can_disable(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline import context_trace as ct

    monkeypatch.setenv("CTX_TRACE_PARALLEL", "0")
    assert ct._trace_parallel_enabled() is False

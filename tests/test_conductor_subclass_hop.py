"""Conductor class pack should hop to MultiArchConductor when file-local."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _trace_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_TRACE_PARALLEL", "1")
    monkeypatch.setenv("CTX_TRACE_ENGINE", "composite_v1")


def test_find_richer_subclass_multiarch() -> None:
    from pipeline.context_trace import _find_richer_subclass, _load_repo
    from trace_lab.types import TraceNode

    rt = _load_repo(ROOT)
    seed = rt.nodes.get("packages/conductor/conductor.py::Conductor")
    assert seed is not None
    richer = _find_richer_subclass(rt.nodes, seed)
    assert richer is not None
    assert richer.symbol == "MultiArchConductor"
    assert "architectures.py" in richer.file


def test_pack_conductor_hops_to_multiarch() -> None:
    from pipeline.context_trace import run_pack_context

    out = run_pack_context(
        ROOT,
        "Conductor retrieve_conductor MultiArch hybrid graphify BM25 dense",
        seed_file="packages/conductor/conductor.py",
        seed_symbol="Conductor",
        mode="lean",
        policy="strict",
        include_bodies=False,
        k=12,
    )
    assert out.get("ok") is True
    seed_sym = str((out.get("seed") or {}).get("symbol") or "")
    files = {
        str(c.get("file") or c.get("loc") or "").replace("\\", "/")
        for c in (out.get("heatmap") or [])
    }
    # Either reseeded seed is MultiArch, or heatmap spans architectures.py
    assert (
        "MultiArch" in seed_sym
        or any("architectures.py" in f for f in files)
        or out.get("seed_promoted")
    )
    assert int(out.get("count") or 0) >= 3
    # Prefer cross-file when promotion helped
    if out.get("seed_promoted") or "MultiArch" in seed_sym:
        assert any("architectures.py" in f for f in files)
        assert "MultiArch" in seed_sym or any(
            "MultiArch" in str(c.get("symbol") or "") for c in (out.get("heatmap") or [])
        )

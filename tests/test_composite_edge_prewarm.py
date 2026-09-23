"""Composite edge prewarm — second ensure hits memory, pack does not rebuild."""

from __future__ import annotations

from pathlib import Path

from trace_lab.composite_v1 import _EDGE_CACHE, ensure_composite_edges


def test_ensure_composite_edges_builds_once(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def _build(*_a, **_k):
        calls["n"] += 1
        return []

    monkeypatch.setattr("trace_lab.composite_v1.build_enriched_call_graph", _build)
    monkeypatch.setattr("trace_lab.composite_v1.build_dfg_edges", lambda *_a, **_k: [])
    monkeypatch.setattr("trace_lab.composite_v1.compose_pdg", lambda edges, _extra: edges)
    monkeypatch.setattr(
        "trace_lab.corpus.corpus_fingerprint",
        lambda _root: "prewarm-fp",
    )
    key = str(tmp_path.resolve())
    _EDGE_CACHE.pop(key, None)
    first = ensure_composite_edges(tmp_path, {}, None, None, None)
    second = ensure_composite_edges(tmp_path, {}, None, None, None)
    assert first["ok"] is True
    assert first["source"] == "build"
    assert second["source"] == "memory"
    assert calls["n"] == 1
    _EDGE_CACHE.pop(key, None)

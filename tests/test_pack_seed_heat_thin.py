"""Seed policy, query-aware heat, thin-pack / explain-escape signals."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.context_trace import (
    heatmap_is_thin,
    map_ladder_next,
    map_module_clustered,
    pick_suggested_seed,
    resolve_seed_node,
)
from pipeline.mcp_response_lean import _pack_heatmap_only
from trace_lab.composite_v1 import apply_query_aware_heat
from trace_lab.types import TraceNode


def _node(
    file: str,
    symbol: str,
    *,
    kind: str = "function",
    start: int = 1,
    end: int = 10,
) -> TraceNode:
    return TraceNode(
        id=f"{file}::{symbol}",
        file=file,
        symbol=symbol,
        kind=kind,
        start_line=start,
        end_line=end,
        text=f"{kind} {symbol}\n",
    )


def test_pick_suggested_seed_prefers_class_over_private_helper() -> None:
    cards = [
        {
            "file": "packages/pipeline/turbo_quant.py",
            "symbol": "_unpack",
            "kind": "function",
            "role": "function",
            "score": 18.6,
            "start_line": 186,
            "end_line": 195,
            "loc": "packages/pipeline/turbo_quant.py:186-195",
        },
        {
            "file": "packages/pipeline/vectordb.py",
            "symbol": "FaissCollection",
            "kind": "class",
            "role": "class",
            "score": 17.1,
            "start_line": 104,
            "end_line": 369,
            "loc": "packages/pipeline/vectordb.py:104-369",
        },
    ]
    seed = pick_suggested_seed(
        cards,
        query="vector database FAISS how embeddings stored search add load save",
    )
    assert seed is not None
    assert seed["symbol"] == "FaissCollection"
    assert "vectordb" in str(seed["file"])


def test_pick_suggested_seed_prefers_module_card_over_private_when_query_names_file() -> None:
    cards = [
        {
            "file": "packages/pipeline/turbo_quant.py",
            "symbol": "_unpack",
            "kind": "function",
            "role": "function",
            "score": 18.0,
            "start_line": 186,
            "end_line": 195,
            "loc": "packages/pipeline/turbo_quant.py:186-195",
        },
        {
            "file": "packages/pipeline/vectordb.py",
            "symbol": "",
            "kind": "other",
            "role": "other",
            "score": 17.0,
            "start_line": 85,
            "end_line": 91,
            "loc": "packages/pipeline/vectordb.py:85-91",
        },
    ]
    seed = pick_suggested_seed(
        cards,
        query="how does vector database FAISS vectordb work add search save load",
    )
    assert seed is not None
    assert seed["file"] == "packages/pipeline/vectordb.py"


def test_resolve_seed_bare_file_prefers_public_class() -> None:
    nodes = {
        "pkg/db.py::_helper": _node("pkg/db.py", "_helper", kind="function", start=1, end=3),
        "pkg/db.py::Store": _node("pkg/db.py", "Store", kind="class", start=10, end=200),
        "pkg/db.py::run": _node("pkg/db.py", "run", kind="function", start=210, end=220),
    }
    got = resolve_seed_node(nodes, file="pkg/db.py")
    assert got is not None
    assert got.symbol == "Store"


def test_apply_query_aware_heat_boosts_verbs_demotes_accessors() -> None:
    nodes = {
        "f.py::Store.add": _node("f.py", "Store.add", kind="method", start=10, end=40),
        "f.py::Store.get": _node("f.py", "Store.get", kind="method", start=50, end=52),
        "f.py::Store.name": _node("f.py", "Store.name", kind="method", start=53, end=54),
    }
    scores = {
        "f.py::Store.add": 0.50,
        "f.py::Store.get": 0.90,
        "f.py::Store.name": 0.88,
    }
    why = {k: "path" for k in scores}
    out, why2 = apply_query_aware_heat(
        scores, why, nodes, "how embeddings add search save load work"
    )
    assert out["f.py::Store.add"] >= 0.72
    assert out["f.py::Store.get"] < scores["f.py::Store.get"]
    assert out["f.py::Store.name"] < scores["f.py::Store.name"]
    assert "verb_boost" in why2["f.py::Store.add"]
    assert "accessor_demote" in why2["f.py::Store.get"]


def test_heatmap_is_thin_and_pack_lean_signals() -> None:
    thin_cards = [
        {
            "id": "a::get",
            "symbol": "get",
            "heat": "hot",
            "score": 0.9,
            "start_line": 1,
            "end_line": 2,
        },
        {
            "id": "a::name",
            "symbol": "name",
            "heat": "hot",
            "score": 0.8,
            "start_line": 3,
            "end_line": 4,
        },
    ]
    assert heatmap_is_thin(thin_cards) is True
    lean = _pack_heatmap_only(
        {
            "ok": True,
            "tool": "pack_context",
            "seed": {"id": "a::get", "file": "a.py", "symbol": "get"},
            "heatmap": [
                {
                    "id": "a::get",
                    "loc": "a.py:1-2",
                    "symbol": "get",
                    "score": 0.9,
                }
            ],
            "thin": True,
            "prefer": "expand_context|Native-Read seed file",
        },
        tool_name="pack_context",
    )
    assert lean["thin"] is True
    assert "expand" in str(lean.get("prefer") or "").lower()
    assert "thin" in str(lean.get("next") or "").lower()


def test_pick_rejects_from_dict_and_default_root() -> None:
    cards = [
        {
            "file": "packages/pipeline/vectordb.py",
            "symbol": "from_dict",
            "kind": "function",
            "role": "function",
            "score": 99.0,
            "start_line": 100,
            "end_line": 105,
            "loc": "packages/pipeline/vectordb.py:100-105",
        },
        {
            "file": "packages/pipeline/vectordb.py",
            "symbol": "default_vectordb_root",
            "kind": "function",
            "role": "function",
            "score": 90.0,
            "start_line": 41,
            "end_line": 45,
            "loc": "packages/pipeline/vectordb.py:41-45",
        },
        {
            "file": "packages/pipeline/vectordb.py",
            "symbol": "FaissCollection",
            "kind": "class",
            "role": "class",
            "score": 40.0,
            "start_line": 104,
            "end_line": 369,
            "loc": "packages/pipeline/vectordb.py:104-369",
        },
    ]
    seed = pick_suggested_seed(cards, query="vector database FAISS vectordb")
    assert seed is not None
    assert seed["symbol"] == "FaissCollection"


def test_resolve_rejects_from_dict_for_class() -> None:
    nodes = {
        "pkg/db.py::from_dict": _node("pkg/db.py", "from_dict", kind="function", start=1, end=3),
        "pkg/db.py::default_vectordb_root": _node(
            "pkg/db.py", "default_vectordb_root", kind="function", start=5, end=8
        ),
        "pkg/db.py::FaissCollection": _node(
            "pkg/db.py", "FaissCollection", kind="class", start=20, end=200
        ),
    }
    got = resolve_seed_node(nodes, file="pkg/db.py", symbol="from_dict")
    assert got is not None
    assert got.symbol == "FaissCollection"
    got2 = resolve_seed_node(nodes, file="pkg/db.py", start_line=1)
    assert got2 is not None
    assert got2.symbol == "FaissCollection"


def test_finalize_suggested_seed_fills_empty_symbol_from_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import context_trace as ct
    from pipeline.context_trace import finalize_suggested_seed

    nodes = {
        "packages/pipeline/vectordb.py::FaissCollection": _node(
            "packages/pipeline/vectordb.py",
            "FaissCollection",
            kind="class",
            start=104,
            end=369,
        ),
        "packages/pipeline/vectordb.py::add": _node(
            "packages/pipeline/vectordb.py",
            "FaissCollection.add",
            kind="method",
            start=120,
            end=140,
        ),
    }

    class _RT:
        pass

    rt = _RT()
    rt.nodes = nodes
    monkeypatch.setattr(ct, "_load_repo", lambda _root: rt)

    suggested = {
        "file": "packages/pipeline/vectordb.py",
        "symbol": "",
        "start_line": 1,
        "loc": "packages/pipeline/vectordb.py:1-1",
        "kind": "chunk",
        "role": "other",
        "score": 12.0,
    }
    out = finalize_suggested_seed(tmp_path, suggested)
    assert out is not None
    assert out["symbol"] == "FaissCollection"
    assert out.get("seed_incomplete") is not True
    assert "104" in str(out.get("loc") or "")


def test_finalize_suggested_seed_marks_incomplete_when_unresolvable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import context_trace as ct
    from pipeline.context_trace import finalize_suggested_seed

    class _RT:
        nodes: dict = {}

    monkeypatch.setattr(ct, "_load_repo", lambda _root: _RT())
    out = finalize_suggested_seed(
        tmp_path,
        {"file": "packages/missing/nope.py", "symbol": "", "start_line": 1},
    )
    assert out is not None
    assert out.get("seed_incomplete") is True
    assert not (out.get("symbol") or "").strip()


def test_finalize_skips_load_repo_when_seed_already_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import context_trace as ct
    from pipeline.context_trace import finalize_suggested_seed

    called = {"n": 0}

    def _boom(_root: Path) -> None:
        called["n"] += 1
        raise AssertionError("_load_repo must not run for a complete map seed")

    monkeypatch.setattr(ct, "_load_repo", _boom)
    suggested = {
        "file": "packages/pipeline/memory_governor.py",
        "symbol": "MemoryGovernor",
        "loc": "packages/pipeline/memory_governor.py:10-80",
        "kind": "class",
        "role": "class",
        "start_line": 10,
    }
    out = finalize_suggested_seed(
        tmp_path,
        suggested,
        query="MemoryGovernor demote_after_index idle MCP clients",
    )
    assert called["n"] == 0
    assert out is not None
    assert out["symbol"] == "MemoryGovernor"
    assert out["loc"] == suggested["loc"]


def test_finalize_map_path_never_loads_repo_for_incomplete_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline import context_trace as ct
    from pipeline.context_trace import finalize_suggested_seed

    called = {"n": 0}

    def _boom(_root: Path) -> None:
        called["n"] += 1
        raise AssertionError("map must not build the AST graph")

    monkeypatch.setattr(ct, "_load_repo", _boom)
    out = finalize_suggested_seed(
        tmp_path,
        {"file": "packages/pipeline/mcp_locate.py", "symbol": "", "loc": "packages/pipeline/mcp_locate.py:1-60"},
        query="mcp_locate.py map pack_context",
        load_repo=False,
    )
    assert called["n"] == 0
    assert out is not None
    assert out.get("seed_incomplete") is True
    assert not (out.get("symbol") or "").strip()


def test_lean_pack_does_not_poison_collect_skip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Heatmap-only pack must leave packed_ids empty so collect can fill bodies."""
    from pipeline import context_trace as ct

    cards = [
        {
            "id": "pkg/a.py::Store",
            "file": "pkg/a.py",
            "symbol": "Store",
            "kind": "class",
            "score": 1.0,
            "loc": "pkg/a.py:1-10",
            "start_line": 1,
            "end_line": 10,
            "heat": "hot",
            "why": "seed",
        },
        {
            "id": "pkg/a.py::Store.add",
            "file": "pkg/a.py",
            "symbol": "Store.add",
            "kind": "method",
            "score": 0.9,
            "loc": "pkg/a.py:12-20",
            "start_line": 12,
            "end_line": 20,
            "heat": "hot",
            "why": "verb",
        },
    ]

    def _fake_map(*_a, **_k):
        return {
            "ok": True,
            "query": "add search",
            "seed": {"id": "pkg/a.py::Store", "file": "pkg/a.py", "symbol": "Store"},
            "heatmap": cards,
            "_persist": {},
        }

    monkeypatch.setattr(ct, "run_map_context", _fake_map)
    out = ct.run_pack_context(
        tmp_path,
        "add search save load",
        seed_file="pkg/a.py",
        seed_symbol="Store",
        include_bodies=False,
        mode="lean",
    )
    assert out["ok"] is True
    persist = out["_persist"]
    assert persist["packed_ids"] == []
    assert persist["cards"]

    # Simulate collect after lean: no skip poison.
    nodes = {
        "pkg/a.py::Store": _node("pkg/a.py", "Store", kind="class", start=1, end=10),
        "pkg/a.py::Store.add": _node("pkg/a.py", "Store.add", kind="method", start=12, end=20),
    }
    for n in nodes.values():
        object.__setattr__(n, "text", f"def {n.symbol}():\n    return 1\n") if False else None
    # TraceNode is a dataclass — rebuild with text
    from trace_lab.types import TraceNode

    nodes = {
        nid: TraceNode(
            id=nid,
            file=n.file,
            symbol=n.symbol,
            kind=n.kind,
            start_line=n.start_line,
            end_line=n.end_line,
            text=f"body for {n.symbol}\n" * 5,
        )
        for nid, n in nodes.items()
    }

    class _RT:
        pass

    rt = _RT()
    rt.nodes = nodes
    monkeypatch.setattr(ct, "_load_repo", lambda _root: rt)
    collected = ct.run_collect_hot(
        tmp_path,
        cards,
        threshold=0.45,
        skip_ids=set(persist["packed_ids"]),
        max_bodies=2,
    )
    assert collected["count"] >= 1
    assert collected["empty_bodies"] is False
    assert collected["bodies"][0].get("text")


def test_map_explain_escape_next() -> None:
    cards = [
        {"file": "packages/pipeline/vectordb.py", "symbol": "_unpack", "role": "function"},
        {"file": "packages/pipeline/vectordb.py", "symbol": "", "role": "other"},
        {"file": "packages/pipeline/store.py", "symbol": "", "role": "other"},
    ]
    assert map_module_clustered(cards) is True
    nxt = map_ladder_next(
        cards,
        {"file": "packages/pipeline/vectordb.py", "symbol": "_unpack"},
        query="how does the vector database work with FAISS",
    )
    assert "skip pack" in nxt.lower() or "explain" in nxt.lower()

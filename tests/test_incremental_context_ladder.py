"""Unit tests for incremental context ladder helpers."""

from __future__ import annotations

from pipeline.context_trace import (
    build_call_chain,
    card_role,
    fill_map_card_symbol,
    pick_suggested_seed,
    rank_soft_map_cards,
    resolve_seed_node,
    symbol_from_preview,
)
from trace_lab.types import TraceNode


def _node(
    file: str,
    symbol: str,
    *,
    kind: str = "function",
    start: int = 1,
    end: int = 20,
) -> TraceNode:
    return TraceNode(
        id=f"{file}::{symbol}",
        file=file,
        symbol=symbol,
        kind=kind,
        start_line=start,
        end_line=end,
        text=f"def {symbol}():\n    pass\n",
    )


def test_symbol_from_preview_parses_def_and_class() -> None:
    assert symbol_from_preview("def run_pack_context(root, query):") == ("run_pack_context", "function")
    assert symbol_from_preview("async def load():\n    pass") == ("load", "function")
    assert symbol_from_preview("class Engine:\n    pass") == ("Engine", "class")
    assert symbol_from_preview("# just a comment") == ("", "")


def test_fill_map_card_symbol_from_why() -> None:
    card = fill_map_card_symbol(
        {
            "file": "packages/pipeline/context_trace.py",
            "symbol": "",
            "kind": "chunk",
            "role": "function",
            "start_line": 1138,
            "end_line": 1200,
            "why": "def run_pack_context( root: Path, query: str, *, seed_file: str",
        }
    )
    assert card["symbol"] == "run_pack_context"
    assert card["kind"] == "function"
    assert card["loc"] == "packages/pipeline/context_trace.py:1138-1200"


def test_resolve_seed_uses_covering_start_line_without_symbol() -> None:
    nodes = {
        "pkg/a.py::_boot": _node("pkg/a.py", "_boot", kind="function", start=1, end=5),
        "pkg/a.py::run": _node("pkg/a.py", "run", kind="function", start=10, end=40),
        "pkg/a.py::other": _node("pkg/a.py", "other", kind="function", start=50, end=80),
    }
    got = resolve_seed_node(nodes, file="pkg/a.py", start_line=25)
    assert got is not None
    assert got.symbol == "run"


def test_card_role_classifies_tests_docs_and_functions() -> None:
    assert card_role("packages/pipeline/mcp_locate.py", "function") == "function"
    assert card_role("tests/test_mcp_permissions.py", "function") == "test"
    assert card_role("docs/HANDOFF.md", "") == "docs"


def test_rank_soft_map_prefers_packages_over_tests() -> None:
    cards = [
        {
            "file": "tests/test_mcp_permissions.py",
            "symbol": "test_write",
            "kind": "function",
            "score": 20.0,
            "start_line": 1,
            "end_line": 10,
        },
        {
            "file": "packages/pipeline/rules_installer.py",
            "symbol": "write_project_tool_surface",
            "kind": "function",
            "score": 12.0,
            "start_line": 100,
            "end_line": 160,
        },
    ]
    ranked = rank_soft_map_cards(cards)
    assert ranked[0]["file"].startswith("packages/")
    assert ranked[0]["role"] == "function"
    seed = pick_suggested_seed(ranked)
    assert seed is not None
    assert seed["symbol"] == "write_project_tool_surface"


def test_resolve_seed_skips_root_const_for_covering_function() -> None:
    nodes = {
        "packages/pipeline/mcp_locate.py::ROOT": _node(
            "packages/pipeline/mcp_locate.py", "ROOT", kind="const", start=34, end=34
        ),
        "packages/pipeline/mcp_locate.py::map_impl": _node(
            "packages/pipeline/mcp_locate.py", "map_impl", kind="function", start=3486, end=3600
        ),
    }
    got = resolve_seed_node(
        nodes, file="packages/pipeline/mcp_locate.py", symbol="ROOT", start_line=3500
    )
    assert got is not None
    assert got.symbol == "map_impl"


def test_resolve_seed_prefers_function_over_const_in_file() -> None:
    nodes = {
        "pkg/a.py::ROOT": _node("pkg/a.py", "ROOT", kind="const", start=1, end=1),
        "pkg/a.py::run": _node("pkg/a.py", "run", kind="function", start=10, end=40),
    }
    got = resolve_seed_node(nodes, file="pkg/a.py")
    assert got is not None
    assert got.symbol == "run"


def test_pick_suggested_seed_prefers_public_over_private() -> None:
    cards = [
        {
            "file": "packages/pipeline/mcp_locate.py",
            "symbol": "_helper",
            "kind": "function",
            "role": "function",
            "score": 0.99,
            "start_line": 10,
            "end_line": 20,
            "loc": "packages/pipeline/mcp_locate.py:10-20",
        },
        {
            "file": "packages/pipeline/mcp_locate.py",
            "symbol": "create_mcp",
            "kind": "function",
            "role": "function",
            "score": 0.80,
            "start_line": 100,
            "end_line": 200,
            "loc": "packages/pipeline/mcp_locate.py:100-200",
        },
    ]
    seed = pick_suggested_seed(cards)
    assert seed is not None
    assert seed["symbol"] == "create_mcp"


def test_resolve_seed_prefers_public_in_file() -> None:
    nodes = {
        "pkg/a.py::_boot": _node("pkg/a.py", "_boot", kind="function", start=1, end=5),
        "pkg/a.py::run": _node("pkg/a.py", "run", kind="function", start=10, end=40),
    }
    got = resolve_seed_node(nodes, file="pkg/a.py")
    assert got is not None
    assert got.symbol == "run"


def test_build_call_chain_marks_edges() -> None:
    cards = [
        {
            "id": "a::f",
            "loc": "a.py:1-2",
            "symbol": "f",
            "kind": "function",
            "why": "seed/flow",
            "score": 1.0,
        },
        {
            "id": "b::g",
            "loc": "b.py:3-4",
            "symbol": "g",
            "kind": "function",
            "why": "calls f->g",
            "score": 0.9,
        },
    ]
    chain = build_call_chain(cards)
    assert chain[0]["edge"] == "seed"
    assert chain[1]["edge"] == "calls"

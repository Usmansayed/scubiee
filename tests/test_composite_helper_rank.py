"""Composite pack ranking: substantial callees outrank tiny and private helpers."""

from __future__ import annotations

from trace_lab.composite_v1 import apply_rank_composite
from trace_lab.policy.intent import TraceSpec
from trace_lab.types import TraceNode


def _node(symbol: str, start: int, end: int) -> TraceNode:
    return TraceNode(
        id=f"pkg/mod.py::{symbol}",
        file="pkg/mod.py",
        symbol=symbol,
        kind="function",
        start_line=start,
        end_line=end,
        text="pass",
    )


def test_apply_rank_composite_demotes_tiny_and_private_helpers() -> None:
    seed = _node("run_pack_context", 1, 400)
    tiny = _node("_is_default_pack_engine", 10, 12)
    private = _node("_load_repo", 20, 120)
    big = _node("run_map_context", 200, 400)
    nodes = {n.id: n for n in (seed, tiny, private, big)}
    scores = {n.id: 1.0 for n in nodes.values()}
    why = {n.id: "CALLS:1.0 run_pack_context->x" for n in nodes.values()}
    paths = {
        seed.id: (seed.id,),
        tiny.id: (seed.id, tiny.id),
        private.id: (seed.id, private.id),
        big.id: (seed.id, big.id),
    }
    spec = TraceSpec(mode="flow", user_query="pack heatmap run_pack_context")
    ranked, why_out, _paths = apply_rank_composite(scores, why, paths, nodes, spec)
    assert ranked[seed.id] == 1.0
    assert ranked[big.id] > ranked[tiny.id]
    assert ranked[big.id] > ranked[private.id]
    assert "helper_demote" in why_out[tiny.id]
    assert "helper_demote" in why_out[private.id]
    assert "helper_demote" not in why_out[big.id]


def test_query_named_private_helper_keeps_score() -> None:
    seed = _node("run_pack_context", 1, 400)
    private = _node("_load_repo", 20, 120)
    nodes = {n.id: n for n in (seed, private)}
    scores = {n.id: 1.0 for n in nodes.values()}
    why = {n.id: "call" for n in nodes.values()}
    paths = {seed.id: (seed.id,), private.id: (seed.id, private.id)}
    spec = TraceSpec(mode="flow", user_query="pack _load_repo run_pack_context")
    ranked, why_out, _paths = apply_rank_composite(scores, why, paths, nodes, spec)
    # Named so it is not demoted. Span still breaks the 0.99 tie.
    assert ranked[private.id] > 0.9
    assert "helper_demote" not in why_out[private.id]


def test_named_large_callee_stays_above_short_helpers() -> None:
    seed = _node("run_pack_context", 3399, 4162)
    short = _node("card_role", 1, 24)
    named = _node("run_map_context", 1600, 1900)
    nodes = {n.id: n for n in (seed, short, named)}
    scores = {n.id: 1.0 for n in nodes.values()}
    why = {n.id: "call" for n in nodes.values()}
    paths = {
        seed.id: (seed.id,),
        short.id: (seed.id, short.id),
        named.id: (seed.id, named.id),
    }
    spec = TraceSpec(mode="flow", user_query="substantial callees run_map_context")
    ranked, _why, _paths = apply_rank_composite(scores, why, paths, nodes, spec)
    assert ranked[named.id] > ranked[short.id]


def test_pack_run_pack_context_ranks_substantial_callees() -> None:
    import time
    from pathlib import Path

    from pipeline.context_trace import run_pack_context

    root = Path(__file__).resolve().parents[1]
    query = "pack_context lean heatmap run_pack_context composite_v1 multi_seed_v1 seed rank"
    seed = {
        "seed_file": "packages/pipeline/context_trace.py",
        "seed_symbol": "run_pack_context",
        "mode": "lean",
        "include_bodies": False,
        "k": 8,
    }
    t0 = time.perf_counter()
    strict = run_pack_context(root, query, policy="strict", **seed)
    strict_s = time.perf_counter() - t0
    assert strict.get("ok") is True, strict.get("error")
    symbols = [str(c.get("symbol") or "") for c in (strict.get("heatmap") or [])]
    wanted = {"run_map_context", "run_collect_hot", "ensure_seeds_on_heatmap"}
    assert wanted & set(symbols), symbols
    assert "_is_default_pack_engine" not in symbols[:4]
    assert strict_s < 20.0

    named_q = (
        "packages/pipeline/context_trace.py::run_pack_context composite_v1 "
        "substantial callees run_map_context run_collect_hot ensure_seeds_on_heatmap"
    )
    named = run_pack_context(root, named_q, policy="strict", **seed)
    assert named.get("ok") is True, named.get("error")
    named_symbols = [str(c.get("symbol") or "") for c in (named.get("heatmap") or [])]
    assert wanted <= set(named_symbols), named_symbols

    t1 = time.perf_counter()
    broad = run_pack_context(root, query, policy="broad", **seed)
    broad_s = time.perf_counter() - t1
    assert broad.get("ok") is True, broad.get("error")
    assert broad.get("engine") != "polytrace"
    assert (broad.get("escape") or {}).get("to") == "composite_rerank"
    assert broad_s < 20.0
    broad_symbols = [str(c.get("symbol") or "") for c in (broad.get("heatmap") or [])]
    assert wanted & set(broad_symbols), broad_symbols

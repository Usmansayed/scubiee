"""Tests for semantic tracer policy + system arms."""

from __future__ import annotations

from pathlib import Path

from trace_lab.policy.intent import parse_trace_spec
from trace_lab.strategies import compile_bundle
from trace_lab.types import GoldCase, GoldRef


def test_intent_only_care_stays_flow_with_auth_cues() -> None:
    spec = parse_trace_spec(
        "Same auth stack, but I only care about the credential verification path"
    )
    assert spec.mode == "flow"
    assert spec.hop_cap >= 4


def test_intent_excludes_telemetry() -> None:
    spec = parse_trace_spec("Job run until digest is produced, with no telemetry")
    assert "track" in spec.exclude_names or "analytics" in spec.exclude_names


def test_system_arms_registered() -> None:
    root = Path(__file__).resolve().parents[1] / "fixtures" / "trace-lab"
    _nodes, _graph, _lex, tracers = compile_bundle(
        root, with_graphify=True, with_embed_power=False
    )
    for name in (
        "polytrace",
        "callgraph_jedi",
        "dfg_slice",
        "pdg_prio",
        "hybrid_teleport",
        "rank_default",
        "rank_strict",
    ):
        assert name in tracers, name


def test_rank_default_runs_auth() -> None:
    root = Path(__file__).resolve().parents[1] / "fixtures" / "trace-lab"
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=True, with_embed_power=False
    )
    seed = GoldRef(file="app/middleware/auth.py", symbol="authenticate")
    if seed.id not in nodes:
        cands = [
            n
            for n in nodes.values()
            if n.file.endswith("middleware/auth.py") and n.kind in {"function", "method"}
        ]
        assert cands
        n0 = sorted(cands, key=lambda n: n.start_line)[0]
        seed = GoldRef(file=n0.file, symbol=n0.symbol)
    case = GoldCase(
        id="auth",
        title="auth",
        query="How does JWT authentication verify bearer tokens and load the user?",
        seed=seed,
        must=[],
        should=[],
        must_not=[],
        gold_rank=[],
    )
    hm = tracers["rank_default"](case, nodes, graph, lex)
    assert hm.cells
    assert hm.cells[0].score >= 0.9
    assert hm.extra.get("engine") == "semantic_system"

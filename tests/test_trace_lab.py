"""Context-tracing simulation: gold heatmaps vs pluggable strategies."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from trace_lab.ast_graph import build_ast_graph
from trace_lab.cases import default_fixture_root, load_cases
from trace_lab.corpus import extract_nodes
from trace_lab.metrics import evaluate, ndcg_at_k
from trace_lab.sim import HOT_THRESHOLD, run_sim
from trace_lab.strategies import compile_bundle
from trace_lab.types import GoldCase, GoldRef, HeatCell, Heatmap, TraceNode, node_id

FIXTURE = ROOT / "fixtures" / "trace-lab"


def test_fixture_gold_ids_exist_in_corpus():
    nodes = extract_nodes(FIXTURE)
    cases = load_cases(FIXTURE / "cases")
    assert {c.id for c in cases} >= {"auth-flow", "token-expiry", "login-entry", "auth-log-write"}
    missing: list[str] = []
    for case in cases:
        for ref in [case.seed, *case.must, *case.should, *case.must_not]:
            if ref.id not in nodes:
                missing.append(f"{case.id}:{ref.id}")
    assert missing == [], missing


def test_ast_graph_follows_generic_auth_names():
    nodes = extract_nodes(FIXTURE)
    graph = build_ast_graph(FIXTURE, nodes)
    auth = node_id("app/middleware/auth.py", "authenticate")
    verify = node_id("app/services/jwt_service.py", "JwtService.verify")
    decode = node_id("app/utils/token.py", "decode")
    resolve = node_id("app/repositories/user_repo.py", "UserRepository.resolve")
    lookup = node_id("app/models/user.py", "User.lookup")
    ttl = node_id("app/config/security.py", "TOKEN_TTL")

    callees = {t for t, rel, _ in graph.neighbors(auth, directed=True) if rel == "calls"}
    assert verify in callees

    from_verify = {t for t, _rel, _w in graph.neighbors(verify, directed=True)}
    assert decode in from_verify
    assert resolve in from_verify
    assert ttl in from_verify

    from_resolve = {t for t, _rel, _w in graph.neighbors(resolve, directed=True)}
    assert lookup in from_resolve


def test_metrics_math_on_toy_heatmap():
    gold = GoldCase(
        id="toy",
        title="toy",
        query="q",
        seed=GoldRef("a.py", "f"),
        must=[GoldRef("a.py", "f"), GoldRef("b.py", "g")],
        should=[GoldRef("c.py", "h")],
        must_not=[GoldRef("d.py", "noise")],
        gold_rank=[],
    )
    hm = Heatmap(
        strategy="toy",
        cells=[
            HeatCell(node_id("a.py", "f"), 1.0, "seed"),
            HeatCell(node_id("d.py", "noise"), 0.95, "trap"),
            HeatCell(node_id("b.py", "g"), 0.5, "call"),
        ],
    )
    nodes = {
        node_id("a.py", "f"): TraceNode(node_id("a.py", "f"), "a.py", "f", "function", 1, 2, "aa aa"),
        node_id("b.py", "g"): TraceNode(node_id("b.py", "g"), "b.py", "g", "function", 1, 2, "bb"),
        node_id("d.py", "noise"): TraceNode(node_id("d.py", "noise"), "d.py", "noise", "function", 1, 2, "nn nn nn"),
    }
    met = evaluate(hm, gold, nodes, hot_threshold=0.45)
    assert met.recall_must == 1.0
    assert met.false_positives_forbidden == [node_id("d.py", "noise")]
    assert met.inversions >= 1
    assert 0.0 <= ndcg_at_k(hm.ranked_ids(), gold) <= 1.0


def _by_name(report: dict, case_id: str) -> dict[str, dict]:
    case = next(c for c in report["cases"] if c["case"] == case_id)
    return {row["strategy"]: row for row in case["metrics"]}


@pytest.fixture(scope="module")
def sim_report(tmp_path_factory):
    cache = tmp_path_factory.mktemp("trace-lab-cache")
    return run_sim(FIXTURE, cache_root=cache, with_graphify=True)


def test_hybrid_recovers_generic_auth_path(sim_report):
    rows = _by_name(sim_report, "auth-flow")
    hybrid = rows["hybrid"]
    bm25 = rows["bm25_body"]
    assert hybrid["recall_must"] >= 0.8, hybrid["false_negatives"]
    assert "app/utils/token.py::decode" not in bm25["false_negatives"] or bm25["recall_must"] < hybrid["recall_must"]
    assert hybrid["recall_must"] > bm25["recall_must"]
    assert "app/billing/invoices.py::charge" not in hybrid["false_positives_forbidden"]


def test_bm25_falls_for_lexical_trap(sim_report):
    rows = _by_name(sim_report, "auth-flow")
    bm25 = rows["bm25_body"]
    # billing mentions "authentication"; generic decode does not
    assert "app/utils/token.py::decode" in bm25["false_negatives"]
    assert (
        "app/billing/invoices.py::charge" in bm25["false_positives_forbidden"]
        or bm25["recall_must"] < 0.5
    )


def test_naive_bfs_explodes_into_hubs(sim_report):
    rows = _by_name(sim_report, "auth-flow")
    bfs = rows["ast_undirected_bfs"]
    hybrid = rows["hybrid"]
    assert bfs["precision_hot"] < hybrid["precision_hot"]
    assert len(bfs["false_positives_forbidden"]) >= len(hybrid["false_positives_forbidden"])


def test_narrow_log_query_does_not_dump_auth_path(sim_report):
    rows = _by_name(sim_report, "auth-log-write")
    hybrid = rows["hybrid"]
    assert hybrid["recall_must"] == 1.0, hybrid["false_negatives"]
    assert "app/utils/token.py::decode" not in hybrid["false_positives_forbidden"]
    assert "app/services/jwt_service.py::JwtService.verify" not in hybrid["false_positives_forbidden"]


def test_token_expiry_hits_ttl_constant(sim_report):
    rows = _by_name(sim_report, "token-expiry")
    hybrid = rows["hybrid"]
    assert "app/config/security.py::TOKEN_TTL" not in hybrid["false_negatives"]
    assert hybrid["recall_must"] == 1.0, hybrid["false_negatives"]


def test_hybrid_mean_f1_beats_lexical_and_naive_bfs(sim_report):
    summary = {row["strategy"]: row for row in sim_report["summary"]}
    hybrid = summary["hybrid"]
    assert hybrid["mean_f1"] > summary["bm25_body"]["mean_f1"]
    assert hybrid["mean_f1"] > summary["ast_undirected_bfs"]["mean_f1"]
    assert hybrid["mean_recall_must"] >= 0.75


def test_graphify_strategy_runs(sim_report):
    names = {row["strategy"] for row in sim_report["summary"]}
    assert "graphify_propagate" in names
    g = next(r for r in sim_report["summary"] if r["strategy"] == "graphify_propagate")
    assert g["mean_recall_must"] >= 0.0

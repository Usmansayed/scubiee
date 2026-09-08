"""Novel tracing strategies vs the gold heatmap board."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from trace_lab.retrieve import query_intent
from trace_lab.sim import run_sim

FIXTURE = ROOT / "fixtures" / "trace-lab"


def _rows(report: dict, case_id: str) -> dict[str, dict]:
    case = next(c for c in report["cases"] if c["case"] == case_id)
    return {row["strategy"]: row for row in case["metrics"]}


@pytest.fixture(scope="module")
def sim_report(tmp_path_factory):
    cache = tmp_path_factory.mktemp("trace-lab-novel-cache")
    return run_sim(FIXTURE, cache_root=cache, with_graphify=False)


def test_query_intent_classes():
    assert query_intent("How does authentication work?") == "flow"
    assert query_intent("Where is token expiry configured?") == "config"
    assert query_intent("Where does authenticate write log output?") == "site"
    assert query_intent("How does login authenticate the user?") == "entry"


def test_novel_strategies_are_on_the_board(sim_report):
    names = {row["strategy"] for row in sim_report["summary"]}
    for name in (
        "obligation",
        "intent_slice",
        "ppr_idf",
        "hub_shadow",
        "spread_gate",
        "bridge_heat",
        "agree_fuse",
    ):
        assert name in names


def test_obligation_recovers_generic_auth_path(sim_report):
    ob = _rows(sim_report, "auth-flow")["obligation"]
    assert ob["recall_must"] >= 0.8, ob["false_negatives"]
    assert "app/utils/token.py::decode" not in ob["false_negatives"]
    assert "app/billing/invoices.py::charge" not in ob["false_positives_forbidden"]
    assert "app/utils/logger.py::log" not in ob["false_positives_forbidden"]


def test_obligation_site_query_keeps_logger_not_jwt(sim_report):
    ob = _rows(sim_report, "auth-log-write")["obligation"]
    assert ob["recall_must"] == 1.0, ob["false_negatives"]
    assert "app/services/jwt_service.py::JwtService.verify" not in ob["false_positives_forbidden"]
    assert "app/utils/token.py::decode" not in ob["false_positives_forbidden"]


def test_obligation_config_hits_ttl_not_user_lookup(sim_report):
    ob = _rows(sim_report, "token-expiry")["obligation"]
    assert "app/config/security.py::TOKEN_TTL" not in ob["false_negatives"]
    assert "app/models/user.py::User.lookup" not in ob["false_positives_forbidden"]


def test_hub_shadow_cleaner_than_naive_bfs(sim_report):
    summary = {row["strategy"]: row for row in sim_report["summary"]}
    assert summary["hub_shadow"]["sum_forbidden_fp"] < summary["ast_undirected_bfs"]["sum_forbidden_fp"]


def test_novel_beats_lexical_mean_f1(sim_report):
    summary = {row["strategy"]: row for row in sim_report["summary"]}
    lexical = summary["bm25_body"]["mean_f1"]
    best_novel = max(
        summary[n]["mean_f1"]
        for n in ("obligation", "agree_fuse", "intent_slice", "spread_gate", "ppr_idf")
    )
    assert best_novel > lexical

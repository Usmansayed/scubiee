"""PolyTrace: 10+ diverse gold cases, mean F1 and must-recall >= 0.95."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from trace_lab.cases import load_cases
from trace_lab.retrieve import query_intent
from trace_lab.sim import run_sim

FIXTURE = ROOT / "fixtures" / "trace-lab"


def _rows(report: dict, case_id: str) -> dict[str, dict]:
    case = next(c for c in report["cases"] if c["case"] == case_id)
    return {row["strategy"]: row for row in case["metrics"]}


@pytest.fixture(scope="module")
def sim_report(tmp_path_factory):
    cache = tmp_path_factory.mktemp("trace-lab-poly-cache")
    return run_sim(FIXTURE, cache_root=cache, with_graphify=False)


def test_board_has_at_least_ten_diverse_cases():
    cases = load_cases(FIXTURE / "cases")
    ids = {c.id for c in cases}
    assert len(ids) >= 10, ids
    traps = {
        "auth-flow",
        "token-expiry",
        "auth-log-write",
        "charge-flow",
        "event-emit",
        "ttl-refs",
        "cors-isolated",
        "store-fetch",
        "job-run",
        "health-isolated",
    }
    assert traps <= ids, ids


def test_query_intent_refs_and_what_does():
    assert query_intent("Who uses TOKEN_TTL?") == "refs"
    assert query_intent("What does verify do with the token?") == "flow"


def test_polytrace_mean_f1_and_recall_hit_95(sim_report):
    summary = {row["strategy"]: row for row in sim_report["summary"]}
    row = summary["polytrace"]
    assert row["mean_recall_must"] >= 0.95, row
    assert row["mean_f1"] >= 0.95, row
    assert row["sum_forbidden_fp"] == 0, row
    assert row["sum_fn"] == 0, row


def test_polytrace_event_emit_finds_bound_handler(sim_report):
    pt = _rows(sim_report, "event-emit")["polytrace"]
    assert pt["recall_must"] == 1.0, pt["false_negatives"]
    assert "app/handlers/welcome.py::handle" not in pt["false_negatives"]
    assert "app/middleware/auth.py::authenticate" not in pt["false_positives_forbidden"]


def test_polytrace_charge_takes_http_not_auth(sim_report):
    pt = _rows(sim_report, "charge-flow")["polytrace"]
    assert "app/http/client.py::get" not in pt["false_negatives"]
    assert "app/middleware/auth.py::authenticate" not in pt["false_positives_forbidden"]


def test_polytrace_cors_does_not_leak_auth(sim_report):
    pt = _rows(sim_report, "cors-isolated")["polytrace"]
    assert pt["recall_must"] == 1.0
    assert "app/middleware/auth.py::authenticate" not in pt["false_positives_forbidden"]


def test_polytrace_ttl_refs_does_not_forward_slice(sim_report):
    pt = _rows(sim_report, "ttl-refs")["polytrace"]
    assert "app/services/jwt_service.py::JwtService.verify" not in pt["false_negatives"]
    assert "app/models/user.py::User.lookup" not in pt["false_positives_forbidden"]
    assert "app/middleware/auth.py::authenticate" not in pt["false_positives_forbidden"]


def test_polytrace_store_fetch_keeps_override(sim_report):
    pt = _rows(sim_report, "store-fetch")["polytrace"]
    assert pt["recall_must"] == 1.0, pt["false_negatives"]
    assert "app/models/user.py::User.lookup" not in pt["false_positives_forbidden"]


def test_polytrace_isolation_leaves(sim_report):
    for case_id in ("health-isolated", "session-isolated"):
        pt = _rows(sim_report, case_id)["polytrace"]
        assert pt["recall_must"] == 1.0, (case_id, pt["false_negatives"])
        assert pt["false_positives_forbidden"] == [], (case_id, pt)


def test_polytrace_auth_flow_still_recovers_generic_names(sim_report):
    pt = _rows(sim_report, "auth-flow")["polytrace"]
    assert pt["recall_must"] == 1.0, pt["false_negatives"]
    assert "app/billing/invoices.py::charge" not in pt["false_positives_forbidden"]
    assert "app/utils/logger.py::log" not in pt["false_positives_forbidden"]


def test_polytrace_job_run_follows_generic_execute(sim_report):
    pt = _rows(sim_report, "job-run")["polytrace"]
    assert pt["recall_must"] == 1.0, pt["false_negatives"]
    assert "app/jobs/digest.py::send_digest" not in pt["false_negatives"]
    assert "app/http/client.py::get" not in pt["false_positives_forbidden"]


def test_polytrace_jwt_midchain_does_not_walk_callers(sim_report):
    pt = _rows(sim_report, "jwt-verify-chain")["polytrace"]
    assert pt["recall_must"] == 1.0, pt["false_negatives"]
    assert "app/events/bus.py::emit" not in pt["false_positives_forbidden"]


def test_polytrace_resolve_does_not_include_authenticate(sim_report):
    pt = _rows(sim_report, "user-resolve-chain")["polytrace"]
    assert pt["recall_must"] == 1.0, pt["false_negatives"]
    assert "app/middleware/auth.py::authenticate" not in pt["false_positives_forbidden"]
    assert "app/utils/token.py::decode" not in pt["false_positives_forbidden"]

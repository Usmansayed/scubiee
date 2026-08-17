"""Tiering prevents routine CE verification from spending tokens on labs."""

from __future__ import annotations

import argparse

def test_quick_plan_contains_only_local_deterministic_checks(tmp_path) -> None:
    from pipeline.test_runner import build_test_plan

    plan = build_test_plan("quick", root=tmp_path)

    assert plan.tier == "quick"
    assert plan.requires_network is False
    assert plan.requires_external_client is False
    assert "tests/test_source_integrity.py" in plan.pytest_targets
    assert "tests/test_preflight.py" in plan.pytest_targets


def test_fault_and_client_tiers_are_opt_in(tmp_path) -> None:
    from pipeline.test_runner import build_test_plan

    fault = build_test_plan("fault", root=tmp_path)
    clients = build_test_plan("clients", root=tmp_path)

    assert fault.opt_in is True
    assert fault.requires_network is False
    assert clients.opt_in is True
    assert clients.requires_external_client is True


def test_run_plan_marks_missing_external_client_as_skipped(tmp_path) -> None:
    from pipeline.test_runner import TestPlan, run_plan

    plan = TestPlan(
        tier="clients",
        pytest_targets=("tests/test_sdk_mcp_smoke.py",),
        opt_in=True,
        requires_external_client=True,
    )
    report = run_plan(plan, root=tmp_path, external_client_available=False)

    assert report["ok"] is True
    assert report["status"] == "skipped"
    assert report["reason"] == "external_client_unavailable"


def test_cmd_test_prints_json_report(monkeypatch, tmp_path, capsys) -> None:
    from pipeline import __main__ as cli

    monkeypatch.setattr(
        "pipeline.test_runner.run_plan",
        lambda *_args, **_kwargs: {"ok": True, "status": "passed", "tier": "quick"},
    )
    rc = cli.cmd_test(argparse.Namespace(tier="quick", path=str(tmp_path), clients=False))

    assert rc == 0
    assert '"status": "passed"' in capsys.readouterr().out

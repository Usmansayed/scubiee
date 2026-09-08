"""End-to-end upgrade scenario tests (isolated CTX_HOME, mocked heavy I/O)."""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from conftest import enroll_test_repo
from pipeline.upgrade_manifest import build_diff_plan
from pipeline.upgrade_scenarios import (
    apply_stale_state,
    get_scenario,
    list_scenarios,
    plan_after_stale,
    verify_post_upgrade,
)


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    return path


@pytest.fixture
def enrolled_repo(tmp_path: Path, _isolate_scubiee_home: Path) -> tuple[Path, str]:
    repo = _git_repo(tmp_path / "managed-repo")
    pid = enroll_test_repo(repo, home=_isolate_scubiee_home)
    return repo, pid


@pytest.mark.parametrize("scenario", [s.id for s in list_scenarios()], ids=lambda x: x)
def test_stale_state_triggers_expected_plan(
    scenario: str,
    enrolled_repo: tuple[Path, str],
):
    repo, pid = enrolled_repo
    sc = get_scenario(scenario)
    plan_dict = plan_after_stale(scenario, repo, project_id=pid, version="0.3.10")
    actions = {a["component"]: a["action"] for a in plan_dict.get("actions") or []}
    for component in sc.expected_actions:
        assert actions.get(component) != "skip", (
            f"{scenario}: expected {component} to run, plan={plan_dict}"
        )


def test_stale_mcp_pins_plan_rewrite(enrolled_repo: tuple[Path, str]):
    repo, pid = enrolled_repo
    plan = plan_after_stale("stale_mcp_pins", repo, project_id=pid)
    mcp = next(a for a in plan["actions"] if a["component"] == "mcp_pins")
    assert mcp["action"] == "rewrite"


def test_embed_mismatch_plan_rebuild(enrolled_repo: tuple[Path, str]):
    repo, pid = enrolled_repo
    plan = plan_after_stale("embed_abi_mismatch", repo, project_id=pid)
    emb = next(a for a in plan["actions"] if a["component"] == "embeddings")
    assert emb["action"] == "rebuild"
    assert emb["destructive"] is True


def test_force_reindex_only_with_flag(enrolled_repo: tuple[Path, str]):
    repo, pid = enrolled_repo
    apply_stale_state("force_reindex", repo, project_id=pid, version="0.3.10")
    without = build_diff_plan(
        from_version="0.3.10",
        to_version="0.3.10",
        skip_package=True,
        force_reindex=False,
    )
    assert without.action_for("embeddings").action == "skip"  # type: ignore[union-attr]
    with_flag = build_diff_plan(
        from_version="0.3.10",
        to_version="0.3.10",
        skip_package=True,
        force_reindex=True,
    )
    assert with_flag.action_for("embeddings").action == "rebuild"  # type: ignore[union-attr]


def _mock_upgrade_supervisor(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    """Patch destructive upgrade phases for fast in-process runs."""
    import pipeline.upgrade_supervisor as sup

    monkeypatch.setattr(
        sup,
        "quiesce_for_upgrade",
        lambda: {"ok": True, "skipped": True},
    )
    monkeypatch.setattr(
        sup,
        "swap_package",
        lambda pre_release=False: {"ok": True, "skipped": True},
    )
    monkeypatch.setattr(
        sup,
        "ensure_daemon_after_upgrade",
        lambda: {"ok": True, "action": "restarted_after_upgrade"},
    )
    monkeypatch.setattr(
        sup,
        "health_check",
        lambda: {"ok": True, "mocked": True},
    )
    monkeypatch.setattr(
        sup,
        "rebuild_embeddings_if_needed",
        lambda plan: {"ok": True, "skipped": False, "reports": [], "mocked": True},
    )

    def _fake_repair() -> dict:
        from pipeline.project_id import context_engine_home

        accel = context_engine_home() / "accel.json"
        accel.parent.mkdir(parents=True, exist_ok=True)
        if not accel.is_file():
            accel.write_text("{}\n", encoding="utf-8")
        return {"ok": True, "profile": "cpu", "mocked": True}

    monkeypatch.setattr(sup, "maybe_setup_repair", _fake_repair)
    monkeypatch.setattr(
        "pipeline.upgrade.check_pypi_version",
        lambda force=False, timeout=5.0: {
            "current": "0.3.10",
            "latest": "0.3.10",
            "update_available": False,
        },
    )
    monkeypatch.setattr(
        "pipeline.mcp_hot_reload.nudge_mcp_hot_reload",
        lambda version: {"ok": True, "mocked": True},
    )
    monkeypatch.setattr("pipeline.upgrade.installed_version", lambda: "0.3.10")
    monkeypatch.chdir(repo)


@pytest.mark.parametrize(
    "scenario_id",
    [
        "stale_mcp_pins",
        "stale_gate_rules",
        "stale_index_schema",
        "missing_accel",
        "stale_home_layout",
        "legacy_mcp_command",
    ],
)
def test_mock_upgrade_repairs_scenario(
    scenario_id: str,
    enrolled_repo: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
):
    repo, pid = enrolled_repo
    sc = get_scenario(scenario_id)
    apply_stale_state(scenario_id, repo, project_id=pid, version="0.3.10")
    _mock_upgrade_supervisor(monkeypatch, repo)

    from pipeline.upgrade import do_upgrade

    report = do_upgrade(
        skip_package=True,
        connect=True,
        repair=bool(sc.upgrade_flags.get("repair")),
        reindex=bool(sc.upgrade_flags.get("reindex")),
    )
    assert report.get("ok") is True, report

    verify = verify_post_upgrade(
        scenario_id,
        repo,
        project_id=pid,
        version="0.3.10",
        report=report,
    )
    assert verify["ok"] is True, verify


def test_combined_surface_plan(enrolled_repo: tuple[Path, str]):
    repo, pid = enrolled_repo
    plan = plan_after_stale("combined_surface", repo, project_id=pid)
    active = {
        a["component"]
        for a in plan["actions"]
        if a["action"] != "skip"
    }
    assert "mcp_pins" in active
    assert "gate_rules" in active
    assert "index_schema" in active
    assert "accel" in active


def test_combined_mock_upgrade(
    enrolled_repo: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
):
    repo, pid = enrolled_repo
    apply_stale_state("combined_surface", repo, project_id=pid, version="0.3.10")
    _mock_upgrade_supervisor(monkeypatch, repo)

    from pipeline.upgrade import do_upgrade

    report = do_upgrade(skip_package=True, connect=True, repair=True)
    assert report.get("ok") is True
    verify = verify_post_upgrade(
        "combined_surface",
        repo,
        project_id=pid,
        version="0.3.10",
        report=report,
    )
    assert verify["ok"] is True, verify

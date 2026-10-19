"""Commands that used to fail or no-op silently now say what happened and what to do."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_scubiee_test_outside_a_source_checkout_is_unavailable(tmp_path: Path) -> None:
    from pipeline.test_runner import build_test_plan, run_plan

    report = run_plan(build_test_plan("quick", root=tmp_path), root=tmp_path)
    assert report["ok"] is False
    assert report["status"] == "unavailable"
    assert report["reason"] == "test_files_not_found"
    assert "scubiee doctor" in report["hint"]


def test_cmd_test_exits_2_with_hint_when_unavailable(tmp_path: Path, capsys) -> None:
    import argparse

    from pipeline.__main__ import cmd_test

    rc = cmd_test(argparse.Namespace(tier="quick", path=str(tmp_path), clients=False))
    assert rc == 2
    assert "source checkout" in capsys.readouterr().err


@pytest.fixture
def never_indexed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from conftest import enroll_test_repo

    from pipeline.repo_lifecycle import never_index_repo

    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    enroll_test_repo(repo, home=home, project_id="ce_neverindex1234567890abcdefab")
    never_index_repo(repo, reason="test")
    return repo


def test_register_refuses_a_never_index_repo(never_indexed: Path) -> None:
    from pipeline.registration import register_project
    from pipeline.repo_lifecycle import managed_state

    result = register_project(never_indexed, index=True)
    assert result.ok is False
    assert result.error == "never_index"
    assert "scubiee remove ." in (result.hint or "")
    assert managed_state(never_indexed) == "never_index"


def test_never_index_refusals_explain_how_to_undo(never_indexed: Path) -> None:
    from pipeline.repo_lifecycle import activate_repo, rebuild_repo, sync_now_repo

    for out in (activate_repo(never_indexed), rebuild_repo(never_indexed), sync_now_repo(never_indexed)):
        assert out["ok"] is False and out["error"] == "never_index"
        assert "scubiee init ." in out["hint"]

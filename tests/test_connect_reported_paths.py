"""connect/resume reports only paths that exist on disk (real-user journey #6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.rules_installer import install_tool
from pipeline.tool_registry import TOOL_MAP

from conftest import write_machine_setup


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    ce = tmp_path / "ce-home"
    ce.mkdir()
    write_machine_setup(ce)
    monkeypatch.setenv("CTX_HOME", str(ce))
    return home


def _enroll(repo: Path, pid: str) -> None:
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / ".scubiee").mkdir()
    (repo / ".scubiee" / "id.json").write_text(
        json.dumps({"project_id": pid}), encoding="utf-8"
    )
    from pipeline.project_id import load_registry, save_registry

    reg = load_registry() or {}
    reg.setdefault("projects", {})[pid] = {
        "managed": True,
        "root": str(repo.resolve()),
        "paths": [str(repo.resolve())],
    }
    save_registry(reg)


def _same(a: str, b: Path) -> bool:
    return Path(a).resolve() == b.resolve()


def test_connect_from_unrelated_cwd_reports_written_repo_paths(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "proj"
    _enroll(repo, "ce_reported_paths_1234567890ab")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    report = install_tool(TOOL_MAP["cursor"])

    assert report["ok"], report
    assert _same(report["mcp_path"], repo / ".cursor" / "mcp.json")
    assert all(Path(p).is_file() for p in report["mcp_paths"])
    assert report["rule_paths"], report
    assert all(Path(p).is_file() for p in report["rule_paths"])
    assert Path(report["rule_path"]).is_file()
    assert not str(report["rule_path"]).startswith(str(fake_home))
    assert not (elsewhere / ".cursor").exists()


def test_connect_with_no_enrolled_repo_reports_no_paths(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    report = install_tool(TOOL_MAP["cursor"])

    assert report["ok"], report
    assert report["mcp_path"] is None and report["mcp_paths"] == []
    assert report["rule_path"] is None and report["rule_paths"] == []
    assert report["notice"]


def test_dry_run_reports_would_write_paths_without_writing(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "proj"
    _enroll(repo, "ce_reported_dry_1234567890abcd")
    monkeypatch.chdir(tmp_path)

    report = install_tool(TOOL_MAP["cursor"], dry_run=True)

    assert _same(report["mcp_path"], repo / ".cursor" / "mcp.json")
    assert any(_same(p, repo / ".cursor" / "rules" / "scubiee.mdc") for p in report["rule_paths"])
    assert not (repo / ".cursor").exists()


def test_two_repos_listed_once_each(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    _enroll(a, "ce_reported_two_a_1234567890ab")
    _enroll(b, "ce_reported_two_b_1234567890ab")
    monkeypatch.chdir(tmp_path)

    report = install_tool(TOOL_MAP["cursor"])

    assert len(report["mcp_paths"]) == len(set(report["mcp_paths"])) == 2
    assert {Path(p).resolve() for p in report["mcp_paths"]} == {
        (a / ".cursor" / "mcp.json").resolve(),
        (b / ".cursor" / "mcp.json").resolve(),
    }


def test_resume_enable_lists_each_written_mcp_once(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "proj"
    _enroll(repo, "ce_reported_resume_1234567890a")
    monkeypatch.chdir(tmp_path)
    from pipeline.pause_resume import _enable_mcp_for_tool

    enabled = _enable_mcp_for_tool(TOOL_MAP["cursor"])

    assert len(enabled) == 1 and _same(enabled[0], repo / ".cursor" / "mcp.json")

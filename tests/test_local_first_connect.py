"""Local-first connect: global MCP + fan-out to enrolled repos."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.connect_state import (
    add_connected_tool,
    load_connected_tools,
    remove_connected_tool,
    save_connected_tools,
)
from pipeline.rules_installer import (
    apply_connected_tools_to_repo,
    install_tool,
    uninstall_tool,
    write_project_gate_rules,
)
from pipeline.tool_registry import TOOL_MAP

from conftest import write_machine_setup


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".git").mkdir()
    return path


def _enroll(repo: Path, pid: str, monkeypatch, tmp_path: Path) -> None:
    ce = repo / ".scubiee"
    ce.mkdir(exist_ok=True)
    (ce / "id.json").write_text(json.dumps({"project_id": pid}), encoding="utf-8")
    home = tmp_path / "ce-home"
    home.mkdir(exist_ok=True)
    write_machine_setup(home)
    monkeypatch.setenv("CTX_HOME", str(home))
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "paths": [str(repo.resolve())],
                }
            }
        }
    )


def test_connect_state_roundtrip(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    assert load_connected_tools() == []
    save_connected_tools(["cursor", "codex"])
    assert load_connected_tools() == ["cursor", "codex"]
    assert add_connected_tool("cursor") == ["cursor", "codex"]
    assert remove_connected_tool("cursor") == ["codex"]


def test_connect_fans_out_to_enrolled_repo(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "proj")
    pid = "ce_local_first1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)

    report = install_tool(TOOL_MAP["cursor"])
    assert report["ok"], report
    assert "cursor" in report["connected_tools"]
    fan = report["project_fan_out"]
    assert fan["repos"] == 1
    assert (repo / ".cursor" / "mcp.json").is_file()
    assert (repo / ".cursor" / "rules" / "scubiee.mdc").is_file()
    global_mcp = json.loads((repo / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    env = global_mcp["mcpServers"]["scubiee"]["env"]
    assert env["CTX_REPO"].replace("\\", "/") == str(repo.resolve()).replace("\\", "/")
    assert env["CTX_PROJECT_ID"] == pid
    assert not (fake_home / ".cursor" / "mcp.json").exists()


def test_init_applies_only_connected_tools(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path / "proj")
    pid = "ce_init_only_conn1234567890ab"
    _enroll(repo, pid, monkeypatch, tmp_path)
    home = tmp_path / "ce-home"
    home.mkdir(exist_ok=True)
    write_machine_setup(home)
    monkeypatch.setenv("CTX_HOME", str(home))
    save_connected_tools(["cursor"])

    skipped = apply_connected_tools_to_repo(repo)
    assert not skipped.get("skipped")
    assert (repo / ".cursor" / "mcp.json").is_file()
    assert (repo / ".codex").exists() is False


def test_init_skips_when_no_tools_connected(tmp_path: Path, monkeypatch) -> None:
    repo = _git_repo(tmp_path / "proj")
    pid = "ce_init_skip1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)
    home = tmp_path / "ce-home"
    home.mkdir(exist_ok=True)
    write_machine_setup(home)
    monkeypatch.setenv("CTX_HOME", str(home))
    save_connected_tools([])

    report = apply_connected_tools_to_repo(repo)
    assert report["skipped"]
    assert "no tools connected" in report["skip_reason"]


def test_unenrolled_repo_gets_no_files_on_connect(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    junk = _git_repo(tmp_path / "not-enrolled")
    monkeypatch.chdir(junk)
    home = tmp_path / "ce-home"
    home.mkdir()
    write_machine_setup(home)
    monkeypatch.setenv("CTX_HOME", str(home))
    save_connected_tools([])

    report = install_tool(TOOL_MAP["cursor"])
    assert report["ok"]
    assert report["project_fan_out"]["repos"] == 0
    assert not (junk / ".cursor" / "mcp.json").exists()


def test_disconnect_cleans_registry_repo_without_id_json(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    """Fan-out disconnect must work when user deleted repo-local .scubiee/."""
    repo = _git_repo(tmp_path / "proj")
    pid = "ce_no_id_json1234567890abcdef"
    home = tmp_path / "ce-home"
    home.mkdir(exist_ok=True)
    write_machine_setup(home)
    monkeypatch.setenv("CTX_HOME", str(home))
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "paths": [str(repo.resolve())],
                }
            }
        }
    )
    save_connected_tools(["cursor"])
    mcp = repo / ".cursor" / "mcp.json"
    mcp.parent.mkdir(parents=True)
    mcp.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "scubiee": {
                        "command": "x",
                        "env": {"CTX_REPO": str(repo.resolve()).replace("\\", "/")},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert not (repo / ".scubiee").exists()

    report = uninstall_tool(TOOL_MAP["cursor"], all_workspaces=True)
    assert report["ok"]
    assert report["project_fan_out"]["repos"] == 1
    assert not mcp.exists()


def test_connect_fans_out_mcp_to_registry_repo_without_id_json(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "proj")
    pid = "ce_conn_no_id1234567890abcdef"
    home = tmp_path / "ce-home"
    home.mkdir(exist_ok=True)
    write_machine_setup(home)
    monkeypatch.setenv("CTX_HOME", str(home))
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "paths": [str(repo.resolve())],
                }
            }
        }
    )
    report = install_tool(TOOL_MAP["cursor"])
    assert report["ok"]
    assert report["project_fan_out"]["repos"] == 1
    assert (repo / ".cursor" / "mcp.json").is_file()
    assert not (repo / ".cursor" / "rules" / "scubiee.mdc").exists()


def test_disconnect_all_workspaces_removes_project_files(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    repo = _git_repo(tmp_path / "proj")
    pid = "ce_disc_all1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)
    install_tool(TOOL_MAP["cursor"])
    write_project_gate_rules(repo, slugs=["cursor"])
    rule = repo / ".cursor" / "rules" / "scubiee.mdc"
    assert rule.is_file()

    report = uninstall_tool(TOOL_MAP["cursor"], all_workspaces=True)
    assert report["ok"]
    assert report["all_workspaces"] is True
    assert not rule.is_file()
    assert "cursor" not in load_connected_tools()


def test_init_reapplies_connected_tools_after_id_json_removed(
    tmp_path: Path, monkeypatch
) -> None:
    """Registry + connected_tools survive deleted .scubiee/; init restores rules."""
    repo = _git_repo(tmp_path / "proj")
    pid = "ce_reenroll1234567890abcdef"
    home = tmp_path / "ce-home"
    home.mkdir(exist_ok=True)
    write_machine_setup(home)
    monkeypatch.setenv("CTX_HOME", str(home))
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "paths": [str(repo.resolve())],
                }
            }
        }
    )
    save_connected_tools(["cursor"])
    install_tool(TOOL_MAP["cursor"])
    assert (repo / ".cursor" / "mcp.json").is_file()
    assert not (repo / ".cursor" / "rules" / "scubiee.mdc").exists()

    _enroll(repo, pid, monkeypatch, tmp_path)
    report = apply_connected_tools_to_repo(repo)
    assert report["ok"]
    assert not report.get("skipped")
    assert (repo / ".cursor" / "rules" / "scubiee.mdc").is_file()

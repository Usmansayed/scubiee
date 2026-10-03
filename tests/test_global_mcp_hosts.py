"""Project-local MCP hosts: env resolution and connect fan-out."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.host_workspace import (
    GLOBAL_MCP_TOOL_SLUGS,
    HOST_SPECS,
    SPECIAL_WORKSPACE_LOCAL_MCP_SLUGS,
    is_special_workspace_local_tool,
)
from pipeline.rules_installer import format_server_entry, install_tool, write_project_gate_rules
from pipeline.tool_registry import ALL_SLUGS, TOOL_MAP

from conftest import write_machine_setup


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
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


def test_all_hosts_are_project_local() -> None:
    assert GLOBAL_MCP_TOOL_SLUGS == frozenset()
    assert len(SPECIAL_WORKSPACE_LOCAL_MCP_SLUGS) == len(ALL_SLUGS)
    for slug in ALL_SLUGS:
        assert is_special_workspace_local_tool(slug)
        assert HOST_SPECS[slug].global_connect is False


@pytest.mark.parametrize("slug", sorted(ALL_SLUGS))
def test_project_connect_fans_out_to_enrolled_repo(
    slug: str, fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    workspace = _git_repo(tmp_path / f"ws-{slug}")
    pid = f"ce_{slug.replace('-', '_')[:20]}1234567890ab"
    _enroll(workspace, pid, monkeypatch, tmp_path)
    report = install_tool(TOOL_MAP[slug], repo=workspace)
    assert report["ok"], report
    assert report.get("scope") == "project-local"
    assert report["project_fan_out"]["repos"] == 1
    entry = format_server_entry(TOOL_MAP[slug], workspace, pin_repo=True)
    env = entry.get("env") or entry.get("environment") or {}
    assert env.get("CTX_MCP_CLIENT") == slug
    assert env.get("CTX_REPO", "").replace("\\", "/") == str(workspace.resolve()).replace("\\", "/")


@pytest.mark.parametrize("slug", sorted(ALL_SLUGS))
def test_init_writes_project_rules(
    slug: str, tmp_path: Path, monkeypatch
) -> None:
    tool = TOOL_MAP[slug]
    if tool.rule_format == "none":
        pytest.skip(f"{slug} has no project rules file")
    repo = _git_repo(tmp_path / f"init-{slug}")
    pid = f"ce_global_{slug.replace('-', '_')[:20]}1234567890ab"
    _enroll(repo, pid, monkeypatch, tmp_path)
    report = write_project_gate_rules(repo, slugs=[slug])
    assert report["ok"]
    assert report["written"]
    if tool.rule_user_path:
        assert (repo / tool.rule_user_path).is_file()


# NOTE: the per-host env-key repo-resolution tests that lived here exercised
# ``mcp_locate._default_repo`` / ``_is_repo_managed`` — a resolution path that was
# retired in the Map V3 migration. Map V3 (``pipeline.map_v3_server``) resolves the
# repo from CTX_REPO / MINI_REPO, not the IDE host env-key fan-out, so those cases
# no longer map to live production code. They were removed with the old surface.
# See archive/old-mcp-map/ for the retired tool and its original tests.

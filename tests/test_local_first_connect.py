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


def test_connect_first_notice_when_no_repo_enrolled(
    fake_home: Path, tmp_path: Path, monkeypatch
) -> None:
    """Connect with zero enrolled repos must surface an actionable notice, not a
    silent no-op: the tool is recorded machine-wide and `init` will apply it."""
    home = tmp_path / "ce-home"
    home.mkdir()
    write_machine_setup(home)
    monkeypatch.setenv("CTX_HOME", str(home))
    save_connected_tools([])

    report = install_tool(TOOL_MAP["cursor"])
    assert report["ok"], report
    # Recorded machine-wide even though nothing was applied locally.
    assert "cursor" in report["connected_tools"]
    assert report["project_fan_out"]["repos"] == 0
    assert report.get("repos_applied") == 0
    # The actionable notice is present and points at init.
    notice = (report.get("notice") or "").lower()
    assert notice, "connect-first should surface a notice"
    assert "init" in notice
    assert "machine" in notice


def test_connect_then_init_is_universal_across_tools(
    tmp_path: Path, monkeypatch
) -> None:
    """connect-once (record) then init (apply) must work for every supported tool,
    not just cursor — the project MCP file lands for each connected slug."""
    from pipeline.tool_registry import ALL_SLUGS, TOOL_MAP as TM
    from pipeline.tool_registry import resolve_mcp_project_paths

    repo = _git_repo(tmp_path / "proj")
    pid = "ce_universal1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)
    home = tmp_path / "ce-home"
    home.mkdir(exist_ok=True)
    write_machine_setup(home)
    monkeypatch.setenv("CTX_HOME", str(home))

    # Record EVERY tool machine-wide (connect once).
    save_connected_tools(list(ALL_SLUGS))

    # A single init must apply all of them.
    report = apply_connected_tools_to_repo(repo)
    assert report["ok"], report
    assert not report.get("skipped"), report
    assert sorted(report["connected_tools"]) == sorted(ALL_SLUGS)

    # Every tool's project MCP path should now exist under the repo.
    missing = []
    for slug in ALL_SLUGS:
        tool = TM[slug]
        paths = resolve_mcp_project_paths(tool, repo)
        if paths and not any(p.is_file() for p in paths):
            missing.append(slug)
    assert not missing, f"init did not apply MCP for: {missing}"


# ---------------------------------------------------------------------------
# Reliability hardening: the connect-once promise must survive corruption,
# partial writes, bad slugs, and per-tool failures.
# ---------------------------------------------------------------------------

def _ce_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "ce-home"
    home.mkdir(exist_ok=True)
    write_machine_setup(home)
    monkeypatch.setenv("CTX_HOME", str(home))
    return home


def test_connected_tools_atomic_write_and_bak_recovery(tmp_path: Path, monkeypatch) -> None:
    """A torn/corrupt primary must self-heal from the .bak snapshot, not reset
    the user's connections to empty (that would silently break connect-once)."""
    from pipeline import connect_state as cs

    _ce_home(tmp_path, monkeypatch)
    cs.save_connected_tools(["cursor", "kiro"])
    cs.save_connected_tools(["cursor", "kiro", "codex"])  # .bak now = [cursor,kiro]
    assert cs.load_connected_tools() == ["cursor", "kiro", "codex"]

    # Simulate an interrupted write: truncated JSON in the primary file.
    cs._state_path().write_text('{"slugs": ["cur', encoding="utf-8")
    recovered = cs.load_connected_tools()
    assert recovered == ["cursor", "kiro"], recovered  # recovered from .bak
    # Primary was healed back to valid JSON.
    assert json.loads(cs._state_path().read_text(encoding="utf-8"))["slugs"] == [
        "cursor",
        "kiro",
    ]


def test_connected_tools_corrupt_both_is_empty_not_crash(tmp_path: Path, monkeypatch) -> None:
    from pipeline import connect_state as cs

    _ce_home(tmp_path, monkeypatch)
    cs._state_path().write_text("not json at all", encoding="utf-8")
    cs._backup_path().write_text("also broken {", encoding="utf-8")
    assert cs.load_connected_tools() == []  # safe-empty, never raises


def test_connected_tools_empty_primary_is_honored(tmp_path: Path, monkeypatch) -> None:
    """A genuinely-empty primary must NOT be overridden by a stale .bak."""
    from pipeline import connect_state as cs

    _ce_home(tmp_path, monkeypatch)
    cs.save_connected_tools(["cursor"])
    cs.save_connected_tools([])  # user disconnected everything
    assert cs.load_connected_tools() == []


def test_add_remove_canonicalizes_alias_and_dedups(tmp_path: Path, monkeypatch) -> None:
    from pipeline import connect_state as cs

    _ce_home(tmp_path, monkeypatch)
    # windsurf is an alias for devin-desktop; both forms must collapse to one.
    cs.add_connected_tool("windsurf")
    cs.add_connected_tool("devin-desktop")
    assert cs.load_connected_tools() == ["devin-desktop"]
    cs.remove_connected_tool("windsurf")
    assert cs.load_connected_tools() == []


def test_init_apply_isolates_a_failing_tool(tmp_path: Path, monkeypatch) -> None:
    """If one connected tool's apply raises, the others must still be applied."""
    import pipeline.rules_installer as ri

    repo = _git_repo(tmp_path / "proj")
    pid = "ce_isolate1234567890abcdef00"
    _enroll(repo, pid, monkeypatch, tmp_path)
    _ce_home(tmp_path, monkeypatch)
    save_connected_tools(["cursor", "kiro"])

    real = ri.write_project_tool_surface

    def flaky(root, tool, *, dry_run=False):
        if tool.slug == "cursor":
            raise RuntimeError("boom: simulated cursor failure")
        return real(root, tool, dry_run=dry_run)

    monkeypatch.setattr(ri, "write_project_tool_surface", flaky)

    report = ri.apply_connected_tools_to_repo(repo)
    # The failing tool is recorded as an error but does NOT abort the apply:
    assert any("cursor" in e for e in report["errors"]), report["errors"]
    # kiro still got applied.
    assert "kiro" in report.get("applied_tools", [])
    assert (repo / ".kiro" / "settings" / "mcp.json").is_file()


def test_double_init_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    """Running init twice must not corrupt or duplicate the applied config."""
    repo = _git_repo(tmp_path / "proj")
    pid = "ce_idem1234567890abcdef0000"
    _enroll(repo, pid, monkeypatch, tmp_path)
    _ce_home(tmp_path, monkeypatch)
    save_connected_tools(["cursor"])

    r1 = apply_connected_tools_to_repo(repo)
    assert r1["ok"], r1
    mcp = repo / ".cursor" / "mcp.json"
    first = mcp.read_text(encoding="utf-8")
    r2 = apply_connected_tools_to_repo(repo)
    assert r2["ok"], r2
    second = mcp.read_text(encoding="utf-8")
    # Single scubiee server entry, stable across re-apply.
    data = json.loads(second)
    assert list(data["mcpServers"].keys()) == ["scubiee"]
    assert json.loads(first)["mcpServers"].keys() == data["mcpServers"].keys()

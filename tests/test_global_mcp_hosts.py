"""Global MCP hosts (non special-4): connect, schema, workspace resolution.

Special-4 (Kiro, Copilot, Cline, Roo) are excluded — they need project-level MCP.
See docs/global-mcp-hosts-research.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.host_workspace import (
    GLOBAL_MCP_TOOL_SLUGS,
    HOST_SPECS,
    SPECIAL_WORKSPACE_LOCAL_MCP_SLUGS,
    ide_workspace_env_keys,
    is_global_mcp_tool,
)
from pipeline.rules_installer import format_server_entry, install_tool, write_project_gate_rules
from pipeline.tool_registry import TOOL_MAP

# One primary workspace env key per global host (for resolution tests).
GLOBAL_HOST_WORKSPACE_ENV: dict[str, str] = {
    "cursor": "CURSOR_PROJECT_DIR",
    "claude-code": "CLAUDE_PROJECT_DIR",
    "codex": "CODEX_WORKSPACE_ROOT",
    "windsurf": "WINDSURF_WORKSPACE",
    "continue": "CONTINUE_PROJECT_DIR",
    "zed": "ZED_PROJECT_DIR",
    "opencode": "OPENCODE_DEFAULT_PROJECT",
    "amp": "AMP_PROJECT_DIR",
    "pi": "PI_PROJECT_DIR",
}

_CLEAR_ALL_IDE = tuple(ide_workspace_env_keys()) + (
    "CTX_REPO",
    "CTX_PROJECT_ID",
    "CONTEXT_ENGINE_REPO",
)


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


def test_global_vs_special_four_partition() -> None:
    assert len(GLOBAL_MCP_TOOL_SLUGS) == 9
    assert SPECIAL_WORKSPACE_LOCAL_MCP_SLUGS == frozenset(
        {"kiro", "copilot", "cline", "roo-code"}
    )
    assert GLOBAL_MCP_TOOL_SLUGS & SPECIAL_WORKSPACE_LOCAL_MCP_SLUGS == frozenset()
    for slug in GLOBAL_MCP_TOOL_SLUGS:
        assert slug in TOOL_MAP
        assert is_global_mcp_tool(slug)
        assert HOST_SPECS[slug].global_connect is True
    for slug in SPECIAL_WORKSPACE_LOCAL_MCP_SLUGS:
        assert HOST_SPECS[slug].global_connect is False


@pytest.mark.parametrize("slug", sorted(GLOBAL_MCP_TOOL_SLUGS))
def test_global_connect_writes_mcp_only_no_ctx_repo(
    slug: str, fake_home: Path, tmp_path: Path
) -> None:
    workspace = _git_repo(tmp_path / f"ws-{slug}")
    report = install_tool(TOOL_MAP[slug], repo=workspace)
    assert report["ok"], report
    assert report.get("scope") == "global"
    assert not report.get("workspace_mcp_written")
    assert report.get("rule_written") is None
    entry = format_server_entry(TOOL_MAP[slug], pin_repo=False)
    env = entry.get("env") or entry.get("environment") or {}
    assert "CTX_REPO" not in env
    assert env.get("CTX_MCP_CLIENT") == slug


@pytest.mark.parametrize("slug", sorted(GLOBAL_MCP_TOOL_SLUGS))
def test_global_init_writes_project_rules(
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


@pytest.mark.parametrize("slug", sorted(GLOBAL_MCP_TOOL_SLUGS))
def test_global_host_workspace_env_resolves_repo(
    slug: str, tmp_path: Path, monkeypatch
) -> None:
    from pipeline import mcp_locate

    opened = _git_repo(tmp_path / f"opened-{slug}")
    pid = f"ce_res_{slug.replace('-', '_')[:16]}1234567890abcd"
    _enroll(opened, pid, monkeypatch, tmp_path)
    junk = tmp_path / "spawn"
    junk.mkdir()
    monkeypatch.chdir(junk)
    env_key = GLOBAL_HOST_WORKSPACE_ENV[slug]
    monkeypatch.setenv(env_key, str(opened))
    for key in _CLEAR_ALL_IDE:
        if key != env_key:
            monkeypatch.delenv(key, raising=False)
    assert mcp_locate._default_repo() == opened.resolve()
    assert mcp_locate._is_repo_managed() is True


@pytest.mark.parametrize(
    ("slug", "env_key"),
    [(s, GLOBAL_HOST_WORKSPACE_ENV[s]) for s in sorted(GLOBAL_MCP_TOOL_SLUGS)],
)
def test_detect_mcp_host_global_tools(
    monkeypatch: pytest.MonkeyPatch, slug: str, env_key: str
) -> None:
    monkeypatch.delenv("CTX_MCP_CLIENT", raising=False)
    for key in ide_workspace_env_keys():
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(env_key, "/tmp/project")
    from pipeline.session_isolation import detect_mcp_host

    assert detect_mcp_host() == slug


def test_windsurf_alternate_env_key(tmp_path: Path, monkeypatch) -> None:
    from pipeline import mcp_locate

    opened = _git_repo(tmp_path / "windsurf-ws")
    junk = tmp_path / "spawn"
    junk.mkdir()
    monkeypatch.chdir(junk)
    monkeypatch.setenv("CODEIUM_WINDSURF_WORKSPACE", str(opened))
    for key in _CLEAR_ALL_IDE:
        if key != "CODEIUM_WINDSURF_WORKSPACE":
            monkeypatch.delenv(key, raising=False)
    assert mcp_locate._default_repo() == opened.resolve()


def test_claude_code_alt_env_key(tmp_path: Path, monkeypatch) -> None:
    from pipeline import mcp_locate

    opened = _git_repo(tmp_path / "claude-ws")
    junk = tmp_path / "spawn"
    junk.mkdir()
    monkeypatch.chdir(junk)
    monkeypatch.setenv("CLAUDE_CODE_PROJECT_DIR", str(opened))
    for key in _CLEAR_ALL_IDE:
        if key != "CLAUDE_CODE_PROJECT_DIR":
            monkeypatch.delenv(key, raising=False)
    assert mcp_locate._default_repo() == opened.resolve()


def test_opencode_alt_env_key(tmp_path: Path, monkeypatch) -> None:
    from pipeline import mcp_locate

    opened = _git_repo(tmp_path / "opencode-ws")
    junk = tmp_path / "spawn"
    junk.mkdir()
    monkeypatch.chdir(junk)
    monkeypatch.setenv("OPENCODE_PROJECT", str(opened))
    for key in _CLEAR_ALL_IDE:
        if key != "OPENCODE_PROJECT":
            monkeypatch.delenv(key, raising=False)
    assert mcp_locate._default_repo() == opened.resolve()


def test_global_tool_cwd_fallback_when_chdir_is_repo(
    tmp_path: Path, monkeypatch
) -> None:
    """Hosts that spawn MCP with project cwd (Codex CLI, Pi, Zed project scope)."""
    from pipeline import mcp_locate

    repo = _git_repo(tmp_path / "cwd-ws")
    pid = "ce_cwd_fallback1234567890abcdef"
    _enroll(repo, pid, monkeypatch, tmp_path)
    monkeypatch.chdir(repo)
    for key in _CLEAR_ALL_IDE:
        monkeypatch.delenv(key, raising=False)
    assert mcp_locate._default_repo() == repo.resolve()
    assert mcp_locate._is_repo_managed() is True

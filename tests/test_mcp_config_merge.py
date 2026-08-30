"""MCP config merge safety: preserve user servers, refuse corrupt files."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.branding import MCP_SERVER_NAME
from pipeline.rules_installer import (
    MCPConfigMergeError,
    _is_continue_project_mcp,
    _remove_mcp_json_keyed,
    _write_continue_project_mcp,
    _write_mcp_json_keyed,
    format_server_entry,
    remove_mcp_config,
    write_mcp_config,
)
from pipeline.tool_registry import ALL_SLUGS, TOOL_MAP, resolve_mcp_project_write_targets

OTHER = "my-local-mcp"
OTHER_STDIO = {"command": "node", "args": ["server.js"]}


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _seed_json(path: Path, key: str, schema: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if schema == "amp":
        data: dict = {"amp.mcpServers": {OTHER: OTHER_STDIO}}
    elif schema == "zed":
        data = {"context_servers": {OTHER: {"command": "node", "args": []}}}
    elif schema == "opencode":
        data = {
            "$schema": "https://opencode.ai/config.json",
            "mcp": {
                OTHER: {
                    "type": "local",
                    "enabled": True,
                    "command": ["node", "other.js"],
                }
            },
        }
    elif schema == "vscode":
        data = {"servers": {OTHER: {"type": "stdio", "command": "node", "args": ["x.js"]}}}
    else:
        data = {key: {OTHER: OTHER_STDIO}}
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _seed_codex(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '[model]\nname = "gpt-4"\n\n'
        "[mcp_servers.other]\n"
        'command = "node"\n'
        'args = ["other.js"]\n',
        encoding="utf-8",
    )


def _assert_valid_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _servers_dict(data: dict, schema: str, key: str) -> dict:
    if schema == "amp":
        return data["amp.mcpServers"]
    if schema == "zed":
        return data["context_servers"]
    if schema == "opencode":
        mcp = data.get("mcp", {})
        if isinstance(mcp.get("servers"), dict):
            return mcp["servers"]
        return mcp
    return data[key]


@pytest.mark.parametrize("slug", ALL_SLUGS)
def test_write_remove_roundtrip_preserves_other_servers(tmp_path: Path, slug: str) -> None:
    tool = TOOL_MAP[slug]
    repo = _repo(tmp_path)
    entry = format_server_entry(tool, repo, pin_repo=True)

    for path, schema, key in resolve_mcp_project_write_targets(tool, repo):
        before_text: str | None = None

        if schema == "codex":
            _seed_codex(path)
            before_text = path.read_text(encoding="utf-8")
            write_mcp_config(tool, path, entry, schema=schema, key=key)
            text = path.read_text(encoding="utf-8")
            assert "[model]" in text
            assert f"[mcp_servers.{MCP_SERVER_NAME}]" in text
            assert "[mcp_servers.other]" in text
            assert remove_mcp_config(tool, path, schema=schema, key=key) is True
            after = path.read_text(encoding="utf-8")
            assert f"mcp_servers.{MCP_SERVER_NAME}" not in after
            assert "[mcp_servers.other]" in after
            assert "[model]" in after
            continue

        if schema == "continue" and _is_continue_project_mcp(path):
            _write_continue_project_mcp(path, entry)
            assert path.is_file()
            assert MCP_SERVER_NAME in path.read_text(encoding="utf-8").lower()
            assert remove_mcp_config(tool, path, schema=schema, key=key) is True
            assert not path.exists()
            continue

        _seed_json(path, key, schema)
        before_text = path.read_text(encoding="utf-8")
        write_mcp_config(tool, path, entry, schema=schema, key=key)

        data = _assert_valid_json(path)
        servers = _servers_dict(data, schema, key)
        assert MCP_SERVER_NAME in servers
        assert OTHER in servers

        assert remove_mcp_config(tool, path, schema=schema, key=key) is True
        if path.is_file():
            after = _assert_valid_json(path)
            servers_after = _servers_dict(after, schema, key)
            assert MCP_SERVER_NAME not in servers_after
            assert OTHER in servers_after
        else:
            # File removed only when scubiee was the sole content — should not happen here.
            assert OTHER in before_text


def test_write_refuses_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    corrupt = "{ not valid json"
    path.write_text(corrupt, encoding="utf-8")
    entry = {"command": "python", "args": ["-m", "x"]}

    with pytest.raises(MCPConfigMergeError, match="invalid JSON"):
        _write_mcp_json_keyed(path, "mcpServers", entry)

    assert path.read_text(encoding="utf-8") == corrupt


def test_write_refuses_non_object_json_root(tmp_path: Path) -> None:
    path = tmp_path / "mcp.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    entry = {"command": "python", "args": ["-m", "x"]}

    with pytest.raises(MCPConfigMergeError, match="JSON object"):
        _write_mcp_json_keyed(path, "mcpServers", entry)

    assert path.read_text(encoding="utf-8") == "[1, 2, 3]"


def test_remove_skips_invalid_json(tmp_path: Path) -> None:
    from pipeline.rules_installer import _remove_mcp_json_keyed

    path = tmp_path / "mcp.json"
    corrupt = "{ broken"
    path.write_text(corrupt, encoding="utf-8")
    warnings: list[dict[str, str]] = []

    assert _remove_mcp_json_keyed(path, "mcpServers", warnings=warnings) is False
    assert path.read_text(encoding="utf-8") == corrupt
    assert len(warnings) == 1
    assert "invalid JSON" in warnings[0]["reason"]


def test_pause_reports_corrupt_mcp_skip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from conftest import enroll_test_repo, write_machine_setup

    from pipeline.connect_state import add_connected_tool
    from pipeline.pause_resume import pause

    ce_home = tmp_path / "ce-home"
    write_machine_setup(ce_home)
    monkeypatch.setenv("CTX_HOME", str(ce_home))

    repo = tmp_path / "ws"
    repo.mkdir()
    (repo / ".git").mkdir()
    enroll_test_repo(repo, home=ce_home)

    mcp = repo / ".cursor" / "mcp.json"
    mcp.parent.mkdir(parents=True)
    mcp.write_text("{ not-valid scubiee\n", encoding="utf-8")

    add_connected_tool("cursor")

    with patch("pipeline.daemon.stop_daemon", return_value={"ok": True}), \
         patch("pipeline.watchdog.stop_watchdog", return_value={"ok": True}), \
         patch("pipeline.lifecycle_runtime.set_desired_mode"):
        result = pause()

    assert result.get("mcp_skipped")
    assert any("invalid JSON" in (e.get("reason") or "") for e in result["mcp_skipped"])


def test_write_merges_into_empty_file(tmp_path: Path) -> None:
    path = tmp_path / ".cursor" / "mcp.json"
    entry = {"command": "python", "args": ["-m", "pipeline.mcp_locate"], "env": {}}

    _write_mcp_json_keyed(path, "mcpServers", entry)
    data = _assert_valid_json(path)
    assert MCP_SERVER_NAME in data["mcpServers"]


def test_copilot_dual_paths_independent(tmp_path: Path) -> None:
    tool = TOOL_MAP["copilot"]
    repo = _repo(tmp_path)
    vscode = repo / ".vscode" / "mcp.json"
    root_mcp = repo / ".mcp.json"

    _seed_json(vscode, "servers", "vscode")
    _seed_json(root_mcp, "mcpServers", "claude")

    vscode_entry = format_server_entry(tool, repo, pin_repo=True, schema="vscode")
    claude_entry = format_server_entry(tool, repo, pin_repo=True, schema="claude")
    write_mcp_config(tool, vscode, vscode_entry, schema="vscode", key="servers")
    write_mcp_config(tool, root_mcp, claude_entry, schema="claude", key="mcpServers")

    vscode_data = _assert_valid_json(vscode)
    root_data = _assert_valid_json(root_mcp)
    assert MCP_SERVER_NAME in vscode_data["servers"]
    assert OTHER in vscode_data["servers"]
    assert MCP_SERVER_NAME in root_data["mcpServers"]
    assert OTHER in root_data["mcpServers"]

    assert remove_mcp_config(tool, vscode, schema="vscode", key="servers") is True
    assert remove_mcp_config(tool, root_mcp, schema="claude", key="mcpServers") is True

    vscode_after = _assert_valid_json(vscode)
    root_after = _assert_valid_json(root_mcp)
    assert MCP_SERVER_NAME not in vscode_after["servers"]
    assert OTHER in vscode_after["servers"]
    assert MCP_SERVER_NAME not in root_after["mcpServers"]
    assert OTHER in root_after["mcpServers"]


def test_opencode_v1_flat_schema_roundtrip(tmp_path: Path) -> None:
    tool = TOOL_MAP["opencode"]
    repo = _repo(tmp_path)
    path = repo / "opencode.json"
    _seed_json(path, "mcp", "opencode")
    entry = format_server_entry(tool, repo, pin_repo=True)

    write_mcp_config(tool, path, entry, schema="opencode", key="mcp")
    data = _assert_valid_json(path)
    assert isinstance(data["mcp"].get("servers"), dict) is False
    assert MCP_SERVER_NAME in data["mcp"]
    assert OTHER in data["mcp"]
    assert "enabled" in data["mcp"][MCP_SERVER_NAME]

    assert remove_mcp_config(tool, path, schema="opencode", key="mcp") is True
    after = _assert_valid_json(path)
    assert MCP_SERVER_NAME not in after["mcp"]
    assert OTHER in after["mcp"]


def test_opencode_v2_servers_schema_roundtrip(tmp_path: Path) -> None:
    tool = TOOL_MAP["opencode"]
    repo = _repo(tmp_path)
    path = repo / "opencode.json"
    path.write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "mcp": {
                    "servers": {
                        OTHER: {
                            "type": "local",
                            "disabled": False,
                            "command": ["node", "other.js"],
                        }
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    entry = format_server_entry(tool, repo, pin_repo=True)

    write_mcp_config(tool, path, entry, schema="opencode", key="mcp")
    data = _assert_valid_json(path)
    servers = data["mcp"]["servers"]
    assert MCP_SERVER_NAME in servers
    assert OTHER in servers
    assert "disabled" in servers[MCP_SERVER_NAME]
    assert "enabled" not in servers[MCP_SERVER_NAME]

    assert remove_mcp_config(tool, path, schema="opencode", key="mcp") is True
    after = _assert_valid_json(path)
    assert MCP_SERVER_NAME not in after["mcp"]["servers"]
    assert OTHER in after["mcp"]["servers"]


def test_opencode_fresh_file_uses_v2_schema(tmp_path: Path) -> None:
    tool = TOOL_MAP["opencode"]
    repo = _repo(tmp_path)
    path = repo / "opencode.json"
    entry = format_server_entry(tool, repo, pin_repo=True)

    write_mcp_config(tool, path, entry, schema="opencode", key="mcp")
    data = _assert_valid_json(path)
    assert isinstance(data["mcp"]["servers"], dict)
    assert MCP_SERVER_NAME in data["mcp"]["servers"]
    assert "disabled" in data["mcp"]["servers"][MCP_SERVER_NAME]


def test_copilot_remove_workspace_mcp_dotfile_name(tmp_path: Path) -> None:
    """Root ``.mcp.json`` has path.name ``.mcp.json`` (not ``mcp.json``)."""
    from pipeline.rules_installer import _remove_workspace_mcp, write_mcp_config

    tool = TOOL_MAP["copilot"]
    repo = _repo(tmp_path)
    vscode = repo / ".vscode" / "mcp.json"
    root_mcp = repo / ".mcp.json"
    _seed_json(vscode, "servers", "vscode")
    _seed_json(root_mcp, "mcpServers", "claude")
    write_mcp_config(
        tool,
        vscode,
        format_server_entry(tool, repo, pin_repo=True, schema="vscode"),
        schema="vscode",
        key="servers",
    )
    write_mcp_config(
        tool,
        root_mcp,
        format_server_entry(tool, repo, pin_repo=True, schema="claude"),
        schema="claude",
        key="mcpServers",
    )
    assert _remove_workspace_mcp(tool, repo) is True
    assert MCP_SERVER_NAME not in _assert_valid_json(vscode)["servers"]
    assert OTHER in _assert_valid_json(vscode)["servers"]
    assert MCP_SERVER_NAME not in _assert_valid_json(root_mcp)["mcpServers"]
    assert OTHER in _assert_valid_json(root_mcp)["mcpServers"]

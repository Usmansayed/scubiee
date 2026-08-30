"""Stop must surgically remove Scubiee MCP/rules for every supported tool."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline.tool_registry import ALL_SLUGS, TOOL_MAP


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    return home


def test_pause_teardowns_every_tool_in_registry(ce_home: Path) -> None:
    from pipeline.pause_resume import pause

    seen: list[str] = []

    def fake_teardown_all() -> list[dict]:
        seen.extend(tool.slug for tool in TOOL_MAP.values())
        return [{"slug": s} for s in seen]

    with patch("pipeline.pause_resume._detect_connected_tools", return_value=["cursor"]), \
         patch("pipeline.pause_resume._teardown_all_tool_surfaces", side_effect=fake_teardown_all), \
         patch("pipeline.pause_resume._strip_agents_md_all_repos", return_value=[]), \
         patch("pipeline.pause_resume._hide_repo_scubiee_dirs", return_value=[]), \
         patch("pipeline.daemon.stop_daemon", return_value={"ok": True}), \
         patch("pipeline.watchdog.stop_watchdog", return_value={"ok": True}), \
         patch("pipeline.lifecycle_runtime.set_desired_mode"):
        pause()

    assert set(seen) == set(ALL_SLUGS)


def test_remove_continue_project_yaml_only(tmp_path: Path) -> None:
    from pipeline.rules_installer import remove_mcp_config
    from pipeline.tool_registry import TOOL_MAP

    path = tmp_path / ".continue" / "mcpServers" / "scubiee.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("name: Scubiee\nmcpServers:\n  - name: scubiee\n", encoding="utf-8")

    assert remove_mcp_config(TOOL_MAP["continue"], path, schema="continue") is True
    assert not path.exists()


def test_remove_continue_global_yaml_preserves_other_servers(tmp_path: Path) -> None:
    from pipeline.rules_installer import remove_mcp_config
    from pipeline.tool_registry import TOOL_MAP

    path = tmp_path / "config.yaml"
    path.write_text(
        "models:\n  - name: gpt-4\n"
        "mcpServers:  # scubiee\n"
        '  - name: scubiee\n    command: "python"\n    args: ["-m", "x"]\n',
        encoding="utf-8",
    )

    assert remove_mcp_config(TOOL_MAP["continue"], path, schema="continue") is True
    text = path.read_text(encoding="utf-8")
    assert "gpt-4" in text
    assert "scubiee" not in text.lower() or "# scubiee" not in text


def test_remove_opencode_preserves_other_mcp(tmp_path: Path) -> None:
    from pipeline.rules_installer import remove_mcp_config
    from pipeline.tool_registry import TOOL_MAP

    path = tmp_path / "opencode.json"
    path.write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "scubiee": {"type": "local", "enabled": True, "command": ["python", "-m", "x"]},
            "other": {"type": "local", "enabled": True, "command": ["node", "y.js"]},
        },
    }, indent=2), encoding="utf-8")

    assert remove_mcp_config(TOOL_MAP["opencode"], path) is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "scubiee" not in data["mcp"]
    assert "other" in data["mcp"]


def test_remove_opencode_v2_preserves_other_mcp(tmp_path: Path) -> None:
    from pipeline.rules_installer import remove_mcp_config
    from pipeline.tool_registry import TOOL_MAP

    path = tmp_path / "opencode.json"
    path.write_text(json.dumps({
        "$schema": "https://opencode.ai/config.json",
        "mcp": {
            "servers": {
                "scubiee": {
                    "type": "local",
                    "disabled": False,
                    "command": ["python", "-m", "x"],
                },
                "other": {
                    "type": "local",
                    "disabled": False,
                    "command": ["node", "y.js"],
                },
            }
        },
    }, indent=2), encoding="utf-8")

    assert remove_mcp_config(TOOL_MAP["opencode"], path) is True
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "scubiee" not in data["mcp"]["servers"]
    assert "other" in data["mcp"]["servers"]


def test_remove_codex_toml_preserves_other_sections(tmp_path: Path) -> None:
    from pipeline.rules_installer import remove_mcp_config
    from pipeline.tool_registry import TOOL_MAP

    path = tmp_path / "config.toml"
    path.write_text(
        '[model]\nname = "gpt-5"\n\n'
        "[mcp_servers.scubiee]\n"
        'command = "python"\n'
        'args = ["-m", "pipeline.mcp_locate"]\n',
        encoding="utf-8",
    )

    assert remove_mcp_config(TOOL_MAP["codex"], path, schema="codex") is True
    text = path.read_text(encoding="utf-8")
    assert "[model]" in text
    assert "mcp_servers.scubiee" not in text


@pytest.fixture
def ce_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    return home

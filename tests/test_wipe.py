"""wipe --all requires --yes; repo wipe removes id + store."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.wipe import audit_scubiee_artifacts, wipe, wipe_all, wipe_repo


def test_wipe_all_requires_yes(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    out = wipe_all(yes=False)
    assert out["ok"] is False
    assert out["error"] == "confirm_required"
    assert "--confirm" in out["hint"]
    assert home.is_dir()


def test_wipe_all_confirm_alias_via_dispatch(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    from pipeline.wipe import wipe

    out = wipe(all=True, yes=True, models=False, package=False)
    assert out["scope"] == "all"
    assert not home.exists()


def test_wipe_all_yes_removes_home(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    (home / "projects" / "ce_x").mkdir(parents=True)
    (home / "prefs.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CTX_HOME", str(home))

    fake_user = tmp_path / "fake-user"
    (fake_user / ".cursor").mkdir(parents=True)
    (fake_user / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"context-engine": {"command": "x"}, "other": {}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", lambda: fake_user)

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    out = wipe_all(yes=True, models=False, package=False, repo=repo)
    assert out["ok"] is True
    assert out["scope"] == "all"
    assert not home.exists()
    mcp = json.loads((fake_user / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    assert "context-engine" not in (mcp.get("mcpServers") or {})
    assert "other" in (mcp.get("mcpServers") or {})


def test_wipe_repo_removes_id_and_rule(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    id_dir = repo / ".context-engine"
    id_dir.mkdir()
    (id_dir / "id.json").write_text(
        json.dumps({"project_id": "ce_test"}), encoding="utf-8"
    )
    rule = repo / ".cursor" / "rules" / "context-agent.mdc"
    rule.parent.mkdir(parents=True)
    rule.write_text("x", encoding="utf-8")
    mcp = repo / ".cursor" / "mcp.json"
    mcp.write_text(
        json.dumps({"mcpServers": {"context-engine": {"command": "x"}}}),
        encoding="utf-8",
    )

    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                "ce_test": {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "lifecycle_state": "active",
                }
            }
        }
    )

    out = wipe_repo(repo)
    assert out["scope"] == "repo"
    assert not id_dir.exists()
    assert not rule.exists()
    if mcp.is_file():
        data = json.loads(mcp.read_text(encoding="utf-8"))
        assert "context-engine" not in (data.get("mcpServers") or {})
    else:
        assert not mcp.exists()


def test_wipe_repo_hint_mentions_all(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    (home / "accel.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    out = wipe_repo(repo)
    assert "wipe --all --confirm" in out["hint"]
    assert out["still_on_machine"]["accel_json"] is True


def test_audit_reports_ctx_home(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    out = audit_scubiee_artifacts(include_package=False)
    assert out["clean"] is False
    kinds = {item["kind"] for item in out["remaining"]}
    assert "ctx_home" in kinds


def test_wipe_repo_removes_workspace_local_mcp_files(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    files = [
        repo / ".kiro" / "settings" / "mcp.json",
        repo / ".vscode" / "mcp.json",
        repo / ".mcp.json",
        repo / ".cline" / "mcp.json",
        repo / ".roo" / "mcp.json",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        key = "servers" if ".vscode" in path.parts else "mcpServers"
        path.write_text(
            json.dumps({key: {"context-engine": {"command": "x"}}}),
            encoding="utf-8",
        )

    out = wipe_repo(repo)
    assert out["ok"] is True
    for path in files:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            servers = data.get("mcpServers") or data.get("servers") or {}
            assert "context-engine" not in servers
        else:
            assert not path.exists()


def test_wipe_all_removes_all_connect_tool_mcp(tmp_path: Path, monkeypatch) -> None:
    """wipe --all must clear every tool connect can write, not only Cursor/Kiro."""
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))

    fake_user = tmp_path / "fake-user"
    fake_user.mkdir()
    monkeypatch.setenv("HOME", str(fake_user))
    monkeypatch.setenv("USERPROFILE", str(fake_user))
    monkeypatch.setenv("APPDATA", str(fake_user / "AppData" / "Roaming"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_user))

    # Cursor (already covered elsewhere) + Claude Code + Windsurf user MCP.
    cursor_mcp = fake_user / ".cursor" / "mcp.json"
    cursor_mcp.parent.mkdir(parents=True)
    cursor_mcp.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "context-engine": {"command": "x"},
                    "keep-me": {"command": "y"},
                }
            }
        ),
        encoding="utf-8",
    )
    claude_mcp = fake_user / ".claude.json"
    claude_mcp.write_text(
        json.dumps({"mcpServers": {"context-engine": {"command": "x"}, "other": {}}}),
        encoding="utf-8",
    )
    windsurf_mcp = fake_user / ".codeium" / "windsurf" / "mcp_config.json"
    windsurf_mcp.parent.mkdir(parents=True)
    windsurf_mcp.write_text(
        json.dumps({"mcpServers": {"context-engine": {"command": "x"}}}),
        encoding="utf-8",
    )
    # Codex TOML
    codex_cfg = fake_user / ".codex" / "config.toml"
    codex_cfg.parent.mkdir(parents=True)
    codex_cfg.write_text(
        '[mcp_servers.other]\ncommand = "y"\n\n[mcp_servers.context-engine]\ncommand = "x"\n',
        encoding="utf-8",
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)

    out = wipe_all(yes=True, models=False, package=False, repo=repo)
    assert out["ok"] is True
    assert any("disconnect_all_tools" in a for a in out.get("actions", []))

    cursor = json.loads(cursor_mcp.read_text(encoding="utf-8"))
    assert "context-engine" not in (cursor.get("mcpServers") or {})
    assert "keep-me" in (cursor.get("mcpServers") or {})

    claude = json.loads(claude_mcp.read_text(encoding="utf-8"))
    assert "context-engine" not in (claude.get("mcpServers") or {})
    assert "other" in (claude.get("mcpServers") or {})

    if windsurf_mcp.is_file():
        wind = json.loads(windsurf_mcp.read_text(encoding="utf-8"))
        assert "context-engine" not in (wind.get("mcpServers") or {})
    # Empty-only files may be deleted entirely.

    if codex_cfg.is_file():
        text = codex_cfg.read_text(encoding="utf-8")
        assert "context-engine" not in text
        assert "other" in text

    audit = audit_scubiee_artifacts(include_package=False, include_models=False)
    tool_leftovers = [r for r in audit["remaining"] if str(r["kind"]).startswith("tool_mcp:")]
    assert tool_leftovers == [], tool_leftovers


def test_disconnect_all_workspaces_removes_other_repo_local_mcp(
    tmp_path: Path, monkeypatch
) -> None:
    from pipeline.rules_installer import uninstall_tool
    from pipeline.tool_registry import TOOL_MAP

    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    monkeypatch.setenv("HOME", str(tmp_path / "user-home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "user-home"))
    (tmp_path / "user-home").mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "user-home"))

    repo_a = tmp_path / "a"
    repo_b = tmp_path / "b"
    for repo in (repo_a, repo_b):
        repo.mkdir()
        (repo / ".git").mkdir()
        mcp = repo / ".kiro" / "settings" / "mcp.json"
        mcp.parent.mkdir(parents=True)
        mcp.write_text(
            json.dumps({"mcpServers": {"context-engine": {"command": "x", "env": {}}}}),
            encoding="utf-8",
        )

    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                "ce_aaaaa": {
                    "managed": True,
                    "root": str(repo_a.resolve()),
                    "paths": [str(repo_a.resolve())],
                },
                "ce_bbbbb": {
                    "managed": True,
                    "root": str(repo_b.resolve()),
                    "paths": [str(repo_b.resolve())],
                },
            }
        }
    )

    monkeypatch.chdir(repo_a)
    report = uninstall_tool(TOOL_MAP["kiro"], repo=repo_a, all_workspaces=True)
    assert report["ok"] is True
    assert report.get("all_workspaces") is True
    assert not (repo_a / ".kiro" / "settings" / "mcp.json").is_file()
    assert not (repo_b / ".kiro" / "settings" / "mcp.json").is_file()

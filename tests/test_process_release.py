"""Process lock release before wipe/upgrade."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_release_calls_stub_then_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.process_control import release_scubiee_process_locks

    order: list[str] = []

    def _stub(**kw: object) -> dict:
        order.append("stub")
        return {"ok": True, "stubbed": []}

    def _disable(**kw: object) -> dict:
        order.append("disable")
        return {"ok": True, "disabled": []}

    def _kill(**kw: object) -> dict:
        order.append("kill")
        return {"ok": True, "remaining": [], "remaining_pids": []}

    monkeypatch.setattr("pipeline.process_control.stub_mcp_commands_to_noop", _stub)
    monkeypatch.setattr(
        "pipeline.process_control.disable_mcp_to_prevent_respawn",
        _disable,
    )
    monkeypatch.setattr(
        "pipeline.process_control.kill_all_scubiee_processes",
        _kill,
    )
    monkeypatch.setattr("pipeline.process_control.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.set_desired_mode",
        lambda *_a, **_k: None,
    )

    out = release_scubiee_process_locks()
    assert order == ["stub", "kill", "disable"]
    assert out["ok"] is True


def test_halt_keeps_mcp_stub_without_strip(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.process_control import release_scubiee_process_locks

    disabled = []

    monkeypatch.setattr(
        "pipeline.process_control.stub_mcp_commands_to_noop",
        lambda **kw: {"ok": True, "stubbed": ["x"]},
    )
    monkeypatch.setattr(
        "pipeline.process_control.disable_mcp_to_prevent_respawn",
        lambda **kw: disabled.append("yes") or {"ok": True, "disabled": []},
    )
    monkeypatch.setattr(
        "pipeline.process_control.kill_all_scubiee_processes",
        lambda **kw: {"ok": True, "remaining": [], "remaining_pids": []},
    )
    monkeypatch.setattr("pipeline.process_control.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.set_desired_mode",
        lambda *_a, **_k: None,
    )

    out = release_scubiee_process_locks(strip_mcp=False)
    assert out["ok"] is True
    assert disabled == []
    assert "mcp" not in out


def test_release_reports_remaining_pids(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.process_control import release_scubiee_process_locks

    monkeypatch.setattr(
        "pipeline.process_control.stub_mcp_commands_to_noop",
        lambda **kw: {"ok": True, "stubbed": []},
    )

    monkeypatch.setattr(
        "pipeline.process_control.disable_mcp_to_prevent_respawn",
        lambda **kw: {"ok": True, "disabled": []},
    )
    monkeypatch.setattr(
        "pipeline.process_control.kill_all_scubiee_processes",
        lambda **kw: {"ok": False, "remaining_pids": [9999], "remaining": [{"pid": 9999}]},
    )
    monkeypatch.setattr("pipeline.process_control.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.set_desired_mode",
        lambda *_a, **_k: None,
    )

    out = release_scubiee_process_locks()
    assert out["ok"] is False
    assert out["remaining_pids"] == [9999]
    assert "hint" in out


def test_stub_mcp_rewrites_command_without_removing_other_servers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pipeline.process_control import mcp_noop_command, stub_mcp_commands_to_noop

    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    mcp = repo / ".cursor" / "mcp.json"
    mcp.parent.mkdir(parents=True)
    mcp.write_text(
        '{"mcpServers": {"scubiee": {"command": "python", "args": ["-m", "pipeline.mcp_locate"]}, "other": {"command": "keep"}}}',
        encoding="utf-8",
    )
    monkeypatch.chdir(repo)

    out = stub_mcp_commands_to_noop(project=repo)
    assert out["ok"] is True
    import json

    data = json.loads(mcp.read_text(encoding="utf-8"))
    cmd, args = mcp_noop_command()
    scubiee = data["mcpServers"]["scubiee"]
    assert scubiee["command"] == cmd
    assert scubiee["args"] == args
    assert data["mcpServers"]["other"]["command"] == "keep"


def test_stub_continue_yaml_rewrites_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.process_control import mcp_noop_command, stub_mcp_commands_to_noop

    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    fake_user = tmp_path / "user"
    fake_user.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_user))
    monkeypatch.setenv("HOME", str(fake_user))
    monkeypatch.setenv("USERPROFILE", str(fake_user))

    cfg = fake_user / ".continue" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(
        "name: keep\n"
        "mcpServers:  # scubiee\n"
        "  - name: scubiee\n"
        '    command: "python"\n'
        '    args: ["-m", "pipeline.mcp_locate"]\n'
        "other:\n"
        "  keep: true\n",
        encoding="utf-8",
    )
    project = tmp_path / "repo"
    project.mkdir()
    proj_yaml = project / ".continue" / "mcpServers" / "scubiee.yaml"
    proj_yaml.parent.mkdir(parents=True)
    proj_yaml.write_text(
        "name: Scubiee\n"
        "mcpServers:\n"
        "  - name: scubiee\n"
        '    command: "python"\n'
        '    args: ["-m", "pipeline.mcp_locate"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    out = stub_mcp_commands_to_noop(project=project)
    assert out["ok"] is True
    cmd, args = mcp_noop_command()
    text = cfg.read_text(encoding="utf-8")
    assert f'command: "{cmd}"' in text
    assert "pipeline.mcp_locate" not in text
    assert "keep: true" in text
    proj_text = proj_yaml.read_text(encoding="utf-8")
    assert f'command: "{cmd}"' in proj_text
    assert "pipeline.mcp_locate" not in proj_text


def test_halt_allowed_when_globally_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.lifecycle_guard import paused_blocks_command

    monkeypatch.setattr("pipeline.pause_resume.is_paused", lambda: True)
    assert paused_blocks_command("halt", ["halt"]) is None
    assert paused_blocks_command("unlock-tool", ["unlock-tool"]) is None


def test_disable_mcp_fans_out_enrolled_repos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.process_control import disable_mcp_to_prevent_respawn

    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    repo = tmp_path / "repo"
    repo.mkdir()
    mcp = repo / ".cursor" / "mcp.json"
    mcp.parent.mkdir(parents=True)
    mcp.write_text(
        '{"mcpServers": {"scubiee": {"command": "x"}, "other": {}}}',
        encoding="utf-8",
    )

    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                "ce_test1234567890abcdef": {
                    "managed": True,
                    "root": str(repo.resolve()),
                }
            }
        }
    )

    monkeypatch.setattr(
        "pipeline.pause_resume._disable_mcp_for_tool",
        lambda tool: [],
    )

    out = disable_mcp_to_prevent_respawn(project=repo)
    assert out["ok"] is True
    import json

    data = json.loads(mcp.read_text(encoding="utf-8"))
    assert "scubiee" not in (data.get("mcpServers") or {})
    assert "other" in (data.get("mcpServers") or {})

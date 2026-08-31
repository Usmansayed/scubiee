"""Production hardening: bridge-preserving quiesce, CTX_HOME guard, MCP env refresh."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_kill_all_scubiee_processes_excludes_bridge(monkeypatch):
    from pipeline import process_control

    bridge = {"pid": 100, "cmdline": "scubiee-mcp-bridge.exe", "exe": "scubiee-mcp-bridge.exe"}
    worker = {"pid": 101, "cmdline": "scubiee-mcp child", "exe": "scubiee-mcp.exe"}
    engine = {"pid": 102, "cmdline": "python -m pipeline engine run", "exe": "python.exe"}

    monkeypatch.setattr(process_control, "stop_engine_worker_processes", lambda: {"ok": True})
    monkeypatch.setattr(process_control, "stop_all_context_engine_processes", lambda: {"ok": True})
    monkeypatch.setattr(process_control, "uv_tool_root", lambda: None)

    calls: list[int] = []

    def fake_terminate(pid: int, *, grace_s: float = 0.5):
        calls.append(pid)
        return {"terminated": True, "pid": pid}

    monkeypatch.setattr(process_control, "safe_terminate_pid", fake_terminate)

    rounds = {"n": 0}

    def fake_enumerate(*, exclude_self: bool = True):
        rounds["n"] += 1
        if rounds["n"] == 1:
            return [bridge, worker, engine]
        return []

    monkeypatch.setattr(process_control, "enumerate_scubiee_processes", fake_enumerate)

    report = process_control.kill_all_scubiee_processes(exclude_bridge=True, rounds=1)
    assert 100 not in calls
    assert 101 in calls
    assert 102 in calls
    assert report["skipped_bridge_pids"] == [100]
    assert report["ok"] is True


def test_quiesce_uses_exclude_bridge(monkeypatch):
    captured: dict[str, bool] = {}

    def fake_kill(*, exclude_self: bool = True, exclude_bridge: bool = False, rounds: int = 3):
        captured["exclude_bridge"] = exclude_bridge
        return {"ok": True, "remaining": []}

    def fake_release(**kwargs):
        return {"ok": True}

    monkeypatch.setattr(
        "pipeline.process_control.kill_all_scubiee_processes",
        fake_kill,
    )
    monkeypatch.setattr(
        "pipeline.process_control.release_scubiee_process_locks",
        fake_release,
    )
    monkeypatch.setattr(
        "pipeline.upgrade_platform.verify_quiesced",
        lambda **kwargs: {"ok": False},
    )
    monkeypatch.setattr("pipeline.daemon.stop_daemon", lambda: None)

    from pipeline.upgrade_platform import quiesce_for_upgrade

    report = quiesce_for_upgrade()
    assert captured.get("exclude_bridge") is True
    assert "kill_round_1" in report.get("phases", [])


def test_ctx_home_blocks_temp_path(monkeypatch):
    from pipeline.ctx_home_guard import enforce_ctx_home_or_exit, validate_ctx_home

    monkeypatch.delenv("CTX_ALLOW_TEST_HOME", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("CTX_HOME", r"C:\Users\me\AppData\Local\Temp\pytest-of-me\home")

    report = validate_ctx_home()
    assert report["ok"] is False
    assert report["error"] == "ctx_home_polluted"

    with pytest.raises(SystemExit) as exc:
        enforce_ctx_home_or_exit()
    assert exc.value.code == 1


def test_ctx_home_allows_test_bypass(monkeypatch):
    from pipeline.ctx_home_guard import validate_ctx_home

    monkeypatch.setenv("CTX_HOME", r"C:\Temp\scubiee-test-home")
    monkeypatch.setenv("CTX_ALLOW_TEST_HOME", "1")

    report = validate_ctx_home()
    assert report["ok"] is True
    assert report.get("test_bypass") is True


def test_patch_build_env_in_toml(tmp_path: Path):
    from pipeline.mcp_hot_reload import _patch_build_env_in_toml

    path = tmp_path / "config.toml"
    path.write_text(
        '\n[mcp_servers.scubiee]\n'
        'command = "scubiee-mcp-bridge"\n'
        'env = { CTX_REPO = "/repo", CTX_SCUBIEE_BUILD = "stale-1" }\n',
        encoding="utf-8",
    )
    assert _patch_build_env_in_toml(path, "0.3.9-99") is True
    text = path.read_text(encoding="utf-8")
    assert 'CTX_SCUBIEE_BUILD = "0.3.9-99"' in text
    assert _patch_build_env_in_toml(path, "0.3.9-99") is False


def test_patch_build_env_in_yaml(tmp_path: Path):
    from pipeline.mcp_hot_reload import _patch_build_env_in_yaml

    path = tmp_path / "scubiee.yaml"
    path.write_text(
        "name: Scubiee\n"
        "mcpServers:\n"
        '  - name: scubiee\n'
        '    command: "scubiee-mcp-bridge"\n'
        "    env:\n"
        '      CTX_REPO: "/repo"\n'
        '      CTX_SCUBIEE_BUILD: "stale-1"\n',
        encoding="utf-8",
    )
    assert _patch_build_env_in_yaml(path, "0.3.9-99") is True
    text = path.read_text(encoding="utf-8")
    assert 'CTX_SCUBIEE_BUILD: "0.3.9-99"' in text


def test_client_for_records_admission_error(monkeypatch, tmp_path: Path):
    from pipeline import mcp_locate

    repo = tmp_path / "repo"
    repo.mkdir()
    captured: list[str] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def open_repo(self, *args, **kwargs):
            raise RuntimeError("daemon unreachable")

        def note_locate(self, *args, **kwargs):
            return None

    monkeypatch.setattr("pipeline.daemon.ensure_daemon", lambda *a, **k: None)
    monkeypatch.setattr("pipeline.client.EngineClient", FakeClient)
    monkeypatch.setattr(mcp_locate, "_stderr", lambda msg: captured.append(msg))

    client = mcp_locate._client_for(repo)
    admission = getattr(client, "_scubiee_admission")
    assert admission["ok"] is False
    assert admission["error"] == "open_repo_failed"
    assert any("admission warning" in line for line in captured)

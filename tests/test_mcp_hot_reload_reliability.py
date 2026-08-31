"""Reliability / stress tests for MCP bridge hot-reload and upgrade nudge."""

from __future__ import annotations

import json
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

from pipeline.mcp_bridge import McpBridge
from pipeline.mcp_hot_reload import (
    current_build_id,
    nudge_mcp_hot_reload,
    read_active_build_stamp,
    write_active_build_stamp,
)
from pipeline.mcp_install import server_entry
from pipeline.process_control import kill_mcp_worker_processes

FAKE_MCP_SCRIPT = textwrap.dedent(
    '''
    import json, os, sys
    gen = os.environ.get("CTX_FAKE_GEN", "?")
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        req = json.loads(line)
        mid = req.get("id")
        method = req.get("method")
        if method == "initialize":
            out = {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "fake", "version": gen},
                },
            }
        elif method == "tools/list":
            out = {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {"tools": [{"name": f"tool_{gen}", "description": "x"}]},
            }
        elif method == "tools/call":
            out = {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {"content": [{"type": "text", "text": f"gen={gen}"}]},
            }
        elif method == "notifications/initialized":
            continue
        else:
            out = {"jsonrpc": "2.0", "id": mid, "result": {}}
        print(json.dumps(out), flush=True)
    '''
)


def _bridge_with_fake_child(tmp_path, monkeypatch, *, gen: str = "1") -> McpBridge:
    script = tmp_path / "fake_mcp.py"
    script.write_text(FAKE_MCP_SCRIPT, encoding="utf-8")
    monkeypatch.setenv("CTX_FAKE_GEN", gen)
    monkeypatch.setenv("CTX_MCP_BRIDGE_MODE", "shared")
    for key in (
        "CTX_MCP_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
        "MCP_SESSION_ID",
        "CONVERSATION_ID",
        "CHAT_ID",
        "THREAD_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(
        "CTX_MCP_BRIDGE_SPAWN_JSON",
        json.dumps([sys.executable, str(script)]),
    )
    return McpBridge()


def _handshake(bridge: McpBridge) -> None:
    bridge.handle_client_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
    )
    bridge.handle_client_message({"jsonrpc": "2.0", "method": "notifications/initialized"})


def test_server_entry_prefers_bridge_when_on_path(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    fake_bridge = str(tmp_path / "scubiee-mcp-bridge.exe")

    def fake_which(name: str):
        if name == "scubiee-mcp-bridge":
            return fake_bridge
        if name == "scubiee-mcp":
            return str(tmp_path / "scubiee-mcp.exe")
        return None

    monkeypatch.setattr("shutil.which", fake_which)
    entry = server_entry(tmp_path)
    assert entry["command"].replace("\\", "/") == fake_bridge.replace("\\", "/")
    assert entry["args"] == []
    assert "CTX_SCUBIEE_BUILD" in entry["env"]


def test_server_entry_falls_back_to_mcp_when_no_bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    fake_mcp = str(tmp_path / "scubiee-mcp.exe")

    def fake_which(name: str):
        if name == "scubiee-mcp-bridge":
            return None
        if name == "scubiee-mcp":
            return fake_mcp
        return None

    monkeypatch.setattr("shutil.which", fake_which)
    entry = server_entry(None)
    assert entry["command"].replace("\\", "/") == fake_mcp.replace("\\", "/")


def test_bridge_stderr_drain_prevents_block(tmp_path, monkeypatch, capsys):
    """Chatty stderr must be drained so the child cannot deadlock."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    script = tmp_path / "noisy_stderr.py"
    script.write_text(
        textwrap.dedent(
            '''
            import json, sys
            for i in range(50):
                print(f"noise-{i}", file=sys.stderr, flush=True)
            for raw in sys.stdin:
                line = raw.strip()
                if not line:
                    continue
                req = json.loads(line)
                mid = req.get("id")
                if req.get("method") == "initialize":
                    print(json.dumps({"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"n","version":"1"}}}), flush=True)
            '''
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "CTX_MCP_BRIDGE_SPAWN_JSON",
        json.dumps([sys.executable, str(script)]),
    )
    bridge = McpBridge()
    bridge.handle_client_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
    )
    err = capsys.readouterr().err
    assert "noise-0" in err or "noise-49" in err
    bridge.kill_child()


def test_pyproject_declares_bridge_entrypoint():
    py = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    scripts = py["project"]["scripts"]
    assert "scubiee-mcp-bridge" in scripts
    assert scripts["scubiee-mcp-bridge"] == "pipeline.mcp_bridge:main"


@pytest.mark.parametrize("cycles", [3, 5])
def test_bridge_survives_multiple_upgrade_cycles(tmp_path, monkeypatch, cycles: int):
    """Simulate repeated upgrade stamps — bridge must respawn each time."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    captured: list[str] = []

    def capture_write(data: str) -> int:
        captured.append(data)
        return len(data)

    monkeypatch.setattr(sys.stdout, "write", capture_write)
    monkeypatch.setattr(sys.stdout, "flush", lambda: None)

    bridge = _bridge_with_fake_child(tmp_path, monkeypatch, gen="0")
    _handshake(bridge)

    for i in range(cycles):
        write_active_build_stamp(f"0.0.{i}", epoch=float(100 + i))
        monkeypatch.setenv("CTX_FAKE_GEN", str(i + 1))
        bridge.kill_child()
        bridge._loaded_build_id = "stale"

        bridge.handle_client_message(
            {
                "jsonrpc": "2.0",
                "id": 100 + i,
                "method": "tools/call",
                "params": {"name": "gate", "arguments": {}},
            }
        )

    joined = "".join(captured)
    for i in range(cycles):
        assert f"gen={i + 1}" in joined
    bridge.kill_child()


def test_nudge_then_rebind_build_id_updates(tmp_path, monkeypatch):
    """Upgrade nudge writes stamp; server_entry picks it up."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setattr(
        "pipeline.process_control.kill_mcp_worker_processes",
        lambda exclude_bridge=True: {"ok": True, "killed": [], "remaining_pids": []},
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.set_desired_mode",
        lambda mode: {"ok": True},
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.note_engine_transition",
        lambda action: {"ok": True},
    )

    before = current_build_id()
    nudge = nudge_mcp_hot_reload("9.9.9")
    assert nudge["ok"] is True
    after = current_build_id()
    assert after != before
    assert read_active_build_stamp()["version"] == "9.9.9"

    monkeypatch.setattr("shutil.which", lambda _n: None)
    entry = server_entry(None)
    assert entry["env"]["CTX_SCUBIEE_BUILD"] == after


def test_upgrade_supervisor_includes_hot_reload_on_connect(tmp_path, monkeypatch):
    """Full upgrade path (mocked) must call nudge before rebind."""
    from pipeline import upgrade
    import pipeline.upgrade_supervisor as sup
    from pipeline.upgrade_manifest import ComponentAction, DiffPlan

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    nudge_calls: list[str] = []
    rebind_calls: list[str] = []

    monkeypatch.setattr(upgrade, "installed_version", lambda: "0.3.6")
    monkeypatch.setattr(
        "importlib.metadata.version",
        lambda pkg: "0.3.6" if pkg == "scubiee" else "0.0.0",
    )
    monkeypatch.setattr(
        upgrade,
        "check_pypi_version",
        lambda force=False, timeout=5.0: {
            "current": "0.3.6",
            "latest": "0.3.6",
            "update_available": False,
        },
    )
    monkeypatch.setattr(
        sup,
        "build_diff_plan",
        lambda **kwargs: DiffPlan(
            from_version=kwargs["from_version"],
            to_version=kwargs["to_version"],
            actions=[
                ComponentAction("package", "skip", "same"),
                ComponentAction("daemon", "restart", "ensure"),
                ComponentAction("mcp_pins", "refresh", "rebind"),
                ComponentAction("gate_rules", "refresh", "rebind"),
            ],
        ),
    )
    monkeypatch.setattr(
        sup,
        "quiesce_for_upgrade",
        lambda project=None: {"ok": True, "phases": ["release_locks"]},
    )
    monkeypatch.setattr(
        sup,
        "ensure_daemon_after_upgrade",
        lambda repo=None: {"ok": True, "action": "already_running"},
    )
    monkeypatch.setattr(
        sup,
        "health_check",
        lambda timeout=5.0: {"ok": True, "installed_version": "0.3.6", "daemon_version": "0.3.6"},
    )
    monkeypatch.setattr(sup, "maybe_setup_repair", lambda: {"ok": True, "skipped": True})
    monkeypatch.setattr(sup, "rebuild_embeddings_if_needed", lambda plan: {"ok": True, "skipped": True})
    monkeypatch.setattr(sup, "migrate_indexes", lambda: {"ok": True, "skipped": True})
    monkeypatch.setattr(
        sup,
        "snapshot_for_rollback",
        lambda revision_id, old_version: {"ok": True, "revision_id": revision_id},
    )

    def fake_nudge(version=None):
        nudge_calls.append(version or "")
        return {"ok": True, "stamp": {"build_id": "0.3.6-999"}}

    def fake_rebind():
        rebind_calls.append("yes")
        return {"ok": True, "repos": []}

    monkeypatch.setattr("pipeline.mcp_hot_reload.nudge_mcp_hot_reload", fake_nudge)
    monkeypatch.setattr(sup, "rebind_mcp_and_rules", fake_rebind)

    report = upgrade.do_upgrade(skip_package=True, connect=True)
    assert report["ok"] is True
    assert nudge_calls == ["0.3.6"]
    assert rebind_calls == ["yes"]
    assert "mcp_hot_reload" in report
    assert "auto-reloads" in report["next_steps"][0]


def test_kill_workers_leaves_bridge_running(monkeypatch):
    bridge = {"pid": 42, "cmdline": "scubiee-mcp-bridge.exe", "exe": "scubiee-mcp-bridge.exe"}
    worker_a = {"pid": 43, "cmdline": "scubiee-mcp.exe", "exe": "scubiee-mcp.exe"}
    worker_b = {"pid": 44, "cmdline": "python -m pipeline.mcp_locate", "exe": "python.exe"}
    alive = {42: bridge, 43: worker_a, 44: worker_b}

    def fake_enumerate(*, exclude_self=True):
        return list(alive.values())

    monkeypatch.setattr(
        "pipeline.process_control.enumerate_scubiee_processes",
        fake_enumerate,
    )
    killed: list[int] = []

    def fake_term(pid: int, *, grace_s: float = 1.0):
        killed.append(pid)
        alive.pop(pid, None)
        return {"pid": pid, "ok": True, "terminated": True}

    monkeypatch.setattr("pipeline.process_control.safe_terminate_pid", fake_term)
    report = kill_mcp_worker_processes(exclude_bridge=True)
    assert 42 not in killed
    assert 43 in killed
    assert 44 in killed
    assert report["ok"] is True
    assert report["remaining_pids"] == []


def test_bridge_child_death_triggers_respawn(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    bridge = _bridge_with_fake_child(tmp_path, monkeypatch)
    _handshake(bridge)
    assert bridge._child is not None
    bridge._child.kill()
    bridge._child.wait(timeout=5)
    assert bridge.needs_respawn() is True

    captured: list[str] = []

    def capture_write(data: str) -> int:
        captured.append(data)
        return len(data)

    monkeypatch.setattr(sys.stdout, "write", capture_write)
    monkeypatch.setattr(sys.stdout, "flush", lambda: None)

    bridge.handle_client_message(
        {
            "jsonrpc": "2.0",
            "id": 99,
            "method": "tools/list",
            "params": {},
        }
    )
    assert any("tools" in chunk for chunk in captured)
    bridge.kill_child()

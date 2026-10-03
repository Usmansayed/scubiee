"""Tests for MCP hot reload stamp + bridge respawn logic."""

from __future__ import annotations

import json
import sys
import textwrap

import pytest

from pipeline.mcp_bridge import McpBridge
from pipeline.mcp_hot_reload import (
    active_build_path,
    current_build_id,
    make_build_id,
    nudge_mcp_hot_reload,
    read_active_build_stamp,
    write_active_build_stamp,
)
from pipeline.process_control import (
    _is_mcp_bridge_process,
    _is_mcp_worker_process,
    kill_mcp_worker_processes,
)

_NOTICE_PREFIX = "[scubiee] MCP worker restarted"


def test_make_build_id():
    assert make_build_id("0.3.6", epoch=1000.0) == "0.3.6-1000"


def test_write_and_read_active_build_stamp(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    stamp = write_active_build_stamp("0.3.7", epoch=12345.0)
    assert stamp["version"] == "0.3.7"
    assert stamp["build_id"] == "0.3.7-12345"
    assert active_build_path().is_file()
    loaded = read_active_build_stamp()
    assert loaded is not None
    assert loaded["build_id"] == "0.3.7-12345"
    assert current_build_id() == "0.3.7-12345"


def test_read_active_build_stamp_synthesizes_build_id(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    active_build_path().parent.mkdir(parents=True, exist_ok=True)
    active_build_path().write_text(
        json.dumps({"version": "1.0.0", "epoch": 99}) + "\n",
        encoding="utf-8",
    )
    loaded = read_active_build_stamp()
    assert loaded is not None
    assert loaded["build_id"] == "1.0.0-99"


def test_bridge_needs_respawn_on_stamp_change(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    write_active_build_stamp("0.3.6", epoch=1.0)
    bridge = McpBridge()
    bridge._loaded_build_id = "0.3.5-0"
    assert bridge.needs_respawn() is True


def test_bridge_no_respawn_when_stamp_matches(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    stamp = write_active_build_stamp("0.3.6", epoch=1.0)
    bridge = McpBridge()
    bridge._loaded_build_id = stamp["build_id"]
    bridge._child = type("P", (), {"poll": lambda self: None})()
    assert bridge.needs_respawn() is False


def test_mcp_worker_vs_bridge_detection():
    bridge = {"cmdline": "scubiee-mcp-bridge.exe", "exe": "scubiee-mcp-bridge.exe"}
    worker = {"cmdline": "scubiee-mcp.exe", "exe": "scubiee-mcp.exe"}
    assert _is_mcp_bridge_process(bridge) is True
    assert _is_mcp_worker_process(bridge) is False
    assert _is_mcp_worker_process(worker) is True


def test_kill_mcp_worker_skips_bridge(monkeypatch):
    bridge_proc = {"pid": 100, "cmdline": "scubiee-mcp-bridge", "exe": "scubiee-mcp-bridge.exe"}
    worker_proc = {"pid": 200, "cmdline": "scubiee-mcp", "exe": "scubiee-mcp.exe"}

    monkeypatch.setattr(
        "pipeline.process_control.enumerate_scubiee_processes",
        lambda exclude_self=True: [bridge_proc, worker_proc],
    )
    terminated: list[int] = []

    def fake_terminate(pid: int, *, grace_s: float = 1.0):
        terminated.append(pid)
        return {"pid": pid, "ok": True, "terminated": True}

    monkeypatch.setattr("pipeline.process_control.safe_terminate_pid", fake_terminate)
    report = kill_mcp_worker_processes(exclude_bridge=True)
    assert 200 in terminated
    assert 100 not in terminated
    assert 100 in report["skipped_bridge_pids"]


def test_nudge_mcp_hot_reload(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setattr(
        "pipeline.process_control.kill_mcp_worker_processes",
        lambda exclude_bridge=True: {"ok": True, "killed": [], "remaining_pids": []},
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.set_desired_mode",
        lambda mode: {"ok": True, "mode": mode},
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.note_engine_transition",
        lambda action: {"ok": True, "action": action},
    )
    report = nudge_mcp_hot_reload("0.3.8")
    assert report["ok"] is True
    assert read_active_build_stamp()["version"] == "0.3.8"


FAKE_MCP_SCRIPT = textwrap.dedent(
    '''
    import json, sys
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
                    "serverInfo": {"name": "fake", "version": "1"},
                },
            }
        elif method == "tools/list":
            out = {"jsonrpc": "2.0", "id": mid, "result": {"tools": []}}
        elif method == "tools/call":
            out = {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {"content": [{"type": "text", "text": "pong"}]},
            }
        elif method == "notifications/initialized":
            continue
        else:
            out = {"jsonrpc": "2.0", "id": mid, "result": {}}
        print(json.dumps(out), flush=True)
    '''
)


def test_bridge_lazy_respawn_with_fake_child(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_MCP_BRIDGE_MODE", "shared")
    for key in ("CTX_MCP_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "MCP_SESSION_ID"):
        monkeypatch.delenv(key, raising=False)
    script = tmp_path / "fake_mcp.py"
    script.write_text(FAKE_MCP_SCRIPT, encoding="utf-8")
    monkeypatch.setenv(
        "CTX_MCP_BRIDGE_SPAWN_JSON",
        json.dumps([sys.executable, str(script)]),
    )

    write_active_build_stamp("0.0.1", epoch=1.0)

    bridge = McpBridge()
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    bridge.handle_client_message(init)
    bridge.handle_client_message({"jsonrpc": "2.0", "method": "notifications/initialized"})
    bridge.handle_client_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "gate", "arguments": {}},
        }
    )

    write_active_build_stamp("0.0.2", epoch=2.0)
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
            "id": 3,
            "method": "tools/call",
            "params": {"name": "gate", "arguments": {}},
        }
    )
    joined = "".join(captured)
    assert "tools/list_changed" in joined or _NOTICE_PREFIX in joined
    assert "pong" in joined
    bridge.kill_child()


def test_bridge_does_not_emit_list_changed_on_steady_tools_call(tmp_path, monkeypatch):
    """Steady map/pack/expand must not spam tools/list_changed (duplicate Cursor bridges)."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_MCP_HOT_RELOAD", "1")
    write_active_build_stamp("0.0.1", epoch=1.0)

    fake = tmp_path / "fake_worker.py"
    fake.write_text(
        textwrap.dedent(
            """\
            import json, sys
            for line in sys.stdin:
                msg = json.loads(line)
                mid = msg.get("id")
                method = msg.get("method")
                if method == "initialize":
                    sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2024-11-05","capabilities":{},"serverInfo":{"name":"t","version":"1"}}}) + "\\n")
                    sys.stdout.flush()
                elif method == "notifications/initialized":
                    pass
                elif method == "tools/call":
                    sys.stdout.write(json.dumps({"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":"pong"}]}}) + "\\n")
                    sys.stdout.flush()
            """
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(
        "CTX_MCP_BRIDGE_SPAWN_JSON",
        json.dumps([sys.executable, str(fake)]),
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
    bridge.handle_client_message({"jsonrpc": "2.0", "method": "notifications/initialized"})

    captured: list[str] = []

    def capture_write(data: str) -> int:
        captured.append(data)
        return len(data)

    monkeypatch.setattr(sys.stdout, "write", capture_write)
    monkeypatch.setattr(sys.stdout, "flush", lambda: None)

    # First tools/call after init — worker already spawned at initialize; gen unchanged.
    bridge.handle_client_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "gate", "arguments": {}},
        }
    )
    joined = "".join(captured)
    assert "tools/list_changed" not in joined
    assert "pong" in joined
    bridge.kill_child()


def test_handshake_reports_scubiee_map_v3_server_info() -> None:
    """`serverInfo` is the one surface a user can check for which map is live.

    The old FastMCP surface (mcp_locate.create_mcp) fell back to the installed
    `mcp` SDK version in serverInfo. Map V3 (pipeline.map_v3_server) is a
    hand-rolled JSON-RPC server that answers `initialize` with an explicit,
    scubiee-branded serverInfo — so the SDK-version leak cannot recur. This
    pins the live initialize contract for the shipped Map V3 server.
    """
    import inspect

    from pipeline import map_v3_server

    src = inspect.getsource(map_v3_server)
    assert '"protocolVersion": "2024-11-05"' in src
    assert '"serverInfo": {"name": "scubiee-map-v3"' in src
    # Must not fall back to the mcp SDK "1.x" package version as the old surface did.
    import re

    m = re.search(r'"serverInfo":\s*\{"name":\s*"scubiee-map-v3",\s*"version":\s*"([^"]+)"', src)
    assert m, "Map V3 serverInfo version string not found"
    assert m.group(1) and not m.group(1).startswith("1.30"), m.group(1)

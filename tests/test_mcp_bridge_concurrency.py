"""Concurrency + session routing tests for scubiee-mcp-bridge v2."""

from __future__ import annotations

import json
import sys
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from pipeline.mcp_bridge import McpBridge, spawn_child_process
from pipeline.mcp_bridge_session import ChildWorker, extract_session_key
from pipeline.mcp_hot_reload import write_active_build_stamp

CONCURRENT_FAKE = textwrap.dedent(
    """
    import json, sys, threading, time
    lock = threading.Lock()
    inflight = 0
    peak = 0

    def handle(req):
        global inflight, peak
        mid = req.get("id")
        method = req.get("method")
        if method == "initialize":
            out = {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "serverInfo": {"name": "fake-concurrent", "version": "1"},
                },
            }
        elif method == "tools/call":
            with lock:
                inflight += 1
                peak = max(peak, inflight)
            time.sleep(0.08)
            with lock:
                inflight -= 1
            out = {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {"content": [{"type": "text", "text": f"peak={peak}"}]},
            }
        elif method == "notifications/initialized":
            return
        else:
            out = {"jsonrpc": "2.0", "id": mid, "result": {}}
        print(json.dumps(out), flush=True)

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        req = json.loads(line)
        threading.Thread(target=handle, args=(req,), daemon=True).start()
    """
)

SESSION_FAKE = textwrap.dedent(
    """
    import json, os, sys
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
                    "serverInfo": {"name": "fake-session", "version": "1"},
                },
            }
        elif method == "tools/call":
            sid = os.environ.get("CTX_MCP_SESSION_ID", "__none__")
            out = {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {"content": [{"type": "text", "text": sid}]},
            }
        elif method == "notifications/initialized":
            continue
        else:
            out = {"jsonrpc": "2.0", "id": mid, "result": {}}
        print(json.dumps(out), flush=True)
    """
)


def _install_fake(monkeypatch, tmp_path, script: str) -> None:
    path = tmp_path / "fake.py"
    path.write_text(script, encoding="utf-8")
    monkeypatch.setenv("CTX_MCP_BRIDGE_SPAWN_JSON", json.dumps([sys.executable, str(path)]))


def _handshake(bridge: McpBridge) -> None:
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


def test_extract_session_key_from_tools_call():
    msg = {
        "method": "tools/call",
        "params": {
            "name": "grep",
            "arguments": {"session_id": "claude-code@chat-abc"},
        },
    }
    assert extract_session_key(msg) == "claude-code@chat-abc"


def test_bridge_routing_from_host_env(monkeypatch):
    from pipeline.session_isolation import bridge_routing_session_key

    monkeypatch.setenv("CTX_MCP_CLIENT", "claude-code")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "thread-99")
    key, source = bridge_routing_session_key({"method": "tools/list", "params": {}})
    assert source == "host_env"
    assert key == "claude-code@chat-thread-99"


def test_child_worker_concurrent_requests(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    _install_fake(monkeypatch, tmp_path, CONCURRENT_FAKE)
    write_active_build_stamp("0.0.1", epoch=1.0)

    worker = ChildWorker(
        session_key="__shared__",
        spawn_fn=spawn_child_process,
        stderr_log=lambda _m: None,
    )
    worker.set_handshake(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        client_initialized=True,
    )
    worker.ensure_ready()

    def call_tool(rid: int) -> dict:
        return worker.request(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "method": "tools/call",
                "params": {"name": "gate", "arguments": {}},
            }
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(call_tool, range(10, 14)))

    peaks = []
    for resp in results:
        content = resp.get("result", {}).get("content", [])
        text = content[0]["text"] if content else ""
        peaks.append(int(text.split("=")[1]))
    assert max(peaks) >= 2
    worker.kill()


def test_bridge_parallel_tools_call(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    _install_fake(monkeypatch, tmp_path, CONCURRENT_FAKE)
    write_active_build_stamp("0.0.1", epoch=1.0)

    bridge = McpBridge()
    captured: list[str] = []
    lock = threading.Lock()

    def capture_write(data: str) -> int:
        with lock:
            captured.append(data)
        return len(data)

    monkeypatch.setattr(sys.stdout, "write", capture_write)
    monkeypatch.setattr(sys.stdout, "flush", lambda: None)

    _handshake(bridge)

    def call_tool(rid: int) -> None:
        bridge.handle_client_message(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "method": "tools/call",
                "params": {"name": "gate", "arguments": {}},
            }
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(call_tool, range(20, 24)))

    joined = "".join(captured)
    assert "peak=" in joined
    bridge.kill_child()


def test_auto_mode_isolates_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_MCP_BRIDGE_MODE", "auto")
    _install_fake(monkeypatch, tmp_path, SESSION_FAKE)
    write_active_build_stamp("0.0.1", epoch=1.0)

    bridge = McpBridge()
    captured: list[str] = []
    monkeypatch.setattr(sys.stdout, "write", lambda data: captured.append(data) or len(data))
    monkeypatch.setattr(sys.stdout, "flush", lambda: None)

    _handshake(bridge)

    for sid, rid in (("claude-code@chat-alpha", 30), ("codex@chat-beta", 31)):
        bridge.handle_client_message(
            {
                "jsonrpc": "2.0",
                "id": rid,
                "method": "tools/call",
                "params": {
                    "name": "gate",
                    "arguments": {"session_id": sid},
                },
            }
        )

    joined = "".join(captured)
    assert "claude-code@chat-alpha" in joined
    assert "codex@chat-beta" in joined
    bridge.kill_child()


def test_auto_mode_isolates_host_env_session(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    monkeypatch.setenv("CTX_MCP_BRIDGE_MODE", "auto")
    monkeypatch.setenv("CTX_MCP_CLIENT", "claude-code")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "env-thread-1")
    _install_fake(monkeypatch, tmp_path, SESSION_FAKE)
    write_active_build_stamp("0.0.1", epoch=1.0)

    bridge = McpBridge()
    captured: list[str] = []
    monkeypatch.setattr(sys.stdout, "write", lambda data: captured.append(data) or len(data))
    monkeypatch.setattr(sys.stdout, "flush", lambda: None)

    _handshake(bridge)
    bridge.handle_client_message(
        {
            "jsonrpc": "2.0",
            "id": 40,
            "method": "tools/call",
            "params": {"name": "gate", "arguments": {}},
        }
    )

    joined = "".join(captured)
    assert "claude-code@chat-env-thread-1" in joined
    bridge.kill_child()


def test_verify_mcp_json_accepts_bridge(tmp_path, monkeypatch):
    from pipeline.mcp_install import verify_mcp_json

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "scubiee": {
                        "command": "C:/tools/scubiee-mcp-bridge.exe",
                        "args": [],
                        "env": {"CTX_SCUBIEE_BUILD": "0.3.7-1"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    report = verify_mcp_json(path)
    assert report["ok"] is True
    assert report["uses_bridge"] is True


def test_refresh_mcp_build_env_updates_stamp(tmp_path, monkeypatch):
    from pipeline.mcp_hot_reload import _patch_build_env_in_mcp_file

    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    write_active_build_stamp("0.3.9", epoch=99.0)
    mcp_path = tmp_path / "repo" / ".cursor" / "mcp.json"
    mcp_path.parent.mkdir(parents=True)
    mcp_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "scubiee": {
                        "command": "scubiee-mcp-bridge",
                        "env": {"CTX_SCUBIEE_BUILD": "stale-1"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert _patch_build_env_in_mcp_file(mcp_path, "0.3.9-99") is True
    loaded = json.loads(mcp_path.read_text(encoding="utf-8"))
    assert loaded["mcpServers"]["scubiee"]["env"]["CTX_SCUBIEE_BUILD"] == "0.3.9-99"
    assert _patch_build_env_in_mcp_file(mcp_path, "0.3.9-99") is False

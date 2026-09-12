"""Windows pythonw must still speak MCP stdio (pipes inherited, no console)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

_ECHO_WORKER = """\
import json
import sys

for raw in sys.stdin:
    line = raw.strip()
    if not line:
        continue
    msg = json.loads(line)
    method = msg.get("method")
    req_id = msg.get("id")
    if method == "initialize":
        print(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {"name": "echo", "version": "0"},
                    },
                }
            ),
            flush=True,
        )
    elif req_id is not None:
        print(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {}}), flush=True)
"""


@pytest.mark.skipif(os.name != "nt", reason="pythonw is a Windows host contract")
def test_pythonw_mcp_bridge_initialize_roundtrip(tmp_path: Path) -> None:
    pyw = Path(sys.executable).with_name("pythonw.exe")
    if not pyw.is_file():
        pytest.skip(f"pythonw.exe not beside {sys.executable}")

    worker = tmp_path / "echo_mcp.py"
    worker.write_text(_ECHO_WORKER, encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    env = os.environ.copy()
    env["CTX_HOME"] = str(home)
    env["CTX_ALLOW_TEST_HOME"] = "1"
    env["CTX_MCP_BRIDGE_SPAWN_JSON"] = json.dumps(
        [sys.executable, "-u", str(worker)]
    )
    env["PYTHONUTF8"] = "1"
    env.pop("CTX_ENGINE_URL", None)

    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    proc = subprocess.Popen(
        [str(pyw), "-u", "-m", "pipeline.mcp_bridge"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=str(tmp_path),
        creationflags=flags,
    )
    stdout_lines: list[str] = []
    stderr_buf: list[str] = []

    def _drain_err() -> None:
        assert proc.stderr is not None
        stderr_buf.append(proc.stderr.read())

    err_thread = threading.Thread(target=_drain_err, daemon=True)
    err_thread.start()
    try:
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "lifecycle-sim", "version": "0"},
                    },
                }
            )
            + "\n"
        )
        proc.stdin.flush()
        deadline = time.time() + 20.0
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            line = proc.stdout.readline()
            if not line:
                continue
            stdout_lines.append(line)
            if line.strip().startswith("{"):
                break
        proc.stdin.close()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
    finally:
        if proc.poll() is None:
            proc.kill()

    err_thread.join(timeout=2)
    payload = ""
    for line in stdout_lines:
        if line.strip().startswith("{"):
            payload = line.strip()
            break
    assert payload, (
        f"no JSON-RPC on pythonw stdout; exit={proc.returncode} "
        f"stdout={stdout_lines!r} stderr={''.join(stderr_buf)[-1500:]}"
    )
    msg = json.loads(payload)
    assert msg.get("id") == 1
    assert "result" in msg
    assert msg["result"]["serverInfo"]["name"] == "echo"

"""Smoke: Kiro + ab_dev_with must call Scubiee gate."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIRO = Path(r"C:\Users\usman\AppData\Local\Kiro-Cli\kiro-cli.exe")
MCP = Path.home() / ".local" / "bin" / "scubiee-mcp.EXE"
BRIDGE = Path.home() / ".local" / "bin" / "scubiee-mcp-bridge.EXE"


def _kiro_key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("KIRO_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("KIRO_API_KEY", "")


def _kiro_settings() -> None:
    for scope in ([], ["--workspace"]):
        for key, val in (
            # loadedBefore=true => wait for MCP before the first prompt.
            ("mcp.loadedBefore", "true"),
            ("mcp.initTimeout", "90"),
            ("mcp.noInteractiveTimeout", "90"),
        ):
            subprocess.run(
                [str(KIRO), "settings", *scope, key, val],
                cwd=str(ROOT),
                check=False,
                capture_output=True,
            )


def _ensure_engine() -> None:
    env = os.environ.copy()
    env["CTX_ENGINE_IDLE_S"] = "3600"
    env["PATH"] = str(Path.home() / ".local" / "bin") + os.pathsep + env.get("PATH", "")
    subprocess.run(
        ["scubiee", "engine", "ensure", "--wait", "60"],
        cwd=str(ROOT),
        env=env,
        check=False,
    )


def main() -> int:
    _kiro_settings()
    _ensure_engine()

    live = json.loads((ROOT / ".scubiee" / "id.json").read_text(encoding="utf-8"))["project_id"]
    sid = f"kiro-smoke-{uuid.uuid4().hex[:8]}"
    use_bridge = os.environ.get("KIRO_SMOKE_BRIDGE", "0") == "1"
    cmd_path = str(BRIDGE if use_bridge else MCP).replace("\\", "/")
    env_pins = {
        "CTX_REPO": str(ROOT).replace("\\", "/"),
        "CTX_PROJECT_ID": live,
        "CTX_MCP_CLIENT": "kiro",
        "CTX_MCP_SURFACE": "phase",
        "CTX_MCP_EXPERIMENT": "ship",
        "CTX_TRACE_ENGINE": "composite_v1",
        "CTX_ENGINE_URL": "http://127.0.0.1:8765",
        "PYTHONUTF8": "1",
        "CTX_BACKGROUND_SYNC": "0",
        "CTX_AUTO_INDEX": "0",
        "CTX_MCP_SESSION_ISOLATE": "1",
        "CTX_MCP_SESSION_ID": sid,
        "CTX_ENGINE_IDLE_S": "3600",
    }
    tools = [
        "read",
        "write",
        "shell",
        "@scubiee",
        "@scubiee/gate",
        "@scubiee/map",
        "@scubiee/status",
    ]
    cfg = {
        "name": "ab_dev_with",
        "description": "smoke",
        "includeMcpJson": False,
        "includePowers": False,
        "model": "claude-sonnet-5",
        "prompt": "Use Scubiee MCP tools when available.",
        "tools": tools,
        "allowedTools": tools,
        "resources": [],
        "mcpServers": {
            "scubiee": {
                "command": cmd_path,
                "args": [],
                "disabled": False,
                "timeout": 300000,
                "env": env_pins,
                "autoApprove": ["*"],
                "alwaysAllow": ["*"],
            }
        },
    }
    agent_path = ROOT / ".kiro" / "agents" / "ab_dev_with.json"
    agent_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    for p in (
        Path.home() / ".kiro" / "settings" / "mcp.json",
        ROOT / ".kiro" / "settings" / "mcp.json",
    ):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"mcpServers": {}}, indent=2) + "\n", encoding="utf-8")

    listed = subprocess.run(
        [str(KIRO), "settings", "list", "--format", "json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print("settings", (listed.stdout or "").strip())
    print("cmd", cmd_path, "sid", sid)

    drop = {k for k in os.environ if k.startswith("CURSOR_") or k.startswith("__CURSOR")}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env["KIRO_API_KEY"] = _kiro_key()
    env["CTX_MCP_SESSION_ID"] = sid
    env["CTX_ENGINE_IDLE_S"] = "3600"
    env["PATH"] = str(Path.home() / ".local" / "bin") + os.pathsep + env.get("PATH", "")

    chat = [
        str(KIRO),
        "chat",
        "--no-interactive",
        "--trust-all-tools",
        "--require-mcp-startup",
        "--agent",
        "ab_dev_with",
        "--agent-engine",
        "v1",
        "--legacy-ui",
        "--model",
        "claude-sonnet-5",
        "--effort",
        "low",
        "--wrap",
        "never",
        "Call Scubiee MCP gate. Reply OK or FAIL only.",
    ]
    t0 = time.time()
    proc = subprocess.run(
        chat,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    print("elapsed", round(time.time() - t0, 1), "rc", proc.returncode)
    for ln in [x for x in out.splitlines() if x.strip()][-30:]:
        print(ln)
    clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", out)
    if "Not all mcp servers loaded" in clean:
        print("SMOKE=FAIL_MCP_STARTUP")
        return 1
    if re.search(r"(?m)^\s*OK\s*$", clean) or re.search(r">\s*OK\b", clean):
        print("SMOKE=OK")
        return 0
    if re.search(r"\bFAIL\b", clean):
        print("SMOKE=FAIL")
        return 1
    print("SMOKE=UNKNOWN")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

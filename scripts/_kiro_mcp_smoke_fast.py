"""Fast Kiro MCP smoke after harness fix."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from kiro_mcp_ab_dev_eval import (  # noqa: E402
    KIRO,
    _kiro_env,
    _kill_hung_mcp_bridges,
    _load_dotenv_key,
    ensure_kiro_mcp_wait_settings,
    write_agents,
)


def main() -> int:
    os.environ["CTX_ENGINE_IDLE_S"] = "3600"
    os.environ.pop("CTX_MCP_SESSION_ID", None)
    for k in list(os.environ):
        if k.startswith("CURSOR_") or k.startswith("__CURSOR"):
            os.environ.pop(k, None)

    _load_dotenv_key()
    ensure_kiro_mcp_wait_settings()
    _kill_hung_mcp_bridges()
    path_env = {
        **os.environ,
        "PATH": str(Path.home() / ".local" / "bin")
        + os.pathsep
        + os.environ.get("PATH", ""),
    }
    subprocess.run(
        ["scubiee", "engine", "ensure", "--wait", "45"],
        cwd=str(ROOT),
        check=False,
        env=path_env,
    )

    for p in (
        Path.home() / ".kiro" / "settings" / "mcp.json",
        ROOT / ".kiro" / "settings" / "mcp.json",
    ):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"mcpServers":{}}\n', encoding="utf-8")

    # Neutralize other agents' MCP so Kiro does not multi-spawn scubiee.
    agents_dir = ROOT / ".kiro" / "agents"
    for path in agents_dir.glob("*.json"):
        if path.name == "ab_dev_with.json":
            continue
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if cfg.get("mcpServers"):
            cfg["mcpServers"] = {}
            path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
            print("cleared mcpServers in", path.name)

    agent = write_agents(ROOT, model="claude-sonnet-5", with_mcp=True)
    cfg = json.loads(agent.read_text(encoding="utf-8"))
    sid = (
        (cfg.get("mcpServers") or {})
        .get("scubiee", {})
        .get("env", {})
        .get("CTX_MCP_SESSION_ID")
    )
    print(
        "agent",
        agent.name,
        "includeMcpJson",
        cfg.get("includeMcpJson"),
        "session",
        sid,
    )

    env = _kiro_env(ROOT)
    env["KIRO_API_KEY"] = os.environ.get("KIRO_API_KEY", "")
    cmd = [
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
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", out)
    print("elapsed", round(time.time() - t0, 1), "rc", proc.returncode)
    for ln in [x for x in clean.splitlines() if x.strip()][-20:]:
        print(ln)
    if "Not all mcp servers loaded" in clean:
        print("SMOKE=FAIL_MCP_STARTUP")
        return 1
    if re.search(r"(?m)^\s*OK\s*$", clean) or re.search(r">\s*OK\b", clean):
        print("SMOKE=OK")
        return 0
    print("SMOKE=FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Smoke with valid ab_dev_with agent (no useLegacyMcpJson alias clash)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kiro_mcp_ab_dev_eval import (  # noqa: E402
    KIRO,
    _kiro_env,
    _kill_hung_mcp_bridges,
    _load_dotenv_key,
    _scubiee_env,
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

    for p in (
        Path.home() / ".kiro" / "settings" / "mcp.json",
        ROOT / ".kiro" / "settings" / "mcp.json",
    ):
        p.write_text('{"mcpServers":{}}\n', encoding="utf-8")

    agent = write_agents(ROOT, model="claude-sonnet-5", with_mcp=True)
    cfg = json.loads(agent.read_text(encoding="utf-8"))
    cfg.pop("useLegacyMcpJson", None)
    cfg["includeMcpJson"] = False
    mcp = str(Path.home() / ".local" / "bin" / "scubiee-mcp.EXE").replace("\\", "/")
    cfg["mcpServers"]["scubiee"]["command"] = mcp
    cfg["mcpServers"]["scubiee"]["env"] = _scubiee_env(ROOT)
    agent.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    val = subprocess.run(
        [str(KIRO), "agent", "validate", "--path", str(agent)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print("validate", val.returncode, (val.stdout or val.stderr or "")[:300])
    if val.returncode != 0:
        print("SMOKE=FAIL_VALIDATE")
        return 1

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
    clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", (proc.stdout or "") + "\n" + (proc.stderr or ""))
    print("elapsed", round(time.time() - t0, 1))
    print("invalid_agent", "no agent with name" in clean or "invalid" in clean.lower())
    print("not_all", "Not all mcp" in clean)
    for ln in [x for x in clean.splitlines() if x.strip()][-18:]:
        print(ln)
    if "no agent with name" in clean or "Json supplied" in clean:
        print("SMOKE=FAIL_AGENT")
        return 1
    if re.search(r"(?m)^\s*OK\s*$", clean) or re.search(r">\s*OK\b", clean):
        if "Not all mcp servers loaded" not in clean:
            print("SMOKE=OK")
            return 0
        # tools worked despite warning
        print("SMOKE=OK_WITH_WARN")
        return 0
    print("SMOKE=FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

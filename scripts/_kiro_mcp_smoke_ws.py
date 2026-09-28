"""Smoke Kiro MCP from a known-good A/B with-workspace."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WS = (
    ROOT
    / ".ab_workspaces"
    / "kiro_ab_dev"
    / "20260909T170339Z_complex_retrieval"
    / "with"
)
KIRO = Path(r"C:\Users\usman\AppData\Local\Kiro-Cli\kiro-cli.exe")
MCP = Path.home() / ".local" / "bin" / "scubiee-mcp.EXE"


def main() -> int:
    for scope in ([], ["--workspace"]):
        for key, val in (
            ("mcp.loadedBefore", "false"),
            ("mcp.initTimeout", "90"),
            ("mcp.noInteractiveTimeout", "90"),
        ):
            subprocess.run(
                [str(KIRO), "settings", *scope, key, val],
                cwd=str(ROOT),
                check=False,
                capture_output=True,
            )

    live = json.loads((ROOT / ".scubiee" / "id.json").read_text(encoding="utf-8"))[
        "project_id"
    ]
    key = ""
    for line in (ROOT / ".env").read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("KIRO_API_KEY="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")

    agent = WS / ".kiro" / "agents" / "ab_dev_with.json"
    cfg = json.loads(agent.read_text(encoding="utf-8"))
    cfg["includeMcpJson"] = False
    srv = cfg.setdefault("mcpServers", {}).setdefault("scubiee", {})
    srv["command"] = str(MCP).replace("\\", "/")
    srv["disabled"] = False
    envp = srv.setdefault("env", {})
    envp.update(
        {
            "CTX_REPO": str(WS).replace("\\", "/"),
            "CTX_PROJECT_ID": live,
            "CTX_ENGINE_URL": "http://127.0.0.1:8765",
            "CTX_ENGINE_IDLE_S": "3600",
            "CTX_MCP_CLIENT": "kiro",
            "CTX_MCP_SURFACE": "phase",
            "CTX_MCP_EXPERIMENT": "ship",
            "CTX_TRACE_ENGINE": "composite_v1",
            "CTX_BACKGROUND_SYNC": "0",
            "CTX_AUTO_INDEX": "0",
            "PYTHONUTF8": "1",
        }
    )
    agent.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    drop = {k for k in os.environ if k.startswith("CURSOR_") or k.startswith("__CURSOR")}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env["KIRO_API_KEY"] = key
    env["CTX_ENGINE_IDLE_S"] = "3600"
    env["PATH"] = str(Path.home() / ".local" / "bin") + os.pathsep + env.get("PATH", "")

    listed = subprocess.check_output(
        [str(KIRO), "settings", "list", "--format", "json"],
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    print("settings", listed.strip())
    print("cwd", WS)

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
        cwd=str(WS),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    print("elapsed", round(time.time() - t0, 1), "rc", proc.returncode)
    clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", out)
    for ln in [x for x in clean.splitlines() if x.strip()][-25:]:
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

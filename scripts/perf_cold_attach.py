"""PERF scan: cold-attach gate + first few map latencies (engine warming)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from mcp_stdio_client import McpStdioClient  # noqa: E402

PID = "ce_3536ac8e8e83bb8e4d888db37847729c"
REPO = str(ROOT).replace("\\", "/")


def main() -> int:
    cfg = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    e = cfg["mcpServers"]["scubiee"]
    env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    env.update(e.get("env") or {})
    env.pop("PYTHONPATH", None)
    c = McpStdioClient(e["command"], e.get("args", []))
    c.env = env
    with c:
        t = time.perf_counter()
        c.call_text("gate", project_id=PID)
        print(f"gate {(time.perf_counter() - t) * 1000:.0f}ms", flush=True)
        for i in range(6):
            t = time.perf_counter()
            try:
                m = json.loads(c.call_text(
                    "map",
                    query="engine warm contract lifecycle idle standby enforce_mcp_warm_contract",
                    project_id=PID, path=REPO,
                ))
            except Exception as exc:  # noqa: BLE001
                m = {"ok": False, "error": repr(exc)}
            ms = (time.perf_counter() - t) * 1000
            print(f"map#{i} {ms:.0f}ms ok={m.get('ok')} err={m.get('error')} "
                  f"cards={len(m.get('cards') or [])}", flush=True)
            time.sleep(2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

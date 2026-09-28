"""Live proof for BUG-B (gate wrong project_id) and BUG-C (missing-arg envelope)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from mcp_stdio_client import McpStdioClient  # noqa: E402

PID = "ce_3536ac8e8e83bb8e4d888db37847729c"
REPO = str(ROOT).replace("\\", "/")


def _client():
    cfg = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    e = cfg["mcpServers"]["scubiee"]
    env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    env.update(e.get("env") or {})
    env.pop("PYTHONPATH", None)
    c = McpStdioClient(e["command"], e.get("args", []))
    c.env = env
    return c


def main() -> int:
    with _client() as c:
        c.call_text("gate", project_id=PID)
        print("=== BUG-B: gate project_id variants ===", flush=True)
        for label, kw in [
            ("wrong id", {"project_id": "ce_deadbeef"}),
            ("empty id", {"project_id": ""}),
            ("good id", {"project_id": PID}),
        ]:
            txt = c.call_text("gate", **kw)
            print(f"  {label:<9} -> {txt.splitlines()[0][:80]!r}", flush=True)

        print("\n=== BUG-B: status(detail=gate) wrong id ===", flush=True)
        print("  " + c.call_text("status", project_id="ce_deadbeef", detail="gate")[:40], flush=True)

        print("\n=== BUG-C: missing/empty required args -> uniform {ok:false} ===", flush=True)
        cases = [
            ("map no query", "map", {"project_id": PID, "path": REPO}),
            ("map empty query", "map", {"query": "", "project_id": PID, "path": REPO}),
            ("pack no query", "pack_context", {"seed_file": "packages/pipeline/server.py",
                                               "project_id": PID, "path": REPO}),
            ("pack empty query", "pack_context", {"query": "", "seed_file": "packages/pipeline/server.py",
                                                  "project_id": PID, "path": REPO}),
        ]
        for label, tool, kw in cases:
            txt = c.call_text(tool, **kw)
            try:
                o = json.loads(txt)
                shape = f"ok={o.get('ok')} error={o.get('error')!r}"
            except json.JSONDecodeError:
                shape = f"NON-JSON: {txt[:70]!r}"
            print(f"  {label:<18} -> {shape}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

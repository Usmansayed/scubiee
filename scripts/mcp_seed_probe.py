"""Does pack_context accept map's own suggested_seeds? Try every seed spelling."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from mcp_stdio_client import McpStdioClient  # noqa: E402

PID = "ce_3536ac8e8e83bb8e4d888db37847729c"
REPO = str(ROOT).replace("\\", "/")


def _client() -> McpStdioClient:
    cfg = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    e = cfg["mcpServers"]["scubiee"]
    env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    env.update(e.get("env") or {})
    env.pop("PYTHONPATH", None)
    c = McpStdioClient(e["command"], e.get("args", []))
    c.env = env
    return c


def call(c, tool, **a):
    t0 = time.perf_counter()
    try:
        o = json.loads(c.call_text(tool, **a))
    except Exception as exc:  # noqa: BLE001
        o = {"ok": False, "error": repr(exc)}
    ms = round((time.perf_counter() - t0) * 1000, 1)
    return o, ms


def main() -> int:
    with _client() as c:
        c.call_text("gate", project_id=PID)
        for _ in range(30):
            s = json.loads(c.call_text("status", project_id=PID, detail="full"))
            if s.get("embedder_loaded") or (s.get("warm_wait") or {}).get("done"):
                break
            time.sleep(4)
        m, _ = call(c, "map",
                    query="graph catch-up merge child process graph_merge_worker start_graph_merge "
                          "commit keeper rename graph.json build_merge dedup",
                    project_id=PID, path=REPO)
        seed = (m.get("suggested_seeds") or [None])[0]
        print("suggested_seed:", json.dumps(seed), flush=True)
        if not seed:
            return 1
        loc = seed.get("loc") or ""
        line = int(re.search(r":(\d+)", loc).group(1)) if re.search(r":(\d+)", loc) else 0
        q = "child graph merge commit on keeper, atomic rename graph.json, graph_pending per path"
        variants = [
            ("symbol only (line=0)", dict(seed_file=seed["file"], seed_symbol=seed["symbol"], seed_line=0)),
            ("line only (no symbol)", dict(seed_file=seed["file"], seed_line=line)),
            ("symbol + line from loc", dict(seed_file=seed["file"], seed_symbol=seed["symbol"], seed_line=line)),
            ("file only", dict(seed_file=seed["file"])),
        ]
        for label, kw in variants:
            o, ms = call(c, "pack_context", query=q, project_id=PID, path=REPO, mode="lean", **kw)
            hot = o.get("heatmap_n")
            if hot is None:
                hm = o.get("heatmap") or o.get("hot") or []
                hot = len(hm) if isinstance(hm, list) else "?"
            print(f"  {label:<26} ok={o.get('ok')} hot={hot} thin={o.get('thin')} "
                  f"err={o.get('error')} {ms}ms", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

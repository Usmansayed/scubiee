"""Is 'seed not found' specific to newly-added files, or any map seed?"""

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
    try:
        return json.loads(c.call_text(tool, **a))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": repr(exc)}


QUERIES = [
    ("old file: mcp_locate map_impl", "mcp_locate map_impl map result cache token generation "
     "dense D_channel_best retrieve pack_context"),
    ("old file: incremental_sync", "incremental_sync hot lane force_files chunk merkle diff "
     "embed_records upsert vectors publish"),
    ("old file: server EngineHTTPServer", "EngineHTTPServer handle_error ConnectionAbortedError "
     "_json wfile write server run"),
    ("new file: graph_merge_worker", "graph_merge_worker start_graph_merge child process merge "
     "commit keeper rename graph.json"),
    ("new file: fast_stat", "fast_stat GetFileAttributesExW PyDLL GIL cached_resolve rebuild_universe"),
]


def main() -> int:
    with _client() as c:
        c.call_text("gate", project_id=PID)
        for _ in range(30):
            s = call(c, "status", project_id=PID, detail="full")
            if s.get("embedder_loaded") or (s.get("warm_wait") or {}).get("done"):
                break
            time.sleep(4)
        for label, q in QUERIES:
            m = call(c, "map", query=q, project_id=PID, path=REPO)
            seed = (m.get("suggested_seeds") or [None])[0]
            if not seed:
                print(f"{label:<34} no seed", flush=True)
                continue
            loc = seed.get("loc") or ""
            line = int(re.search(r":(\d+)", loc).group(1)) if re.search(r":(\d+)", loc) else 0
            p = call(c, "pack_context", query=q, project_id=PID, path=REPO, mode="lean",
                     seed_file=seed["file"], seed_symbol=seed.get("symbol") or "", seed_line=line)
            hm = p.get("heatmap") or p.get("hot") or []
            hot = len(hm) if isinstance(hm, list) else p.get("heatmap_n")
            print(f"{label:<34} seed={seed['file'].split('/')[-1]}::{seed.get('symbol')} "
                  f"line={line} -> pack ok={p.get('ok')} hot={hot} err={p.get('error')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

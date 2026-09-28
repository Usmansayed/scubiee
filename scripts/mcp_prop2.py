"""New-file propagation: disk-only (newcomer scan) vs explicit /v1/dirty (IDE lane).

Answers: when a NEW file is created, how fast does it become visible to search /
map / pack — and does the IDE's /v1/dirty hint make it instant?
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from mcp_stdio_client import McpStdioClient  # noqa: E402

PID = "ce_3536ac8e8e83bb8e4d888db37847729c"
REPO = str(ROOT).replace("\\", "/")
BASE = "http://127.0.0.1:8765"


def http(method: str, path: str, body=None, timeout=30.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _client() -> McpStdioClient:
    cfg = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    e = cfg["mcpServers"]["scubiee"]
    env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    env.update(e.get("env") or {})
    env.pop("PYTHONPATH", None)
    argv = json.loads(env["CTX_MCP_BRIDGE_SPAWN_JSON"])
    c = McpStdioClient(argv[0], argv[1:])
    c.env = env
    return c


def poll(fn, timeout_s, interval=0.4):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            if fn():
                return time.time() - t0
        except Exception:  # noqa: BLE001
            pass
        time.sleep(interval)
    return None


def search_has(token, rel):
    hits = http("POST", "/v1/search", {"query": token, "top_k": 12, "path": REPO}).get("hits") or []
    return any(str(h.get("file") or "").replace("\\", "/") == rel for h in hits)


def main() -> int:
    stamp = int(time.time())
    created = []
    lines = []

    def line(s):
        print(s, flush=True)
        lines.append(s)

    # Attach the MCP client FIRST so the engine stays warm (idle standby stops
    # it ~10s after the last client leaves). Everything runs inside this session.
    with _client() as c:
        c.call_text("gate", project_id=PID)

        def mcp(tool, **a):
            try:
                return json.loads(c.call_text(tool, **a))
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": repr(exc)}

        # === A. NEW FILE, disk-only, explicit /v1/dirty hint (the IDE lane) ===
        tok = f"zzp2{stamp}dirty"
        rel = f"packages/pipeline/zz_prop2_{stamp}_dirty.py"
        p = ROOT / rel
        p.write_text(f'def {tok}_fn():\n    """{tok} via dirty hint."""\n    return 1\n', encoding="utf-8")
        created.append(p)
        http("POST", "/v1/dirty", {"paths": [rel], "path": REPO})
        secs = poll(lambda: search_has(f"{tok}_fn", rel), timeout_s=30)
        line(f"A. new file + /v1/dirty -> searchable: "
             f"{'%.0fms' % (secs*1000) if secs else 'MISS(>30s)'}")

        # === B. NEW FILE, disk-only, NO hint (rely on newcomer scan) ===
        tok2 = f"zzp2{stamp}disk"
        rel2 = f"packages/pipeline/zz_prop2_{stamp}_disk.py"
        p2 = ROOT / rel2
        p2.write_text(f'def {tok2}_fn():\n    """{tok2} disk only."""\n    return 1\n', encoding="utf-8")
        created.append(p2)
        # do NOT call /v1/dirty. Newcomer scan default is 600s; measure up to 90s.
        secs2 = poll(lambda: search_has(f"{tok2}_fn", rel2), timeout_s=90, interval=1.0)
        line(f"B. new file, disk-only (no hint) -> searchable: "
             f"{'%.1fs' % secs2 if secs2 else 'MISS(>90s, newcomer scan is 600s)'}")

        def map_has():
            m = mcp("map", query=f"{tok}_fn via dirty hint zz prop2", project_id=PID, path=REPO)
            return f"{tok}_fn" in json.dumps(m) or rel in json.dumps(m)
        smap = poll(map_has, timeout_s=60, interval=1.5)
        line(f"C. dirty-hinted file -> map surfaces symbol: "
             f"{'%.1fs' % smap if smap else 'MISS(>60s)'}")

        def pack_ok():
            pk = mcp("pack_context", query=f"{tok}_fn via dirty hint",
                     seed_file=rel, seed_symbol=f"{tok}_fn", seed_line=1,
                     project_id=PID, path=REPO, mode="lean")
            return not pk.get("error") and bool(pk.get("heatmap") or pk.get("seed_coverage"))
        spack = poll(pack_ok, timeout_s=60, interval=1.5)
        line(f"D. dirty-hinted file -> pack seed resolves: "
             f"{'%.1fs' % spack if spack else 'MISS(>60s, graph catch-up lane)'}")

    for pp in created:
        pp.unlink(missing_ok=True)
    for stray in (ROOT / "packages" / "pipeline").glob("zz_prop2_*.py"):
        stray.unlink(missing_ok=True)

    Path(os.environ["TEMP"], "prop2.txt").write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

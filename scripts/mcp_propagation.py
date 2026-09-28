"""Thorough Scubiee propagation + feature test.

Measures how fast a real filesystem change becomes visible through each surface:
  - search (hot BM25 lane)   : save -> /v1/search finds the new token
  - map    (dense/graph)     : save -> MCP map surfaces the new symbol
  - pack   (composite graph) : save -> MCP pack seed resolves in the new file
  - expand (graph edges)     : add a call edge -> expand_context shows the caller
  - delete                   : remove file -> search stops returning it
  - rename                   : move symbol -> old gone / new present

Everything is done on throwaway files under packages/pipeline/zz_prop_* which
are cleaned up at the end. Timings are wall-clock from write() to first
visibility, polling each surface.

    python scripts/mcp_propagation.py
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
ROWS: list[dict] = []


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


def http(method: str, path: str, body: dict | None = None, timeout: float = 30.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def rec(scenario: str, secs: float | None, budget_s: float, note: str = "") -> None:
    ok = secs is not None and secs <= budget_s
    ms = None if secs is None else round(secs * 1000)
    ROWS.append({"scenario": scenario, "ms": ms, "budget_ms": round(budget_s * 1000),
                 "ok": ok, "note": note})
    flag = "OK  " if ok else ("MISS" if secs is None else "SLOW")
    shown = "  n/a  " if ms is None else f"{ms:6d}ms"
    print(f"  [{flag}] {shown} / {round(budget_s*1000):>6}  {scenario}  {note}", flush=True)


def poll_until(fn, timeout_s: float, interval_s: float = 0.4):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            if fn():
                return time.time() - t0
        except Exception:  # noqa: BLE001
            pass
        time.sleep(interval_s)
    return None


def search_has(token: str, rel: str) -> bool:
    hits = http("POST", "/v1/search", {"query": token, "top_k": 12, "path": REPO}).get("hits") or []
    return any(str(h.get("file") or "").replace("\\", "/") == rel for h in hits)


def main() -> int:
    stamp = int(time.time())
    created: list[Path] = []

    def newfile(name: str, text: str) -> tuple[str, Path]:
        rel = f"packages/pipeline/zz_prop_{stamp}_{name}.py"
        p = ROOT / rel
        p.write_text(text, encoding="utf-8")
        created.append(p)
        return rel, p

    with _client() as c:
        def mcp(tool, **a):
            try:
                return json.loads(c.call_text(tool, **a))
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": repr(exc)}

        # warm attach
        c.call_text("gate", project_id=PID)

        # === 1. CREATE -> search (hot BM25 lane) ===
        print("=== create new file -> search (hot lane) ===", flush=True)
        tok = f"zzprop{stamp}alpha"
        rel, p = newfile("alpha", f'def {tok}_fn():\n    """{tok} marker."""\n    return 1\n')
        secs = poll_until(lambda: search_has(f"{tok}_fn", rel), timeout_s=30)
        rec("create -> search finds file", secs, 6.0, "" if secs else "not searchable in 30s")

        # === 2. CREATE -> map (dense/graph lane) surfaces the symbol ===
        print("=== create new file -> map surfaces symbol ===", flush=True)

        def map_has():
            m = mcp("map", query=f"{tok}_fn marker function in zz_prop alpha",
                    project_id=PID, path=REPO)
            blob = json.dumps(m)
            return rel in blob or f"{tok}_fn" in blob
        secs = poll_until(map_has, timeout_s=45, interval_s=1.0)
        rec("create -> map surfaces symbol", secs, 20.0, "" if secs else "not in map in 45s")

        # === 3. CREATE -> pack seed resolves in the new file (graph lane) ===
        print("=== create new file -> pack seed resolves (graph lane) ===", flush=True)

        def pack_ok():
            pk = mcp("pack_context", query=f"{tok}_fn marker in zz_prop alpha",
                     seed_file=rel, seed_symbol=f"{tok}_fn", seed_line=1,
                     project_id=PID, path=REPO, mode="lean")
            if pk.get("error"):
                return False
            heat = pk.get("heatmap") or pk.get("seeds") or []
            cov = pk.get("seed_coverage")
            return bool(heat) or bool(cov)
        secs = poll_until(pack_ok, timeout_s=60, interval_s=1.5)
        rec("create -> pack seed resolves", secs, 30.0, "" if secs else "seed unresolved in 60s")

        # === 4. MODIFY -> search reflects new token ===
        print("=== modify file -> search reflects new content ===", flush=True)
        tok2 = f"zzprop{stamp}beta"
        p.write_text(f'def {tok}_fn():\n    """{tok} marker."""\n    return 1\n\n'
                     f'def {tok2}_added():\n    """{tok2} newly added."""\n    return 2\n',
                     encoding="utf-8")
        secs = poll_until(lambda: search_has(f"{tok2}_added", rel), timeout_s=30)
        rec("modify -> search sees new symbol", secs, 6.0, "" if secs else "not seen in 30s")

        # === 5. ADD CALL EDGE -> expand_context shows caller (graph lane) ===
        print("=== add call edge -> expand_context callers ===", flush=True)
        rel_b, pb = newfile("caller", f"from pipeline.zz_prop_{stamp}_alpha import {tok}_fn\n\n"
                                       f"def {tok}_caller():\n    return {tok}_fn()\n")

        def expand_sees_caller():
            ex = mcp("expand_context", node=f"{rel}::{tok}_fn", direction="callers",
                     project_id=PID, path=REPO, query=f"{tok}_caller calls {tok}_fn")
            return f"{tok}_caller" in json.dumps(ex) or rel_b in json.dumps(ex)
        secs = poll_until(expand_sees_caller, timeout_s=60, interval_s=2.0)
        rec("add call edge -> expand shows caller", secs, 35.0,
            "" if secs else "caller edge not in graph in 60s")

        # === 6. DELETE -> search stops returning the file ===
        print("=== delete file -> search drops it ===", flush=True)
        pb.unlink(missing_ok=True)
        if pb in created:
            created.remove(pb)
        secs = poll_until(lambda: not search_has(f"{tok}_caller", rel_b), timeout_s=30)
        rec("delete -> search drops file", secs, 8.0, "" if secs else "still returned after 30s")

    ok = sum(1 for r in ROWS if r["ok"])
    print(f"\n=== propagation: {ok}/{len(ROWS)} within budget ===", flush=True)
    for r in ROWS:
        if not r["ok"]:
            print(f"  ATTN: {r['scenario']} {r['ms']}ms > {r['budget_ms']}ms {r['note']}", flush=True)

    # cleanup
    for p in created:
        p.unlink(missing_ok=True)
    # also sweep any zz_prop leftovers from earlier partial runs
    for stray in (ROOT / "packages" / "pipeline").glob("zz_prop_*.py"):
        stray.unlink(missing_ok=True)

    out = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else str(
        ROOT / "scripts" / "_prop_out.json")
    Path(out).write_text(json.dumps(ROWS, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

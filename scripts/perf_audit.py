"""Comprehensive perf audit: measure every latency-bearing operation with an
expected/reasonable budget and a pass/fail verdict. Emits a markdown table.

Runs against a warm engine + one MCP stdio session. HTTP + MCP + propagation.

    python scripts/perf_audit.py [--json out.json] [--md out.md]
"""

from __future__ import annotations

import json
import os
import statistics
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


def _client():
    cfg = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    e = cfg["mcpServers"]["scubiee"]
    env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    env.update(e.get("env") or {})
    env.pop("PYTHONPATH", None)
    # The mcp.json ``command`` is a no-op stub (``cmd /c exit 0``); the real MCP
    # server is launched via CTX_MCP_BRIDGE_SPAWN_JSON. Honor it so the harness
    # spawns the actual stdio worker instead of a process that exits at once.
    spawn = env.get("CTX_MCP_BRIDGE_SPAWN_JSON")
    if spawn:
        argv = json.loads(spawn)
        command, args = argv[0], argv[1:]
    else:
        command, args = e["command"], e.get("args", [])
    c = McpStdioClient(command, args)
    c.env = env
    return c


def http(method: str, path: str, body: dict | None = None, timeout: float = 60.0):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def record(scenario: str, ms: float, budget_ms: float, note: str = "") -> None:
    ok = ms <= budget_ms
    ROWS.append({"scenario": scenario, "ms": round(ms, 1), "budget_ms": budget_ms,
                 "acceptable": ok, "note": note})
    flag = "OK " if ok else "SLOW"
    print(f"  [{flag}] {ms:8.1f}ms / {budget_ms:>6.0f}  {scenario}  {note}", flush=True)


def timeit(fn):
    t0 = time.perf_counter()
    out = fn()
    return (time.perf_counter() - t0) * 1000, out


def mcp_call(c, tool, **a):
    def _f():
        try:
            return json.loads(c.call_text(tool, **a))
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": repr(exc)}
    return timeit(_f)


def main() -> int:
    print("=== HTTP GET endpoints ===", flush=True)
    for path, budget in [("/health", 50), ("/v1/status", 300), ("/v1/settings", 200),
                         ("/v1/resources", 300), ("/dashboard", 200)]:
        try:
            ms, _ = timeit(lambda p=path: http("GET", p) if p != "/dashboard"
                           else urllib.request.urlopen(BASE + p, timeout=20).read())
        except Exception as exc:  # noqa: BLE001
            ms = -1
            record(f"GET {path}", 0, budget, f"ERR {exc}")
            continue
        record(f"GET {path}", ms, budget)

    print("=== HTTP search (warm/repeat/large) ===", flush=True)
    q = "graph merge worker commit keeper rename graph.json"
    ms, _ = timeit(lambda: http("POST", "/v1/search", {"query": q, "top_k": 8, "path": REPO}, 120))
    record("POST /v1/search first", ms, 3000)
    for i in range(3):
        ms, _ = timeit(lambda: http("POST", "/v1/search", {"query": q, "top_k": 8, "path": REPO}))
        record(f"POST /v1/search repeat#{i}", ms, 800)
    ms, _ = timeit(lambda: http("POST", "/v1/search",
                   {"query": "engine keeper watchdog lifecycle warm contract idle standby "
                             "publish generation hot lane graph catch-up embedder prewarm",
                    "top_k": 20, "path": REPO}))
    record("POST /v1/search large query top_k=20", ms, 1500)

    print("=== HTTP structural endpoints ===", flush=True)
    for path, body, budget in [
        ("/v1/grep", {"pattern": "def build_merge", "path": REPO}, 1500),
        ("/v1/grep_ident", {"ident": "start_graph_merge", "path": REPO}, 1500),
        ("/v1/outline", {"file": "packages/pipeline/graph_merge_worker.py", "path": REPO}, 800),
        ("/v1/read_span", {"file": "packages/pipeline/graph_merge_worker.py",
                           "start_line": 1, "end_line": 40, "path": REPO}, 500),
        ("/v1/graph_neighbors", {"paths": ["packages/pipeline/sync_loop.py"], "path": REPO}, 1500),
        ("/v1/query_graph", {"question": "how does the keeper publish generations", "path": REPO}, 3000),
        ("/v1/follow_imports", {"file": "packages/pipeline/graph_merge_worker.py", "path": REPO}, 1500),
    ]:
        try:
            ms, out = timeit(lambda p=path, b=body: http("POST", p, b, 30))
            record(f"POST {path}", ms, budget,
                   "" if isinstance(out, dict) and out.get("ok", True) else f"({out.get('error','')[:40]})")
        except Exception as exc:  # noqa: BLE001
            record(f"POST {path}", 0, budget, f"ERR {str(exc)[:50]}")

    print("=== MCP tools (warm session) ===", flush=True)
    with _client() as c:
        ms, _ = mcp_call(c, "gate", project_id=PID)
        record("MCP gate (attach)", ms, 2000)
        ms, _ = mcp_call(c, "status", project_id=PID, detail="full")
        record("MCP status full", ms, 1500)

        mq = ("graph catch-up child process graph_merge_worker start_graph_merge commit "
              "keeper rename graph.json build_merge dedup")
        ms, m = mcp_call(c, "map", query=mq, project_id=PID, path=REPO)
        record("MCP map first (cold topic)", ms, 3000)
        seeds = m.get("suggested_seeds") or []
        for i in range(3):
            ms, _ = mcp_call(c, "map", query=mq, project_id=PID, path=REPO)
            record(f"MCP map repeat#{i} (cache)", ms, 800)

        if seeds:
            s0 = seeds[0]
            import re
            ln = int(re.search(r":(\d+)", s0.get("loc") or "").group(1)) if re.search(r":(\d+)", s0.get("loc") or "") else 0
            pq = "child process graph merge commit on the keeper, atomic rename, graph_pending per path"
            ms, _ = mcp_call(c, "pack_context", query=pq, seed_file=s0["file"],
                             seed_symbol=s0.get("symbol") or "", seed_line=ln,
                             project_id=PID, path=REPO, mode="lean")
            record("MCP pack first (builds composite edges)", ms, 2500)
            for i in range(3):
                ms, _ = mcp_call(c, "pack_context", query=pq, seed_file=s0["file"],
                                 seed_symbol=s0.get("symbol") or "", seed_line=ln,
                                 project_id=PID, path=REPO, mode="lean")
                record(f"MCP pack repeat#{i}", ms, 500)
            ms, _ = mcp_call(c, "pack_context", query=pq, seed_file=s0["file"],
                             seed_symbol=s0.get("symbol") or "", seed_line=ln,
                             project_id=PID, path=REPO, mode="lean", include_bodies=1)
            record("MCP pack include_bodies", ms, 1500)
            node = f"{s0['file']}::{s0.get('symbol')}" if s0.get("symbol") else s0["file"]
            for d in ("callers", "callees", "effects", "config", "all"):
                ms, _ = mcp_call(c, "expand_context", node=node, direction=d,
                                 project_id=PID, path=REPO, query=pq)
                record(f"MCP expand_context {d}", ms, 600)
            ms, _ = mcp_call(c, "collect_hot_context", project_id=PID, path=REPO)
            record("MCP collect_hot_context", ms, 600)
        ms, _ = mcp_call(c, "workspace", action="show", project_id=PID, path=REPO)
        record("MCP workspace show", ms, 500)
        ms, _ = mcp_call(c, "expand", handle="packages/pipeline/graph_merge_worker.py:1-40",
                         project_id=PID, path=REPO)
        record("MCP expand file:lines", ms, 500)

    print("=== propagation: save small file -> searchable ===", flush=True)
    stamp = int(time.time())
    rel = f"packages/pipeline/zz_audit_{stamp}.py"
    fp = ROOT / rel
    tok = f"zzaudit{stamp}"
    fp.write_text(f'def {tok}_fn():\n    """{tok}"""\n    return 1\n', encoding="utf-8")
    try:
        t0 = time.time()
        found = None
        while time.time() - t0 < 30:
            hits = http("POST", "/v1/search", {"query": f"{tok}_fn", "top_k": 10, "path": REPO}).get("hits") or []
            if any(str(h.get("file") or "").replace("\\", "/") == rel for h in hits):
                found = (time.time() - t0) * 1000
                break
            time.sleep(0.5)
        record("save small file -> searchable", found if found else 30000, 5000,
               "" if found else "NOT searchable in 30s")
    finally:
        fp.unlink(missing_ok=True)

    ok = sum(1 for r in ROWS if r["acceptable"])
    slow = [r for r in ROWS if not r["acceptable"]]
    print(f"\n=== {ok}/{len(ROWS)} within budget; {len(slow)} slow ===", flush=True)
    for r in slow:
        print(f"  SLOW: {r['scenario']} {r['ms']}ms > {r['budget_ms']}ms {r['note']}", flush=True)

    if "--json" in sys.argv:
        Path(sys.argv[sys.argv.index("--json") + 1]).write_text(
            json.dumps(ROWS, indent=2), encoding="utf-8")
    if "--md" in sys.argv:
        lines = ["| scenario | measured (ms) | budget (ms) | acceptable |",
                 "|---|---|---|---|"]
        for r in ROWS:
            lines.append(f"| {r['scenario']} | {r['ms']} | {r['budget_ms']} | "
                         f"{'Y' if r['acceptable'] else '**N**'} {r['note']} |")
        Path(sys.argv[sys.argv.index("--md") + 1]).write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

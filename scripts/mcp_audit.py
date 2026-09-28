"""Exercise the Scubiee MCP tools (the 8 the IDE calls) through the real stdio
bridge and record latency + a correctness signal for each.

    python scripts/mcp_audit.py
"""

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
ROWS: list[dict] = []


def _client() -> McpStdioClient:
    cfg = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    e = cfg["mcpServers"]["scubiee"]
    env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    env.update(e.get("env") or {})
    env.pop("PYTHONPATH", None)
    spawn = env.get("CTX_MCP_BRIDGE_SPAWN_JSON")
    if spawn:
        argv = json.loads(spawn)
        command, args = argv[0], argv[1:]
    else:
        command, args = e["command"], e.get("args", [])
    c = McpStdioClient(command, args)
    c.env = env
    return c


def call(c: McpStdioClient, tool: str, **a):
    t0 = time.perf_counter()
    try:
        raw = c.call_text(tool, **a)
        ms = (time.perf_counter() - t0) * 1000
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            obj = {"_raw": raw}
    except Exception as exc:  # noqa: BLE001
        ms = (time.perf_counter() - t0) * 1000
        obj = {"ok": False, "error": repr(exc)}
    return ms, obj


def rec(scenario: str, ms: float, ok: bool, note: str = "") -> None:
    ROWS.append({"scenario": scenario, "ms": round(ms, 1), "ok": ok, "note": note})
    flag = "OK  " if ok else "BAD "
    print(f"  [{flag}] {ms:8.1f}ms  {scenario}  {note}", flush=True)


def _has(obj: dict, *keys: str) -> bool:
    return isinstance(obj, dict) and any(obj.get(k) for k in keys)


def main() -> int:
    out_lines: list[str] = []
    with _client() as c:
        tools = c.list_tools()
        print("tools:", tools, flush=True)
        rec("tools/list", 0, len(tools) >= 8, f"{len(tools)} tools: {tools}")

        # --- gate (attach) ---
        ms, g = call(c, "gate", project_id=PID)
        rec("gate (attach)", ms, _has(g, "ok", "ready", "warm_state", "gate"),
            f"warm={g.get('warm_state') or g.get('gate')}")

        # --- status ---
        ms, st = call(c, "status", project_id=PID, detail="full")
        rec("status full", ms, isinstance(st, dict) and not st.get("error"),
            f"keys={list(st)[:5]}")

        # --- map (soft/structural: dense code-vocab query) ---
        mq = ("graph catch-up child process graph_merge_worker start_graph_merge "
              "commit keeper rename graph.json build_merge dedup export to_json "
              "incremental sync loop batch prune sources")
        ms, m = call(c, "map", query=mq, project_id=PID, path=REPO)
        seeds = m.get("suggested_seeds") or m.get("seeds") or []
        cards = m.get("cards") or m.get("hits") or []
        rec("map first (cold topic)", ms, bool(seeds or cards),
            f"seeds={len(seeds)} cards={len(cards)}")
        out_lines.append("map suggested_seeds: " + json.dumps(seeds[:3], indent=2))

        # repeat (cache)
        for i in range(2):
            ms, _ = call(c, "map", query=mq, project_id=PID, path=REPO)
            rec(f"map repeat#{i} (cache)", ms, True)

        # --- pack (fold a seed into a denser pack query) ---
        packed_ok = False
        if seeds:
            s0 = seeds[0]
            sfile = s0.get("file") or ""
            ssym = s0.get("symbol") or ""
            loc = s0.get("loc") or ""
            mline = re.search(r":(\d+)", loc)
            sline = int(mline.group(1)) if mline else int(s0.get("line") or 0)
            pq = (f"graph catch-up on the keeper via {ssym or 'start_graph_merge'}: "
                  f"child process runs build_merge(dedup=True), atomic rename of "
                  f"graph.json, prune sources per batch in {sfile}")
            ms, p = call(c, "pack_context", query=pq, seed_file=sfile,
                         seed_symbol=ssym, seed_line=sline,
                         project_id=PID, path=REPO, mode="lean")
            heat = p.get("heatmap") or p.get("locs") or p.get("cards") or p.get("spans")
            thin = bool(p.get("thin"))
            packed_ok = bool(heat) and not p.get("error")
            rec("pack first (lean)", ms, packed_ok,
                f"thin={thin} heat={len(heat) if hasattr(heat,'__len__') else heat} "
                f"err={p.get('error')}")
            out_lines.append("pack keys: " + json.dumps(list(p)[:12]))

            for i in range(2):
                ms, _ = call(c, "pack_context", query=pq, seed_file=sfile,
                             seed_symbol=ssym, seed_line=sline,
                             project_id=PID, path=REPO, mode="lean")
                rec(f"pack repeat#{i}", ms, True)

            # bodies
            ms, pb = call(c, "collect_hot_context", project_id=PID, path=REPO)
            rec("collect_hot_context", ms, not pb.get("error"),
                f"keys={list(pb)[:6]}")

            # --- expand_context on the seed node ---
            node = f"{sfile}::{ssym}" if ssym else sfile
            for d in ("callers", "callees", "all"):
                ms, ex = call(c, "expand_context", node=node, direction=d,
                              project_id=PID, path=REPO, query=pq)
                rec(f"expand_context {d}", ms, not ex.get("error"),
                    f"keys={list(ex)[:5]}")
        else:
            rec("pack first (lean)", 0, False, "no seeds from map -> cannot pack")

        # --- workspace ---
        ms, ws = call(c, "workspace", action="show", project_id=PID, path=REPO)
        rec("workspace show", ms, not ws.get("error"), f"keys={list(ws)[:6]}")

        # --- expand (file:lines handle) ---
        ms, xf = call(c, "expand",
                      handle="packages/pipeline/graph_merge_worker.py:1-40",
                      project_id=PID, path=REPO)
        rec("expand file:lines", ms, not xf.get("error"), f"keys={list(xf)[:5]}")

    ok = sum(1 for r in ROWS if r["ok"])
    bad = [r for r in ROWS if not r["ok"]]
    print(f"\n=== MCP: {ok}/{len(ROWS)} tools returned usable output; {len(bad)} bad ===",
          flush=True)
    for r in bad:
        print(f"  BAD: {r['scenario']} {r['ms']}ms {r['note']}", flush=True)

    Path(sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv
         else str(ROOT / "scripts" / "_mcp_audit_out.json")).write_text(
        json.dumps({"rows": ROWS, "detail": out_lines}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Exercise every Scubiee MCP tool through the real stdio bridge, many ways.

Opens ONE MCP session from .cursor/mcp.json (as Cursor/Kiro do), warms it, then
runs a battery: gate, status, map (cold/refined/needle/vague), pack_context
(lean/multi-seed/thin/include_bodies/bad-seed), expand_context (callers/callees/
effects/config/broad), collect_hot_context, workspace (show/pin/clear), expand
(good/bad handle). Prints per-call ok/ms and a short shape summary, then a table.

    python scripts/mcp_experiment.py [--json out.json]
"""

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
ROWS: list[dict] = []


def _client() -> McpStdioClient:
    cfg = json.loads((ROOT / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    entry = cfg["mcpServers"]["scubiee"]
    env = {k: v for k, v in os.environ.items() if k.upper() != "PYTHONPATH"}
    env.update(entry.get("env") or {})
    env.pop("PYTHONPATH", None)
    c = McpStdioClient(entry["command"], entry.get("args", []))
    c.env = env
    c.stderr_path = str(Path(os.environ.get("TEMP", ".")) / "mcp_experiment_bridge.log")
    return c


def run(c: McpStdioClient, label: str, tool: str, **args) -> dict:
    t0 = time.perf_counter()
    try:
        text = c.call_text(tool, **args)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            obj = {"_nonjson": True, "text": text[:200]}
    except Exception as exc:  # noqa: BLE001
        ms = round((time.perf_counter() - t0) * 1000, 1)
        obj = {"_error": repr(exc)}
    row = {"label": label, "tool": tool, "ms": ms, "obj": obj}
    ROWS.append(row)
    print(f"[{ms:8.1f}ms] {label:<34} {_summ(tool, obj)}", flush=True)
    return obj


def _summ(tool: str, o: dict) -> str:
    if "_error" in o:
        return f"ERROR {o['_error'][:90]}"
    if o.get("_nonjson"):
        return f"non-json: {o['text'][:80]}"
    ok = o.get("ok")
    err = o.get("error")
    bits = [f"ok={ok}"]
    if err:
        bits.append(f"error={err}")
    for k in ("warm_state", "cache", "heatmap_n", "count", "agreement_n", "state",
              "seed", "seed_used", "thin", "generation", "warm_wait", "should_retry"):
        if k in o:
            v = o[k]
            if isinstance(v, dict):
                v = v.get("done", v)
            bits.append(f"{k}={v}")
    for key in ("cards", "hot", "chain", "pack", "delta", "spans", "hits", "seeds",
                "suggested_seeds", "pins", "heatmap"):
        v = o.get(key)
        if isinstance(v, list):
            bits.append(f"{key}[{len(v)}]")
    return " ".join(bits)


def warm(c: McpStdioClient) -> None:
    run(c, "gate (attach)", "gate", project_id=PID)
    # Poll status.warm_wait until dense is ready (documented agent behavior).
    t0 = time.time()
    while time.time() - t0 < 150:
        o = run(c, "status (warm poll)", "status", project_id=PID, detail="full")
        ww = o.get("warm_wait") or {}
        if ww.get("done") or o.get("embedder_loaded") or o.get("dense_ready"):
            break
        time.sleep(4)


def seeds_from(o: dict) -> list[dict]:
    ss = o.get("suggested_seeds") or o.get("seeds") or []
    out = []
    for s in ss[:3]:
        if isinstance(s, dict) and s.get("file"):
            out.append({"file": s["file"], "symbol": s.get("symbol") or "", "line": s.get("line") or 0})
    return out


def main() -> int:
    print(f"repo={REPO}\nproject={PID}\n", flush=True)
    with _client() as c:
        tools = c.list_tools()
        print(f"tools/list -> {tools}\n", flush=True)
        warm(c)

        print("\n=== map (varied queries) ===", flush=True)
        m_cold = run(c, "map cold: graph catch-up child", "map",
                     query="graph catch-up merge runs off the keeper in a child process "
                           "graph_merge_worker start_graph_merge commit rename graph.json",
                     project_id=PID, path=REPO)
        run(c, "map needle-ish: fast_stat GIL", "map",
            query="fast_stat GetFileAttributesExW PyDLL GIL convoy root_probe rebuild_universe stat",
            project_id=PID, path=REPO)
        run(c, "map vague one-liner", "map", query="where is the thing that saves stuff",
            project_id=PID, path=REPO)
        m_refine = run(c, "map refined: prewarm phase", "map",
                       query="prewarm phase stale warm_autoload set_phase write_phase_file "
                             "hung_prewarm_should_abort watchdog restart embedder_loaded",
                       project_id=PID, path=REPO)
        run(c, "map repeat (cache?)", "map",
            query="graph catch-up merge runs off the keeper in a child process "
                  "graph_merge_worker start_graph_merge commit rename graph.json",
            project_id=PID, path=REPO)

        seeds = seeds_from(m_cold) or seeds_from(m_refine)
        print(f"\nsuggested_seeds -> {seeds}\n", flush=True)

        print("=== pack_context (varied) ===", flush=True)
        if seeds:
            s0 = seeds[0]
            run(c, "pack lean single-seed", "pack_context",
                query="child process graph merge commit on the keeper, atomic rename, "
                      "graph_pending paid off per path",
                seed_file=s0["file"], seed_symbol=s0["symbol"], seed_line=s0["line"],
                project_id=PID, path=REPO, mode="lean")
            if len(seeds) >= 2:
                s1 = seeds[1]
                run(c, "pack multi-seed (agreement)", "pack_context",
                    query="graph catch-up child worker commit keeper rename dedup build_merge",
                    seed_file=s0["file"], seed_symbol=s0["symbol"], seed_line=s0["line"],
                    seed2_file=s1["file"], seed2_symbol=s1["symbol"], seed2_line=s1["line"],
                    project_id=PID, path=REPO, mode="lean")
            run(c, "pack include_bodies=1", "pack_context",
                query="child process graph merge commit keeper",
                seed_file=s0["file"], seed_symbol=s0["symbol"], seed_line=s0["line"],
                project_id=PID, path=REPO, mode="lean", include_bodies=1)
            run(c, "pack policy=broad", "pack_context",
                query="child process graph merge commit keeper", seed_file=s0["file"],
                seed_symbol=s0["symbol"], seed_line=s0["line"], project_id=PID, path=REPO,
                mode="lean", policy="broad")
        run(c, "pack bad seed (empty)", "pack_context", query="x", seed_file="",
            project_id=PID, path=REPO, mode="lean")
        run(c, "pack seed=_ (forbidden)", "pack_context", query="x", seed_file="_",
            project_id=PID, path=REPO, mode="lean")

        print("\n=== expand_context (directions) ===", flush=True)
        node = f"{seeds[0]['file']}::{seeds[0]['symbol']}" if seeds and seeds[0]["symbol"] else (seeds[0]["file"] if seeds else "packages/pipeline/sync_loop.py")
        for direction in ("callers", "callees", "effects", "config", "broad", "all"):
            run(c, f"expand {direction}", "expand_context",
                node=node, direction=direction, project_id=PID, path=REPO,
                query="graph catch-up keeper child commit")
        run(c, "expand with_bodies", "expand_context", node=node, direction="callers",
            with_bodies=True, project_id=PID, path=REPO, query="graph catch-up keeper child")

        print("\n=== collect_hot_context ===", flush=True)
        run(c, "collect (threshold)", "collect_hot_context", project_id=PID, path=REPO)
        ids = ""
        if seeds and seeds[0]["symbol"]:
            ids = f"{seeds[0]['file']}::{seeds[0]['symbol']}"
        if ids:
            run(c, "collect explicit ids", "collect_hot_context", ids=ids, project_id=PID, path=REPO)

        print("\n=== workspace ===", flush=True)
        run(c, "workspace show", "workspace", action="show", project_id=PID, path=REPO)
        run(c, "workspace pin", "workspace", action="pin",
            path="packages/pipeline/graph_merge_worker.py", project_id=PID)
        run(c, "workspace show (after pin)", "workspace", action="show", project_id=PID, path=REPO)

        print("\n=== expand (span handles) ===", flush=True)
        run(c, "expand bad handle", "expand", handle="does-not-exist", project_id=PID, path=REPO)
        run(c, "expand file:lines", "expand",
            handle="packages/pipeline/graph_merge_worker.py:1-40", project_id=PID, path=REPO)

    print("\n\n=== SUMMARY ===", flush=True)
    print(f"{'ms':>9}  {'tool':<18} label", flush=True)
    for r in ROWS:
        print(f"{r['ms']:>9.1f}  {r['tool']:<18} {r['label']}", flush=True)
    if "--json" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--json") + 1])
        out.write_text(json.dumps(ROWS, indent=2, default=str), encoding="utf-8")
        print(f"\nwrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

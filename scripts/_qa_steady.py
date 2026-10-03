from __future__ import annotations
import os, time
os.environ.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")
os.environ.setdefault("CTX_REPO", r"C:\Users\usman\Downloads\context-engine")
os.environ.setdefault("CTX_PROJECT_ID", "ce_3536ac8e8e83bb8e4d888db37847729c")
os.environ["MINI_REPO"] = os.environ["CTX_REPO"]

import pipeline.map_v3_helpers as mv
from pipeline import map_v3_server as srv

# Simulate the worker's background warm (pre-read code/test files), then measure.
print("warming (pre-read code/test files like the server's _warm thread)...", flush=True)
t0 = time.perf_counter()
mv._warm()
print(f"warm done in {(time.perf_counter()-t0)*1000:.0f}ms; cached_lines={len(mv._LINES)}", flush=True)

QS = [
    "freshness choose_strategy incremental vs full sync decision",
    "daemon watchdog force restart health poll",
    "embedder CodeRank FastEmbed batch scheduler acquire",
    "map v3 server tool dispatch find focus related graph",
    "mcp bridge spawn worker respawn hot reload",
]
print("\n-- find (post-warm, grep should hit cache) --", flush=True)
for i, q in enumerate(QS):
    t0 = time.perf_counter()
    out = srv.tool_map({"config": "find", "query": q})
    print(f"  find#{i} {(time.perf_counter()-t0)*1000:7.0f}ms  {len(out)}c", flush=True)

print("\n-- focus (post-warm) --", flush=True)
for nm in ("choose_strategy", "run_ship_ladder", "ensure_fresh_for_search"):
    t0 = time.perf_counter()
    out = srv.tool_map({"config": "focus", "names": [nm]})
    print(f"  focus[{nm}] {(time.perf_counter()-t0)*1000:7.0f}ms  {len(out)}c", flush=True)

print("\n-- related / graph (post-warm) --", flush=True)
for cfg, args in (
    ("related", {"config": "related", "anchor": "packages/pipeline/freshness.py::choose_strategy", "query": "sync strategy"}),
    ("graph", {"config": "graph", "query": "map v3 server tool dispatch"}),
):
    t0 = time.perf_counter()
    out = srv.tool_map(args)
    print(f"  {cfg:8s} {(time.perf_counter()-t0)*1000:7.0f}ms  {len(out)}c", flush=True)

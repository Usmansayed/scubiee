"""Profile where time goes inside each Map V3 config, warm engine, in-process
(no stdio/subprocess overhead) so we isolate bridge/helper cost from transport.

Wraps the hot internal helpers with cumulative timers + call counts, then runs
each config and prints a per-config breakdown.
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")
os.environ.setdefault("CTX_REPO", r"C:\Users\usman\Downloads\context-engine")
os.environ.setdefault("CTX_PROJECT_ID", "ce_3536ac8e8e83bb8e4d888db37847729c")
os.environ["MINI_REPO"] = os.environ["CTX_REPO"]

import pipeline.map_v3_helpers as mv  # noqa: E402
from pipeline import map_v3_server as srv  # noqa: E402

STATS: dict[str, dict] = {}


def wrap(mod, name):
    orig = getattr(mod, name)
    STATS[name] = {"n": 0, "ms": 0.0}

    def inner(*a, **k):
        t0 = time.perf_counter()
        try:
            return orig(*a, **k)
        finally:
            dt = (time.perf_counter() - t0) * 1000
            STATS[name]["n"] += 1
            STATS[name]["ms"] += dt

    setattr(mod, name, inner)
    return orig


# Hot leaf helpers (engine HTTP + disk + AST).
for fn in ("_http", "_repo_files", "_outline", "_search", "_grep", "_code_text", "_lines", "_enclosing"):
    if hasattr(mv, fn):
        wrap(mv, fn)


def reset():
    for v in STATS.values():
        v["n"] = 0
        v["ms"] = 0.0


mv._repo_files()  # prime the file cache once up front


def run(label, args, warm_first=True):
    # warm once (fills engine map cache), then measure the clean call
    if warm_first:
        srv.tool_map(dict(args))
    reset()
    t0 = time.perf_counter()
    out = srv.tool_map(dict(args))
    total = (time.perf_counter() - t0) * 1000
    inside = sum(v["ms"] for v in STATS.values())
    print(f"\n=== {label}  total={total:.0f}ms  (measured-helpers={inside:.0f}ms, other={total-inside:.0f}ms)  out={len(out)}c")
    for name, v in sorted(STATS.items(), key=lambda x: -x[1]["ms"]):
        if v["n"]:
            print(f"    {name:14s} n={v['n']:3d}  {v['ms']:7.1f}ms  ({v['ms']/max(total,1)*100:4.0f}% of total)")
    return total


print("Profiling each config warm (in-process; excludes stdio).")
# find
run("find", {"config": "find", "query": "freshness choose_strategy incremental vs full sync decision"})
run("find+keywords", {"config": "find", "query": "embed many encode batch", "keywords": ["embed_many", "Embedder"]})
# focus
run("focus choose_strategy", {"config": "focus", "names": ["choose_strategy"]})
run("focus run_ship_ladder", {"config": "focus", "names": ["run_ship_ladder"]})
# related
run("related", {"config": "related", "anchor": "packages/pipeline/freshness.py::choose_strategy", "query": "sync strategy decision incremental"})
# graph
run("graph", {"config": "graph", "query": "map v3 server tool dispatch handlers config"})

print("\n--- repeat find 5x to show warm steady-state ---")
reset()
for i in range(5):
    t0 = time.perf_counter()
    srv.tool_map({"config": "find", "query": f"daemon watchdog restart health poll variant{i}"})
    print(f"  find#{i} {(time.perf_counter()-t0)*1000:.0f}ms  (_http cum={STATS['_http']['ms']:.0f}ms n={STATS['_http']['n']})")

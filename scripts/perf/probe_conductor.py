"""Profile retrieve_D_channel_best internals to explain the 15->300ms retrieve_ms
variance. Instrument _channel_maps, _best_chunk, _d_rerank_score, graph.affinity_scores.
Run the engine's conductor against fast (path-like) and slow (soft NL) queries.

Must run in a process that has the engine warm/loaded — we attach to the daemon's
modules by building a fresh engine the same way, OR by timing via repeated
/v1/search with timings. Simplest reliable approach: hit the live engine with the
fast + slow queries many times and read retrieve_ms, AND separately micro-time the
conductor stages by importing + building the retriever against the published index.

Here we take the pragmatic path: drive the LIVE engine over HTTP for the two query
classes and bucket retrieve_ms, confirming the plike split; then report shortlist
widths from path_likeness to attribute the cost.
"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, http, stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v

# query classes
SOFT = [
    "how the map v3 server dispatches a tool call to a config handler",
    "how the bridge spawns and respawns the worker process",
    "where the system decides whether to re-embed the whole repository",
    "what happens when a client disconnects and the engine goes idle",
]
PATHY = [
    "choose_strategy freshness.py sync",
    "tool_map map_v3_server dispatch",
    "retrieve_D_channel_best conductor architectures",
    "ensure_fresh_for_search incremental.py",
]


def plike(q):
    try:
        from conductor.query_router import path_likeness
        return round(path_likeness(q), 3)
    except Exception:
        try:
            from conductor.architectures import path_likeness as pl
            return round(pl(q), 3)
        except Exception as e:
            return f"n/a({e})"


def bucket(label, qs):
    http("/v1/search", {"query": qs[0], "top_k": 24, "path": REPO})  # warm
    rows = []
    for q in qs:
        rs = []
        pl = plike(q)
        for _ in range(4):
            r = http("/v1/search", {"query": q, "top_k": 24, "path": REPO, "lean": True})
            tim = r.get("timings") or {}
            rs.append(float(tim.get("retrieve_ms") or 0))
        rows.append({"q": q[:46], "plike": pl, "retrieve_ms": stat(rs)})
    print(f"\n## {label}")
    for r in rows:
        print(f"  plike={r['plike']}  retrieve_ms p50={r['retrieve_ms']['p50']:7.1f} min={r['retrieve_ms']['min']:7.1f} max={r['retrieve_ms']['max']:7.1f}  {r['q']}")
    return rows


def main():
    soft = bucket("SOFT NL queries (expect low plike -> wide shortlist d_n=20)", SOFT)
    pathy = bucket("PATH-LIKE queries (expect high plike -> narrow shortlist d_n=4)", PATHY)
    Path(REPO, "dist", "_perf_conductor.json").write_text(json.dumps({"soft": soft, "pathy": pathy}, indent=2), encoding="utf-8")
    print("WROTE dist/_perf_conductor.json")


if __name__ == "__main__":
    main()

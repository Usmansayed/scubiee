"""Capture /v1/search top-k (path, start_line, end_line, rank) + retrieve_ms for a
fixed soft-query battery, to a labeled JSON. Run once with the engine's
CTX_GRAPH_SELECTIVE_UNION off (baseline) and once on (optimized); diff the files."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, http, stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v

LABEL = sys.argv[1] if len(sys.argv) > 1 else "run"
QUERIES = [
    "how the map v3 server dispatches a tool call to a config handler",
    "how the bridge spawns and respawns the worker process",
    "what happens when a client disconnects and the engine goes idle",
    "where the system decides whether to re-embed the whole repository",
    "how are search results ranked and fused across channels",
    "where freshness decides the sync strategy incremental vs full",
    "how does the keeper publish dirty files after a debounce window",
]


def main():
    http("/v1/search", {"query": "warm", "top_k": 24, "path": REPO})
    out = {}
    for q in QUERIES:
        http("/v1/search", {"query": q, "top_k": 24, "path": REPO})  # cache embed
        rms = []
        hits_sig = None
        for _ in range(3):
            r = http("/v1/search", {"query": q, "top_k": 24, "path": REPO})
            tim = r.get("timings") or {}
            rms.append(float(tim.get("retrieve_ms") or 0))
            sig = [(h.get("path"), h.get("start_line"), h.get("end_line"), h.get("rank")) for h in (r.get("hits") or [])]
            hits_sig = sig
        out[q] = {"retrieve_ms": stat(rms), "topk": hits_sig[:12]}
    Path(REPO, "dist", f"_topk_{LABEL}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"WROTE dist/_topk_{LABEL}.json")
    for q, d in out.items():
        print(f"  retrieve p50={d['retrieve_ms']['p50']:7.1f}ms  {q[:46]}")


if __name__ == "__main__":
    main()

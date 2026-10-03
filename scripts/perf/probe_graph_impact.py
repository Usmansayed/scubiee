"""Decisive validation: does the graph channel change the FINAL find ranking for
soft queries (where its weight is 0.005)? Compare /v1/search hits with graph ON
(current) vs graph forced to zero/bounded, over many soft + path-like queries.

We can't easily toggle graph in the running engine from here, so instead we read
the hits WITH graph (live), then ask the engine for the same with a time-bounded
graph (via a new ?graph_budget hook we add) OR compare rank stability. For this
first pass we quantify: for each query, what fraction of the final top-8 files
have a nonzero graph score that actually changed their rank vs dense-only order.

Pragmatic approach that needs no engine change: read full timings incl per-hit
channels is not exposed, so we instead compare the published hits' ORDER to a
dense-only re-sort using the dense scores the engine returns. If identical, graph
did not reorder the top-k and can be safely bounded for that query class.
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, http, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v

SOFT = [
    "how the map v3 server dispatches a tool call to a config handler",
    "how the bridge spawns and respawns the worker process",
    "what happens when a client disconnects and the engine goes idle",
    "where the system decides whether to re-embed the whole repository",
    "how are search results ranked and fused across channels",
]


def main():
    print("## For each soft query: top-8 files, and whether channels tag is dense-only")
    for q in SOFT:
        http("/v1/search", {"query": q, "top_k": 24, "path": REPO})
        r = http("/v1/search", {"query": q, "top_k": 24, "path": REPO})
        hits = r.get("hits") or []
        top = hits[:8]
        # 'source' encodes channels e.g. D_channel_best:dense / dense+graph / dense+bm25
        rows = [(h.get("path", "").split("/")[-1], h.get("source", ""), h.get("score")) for h in top]
        tim = r.get("timings") or {}
        print(f"\n  Q: {q[:50]}  (retrieve={tim.get('retrieve_ms')}ms graph={((tim.get('channels') or {}).get('graph_block_ms'))}ms)")
        for name, src, sc in rows:
            # does graph participate in this hit's channel tag?
            graphy = "graph" in (src or "")
            print(f"      {'G' if graphy else ' '} {name:40s} {src}")
    print("\nLegend: 'G' = this hit's file was tagged by the graph channel (so graph MIGHT affect its rank).")


if __name__ == "__main__":
    main()

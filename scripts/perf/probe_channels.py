"""Read the per-channel timings (graph/bm25/dense block ms) now surfaced in
timings.channels, for soft (slow retrieve) vs path-like (fast) queries. This
pinpoints which channel is the retrieve_ms long pole."""
from __future__ import annotations
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, http, stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v

SOFT = [
    "how the map v3 server dispatches a tool call to a config handler",
    "how the bridge spawns and respawns the worker process",
    "what happens when a client disconnects and the engine goes idle",
]
PATHY = [
    "choose_strategy freshness sync",
    "tool_map map_v3_server dispatch",
    "retrieve_D_channel_best conductor",
]


def run(label, qs):
    print(f"\n## {label}")
    out = []
    for q in qs:
        http("/v1/search", {"query": q, "top_k": 24, "path": REPO})  # ensure embed cached
        r = http("/v1/search", {"query": q, "top_k": 24, "path": REPO})
        tim = r.get("timings") or {}
        ch = tim.get("channels") or {}
        print(f"  retrieve={tim.get('retrieve_ms'):7} plike={tim.get('path_likeness')}  "
              f"graph={ch.get('graph_block_ms')} bm25={ch.get('bm25_block_ms')} dense={ch.get('dense_block_ms')} poolwall={ch.get('channel_pool_wall_ms')}  {q[:40]}")
        out.append({"q": q[:40], "timings": tim})
    return out


def main():
    s = run("SOFT NL (slow retrieve)", SOFT)
    p = run("PATH-LIKE (fast retrieve)", PATHY)
    Path(REPO, "dist", "_perf_channels.json").write_text(json.dumps({"soft": s, "pathy": p}, indent=2), encoding="utf-8")
    print("WROTE dist/_perf_channels.json")


if __name__ == "__main__":
    main()

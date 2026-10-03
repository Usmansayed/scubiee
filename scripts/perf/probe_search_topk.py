"""Does /v1/search cost scale with top_k? related uses top_k=20 vs find's ~8.
Measure engine total_ms + wall at top_k in {5,8,20,40} for a few queries (warm)."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, http, stat  # noqa: E402

QUERIES = ["freshness staleness decision", "dispatch config handler map",
           "build verify install ship ladder"]
TOPKS = [5, 8, 20, 40]


def one(q, k):
    t0 = time.perf_counter()
    r = http("/v1/search", {"query": q, "top_k": k, "path": REPO}, timeout=90)
    wall = (time.perf_counter() - t0) * 1000
    t = r.get("timings") or {}
    return wall, t.get("total_ms"), t.get("retrieve_ms"), t.get("embed_ms"), len(r.get("hits") or [])


def main():
    # warm each query/topk once
    for q in QUERIES:
        for k in TOPKS:
            one(q, k)
    out = {}
    for k in TOPKS:
        walls, totals, retrs = [], [], []
        for q in QUERIES:
            for _ in range(5):
                w, tot, rt, em, nh = one(q, k)
                walls.append(w); 
                if tot is not None: totals.append(tot)
                if rt is not None: retrs.append(rt)
        out[k] = {"wall": stat(walls),
                  "engine_total_ms": stat(totals) if totals else None,
                  "retrieve_ms": stat(retrs) if retrs else None}
        print(f"top_k={k:3d}  wall={out[k]['wall']}  engine_total={out[k]['engine_total_ms']}  retrieve={out[k]['retrieve_ms']}")
    Path(REPO, "dist", "_perf_search_topk.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("WROTE dist/_perf_search_topk.json")


if __name__ == "__main__":
    main()

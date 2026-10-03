"""Profile the engine side of find's cost: /v1/search. The engine records
eng._last_timings and returns it as `timings` in the response — use that to see
whether time is in query embedding, FAISS/dense search, BM25, fusion, or result
assembly. Also measure the pure HTTP overhead vs the reported engine compute."""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, http, stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v

QUERIES = [
    "where freshness decides the sync strategy incremental vs full",
    "how the map v3 server dispatches a tool call to a config handler",
    "where the engine health endpoint computes warm and dense readiness",
    "how the bridge spawns and respawns the worker process",
    "resource manager memory budget admission pause resume governor",
    "embedder CodeRank FastEmbed batch fair scheduler acquire",
]


def main():
    # warm
    http("/v1/search", {"query": "warm", "top_k": 24, "path": REPO})
    rows = []
    for q in QUERIES:
        for _ in range(3):
            t0 = time.perf_counter()
            r = http("/v1/search", {"query": q, "top_k": 24, "path": REPO})
            wall = (time.perf_counter() - t0) * 1000
            tim = r.get("timings") or {}
            rows.append({
                "q": q[:38],
                "wall_ms": round(wall, 1),
                "n_hits": len(r.get("hits") or []),
                "retrieve_mode": r.get("retrieve_mode"),
                "timings": tim,
            })
    print("## /v1/search wall + engine-reported timings")
    for r in rows:
        print(f"  wall={r['wall_ms']:7.1f}ms hits={r['n_hits']:2d} mode={r['retrieve_mode']}  {r['q']}")
        if r["timings"]:
            keys = sorted(r["timings"].items(), key=lambda x: -(x[1] if isinstance(x[1], (int, float)) else 0))
            print("       timings: " + ", ".join(f"{k}={v}" for k, v in keys if isinstance(v, (int, float)))[:160])
    walls = [r["wall_ms"] for r in rows]
    print("\n## wall distribution:", stat(walls))
    # show one full timings dict verbatim
    full = next((r["timings"] for r in rows if r["timings"]), {})
    print("## sample full timings keys:", list(full.keys()))
    Path(REPO, "dist", "_perf_engine_search.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print("WROTE dist/_perf_engine_search.json")


if __name__ == "__main__":
    main()

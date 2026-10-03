"""SYSTEM-WIDE — cumulative end-to-end warm latency for ALL map configs with every
KEPT change active (grep memoization + scandir walk + no-proxy opener + lean search).
In-process via the real map_v3_server handlers. One warm call then N measured per case."""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v
import pipeline.map_v3_helpers as mv  # noqa: E402
from pipeline import map_v3_server as srv  # noqa: E402


def bench(args, n=8):
    srv.tool_map(dict(args))  # warm
    xs = []
    for _ in range(n):
        t0 = time.perf_counter()
        out = srv.tool_map(dict(args))
        xs.append((time.perf_counter() - t0) * 1000)
    return stat(xs), len(out)


def main():
    mv._repo_files(); mv._warm()
    cases = {
        "find (nl query)": {"config": "find", "query": "freshness staleness decision"},
        "find (keyword)": {"config": "find", "query": "choose_strategy", "names": ["choose_strategy"]},
        "focus bare name": {"config": "focus", "names": ["choose_strategy"]},
        "focus file::symbol": {"config": "focus", "names": ["packages/pipeline/freshness.py::choose_strategy"]},
        "related file::symbol": {"config": "related", "anchor": "packages/pipeline/freshness.py::choose_strategy", "query": "freshness staleness"},
        "graph query": {"config": "graph", "query": "map config dispatch handler"},
    }
    rep = {}
    for label, args in cases.items():
        s, n = bench(args)
        rep[label] = {"stat": s, "out_chars": n}
        print(f"  {s['p50']:7.1f}ms p50  (min {s['min']}, p95 {s['p95']})  out={n}c  {label}")
    Path(REPO, "dist", "_perf_cumulative.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print("WROTE dist/_perf_cumulative.json")


if __name__ == "__main__":
    main()

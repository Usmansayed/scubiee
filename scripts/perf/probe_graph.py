"""TOOL 6 — map config=graph: count _http + _grep, stage-profile seed-search vs
node build (_top_level_symbols) vs edge extraction (_code_text + regex). In-process.
graph does NO grep in the common path; cost should be the single /v1/search + AST."""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v

import pipeline.map_v3_helpers as mv  # noqa: E402
from pipeline import map_v3_server as srv  # noqa: E402

STATS: dict[str, dict] = {}
HTTP_PATHS: list[str] = []
GREP_PATS: list[str] = []


def wrap(mod, name):
    orig = getattr(mod, name)
    STATS[name] = {"n": 0, "ms": 0.0}

    def inner(*a, **k):
        t0 = time.perf_counter()
        try:
            return orig(*a, **k)
        finally:
            STATS[name]["n"] += 1
            STATS[name]["ms"] += (time.perf_counter() - t0) * 1000
    setattr(mod, name, inner)


for fn in ("_search", "_outline", "_code_text", "_top_level_symbols", "_locate_target",
           "_lines", "_grep_scope_files", "_py_outline"):
    if hasattr(mv, fn):
        wrap(mv, fn)
for fn in ("_top_level_symbols", "_locate_target"):
    if hasattr(srv, fn):
        wrap(srv, fn)

_real_http = mv._http
STATS["_http"] = {"n": 0, "ms": 0.0}
def _http_spy(path, payload=None, timeout=90.0):
    HTTP_PATHS.append(path)
    t0 = time.perf_counter()
    try:
        return _real_http(path, payload, timeout)
    finally:
        STATS["_http"]["n"] += 1
        STATS["_http"]["ms"] += (time.perf_counter() - t0) * 1000
mv.__dict__["_http"] = _http_spy

_real_grep = mv._grep
STATS["_grep"] = {"n": 0, "ms": 0.0}
def _grep_spy(pattern, max_hits=300, scope="code"):
    GREP_PATS.append(pattern[:36])
    t0 = time.perf_counter()
    try:
        return _real_grep(pattern, max_hits, scope)
    finally:
        STATS["_grep"]["n"] += 1
        STATS["_grep"]["ms"] += (time.perf_counter() - t0) * 1000
mv.__dict__["_grep"] = _grep_spy


def reset():
    for v in STATS.values():
        v["n"] = 0; v["ms"] = 0.0
    HTTP_PATHS.clear(); GREP_PATS.clear()


def run(label, args):
    srv.tool_map(dict(args))  # warm
    reset()
    t0 = time.perf_counter()
    out = srv.tool_map(dict(args))
    total = (time.perf_counter() - t0) * 1000
    rows = {n: (v["n"], round(v["ms"], 1)) for n, v in STATS.items() if v["n"]}
    return {"label": label, "total_ms": round(total, 1), "out_chars": len(out),
            "n_http": len(HTTP_PATHS), "http": list(HTTP_PATHS),
            "n_grep": len(GREP_PATS), "helpers": rows}


def main():
    mv._repo_files(); mv._warm()
    cases = [
        ("graph query 'freshness decision'", {"config": "graph", "query": "freshness staleness decision"}),
        ("graph query 'map dispatch'", {"config": "graph", "query": "map config dispatch handler"}),
        ("graph anchor file::symbol", {"config": "graph", "anchor": "packages/pipeline/map_v3_server.py::cfg_find", "query": "find retrieval"}),
    ]
    results, lat = [], []
    for label, args in cases:
        r = run(label, args)
        results.append(r); lat.append(r["total_ms"])
        print(f"\n  {r['total_ms']:7.1f}ms  n_http={r['n_http']} n_grep={r['n_grep']}  out={r['out_chars']}c  {label}")
        print(f"     http={r['http']}")
        for n, (cnt, ms) in sorted(r["helpers"].items(), key=lambda x: -x[1][1]):
            print(f"       {n:18s} n={cnt:4d} {ms:7.1f}ms")
    print("\n## graph latency (warm):", stat(lat))
    Path(REPO, "dist", "_perf_graph.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("WROTE dist/_perf_graph.json")


if __name__ == "__main__":
    main()

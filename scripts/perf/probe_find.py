"""TOOL 3 — map config=find: count _http calls, stage-profile the hot helpers,
and separate engine (HTTP) time from local (grep/AST/body) time. In-process so
helper CPU is isolated from stdio/bridge."""
from __future__ import annotations
import json, os, sys, time, statistics
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v

import pipeline.map_v3_helpers as mv  # noqa: E402
from pipeline import map_v3_server as srv  # noqa: E402

STATS: dict[str, dict] = {}
HTTP_PATHS: list[str] = []


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


# wrap the leaf helpers (NOT _http — handled by the spy below to also log paths)
for fn in ("_search", "_grep", "_outline", "_enclosing", "_code_text", "_lines", "_numbered", "_match_lines"):
    if hasattr(mv, fn):
        wrap(mv, fn)

# spy on _http to count calls + record engine paths, and time it
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


def reset():
    for v in STATS.values():
        v["n"] = 0; v["ms"] = 0.0
    HTTP_PATHS.clear()


def run(label, args, warm=True):
    if warm:
        srv.tool_map(dict(args))
    reset()
    t0 = time.perf_counter()
    out = srv.tool_map(dict(args))
    total = (time.perf_counter() - t0) * 1000
    inside = sum(v["ms"] for v in STATS.values() if v["n"])
    http_ms = STATS.get("_search", {}).get("ms", 0)  # engine time via _search wrapper
    rows = {n: (v["n"], round(v["ms"], 1)) for n, v in STATS.items() if v["n"]}
    return {"label": label, "total_ms": round(total, 1), "out_chars": len(out),
            "http_calls": list(HTTP_PATHS), "n_http": len(HTTP_PATHS),
            "helpers": rows}


def main():
    mv._repo_files()
    mv._warm()  # like the server's background warm thread
    QUERIES_NOKW = [
        "where freshness decides the sync strategy incremental vs full",
        "how the map v3 server dispatches a tool call to a config handler",
        "where the engine health endpoint computes warm and dense readiness",
        "how the bridge spawns and respawns the worker process",
        "where keyword grep prefilter skips files before the regex",
    ]
    QUERIES_KW = [
        {"query": "embed many encode batch", "keywords": ["embed_many", "Embedder"]},
        {"query": "run ship ladder checks", "keywords": ["run_ship_ladder"]},
    ]
    results = []
    # repeat each no-kw query to get warm steady-state latency
    lat = []
    for q in QUERIES_NOKW:
        r = run(f"find(nokw): {q[:40]}", {"config": "find", "query": q})
        results.append(r)
        lat.append(r["total_ms"])
    for kw in QUERIES_KW:
        r = run(f"find(kw): {kw['keywords']}", {"config": "find", **kw})
        results.append(r)
        lat.append(r["total_ms"])

    print("## per-query")
    for r in results:
        print(f"  {r['total_ms']:7.1f}ms  n_http={r['n_http']} paths={r['http_calls']}  out={r['out_chars']}c  {r['label']}")
        for n, (cnt, ms) in sorted(r["helpers"].items(), key=lambda x: -x[1][1]):
            print(f"       {n:12s} n={cnt:3d} {ms:7.1f}ms")
    print("\n## find latency distribution (warm):", stat(lat))

    # aggregate HTTP-call count stats across queries
    ncalls = [r["n_http"] for r in results]
    print("## _http calls per find:", {"min": min(ncalls), "max": max(ncalls), "typical_nokw": results[0]["n_http"], "typical_kw": results[-1]["n_http"]})

    Path(REPO, "dist", "_perf_find.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("WROTE dist/_perf_find.json")


if __name__ == "__main__":
    main()

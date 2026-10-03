"""TOOL 4 — map config=focus: count _http + _grep calls, stage-profile, separate
resolution vs callers/callees vs body. In-process so helper CPU is isolated.
Tests bare-name targets (names=[X]) and file::symbol targets (no grep resolution)."""
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


for fn in ("_search", "_outline", "_enclosing", "_code_text", "_lines", "_numbered",
           "_resolve_symbol_name", "_locate_target", "_resolve_file", "_top_level_symbols"):
    if hasattr(mv, fn):
        wrap(mv, fn)
# server-level helpers
for fn in ("_callers_of", "_callees_in", "_top_level_symbols", "_resolve_one", "_pack_bodies"):
    if hasattr(srv, fn):
        wrap(srv, fn)

# spy _http (count + time)
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

# spy _grep (count + time + pattern)
_real_grep = mv._grep
STATS["_grep"] = {"n": 0, "ms": 0.0}
def _grep_spy(pattern, max_hits=300, scope="code"):
    GREP_PATS.append(pattern[:40])
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


def run(label, args, warm=True):
    if warm:
        srv.tool_map(dict(args))
    reset()
    t0 = time.perf_counter()
    out = srv.tool_map(dict(args))
    total = (time.perf_counter() - t0) * 1000
    rows = {n: (v["n"], round(v["ms"], 1)) for n, v in STATS.items() if v["n"]}
    return {"label": label, "total_ms": round(total, 1), "out_chars": len(out),
            "n_http": len(HTTP_PATHS), "http": list(HTTP_PATHS),
            "n_grep": len(GREP_PATS), "grep_pats": list(GREP_PATS), "helpers": rows}


def main():
    mv._repo_files(); mv._warm()
    cases = [
        ("focus bare name choose_strategy", {"config": "focus", "names": ["choose_strategy"]}),
        ("focus bare name run_ship_ladder", {"config": "focus", "names": ["run_ship_ladder"]}),
        ("focus bare name tool_map", {"config": "focus", "names": ["tool_map"]}),
        ("focus file::symbol (no resolve grep)", {"config": "focus", "names": ["packages/pipeline/freshness.py::choose_strategy"]}),
        ("focus 3 names (multi)", {"config": "focus", "names": ["choose_strategy", "run_ship_ladder", "ensure_fresh_for_search"]}),
    ]
    results = []
    lat = []
    for label, args in cases:
        r = run(label, args)
        results.append(r); lat.append(r["total_ms"])
        print(f"\n  {r['total_ms']:7.1f}ms  n_http={r['n_http']} n_grep={r['n_grep']}  out={r['out_chars']}c  {label}")
        print(f"     grep_pats={r['grep_pats']}")
        for n, (cnt, ms) in sorted(r["helpers"].items(), key=lambda x: -x[1][1]):
            print(f"       {n:18s} n={cnt:3d} {ms:7.1f}ms")
    print("\n## focus latency (warm):", stat(lat))
    Path(REPO, "dist", "_perf_focus.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("WROTE dist/_perf_focus.json")


if __name__ == "__main__":
    main()

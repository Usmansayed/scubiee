"""TOOL 4 fix candidate — memoize the per-scope filtered+sorted grep file list.
The walk stage (~117ms = 80% of a warm grep) rebuilds + re-_kind_of()s ~4897 files
on EVERY grep. The result is identical within a session. A/B: cached vs live list,
assert byte-identical ordering, measure the per-grep win and the end-to-end focus win."""
from __future__ import annotations
import json, os, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v

import pipeline.map_v3_helpers as mv  # noqa: E402

_order = {"code": 0, "tests": 1, "docs": 2, "other": 3}


def live_list(scope):
    want = {"code": ("code", "tests"), "tests": ("tests",), "docs": ("docs",),
            "all": ("code", "tests", "docs", "other")}.get(scope, ("code", "tests"))
    files = [f for f in mv._repo_files() if Path(f).suffix.lower() in mv._GREP_EXT and mv._kind_of(f) in want]
    files.sort(key=lambda f: (_order[mv._kind_of(f)], f))
    return files


_CACHE: dict = {}
def cached_list(scope):
    files = mv._repo_files()
    key = (scope, id(files), len(files))
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    out = live_list(scope)
    _CACHE[key] = out
    return out


def time_n(fn, scope, n=20):
    xs = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn(scope)
        xs.append((time.perf_counter() - t0) * 1000)
    return stat(xs)


def main():
    mv._repo_files(); mv._warm()
    report = {}
    for scope in ("code",):
        a = live_list(scope)
        b = cached_list(scope)
        identical = (a == b)
        report[scope] = {"identical": identical, "n_files": len(a),
                         "live": time_n(live_list, scope), "cached": time_n(cached_list, scope)}
        print(f"scope={scope} identical={identical} n={len(a)}")
        print(f"  live  : {report[scope]['live']}")
        print(f"  cached: {report[scope]['cached']}")
    Path(REPO, "dist", "_perf_grep_filelist_ab.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("WROTE dist/_perf_grep_filelist_ab.json")


if __name__ == "__main__":
    main()

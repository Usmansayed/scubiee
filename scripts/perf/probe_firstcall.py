"""STARTUP — isolate the ~400ms first-call tax. In ONE fresh process, time:
  1) first mv._http('/health')           (first TCP connect from this proc)
  2) first mv._search(q)  (first /v1/search round-trip)
  3) 2nd _search(q)       (steady)
  4) first full cfg_find  vs 2nd
Checks the _http retry path (cold-connect fail -> 0.3s sleep + retry) and whether
the engine pays a per-first-request cost. Engine already warm+dense."""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v

import pipeline.map_v3_helpers as mv  # noqa: E402
from pipeline import map_v3_server as srv  # noqa: E402


def ms(fn):
    t0 = time.perf_counter()
    r = fn()
    return (time.perf_counter() - t0) * 1000, r


def main():
    rep = {}
    t, _ = ms(lambda: mv._http("/health", None, 8))
    rep["first_health_http_ms"] = round(t, 1)
    t, h1 = ms(lambda: mv._search("freshness decision", 8))
    rep["first_search_ms"] = round(t, 1)
    t, _ = ms(lambda: mv._search("freshness decision", 8))
    rep["second_search_ms"] = round(t, 1)
    t, _ = ms(lambda: mv._search("a totally different brand new query string", 8))
    rep["first_search_newq_ms"] = round(t, 1)
    # full find
    t, _ = ms(lambda: srv.tool_map({"config": "find", "query": "freshness decision"}))
    rep["first_find_ms"] = round(t, 1)
    t, _ = ms(lambda: srv.tool_map({"config": "find", "query": "freshness decision"}))
    rep["second_find_ms"] = round(t, 1)
    rep["n_hits_first_search"] = len(h1)
    for k, v in rep.items():
        print(f"  {k:26s} = {v}")
    Path(REPO, "dist", "_perf_firstcall.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print("WROTE dist/_perf_firstcall.json")


if __name__ == "__main__":
    main()

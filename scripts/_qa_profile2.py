from __future__ import annotations
import os, sys, time
os.environ.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")
os.environ.setdefault("CTX_REPO", r"C:\Users\usman\Downloads\context-engine")
os.environ.setdefault("CTX_PROJECT_ID", "ce_3536ac8e8e83bb8e4d888db37847729c")
os.environ["MINI_REPO"] = os.environ["CTX_REPO"]


def t(label, fn):
    t0 = time.perf_counter()
    r = fn()
    dt = (time.perf_counter() - t0) * 1000
    print(f"{label:28s} {dt:8.1f}ms", flush=True)
    return r, dt


import pipeline.map_v3_helpers as mv  # noqa: E402
from pipeline import map_v3_server as srv  # noqa: E402

print("start", flush=True)
# 1) the repo file walk in isolation (first call builds the cache)
files, _ = t("_repo_files (cold walk)", lambda: mv._repo_files())
print(f"   file count = {len(files)}", flush=True)
t("_repo_files (cached)", lambda: mv._repo_files())
# 2) one engine search
t("_search top_k=8", lambda: mv._search("freshness choose_strategy sync", 8))
# 3) full find config (warm engine, cached files)
t("tool_map find #1", lambda: srv.tool_map({"config": "find", "query": "freshness choose_strategy incremental vs full sync decision"}))
t("tool_map find #2", lambda: srv.tool_map({"config": "find", "query": "freshness choose_strategy incremental vs full sync decision"}))
t("tool_map focus", lambda: srv.tool_map({"config": "focus", "names": ["choose_strategy"]}))
t("tool_map related", lambda: srv.tool_map({"config": "related", "anchor": "packages/pipeline/freshness.py::choose_strategy", "query": "sync strategy"}))
t("tool_map graph", lambda: srv.tool_map({"config": "graph", "query": "map v3 server tool dispatch"}))
print("done", flush=True)

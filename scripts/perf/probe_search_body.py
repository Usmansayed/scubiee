"""Is the ~34ms unaccounted gap (search_wall - engine_total - http_floor) in the
RESPONSE BODY (keeper=sync_loop.status() + previews) that map_v3._search discards?
Measure: response byte size, and dirty_ledger.snapshot() cost in-process."""
from __future__ import annotations
import json, os, sys, time, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v
ENG = "http://127.0.0.1:8765"


def raw(path, payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(ENG + path, data=data, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    ms = (time.perf_counter() - t0) * 1000
    return body, ms


def main():
    raw("/v1/search", {"query": "warm", "top_k": 24, "path": REPO})
    sizes, walls, hit_bytes, keeper_bytes, tim_bytes = [], [], [], [], []
    for _ in range(10):
        body, ms = raw("/v1/search", {"query": "freshness sync strategy choose_strategy incremental", "top_k": 24, "path": REPO})
        walls.append(ms)
        sizes.append(len(body))
        obj = json.loads(body)
        hit_bytes.append(len(json.dumps(obj.get("hits") or [])))
        keeper_bytes.append(len(json.dumps(obj.get("keeper") or {})))
        tim_bytes.append(len(json.dumps(obj.get("timings") or {})))
    print("## /v1/search response body size (bytes):", stat([float(s) for s in sizes]))
    print(f"##   of which hits={stat([float(x) for x in hit_bytes])['p50']}B  keeper={stat([float(x) for x in keeper_bytes])['p50']}B  timings={stat([float(x) for x in tim_bytes])['p50']}B")
    print("## wall:", stat(walls))

    # dirty_ledger.snapshot cost: we cannot touch the daemon's ledger from here,
    # but we can see the keeper block size it produces (above). Report top-level
    # keys so we know what's being serialized and discarded by _search.
    body, _ = raw("/v1/search", {"query": "freshness", "top_k": 24, "path": REPO})
    obj = json.loads(body)
    print("## response top-level keys:", list(obj.keys()))
    print("## _search() uses only: hits  (everything else is discarded by map_v3_helpers)")
    k = obj.get("keeper") or {}
    print("## keeper keys:", list(k.keys()))

    Path(REPO, "dist", "_perf_search_body.json").write_text(json.dumps({
        "size_p50": stat([float(s) for s in sizes])["p50"],
        "hit_bytes_p50": stat([float(x) for x in hit_bytes])["p50"],
        "keeper_bytes_p50": stat([float(x) for x in keeper_bytes])["p50"],
        "wall": stat(walls),
    }, indent=2), encoding="utf-8")
    print("WROTE dist/_perf_search_body.json")


if __name__ == "__main__":
    main()

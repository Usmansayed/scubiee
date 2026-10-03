"""Is the engine caching search results? Compare: (a) same query repeated,
(b) same query with a unique suffix each call (cache-busting). If (a) is ~0ms
retrieve and (b) is high, there is a result cache keyed on the query string."""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, http, stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v


def one(q):
    # NOT lean: we need the timings block (lean drops it by design)
    r = http("/v1/search", {"query": q, "top_k": 24, "path": REPO})
    tim = r.get("timings") or {}
    return float(tim.get("embed_ms") or 0), float(tim.get("retrieve_ms") or 0), float(tim.get("total_ms") or 0)


def main():
    base = "how the map v3 server dispatches a tool call to a config handler"
    # (a) repeated identical
    print("## repeated identical query (expect cache hit after 1st)")
    for i in range(5):
        e, r, t = one(base)
        print(f"  call{i}: embed={e:7.1f} retrieve={r:7.1f} total={t:7.1f}")
    # (b) unique each time (cache-busting)
    print("## unique query each call (cache-busting suffix)")
    uniq = []
    for i in range(6):
        e, r, t = one(base + f" variant number {i} unique {time.time_ns()}")
        print(f"  call{i}: embed={e:7.1f} retrieve={r:7.1f} total={t:7.1f}")
        uniq.append((e, r, t))
    print("## unique-query retrieve_ms:", stat([x[1] for x in uniq]))
    print("## unique-query embed_ms:", stat([x[0] for x in uniq]))
    print("## unique-query total_ms:", stat([x[2] for x in uniq]))
    Path(REPO, "dist", "_perf_cachecheck.json").write_text(json.dumps({"unique": uniq}, indent=2), encoding="utf-8")
    print("WROTE")


if __name__ == "__main__":
    main()

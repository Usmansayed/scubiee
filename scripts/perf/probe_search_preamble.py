"""Quantify the ~50ms gap between engine total_ms (retrieve+embed) and the HTTP
wall for /v1/search. Candidates: ce.search preamble (gate, governor
ensure_semantic_tier/refresh_from_hub, embedder_is_loaded, keepalive loop,
_ensure_engine) + HTTP framing. Measure each sub-part in-process in the ENGINE's
modules (run inside a process that imports them the same way the daemon does).

NOTE: this measures the functions in THIS process (fresh import), which is an
upper bound; the running daemon has them warm. We cross-check against the daemon
by also timing the pure HTTP overhead (a trivial endpoint) vs /v1/search wall.
"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, http, stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v


def many(fn, n=20):
    xs = []
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            fn()
        except Exception:
            pass
        xs.append((time.perf_counter() - t0) * 1000)
    return stat(xs)


def main():
    # 1) Pure HTTP framing overhead: time a cheap endpoint (/health) vs /v1/search
    #    wall. Difference approximates (search preamble + retrieve + embed) - health.
    http("/health"); http("/v1/search", {"query": "warm", "top_k": 24, "path": REPO})
    health = [_t(http, "/health") for _ in range(20)]
    srch = []
    engine_total = []
    for _ in range(20):
        t0 = time.perf_counter()
        r = http("/v1/search", {"query": "freshness sync strategy choose_strategy", "top_k": 24, "path": REPO})
        srch.append((time.perf_counter() - t0) * 1000)
        tim = r.get("timings") or {}
        engine_total.append(float(tim.get("total_ms") or 0))
    print("## /health wall:", stat(health))
    print("## /v1/search wall:", stat(srch))
    print("## engine total_ms (reported):", stat(engine_total))
    # wall - engine_total - health_floor = ce.search preamble (approx)
    import statistics as st
    gap = st.median(srch) - st.median(engine_total)
    print(f"## median(search_wall - engine_total_ms) = {gap:.1f}ms  (preamble + extra HTTP body)")
    print(f"## median(/health wall) = {st.median(health):.1f}ms  (HTTP floor)")

    # 2) Time the preamble pieces in THIS process (import cost warm after first call)
    try:
        from pipeline.memory_governor import get_governor
        gov = get_governor()
        print("## get_governor():", many(get_governor))
        print("## gov.ensure_semantic_tier():", many(gov.ensure_semantic_tier))
        try:
            from pipeline.hub import get_hub  # may not exist; best-effort
        except Exception:
            get_hub = None
        print("## gov.refresh_from_hub(None):", many(lambda: gov.refresh_from_hub(None)))
    except Exception as e:
        print("governor probe err:", e)
    try:
        from pipeline.engine import embedder_is_loaded
        print("## embedder_is_loaded():", many(embedder_is_loaded))
    except Exception as e:
        print("embedder_is_loaded err:", e)


def _t(fn, *a):
    t0 = time.perf_counter(); fn(*a); return (time.perf_counter() - t0) * 1000


if __name__ == "__main__":
    main()

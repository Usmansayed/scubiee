"""A/B the lean /v1/search change against the source-run engine: lean=True (drops
keeper block) vs lean=False (full body). Measure body size + wall, same queries,
interleaved to cancel drift. Confirm hits are IDENTICAL (behavior preserving)."""
from __future__ import annotations
import json, os, sys, time, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v
ENG = "http://127.0.0.1:8765"

QUERIES = [
    "freshness decides sync strategy incremental vs full",
    "map v3 server dispatch tool call config handler",
    "engine health warm dense readiness compute",
    "bridge spawn respawn worker process",
    "resource manager memory budget admission pause governor",
]


def call(q, lean):
    data = json.dumps({"query": q, "top_k": 24, "path": REPO, "lean": lean}).encode()
    req = urllib.request.Request(ENG + "/v1/search", data=data, headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    return body, (time.perf_counter() - t0) * 1000


def main():
    call(QUERIES[0], True); call(QUERIES[0], False)  # warm
    lean_wall, full_wall, lean_sz, full_sz = [], [], [], []
    hits_match = True
    for q in QUERIES:
        for _ in range(4):
            # interleave lean/full to cancel drift
            lb, lms = call(q, True)
            fb, fms = call(q, False)
            lean_wall.append(lms); full_wall.append(fms)
            lean_sz.append(len(lb)); full_sz.append(len(fb))
            lo = json.loads(lb); fo = json.loads(fb)
            # hits must be identical (same ranking, same spans)
            lh = [(h.get("path"), h.get("start_line"), h.get("end_line"), h.get("rank")) for h in (lo.get("hits") or [])]
            fh = [(h.get("path"), h.get("start_line"), h.get("end_line"), h.get("rank")) for h in (fo.get("hits") or [])]
            if lh != fh:
                hits_match = False
    print("## lean body bytes:", stat([float(x) for x in lean_sz]))
    print("## full body bytes:", stat([float(x) for x in full_sz]))
    print("## lean wall ms:", stat(lean_wall))
    print("## full wall ms:", stat(full_wall))
    import statistics as st
    print(f"## body reduction: {st.median(full_sz):.0f} -> {st.median(lean_sz):.0f} bytes ({100*(1-st.median(lean_sz)/st.median(full_sz)):.0f}% smaller)")
    print(f"## wall delta (full - lean) median: {st.median(full_wall)-st.median(lean_wall):.1f}ms")
    print(f"## HITS IDENTICAL lean==full: {hits_match}")
    Path(REPO, "dist", "_perf_lean_ab.json").write_text(json.dumps({
        "lean_bytes": stat([float(x) for x in lean_sz]), "full_bytes": stat([float(x) for x in full_sz]),
        "lean_wall": stat(lean_wall), "full_wall": stat(full_wall), "hits_identical": hits_match,
    }, indent=2), encoding="utf-8")
    print("WROTE dist/_perf_lean_ab.json")


if __name__ == "__main__":
    main()

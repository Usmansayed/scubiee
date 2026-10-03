from __future__ import annotations
import os, re, time
os.environ.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")
os.environ.setdefault("CTX_REPO", r"C:\Users\usman\Downloads\context-engine")
os.environ["MINI_REPO"] = os.environ["CTX_REPO"]
import pipeline.map_v3_helpers as mv
from pathlib import Path

mv._warm()
want = ("code", "tests")
files = [f for f in mv._repo_files() if Path(f).suffix.lower() in mv._GREP_EXT and mv._kind_of(f) in want]
print(f"candidate files={len(files)}", flush=True)


def grep_naive(pattern, max_hits=300):
    rx = re.compile(pattern); rxf = re.compile(pattern, re.MULTILINE)
    order = {"code": 0, "tests": 1, "docs": 2, "other": 3}
    fs = sorted(files, key=lambda f: (order[mv._kind_of(f)], f))
    out = []
    for f in fs:
        t = mv._text(f)
        if len(t) > 2_000_000: continue
        if not rxf.search(t): continue
        for i, line in enumerate(mv._lines(f), 1):
            if rx.search(line):
                out.append((f, i)); 
                if len(out) >= max_hits: return out
    return out


PATS = [
    r"\bchoose_strategy\b",
    r"\brun_ship_ladder\s*\(",
    r"(?i)\b(embed_many|Embedder)\b",
    r"^\s*(?:async\s+)?(?:def|class)\s+run_pack_context\b",
    r"\bensure_fresh_for_search\b",
]
allok = True
for p in PATS:
    # correctness: new _grep vs naive full-scan must match exactly
    t0 = time.perf_counter(); fast, _ = mv._grep(p, max_hits=300, scope="code"); fast_ms = (time.perf_counter()-t0)*1000
    fastset = {(h["path"], h["line"]) for h in fast}
    naive = set(grep_naive(p))
    ok = fastset == naive
    allok = allok and ok
    print(f"  {p!r:55s} fast={len(fastset)} naive={len(naive)} match={ok}  {fast_ms:6.0f}ms", flush=True)
print("ALL MATCH:", allok, flush=True)

from __future__ import annotations
import os, re
os.environ.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")
os.environ.setdefault("CTX_REPO", r"C:\Users\usman\Downloads\context-engine")
os.environ["MINI_REPO"] = os.environ["CTX_REPO"]
import pipeline.map_v3_helpers as mv
from pathlib import Path

mv._warm()


def naive(pattern, scope, max_hits):
    rx = re.compile(pattern); rxf = re.compile(pattern, re.MULTILINE)
    want = {"code": ("code", "tests"), "tests": ("tests",), "docs": ("docs",),
            "all": ("code", "tests", "docs", "other")}.get(scope, ("code", "tests"))
    files = [f for f in mv._repo_files() if Path(f).suffix.lower() in mv._GREP_EXT and mv._kind_of(f) in want]
    order = {"code": 0, "tests": 1, "docs": 2, "other": 3}
    files.sort(key=lambda f: (order[mv._kind_of(f)], f))
    out = []
    for f in files:
        t = mv._text(f)
        if len(t) > 2_000_000: continue
        if not rxf.search(t): continue
        for i, line in enumerate(mv._lines(f), 1):
            if rx.search(line):
                out.append((f, i))
                if len(out) >= max_hits: return out
    return out


# representative patterns actually used by the configs + tricky shapes
CASES = [
    (r"\bchoose_strategy\b", "code", 300),
    (r"\brun_ship_ladder\s*\(", "code", 120),
    (r"(?i)\b(embed_many|Embedder)\b", "code", 300),
    (r"^\s*(?:async\s+)?(?:def|class)\s+run_pack_context\b", "code", 50),
    (r"\b(run_pack_context|run_expand_context|run_map_context)\b", "all", 800),
    (r"\bEmbedder\b", "code", 400),
    (r"\btool_map\s*\(", "code", 60),
    (r"^\s*(?:async\s+)?(?:def|class|function|func|fn)\s+(cfg_find|cfg_focus)\b", "code", 200),
    (r"\bddoes_not_exist_zzz\b", "code", 50),
    (r"gate", "code", 100),  # short bare literal
]
allok = True
for pat, scope, mh in CASES:
    fast, _ = mv._grep(pat, max_hits=mh, scope=scope)
    fastset = {(h["path"], h["line"]) for h in fast}
    nv = set(naive(pat, scope, mh))
    # order-independent set equality (both capped at same max_hits, same file order)
    ok = fastset == nv
    pf = mv._pattern_prefilter(pat)
    allok = allok and ok
    print(f"  match={ok}  optimized={'Y' if pf else 'n'}  fast={len(fastset):4d} naive={len(nv):4d}  {pat[:50]}", flush=True)
print("ALL CORRECT:", allok, flush=True)

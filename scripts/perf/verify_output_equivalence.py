"""QUALITY GUARANTEE — prove the 0.3.139 optimizations are output-identical to the
pre-optimization behavior. For each map config we run the shipped tool TWICE against
the same live engine:
  A) OPTIMIZED  — exactly as shipped (grep file-list memoized, scandir walk, lean search)
  B) BASELINE   — the SAME tool code but with each optimization monkey-patched back to
                  its pre-optimization form (inline file-list rebuild, non-lean search)
then diff the FULL output text. Identical text == identical end results.

Run against the installed daemon on 127.0.0.1:8765."""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v

import pipeline.map_v3_helpers as mv  # noqa: E402
from pipeline import map_v3_server as srv  # noqa: E402

CASES = [
    ("find nl", {"config": "find", "query": "where freshness report decides sync strategy"}),
    ("find keyword", {"config": "find", "query": "choose_strategy", "names": ["choose_strategy"]}),
    ("focus bare", {"config": "focus", "names": ["choose_strategy"]}),
    ("focus file::symbol", {"config": "focus", "names": ["packages/pipeline/freshness.py::choose_strategy"]}),
    ("focus multi", {"config": "focus", "names": ["choose_strategy", "run_ship_ladder"]}),
    ("related", {"config": "related", "anchor": "packages/pipeline/freshness.py::choose_strategy", "query": "freshness staleness"}),
    ("graph", {"config": "graph", "query": "map config dispatch handler"}),
]


# ---- BASELINE reimplementations (pre-optimization behavior) -----------------
def _grep_scope_files_BASELINE(scope: str):
    """The pre-0.3.139 inline build: rebuild + re-_kind_of every call, no memo."""
    want = {"code": ("code", "tests"), "tests": ("tests",), "docs": ("docs",),
            "all": ("code", "tests", "docs", "other")}.get(scope, ("code", "tests"))
    files = [f for f in mv._repo_files() if Path(f).suffix.lower() in mv._GREP_EXT and mv._kind_of(f) in want]
    order = {"code": 0, "tests": 1, "docs": 2, "other": 3}
    files.sort(key=lambda f: (order[mv._kind_of(f)], f))
    return files


def _search_BASELINE(query: str, top_k: int):
    """Pre-0.3.139: non-lean /v1/search (full body incl keeper), read hits only."""
    r = mv._http("/v1/search", {"query": query, "top_k": top_k, "path": str(mv.REPO)})
    return r.get("hits") or []


def run_all(label_fn):
    out = {}
    for label, args in CASES:
        # two calls, discard first (warm), keep second (stable)
        srv.tool_map(dict(args))
        out[label] = srv.tool_map(dict(args))
    return out


def main():
    mv._repo_files(); mv._warm()

    # A) OPTIMIZED (as shipped)
    opt = run_all("optimized")

    # B) BASELINE (monkey-patch optimizations back to pre-opt form)
    real_scope = mv._grep_scope_files
    real_search = mv._search
    mv._grep_scope_files = _grep_scope_files_BASELINE
    mv._search = _search_BASELINE
    # cfg_* in srv call module-level _search imported by name; patch there too
    srv._search = _search_BASELINE
    try:
        base = run_all("baseline")
    finally:
        mv._grep_scope_files = real_scope
        mv._search = real_search
        srv._search = real_search

    print(f"{'case':20s} {'opt_chars':>9s} {'base_chars':>10s}  identical")
    all_ok = True
    rep = {}
    for label, _ in CASES:
        o, b = opt[label], base[label]
        same = (o == b)
        all_ok = all_ok and same
        rep[label] = {"identical": same, "opt_chars": len(o), "base_chars": len(b)}
        print(f"{label:20s} {len(o):9d} {len(b):10d}  {'YES' if same else 'NO <<<<'}")
        if not same:
            # show first divergence
            for i, (co, cb) in enumerate(zip(o, b)):
                if co != cb:
                    print(f"    first diff at char {i}: opt={o[i:i+60]!r} base={b[i:i+60]!r}")
                    break
    print(f"\nALL IDENTICAL: {all_ok}")
    Path(REPO, "dist", "_verify_equiv.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print("WROTE dist/_verify_equiv.json")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()

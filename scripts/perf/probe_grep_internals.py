"""TOOL 4 deep-dive — split one warm _grep pass into stages: file-walk+text (warm
cache), prefilter `in` scans, whole-file regex, per-line regex on survivors.
Measures the def-finder grep and the callers grep for a few symbols. In-process."""
from __future__ import annotations
import json, os, re, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v

import pipeline.map_v3_helpers as mv  # noqa: E402


def staged_grep(pattern: str, scope: str = "code"):
    """Re-implements the _grep walk but times each stage. Mirrors the real impl."""
    try:
        rx = re.compile(pattern)
        rx_file = re.compile(pattern, re.MULTILINE)
    except re.error:
        rx = re.compile(re.escape(pattern)); rx_file = rx
    pf = mv._pattern_prefilter(pattern)
    keep, keep_ci = (pf if pf else (None, False))
    want = {"code": ("code", "tests")}.get(scope, ("code", "tests"))
    t = {"walk": 0.0, "text": 0.0, "prefilter": 0.0, "whole": 0.0, "perline": 0.0}
    c = {"files": 0, "after_pf": 0, "after_whole": 0, "hits": 0}

    t0 = time.perf_counter()
    files = [f for f in mv._repo_files() if Path(f).suffix.lower() in mv._GREP_EXT and mv._kind_of(f) in want]
    order = {"code": 0, "tests": 1, "docs": 2, "other": 3}
    files.sort(key=lambda f: (order[mv._kind_of(f)], f))
    t["walk"] += (time.perf_counter() - t0) * 1000
    c["files"] = len(files)

    for f in files:
        t0 = time.perf_counter()
        text = mv._text_cached_fast(f)
        t["text"] += (time.perf_counter() - t0) * 1000
        if len(text) > 2_000_000:
            continue
        if keep is not None:
            t0 = time.perf_counter()
            probe = text  # (code path for case-sensitive def/callers patterns)
            ok = keep(probe)
            t["prefilter"] += (time.perf_counter() - t0) * 1000
            if not ok:
                continue
        c["after_pf"] += 1
        t0 = time.perf_counter()
        hit_whole = rx_file.search(text)
        t["whole"] += (time.perf_counter() - t0) * 1000
        if not hit_whole:
            continue
        c["after_whole"] += 1
        t0 = time.perf_counter()
        for i, line in enumerate(mv._lines(f), 1):
            if rx.search(line):
                c["hits"] += 1
        t["perline"] += (time.perf_counter() - t0) * 1000
    total = sum(t.values())
    return {"total_ms": round(total, 1), "stages": {k: round(v, 1) for k, v in t.items()}, "counts": c}


def main():
    mv._repo_files(); mv._warm()
    names = ["choose_strategy", "run_ship_ladder", "tool_map"]
    def_pat = r"^\s*(?:async\s+)?(?:def|class|function|func|fn)\s+{0}\b"
    call_pat = r"\b{0}\s*\("
    out = []
    # warm the text cache once
    staged_grep(def_pat.format("warmup"))
    for n in names:
        d = staged_grep(def_pat.format(n))
        c = staged_grep(call_pat.format(n))
        out.append({"name": n, "def_grep": d, "callers_grep": c})
        print(f"\n  {n}")
        print(f"    def   : {d['total_ms']:7.1f}ms  {d['stages']}  files={d['counts']['files']} pf_pass={d['counts']['after_pf']} whole_pass={d['counts']['after_whole']} hits={d['counts']['hits']}")
        print(f"    callers:{c['total_ms']:7.1f}ms  {c['stages']}  files={c['counts']['files']} pf_pass={c['counts']['after_pf']} whole_pass={c['counts']['after_whole']} hits={c['counts']['hits']}")
    Path(REPO, "dist", "_perf_grep_internals.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\nWROTE dist/_perf_grep_internals.json")


if __name__ == "__main__":
    main()

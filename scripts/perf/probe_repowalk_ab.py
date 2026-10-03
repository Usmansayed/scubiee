"""STARTUP deep-dive — can _repo_files() walk (~300ms for ~8000 files) be faster?
A/B three implementations, assert BYTE-IDENTICAL sorted output:
  cur    : current (os.walk + os.path.relpath + os.path.join + _norm per file)
  slice  : os.walk but build rel path by string-slicing dirpath (no relpath/join)
  scandir: os.scandir recursion, slice-based rel path
Correctness first: all must equal the current result exactly."""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v

import pipeline.map_v3_helpers as mv  # noqa: E402

ROOT = str(mv.REPO)
SKIP = mv.SKIP_DIRS


def _norm(p):
    return str(p or "").replace("\\", "/").lstrip("./")


def cur():
    out = []
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [d for d in dns if d not in SKIP and not d.startswith(".venv")]
        for fn in fns:
            out.append(_norm(os.path.relpath(os.path.join(dp, fn), ROOT)))
    return sorted(out)


def slice_walk():
    out = []
    base = len(ROOT) + 1
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [d for d in dns if d not in SKIP and not d.startswith(".venv")]
        rel_dir = dp[base:]
        prefix = (rel_dir.replace("\\", "/") + "/") if rel_dir else ""
        for fn in fns:
            out.append(_norm(prefix + fn))
    return sorted(out)


def scandir_walk():
    out = []
    base = len(ROOT) + 1
    stack = [ROOT]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    if e.is_dir(follow_symlinks=False):
                        nm = e.name
                        if nm in SKIP or nm.startswith(".venv"):
                            continue
                        stack.append(e.path)
                    else:
                        out.append(_norm(e.path[base:].replace("\\", "/")))
        except OSError:
            pass
    return sorted(out)


def time_fn(fn, n=10):
    xs = []
    for _ in range(n):
        fn()
        t0 = time.perf_counter()
        fn()
        xs.append((time.perf_counter() - t0) * 1000)
    return stat(xs)


def main():
    a = cur(); b = slice_walk(); c = scandir_walk()
    print(f"n_cur={len(a)} n_slice={len(b)} n_scandir={len(c)}")
    print(f"slice identical  = {a == b}")
    print(f"scandir identical= {a == c}")
    if a != c:
        only_cur = set(a) - set(c); only_sc = set(c) - set(a)
        print(f"  scandir diff: only_cur={list(only_cur)[:5]} only_scandir={list(only_sc)[:5]}")
    rep = {"identical_slice": a == b, "identical_scandir": a == c, "n": len(a),
           "cur": time_fn(cur), "slice": time_fn(slice_walk), "scandir": time_fn(scandir_walk)}
    print(f"\n  cur    : {rep['cur']}")
    print(f"  slice  : {rep['slice']}")
    print(f"  scandir: {rep['scandir']}")
    Path(REPO, "dist", "_perf_repowalk_ab.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print("WROTE dist/_perf_repowalk_ab.json")


if __name__ == "__main__":
    main()

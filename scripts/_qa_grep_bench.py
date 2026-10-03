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
texts = [mv._text(f) for f in files]
print(f"files={len(files)} total={sum(len(t) for t in texts):,}B", flush=True)

name = "choose_strategy"
# A) pure substring scan (what the prefilter does)
for _ in range(3):
    t0 = time.perf_counter(); n = sum(1 for t in texts if name in t); dt = (time.perf_counter()-t0)*1000
    print(f"  substring 'in' scan all files: {dt:7.1f}ms (files_with={n})", flush=True)
# B) regex MULTILINE search over all files (the old whole-file precheck)
rxf = re.compile(r"\b"+name+r"\b", re.MULTILINE)
for _ in range(3):
    t0 = time.perf_counter(); n = sum(1 for t in texts if rxf.search(t)); dt = (time.perf_counter()-t0)*1000
    print(f"  regex precheck scan all files: {dt:7.1f}ms (files_with={n})", flush=True)
# C) regex ONLY on files that pass substring (combined fast path)
for _ in range(3):
    t0 = time.perf_counter()
    n = sum(1 for t in texts if name in t and rxf.search(t)); dt = (time.perf_counter()-t0)*1000
    print(f"  substring-then-regex combined: {dt:7.1f}ms (files_with={n})", flush=True)
# D) current mv._grep end to end
for _ in range(3):
    t0 = time.perf_counter(); h, _ = mv._grep(r"\b"+name+r"\b", 300, "code"); dt = (time.perf_counter()-t0)*1000
    print(f"  mv._grep end-to-end:           {dt:7.1f}ms (hits={len(h)})", flush=True)

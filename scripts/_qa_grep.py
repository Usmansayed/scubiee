from __future__ import annotations
import os, time
os.environ.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")
os.environ.setdefault("CTX_REPO", r"C:\Users\usman\Downloads\context-engine")
os.environ["MINI_REPO"] = os.environ["CTX_REPO"]
import pipeline.map_v3_helpers as mv

mv._warm()
print(f"cached_lines={len(mv._LINES)} cached_text={len(mv._TEXT)}", flush=True)
# How many files does grep consider, and how long to scan them repeatedly?
want = ("code", "tests")
files = [f for f in mv._repo_files() if __import__("pathlib").Path(f).suffix.lower() in mv._GREP_EXT and mv._kind_of(f) in want]
print(f"grep candidate files={len(files)}", flush=True)
total_bytes = sum(len(mv._text(f)) for f in files)
print(f"total scanned bytes={total_bytes:,} (~{total_bytes/1_000_000:.1f} MB)", flush=True)
for pat in ("choose_strategy", "embed_many", "run_ship_ladder"):
    for trial in range(3):
        t0 = time.perf_counter()
        hits, trunc = mv._grep(pat, max_hits=300, scope="code")
        print(f"  _grep({pat!r}) trial{trial} {(time.perf_counter()-t0)*1000:7.0f}ms hits={len(hits)}", flush=True)
# how much is the whole-file precheck vs per-line?
import re
t0 = time.perf_counter()
rx = re.compile("choose_strategy", re.MULTILINE)
nmatch = sum(1 for f in files if rx.search(mv._text(f)))
print(f"  whole-file precheck only over {len(files)} files: {(time.perf_counter()-t0)*1000:.0f}ms (files_with_hit={nmatch})", flush=True)

"""Issue 6: where does a one-file graph catch-up spend its time?

Copies the live graph.json to a temp dir (the store is never written) and runs
the same patch the keeper runs for one changed file, timing each phase.

    python scripts/graph_merge_profile.py <repo> <repo-relative file>
"""

from __future__ import annotations

import cProfile
import pstats
import shutil
import sys
import tempfile
import time
from pathlib import Path


def main() -> int:
    repo = Path(sys.argv[1]).resolve()
    rel = sys.argv[2]
    from pipeline.project_id import peek_project

    ref = peek_project(repo)
    src = ref.store_dir / "graph.json"
    tmp = Path(tempfile.mkdtemp(prefix="graph_merge_profile_"))
    out = tmp / "graph.json"
    shutil.copy2(src, out)

    from graphify.extract import extract

    t = time.perf_counter()
    raw = extract([repo / rel], root=repo, cache_root=tmp)
    t_extract = time.perf_counter() - t

    from graphify import build as gb

    phases: dict[str, float] = {}
    real_load = gb._load_existing_graph
    real_build = gb.build

    def timed_load(*a, **k):
        t0 = time.perf_counter()
        try:
            return real_load(*a, **k)
        finally:
            phases["load_existing_graph"] = time.perf_counter() - t0

    def timed_build(*a, **k):
        t0 = time.perf_counter()
        try:
            return real_build(*a, **k)
        finally:
            phases["build(dedup=True)"] = time.perf_counter() - t0

    gb._load_existing_graph = timed_load
    gb.build = timed_build
    from conductor.graphify_retriever import patch_and_save_graph

    prof = cProfile.Profile()
    t = time.perf_counter()
    prof.enable()
    patch_and_save_graph(raw, repo, out)
    prof.disable()
    total = time.perf_counter() - t
    print(f"extract one file: {t_extract * 1000:.0f} ms")
    print(f"patch_and_save_graph total: {total * 1000:.0f} ms")
    for k, v in phases.items():
        print(f"  {k}: {v * 1000:.0f} ms")
    print(f"  rest (json export + reload): {(total - sum(phases.values())) * 1000:.0f} ms")
    stats = pstats.Stats(prof)
    stats.sort_stats("cumulative").print_stats(18)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

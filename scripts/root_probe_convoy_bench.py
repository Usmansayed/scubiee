"""Issue 4 follow-up: the change poll's per-file stat under GIL contention.

Read-only. Times ``root_probe._rebuild_universe`` over the live store's indexed
files, alone and with N CPU-bound Python threads running (what concurrent
/v1/search requests do to the keeper). Each ``os.stat`` releases the GIL and
has to win it back from a busy thread (the "convoy effect", bpo-7946).

    python scripts/root_probe_convoy_bench.py <repo> [busy_threads]
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path


def main() -> int:
    repo = Path(sys.argv[1]).resolve()
    busy = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    from pipeline import root_probe as rp
    from pipeline.ignore import load_scubiee_ignore
    from pipeline.merkle import is_junk_rel
    from pipeline.project_id import peek_project
    from pipeline.store import PipelineStore

    ref = peek_project(repo)
    store = PipelineStore(repo, base_dir=ref.store_dir, project_id=ref.project_id, resolve=False)
    rules = load_scubiee_ignore(repo)
    snap = {k: v for k, v in store.load_merkle().items() if not is_junk_rel(k, root=repo, rules=rules)}
    mtimes = store.load_mtimes()
    print(f"indexed files: {len(snap)}  dirs: {len({str(Path(k).parent) for k in snap})}")

    def run(label: str) -> None:
        t = time.perf_counter()
        cur, hashed = rp._rebuild_universe(repo, snap, mtimes)
        print(f"  {label:<28} {(time.perf_counter() - t) * 1000:7.0f} ms  files={len(cur)} hashed={hashed}")

    run("idle")
    stop = threading.Event()

    def spin() -> None:
        x = 0
        while not stop.is_set():
            for i in range(10000):
                x += i * i

    threads = [threading.Thread(target=spin, daemon=True) for _ in range(busy)]
    for th in threads:
        th.start()
    time.sleep(0.2)
    run(f"{busy} busy thread(s)")
    # The whole change poll the keeper runs every second (not just the stats).
    import cProfile
    import pstats

    watch = rp.DirWatch()
    kw = {"store": store} if "store" in rp.root_probe.__code__.co_varnames else {}
    rp.root_probe(repo, discover_newcomers=False, dir_watch=watch, **kw)
    prof = cProfile.Profile()
    t = time.perf_counter()
    prof.enable()
    rp.root_probe(repo, discover_newcomers=False, dir_watch=watch, **kw)
    prof.disable()
    print(f"  {'full root_probe, busy':<28} {(time.perf_counter() - t) * 1000:7.0f} ms")
    pstats.Stats(prof).sort_stats("cumulative").print_stats(14)
    stop.set()
    for th in threads:
        th.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

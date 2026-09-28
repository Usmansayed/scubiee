"""Issue 4 follow-up: cost of the keeper's per-drain chunk-count estimate.

``_estimate_dirty_chunks`` parsed all of chunks.jsonl (every chunk's text) on
every drain, hot saves included. Read-only; times it idle and with one busy
thread against a byte-level count of the ``"file"`` field.

    python scripts/estimate_cost_bench.py <repo>
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path


def main() -> int:
    repo = Path(sys.argv[1]).resolve()
    from pipeline.project_id import peek_project
    from pipeline.store import PipelineStore
    from pipeline.sync_loop import count_chunks_per_file

    ref = peek_project(repo)
    st = PipelineStore(repo, base_dir=ref.store_dir, project_id=ref.project_id, resolve=False)

    def full() -> dict[str, int]:
        c: dict[str, int] = {}
        for ch in st.load_chunks():
            k = ch.file.replace("\\", "/")
            c[k] = c.get(k, 0) + 1
        return c

    print(f"chunks.jsonl {st.chunks_path.stat().st_size / 2**20:.1f} MB", flush=True)
    for label in ("idle", "1 busy thread"):
        stop = threading.Event()
        if label != "idle":
            def spin() -> None:
                x = 0
                while not stop.is_set():
                    for i in range(10000):
                        x += i
            threading.Thread(target=spin, daemon=True).start()
            time.sleep(0.1)
        t = time.perf_counter()
        a = full()
        t_full = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        b = count_chunks_per_file(st.chunks_path)
        t_fast = (time.perf_counter() - t) * 1000
        stop.set()
        print(f"{label:<14} load_chunks={t_full:7.0f} ms  byte count={t_fast:6.0f} ms  "
              f"files={len(a)} equal={a == b}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

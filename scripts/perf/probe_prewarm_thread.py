"""Is the ~400ms first-_http tax process-global or main-thread-local?
In ONE process: run _http('/health') on a background thread, join it, THEN time
_http on the main thread. If main-thread call is fast -> prewarm works (cost is
process-global). If still ~400ms -> cost is per-thread or per the main thread's first
socket op, and a bg prewarm cannot hide it."""
from __future__ import annotations
import os, sys, threading, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v
import pipeline.map_v3_helpers as mv  # noqa: E402


def main():
    # background thread pays the first _http
    bg_ms = []
    def bg():
        t0 = time.perf_counter()
        mv._http("/health", None, 8)
        bg_ms.append((time.perf_counter() - t0) * 1000)
    th = threading.Thread(target=bg); th.start(); th.join()
    # now main thread
    t0 = time.perf_counter()
    mv._http("/health", None, 8)
    main_ms = (time.perf_counter() - t0) * 1000
    # control: a fresh process baseline is measured elsewhere
    print(f"bg_first_http_ms   = {bg_ms[0]:.1f}")
    print(f"main_after_bg_ms   = {main_ms:.1f}")


if __name__ == "__main__":
    main()

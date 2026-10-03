"""Profile INSIDE the engine's /health to find the variable cost (min 3.4ms vs
p50 15.7ms). ce.health() is in-process in the ENGINE, so we measure it by timing
the known per-call sub-parts in isolation against the live engine's modules."""
from __future__ import annotations
import os, sys, time, statistics
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, http, stat, base_env  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v


def many(fn, n=30):
    xs = []
    for _ in range(n):
        t0 = time.perf_counter(); fn(); xs.append((time.perf_counter() - t0) * 1000)
    return stat(xs)


def main():
    # 1) end-to-end /health over HTTP (loopback), many samples to see the spread
    http("/health")
    print("E2E /health:", many(lambda: http("/health"), 40))

    # 2) read_phase() in isolation — the one per-call disk read in ce.health()
    try:
        from pipeline.warm_autoload import read_phase
        print("read_phase():", many(read_phase, 40))
    except Exception as e:
        print("read_phase err", e)

    # 3) embedder_is_loaded / prewarm_status cached flags
    try:
        from pipeline.engine import embedder_is_loaded, prewarm_status
        print("embedder_is_loaded():", many(embedder_is_loaded, 40))
        print("prewarm_status():", many(prewarm_status, 40))
    except Exception as e:
        print("engine flags err", e)

    # 4) is the spread the loopback TCP connect, or the handler? Compare a
    #    keep-alive-ish rapid burst vs spaced calls.
    burst = []
    for _ in range(40):
        t0 = time.perf_counter(); http("/health"); burst.append((time.perf_counter() - t0) * 1000)
    print("burst /health:", stat(burst))
    spaced = []
    for _ in range(10):
        t0 = time.perf_counter(); http("/health"); spaced.append((time.perf_counter() - t0) * 1000)
        time.sleep(0.25)
    print("spaced /health (0.25s gap):", stat(spaced))


if __name__ == "__main__":
    main()

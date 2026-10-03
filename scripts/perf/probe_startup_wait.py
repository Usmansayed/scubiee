"""STARTUP — is the first-call tax the cold LOCAL cache (warm thread not done) or the
engine round-trip? Compare: first call IMMEDIATELY after init vs first call AFTER
waiting for the _warm bg thread (~2s). If waiting collapses it to steady, the tax is
local cold reads; if it stays high, it's the engine /v1/search."""
from __future__ import annotations
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, stat, StdioWorker  # noqa: E402


def cycle(wait_s):
    w = StdioWorker()
    w.init()
    if wait_s:
        time.sleep(wait_s)
    t = time.perf_counter()
    w.call("map", {"config": "find", "query": "freshness decision"})
    first = (time.perf_counter() - t) * 1000
    t2 = time.perf_counter()
    w.call("map", {"config": "find", "query": "freshness decision"})
    steady = (time.perf_counter() - t2) * 1000
    w.close()
    return first, steady


def main():
    no_wait_first, no_wait_steady = [], []
    wait_first, wait_steady = [], []
    for _ in range(4):
        f, s = cycle(0.0)
        no_wait_first.append(f); no_wait_steady.append(s)
    for _ in range(4):
        f, s = cycle(2.5)
        wait_first.append(f); wait_steady.append(s)
    rep = {
        "no_wait_first": stat(no_wait_first), "no_wait_steady": stat(no_wait_steady),
        "waited_first": stat(wait_first), "waited_steady": stat(wait_steady),
    }
    print("no-wait first :", rep["no_wait_first"])
    print("no-wait steady:", rep["no_wait_steady"])
    print("waited  first :", rep["waited_first"])
    print("waited  steady:", rep["waited_steady"])
    Path(REPO, "dist", "_perf_startup_wait.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print("WROTE dist/_perf_startup_wait.json")


if __name__ == "__main__":
    main()

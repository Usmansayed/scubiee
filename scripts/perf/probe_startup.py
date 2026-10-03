"""TOOL 7 — STARTUP / WARMUP. Isolates one-time costs from steady-state latency.
Engine is kept warm+dense so this measures the WORKER side:
  A) process spawn + import + initialize handshake (StdioWorker)
  B) first tools/call (cold worker caches, racing the _warm bg thread)
  C) steady-state call after warm
  D) in-process _warm() wall + _repo_files() walk, measured directly
Repeats the spawn a few times for a stable spawn/import number."""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import REPO, PY, stat, base_env, StdioWorker  # noqa: E402


def spawn_cycle():
    t0 = time.perf_counter()
    w = StdioWorker()
    w.init()  # spawn + import + initialize + notifications/initialized
    t_init = (time.perf_counter() - t0) * 1000
    # first real tool call (cold caches, _warm racing)
    t1 = time.perf_counter()
    txt, _ = w.call("map", {"config": "find", "query": "freshness decision"})
    t_first = (time.perf_counter() - t1) * 1000
    # steady state (same call again, caches primed)
    t2 = time.perf_counter()
    w.call("map", {"config": "find", "query": "freshness decision"})
    t_steady = (time.perf_counter() - t2) * 1000
    w.close()
    return t_init, t_first, t_steady, len(txt)


def inproc_warm():
    env = base_env()
    for k, v in env.items():
        os.environ[k] = v
    import importlib
    import pipeline.map_v3_helpers as mv
    importlib.reload(mv)
    t0 = time.perf_counter()
    files = mv._repo_files()
    t_walk = (time.perf_counter() - t0) * 1000
    t1 = time.perf_counter()
    mv._warm()
    t_warm = (time.perf_counter() - t1) * 1000
    return t_walk, t_warm, len(files)


def main():
    inits, firsts, steadies = [], [], []
    for _ in range(4):
        ti, tf, ts, n = spawn_cycle()
        inits.append(ti); firsts.append(tf); steadies.append(ts)
        print(f"  spawn+init={ti:7.1f}ms  first_call={tf:7.1f}ms  steady={ts:7.1f}ms  out={n}c")
    t_walk, t_warm, nf = inproc_warm()
    print(f"\n  in-proc: _repo_files walk={t_walk:.1f}ms  _warm()={t_warm:.1f}ms  files={nf}")
    report = {
        "spawn_init_ms": stat(inits),
        "first_call_ms": stat(firsts),
        "steady_call_ms": stat(steadies),
        "repo_walk_ms": round(t_walk, 1),
        "warm_ms": round(t_warm, 1),
        "n_files": nf,
    }
    print("\n## spawn+init:", report["spawn_init_ms"])
    print("## first_call:", report["first_call_ms"])
    print("## steady    :", report["steady_call_ms"])
    Path(REPO, "dist", "_perf_startup.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("WROTE dist/_perf_startup.json")


if __name__ == "__main__":
    main()

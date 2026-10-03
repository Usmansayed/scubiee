"""TOOL 1 (status) + TOOL 2 (gate): measure the health-signal tools and the
transport floor every tool pays. Both tools = one _http('/health') + trivial
string format, so this also measures: raw engine /health, in-process tool,
stdio-worker round-trip, and the bridge path."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _perf_harness import (  # noqa: E402
    REPO, http, stat, timeit, StdioWorker, ensure_engine_warm, base_env,
)

import os  # noqa: E402
for k, v in base_env().items():
    os.environ[k] = v

OUT = {}


def section(name, obj):
    OUT[name] = obj
    print(f"\n## {name}")
    print(json.dumps(obj, indent=2))


def main():
    h = ensure_engine_warm(dense=True)
    print(f"engine: ok={h.get('ok')} dense={h.get('dense_ready')} chunks={h.get('chunks')} v={h.get('version')}")

    # --- A) raw engine /health round-trip (the transport+engine floor) ---
    http("/health")  # warm the connection
    samples = [timeit(http, "/health")[1] for _ in range(15)]
    section("raw_engine_health_ms", stat(samples))

    # --- B) in-process tool_gate / tool_status (helper CPU only, no stdio) ---
    import pipeline.map_v3_helpers as mv
    mv._http("/health")  # warm
    g = [timeit(mv.tool_gate, {})[1] for _ in range(15)]
    s = [timeit(mv.tool_status, {})[1] for _ in range(15)]
    section("inproc_gate_ms", stat(g))
    section("inproc_status_ms", stat(s))
    # confirm outputs
    OUT["sample_gate"] = mv.tool_gate({})
    OUT["sample_status"] = mv.tool_status({})
    print("gate ->", OUT["sample_gate"])
    print("status ->", OUT["sample_status"])

    # --- C) stdio worker round-trip (adds worker process + stdio framing) ---
    w = StdioWorker()
    try:
        _, init_ms = timeit(w.init)
        OUT["stdio_worker_init_ms"] = round(init_ms, 1)
        # first call (cold worker: _warm thread may still be running)
        _, first_g = timeit(lambda: w.call("gate", {}))
        OUT["stdio_gate_first_ms"] = round(first_g, 1)
        gw = [timeit(lambda: w.call("gate", {}))[1] for _ in range(15)]
        sw = [timeit(lambda: w.call("status", {}))[1] for _ in range(15)]
        section("stdio_gate_ms", stat(gw))
        section("stdio_status_ms", stat(sw))
    finally:
        w.close()

    # --- D) bridge path (real production: bridge proxies to a spawned worker) ---
    import subprocess
    br = subprocess.Popen(
        [sys.executable, "-u", "-m", "pipeline.mcp_bridge"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", env=os.environ, cwd=REPO,
    )
    try:
        _id = {"n": 0}

        def brpc(method, params=None):
            _id["n"] += 1
            br.stdin.write(json.dumps({"jsonrpc": "2.0", "id": _id["n"], "method": method, "params": params or {}}) + "\n")
            br.stdin.flush()
            return json.loads(br.stdout.readline())

        _, binit = timeit(brpc, "initialize")
        OUT["bridge_init_ms"] = round(binit, 1)
        br.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"); br.stdin.flush()

        def bcall(name):
            r = brpc("tools/call", {"name": name, "arguments": {}})
            return r.get("result", {}).get("content", [{}])[0].get("text", "")

        _, bfirst = timeit(lambda: bcall("gate"))
        OUT["bridge_gate_first_ms"] = round(bfirst, 1)
        bg = [timeit(lambda: bcall("gate"))[1] for _ in range(10)]
        bs = [timeit(lambda: bcall("status"))[1] for _ in range(10)]
        section("bridge_gate_ms", stat(bg))
        section("bridge_status_ms", stat(bs))
    finally:
        try:
            br.stdin.close(); br.terminate()
        except Exception:
            pass

    Path(REPO, "dist", "_perf_health.json").write_text(json.dumps(OUT, indent=2), encoding="utf-8")
    print("\nWROTE dist/_perf_health.json")


if __name__ == "__main__":
    main()

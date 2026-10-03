"""Reusable measurement harness for the Scubiee MCP performance investigation.

Three measurement surfaces:
  1) engine HTTP直接   — time a raw /health or /v1/* round-trip (isolates engine).
  2) in-process tool   — import map_v3_server, call tool_map/tool_gate/tool_status
                         (isolates bridge/helper CPU; no stdio).
  3) stdio worker      — spawn `python -m pipeline.map_v3_server`, drive JSON-RPC
                         over its pipes (adds worker process + stdio framing).
  4) bridge path       — spawn `python -m pipeline.mcp_bridge` (the real prod path:
                         bridge proxies to a spawned worker).

Usage: imported by per-tool probes. Run those, not this.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path

REPO = r"C:\Users\usman\Downloads\context-engine"
PID = "ce_3536ac8e8e83bb8e4d888db37847729c"
PY = r"C:\Users\usman\Miniconda3\python.exe"
ENGINE = "http://127.0.0.1:8765"


def base_env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(Path(REPO) / "packages")
    env["PYTHONIOENCODING"] = "utf-8"
    env["CTX_ENGINE_URL"] = ENGINE
    env["CTX_REPO"] = REPO
    env["CTX_PROJECT_ID"] = PID
    for k in ("MINI_ENGINE_URL", "MINI_REPO", "MINI_PROJECT_ID"):
        env.pop(k, None)
    return env


def http(path: str, payload=None, timeout=60):
    url = ENGINE + path
    data = None if payload is None else json.dumps(payload).encode()
    headers = {} if payload is None else {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def stat(samples: list[float]) -> dict:
    s = sorted(samples)
    return {
        "n": len(s),
        "min": round(s[0], 1),
        "p50": round(statistics.median(s), 1),
        "p95": round(s[min(len(s) - 1, int(len(s) * 0.95))], 1),
        "max": round(s[-1], 1),
        "mean": round(statistics.mean(s), 1),
    }


def timeit(fn, *a, **k):
    t0 = time.perf_counter()
    out = fn(*a, **k)
    return out, (time.perf_counter() - t0) * 1000


class StdioWorker:
    """Drive one `python -m pipeline.map_v3_server` over its stdio pipes."""

    def __init__(self, module="pipeline.map_v3_server"):
        self.p = subprocess.Popen(
            [PY, "-u", "-m", module],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", env=base_env(), cwd=REPO,
        )
        self._id = 0

    def rpc(self, method, params=None):
        self._id += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline())

    def notify(self, method):
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.p.stdin.flush()

    def init(self):
        r = self.rpc("initialize")
        self.notify("notifications/initialized")
        return r

    def call(self, name, args):
        r = self.rpc("tools/call", {"name": name, "arguments": args})
        return r.get("result", {}).get("content", [{}])[0].get("text", ""), r

    def close(self):
        try:
            self.p.stdin.close(); self.p.terminate()
        except Exception:
            pass


def ensure_engine_warm(dense: bool = True, wait_s: float = 120) -> dict:
    """Make sure the engine is up and (optionally) dense before measuring."""
    import pipeline.daemon as d  # noqa
    from pathlib import Path as _P
    try:
        d.ensure_daemon(_P(REPO), force_if_hung=False)
    except Exception:
        pass
    t0 = time.time()
    last = {}
    while time.time() - t0 < wait_s:
        try:
            last = http("/health", timeout=8)
            if last.get("ok") and (not dense or last.get("dense_ready")):
                return last
            if dense and not last.get("dense_ready"):
                # nudge the embedder with one search
                try:
                    http("/v1/search", {"query": "warm nudge", "top_k": 3, "path": REPO}, timeout=90)
                except Exception:
                    pass
        except Exception:
            pass
        time.sleep(2)
    return last

#!/usr/bin/env python3
"""Probe /health + /v1/embed/prewarm and print wall timings."""
from __future__ import annotations

import json
import time
import urllib.request

BASE = "http://127.0.0.1:8765"
ROOT = r"C:\Users\usman\Downloads\context-engine"


def get(path: str, timeout: float = 10.0):
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
            body = r.read().decode()
        return round((time.perf_counter() - t0) * 1000, 1), json.loads(body)
    except Exception as e:  # noqa: BLE001
        return round((time.perf_counter() - t0) * 1000, 1), {"error": str(e)}


def post(path: str, data: dict, timeout: float = 60.0):
    t0 = time.perf_counter()
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
        return round((time.perf_counter() - t0) * 1000, 1), json.loads(body)
    except Exception as e:  # noqa: BLE001
        return round((time.perf_counter() - t0) * 1000, 1), {"error": str(e)}


def main() -> None:
    ms, h = get("/health")
    print("HEALTH", ms, json.dumps(h)[:600])
    ms, p = post(
        "/v1/embed/prewarm",
        {"path": ROOT, "wait": False},
        timeout=15,
    )
    print("PREWARM_ASYNC", ms, json.dumps(p)[:1000])
    for i in range(18):
        time.sleep(5)
        ms, h = get("/health")
        print(
            f"T+{(i+1)*5}s HEALTH {ms}ms embedder={h.get('embedder_loaded')} "
            f"running={h.get('embed_prewarm_running')} dense={h.get('dense_ready')} "
            f"keys={sorted(h.keys()) if isinstance(h, dict) else h}"
        )
        if h.get("embedder_loaded"):
            break
        if h.get("error"):
            print("  health_error", h.get("error"))
    ms, p2 = post(
        "/v1/embed/prewarm",
        {"path": ROOT, "wait": True, "sync": True, "wait_s": 25},
        timeout=40,
    )
    print("PREWARM_SYNC", ms, json.dumps(p2)[:1500])
    ms, h = get("/health")
    print("FINAL_HEALTH", ms, json.dumps(h)[:600])


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Probe semantic search latency after an idle gap (embed keepalive acceptance).

Usage:
  python scripts/probe_idle_map_keepalive.py --idle-s 120
  uv run python scripts/probe_idle_map_keepalive.py --idle-s 45

Registers a probe client so keepalive runs, prewarms, baselines a search,
sleeps, then searches again. Target: after_idle_ms < 2000 (prefer <500).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--idle-s", type=float, default=120.0)
    ap.add_argument("--repo", default=os.environ.get("CTX_REPO") or str(Path.cwd()))
    ap.add_argument(
        "--query",
        default="BackgroundSyncLoop keeper_tick embed keepalive RuntimeController",
    )
    args = ap.parse_args()
    root = Path(args.repo).resolve()
    os.environ.setdefault("CTX_REPO", str(root))

    from pipeline.client import EngineClient

    client = EngineClient(workspace_path=str(root), timeout=60.0)
    cid = f"probe:keepalive@{os.getpid()}"
    try:
        reg = client.post(
            "/v1/client/register",
            {"client_id": cid, "pid": os.getpid(), "kind": "probe"},
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"register: {exc}"}))
        return 2

    try:
        pre = client.post(
            "/v1/embed/prewarm", {"path": str(root), "wait": True, "sync": True}
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"prewarm: {exc}"}))
        return 2

    ka = client.post(
        "/v1/embed/keepalive",
        {"path": str(root), "ensure_loop": True, "tick": 0},
    )

    def _search(q: str) -> float:
        t0 = time.perf_counter()
        client.post("/v1/search", {"path": str(root), "query": q, "k": 8})
        return round((time.perf_counter() - t0) * 1000, 1)

    e1 = _search(args.query)
    print(
        f"[probe] baseline search_ms={e1} clients={(reg or {}).get('active_clients')} "
        f"keepalive={ka}",
        flush=True,
    )
    print(f"[probe] sleeping idle_s={args.idle_s}…", flush=True)
    time.sleep(max(0.0, float(args.idle_s)))

    e2 = _search(args.query + " after-idle")
    try:
        st = client.post(
            "/v1/embed/keepalive",
            {"path": str(root), "ensure_loop": False, "tick": 0},
        )
    except Exception:  # noqa: BLE001
        st = {}

    ok = e2 < 2000.0
    out = {
        "ok": ok,
        "baseline_search_ms": e1,
        "after_idle_search_ms": e2,
        "idle_s": args.idle_s,
        "target_ms": 2000,
        "prewarm": {
            k: (pre or {}).get(k)
            for k in ("ok", "already_warm", "ms", "embedder_loaded")
        },
        "keepalive_status": (st or {}).get("status") or st,
    }
    print(json.dumps(out, indent=2))
    try:
        client.post("/v1/client/unregister", {"client_id": cid})
    except Exception:  # noqa: BLE001
        pass
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

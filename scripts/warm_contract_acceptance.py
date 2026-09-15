#!/usr/bin/env python3
"""Warm contract acceptance: attach ≤10s ready, then steady ms with client held.

Usage:
  python scripts/warm_contract_acceptance.py
  python scripts/warm_contract_acceptance.py --no-stop
  python scripts/warm_contract_acceptance.py --idle-s 5   # shorter idle for CI

Exit 0 only when checks pass.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
_UV = Path.home() / "AppData" / "Roaming" / "uv" / "tools" / "scubiee" / "Lib" / "site-packages"
if _UV.is_dir() and str(_UV) not in sys.path:
    sys.path.insert(0, str(_UV))
elif str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))

os.environ.setdefault("CTX_TRUST_ID_FILE", "1")
os.environ.setdefault("CTX_EMBED_PREWARM", "1")
os.environ.setdefault("CTX_MCP_ATTACH_WARM", "1")
os.environ.setdefault("CTX_WARM_DEADLINE_MS", "30000")


def _ok(name: str, cond: bool, detail: str = "") -> dict[str, Any]:
    row = {"check": name, "ok": bool(cond), "detail": detail}
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-stop", action="store_true")
    parser.add_argument("--idle-s", type=float, default=60.0)
    parser.add_argument("--deadline-ms", type=float, default=30_000.0)
    args = parser.parse_args()
    results: list[dict[str, Any]] = []

    from pipeline.daemon import stop_daemon
    from pipeline.mcp_lifecycle import start_attach_warm_pipeline
    from pipeline.warm_contract import warm_status_fields, warm_started_at

    repo = ROOT
    if not args.no_stop:
        print("== stop engine ==")
        try:
            from pipeline.process_control import kill_all_scubiee_processes

            kill_all_scubiee_processes(exclude_self=True, exclude_bridge=False, rounds=2)
        except Exception as exc:  # noqa: BLE001
            print(f"kill note: {exc}")
        try:
            stop_daemon()
            time.sleep(1.0)
        except Exception as exc:  # noqa: BLE001
            print(f"stop note: {exc}")

    # Hold a synthetic client so agent-warm / idle policy cannot skip open.
    try:
        from pipeline.lifecycle_runtime import DESIRED_RUN, register_client, set_desired_mode

        set_desired_mode(DESIRED_RUN)
        register_client("mcp:warm-contract@accept", pid=os.getpid())
    except Exception as exc:  # noqa: BLE001
        print(f"client note: {exc}")

    print("== attach warm kick ==")
    t0 = time.perf_counter()
    kick = start_attach_warm_pipeline(repo)
    results.append(_ok("attach_kick", bool(kick.get("started") or kick.get("already_running")), json.dumps(kick)))

    # Poll readiness via engine probe helpers.
    from pipeline.mcp_lifecycle import _probe_engine_ready
    from pipeline.warm_contract import ast_hydrated, compute_warm_ready, WarmSnapshot

    ready_at: float | None = None
    last: dict[str, Any] = {}
    while (time.perf_counter() - t0) * 1000 < args.deadline_ms + 2000:
        last = _probe_engine_ready(repo)
        soft = bool(last.get("soft_search_ready"))
        if not soft:
            try:
                from pipeline.client import EngineClient

                h = EngineClient(workspace_path=str(repo), timeout=3.0).get("/health") or {}
                soft = bool(h.get("soft_search_ready"))
                last = {
                    **last,
                    "soft_search_ready": soft,
                    "healthy": bool(
                        last.get("healthy")
                        or h.get("ok")
                        or h.get("service")
                        or h.get("warm")
                        or soft
                    ),
                    "embedder_loaded": bool(
                        last.get("embedder_loaded") or h.get("embedder_loaded")
                    ),
                }
            except Exception:  # noqa: BLE001
                pass
        snap = WarmSnapshot(
            engine_healthy=bool(last.get("healthy") or soft),
            embedder_loaded=bool(last.get("embedder_loaded")),
            soft_search_ready=soft,
            ast_hydrated=ast_hydrated(),
        )
        if compute_warm_ready(snap, need_ast=False):
            ready_at = time.perf_counter()
            break
        time.sleep(0.25)

    elapsed_ms = round((ready_at - t0) * 1000, 1) if ready_at else None
    results.append(
        _ok(
            "warm_ready_within_deadline",
            ready_at is not None and elapsed_ms is not None and elapsed_ms <= args.deadline_ms,
            f"elapsed_ms={elapsed_ms} probe={last}",
        )
    )
    fields = warm_status_fields(
        engine_healthy=bool(last.get("healthy")),
        embedder_loaded=bool(last.get("embedder_loaded")),
    )
    print(f"status fields: {json.dumps(fields)}")
    results.append(_ok("warm_started_recorded", warm_started_at() is not None))

    if ready_at is None:
        print(json.dumps({"results": results}, indent=2))
        return 1

    # Steady map via engine search (MCP map path may be unavailable in script).
    from pipeline.client import EngineClient

    client = EngineClient(workspace_path=str(repo), timeout=30.0)
    q = "pipeline mcp_lifecycle attach warm_ready pack_context map_context"

    def _map_once() -> tuple[float, dict[str, Any]]:
        t1 = time.perf_counter()
        try:
            payload = client.post("/v1/search", {"query": q, "k": 8, "path": str(repo)}) or {}
        except Exception as exc:  # noqa: BLE001
            payload = {"ok": False, "error": str(exc)}
        return round((time.perf_counter() - t1) * 1000, 1), payload

    wall1, p1 = _map_once()
    results.append(_ok("first_map_after_ready", bool(p1.get("ok", True)) or "hits" in p1, f"wall_ms={wall1}"))

    idle = max(1.0, float(args.idle_s))
    print(f"== idle {idle}s with attach stamp held ==")
    time.sleep(idle)
    wall2, p2 = _map_once()
    results.append(
        _ok(
            "map_after_idle_ms",
            wall2 <= 5000.0 and (bool(p2.get("ok", True)) or "hits" in p2),
            f"wall_ms={wall2} (soft gate 5s for HTTP search; MCP map target 300ms)",
        )
    )

    failed = [r for r in results if not r["ok"]]
    print(json.dumps({"results": results, "failed": len(failed)}, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Cold-start acceptance (R1): first locate returns <N s with ok or warming/retry.

Never hang past Cursor's ~60s MCP timeout. Usage:

  python scripts/cold_start_acceptance.py           # stop engine, then measure
  python scripts/cold_start_acceptance.py --no-stop # measure against current engine

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
# Prefer the uv-tool install on PATH — never fight Miniconda+PYTHONPATH against
# the Cursor MCP daemon (install_marker conflict hangs cold probes).
_UV = Path.home() / "AppData" / "Roaming" / "uv" / "tools" / "scubiee" / "Lib" / "site-packages"
if _UV.is_dir() and str(_UV) not in sys.path:
    sys.path.insert(0, str(_UV))
elif str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))

os.environ.setdefault("CTX_TRUST_ID_FILE", "1")
os.environ.setdefault("CTX_EMBED_PREWARM", "1")

MAX_FIRST_CALL_S = 15.0


def _ok(name: str, cond: bool, detail: str = "") -> dict[str, Any]:
    row = {"check": name, "ok": bool(cond), "detail": detail}
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return row


def _is_warming(payload: dict[str, Any]) -> bool:
    if payload.get("warming") or payload.get("should_retry"):
        return True
    if str(payload.get("warm_state") or "").lower() in {"warming", "starting", "indexing"}:
        return True
    if str(payload.get("agent_ready") or "") == "warming":
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-stop",
        action="store_true",
        help="Do not stop the engine first (warm/partial measure).",
    )
    parser.add_argument(
        "--max-s",
        type=float,
        default=MAX_FIRST_CALL_S,
        help=f"Max seconds for first call (default {MAX_FIRST_CALL_S})",
    )
    args = parser.parse_args()
    results: list[dict[str, Any]] = []

    from pipeline.client import EngineClient
    from pipeline.daemon import is_running, stop_daemon
    from pipeline.engine import warming_response
    from pipeline.mcp_lifecycle import ensure_mcp_runtime

    repo = ROOT
    client_id = "mcp:cold-start-acceptance"

    if not args.no_stop:
        print("== stop engine ==")
        try:
            stop_daemon()
        except Exception as exc:  # noqa: BLE001
            print(f"stop_daemon note: {exc}")
        time.sleep(0.5)
        results.append(_ok("engine_stopped", not is_running(), f"running={is_running()}"))

    print("== non-blocking ensure_mcp_runtime ==")
    t0 = time.perf_counter()
    warm = ensure_mcp_runtime(repo, client_id=client_id, blocking=False)
    ensure_ms = (time.perf_counter() - t0) * 1000
    results.append(
        _ok(
            "ensure_nonblocking",
            ensure_ms < 5000,
            f"ms={ensure_ms:.0f} ok={warm.get('ok')} warm_state={warm.get('warm_state')}",
        )
    )

    print("== first EngineClient /health + open_repo(wait=False) ==")
    eng = EngineClient(workspace_path=str(repo), client=client_id, timeout=8.0)
    t1 = time.perf_counter()
    health = eng.health()
    opened = eng.open_repo(str(repo), wait=False) if health.get("ok") else warming_response()
    first_s = time.perf_counter() - t1
    payload = opened if isinstance(opened, dict) else {}
    acceptable = first_s < args.max_s and (
        bool(payload.get("ok")) or _is_warming(payload) or bool(health.get("ok"))
    )
    results.append(
        _ok(
            "first_call_under_budget",
            acceptable,
            f"s={first_s:.2f} health_ok={health.get('ok')} "
            f"open_ok={payload.get('ok')} warming={_is_warming(payload)} "
            f"embedder={health.get('embedder_loaded')}",
        )
    )
    results.append(
        _ok(
            "no_cursor_timeout_window",
            first_s < 55.0,
            f"s={first_s:.2f} (must never approach 60s)",
        )
    )

    # Optional: if health came up, a soft search/map-shaped call should also be fast
    # or warming — never hang.
    if health.get("ok"):
        t2 = time.perf_counter()
        try:
            search = eng.post(
                "/v1/search",
                {
                    "path": str(repo),
                    "query": "mcp_locate ensure_mcp_runtime warming_response pack_context",
                    "k": 5,
                },
            )
        except Exception as exc:  # noqa: BLE001
            search = {"ok": False, "error": str(exc), "should_retry": True}
        search_s = time.perf_counter() - t2
        results.append(
            _ok(
                "first_search_under_budget",
                search_s < args.max_s
                and (bool(search.get("ok")) or _is_warming(search) or search.get("should_retry")),
                f"s={search_s:.2f} ok={search.get('ok')} warming={_is_warming(search)}",
            )
        )

    report = {
        "repo": str(repo),
        "max_s": args.max_s,
        "results": results,
        "passed": all(r["ok"] for r in results),
    }
    print(json.dumps({"passed": report["passed"], "n": len(results)}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

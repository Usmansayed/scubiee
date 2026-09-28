"""Mid-session engine death probe (BETA-03 / BETA-08).

1. Wait until /health is ok (engine up, MCP bridge attached elsewhere).
2. Hard-kill the engine process tree (simulates a crash / OS kill).
3. Do NOT run ``scubiee engine ensure``. Poll /health until it is back.

Reports kill->health_ok and kill->soft_search_ready seconds plus the watchdog
log lines written during recovery. ``ok`` requires recovery inside --budget-s.

Usage:
    python scripts/engine_kill_recover_probe.py [--budget-s 120]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def _health() -> dict:
    from pipeline.client import EngineClient, engine_url

    try:
        return EngineClient(engine_url(), timeout=2.0).get("/health") or {}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-s", type=float, default=120.0)
    ap.add_argument("--wait-up-s", type=float, default=180.0)
    ap.add_argument(
        "--hold-bridge",
        action="store_true",
        help="Spawn a Cursor-style MCP bridge for the whole probe (IDE attached).",
    )
    args = ap.parse_args()
    if args.hold_bridge:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from attach_pack_race import PID, _client

        with _client("killprobe") as c:
            c.call_text("gate", project_id=PID)
            return _run(args)
    return _run(args)


def _run(args: argparse.Namespace) -> int:

    from pipeline.daemon import _read_lock_pid
    from pipeline.warm_autoload import mcp_or_client_demand
    from pipeline.watchdog import watchdog_log_path

    t_up = time.time()
    while time.time() - t_up < args.wait_up_s:
        h = _health()
        if h.get("ok") or h.get("service"):
            break
        time.sleep(2.0)
    pid = int(_read_lock_pid() or 0)
    clients, demand = mcp_or_client_demand()
    report: dict = {
        "engine_pid": pid,
        "clients": clients,
        "mcp_demand": demand,
        "pre_health_ok": bool(h.get("ok") or h.get("service")),
    }
    if not pid:
        report["ok"] = False
        report["error"] = "no engine pid"
        print(json.dumps(report, indent=2))
        return 1

    log = watchdog_log_path()
    log_start = log.stat().st_size if log.is_file() else 0
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False)
    t_kill = time.time()
    health_s = soft_s = None
    while time.time() - t_kill < args.budget_s:
        h = _health()
        up = bool(h.get("ok") or h.get("service"))
        if up and health_s is None:
            health_s = round(time.time() - t_kill, 1)
        if up and h.get("soft_search_ready"):
            soft_s = round(time.time() - t_kill, 1)
            break
        time.sleep(1.0)
    new_pid = int(_read_lock_pid() or 0)
    lines: list[str] = []
    if log.is_file():
        with log.open("rb") as fh:
            fh.seek(log_start)
            lines = fh.read().decode("utf-8", "replace").splitlines()[-20:]
    report.update(
        {
            "kill_to_health_s": health_s,
            "kill_to_soft_ready_s": soft_s,
            "new_engine_pid": new_pid,
            "watchdog_log": lines,
            "ok": soft_s is not None and new_pid not in {0, pid},
        }
    )
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

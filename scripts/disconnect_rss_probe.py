#!/usr/bin/env python3
"""Prove disconnect RAM contract: last client gone → engine process exits.

Uses an isolated CTX_HOME + alt port so it does not touch the live :8765 daemon.
Success metric is process absence (ORT RSS is not returned in-process).

  python scripts/disconnect_rss_probe.py
  python scripts/disconnect_rss_probe.py --warm   # also load FastEmbed and record WS
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))


def _seed_live_index(home: Path) -> None:
    """Copy registry + project/vectordb so isolated open/prewarm can load FastEmbed.

    Copies files (no junctions) so probe rmtree cannot delete the live store.
    Skips graphify-out cache.
    """
    import shutil

    live = Path.home() / ".scubiee"
    registry = live / "registry.json"
    if registry.is_file():
        shutil.copy2(registry, home / "registry.json")
    src_projects = live / "projects"
    if src_projects.is_dir():
        for proj in src_projects.iterdir():
            if not proj.is_dir():
                continue
            dst = home / "projects" / proj.name
            dst.mkdir(parents=True, exist_ok=True)
            for item in proj.iterdir():
                if item.name == "graphify-out":
                    continue
                target = dst / item.name
                if item.is_file():
                    shutil.copy2(item, target)
                elif item.is_dir():
                    shutil.copytree(item, target, dirs_exist_ok=True)
    src_vdb = live / "vectordb"
    if src_vdb.is_dir():
        shutil.copytree(src_vdb, home / "vectordb", dirs_exist_ok=True)
    print(f"seeded_index from {live} -> {home}")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import psutil

        return psutil.Process(int(pid)).is_running()
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--warm",
        action="store_true",
        help="Load FastEmbed before unregister (records Working Set).",
    )
    parser.add_argument(
        "--watchdog",
        action="store_true",
        help="Start watchdog sidecar (repro: restart-during-stop → 2GB).",
    )
    parser.add_argument("--port", type=int, default=18765)
    parser.add_argument("--debounce", type=float, default=10.0)
    args = parser.parse_args()

    home = Path.home() / ".scubiee" / "rss-probe-home"
    if home.exists():
        import shutil

        shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True, exist_ok=True)
    if args.warm:
        _seed_live_index(home)
    os.environ["CTX_HOME"] = str(home)
    os.environ["CTX_ALLOW_TEST_HOME"] = "1"
    os.environ["CTX_ENGINE_URL"] = f"http://127.0.0.1:{int(args.port)}"
    os.environ["CTX_DISCONNECT_DEBOUNCE_S"] = str(float(args.debounce))
    os.environ["CTX_ENGINE_IDLE_S"] = str(float(args.debounce))
    os.environ["CTX_ENGINE_TRANSITION_DEBOUNCE_S"] = "0"
    os.environ["CTX_EMBED_PREWARM"] = "1" if args.warm else "0"
    os.environ["CTX_WATCHDOG"] = "1" if args.watchdog else "0"
    os.environ["CTX_TRUST_ID_FILE"] = "1"
    os.environ["CTX_DAEMON_PYTHON"] = sys.executable
    os.environ["PYTHONPATH"] = str(ROOT / "packages") + os.pathsep + os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONUTF8"] = "1"

    from pipeline.daemon import is_running, start_daemon, stop_daemon
    from pipeline.lifecycle_runtime import (
        apply_idle_policy,
        register_client,
        unregister_client,
    )
    from pipeline.process_control import pid_working_set_mb

    print(f"CTX_HOME={home}")
    print(f"url={os.environ['CTX_ENGINE_URL']} debounce_s={args.debounce} warm={args.warm} watchdog={args.watchdog}")

    from pipeline.watchdog import stop_watchdog

    started = start_daemon(ROOT, host="127.0.0.1", port=int(args.port), wait_s=90.0)
    if not started.get("ok") and not is_running():
        print(f"FAIL start_daemon: {started}")
        return 1
    pid = int(started.get("pid") or 0)
    if pid <= 0:
        from pipeline.daemon import _read_lock_pid

        pid = int(_read_lock_pid() or 0)
    ws_before = pid_working_set_mb(pid)
    print(f"engine_pid={pid} ws_mb={ws_before} running={is_running()}")

    rc = 1
    try:
        if args.warm:
            from pipeline.mcp_lifecycle import warm_engine_for_mcp

            warm = warm_engine_for_mcp(ROOT, client_id="mcp:rss-probe")
            print(
                "warm_detail "
                f"ok={warm.get('ok')} embedder={warm.get('embedder_loaded')} "
                f"open={warm.get('open_repo')} prewarm={warm.get('prewarm_wait') or warm.get('prewarm')}"
            )
            if not warm.get("ok"):
                print(f"FAIL warm {warm}")
                return 1
            ws_warm = pid_working_set_mb(pid)
            print(f"ws_after_warm_mb={ws_warm}")
        else:
            register_client("mcp:rss-probe", pid=os.getpid(), kind="mcp")

        if args.watchdog:
            from pipeline.watchdog import start_watchdog, watchdog_pid_path, watchdog_status

            wd = start_watchdog()
            print(f"watchdog={wd}")
            print(f"watchdog_status={watchdog_status()}")
            try:
                _ = int((watchdog_pid_path().read_text(encoding="utf-8") or "0").strip() or 0)
            except Exception:
                pass

        unregister_client("mcp:rss-probe")
        slack = float(args.debounce) + 8.0
        deadline = time.time() + slack
        while time.time() < deadline:
            apply_idle_policy(force=True)
            if not is_running() and (pid <= 0 or not _pid_alive(pid)):
                break
            time.sleep(0.4)

        alive = _pid_alive(pid) if pid else is_running()
        running = is_running()
        print(f"after_wait running={running} pid_alive={alive} ws_mb={pid_working_set_mb(pid)}")
        if running or alive:
            print("FAIL engine process still present after disconnect debounce")
            return 1
        if args.watchdog:
            time.sleep(16.0)
            respawn = is_running()
            print(f"watchdog_after_16s running={respawn}")
            if respawn:
                print("FAIL watchdog restarted engine after disconnect (this is the 2GB pile-up)")
                return 1
        print("PASS engine process gone after last client left (RSS dropped with the process)")
        rc = 0
        return 0
    finally:
        try:
            stop_watchdog()
        except Exception as exc:  # noqa: BLE001
            print(f"stop_watchdog_error={exc}")
        if rc != 0:
            try:
                stop_daemon(reason="rss_probe")
            except Exception as exc:  # noqa: BLE001
                print(f"stop_daemon_error={exc}")


if __name__ == "__main__":
    raise SystemExit(main())

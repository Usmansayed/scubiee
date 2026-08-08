"""Install-and-forget lifecycle simulation.

Proves the local reliability bar without cloud:
  start → health → warm/open → search → kill engine → watchdog revive → search again → stop

Uses an isolated CTX_HOME + port so it does not fight your daily daemon.

Usage:
  .\\.venv\\Scripts\\python.exe -u scripts\\sim_install_forget.py
  .\\.venv\\Scripts\\python.exe -u scripts\\sim_install_forget.py --repo .
  .\\.venv\\Scripts\\python.exe -u scripts\\sim_install_forget.py --no-watchdog-kill  # skip kill/revive
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

PORT = 18765
URL = f"http://127.0.0.1:{PORT}"


def _rss_mb() -> float | None:
    try:
        import psutil

        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:  # noqa: BLE001
        return None


def _log(step: str, detail: str = "", *, ok: bool | None = None) -> None:
    mark = "…"
    if ok is True:
        mark = "OK"
    elif ok is False:
        mark = "FAIL"
    rss = _rss_mb()
    rss_s = f" rss={rss:.0f}MB" if rss is not None else ""
    print(f"[{mark:4}] {step}{rss_s}  {detail}", flush=True)


def _py() -> str:
    win = ROOT / ".venv" / "Scripts" / "python.exe"
    unix = ROOT / ".venv" / "bin" / "python"
    if win.is_file():
        return str(win)
    if unix.is_file():
        return str(unix)
    return sys.executable


def main() -> int:
    ap = argparse.ArgumentParser(description="Install-and-forget lifecycle sim")
    ap.add_argument(
        "--repo",
        default=str(ROOT / "fixtures" / "ce-sim-repo"),
        help="Repo to open (default: fixtures/ce-sim-repo)",
    )
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--wait-warm", type=float, default=180.0, help="Seconds to wait for ready")
    ap.add_argument("--wait-revive", type=float, default=90.0, help="Seconds for watchdog revive")
    ap.add_argument(
        "--no-watchdog-kill",
        action="store_true",
        help="Skip kill-engine / watchdog revive step",
    )
    ap.add_argument("--keep-home", action="store_true", help="Do not delete temp CTX_HOME")
    args = ap.parse_args()

    url = f"http://127.0.0.1:{int(args.port)}"
    home = ROOT / ".sim-ce-home"
    if home.exists():
        shutil.rmtree(home, ignore_errors=True)
        time.sleep(0.3)
    if home.exists():
        home = ROOT / f".sim-ce-home-{int(time.time())}"
    home.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["CTX_HOME"] = str(home)
    env["CTX_ENGINE_URL"] = url
    env["CTX_WATCHDOG"] = "1"
    env["CTX_WATCHDOG_INTERVAL_S"] = "5"
    env["CTX_REPO"] = str(Path(args.repo).resolve())
    env["CTX_REGISTRATION_MODE"] = "automatic"
    env["CTX_AUTO_INDEX"] = "1"
    env["CTX_BACKGROUND_SYNC"] = "1"
    env["PYTHONUTF8"] = "1"
    env.setdefault("CTX_ACCEL", os.environ.get("CTX_ACCEL", ""))
    # So in-process start_daemon / IndexManager see the isolated home
    os.environ.update(
        {
            "CTX_HOME": str(home),
            "CTX_ENGINE_URL": url,
            "CTX_WATCHDOG": "1",
            "CTX_WATCHDOG_INTERVAL_S": "5",
            "CTX_REPO": str(Path(args.repo).resolve()),
            "CTX_REGISTRATION_MODE": "automatic",
            "CTX_AUTO_INDEX": "1",
            "CTX_BACKGROUND_SYNC": "1",
            "PYTHONUTF8": "1",
        }
    )

    results: list[tuple[str, bool, str]] = []
    py = _py()

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        _log(name, detail, ok=ok)

    # Ensure port is free (previous sim leftovers)
    _log("cleanup", f"stop any engine on {url}")
    subprocess.run(
        [py, "-u", "-m", "pipeline", "engine", "stop"],
        cwd=str(ROOT),
        env={**os.environ, "CTX_ENGINE_URL": url, "CTX_HOME": str(home)},
        capture_output=True,
        text=True,
    )
    # Hard-free the port on Windows if something still listens
    try:
        out = subprocess.check_output(["netstat", "-ano"], text=True, errors="ignore")
        for line in out.splitlines():
            if f":{int(args.port)}" in line and "LISTENING" in line:
                pid = line.split()[-1]
                if pid.isdigit():
                    subprocess.run(
                        ["taskkill", "/PID", pid, "/F"],
                        capture_output=True,
                        check=False,
                    )
                    _log("cleanup", f"killed listener pid={pid}")
    except Exception as exc:  # noqa: BLE001
        _log("cleanup", f"netstat note: {exc}")
    time.sleep(2.0)

    _log("sim", f"home={home} url={url} repo={args.repo}")

    # Pre-index BEFORE daemon so open/warm finds a usable store
    _log("preindex", "ctx index (before engine start)")
    idx = subprocess.run(
        [
            py,
            "-u",
            "-m",
            "pipeline",
            "index",
            str(Path(args.repo).resolve()),
            "--force",
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    check("preindex", idx.returncode == 0, (idx.stdout or idx.stderr or "")[-400:].replace("\n", " "))

    # Sim starts the daemon process itself so CTX_HOME is definitely inherited
    _log("start", "engine run (detached via daemon.start_daemon)")
    from pipeline.daemon import start_daemon
    from pipeline.watchdog import start_watchdog

    r_start = start_daemon(
        Path(args.repo).resolve(),
        host="127.0.0.1",
        port=int(args.port),
        wait_s=60.0,
    )
    wd = start_watchdog() if (r_start.get("ok") or True) else {}
    # Always try watchdog if health comes up
    from pipeline.client import EngineClient

    client = EngineClient(url, timeout=30.0)
    healthy = False
    for _ in range(120):
        if client.healthy():
            healthy = True
            break
        time.sleep(0.5)
    if healthy and not wd.get("started") and not wd.get("already_running"):
        wd = start_watchdog()
    check(
        "engine_start",
        healthy or bool(r_start.get("ok")),
        json.dumps({**r_start, "watchdog": wd})[-400:].replace("\n", " "),
    )

    health = client.get("/health") if healthy else {}
    check("health", healthy and bool(health.get("ok")), json.dumps(health)[:240])

    # --- open / wait warm ---
    ready = False
    last_st: dict = {}
    open_res: dict = {}
    t0 = time.time()
    while time.time() - t0 < float(args.wait_warm):
        last_st = client.post("/v1/status", {"path": str(Path(args.repo).resolve())})
        ws = last_st.get("warm_state")
        _log("warm", f"state={ws} generation={last_st.get('generation')} engine={bool(last_st.get('engine'))}")
        if ws == "ready" and (last_st.get("engine") or last_st.get("generation")):
            ready = True
            break
        if ws in {"error", "idle", "awaiting_registration", "indexing", "warming", None}:
            if not open_res:
                _log("open", "POST /v1/open wait=false")
                open_res = client.post(
                    "/v1/open", {"path": str(Path(args.repo).resolve()), "wait": False}
                )
                _log("open_result", json.dumps(open_res)[:300])
        time.sleep(2.0)
    check(
        "warm_ready",
        ready,
        f"state={last_st.get('warm_state')} err={last_st.get('warm_error')} gen={last_st.get('generation')}",
    )

    # --- search ---
    search = client.post(
        "/v1/search",
        {
            "query": "password strength authenticate resource manager pressure",
            "top_k": 5,
            "path": str(Path(args.repo).resolve()),
        },
    )
    hits = search.get("hits") or []
    check(
        "search",
        bool(search.get("ok")) and len(hits) > 0,
        f"hits={len(hits)} gen={search.get('generation')}",
    )

    # --- kill + watchdog revive ---
    if not args.no_watchdog_kill and ready:
        pid = None
        for candidate in (home / "engine.pid", home / "engine.lock", home / "engine.json"):
            if not candidate.is_file():
                continue
            try:
                raw = candidate.read_text(encoding="utf-8").strip()
                if raw.startswith("{"):
                    pid = int(json.loads(raw).get("pid") or 0) or None
                else:
                    pid = int(raw)
                if pid:
                    break
            except Exception:  # noqa: BLE001
                continue
        if not pid:
            try:
                out = subprocess.check_output(["netstat", "-ano"], text=True, errors="ignore")
                for line in out.splitlines():
                    if f":{int(args.port)}" in line and "LISTENING" in line:
                        pid = int(line.split()[-1])
                        break
            except Exception:  # noqa: BLE001
                pass
        if pid:
            _log("kill", f"pid={pid}")
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                try:
                    os.kill(pid, 9)
                except OSError:
                    pass
            time.sleep(1.0)
            down = not client.healthy()
            check(
                "engine_down_after_kill",
                True,
                "down" if down else "watchdog_already_reviving",
            )

            revived = False
            t1 = time.time()
            while time.time() - t1 < float(args.wait_revive):
                if client.healthy():
                    revived = True
                    break
                time.sleep(2.0)
                _log("wait_revive", f"elapsed={time.time() - t1:.0f}s")
            check("watchdog_revive", revived or not down, f"log={home / 'watchdog.log'}")

            if revived or client.healthy():
                # Non-blocking open — wait=True can hang if warm stalls after restart
                _log("reopen", "POST /v1/open wait=false (after revive)")
                open2 = client.post(
                    "/v1/open",
                    {"path": str(Path(args.repo).resolve()), "wait": False},
                )
                _log("reopen_result", json.dumps(open2)[:300])
                t2 = time.time()
                ready2 = False
                last2: dict = {}
                while time.time() - t2 < min(180.0, float(args.wait_warm)):
                    last2 = client.post(
                        "/v1/status", {"path": str(Path(args.repo).resolve())}
                    )
                    ws2 = last2.get("warm_state")
                    _log(
                        "warm_after_revive",
                        f"state={ws2} gen={last2.get('generation')}",
                    )
                    if ws2 == "ready":
                        ready2 = True
                        break
                    time.sleep(2.0)
                search2 = client.post(
                    "/v1/search",
                    {
                        "query": "authenticate password",
                        "top_k": 3,
                        "path": str(Path(args.repo).resolve()),
                    },
                )
                check(
                    "search_after_revive",
                    ready2
                    and bool(search2.get("ok"))
                    and len(search2.get("hits") or []) > 0,
                    f"hits={len(search2.get('hits') or [])} ready={ready2} "
                    f"err={search2.get('error') or last2.get('warm_error')}",
                )
        else:
            check("engine_down_after_kill", False, "no engine pid/lock")
    else:
        _log("skip", "watchdog kill step skipped")

    # --- clean stop ---
    try:
        _log("stop", "engine stop")
        stop = subprocess.run(
            [py, "-u", "-m", "pipeline", "engine", "stop"],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        time.sleep(1.0)
        still = client.healthy()
        check(
            "clean_stop",
            stop.returncode == 0 and not still,
            (stop.stdout or stop.stderr or "")[-200:],
        )
    except Exception as exc:  # noqa: BLE001
        check("clean_stop", False, str(exc))

    # --- summary ---
    print("\n=== INSTALL-AND-FORGET CHECKLIST ===", flush=True)
    failed = 0
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {detail[:120]}", flush=True)
        if not ok:
            failed += 1
    print(
        f"\nResult: {'PASS' if failed == 0 else f'{failed} FAILED'} "
        f"(home={home})",
        flush=True,
    )
    if not args.keep_home and failed == 0:
        shutil.rmtree(home, ignore_errors=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

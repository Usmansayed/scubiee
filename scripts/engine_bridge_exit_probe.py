"""Issue 2: does the engine survive the MCP bridge that started it?

Stops the engine, connects one MCP bridge exactly like Cursor/Kiro
(``.cursor/mcp.json``, PYTHONPATH stripped), lets that bridge cold-start the
engine, records who the engine's parent is and which job objects it belongs to,
then closes the bridge the way a host does (stdin EOF, terminate) and checks
whether the engine and watchdog are still alive.

Usage (PYTHONPATH unset):
    python scripts/engine_bridge_exit_probe.py [--rounds 3] [--no-stop]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from attach_pack_race import PID, _client  # noqa: E402

BASE = "http://127.0.0.1:8765"
HOME = Path(os.environ.get("CTX_HOME") or Path.home() / ".scubiee")
SCUBIEE = str(Path.home() / ".local" / "bin" / "scubiee.exe")


def _health(timeout: float = 3.0) -> dict:
    try:
        with urllib.request.urlopen(BASE + "/health", timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__}


def _engine_pid() -> int | None:
    pid = _health(10.0).get("pid")
    return int(pid) if pid else None


def _touch() -> None:
    req = urllib.request.Request(
        BASE + "/v1/client/touch",
        data=json.dumps({"client_id": "mcp:bridge-exit-probe", "kind": "mcp", "pid": os.getpid()}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:  # noqa: BLE001
        pass


def _watchdog_pid() -> int | None:
    try:
        pid = int((HOME / "watchdog.pid").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if psutil.pid_exists(pid) else None


def _in_job(pid: int, job_name: str | None) -> bool | None:
    """IsProcessInJob for a named job (None name = any job). None = unknown."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenJobObjectW.restype = wintypes.HANDLE
    hproc = k32.OpenProcess(0x1000, False, int(pid))
    if not hproc:
        return None
    hjob = None
    try:
        if job_name:
            hjob = k32.OpenJobObjectW(0x0004, False, job_name)  # JOB_OBJECT_QUERY
            if not hjob:
                return False  # no such job
        res = wintypes.BOOL()
        if not k32.IsProcessInJob(hproc, hjob, ctypes.byref(res)):
            return None
        return bool(res.value)
    finally:
        if hjob:
            k32.CloseHandle(hjob)
        k32.CloseHandle(hproc)


def _ancestry(pid: int) -> list[str]:
    out = []
    try:
        p = psutil.Process(pid)
        for a in p.parents()[:4]:
            try:
                out.append(f"{a.pid}:{a.name()}")
            except psutil.Error:
                out.append(str(a.pid))
    except psutil.Error:
        pass
    return out


def _bridge_pids(launcher_pid: int) -> list[int]:
    pids = []
    try:
        root = psutil.Process(launcher_pid)
        for p in [root, *root.children(recursive=True)]:
            try:
                if "mcp_bridge" in " ".join(p.cmdline()):
                    pids.append(p.pid)
            except psutil.Error:
                continue
    except psutil.Error:
        pass
    return pids


def _stop_all() -> None:
    subprocess.run([SCUBIEE, "engine", "stop", str(ROOT)], capture_output=True, timeout=120)
    t0 = time.time()
    while time.time() - t0 < 30 and _health(1.0).get("ok"):
        time.sleep(0.5)


def one_round(idx: int, stop_first: bool) -> dict:
    row: dict = {"round": idx}
    if stop_first:
        _stop_all()
    row["engine_before"] = _engine_pid()
    c = _client(f"bridgeexit{idx}")
    with c:
        launcher = c._proc.pid  # noqa: SLF001
        c.call_text("gate", project_id=PID)
        t0 = time.time()
        while time.time() - t0 < 90 and not _health(10.0).get("ok"):
            time.sleep(0.5)
        _touch()
        eng = _engine_pid()
        bridges = _bridge_pids(launcher)
        row.update(
            engine=eng,
            engine_up_s=round(time.time() - t0, 1),
            bridges=bridges,
            watchdog=_watchdog_pid(),
        )
        if eng:
            row["engine_parents"] = _ancestry(eng)
            row["engine_in_any_job"] = _in_job(eng, None)
            row["engine_in_supervisor_job"] = _in_job(eng, "Local\\ContextEngineCpuJob")
            row["engine_in_bridge_job"] = any(
                _in_job(eng, f"Local\\ScubieeMcpKill-{b}") for b in bridges
            )
        wd = row["watchdog"]
        if wd:
            row["watchdog_parents"] = _ancestry(wd)
            row["watchdog_in_bridge_job"] = any(
                _in_job(wd, f"Local\\ScubieeMcpKill-{b}") for b in bridges
            )
    # Host closed the bridge (stdin EOF + terminate, like Cursor/Kiro on reload).
    # Another client stays attached (a second IDE), so idle standby must not
    # retire the engine: any death in this window is a kill.
    t_close = time.time()
    alive_all = True
    while time.time() - t_close < 12.0:
        _touch()
        if eng and not psutil.pid_exists(eng):
            alive_all = False
            break
        time.sleep(1.0)
    h = _health(10.0)
    row["engine_after_close"] = h.get("pid")
    row["engine_alive_12s"] = alive_all
    row["engine_survived"] = bool(eng) and alive_all and h.get("pid") == eng
    row["watchdog_after_close"] = _watchdog_pid()
    row["watchdog_survived"] = bool(row["watchdog"]) and row["watchdog_after_close"] == row["watchdog"]
    row["closed_at"] = time.strftime("%H:%M:%S", time.localtime(t_close))
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--no-stop", action="store_true", help="Do not stop the engine first.")
    args = ap.parse_args()
    rows = []
    for i in range(args.rounds):
        row = one_round(i, stop_first=not args.no_stop)
        rows.append(row)
        print(json.dumps(row), flush=True)
    ok = sum(1 for r in rows if r.get("engine_survived") and r.get("watchdog_survived"))
    print(f"\nSUMMARY engine+watchdog survived bridge exit {ok}/{len(rows)}")
    return 0 if ok == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())

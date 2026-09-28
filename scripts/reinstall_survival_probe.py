"""Issue 7 (+ issue 2): what does a reinstall kill, and does the session survive?

Opens one MCP session exactly like Cursor (.cursor/mcp.json -> scubiee-mcp-bridge),
calls ``gate``, records every live Scubiee process (engine, watchdog, bridge,
bridge workers, this holder), runs ``scripts/sync-uv-install.ps1``, then:

* polls the recorded PIDs every 0.25s during and after the install and prints
  which ones died, when, and their exit code where Windows still has it;
* calls ``gate`` again through the SAME stdio session (pass: it answers).

    python scripts/reinstall_survival_probe.py [--no-install] [--wait-s 60]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from attach_pack_race import PID, _client  # noqa: E402


def scubiee_procs() -> dict[int, str]:
    out: dict[int, str] = {}
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
        except Exception:  # noqa: BLE001
            continue
        low = cmd.lower()
        if not any(k in low for k in ("scubiee", "pipeline.", "engine_boot", "_boot_watchdog")):
            continue
        if "reinstall_survival_probe" in low:
            continue
        out[p.info["pid"]] = cmd[:160]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-install", action="store_true")
    ap.add_argument("--wait-s", type=float, default=45.0)
    args = ap.parse_args()
    t0 = time.time()

    def ts() -> str:
        return f"+{time.time() - t0:6.1f}s"

    with _client("reinstall") as c:
        first = c.call_text("gate", project_id=PID)
        print(f"{ts()} gate #1 ok ({len(first)} chars)", flush=True)
        before = scubiee_procs()
        handles: dict[int, psutil.Process] = {}
        for pid in before:
            try:
                handles[pid] = psutil.Process(pid)
            except psutil.Error:
                pass
        print(f"{ts()} tracking {len(before)} processes:")
        for pid, cmd in sorted(before.items()):
            print(f"    {pid:6d} {cmd}")

        died: dict[int, dict] = {}
        stop = threading.Event()

        def watch() -> None:
            while not stop.is_set():
                for pid, h in list(handles.items()):
                    if pid in died:
                        continue
                    try:
                        alive = h.is_running() and h.status() != psutil.STATUS_ZOMBIE
                    except psutil.Error:
                        alive = False
                    if not alive:
                        rc = None
                        try:
                            rc = h.wait(timeout=0)
                        except Exception:  # noqa: BLE001
                            pass
                        died[pid] = {"at": ts(), "rc": rc, "cmd": before.get(pid, "")}
                        print(f"{ts()} DIED pid={pid} rc={rc} {before.get(pid, '')[:120]}", flush=True)
                time.sleep(0.25)

        th = threading.Thread(target=watch, daemon=True)
        th.start()
        if not args.no_install:
            print(f"{ts()} running sync-uv-install.ps1 ...", flush=True)
            r = subprocess.run(
                ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / "sync-uv-install.ps1")],
                capture_output=True, text=True, timeout=600,
            )
            tail = [ln for ln in (r.stdout + r.stderr).splitlines() if "[sync]" in ln][-3:]
            print(f"{ts()} install rc={r.returncode} {' | '.join(tail)}", flush=True)
        time.sleep(args.wait_s)
        second_ok, err = False, None
        t_call = time.perf_counter()
        try:
            second = c.call_text("gate", project_id=PID)
            second_ok = bool(second)
        except Exception as exc:  # noqa: BLE001
            err = repr(exc)
        call_ms = round((time.perf_counter() - t_call) * 1000)
        stop.set()
        th.join(timeout=2)
        after = scubiee_procs()
        new = {p: c for p, c in after.items() if p not in before}
        print(f"{ts()} gate #2 same session: ok={second_ok} ms={call_ms} err={err}")
        print(f"{ts()} died={len(died)} new={len(new)}")
        for pid, cmd in sorted(new.items()):
            print(f"    new {pid:6d} {cmd}")
        print(json.dumps({"gate2_ok": second_ok, "died": died, "new": new}, default=str)[:4000])
        return 0 if second_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

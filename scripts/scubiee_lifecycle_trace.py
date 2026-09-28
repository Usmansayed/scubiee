#!/usr/bin/env python3
"""Continuous Scubiee / MCP / engine process-tree tracer.

Writes JSONL snapshots so we can reconstruct what happened across Cursor
reloads, closes, and engine restarts.

Usage:
  python scripts/scubiee_lifecycle_trace.py
  python scripts/scubiee_lifecycle_trace.py --interval 2 --hours 6

Logs default to %%USERPROFILE%%/.scubiee/lifecycle_trace/
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


INTERESTING = (
    "scubiee",
    "pipeline engine",
    "pipeline.mcp",
    "mcp_locate",
    "mcp_bridge",
    "uv\\tools\\scubiee",
    "uv/tools/scubiee",
)


def _home() -> Path:
    return Path(os.environ.get("CTX_HOME") or (Path.home() / ".scubiee"))


def _out_dir() -> Path:
    d = _home() / "lifecycle_trace"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _read_text(path: Path, limit: int = 4000) -> str | None:
    try:
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return None


def _read_json(path: Path) -> object | None:
    raw = _read_text(path)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw[:500]}


def _port_listeners(port: int = 8765) -> list[dict]:
    rows: list[dict] = []
    try:
        import subprocess

        # Prefer PowerShell NetTCPConnection on Windows for owning PID.
        if os.name == "nt":
            ps = (
                f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue | "
                "Select-Object OwningProcess,State,RemoteAddress | ConvertTo-Json -Compress"
            )
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    ps,
                ],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            raw = (completed.stdout or "").strip()
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict):
                    data = [data]
                for item in data or []:
                    rows.append(
                        {
                            "pid": int(item.get("OwningProcess") or 0),
                            "state": str(item.get("State") or ""),
                            "remote": str(item.get("RemoteAddress") or ""),
                        }
                    )
                return rows
    except Exception as exc:  # noqa: BLE001
        rows.append({"error": str(exc)})
    # Fallback: can we connect?
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            rows.append({"probe": "connect_ok"})
    except OSError:
        rows.append({"probe": "connect_fail"})
    return rows


def _health(url: str = "http://127.0.0.1:8765/health") -> dict:
    try:
        import urllib.request

        with urllib.request.urlopen(url, timeout=1.5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            data = json.loads(body)
            if isinstance(data, dict):
                return {
                    "ok": bool(data.get("ok")),
                    "version": data.get("version"),
                    "warm_state": data.get("warm_state"),
                    "generation": data.get("generation"),
                    "repo": data.get("repo"),
                }
            return {"ok": False, "raw": str(data)[:200]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:200]}


def _win_processes() -> list[dict]:
    import subprocess

    # One CIM query — filter in Python for reliability.
    ps = (
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,Name,CommandLine,CreationDate | "
        "ConvertTo-Json -Compress -Depth 3"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    raw = (completed.stdout or "").strip()
    if not raw:
        return []
    data = json.loads(raw)
    if isinstance(data, dict):
        data = [data]
    out: list[dict] = []
    for item in data or []:
        cmd = str(item.get("CommandLine") or "")
        name = str(item.get("Name") or "")
        blob = f"{name} {cmd}".lower()
        if not any(tok.lower() in blob for tok in INTERESTING):
            continue
        out.append(
            {
                "pid": int(item.get("ProcessId") or 0),
                "ppid": int(item.get("ParentProcessId") or 0),
                "name": name,
                "cmd": cmd[:240],
                "created": str(item.get("CreationDate") or ""),
            }
        )
    out.sort(key=lambda r: r["pid"])
    return out


def _role(cmd: str, name: str) -> str:
    c = f"{name} {cmd}".lower()
    if "mcp-bridge" in c or "mcp_bridge" in c:
        return "mcp_bridge"
    if "scubiee-mcp" in c or "pipeline.mcp" in c or "mcp_locate" in c:
        return "mcp_worker"
    if "engine watchdog" in c or "engine supervisor" in c:
        return "watchdog"
    if "engine run" in c:
        return "engine"
    if "scubiee" in c:
        return "scubiee_other"
    return "other"


def _groups(procs: list[dict]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {
        "mcp_bridge": [],
        "mcp_worker": [],
        "watchdog": [],
        "engine": [],
        "other": [],
    }
    for p in procs:
        role = _role(p.get("cmd") or "", p.get("name") or "")
        key = role if role in groups else "other"
        groups[key].append(int(p["pid"]))
    return groups


def _ancestry(procs: list[dict], pid: int, limit: int = 8) -> list[int]:
    by_pid = {int(p["pid"]): int(p["ppid"]) for p in procs}
    chain = [pid]
    cur = pid
    for _ in range(limit):
        parent = by_pid.get(cur)
        if not parent or parent in chain or parent <= 0:
            break
        chain.append(parent)
        cur = parent
    return chain


def snapshot() -> dict:
    home = _home()
    procs = _win_processes() if os.name == "nt" else []
    groups = _groups(procs)
    engine_pids = groups.get("engine") or []
    listener = None
    ports = _port_listeners(8765)
    for row in ports:
        if str(row.get("state") or "").lower() == "listen" and row.get("pid"):
            listener = int(row["pid"])
            break
    engine_parent_chains = {
        str(pid): _ancestry(procs, pid) for pid in engine_pids
    }
    watchdog_parent_chains = {
        str(pid): _ancestry(procs, pid) for pid in (groups.get("watchdog") or [])
    }
    mcp_parent_chains = {
        str(pid): _ancestry(procs, pid) for pid in (groups.get("mcp_worker") or [])
    }
    # Cross-links: is engine/watchdog under an MCP pid?
    mcp_set = set(groups.get("mcp_worker") or []) | set(groups.get("mcp_bridge") or [])
    ownership = {
        "engine_under_mcp": any(
            any(p in mcp_set for p in chain[1:]) for chain in engine_parent_chains.values()
        ),
        "watchdog_under_mcp": any(
            any(p in mcp_set for p in chain[1:]) for chain in watchdog_parent_chains.values()
        ),
        "listener_pid": listener,
        "lock_pid": None,
    }
    lock = _read_json(home / "engine.lock")
    if isinstance(lock, dict) and lock.get("pid"):
        try:
            ownership["lock_pid"] = int(lock["pid"])
        except (TypeError, ValueError):
            pass
    ownership["lock_eq_listener"] = (
        ownership["lock_pid"] is not None
        and listener is not None
        and ownership["lock_pid"] == listener
    )
    return {
        "ts": _now_iso(),
        "mono": time.monotonic(),
        "health": _health(),
        "ports_8765": ports,
        "groups": groups,
        "ownership": ownership,
        "engine_parent_chains": engine_parent_chains,
        "watchdog_parent_chains": watchdog_parent_chains,
        "mcp_parent_chains": mcp_parent_chains,
        "procs": procs,
        "files": {
            "engine.lock": lock,
            "engine.pid": _read_text(home / "engine.pid", 64),
            "engine.json": _read_json(home / "engine.json"),
            "active_clients": _read_json(home / "active_clients.json"),
            "lifecycle_policy": _read_json(home / "lifecycle_policy.json"),
            "watchdog.pid": _read_text(home / "watchdog.pid", 64),
        },
    }


def _fingerprint(snap: dict) -> str:
    """Compact identity for change detection."""
    parts = [
        str(sorted((snap.get("groups") or {}).items())),
        str((snap.get("ownership") or {})),
        str((snap.get("health") or {}).get("warm_state")),
        str((snap.get("health") or {}).get("ok")),
        str((snap.get("files") or {}).get("active_clients")),
        str((snap.get("files") or {}).get("engine.pid")),
    ]
    return "|".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--interval", type=float, default=2.0, help="Seconds between samples")
    ap.add_argument("--hours", type=float, default=8.0, help="Stop after N hours (0=forever)")
    ap.add_argument(
        "--out",
        type=str,
        default="",
        help="JSONL output path (default: ~/.scubiee/lifecycle_trace/trace-YYYYMMDD-HHMMSS.jsonl)",
    )
    args = ap.parse_args()
    out_dir = _out_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = Path(args.out) if args.out else out_dir / f"trace-{stamp}.jsonl"
    pid_path = out_dir / "tracer.pid"
    latest_path = out_dir / "latest.json"
    pid_path.write_text(str(os.getpid()), encoding="utf-8")
    (out_dir / "active_log.txt").write_text(str(out_path), encoding="utf-8")

    print(f"[lifecycle_trace] pid={os.getpid()} out={out_path}", flush=True)
    print(f"[lifecycle_trace] interval={args.interval}s hours={args.hours}", flush=True)

    deadline = None if args.hours <= 0 else time.time() + args.hours * 3600
    last_fp = ""
    n = 0
    try:
        while True:
            if deadline is not None and time.time() >= deadline:
                print("[lifecycle_trace] hours elapsed — exiting", flush=True)
                break
            try:
                snap = snapshot()
            except Exception as exc:  # noqa: BLE001
                snap = {"ts": _now_iso(), "error": str(exc)}
            fp = _fingerprint(snap) if "error" not in snap else f"err:{snap.get('error')}"
            changed = fp != last_fp
            snap["seq"] = n
            snap["changed"] = changed
            with out_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(snap, ensure_ascii=False) + "\n")
            latest_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            if changed or n == 0:
                own = snap.get("ownership") or {}
                groups = snap.get("groups") or {}
                health = snap.get("health") or {}
                print(
                    f"[{snap.get('ts')}] seq={n} changed={changed} "
                    f"health={health.get('ok')}/{health.get('warm_state')} "
                    f"engine={groups.get('engine')} wd={groups.get('watchdog')} "
                    f"mcp={groups.get('mcp_worker')} "
                    f"eng_under_mcp={own.get('engine_under_mcp')} "
                    f"wd_under_mcp={own.get('watchdog_under_mcp')} "
                    f"lock={own.get('lock_pid')} listen={own.get('listener_pid')}",
                    flush=True,
                )
            last_fp = fp
            n += 1
            time.sleep(max(0.5, float(args.interval)))
    except KeyboardInterrupt:
        print("[lifecycle_trace] interrupted", flush=True)
    finally:
        try:
            if pid_path.is_file() and pid_path.read_text(encoding="utf-8").strip() == str(
                os.getpid()
            ):
                pid_path.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

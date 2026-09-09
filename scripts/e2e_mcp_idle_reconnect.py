#!/usr/bin/env python3
"""End-to-end check of the MCP idle-shutdown and reconnect-adoption behaviour.

Drives the real stdio bridge the way an IDE does:

1. connect a client, call a tool  -> engine warm, client registered
2. close the client               -> disconnect grace window starts
3. poll until the engine stops    -> should land near CTX_ENGINE_IDLE_S (15s)
4. reconnect and call a tool      -> engine comes back and serves
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE_URL = os.environ.get("CTX_ENGINE_URL", "http://127.0.0.1:8765")
IDLE_S = float(os.environ.get("CTX_ENGINE_IDLE_S", "15"))
SHUTDOWN_BUDGET_S = float(os.environ.get("SHUTDOWN_BUDGET_S", IDLE_S * 4))

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))
    if not ok:
        failures.append(label)
    return ok


def engine_up() -> bool:
    try:
        with urllib.request.urlopen(f"{ENGINE_URL}/health", timeout=1.5) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def engine_process_alive() -> bool:
    """Passive liveness check — must not touch the engine's HTTP surface.

    Polling /health while waiting for an idle stop would itself register as
    front-end activity and hold the engine open.
    """
    import psutil

    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if "pipeline engine run" in cmdline:
            return True
    return False


class Bridge:
    """Minimal MCP stdio client against the installed bridge."""

    def __init__(self) -> None:
        exe = shutil.which("scubiee-mcp-bridge") or shutil.which("scubiee-mcp")
        if not exe:
            raise SystemExit("scubiee-mcp-bridge not on PATH")
        env = os.environ.copy()
        env.setdefault("CTX_REPO", str(REPO))
        env.setdefault("PYTHONUTF8", "1")
        self.proc = subprocess.Popen(
            [exe],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", bufsize=1, cwd=str(REPO), env=env,
        )
        self._id = 0

    def call(self, method: str, params: dict | None = None, timeout: float = 90.0):
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                return None
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("id") == self._id:
                return data
        return None

    def handshake(self) -> bool:
        r = self.call("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "e2e-idle-probe", "version": "1.0"},
        })
        if r is None:
            return False
        self.proc.stdin.write(json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.proc.stdin.flush()
        return True

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def session(label: str) -> bool:
    print(f"\n  -- {label} --")
    bridge = Bridge()
    try:
        if not check(f"{label}: handshake", bridge.handshake()):
            return False
        tools = bridge.call("tools/list")
        names = [t.get("name") for t in ((tools or {}).get("result", {}).get("tools") or [])]
        check(f"{label}: tools listed", len(names) >= 3, f"{len(names)} tools")
        res = bridge.call("tools/call", {"name": "status", "arguments": {}})
        ok = bool(res and not res.get("error"))
        check(f"{label}: status tool responds", ok)
        check(f"{label}: engine warm during session", engine_up())
        return ok
    finally:
        bridge.close()


def main() -> int:
    print("=" * 60)
    print(f"  MCP idle shutdown + reconnect  (idle window {IDLE_S}s)")
    print("=" * 60)

    session("session 1")

    print("\n  -- client closed: waiting for idle shutdown --")
    t0 = time.time()
    stopped_at = None
    while time.time() - t0 < SHUTDOWN_BUDGET_S:
        if not engine_process_alive():
            stopped_at = time.time() - t0
            break
        time.sleep(1.0)

    if stopped_at is None:
        check(f"engine stops within {SHUTDOWN_BUDGET_S:.0f}s of disconnect", False,
              "still up")
    else:
        check(f"engine stopped after disconnect", True, f"{stopped_at:.1f}s")
        check("shutdown not premature (>= idle window)", stopped_at >= IDLE_S - 2.0,
              f"{stopped_at:.1f}s vs {IDLE_S}s")

    session("session 2 (reconnect)")

    print("\n" + "=" * 60)
    if failures:
        print(f"  {len(failures)} FAILED: {', '.join(failures)}")
        return 1
    print("  ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

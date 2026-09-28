#!/usr/bin/env python3
"""Production smoke: uv tool install + upgrade --check + bridge entrypoints."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], *, timeout: float = 180.0) -> subprocess.CompletedProcess:
    print(f"\n>>> {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def main() -> int:
    failures: list[str] = []

    import os

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "packages")

    r = subprocess.run(
        [sys.executable, "-c", "from pipeline.mcp_bridge import main; from pipeline.mcp_hot_reload import nudge_mcp_hot_reload; print('imports_ok')"],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        failures.append(f"import check: {r.stderr}")
    else:
        print("PASS imports:", r.stdout.strip())

    # 2. uv tool install (local build)
    if not shutil.which("uv"):
        print("SKIP uv tool install — uv not on PATH")
    else:
        r = run([shutil.which("uv") or "uv", "tool", "install", "--force", "--reinstall", str(ROOT)], timeout=300)
        if r.returncode != 0:
            failures.append(f"uv tool install failed: {r.stderr[-2000:]}")
        else:
            print("PASS uv tool install")

        for exe in ("scubiee", "scubiee-mcp", "scubiee-mcp-bridge"):
            found = shutil.which(exe)
            if not found:
                failures.append(f"missing on PATH after install: {exe}")
            else:
                print(f"PASS which {exe} -> {found}")

        # 3. upgrade --check
        scubiee = shutil.which("scubiee")
        if scubiee:
            r = run([scubiee, "upgrade", "--check"], timeout=120)
            out = (r.stdout or "") + (r.stderr or "")
            print(out[-1500:])
            if r.returncode != 0:
                failures.append(f"scubiee upgrade --check exit {r.returncode}")
            else:
                print("PASS scubiee upgrade --check")

            # 4. refresh path without MCP rebind (daemon + migrate only)
            r = run([scubiee, "upgrade", "--no-connect"], timeout=180)
            out = (r.stdout or "") + (r.stderr or "")
            print(out[-2000:])
            if r.returncode != 0:
                failures.append(f"scubiee upgrade --no-connect exit {r.returncode}")
            else:
                print("PASS scubiee upgrade --no-connect (exit 0)")

    if failures:
        print("\n=== FAILURES ===")
        for f in failures:
            print("-", f)
        return 1

    print("\n=== ALL PRODUCTION SMOKE CHECKS PASSED ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

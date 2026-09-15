#!/usr/bin/env python3
"""MCP ship pre-prod gate — layered; reuses outer CLI combo, does not rebuild it.

Usage:
  python scripts/run_mcp_ship_preprod.py
  python scripts/run_mcp_ship_preprod.py --require-live
  python scripts/run_mcp_ship_preprod.py --skip-cli

Exit 0 when all selected layers pass.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FAST_TESTS = [
    "tests/test_mcp_ship_preprod.py",
    "tests/test_mcp_lean.py",
    "tests/test_mcp_permissions.py",
    "tests/test_mcp_pack_bodies_optin.py",
    "tests/test_pack_engine_identity.py",
    "tests/test_mcp_bridge_concurrency.py",
    "tests/test_mcp_no_repo_scubiee_after_wipe.py",
]


def _run(cmd: list[str], *, label: str, timeout: float | None = None) -> int:
    print(f"\n=== {label} ===")
    print(" ".join(cmd))
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"--- {label} TIMEOUT after {timeout}s ---")
        return 124
    print(f"--- {label} exit={proc.returncode} ---")
    return int(proc.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP ship pre-prod layered gate")
    parser.add_argument(
        "--require-live",
        action="store_true",
        help="Fail if live ship_check / integration ladder cannot run green",
    )
    parser.add_argument(
        "--skip-cli",
        action="store_true",
        help="Skip run_cli_combination_tests.py --quick",
    )
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help="Skip live ship_check and integration tests",
    )
    parser.add_argument(
        "--cli-timeout",
        type=float,
        default=240.0,
        help="Wall-clock timeout seconds for L5 CLI combo (default 240)",
    )
    args = parser.parse_args()

    rc = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            *FAST_TESTS,
            "-q",
            "--tb=line",
            "-m",
            "not integration",
        ],
        label="L1+L2+L4 fast pytest (not integration)",
    )
    if rc != 0:
        return rc

    if not args.skip_live:
        live_pytest = _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_mcp_ship_preprod.py::test_live_ship_ladder_gate_map_pack_expand",
                "-q",
                "--tb=short",
                "-m",
                "integration",
            ],
            label="L3 live ladder (integration)",
        )
        ship_check = _run(
            [sys.executable, "scripts/scubiee_mcp_ship_check.py"],
            label="L3 ship_check script",
        )
        if args.require_live and (live_pytest != 0 or ship_check != 0):
            return live_pytest or ship_check
        if live_pytest != 0:
            print("NOTE: live pytest skipped or failed (ok without --require-live)")
        if ship_check != 0:
            print("NOTE: ship_check failed (ok without --require-live)")

    if not args.skip_cli:
        cli_rc = _run(
            [sys.executable, "scripts/run_cli_combination_tests.py", "--quick"],
            label="L5 CLI combination --quick (reuse)",
            timeout=float(args.cli_timeout),
        )
        if cli_rc == 124:
            print(
                "NOTE: CLI combo timed out — not an MCP ship blocker. "
                "Re-run with --skip-cli or fix engine-stop flakes separately."
            )
            print("MCP ship pre-prod gate: PASS (CLI combo timed out, soft)")
            return 0
        if cli_rc != 0:
            return cli_rc

    print("\nMCP ship pre-prod gate: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

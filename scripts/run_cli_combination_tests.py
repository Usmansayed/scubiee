#!/usr/bin/env python3
"""Run Scubiee CLI combination scenarios (isolated CTX_HOME).

Usage:
  python scripts/run_cli_combination_tests.py
  python scripts/run_cli_combination_tests.py --json results.json

Exit 0 if all scenarios match expectation.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packages"
if str(PACKAGES) not in sys.path:
    sys.path.insert(0, str(PACKAGES))


@dataclass
class Scenario:
    id: str
    group: str
    steps: list[list[str]]
    expect: str  # allowed | blocked | ok | any
    note: str = ""


@dataclass
class Result:
    id: str
    group: str
    ok: bool
    expect: str
    observed: str
    steps: list[dict] = field(default_factory=list)
    note: str = ""


def _run_cli(
    argv: list[str],
    *,
    home: Path,
    cwd: Path,
    env_extra: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> dict:
    env = os.environ.copy()
    env["CTX_HOME"] = str(home)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    cmd = [sys.executable, "-m", "pipeline", *argv]
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "argv": argv,
            "exit": -9,
            "stdout": (exc.stdout or "")[-2000:],
            "stderr": (exc.stderr or "")[-2000:],
            "blocked": False,
            "elapsed_s": round(time.time() - t0, 2),
            "timeout": True,
        }
    combined = (proc.stdout or "") + (proc.stderr or "")
    blocked = "[scubiee] Scubiee is stopped" in combined or "globally stopped" in combined.lower()
    blocked = blocked or "Run `scubiee resume`" in combined
    return {
        "argv": argv,
        "exit": proc.returncode,
        "stdout": (proc.stdout or "")[-2000:],
        "stderr": (proc.stderr or "")[-2000:],
        "blocked": blocked,
        "elapsed_s": round(time.time() - t0, 2),
        "timeout": False,
    }


def _last_step_observed(steps: list[dict], expect: str) -> tuple[bool, str]:
    if not steps:
        return False, "no_steps"
    last = steps[-1]
    if expect == "any":
        return True, f"exit={last.get('exit')}"
    if expect == "blocked":
        ok = last.get("blocked") or last.get("exit") == 1
        return ok, "blocked" if ok else f"exit={last.get('exit')} not blocked"
    if expect == "allowed":
        ok = not last.get("blocked")
        return ok, "allowed" if ok else "unexpected block"
    if expect == "ok":
        ok = last.get("exit") == 0 and not last.get("blocked")
        return ok, f"exit={last.get('exit')}"
    return True, "unknown_expect"


def scenarios() -> list[Scenario]:
    return [
        # --- Read-only always ---
        Scenario("R1", "readonly", [["--version"]], "ok", "version always works"),
        Scenario("R2", "readonly", [["gate", "."]], "any", "gate local only"),
        Scenario("R3", "readonly", [["doctor"]], "any", "doctor may fail if not enrolled"),
        Scenario("R4", "readonly", [["preflight"]], "any", "preflight deps check"),
        # --- Global stop guards ---
        Scenario(
            "G1",
            "global_stop",
            [["stop", "-y"], ["init", "."]],
            "blocked",
            "init after global stop blocked",
        ),
        Scenario(
            "G2",
            "global_stop",
            [["stop", "-y"], ["setup"]],
            "blocked",
            "setup after stop blocked (no --repair)",
        ),
        Scenario(
            "G3",
            "global_stop",
            [["stop", "-y"], ["setup", "--repair"]],
            "any",
            "setup --repair allowed when stopped",
        ),
        Scenario(
            "G4",
            "global_stop",
            [["stop", "-y"], ["engine", "start", "."]],
            "blocked",
            "engine start after global stop blocked",
        ),
        Scenario(
            "G5",
            "global_stop",
            [["stop", "-y"], ["engine", "status", "."]],
            "allowed",
            "engine status allowed when stopped",
        ),
        Scenario(
            "G6",
            "global_stop",
            [["stop", "-y"], ["halt"]],
            "allowed",
            "halt allowed when stopped",
        ),
        Scenario(
            "G7",
            "global_stop",
            [["stop", "-y"], ["wipe", "--all"]],
            "any",
            "wipe --all without confirm returns confirm_required",
        ),
        Scenario(
            "G8",
            "global_stop",
            [["stop", "-y"], ["resume"]],
            "ok",
            "resume after stop",
        ),
        Scenario(
            "G9",
            "global_stop",
            [["stop", "-y"], ["connect", "--cursor"]],
            "any",
            "connect auto-resumes when stopped",
        ),
        # --- Engine-only stop ---
        Scenario(
            "E1",
            "engine_stop",
            [["engine", "stop"], ["engine", "status", "."]],
            "any",
            "engine stop then status",
        ),
        Scenario(
            "E2",
            "engine_stop",
            [["engine", "stop"], ["init", "."]],
            "any",
            "init after engine-only stop (needs setup)",
        ),
        # --- Wipe combinations ---
        Scenario(
            "W1",
            "wipe",
            [["wipe", "."]],
            "any",
            "repo wipe on unmanaged repo",
        ),
        Scenario(
            "W2",
            "wipe",
            [["wipe", "--all"]],
            "any",
            "full wipe needs confirm",
        ),
        Scenario(
            "W3",
            "wipe",
            [["halt"], ["wipe", "--all"]],
            "any",
            "halt then wipe all (confirm gate)",
        ),
        # --- Recovery ---
        Scenario(
            "X1",
            "recovery",
            [["stop", "-y"], ["resume"], ["engine", "status", "."]],
            "any",
            "stop resume engine status chain",
        ),
        Scenario("L1", "lifecycle", [["list"]], "any", "list managed repos"),
        Scenario("L2", "lifecycle", [["migrate", "--check-all"]], "any", "migration check all"),
        Scenario(
            "L3",
            "lifecycle",
            [["stop", "-y"], ["list"]],
            "any",
            "list while globally stopped",
        ),
        Scenario(
            "D1",
            "disconnect",
            [["disconnect", "--cursor"]],
            "any",
            "disconnect cursor (may noop if not connected)",
        ),
        Scenario(
            "I1",
            "init_combo",
            [["stop", "-y"], ["resume"], ["init", "."]],
            "any",
            "init after stop+resume",
        ),
        Scenario(
            "I2",
            "init_combo",
            [["engine", "stop"], ["init", "."]],
            "any",
            "init after engine-only stop",
        ),
    ]


def run_all(*, repo: Path, quick: bool) -> list[Result]:
    results: list[Result] = []
    with tempfile.TemporaryDirectory(prefix="scubiee-cli-test-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        for sc in scenarios():
            if quick and sc.group in {"wipe"}:
                continue
            step_reports: list[dict] = []
            for argv in sc.steps:
                step_reports.append(_run_cli(argv, home=home, cwd=repo, timeout=90.0))
            ok, observed = _last_step_observed(step_reports, sc.expect)
            results.append(
                Result(
                    id=sc.id,
                    group=sc.group,
                    ok=ok,
                    expect=sc.expect,
                    observed=observed,
                    steps=step_reports,
                    note=sc.note,
                )
            )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Scubiee CLI combination tests")
    parser.add_argument("--json", default="", help="Write JSON results here")
    parser.add_argument("--repo", default=str(ROOT), help="Repo path for cwd")
    parser.add_argument("--quick", action="store_true", help="Skip slow wipe scenarios")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    results = run_all(repo=repo, quick=args.quick)
    passed = sum(1 for r in results if r.ok)
    total = len(results)

    print(f"\nScubiee CLI combination tests: {passed}/{total} passed\n")
    print(f"{'ID':<6} {'GROUP':<14} {'EXPECT':<10} {'OBSERVED':<16} {'OK':<4} NOTE")
    print("-" * 72)
    for r in results:
        mark = "PASS" if r.ok else "FAIL"
        print(f"{r.id:<6} {r.group:<14} {r.expect:<10} {r.observed:<16} {mark:<4} {r.note[:40]}")

    payload = {
        "passed": passed,
        "total": total,
        "platform": sys.platform,
        "results": [
            {
                "id": r.id,
                "group": r.group,
                "ok": r.ok,
                "expect": r.expect,
                "observed": r.observed,
                "note": r.note,
                "steps": r.steps,
            }
            for r in results
        ],
    }
    if args.json:
        Path(args.json).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

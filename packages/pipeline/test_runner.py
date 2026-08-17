"""Tiered, repeatable Context Engine verification runner.

Routine agents run ``quick`` or ``core``.  Hardware, installation, and external
client exercises remain explicit opt-in tiers and are reported as skipped when
their prerequisites are absent.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TestPlan:
    tier: str
    pytest_targets: tuple[str, ...]
    opt_in: bool = False
    requires_network: bool = False
    requires_external_client: bool = False


_QUICK = (
    "tests/test_source_integrity.py",
    "tests/test_preflight.py",
    "tests/test_test_runner.py",
    "tests/test_artifact_guard.py",
    "tests/test_dirty_ledger.py",
    "tests/test_session_store.py",
    "tests/test_daemon_guardrails.py",
    "tests/test_doctor_certify.py",
)
_CORE_EXTRA = (
    "tests/test_project_id.py",
    "tests/test_registration_modes.py",
    "tests/test_resources.py",
    "tests/test_live_reindexing.py",
    "tests/test_watchdog.py",
)
_CERTIFICATION = (
    "tests/test_repo_lifecycle.py",
    "tests/test_multi_repo_runtime.py",
    "tests/test_sync_status_canaries.py",
    "tests/test_storage_policy.py",
    "tests/test_watcher_recovery.py",
    "tests/test_production_scenarios.py",
    "tests/test_artifact_guard.py",
    "tests/test_daemon_guardrails.py",
)
_FAULT = _CERTIFICATION
_INSTALL = ("tests/test_opencode_mcp_preflight.py",)
_CLIENTS = (
    "tests/test_sdk_mcp_smoke.py",
    "tests/test_sdk_mcp_dev_trial.py",
    "tests/test_codex_trial_harness.py",
    "tests/test_kiro_trial_harness.py",
)


def _unique_targets(*groups: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(target for group in groups for target in group))


def build_test_plan(tier: str, *, root: Path) -> TestPlan:
    """Return the exact test targets for a named certification tier."""
    del root  # retained to make a future workspace-specific policy explicit
    normalized = tier.strip().lower()
    if normalized == "quick":
        return TestPlan(tier="quick", pytest_targets=_QUICK)
    if normalized == "core":
        return TestPlan(
            tier="core",
            pytest_targets=_unique_targets(_QUICK, _CORE_EXTRA, _CERTIFICATION),
        )
    if normalized == "fault":
        return TestPlan(tier="fault", pytest_targets=_FAULT, opt_in=True)
    if normalized == "install":
        return TestPlan(
            tier="install",
            pytest_targets=_INSTALL,
            opt_in=True,
            requires_network=True,
        )
    if normalized == "clients":
        return TestPlan(
            tier="clients",
            pytest_targets=_CLIENTS,
            opt_in=True,
            requires_external_client=True,
        )
    if normalized == "all":
        return TestPlan(
            tier="all",
            pytest_targets=_unique_targets(
                _QUICK, _CORE_EXTRA, _CERTIFICATION, _INSTALL, _CLIENTS
            ),
            opt_in=True,
            requires_network=True,
            requires_external_client=True,
        )
    raise ValueError(
        f"unknown test tier {tier!r}; choose quick, core, fault, install, clients, or all"
    )


def run_plan(
    plan: TestPlan,
    *,
    root: Path,
    external_client_available: bool | None = None,
) -> dict[str, Any]:
    """Run a plan and return a machine-readable report."""
    if plan.requires_external_client and not external_client_available:
        return {
            "ok": True,
            "status": "skipped",
            "reason": "external_client_unavailable",
            "plan": asdict(plan),
        }
    started = time.perf_counter()
    env = dict(os.environ)
    packages = str(root / "packages")
    env["PYTHONPATH"] = packages + os.pathsep + env.get("PYTHONPATH", "")
    command = [sys.executable, "-m", "pytest", *plan.pytest_targets, "-q", "--tb=short"]
    proc = subprocess.run(
        command,
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "status": "passed" if proc.returncode == 0 else "failed",
        "returncode": proc.returncode,
        "command": command,
        "plan": asdict(plan),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "ms": round((time.perf_counter() - started) * 1000, 1),
    }

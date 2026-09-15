#!/usr/bin/env python3
"""Curated Scubiee e2e suite runner — reuses existing pytest modules + records JSON.

Usage:
  .venv/Scripts/python.exe scripts/run_scubiee_e2e_suite.py
  .venv/Scripts/python.exe scripts/run_scubiee_e2e_suite.py --quick
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Curated batteries — expand coverage without re-running the entire 194-file suite.
SUITES: dict[str, list[str]] = {
    "wrapper_lifecycle": [
        "tests/test_lifecycle_runtime.py",
        "tests/test_lifecycle_disconnect_unload.py",
        "tests/test_runtime_controller.py",
        "tests/test_mcp_bridge.py",
        "tests/test_e2e_system_matrix.py",
    ],
    "resources": [
        "tests/test_memory_governor.py",
        "tests/test_memory_budget.py",
        "tests/test_runtime_publish.py",
    ],
    "sync": [
        "tests/test_live_reindexing.py",
        "tests/test_watcher_recovery.py",
        "tests/test_freshness.py",
        "tests/test_sync_status_canaries.py",
    ],
    "tools_locate": [
        "tests/test_incremental_context_ladder.py",
        "tests/test_expand_after_pack.py",
        "tests/test_attach_warm_pipeline.py",
        "tests/test_locate_worker_prewarm.py",
        "tests/test_reliability_master_plan.py",
    ],
}

QUICK = [
    "tests/test_e2e_system_matrix.py",
    "tests/test_mcp_bridge.py",
    "tests/test_attach_warm_pipeline.py",
    "tests/test_runtime_publish.py",
    "tests/test_reliability_master_plan.py",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs" / "superpowers" / "plans" / "e2e-suite-results.json",
    )
    args = ap.parse_args()

    if args.quick:
        targets = QUICK
        label = "quick"
    else:
        targets = []
        for files in SUITES.values():
            targets.extend(files)
        # de-dupe preserve order
        seen: set[str] = set()
        uniq: list[str] = []
        for t in targets:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        targets = uniq
        label = "full_curated"

    # Prefer the interpreter that invoked this script (uv-tool Python has ORT/FastEmbed).
    # Override with CTX_E2E_PYTHON; set CTX_E2E_USE_VENV=1 to force repo .venv.
    import os

    if (os.environ.get("CTX_E2E_USE_VENV") or "").strip().lower() in {"1", "true", "yes"}:
        py = ROOT / ".venv" / "Scripts" / "python.exe"
        if not py.is_file():
            py = ROOT / ".venv" / "bin" / "python"
        if not py.is_file():
            py = Path(sys.executable)
    else:
        override = (os.environ.get("CTX_E2E_PYTHON") or "").strip()
        py = Path(override) if override else Path(sys.executable)

    report: dict = {
        "label": label,
        "started_at": time.time(),
        "targets": targets,
        "suites": {k: v for k, v in SUITES.items()} if label != "quick" else {"quick": QUICK},
        "runs": [],
    }
    overall_ok = True
    t0 = time.perf_counter()
    cmd = [
        str(py),
        "-m",
        "pytest",
        *targets,
        "-q",
        "--tb=line",
    ]
    print("[e2e] ", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    elapsed = round((time.perf_counter() - t0) * 1000, 1)
    ok = proc.returncode == 0
    overall_ok = ok
    tail = (proc.stdout or "")[-4000:] + "\n" + (proc.stderr or "")[-2000:]
    report["runs"].append(
        {
            "ok": ok,
            "returncode": proc.returncode,
            "elapsed_ms": elapsed,
            "tail": tail[-6000:],
        }
    )
    report["ok"] = overall_ok
    report["elapsed_ms"] = elapsed
    report["finished_at"] = time.time()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(tail[-2000:], flush=True)
    print(f"[e2e] ok={ok} elapsed_ms={elapsed} report={args.out}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

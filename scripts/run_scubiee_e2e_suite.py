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
# Only list files that exist in-tree; ``main`` also skips missing paths so a
# stale entry cannot hard-fail the whole Gate B runner (seen on macOS 0.3.89).
SUITES: dict[str, list[str]] = {
    "wrapper_lifecycle": [
        "tests/test_lifecycle_runtime.py",
        "tests/test_lifecycle_disconnect_unload.py",
        "tests/test_lifecycle_just_works.py",
        "tests/test_mcp_bridge.py",
        "tests/test_mcp_lazy_warm.py",
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
        "tests/test_pack_seed_heat_thin.py",
        "tests/test_warm_path_speedups.py",
        "tests/test_mcp_ensure_coalesce.py",
        "tests/test_idle_no_clients_standby.py",
    ],
}

QUICK = [
    "tests/test_mcp_bridge.py",
    "tests/test_mcp_lazy_warm.py",
    "tests/test_runtime_publish.py",
    "tests/test_warm_path_speedups.py",
    "tests/test_lifecycle_just_works.py",
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
        requested = list(QUICK)
        label = "quick"
    else:
        requested = []
        for files in SUITES.values():
            requested.extend(files)
        # de-dupe preserve order
        seen: set[str] = set()
        uniq: list[str] = []
        for t in requested:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        requested = uniq
        label = "full_curated"

    missing = [t for t in requested if not (ROOT / t).is_file()]
    targets = [t for t in requested if (ROOT / t).is_file()]
    if not targets:
        print("[e2e] no existing test files in curated list — refuse empty run", flush=True)
        return 2

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
        "requested": requested,
        "skipped_missing": missing,
        "suites": {k: v for k, v in SUITES.items()} if label != "quick" else {"quick": QUICK},
        "runs": [],
    }
    if missing:
        print(f"[e2e] skip missing ({len(missing)}): {', '.join(missing)}", flush=True)
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

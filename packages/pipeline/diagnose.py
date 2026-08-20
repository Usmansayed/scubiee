"""ctx diagnose — shareable installation health report with progress bar.

Collects tech stack, setup state, acceleration profile, and runs a quick
validation suite. Saves results to a timestamped log file the user can share.
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _safe_import_version(module: str) -> str | None:
    try:
        mod = importlib.import_module(module)
        return str(getattr(mod, "__version__", getattr(mod, "version", "unknown")))
    except Exception:
        return None


def _scubiee_version() -> str:
    try:
        from importlib.metadata import version

        return version("scubiee")
    except Exception:
        return "unknown"


def _python_info() -> dict[str, Any]:
    return {
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "executable": sys.executable,
        "prefix": sys.prefix,
    }


def _platform_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
    }
    if platform.system() == "Darwin":
        info["mac_version"] = platform.mac_ver()[0]
    return info


def _hardware_info() -> dict[str, Any]:
    try:
        from pipeline.hardware import ensure_hardware_snapshot

        snap = ensure_hardware_snapshot(force=False)
        return {
            "cpu_model": snap.get("cpu_model"),
            "cpu_count": snap.get("cpu_count_logical") or snap.get("cpu_count"),
            "ram_total_gb": round((snap.get("ram_total_bytes") or 0) / 1e9, 2)
            if snap.get("ram_total_bytes")
            else None,
            "recommended_accel": snap.get("recommended_accel"),
            "gpu": snap.get("gpu") or snap.get("gpu_name"),
        }
    except Exception as exc:
        return {"error": str(exc)}


def _accel_profile() -> dict[str, Any]:
    try:
        from pipeline.accel import load_accel

        prof = load_accel()
        if prof is None:
            return {"profile": None, "detail": "no acceleration profile saved"}
        return {
            "profile": prof.profile,
            "backend": getattr(prof, "backend", prof.profile),
            "batch_size": prof.batch_size,
            "texts_per_sec": prof.texts_per_sec,
        }
    except Exception as exc:
        return {"error": str(exc)}


def _library_versions() -> dict[str, str | None]:
    libs = [
        "numpy",
        "faiss",
        "fastembed",
        "onnxruntime",
        "mlx",
        "torch",
        "sentence_transformers",
        "tree_sitter",
        "tree_sitter_languages",
    ]
    versions: dict[str, str | None] = {}
    for lib in libs:
        versions[lib] = _safe_import_version(lib)
    return versions


def _capabilities_check() -> dict[str, Any]:
    try:
        from pipeline.preflight import inspect_capabilities

        return inspect_capabilities(require_semantic=True)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _index_status() -> dict[str, Any]:
    """Check if any managed projects exist and their health."""
    try:
        from pipeline.project_id import load_registry

        registry = load_registry()
        projects = registry.get("projects", {})
        managed = [
            pid for pid, entry in projects.items()
            if entry.get("managed")
        ]
        return {
            "managed_projects": len(managed),
            "project_ids": managed[:5],
        }
    except Exception as exc:
        return {"error": str(exc)}


def _daemon_status() -> dict[str, Any]:
    """Quick check if the daemon is reachable."""
    import urllib.request
    import urllib.error

    url = os.environ.get("CTX_ENGINE_URL", "http://127.0.0.1:8765")
    try:
        req = urllib.request.Request(f"{url}/health", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            return {
                "reachable": True,
                "url": url,
                "version": data.get("version"),
                "uptime_s": data.get("uptime_s"),
            }
    except Exception:
        return {"reachable": False, "url": url}


def _run_quick_tests(progress_callback=None) -> dict[str, Any]:
    """Run the quick verification tier and return results.

    Only runs if executed from within the scubiee source repository where
    test files exist. When installed as a package (normal user scenario),
    skips tests gracefully since test files are not shipped in the wheel.
    """
    try:
        from pipeline.test_runner import build_test_plan, run_plan

        # Determine where test files would live
        root = Path(__file__).resolve().parents[2]
        test_dir = root / "tests"

        # If tests directory doesn't exist, we're running from an installed
        # package — skip gracefully instead of producing misleading failures.
        if not test_dir.is_dir():
            return {
                "ok": True,
                "skipped": True,
                "reason": "test suite not available (installed package, not source checkout)",
            }

        plan = build_test_plan("quick", root=root)
        targets = list(plan.pytest_targets)

        # Verify at least one target file actually exists
        existing = [t for t in targets if (root / t).is_file()]
        if not existing:
            return {
                "ok": True,
                "skipped": True,
                "reason": "no test files found at expected paths",
            }

        if progress_callback:
            progress_callback(0, len(targets), "Starting tests")

        result = run_plan(plan, root=root, external_client_available=False)

        if progress_callback:
            progress_callback(len(targets), len(targets), "Tests complete")

        return result
    except Exception as exc:
        return {"ok": False, "error": str(exc), "ran": False}


def _memory_budget_info() -> dict[str, Any]:
    return {
        "CTX_CE_MEMORY_MODE": os.environ.get("CTX_CE_MEMORY_MODE", "not set"),
        "CTX_CE_RSS_CAP_MB": os.environ.get("CTX_CE_RSS_CAP_MB", "not set"),
        "CTX_EMBED_BATCH": os.environ.get("CTX_EMBED_BATCH", "not set"),
        "CTX_EMBED_BACKEND": os.environ.get("CTX_EMBED_BACKEND", "not set"),
        "CTX_LIVE_MAX_CHUNKS": os.environ.get("CTX_LIVE_MAX_CHUNKS", "300"),
        "CTX_AUTO_FULL_INDEX_CHUNKS": os.environ.get("CTX_AUTO_FULL_INDEX_CHUNKS", "10000"),
        "CTX_BULK_REINDEX_THRESHOLD": os.environ.get("CTX_BULK_REINDEX_THRESHOLD", "300"),
    }


def diagnose(*, run_tests: bool = True, output_path: Path | None = None) -> dict[str, Any]:
    """Run full diagnostic and return structured report."""
    from pipeline.progress_ui import InstallProgress

    bar = InstallProgress()
    bar.start("Running diagnostics...")

    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scubiee_version": _scubiee_version(),
    }

    # 1. Platform
    bar.set(5, "Checking platform")
    report["platform"] = _platform_info()

    # 2. Python
    bar.set(10, "Checking Python")
    report["python"] = _python_info()

    # 3. Hardware
    bar.set(15, "Detecting hardware")
    report["hardware"] = _hardware_info()

    # 4. Acceleration profile
    bar.set(25, "Checking acceleration")
    report["acceleration"] = _accel_profile()

    # 5. Library versions
    bar.set(35, "Checking libraries")
    report["libraries"] = _library_versions()

    # 6. Capabilities (preflight)
    bar.set(45, "Validating capabilities")
    report["capabilities"] = _capabilities_check()

    # 7. Memory budget config
    bar.set(55, "Checking memory config")
    report["memory_budget"] = _memory_budget_info()

    # 8. Index status
    bar.set(60, "Checking managed projects")
    report["index_status"] = _index_status()

    # 9. Daemon status
    bar.set(65, "Checking daemon")
    report["daemon"] = _daemon_status()

    # 10. Tests
    if run_tests:
        bar.set(70, "Running quick tests")
        test_result = _run_quick_tests(
            progress_callback=lambda done, total, phase: bar.set(
                70 + int(25 * done / max(total, 1)), f"Testing: {phase}"
            )
        )
        report["tests"] = test_result
    else:
        report["tests"] = {"skipped": True}

    # Overall verdict
    caps_ok = bool((report.get("capabilities") or {}).get("ok"))
    tests_ok = bool((report.get("tests") or {}).get("ok", True))
    daemon_ok = bool((report.get("daemon") or {}).get("reachable"))
    accel_ok = bool((report.get("acceleration") or {}).get("profile"))

    report["verdict"] = {
        "ok": caps_ok and tests_ok,
        "capabilities": "pass" if caps_ok else "FAIL",
        "tests": "pass" if tests_ok else "FAIL",
        "daemon": "running" if daemon_ok else "not running",
        "acceleration": report.get("acceleration", {}).get("profile") or "none",
    }

    bar.set(98, "Saving report")

    # Save log file
    log_dir = Path.home() / ".context-engine" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = output_path or (log_dir / f"diagnose_{ts}.json")
    log_file.write_text(
        json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8"
    )
    report["log_file"] = str(log_file)

    if report["verdict"]["ok"]:
        bar.finish("All checks passed")
    else:
        bar.finish("Some checks failed — see report")

    return report

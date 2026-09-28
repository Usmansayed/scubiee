#!/usr/bin/env python3
"""Hard preflight for Cursor-open sims — fail CLOSED on known false-positive gaps.

Catches what quiet Lane A historically missed:
  - onnxruntime without DirectML on a dml-profile Windows machine
  - /health unreachable while engine PID holds the port (GIL wedge)
  - stuck embed_prewarm.busy stamp past max age with dead health

Used by cursor_close_open_loop / cursor_open_prod_battery before claiming green.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packages"
if str(PACKAGES) not in sys.path:
    sys.path.insert(0, str(PACKAGES))


def check_ort_accel() -> dict[str, Any]:
    """Fail if machine profile wants DML but the installed ORT has no Dml EP."""
    out: dict[str, Any] = {"ok": True, "checks": {}}
    try:
        import onnxruntime as ort

        providers = list(ort.get_available_providers() or [])
        ver = str(getattr(ort, "__version__", "") or "")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"onnxruntime import failed: {exc}"}

    out["ort_version"] = ver
    out["providers"] = providers
    profile = "cpu"
    try:
        from pipeline.accel import load_accel

        accel = load_accel()
        if accel is not None:
            profile = str(getattr(accel, "profile", None) or getattr(accel, "name", None) or "cpu").lower()
    except Exception:  # noqa: BLE001
        try:
            from pipeline.project_id import context_engine_home

            raw = json.loads(
                (context_engine_home() / "accel.json").read_text(encoding="utf-8")
            )
            profile = str(raw.get("profile") or raw.get("accel") or "cpu").lower()
        except Exception:  # noqa: BLE001
            if sys.platform.startswith("win"):
                profile = "dml"

    out["profile"] = profile
    has_dml = "DmlExecutionProvider" in providers
    out["checks"]["has_dml"] = has_dml
    if profile in {"dml", "directml"} and sys.platform.startswith("win"):
        if not has_dml:
            out["ok"] = False
            out["error"] = (
                f"profile={profile} but ORT {ver} providers={providers} — "
                "missing DmlExecutionProvider (uv/pip likely installed plain "
                "onnxruntime). Run: scubiee setup --repair"
            )
    # Also fail closed if somehow both cpu-only and version blew past pin
    try:
        major_minor = tuple(int(x) for x in ver.split(".")[:2])
        if major_minor >= (1, 25) and profile in {"dml", "directml"}:
            out["ok"] = False
            out["error"] = (
                (out.get("error") or "")
                + f" ORT {ver} is outside scubiee pin <1.25 (false-positive install)."
            ).strip()
    except ValueError:
        pass
    return out


def check_health_alive(*, timeout_s: float = 8.0) -> dict[str, Any]:
    """Single /health probe — must return JSON if engine claims to be up."""
    from pipeline.client import EngineClient, engine_url

    url = engine_url()
    t0 = time.perf_counter()
    try:
        h = EngineClient(url, timeout=timeout_s).health() or {}
        ms = round((time.perf_counter() - t0) * 1000, 1)
        ok = bool(h.get("ok") or h.get("service") or h.get("soft_search_ready"))
        return {
            "ok": ok,
            "ms": ms,
            "soft_search_ready": bool(h.get("soft_search_ready")),
            "embedder_loaded": bool(h.get("embedder_loaded")),
            "url": url,
        }
    except Exception as exc:  # noqa: BLE001
        ms = round((time.perf_counter() - t0) * 1000, 1)
        # Engine may be intentionally down — only fail if port is held.
        port_held = False
        try:
            from pipeline.daemon import default_host_port
            from pipeline.process_control import pids_listening_on_port

            _host, port = default_host_port()
            port_held = bool(pids_listening_on_port(int(port)))
        except Exception:  # noqa: BLE001
            port_held = False
        return {
            "ok": not port_held,  # down+no listener = fine; listener+/health dead = FAIL
            "ms": ms,
            "error": str(exc),
            "port_held": port_held,
            "code": "HEALTH_WEDGE" if port_held else "ENGINE_DOWN",
            "url": url,
        }


def check_busy_stamp(*, max_age_s: float = 180.0) -> dict[str, Any]:
    from pipeline.engine import prewarm_busy_stamp_active, _prewarm_busy_path

    path = _prewarm_busy_path()
    active = bool(prewarm_busy_stamp_active(max_age_s=max_age_s))
    exists = path.is_file()
    age = None
    if exists:
        try:
            age = time.time() - float((path.read_text(encoding="utf-8") or "0").strip() or 0)
        except (OSError, ValueError):
            age = None
    # Stale file older than max_age while still on disk is a smell but not hard fail
    # unless health is also wedged (combined in main).
    return {"ok": True, "active": active, "exists": exists, "age_s": age, "path": str(path)}


def run_preflight(*, require_engine_up: bool = False) -> dict[str, Any]:
    ort = check_ort_accel()
    health = check_health_alive()
    busy = check_busy_stamp()
    errors: list[str] = []
    if not ort.get("ok"):
        errors.append(str(ort.get("error") or "ort_accel"))
    if require_engine_up and not health.get("ok"):
        errors.append(str(health.get("code") or health.get("error") or "health"))
    if health.get("code") == "HEALTH_WEDGE":
        errors.append("HEALTH_WEDGE: port held but /health times out (GIL/ORT storm)")
    if busy.get("active") and health.get("code") == "HEALTH_WEDGE":
        errors.append("prewarm busy stamp active during HEALTH_WEDGE")
    # Stale busy file + health wedge
    age = busy.get("age_s")
    if (
        busy.get("exists")
        and age is not None
        and float(age) > 180.0
        and health.get("code") == "HEALTH_WEDGE"
    ):
        errors.append(f"stale embed_prewarm.busy age_s={age:.0f} with HEALTH_WEDGE")

    return {
        "ok": not errors,
        "errors": errors,
        "ort": ort,
        "health": health,
        "busy": busy,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--require-engine-up",
        action="store_true",
        help="Fail if engine is down (default: only fail on wedge/ORT mismatch)",
    )
    args = ap.parse_args()
    report = run_preflight(require_engine_up=bool(args.require_engine_up))
    print(json.dumps(report, indent=2))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

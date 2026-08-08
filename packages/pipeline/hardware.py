"""Hardware / capability snapshot for Context Engine.

Used at install and by the Resource Manager. Persists to
``~/.context-engine/hardware.json``. Complements ``accel.py`` (ORT profile pick).
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _home() -> Path:
    try:
        from pipeline.project_id import context_engine_home

        return context_engine_home()
    except Exception:  # noqa: BLE001
        return Path.home() / ".context-engine"


def hardware_path() -> Path:
    return _home() / "hardware.json"


def _cpu_model() -> str | None:
    system = platform.system()
    try:
        if system == "Windows":
            r = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            name = (r.stdout or "").strip()
            return name or None
        if system == "Darwin":
            r = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return (r.stdout or "").strip() or None
        # Linux
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.lower().startswith("model name"):
                return line.split(":", 1)[-1].strip()
    except Exception:  # noqa: BLE001
        return None
    return None


def _ram_bytes() -> dict[str, int | None]:
    total = avail = None
    try:
        import psutil  # type: ignore

        vm = psutil.virtual_memory()
        total = int(vm.total)
        avail = int(vm.available)
        return {"total": total, "available": avail}
    except Exception:  # noqa: BLE001
        pass
    try:
        if platform.system() == "Windows":
            r = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "$o=Get-CimInstance Win32_OperatingSystem; "
                    "@{total=[int64]$o.TotalVisibleMemorySize*1KB; "
                    "free=[int64]$o.FreePhysicalMemory*1KB} | ConvertTo-Json -Compress",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if r.returncode == 0 and r.stdout.strip():
                data = json.loads(r.stdout)
                return {
                    "total": int(data.get("total") or 0) or None,
                    "available": int(data.get("free") or 0) or None,
                }
        if platform.system() == "Linux":
            info: dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if ":" not in line:
                    continue
                k, v = line.split(":", 1)
                parts = v.strip().split()
                if parts:
                    info[k] = int(parts[0]) * 1024  # kB → bytes
            return {
                "total": info.get("MemTotal"),
                "available": info.get("MemAvailable") or info.get("MemFree"),
            }
    except Exception:  # noqa: BLE001
        pass
    return {"total": total, "available": avail}


def _accel_libs() -> dict[str, Any]:
    out: dict[str, Any] = {
        "onnxruntime": None,
        "onnxruntime_providers": [],
        "torch_cuda": False,
        "torch_mps": False,
        "mlx": False,
        "psutil": False,
    }
    try:
        import onnxruntime as ort  # type: ignore

        out["onnxruntime"] = getattr(ort, "__version__", "unknown")
        try:
            out["onnxruntime_providers"] = list(ort.get_available_providers())
        except Exception:  # noqa: BLE001
            out["onnxruntime_providers"] = []
    except Exception:  # noqa: BLE001
        pass
    try:
        import torch  # type: ignore

        out["torch_cuda"] = bool(torch.cuda.is_available())
        out["torch_mps"] = bool(
            getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        import mlx.core  # type: ignore  # noqa: F401

        out["mlx"] = True
    except Exception:  # noqa: BLE001
        pass
    try:
        import psutil  # type: ignore  # noqa: F401

        out["psutil"] = True
    except Exception:  # noqa: BLE001
        pass
    return out


def detect_capabilities() -> dict[str, Any]:
    """Full hardware + library snapshot (also merges accel.detect_hardware)."""
    from pipeline.accel import detect_hardware, recommend_profile

    base = detect_hardware()
    ram = _ram_bytes()
    libs = _accel_libs()
    snap = {
        **base,
        "cpu_model": _cpu_model(),
        "cpu_count_logical": os.cpu_count() or base.get("cpu_count") or 4,
        "ram_total_bytes": ram.get("total"),
        "ram_available_bytes": ram.get("available"),
        "libraries": libs,
        "detected_at": time.time(),
        "platform": platform.platform(),
    }
    # Suggested accel (does not install)
    try:
        prof = recommend_profile(base)
        snap["recommended_accel"] = {
            "profile": prof.profile,
            "provider": prof.provider,
            "batch_size": prof.batch_size,
            "reason": prof.reason,
            "device_id": prof.device_id,
        }
    except Exception as exc:  # noqa: BLE001
        snap["recommended_accel"] = {"error": str(exc)}
    return snap


def save_hardware(snap: dict[str, Any] | None = None) -> Path:
    path = hardware_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = snap or detect_capabilities()
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")
    return path


def load_hardware() -> dict[str, Any]:
    path = hardware_path()
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def ensure_hardware_snapshot(*, force: bool = False) -> dict[str, Any]:
    """Load cached snapshot or detect + save on first launch."""
    if not force:
        existing = load_hardware()
        if existing.get("detected_at"):
            return existing
    snap = detect_capabilities()
    save_hardware(snap)
    return snap

"""Detect and repair broken uv-tool / faiss installs (Windows-heavy)."""

from __future__ import annotations

import glob
import importlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def faiss_class_wrappers_present() -> bool:
    for root in sys.path:
        candidate = Path(root) / "faiss" / "class_wrappers.py"
        if candidate.is_file():
            return True
    return False


def faiss_import_ok() -> bool:
    if "faiss" in sys.modules:
        sys.modules.pop("faiss", None)
    try:
        importlib.import_module("faiss")
    except Exception:
        return False
    return True


def _faiss_wheel_repair() -> None:
    from pipeline.accel import pip_install

    tmp = Path(tempfile.mkdtemp(prefix="scubiee-faiss-"))
    try:
        dl = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "faiss-cpu==1.15.0",
                "-d",
                str(tmp),
                "--no-deps",
                "--quiet",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if dl.returncode != 0:
            detail = (dl.stderr or dl.stdout or "").strip() or f"exit {dl.returncode}"
            raise RuntimeError(f"faiss wheel download failed: {detail}")
        wheels = sorted(glob.glob(str(tmp / "faiss_cpu-*.whl")))
        if not wheels:
            raise RuntimeError("faiss wheel not found after download")
        pip_install([wheels[0]], force_reinstall=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def ensure_faiss_importable(*, repair: bool = True) -> str | None:
    """Return an error message if faiss cannot be imported (optionally repair once)."""
    if faiss_import_ok():
        return None
    if not repair:
        return "faiss import failed (run scubiee setup --repair or scripts/repair-uv-scubiee.ps1)"
    if not faiss_class_wrappers_present():
        try:
            _faiss_wheel_repair()
        except Exception as exc:  # noqa: BLE001
            return (
                "faiss-cpu install is incomplete (missing class_wrappers.py). "
                f"Repair failed: {exc}. "
                "On Windows run: scripts/repair-uv-scubiee.ps1"
            )
    if faiss_import_ok():
        return None
    return (
        "faiss still broken after repair. "
        "Quit Cursor (releases MCP lock), then run scripts/repair-uv-scubiee.ps1"
    )

"""Detect multiple scubiee installations that could fight over the daemon."""

import os
import shutil
import sys
from pathlib import Path
from pipeline.project_id import context_engine_home


def active_install_prefix() -> str:
    """Return sys.prefix for the current scubiee install."""
    return sys.prefix


def write_install_marker() -> None:
    """Write current install's sys.prefix to ~/.scubiee/install_marker.json"""
    import json

    home = context_engine_home()
    if not (home / "accel.json").is_file():
        return
    marker_path = home / "install_marker.json"
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "sys_prefix": sys.prefix,
        "executable": sys.executable,
        "version": _get_version(),
    }
    marker_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def check_install_conflict() -> dict | None:
    """Check if another install is active. Returns conflict info or None."""
    import json

    marker_path = context_engine_home() / "install_marker.json"
    if not marker_path.is_file():
        return None
    try:
        data = json.loads(marker_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    recorded_prefix = data.get("sys_prefix", "")
    if not recorded_prefix:
        return None
    current = sys.prefix
    if os.path.normcase(recorded_prefix) != os.path.normcase(current):
        return {
            "conflict": True,
            "current_prefix": current,
            "recorded_prefix": recorded_prefix,
            "recorded_executable": data.get("executable", ""),
            "recorded_version": data.get("version", ""),
            "hint": (
                f"Another scubiee install is active at {recorded_prefix}. "
                "Two installs sharing ~/.scubiee will fight over the daemon. "
                "Uninstall one: pip uninstall scubiee OR uv tool uninstall scubiee"
            ),
        }
    return None


def detect_multiple_on_path() -> list[str]:
    """Find all scubiee executables on PATH."""
    paths: list[str] = []
    found = shutil.which("scubiee")
    if found:
        paths.append(found)
    # Also check common locations
    candidates = [
        Path.home() / ".local" / "bin" / "scubiee",
        Path.home() / ".local" / "bin" / "scubiee.exe",
        Path(sys.prefix) / "Scripts" / "scubiee.exe",
        Path(sys.prefix) / "bin" / "scubiee",
    ]
    for c in candidates:
        if c.is_file() and str(c) not in paths:
            paths.append(str(c))
    return paths


def _get_version() -> str:
    try:
        import importlib.metadata

        return importlib.metadata.version("scubiee")
    except Exception:  # noqa: BLE001
        return "unknown"

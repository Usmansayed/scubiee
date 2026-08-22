"""Detect multiple Python installs so pip/scubiee cannot silently diverge."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def current_python() -> Path:
    return Path(sys.executable).resolve()


def expected_scubiee_exe(python: Path | None = None) -> Path:
    py = python or current_python()
    if sys.platform == "win32":
        return py.parent / "Scripts" / "scubiee.exe"
    return py.parent / "scubiee"


def scubiee_executables_on_path() -> list[Path]:
    name = "scubiee.exe" if sys.platform == "win32" else "scubiee"
    found: list[Path] = []
    seen: set[str] = set()
    for part in os.environ.get("PATH", "").split(os.pathsep):
        if not part:
            continue
        candidate = Path(part) / name
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_file():
            continue
        key = str(resolved).lower() if sys.platform == "win32" else str(resolved)
        if key in seen:
            continue
        seen.add(key)
        found.append(resolved)
    return found


def _is_uv_tool_shim(extra: Path, python: Path | None = None) -> bool:
    """``~/.local/bin/scubiee`` is uv's launcher, not a second pip/conda install."""
    py = python or current_python()
    py_s = str(py).replace("\\", "/").lower()
    if "uv/tools/" not in py_s and "/uv/tools/" not in py_s:
        return False
    extra_s = str(extra).replace("\\", "/").lower()
    return "/.local/bin/" in extra_s or extra_s.endswith("/.local/bin/scubiee.exe")


def extra_scubiee_on_path() -> list[Path]:
    """Other env's scubiee.exe that PATH may pick instead of this interpreter."""
    expected = expected_scubiee_exe()
    py = current_python()
    extras: list[Path] = []
    for path in scubiee_executables_on_path():
        try:
            if path.resolve() == expected.resolve():
                continue
        except OSError:
            pass
        if _is_uv_tool_shim(path, py):
            continue
        extras.append(path)
    return extras


def format_install_identity() -> str:
    try:
        from importlib.metadata import version as pkg_version

        ver = pkg_version("scubiee")
    except Exception:  # noqa: BLE001
        ver = "unknown"
    py = current_python()
    lines = [
        f"scubiee {ver}",
        f"python  {py} ({sys.version.split()[0]})",
        "uninstall this copy:",
        "  scubiee stop",
        "  scubiee wipe --all --yes --package",
        "  uv tool uninstall scubiee   # if tool dir remains",
        f"  {py} -m pip uninstall scubiee -y   # pip/venv installs only",
    ]
    extras = extra_scubiee_on_path()
    if extras:
        lines.append("WARNING: another scubiee is also on PATH:")
        for extra in extras:
            other_py = extra.parent.parent / ("python.exe" if sys.platform == "win32" else "python")
            lines.append(f"  {extra}")
            if other_py.is_file():
                lines.append(f"  uninstall with: {other_py} -m pip uninstall scubiee -y")
    return "\n".join(lines)


def warn_extra_scubiee(stream=None) -> None:
    extras = extra_scubiee_on_path()
    if not extras:
        return
    out = stream if stream is not None else sys.stderr
    out.write(
        "[scubiee] WARNING: PATH has another scubiee besides this Python.\n"
        f"[scubiee] this Python: {current_python()}\n"
    )
    for extra in extras:
        out.write(f"[scubiee] also found: {extra}\n")
    out.write(
        "[scubiee] uninstall must match how you installed (uv tool vs pip).\n"
        "[scubiee] uv:  uv tool uninstall scubiee\n"
        f"[scubiee] pip: {current_python()} -m pip uninstall scubiee -y\n"
    )
    out.flush()

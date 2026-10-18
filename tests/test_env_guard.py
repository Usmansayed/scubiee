from __future__ import annotations

import io
import sys
from pathlib import Path

from pipeline import accel, env_guard


def test_extra_scubiee_on_path(tmp_path: Path, monkeypatch) -> None:
    fake_scripts = tmp_path / "Python312" / "Scripts"
    fake_scripts.mkdir(parents=True)
    extra = fake_scripts / ("scubiee.exe" if sys.platform == "win32" else "scubiee")
    extra.write_bytes(b"")
    ours = env_guard.expected_scubiee_exe()
    monkeypatch.setenv("PATH", str(fake_scripts) + os_pathsep() + str(ours.parent))
    extras = env_guard.extra_scubiee_on_path()
    assert extra.resolve() in extras
    assert ours.resolve() not in extras


def os_pathsep() -> str:
    import os

    return os.pathsep


def test_format_install_identity_includes_python_and_uninstall() -> None:
    text = env_guard.format_install_identity()
    assert "python" in text.lower()
    assert "-m pip uninstall scubiee" in text


def test_warn_extra_scubiee_silent_when_only_ours(monkeypatch) -> None:
    monkeypatch.setenv("PATH", str(env_guard.expected_scubiee_exe().parent))
    buf = io.StringIO()
    env_guard.warn_extra_scubiee(buf)
    assert buf.getvalue() == ""


def test_expected_scubiee_exe_windows_scripts_layout(monkeypatch) -> None:
    monkeypatch.setattr(env_guard.sys, "platform", "win32")
    uv_py = Path("C:/Users/me/AppData/Roaming/uv/tools/scubiee/Scripts/python.exe")
    assert env_guard.expected_scubiee_exe(uv_py) == uv_py.parent / "scubiee.exe"


def test_expected_scubiee_exe_windows_root_python_layout(monkeypatch) -> None:
    monkeypatch.setattr(env_guard.sys, "platform", "win32")
    py = Path("C:/Python312/python.exe")
    assert env_guard.expected_scubiee_exe(py) == py.parent / "Scripts" / "scubiee.exe"


def test_uv_tool_shim_not_counted_as_duplicate(monkeypatch) -> None:
    uv_py = Path("C:/Users/me/AppData/Roaming/uv/tools/scubiee/Scripts/python.exe")
    uv_exe = uv_py.parent / "scubiee.exe"
    shim = Path("C:/Users/me/.local/bin/scubiee.exe")
    monkeypatch.setattr(env_guard, "current_python", lambda: uv_py)
    monkeypatch.setattr(env_guard, "expected_scubiee_exe", lambda: uv_exe)
    monkeypatch.setattr(
        env_guard,
        "scubiee_executables_on_path",
        lambda: [uv_exe.resolve(), shim.resolve()],
    )
    assert env_guard.extra_scubiee_on_path() == []


def test_symlinked_venv_python_is_not_resolved_to_base(tmp_path: Path, monkeypatch) -> None:
    """Linux uv tool layout: tool python -> /usr/local/bin/python3.12, ~/.local/bin/scubiee -> tool bin."""
    import os
    import sys

    import pytest

    base = tmp_path / "usr-local-bin"
    tool_bin = tmp_path / "uv" / "tools" / "scubiee" / "bin"
    shim_dir = tmp_path / "home" / ".local" / "bin"
    for d in (base, tool_bin, shim_dir):
        d.mkdir(parents=True)
    (base / "python3.12").write_bytes(b"")
    (tool_bin / "scubiee").write_bytes(b"")
    try:
        os.symlink(base / "python3.12", tool_bin / "python")
        os.symlink(tool_bin / "scubiee", shim_dir / "scubiee")
    except OSError:
        pytest.skip("symlinks not permitted")
    monkeypatch.setattr(env_guard.sys, "platform", "linux")
    monkeypatch.setattr(sys, "executable", str(tool_bin / "python"))
    monkeypatch.setenv("PATH", str(shim_dir))

    assert env_guard.expected_scubiee_exe() == tool_bin / "scubiee"
    assert env_guard.extra_scubiee_on_path() == []
    report = env_guard.install_identity_report()
    assert report["multiple_installs"] is False


def test_remove_stale_ort_tree(tmp_path: Path, monkeypatch) -> None:
    leftover = tmp_path / "onnxruntime"
    (leftover / "capi").mkdir(parents=True)
    (leftover / "capi" / "x.dll").write_bytes(b"x")
    monkeypatch.setattr(accel, "_site_package_roots", lambda: [tmp_path])
    removed = accel.remove_stale_ort_tree()
    assert str(leftover) in removed
    assert not leftover.exists()

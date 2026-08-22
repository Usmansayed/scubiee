from __future__ import annotations

import io
from pathlib import Path

from pipeline import accel, env_guard


def test_extra_scubiee_on_path(tmp_path: Path, monkeypatch) -> None:
    fake_scripts = tmp_path / "Python312" / "Scripts"
    fake_scripts.mkdir(parents=True)
    extra = fake_scripts / "scubiee.exe"
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

def test_remove_stale_ort_tree(tmp_path: Path, monkeypatch) -> None:
    leftover = tmp_path / "onnxruntime"
    (leftover / "capi").mkdir(parents=True)
    (leftover / "capi" / "x.dll").write_bytes(b"x")
    monkeypatch.setattr(accel, "_site_package_roots", lambda: [tmp_path])
    removed = accel.remove_stale_ort_tree()
    assert str(leftover) in removed
    assert not leftover.exists()

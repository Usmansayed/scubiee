from __future__ import annotations

from pathlib import Path

from pipeline import process_control


def test_uv_tool_root_from_scripts_python() -> None:
    py = Path("C:/Users/me/AppData/Roaming/uv/tools/scubiee/Scripts/python.exe")
    root = process_control.uv_tool_root(py)
    assert root == Path("C:/Users/me/AppData/Roaming/uv/tools/scubiee")


def test_uv_tool_root_none_for_conda() -> None:
    py = Path("C:/Users/me/Miniconda3/python.exe")
    assert process_control.uv_tool_root(py) is None


def test_is_uv_tool_install_checks_receipt(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "uv" / "tools" / "scubiee"
    scripts = root / "Scripts"
    scripts.mkdir(parents=True)
    py = scripts / "python.exe"
    py.write_bytes(b"")
    (root / "uv-receipt.toml").write_text("[tool]\n", encoding="utf-8")
    monkeypatch.setattr(process_control, "uv_tool_root", lambda _p=None: root)
    assert process_control.is_uv_tool_install(py) is True

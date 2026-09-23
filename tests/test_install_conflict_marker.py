"""Install-conflict must not clobber the active uv-tool marker."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch


def test_start_daemon_conflict_does_not_rewrite_marker(tmp_path: Path, monkeypatch) -> None:
    from pipeline import daemon as d
    from pipeline import install_guard as ig

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    # Pretend accel exists so write_install_marker would be allowed.
    (home / "accel.json").write_text("{}", encoding="utf-8")
    marker = home / "install_marker.json"
    marker.write_text(
        json.dumps(
            {
                "sys_prefix": str(tmp_path / "uv-tool"),
                "executable": str(tmp_path / "uv-tool" / "pythonw.exe"),
                "version": "0.3.74",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "uv-tool").mkdir()
    (tmp_path / "uv-tool" / "pythonw.exe").write_text("", encoding="utf-8")

    monkeypatch.setattr(ig, "active_install_prefix", lambda: str(tmp_path / "conda"))
    monkeypatch.setattr(d, "is_running", lambda: True)
    wrote = {"n": 0}

    def boom():
        wrote["n"] += 1

    monkeypatch.setattr(ig, "write_install_marker", boom)
    out = d.start_daemon(tmp_path, wait_s=0)
    assert out.get("already_running") is True
    assert out.get("install_conflict")
    assert wrote["n"] == 0
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert "uv-tool" in data["sys_prefix"]

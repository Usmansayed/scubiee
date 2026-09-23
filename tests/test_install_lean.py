"""Lean install selection: one keeper, older copies dropped, MCP retargeted."""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.install_lean import (
    Install,
    _child_env,
    apply_lean,
    choose_keeper,
    retarget_mcp_file,
    version_key,
)


def test_version_key_orders_patch_releases() -> None:
    assert version_key("0.3.102") < version_key("0.3.107")
    assert version_key("0.3.107") == version_key("0.3.107")


def test_tie_keeps_uv_tool_not_pip() -> None:
    pip = Install(prefix="C:/conda", python="C:/conda/python.exe", version="0.3.107", kind="pip")
    uv = Install(
        prefix="C:/uv/scubiee",
        python="C:/uv/scubiee/Scripts/python.exe",
        version="0.3.107",
        kind="uv-tool",
    )
    assert choose_keeper([pip, uv]) == uv


def test_newer_pip_beats_older_uv() -> None:
    pip = Install(prefix="C:/conda", python="C:/conda/python.exe", version="0.3.108", kind="pip")
    uv = Install(
        prefix="C:/uv/scubiee",
        python="C:/uv/scubiee/Scripts/python.exe",
        version="0.3.107",
        kind="uv-tool",
    )
    assert choose_keeper([uv, pip]) == pip


def test_apply_lean_uninstalls_older_and_rewrites_mcp(tmp_path: Path) -> None:
    keeper = Install(
        prefix="C:/uv/scubiee",
        python="C:/uv/scubiee/Scripts/python.exe",
        version="0.3.107",
        kind="uv-tool",
    )
    old = Install(
        prefix="C:/conda",
        python="C:/conda/python.exe",
        version="0.3.102",
        kind="pip",
    )
    mcp = tmp_path / "mcp.json"
    mcp.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "scubiee": {
                        "command": "C:/conda/pythonw.exe",
                        "args": ["-u", "-m", "pipeline.mcp_bridge"],
                        "env": {"CTX_SCUBIEE_BUILD": "0.3.102-old"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    calls: list[str] = []

    def _fake_uninstall(python: str) -> dict:
        calls.append(python)
        return {"ok": True, "python": python}

    report = apply_lean(
        installs=[old, keeper],
        uninstall=_fake_uninstall,
        mcp_paths=[mcp],
        build_id="0.3.107-test",
    )
    assert calls == ["C:/conda/python.exe"]
    assert report["keeper"]["kind"] == "uv-tool"
    data = json.loads(mcp.read_text(encoding="utf-8"))
    entry = data["mcpServers"]["scubiee"]
    assert "uv/scubiee" in entry["command"].replace("\\", "/")
    assert Path(entry["command"]).name.lower().startswith("python")
    assert entry["env"]["CTX_SCUBIEE_BUILD"] == "0.3.107-test"
    assert report["mcp_rewritten"] == [str(mcp)]


def test_retarget_leaves_keeper_command(tmp_path: Path) -> None:
    mcp = tmp_path / "mcp.json"
    cmd = "C:/uv/scubiee/Scripts/pythonw.exe"
    mcp.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "scubiee": {
                        "command": cmd,
                        "args": ["-u", "-m", "pipeline.mcp_bridge"],
                        "env": {"CTX_SCUBIEE_BUILD": "0.3.107-test"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert retarget_mcp_file(mcp, cmd, "0.3.107-test") is False


def test_child_env_drops_pythonpath(monkeypatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "C:/uv/scubiee/Lib/site-packages")
    monkeypatch.setenv("PYTHONHOME", "C:/uv/scubiee")
    env = _child_env()
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env

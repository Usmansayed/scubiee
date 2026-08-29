"""Verify scubiee setup does NOT write MCP or connect to tools automatically."""

import argparse
from pathlib import Path
from types import SimpleNamespace
import pytest

from pipeline import __main__ as cli
from pipeline.accel import AccelProfile


def test_setup_does_not_write_cursor_or_tool_mcp(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("APPDATA", str(fake_home / "AppData" / "Roaming"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    repo = tmp_path / "project"
    repo.mkdir()

    monkeypatch.setattr(
        "pipeline.accel.configure",
        lambda *args, **kwargs: AccelProfile(
            profile="cpu",
            provider="CPUExecutionProvider",
            batch_size=16,
            envelope={},
        ),
    )
    monkeypatch.setattr(
        "pipeline.lifecycle_runtime.install_session_runtime",
        lambda: {"ok": True, "desktop": "windows"},
    )
    monkeypatch.setitem(__import__("sys").modules, "graphify.extract", SimpleNamespace(extract=lambda: None))
    monkeypatch.setitem(__import__("sys").modules, "graphify.build", SimpleNamespace(build=lambda: None))

    args = argparse.Namespace(
        status=False,
        skip_accel=False,
        skip_install=True,
        skip_model=True,
        skip_bench=True,
        repair=False,
        profile=None,
        repo=str(repo),
        index_path=None,
        register=False,
        host="127.0.0.1",
        port=8765,
        wait=1.0,
    )

    ret = cli.cmd_setup(args)
    assert ret == 0

    # Ensure NO MCP was written to user cursor or repo cursor on setup
    user_cursor_mcp = fake_home / ".cursor" / "mcp.json"
    repo_cursor_mcp = repo / ".cursor" / "mcp.json"
    assert not user_cursor_mcp.exists(), "Setup should not write user ~/.cursor/mcp.json"
    assert not repo_cursor_mcp.exists(), "Setup should not write project .cursor/mcp.json"

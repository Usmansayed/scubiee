"""Integration: hardware fs_id resolves moved checkouts for fan-out and registry."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from pipeline.hw_track import get_filesystem_id, resolve_moved_path
from pipeline.managed_repos import iter_registry_checkout_paths, managed_repo_paths
from pipeline.rules_installer import install_tool
from pipeline.tool_registry import TOOL_MAP

from conftest import write_machine_setup


@pytest.mark.skipif(
    os.name != "nt" and sys.platform != "darwin",
    reason="hw_track resolve requires Windows or macOS",
)
def test_fan_out_finds_hw_moved_checkout(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "ce-home"
    write_machine_setup(home)
    monkeypatch.setenv("CTX_HOME", str(home))

    original = tmp_path / "project-a"
    original.mkdir()
    (original / ".git").mkdir()
    (original / ".scubiee").mkdir()
    pid = "ce_hw_move_fanout1234567890ab"
    (original / ".scubiee" / "id.json").write_text(
        json.dumps({"project_id": pid}), encoding="utf-8"
    )

    fs_id = get_filesystem_id(original)
    assert fs_id is not None

    from pipeline.project_id import save_registry

    stale = str(original.resolve())
    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": stale,
                    "paths": [stale],
                    "fs_id": fs_id,
                }
            }
        }
    )

    moved = tmp_path / "renamed-project"
    shutil.move(str(original), moved)
    assert not original.exists()
    assert resolve_moved_path(fs_id).resolve() == moved.resolve()

    rows = iter_registry_checkout_paths()
    sources = {row["source"] for row in rows if row["project_id"] == pid}
    assert "fs_id" in sources
    assert any(row["exists"] and Path(row["path"]).resolve() == moved.resolve() for row in rows)

    fan_out = managed_repo_paths(enrolled_only=False)
    assert moved.resolve() in {p.resolve() for p in fan_out}

    report = install_tool(TOOL_MAP["cursor"], repo=moved)
    assert report["ok"], report
    assert report["project_fan_out"]["repos"] >= 1
    assert (moved / ".cursor" / "mcp.json").is_file()


@pytest.mark.skipif(
    os.name != "nt" and sys.platform != "darwin",
    reason="hw_track resolve requires Windows or macOS",
)
def test_wipe_registry_collects_hw_moved_path(tmp_path: Path, monkeypatch) -> None:
    from pipeline.wipe import _registered_repo_roots

    home = tmp_path / "ce-home"
    write_machine_setup(home)
    monkeypatch.setenv("CTX_HOME", str(home))

    original = tmp_path / "wipe-target"
    original.mkdir()
    (original / ".scubiee").mkdir()
    pid = "ce_hw_move_wipe1234567890ab"
    (original / ".scubiee" / "id.json").write_text(
        json.dumps({"project_id": pid}), encoding="utf-8"
    )

    fs_id = get_filesystem_id(original)
    assert fs_id is not None

    from pipeline.project_id import save_registry

    stale = str(original.resolve())
    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": stale,
                    "paths": [stale],
                    "fs_id": fs_id,
                }
            }
        }
    )

    moved = tmp_path / "wipe-target-moved"
    shutil.move(str(original), moved)

    roots = _registered_repo_roots()
    assert moved.resolve() in {p.resolve() for p in roots}

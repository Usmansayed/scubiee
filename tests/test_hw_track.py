"""Unit tests for hardware-level filesystem tracking across moves and renames."""

import os
import sys
import shutil
import tempfile
from pathlib import Path
import pytest

from pipeline.hw_track import get_filesystem_id, resolve_moved_path


def test_hardware_tracking_capture_and_resolve(tmp_path: Path):
    orig_dir = tmp_path / "orig_project"
    orig_dir.mkdir(parents=True, exist_ok=True)
    (orig_dir / ".scubiee").mkdir(exist_ok=True)
    (orig_dir / ".scubiee" / "id.json").write_text('{"project_id": "ce_test_123"}', encoding="utf-8")

    # 1. Capture hardware filesystem ID
    fs_id = get_filesystem_id(orig_dir)
    assert fs_id is not None
    if os.name == "nt":
        assert fs_id.get("os") == "nt"
        assert "file_id" in fs_id
        assert "vol_serial" in fs_id
    elif sys.platform == "darwin":
        assert fs_id.get("os") == "darwin"
        assert "dev" in fs_id
        assert "ino" in fs_id

    # 2. Rename / move the folder to a new path
    moved_dir = tmp_path / "moved_deep_project"
    orig_dir.rename(moved_dir)
    assert not orig_dir.exists()
    assert moved_dir.exists()

    # 3. Resolve moved directory using the hardware ID
    resolved = resolve_moved_path(fs_id)
    if os.name == "nt" or sys.platform == "darwin":
        assert resolved is not None, "resolve_moved_path unavailable on this host"
        assert resolved.resolve() == moved_dir.resolve()
        assert (resolved / ".scubiee" / "id.json").is_file()


def test_hardware_tracking_shutil_move(tmp_path: Path) -> None:
    orig_dir = tmp_path / "orig_project_b"
    orig_dir.mkdir(parents=True, exist_ok=True)
    fs_id = get_filesystem_id(orig_dir)
    assert fs_id is not None

    moved_dir = tmp_path / "moved_via_shutil"
    shutil.move(str(orig_dir), moved_dir)
    resolved = resolve_moved_path(fs_id)
    if os.name == "nt" or sys.platform == "darwin":
        assert resolved is not None
        assert resolved.resolve() == moved_dir.resolve()

"""Confirm is for mistake-scale scopes, not normal 500–1000 file repos."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.incremental import (
    DEFAULT_MAX_TOUCH,
    IndexConfirmRequired,
    preflight_index_scope,
    require_index_confirm,
)
from pipeline.indexer import count_indexable_files


def test_require_index_confirm_allows_normal_codebases() -> None:
    require_index_confirm(401, confirm=False, force=False)
    require_index_confirm(1000, confirm=False, force=False)
    require_index_confirm(5000, confirm=False, force=False)


def test_require_index_confirm_blocks_mistake_scale() -> None:
    n = DEFAULT_MAX_TOUCH + 1
    with pytest.raises(IndexConfirmRequired) as exc:
        require_index_confirm(n, confirm=False, force=False)
    assert exc.value.n_files == n
    assert exc.value.max_touch == DEFAULT_MAX_TOUCH
    assert "Safety pause" in str(exc.value)
    require_index_confirm(n, confirm=True, force=False)
    require_index_confirm(n, confirm=False, force=True)


def test_count_indexable_files_respects_fast_roots(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "b.py").write_text("y = 2\n", encoding="utf-8")
    full = count_indexable_files(tmp_path, fast=False)
    fast = count_indexable_files(tmp_path, fast=True, fast_roots=["src"])
    assert full >= 1
    assert fast == 1


def test_broad_home_root_requires_confirm(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "notes.md").write_text("# hi\n", encoding="utf-8")
    monkeypatch.setattr("pipeline.incremental.Path.home", lambda: home)
    with pytest.raises(IndexConfirmRequired) as exc:
        preflight_index_scope(home, confirm=False)
    assert "user home directory" in str(exc.value)
    assert "scubiee init" in str(exc.value)
    assert "--confirm" in str(exc.value)


def test_broad_home_allows_explicit_confirm(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "a.py").write_text("x=1\n", encoding="utf-8")
    monkeypatch.setattr("pipeline.incremental.Path.home", lambda: home)
    assert preflight_index_scope(home, confirm=True) == 1


def test_index_file_hashes_skip_testdata(tmp_path: Path) -> None:
    from pipeline.indexer import _index_file_hashes

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.py").write_text("x=1\n", encoding="utf-8")
    td = tmp_path / "testdata" / "fixture"
    td.mkdir(parents=True)
    for i in range(50):
        (td / f"f{i}.py").write_text(f"x={i}\n", encoding="utf-8")
    assert len(_index_file_hashes(tmp_path)) == 1
    assert preflight_index_scope(tmp_path, confirm=False) == 1

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


def test_require_chunk_force_blocks_over_20k() -> None:
    from pipeline.incremental import DEFAULT_MAX_CHUNKS, require_chunk_force

    require_chunk_force(DEFAULT_MAX_CHUNKS, force=False)
    with pytest.raises(IndexConfirmRequired) as exc:
        require_chunk_force(DEFAULT_MAX_CHUNKS + 1, force=False)
    assert exc.value.kind == "too_many_chunks"
    assert "too many tokens" in str(exc.value).lower()
    assert "--force" in str(exc.value)
    # --confirm must NOT bypass; only --force
    require_chunk_force(DEFAULT_MAX_CHUNKS + 1, force=True)
    payload = exc.value.to_payload(Path("."))
    assert payload["needs_force"] is True
    assert payload["warning"] == "too_many_chunks"


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


def test_broad_home_confirm_still_caps_huge_tree(monkeypatch, tmp_path: Path) -> None:
    """`--confirm` on a home/drive root must NOT also waive the file-count cap.

    Regression for the "looks hung for 20 minutes" trap: `scubiee init --confirm`
    on the home dir used to silently index hundreds of thousands of files
    (AppData, caches, node_modules, …). Now a broad root above the cap still
    stops and demands `--force`; only a genuinely small home passes on --confirm.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pipeline.incremental.Path.home", lambda: home)
    # The broad-root path uses the FAST bounded check, not the full count.
    monkeypatch.setattr("pipeline.paths.exceeds_index_cap", lambda root, cap: True)
    # The full count must NOT be called on the over-cap broad path (that's the
    # whole point — it's what hangs). Make it blow up if reached.
    def _boom(*a, **k):
        raise AssertionError("full count must not run on over-cap broad root")
    monkeypatch.setattr("pipeline.incremental.collect_index_relpaths", _boom)
    # confirm alone is NOT enough on a broad root above the cap.
    with pytest.raises(IndexConfirmRequired) as exc:
        preflight_index_scope(home, confirm=True, force=False)
    assert exc.value.kind == "broad_over_cap"
    # The message must point at --force/--roots, NOT tell them to re-pass --confirm.
    msg = str(exc.value)
    assert "--force" in msg and "--roots" in msg
    # --force is the explicit "I really mean it" escape and skips the gate.
    monkeypatch.setattr(
        "pipeline.incremental.collect_index_relpaths",
        lambda *a, **k: {f"f{i}.py" for i in range(DEFAULT_MAX_TOUCH + 5)},
    )
    assert preflight_index_scope(home, confirm=True, force=True) == DEFAULT_MAX_TOUCH + 5


def test_broad_home_confirm_under_cap_counts_precisely(monkeypatch, tmp_path: Path) -> None:
    """A broad root UNDER the cap on --confirm still returns the precise count."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pipeline.incremental.Path.home", lambda: home)
    monkeypatch.setattr("pipeline.paths.exceeds_index_cap", lambda root, cap: False)
    monkeypatch.setattr(
        "pipeline.incremental.collect_index_relpaths",
        lambda *a, **k: {"a.py", "b.py", "c.py"},
    )
    assert preflight_index_scope(home, confirm=True, force=False) == 3


def test_normal_project_confirm_still_waives_cap(tmp_path: Path) -> None:
    """A non-broad project path keeps the old behaviour: --confirm waives the cap."""
    import pipeline.incremental as inc

    proj = tmp_path / "bigproj"
    proj.mkdir()
    orig = inc.collect_index_relpaths
    try:
        inc.collect_index_relpaths = lambda *a, **k: {
            f"f{i}.py" for i in range(DEFAULT_MAX_TOUCH + 5)
        }
        # Not a broad root → confirm waives the cap as before (no raise).
        assert inc.preflight_index_scope(proj, confirm=True) == DEFAULT_MAX_TOUCH + 5
    finally:
        inc.collect_index_relpaths = orig


def test_index_file_hashes_skip_testdata(tmp_path: Path) -> None:
    from pipeline.indexer import _index_file_hashes
    from pipeline.ignore import clear_ignore_cache

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.py").write_text("x=1\n", encoding="utf-8")
    td = tmp_path / "testdata" / "fixture"
    td.mkdir(parents=True)
    for i in range(50):
        (td / f"f{i}.py").write_text(f"x={i}\n", encoding="utf-8")
    (tmp_path / ".scubieeignore").write_text("testdata/\n", encoding="utf-8")
    clear_ignore_cache()
    assert len(_index_file_hashes(tmp_path)) == 1
    assert preflight_index_scope(tmp_path, confirm=False) == 1

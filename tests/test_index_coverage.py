"""Fast-mode indexing must not silently skip whole top-level directories.

A repo's scripts/ and tests/ answer "how do we run or verify X". They were
missing from the fast roots, so 68 of this repo's 299 python files were
invisible to search while status still reported a healthy index.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.paths import collect_index_paths, fast_roots_from_env


def _write(root: Path, rel: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("def f():\n    return 1\n", encoding="utf-8")
    return p


def test_fast_mode_indexes_scripts_and_tests(tmp_path):
    for rel in (
        "packages/pkg/mod.py",
        "scripts/run_trial.py",
        "tests/test_mod.py",
        "tools/gen.py",
    ):
        _write(tmp_path, rel)

    found = {
        p.relative_to(tmp_path).as_posix() for p in collect_index_paths(tmp_path, fast=True)
    }
    assert "scripts/run_trial.py" in found
    assert "tests/test_mod.py" in found
    assert "tools/gen.py" in found
    assert "packages/pkg/mod.py" in found


def test_fast_mode_still_skips_vendored_and_generated_trees(tmp_path):
    for rel in (
        "packages/pkg/mod.py",
        "vendor/dep/mod.py",
        "out/build/mod.py",
        "research/notes.py",
    ):
        _write(tmp_path, rel)

    found = {
        p.relative_to(tmp_path).as_posix() for p in collect_index_paths(tmp_path, fast=True)
    }
    assert found == {"packages/pkg/mod.py"}


def test_copied_trees_do_not_re_enter_through_a_nested_root(tmp_path):
    # testdata/<copy>/packages/... duplicates the real source; matching a root
    # anywhere in the path made those copies 53% of this repo's index.
    _write(tmp_path, "packages/pkg/mod.py")
    _write(tmp_path, "testdata/work_copy/packages/pkg/mod.py")
    _write(tmp_path, "testdata/work_copy/scripts/run.py")

    found = {
        p.relative_to(tmp_path).as_posix()
        for p in collect_index_paths(tmp_path, fast=True, fast_roots=["packages", "scripts"])
    }
    assert found == {"packages/pkg/mod.py"}


def test_testdata_fixtures_skipped_by_default(tmp_path):
    # Indexing this monorepo with testdata/ as a fast root pulled 2k+ fixture
    # .py files and stalled at chunk before embed ever ran.
    _write(tmp_path, "packages/pkg/mod.py")
    _write(tmp_path, "testdata/frontend-mcp/src/app.py")
    _write(tmp_path, "scripts/run.py")

    found = {
        p.relative_to(tmp_path).as_posix() for p in collect_index_paths(tmp_path, fast=True)
    }
    assert found == {"packages/pkg/mod.py", "scripts/run.py"}
    assert not any(p.startswith("testdata/") for p in found)


def test_env_override_still_wins(monkeypatch):
    monkeypatch.setenv("CTX_FAST_ROOTS", "src,lib")
    assert fast_roots_from_env() == ("src/", "lib/")


def test_indexer_skips_ide_dotdirs_like_merkle(tmp_path):
    """Merkle skips all dotdirs; indexer must skip IDE trees or probe loops forever."""
    _write(tmp_path, "packages/pkg/mod.py")
    for rel in (
        ".kiro/specs/foo/bugfix.md",
        ".cursor/rules/x.md",
        ".codex/notes.md",
        ".cline/notes.md",
        ".roo/notes.md",
        ".amp/notes.md",
        ".continue/notes.md",
        ".claude/notes.md",
    ):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# ide\n", encoding="utf-8")

    found = {p.relative_to(tmp_path).as_posix() for p in collect_index_paths(tmp_path)}
    assert "packages/pkg/mod.py" in found
    assert not any(p.startswith(".") for p in found)

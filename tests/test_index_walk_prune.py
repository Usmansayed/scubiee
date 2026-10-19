"""Index walk pruning + graphify ignore fast paths must not change which files are collected."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

import pytest

from graphify import detect
from graphify.extract import collect_files
from pipeline.ignore import clear_ignore_cache, load_scubiee_ignore, should_index_rel
from pipeline.paths import collect_index_relpaths, index_dir_pruner


def _write(root: Path, rel: str, text: str = "x = 1\n") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _unpruned_relpaths(root: Path) -> set[str]:
    root = root.resolve()
    rules = load_scubiee_ignore(root)
    return {
        p.relative_to(root).as_posix()
        for p in collect_files(root, root=root)
        if should_index_rel(root, p.relative_to(root).as_posix(), rules=rules)
    }


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    clear_ignore_cache()
    _write(tmp_path, "src/app.py")
    _write(tmp_path, "src/deep/mod.py")
    _write(tmp_path, "testdata/fixture/copy.py")
    _write(tmp_path, "research/notes.py")
    _write(tmp_path, ".venv/lib/site.py")
    _write(tmp_path, "docs/guide.md", "# guide\n")
    _write(tmp_path, "build.log/inner.py")
    (tmp_path / ".gitignore").write_text("*.tmp\n!keep.tmp\ntestdata/\n", encoding="utf-8")
    return tmp_path


def test_prune_keeps_same_files_without_negation(tree: Path) -> None:
    (tree / ".scubieeignore").write_text("testdata/\nresearch/\n*.log\n", encoding="utf-8")
    clear_ignore_cache()
    got = collect_index_relpaths(tree)
    assert got == _unpruned_relpaths(tree)
    assert "src/app.py" in got and "src/deep/mod.py" in got
    assert not any(r.startswith(("testdata/", "research/", ".venv/", "build.log/")) for r in got)


def test_prune_skips_custom_rules_when_negation_present(tree: Path) -> None:
    (tree / ".scubieeignore").write_text("testdata/\n!testdata/fixture/copy.py\n", encoding="utf-8")
    clear_ignore_cache()
    rules = load_scubiee_ignore(tree.resolve())
    prune = index_dir_pruner(tree.resolve(), rules)
    assert prune(tree.resolve() / "testdata") is False
    assert prune(tree.resolve() / ".venv") is True
    assert collect_index_relpaths(tree) == _unpruned_relpaths(tree)


def test_pruner_never_prunes_root_or_outside(tree: Path) -> None:
    root = tree.resolve()
    prune = index_dir_pruner(root, load_scubiee_ignore(root))
    assert prune(root) is False
    assert prune(root.parent) is False


def test_rel_under_anchor_matches_pathlib(tmp_path: Path) -> None:
    anchor = tmp_path.resolve()
    cases = [anchor, anchor / "a", anchor / "a" / "b.py", anchor.parent, anchor.parent / "other" / "x.py"]
    for target in cases:
        try:
            want: str | None = str(target.relative_to(anchor)).replace(os.sep, "/")
        except ValueError:
            want = None
        s = str(target)
        assert detect._rel_under_anchor(s, os.path.normcase(s), anchor) == want


def test_rel_under_anchor_rejects_sibling_prefix(tmp_path: Path) -> None:
    anchor = (tmp_path / "pkg").resolve()
    sibling = (tmp_path / "pkg2" / "x.py").resolve()
    s = str(sibling)
    assert detect._rel_under_anchor(s, os.path.normcase(s), anchor) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows path case-insensitivity")
def test_rel_under_anchor_case_insensitive_on_windows(tmp_path: Path) -> None:
    anchor = tmp_path.resolve()
    target = Path(str(anchor).upper()) / "Sub" / "File.py"
    s = str(target)
    assert detect._rel_under_anchor(s, os.path.normcase(s), anchor) == "Sub/File.py"


def test_memoised_normcase_matches_fnmatch() -> None:
    names = ["Build.LOG", "src/App.py", "a/b/c.tmp", "keep.tmp", "Docs\\x.md"]
    pats = ["*.log", "src/*", "*.tmp", "KEEP.tmp", "docs/*"]
    for n in names:
        for p in pats:
            assert fnmatch.fnmatchcase(detect._nc(n), detect._nc(p)) == fnmatch.fnmatch(n, p)


def test_is_ignored_unchanged_semantics(tree: Path) -> None:
    root = tree.resolve()
    _write(root, "a/x.tmp")
    _write(root, "a/keep.tmp")
    patterns = detect._load_graphifyignore(root)
    assert detect._is_ignored(root / "a" / "x.tmp", root, patterns) is True
    assert detect._is_ignored(root / "a" / "keep.tmp", root, patterns) is False
    assert detect._is_ignored(root / "testdata" / "fixture" / "copy.py", root, patterns) is True
    assert detect._is_ignored(root / "src" / "app.py", root, patterns) is False

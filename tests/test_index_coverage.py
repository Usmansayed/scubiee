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


def test_scoped_roots_index_all_languages(tmp_path):
    """Scoped mode must keep TS/JS/Go — never Python-only (production polyglot)."""
    for rel, body in (
        ("packages/pkg/mod.py", "def f():\n    return 1\n"),
        ("packages/pkg/ui.ts", "export const x = 1;\n"),
        ("packages/pkg/svc.go", "package pkg\n"),
        ("other/skip.py", "def g():\n    pass\n"),
    ):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")

    found = {
        p.relative_to(tmp_path).as_posix()
        for p in collect_index_paths(tmp_path, fast=True, fast_roots=["packages"])
    }
    assert found == {
        "packages/pkg/mod.py",
        "packages/pkg/ui.ts",
        "packages/pkg/svc.go",
    }


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
    # Fast roots are prefix-anchored, so testdata/... never matches packages|/scripts/.
    # Project fixtures also belong in ``.scubieeignore`` for full (non-fast) scans.
    from pipeline.ignore import clear_ignore_cache

    _write(tmp_path, "packages/pkg/mod.py")
    _write(tmp_path, "testdata/frontend-mcp/src/app.py")
    _write(tmp_path, "scripts/run.py")
    (tmp_path / ".scubieeignore").write_text("testdata/\n", encoding="utf-8")
    clear_ignore_cache()

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


def test_binary_and_non_utf8_files_excluded(tmp_path):
    """A file with a source extension but binary / non-UTF-8 bytes must NOT be
    collected — it would otherwise reach the strict-utf-8 extractor and abort
    indexing for the WHOLE repo (bug-bounty finding #6)."""
    # good, decodable source files — must be kept
    (tmp_path / "good.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    (tmp_path / "cjk.py").write_text("def \u540d\u524d():\n    return 1\n", encoding="utf-8")
    (tmp_path / "bom.py").write_bytes(b"\xef\xbb\xbfdef bom():\n    return 1\n")
    # hostile files with a .py extension — must be excluded
    (tmp_path / "binary.py").write_bytes(bytes(range(256)) * 50)        # NUL bytes
    (tmp_path / "badenc.py").write_bytes(b"\xff\xfe\x80\x81def x(): pass")  # invalid utf-8
    (tmp_path / "empty.py").write_bytes(b"")                            # empty is fine

    found = {
        p.relative_to(tmp_path).as_posix()
        for p in collect_index_paths(tmp_path)
    }
    # decodable text is indexed
    assert "good.py" in found
    assert "cjk.py" in found
    assert "bom.py" in found
    assert "empty.py" in found
    # binary / non-utf-8 is excluded so it can't abort the whole index
    assert "binary.py" not in found
    assert "badenc.py" not in found


def test_is_probably_text_classifies_correctly(tmp_path):
    from pipeline.paths import _is_probably_text

    cases = {
        "a.py": (b"def ok(): return 1", True),
        "nul.py": (bytes(range(256)) * 10, False),
        "bad.py": (b"\xff\xfe\x80\x81x", False),
        "empty.py": (b"", True),
        "bom.py": (b"\xef\xbb\xbfdef f(): pass", True),
    }
    for name, (data, expected) in cases.items():
        p = tmp_path / name
        p.write_bytes(data)
        assert _is_probably_text(p) is expected, name


def test_exceeds_index_cap_early_exits_over_limit(tmp_path: Path) -> None:
    """Bounded cap check returns True past the cap without materialising all files."""
    from pipeline.paths import exceeds_index_cap

    for i in range(30):
        _write(tmp_path, f"src/f{i}.py")
    assert exceeds_index_cap(tmp_path, 10) is True
    assert exceeds_index_cap(tmp_path, 100) is False


def test_exceeds_index_cap_skips_ignored_dirs(tmp_path: Path) -> None:
    """node_modules / .git / .venv must not count toward the cap."""
    from pipeline.paths import exceeds_index_cap

    _write(tmp_path, "src/real.py")
    for i in range(50):
        _write(tmp_path, f"node_modules/pkg/j{i}.py")
        _write(tmp_path, f".venv/lib/v{i}.py")
    # Only src/real.py counts → nowhere near a cap of 10.
    assert exceeds_index_cap(tmp_path, 10) is False

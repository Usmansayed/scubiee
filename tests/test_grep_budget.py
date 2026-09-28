"""Regression: grep_scan must not let one oversized data file starve the scan.

Before the per-file line cap, a huge JSON/log sorted before real source consumed
the whole global line budget, so grep(**/*) returned 0 hits with a silent
``scan_incomplete`` even though the pattern existed in a later source file.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.capability import grep_scan, iter_glob_files


def _mk_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "aaa_data").mkdir(parents=True)
    (root / "zzz_src").mkdir(parents=True)
    # A big data file that sorts BEFORE the source file and, pre-fix, would eat
    # the whole line budget. 120k lines > default per-file cap (60k).
    big = root / "aaa_data" / "report.json"
    big.write_text("\n".join(f'  "k{i}": {i},' for i in range(120_000)), encoding="utf-8")
    # The real target, later in sorted order.
    src = root / "zzz_src" / "mod.py"
    src.write_text("def target_symbol():\n    return 1\n", encoding="utf-8")
    return root


def test_grep_reaches_source_past_large_data_file(tmp_path: Path) -> None:
    root = _mk_repo(tmp_path)
    files = iter_glob_files(root, "**/*")
    assert "zzz_src/mod.py" in files
    rep = grep_scan(root, r"def target_symbol", glob="**/*", max_hits=50)
    assert rep["count"] >= 1, rep
    assert not rep.get("scan_incomplete"), rep
    assert any(h["file"] == "zzz_src/mod.py" for h in rep["hits"]), rep


def test_grep_py_glob_finds_symbol(tmp_path: Path) -> None:
    root = _mk_repo(tmp_path)
    rep = grep_scan(root, r"def target_symbol", glob="**/*.py", max_hits=50)
    assert rep["count"] == 1, rep
    assert rep["hits"][0]["file"] == "zzz_src/mod.py"


def test_iter_glob_files_skips_ignored_dirs(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / ".venv" / "lib").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / ".venv" / "lib" / "junk.py").write_text("y = 2\n", encoding="utf-8")
    files = iter_glob_files(root, "**/*")
    assert "src/a.py" in files
    assert not any(f.startswith(".venv/") for f in files), files

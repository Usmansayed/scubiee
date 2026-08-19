from __future__ import annotations

from pathlib import Path

from pipeline.capability import grep_scan, path_glob_match
from pipeline.mcp_locate import _find_repo_files


def test_path_glob_match_double_star_nested() -> None:
    assert path_glob_match("docs/a/b.md", "**/*.md")
    assert path_glob_match("readme.md", "**/*.md")
    assert not path_glob_match("docs/a/b.py", "**/*.md")


def test_grep_honors_non_python_glob(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "note.md").write_text("token CeGrepMdOnly9910\n", encoding="utf-8")
    (tmp_path / "pkg" / "code.py").write_text("token CeGrepMdOnly9910\n", encoding="utf-8")

    py_only = grep_scan(tmp_path, "CeGrepMdOnly9910", glob="*.py", max_hits=20)
    md_only = grep_scan(tmp_path, "CeGrepMdOnly9910", glob="*.md", max_hits=20)

    assert py_only["hits"] and py_only["hits"][0]["path"].endswith("code.py")
    assert md_only["hits"] and md_only["hits"][0]["path"].endswith("note.md")
    assert py_only["truncated"] is False
    assert md_only["truncated"] is False


def test_grep_truncated_when_cap_hit(tmp_path: Path) -> None:
    src = tmp_path / "a.py"
    src.write_text("k=1\nk=2\nk=3\n", encoding="utf-8")
    report = grep_scan(tmp_path, r"k=", glob="*.py", max_hits=2)
    assert report["count"] == 2
    assert report["truncated"] is True
    assert report["has_more"] is True


def test_glob_collects_then_slices_truncated(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    (tmp_path / "top.md").write_text("x\n", encoding="utf-8")
    (nested / "deep.md").write_text("x\n", encoding="utf-8")
    found, truncated = _find_repo_files(tmp_path, "**/*.md", limit=1)
    assert truncated is True
    assert len(found) == 1
    found_all, truncated_all = _find_repo_files(tmp_path, "**/*.md", limit=10)
    assert truncated_all is False
    assert set(found_all) == {"top.md", "a/b/deep.md"}

"""Tests for pipeline.ignore — builtins, .scubieeignore, dirty filter, gate summary."""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.ignore import (
    BUILTIN_IGNORE_DIRS,
    agent_ignore_summary,
    clear_ignore_cache,
    filter_dirty_paths,
    format_gate_ignore_lines,
    is_junk_rel,
    should_index_rel,
)
from pipeline.merkle import scan_file_hashes


@pytest.fixture(autouse=True)
def _clear_ignore_cache():
    clear_ignore_cache()
    yield
    clear_ignore_cache()


def test_builtins_skip_node_modules_not_packages():
    assert not should_index_rel(None, "node_modules/left-pad/index.js")
    assert should_index_rel(None, "packages/pipeline/ignore.py")
    assert should_index_rel(None, "modules/foo/bar.py")
    assert "testdata" not in BUILTIN_IGNORE_DIRS
    assert "research" not in BUILTIN_IGNORE_DIRS


def test_testdata_util_filename_is_indexed():
    assert should_index_rel(None, "packages/foo/testdata_util.py")


def test_nested_testdata_needs_scubieeignore(tmp_path: Path):
    assert should_index_rel(tmp_path, "a/testdata/b.py")  # no ignore file yet
    (tmp_path / ".scubieeignore").write_text("testdata/\n", encoding="utf-8")
    clear_ignore_cache()
    assert not should_index_rel(tmp_path, "a/testdata/b.py")
    assert should_index_rel(tmp_path, "packages/foo/testdata_util.py")


def test_negation_cannot_override_builtin(tmp_path: Path):
    (tmp_path / ".scubieeignore").write_text("!node_modules/keep/x.py\n", encoding="utf-8")
    clear_ignore_cache()
    assert not should_index_rel(tmp_path, "node_modules/keep/x.py")


def test_negation_reincludes_custom(tmp_path: Path):
    (tmp_path / ".scubieeignore").write_text(
        "fixtures/\n!fixtures/keep/me.py\n",
        encoding="utf-8",
    )
    clear_ignore_cache()
    assert not should_index_rel(tmp_path, "fixtures/drop/x.py")
    assert should_index_rel(tmp_path, "fixtures/keep/me.py")


def test_filter_dirty_paths_reports_reason(tmp_path: Path):
    (tmp_path / ".scubieeignore").write_text("testdata/\n", encoding="utf-8")
    clear_ignore_cache()
    kept, dropped = filter_dirty_paths(
        tmp_path,
        [
            "packages/a.py",
            "testdata/probe.py",
            "node_modules/x.js",
            "packages/a.py",
        ],
    )
    assert kept == ["packages/a.py"]
    reasons = {d["path"]: d["reason"] for d in dropped}
    assert reasons["testdata/probe.py"] == "scubieeignore"
    assert reasons["node_modules/x.js"] == "builtin"


def test_scan_respects_scubieeignore(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.py").write_text("x=1\n", encoding="utf-8")
    td = tmp_path / "testdata" / "fixture"
    td.mkdir(parents=True)
    (td / "f0.py").write_text("x=0\n", encoding="utf-8")
    (tmp_path / ".scubieeignore").write_text("testdata/\n", encoding="utf-8")
    clear_ignore_cache()
    hashes = scan_file_hashes(tmp_path)
    rels = {k.replace("\\", "/") for k in hashes}
    assert rels == {"src/real.py"}


def test_scan_without_ignore_indexes_testdata(tmp_path: Path):
    """Fixtures are custom — without .scubieeignore they are indexable."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.py").write_text("x=1\n", encoding="utf-8")
    td = tmp_path / "testdata" / "fixture"
    td.mkdir(parents=True)
    (td / "f0.py").write_text("x=0\n", encoding="utf-8")
    hashes = scan_file_hashes(tmp_path)
    rels = {k.replace("\\", "/") for k in hashes}
    assert "src/real.py" in rels
    assert "testdata/fixture/f0.py" in rels


def test_dotdir_junk_and_github_allowlist():
    assert is_junk_rel(".zed/SCUBIEE_MCP_PERMISSIONS.md")
    assert is_junk_rel(".cursor/rules/x.md")
    assert not is_junk_rel(".github/workflows/ci.yml")


def test_agent_ignore_summary_and_gate_lines(tmp_path: Path):
    (tmp_path / ".scubieeignore").write_text("testdata/\nresearch/\n", encoding="utf-8")
    clear_ignore_cache()
    s = agent_ignore_summary(tmp_path)
    assert s["index_skip"] == "builtins+scubieeignore(n=2)"
    assert "packages/" in s["index_write_hint"]
    text = format_gate_ignore_lines(tmp_path)
    assert "index_skip:" in text
    assert "index_write_hint:" in text

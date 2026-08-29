"""Regression tests keyed to docs/scubiee-mcp-agent-evaluation.md P0–P2 issues."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.capability import truncation_meta
from pipeline.mcp_locate import (
    _call_sites_for_ident,
    _enrich_map_cards,
    _explicit_dot_dirs_in_pattern,
    _find_repo_files,
    _parse_call_sites_symbol,
    _read_line_range,
    _resolve_symbol_lines,
    create_mcp,
)


def _git_repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".git").mkdir()
    return root


def _enroll(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    ce = repo / ".scubiee"
    ce.mkdir()
    pid = "ce_eval1234567890abcdef12345678"
    (ce / "id.json").write_text(json.dumps({"project_id": pid}), encoding="utf-8")
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "paths": [str(repo.resolve())],
                }
            }
        }
    )
    monkeypatch.setenv("CTX_REPO", str(repo.resolve()))
    monkeypatch.chdir(repo)


def test_truncation_meta_includes_next_start_line() -> None:
    text = "line\n" * 100
    meta = truncation_meta(
        text,
        start_line=1,
        end_line=100,
        lines_total=100,
        max_chars=20,
        path="pkg/mod.py",
    )
    assert meta["truncated"] is True
    assert meta.get("next_start_line")
    assert "focus(path=" in meta.get("next", "")


def test_read_line_range_file_not_found(tmp_path: Path) -> None:
    out = _read_line_range(tmp_path, "missing.py", 1, 10, 1000)
    assert out.get("ok") is False
    assert "file not found" in out.get("error", "")


def test_resolve_symbol_lines_class_method(tmp_path: Path) -> None:
    f = tmp_path / "fair_schedule.py"
    f.write_text(
        "class FairEmbedScheduler:\n"
        "    def acquire(self, key: str) -> bool:\n"
        "        return True\n",
        encoding="utf-8",
    )
    rng = _resolve_symbol_lines(tmp_path, "fair_schedule.py", "FairEmbedScheduler.acquire")
    assert rng is not None
    start, end = rng
    assert start <= 2 <= end


def test_enrich_map_cards_large_span_hint() -> None:
    cards = [{"file": "a.py", "start_line": 1, "end_line": 500, "why": "big"}]
    out = _enrich_map_cards(cards)
    assert out[0].get("span_hint")
    assert out[0].get("display_end_line") == 121


def test_glob_ignores_worktrees(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("x=1\n", encoding="utf-8")
    wt = tmp_path / ".worktrees" / "wt" / "pkg"
    wt.mkdir(parents=True)
    (wt / "mod.py").write_text("y=2\n", encoding="utf-8")
    found, truncated = _find_repo_files(tmp_path, "**/mod.py", limit=10)
    assert len(found) == 1
    assert ".worktrees" not in found[0]
    assert truncated is False


def test_phase_surface_includes_expand(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    repo = _git_repo(tmp_path)
    _enroll(monkeypatch, repo)
    monkeypatch.setenv("CTX_MCP_SURFACE", "phase")
    monkeypatch.setattr("pipeline.mcp_locate._is_repo_managed", lambda: True)
    tools = set(create_mcp(name="eval-phase")._tool_manager._tools)
    assert "expand" in tools


def test_path_rank_penalty_deprioritizes_tests() -> None:
    from pipeline.locate import _path_rank_penalty

    assert _path_rank_penalty("tests/test_foo.py") < _path_rank_penalty("packages/pipeline/foo.py")


def test_call_sites_finds_usages_not_definitions(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "store.py").write_text(
        "def invalidate_paths(repo, paths):\n    return {}\n",
        encoding="utf-8",
    )
    (pkg / "sync.py").write_text(
        "from pkg.store import invalidate_paths\n\n"
        "def run():\n    invalidate_paths('r', [])\n",
        encoding="utf-8",
    )
    sites = _call_sites_for_ident(tmp_path, "invalidate_paths", keep=4)
    files = {s["file"].replace("\\", "/") for s in sites}
    assert any("sync.py" in f for f in files)
    assert all("why" not in s or s.get("why") == "call" for s in sites)


def test_parse_call_sites_symbol_file_colon_name() -> None:
    ident, scope = _parse_call_sites_symbol(
        query="", target="sync_loop.py:_invalidate_session_paths", path=""
    )
    assert ident == "_invalidate_session_paths"
    assert scope == "sync_loop.py"


def test_glob_explicit_dot_scubiee_dir(tmp_path: Path) -> None:
    ce = tmp_path / ".scubiee"
    ce.mkdir()
    (ce / "id.json").write_text('{"project_id": "ce_test"}\n', encoding="utf-8")
    assert ".scubiee" in _explicit_dot_dirs_in_pattern(".scubiee/**")
    found, truncated = _find_repo_files(tmp_path, ".scubiee/**", limit=10)
    assert any(f.endswith("id.json") for f in found)
    assert truncated is False


def test_default_repo_uses_last_managed_when_spawn_cwd_wrong(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """MCP spawn cwd (e.g. Miniconda3) must not flip managed:false after a bound call."""
    from pipeline import mcp_locate as ml

    repo = tmp_path / "proj"
    repo.mkdir()
    ce = repo / ".scubiee"
    ce.mkdir()
    pid = "ce_eval1234567890abcdef12345678"
    (ce / "id.json").write_text(json.dumps({"project_id": pid}), encoding="utf-8")
    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                pid: {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "paths": [str(repo.resolve())],
                    "lifecycle_state": "active",
                }
            }
        }
    )
    monkeypatch.delenv("CTX_REPO", raising=False)
    monkeypatch.delenv("CTX_PROJECT_ID", raising=False)
    monkeypatch.chdir(tmp_path)  # unenrolled cwd

    assert ml._is_repo_managed() is False
    with ml._bind_request_repo(project_id=pid):
        assert ml._is_repo_managed() is True
    assert ml._is_repo_managed() is True
    assert ml._default_repo().resolve() == repo.resolve()

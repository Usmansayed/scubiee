"""TDD: session store handles, dedup stubs, recall/expand."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "testdata" / "cursor_sdk_ab" / "work_d_channel_best_mcponly"


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    (root / ".context-engine").mkdir()
    src = root / "pkg"
    src.mkdir()
    f = src / "mod.py"
    f.write_text("def hello():\n    return 1\n\ndef world():\n    return 2\n", encoding="utf-8")
    monkeypatch.setenv("CTX_REPO", str(root))
    monkeypatch.setenv("CTX_TOKEN_MODE", "savings")
    yield root
    from pipeline.session_store import clear_store

    clear_store(root)


def test_put_span_returns_handle_and_stores_text(repo: Path):
    from pipeline.session_store import expand, put_span

    text = "def hello():\n    return 1\n"
    card = put_span(
        repo,
        path="pkg/mod.py",
        start_line=1,
        end_line=2,
        text=text,
        why="entry",
        source="test",
        excerpt_chars=40,
    )
    assert card["handle"].startswith("sp_")
    assert "text" not in card or not card.get("text")
    assert card["excerpt"]
    assert len(card["excerpt"]) <= 50
    body = expand(repo, card["handle"])
    assert body["ok"] is True
    assert "def hello" in body["text"]


def test_second_put_same_hash_returns_already_in_session(repo: Path):
    from pipeline.session_store import put_span

    text = "def hello():\n    return 1\n"
    a = put_span(repo, path="pkg/mod.py", start_line=1, end_line=2, text=text, why="a")
    b = put_span(repo, path="pkg/mod.py", start_line=1, end_line=2, text=text, why="b")
    assert a["handle"] == b["handle"]
    assert b["status"] == "already_in_session"
    assert b.get("excerpt") in (None, "", a.get("excerpt")) or "already" in str(b.get("hint", "")).lower()


def test_govern_targets_strips_full_excerpts_into_handles(repo: Path):
    from pipeline.session_store import govern_targets

    long_body = "def hello():\n    return 1\n\n" + ("x" * 200) + "\n\ndef world():\n    return 2\n"
    targets = [
        {
            "file": "pkg/mod.py",
            "start_line": 1,
            "end_line": 4,
            "role": "core",
            "why": "mod",
            "excerpt": long_body,
        }
    ]
    out = govern_targets(repo, targets, excerpt_chars=40)
    assert out[0]["handle"].startswith("sp_")
    assert "def world" not in (out[0].get("excerpt") or "")
    assert len(out[0].get("excerpt") or "") <= 50


def test_recall_lists_handles(repo: Path):
    from pipeline.session_store import put_span, recall

    put_span(repo, path="pkg/mod.py", start_line=1, end_line=2, text="abc", why="x", topic="auth flow")
    card = recall(repo, need="auth")
    assert card["ok"] is True
    assert card["spans"]
    assert card["spans"][0]["handle"].startswith("sp_")


def test_mcp_exposes_lean_surface(monkeypatch):
    pytest.importorskip("mcp")
    monkeypatch.setenv("CTX_MCP_SURFACE", "read")
    from pipeline.mcp_locate import create_mcp

    names = set(create_mcp()._tool_manager._tools)
    # Session reuse (recall/expand) is now folded INTO read's dedupe, not a tool.
    assert names == {"search", "read", "status"}


def test_mcp_phase_surface_exposes_locate_toolkit(monkeypatch):
    pytest.importorskip("mcp")
    monkeypatch.setenv("CTX_MCP_SURFACE", "phase")
    from pipeline.mcp_locate import create_mcp

    names = set(create_mcp()._tool_manager._tools)
    assert names == {
        "map",
        "focus",
        "grep",
        "glob",
        "workspace",
        "register_project",
        "status",
    }

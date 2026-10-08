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
    (root / ".scubiee").mkdir()
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


def test_session_ids_use_isolated_store_paths(repo: Path):
    from pipeline.session_store import put_span

    a = put_span(
        repo,
        path="pkg/mod.py",
        start_line=1,
        end_line=2,
        text="session-a",
        why="a",
        session_id="chat-a",
    )
    b = put_span(
        repo,
        path="pkg/mod.py",
        start_line=1,
        end_line=2,
        text="session-b",
        why="b",
        session_id="chat-b",
    )
    assert a["handle"] != b["handle"]


def test_map_v3_exposes_shipped_tool_surface():
    """Map V3 (pipeline.map_v3_server) ships exactly one lean tool surface.

    The old mcp_locate server switched tool sets by CTX_MCP_SURFACE (a "read"
    surface of {gate,search,read,status} and a "phase" surface of the 8-tool
    pack/expand toolkit). Both were retired in the Map V3 migration. Map V3
    exposes a single fixed surface — the four configs live under one `map`
    tool, not as separate tools — so this pins the shipped set to {map,gate,status}.
    See archive/old-mcp-map/ for the retired multi-surface server.
    """
    from pipeline.map_v3_server import CONFIGS, TOOLS

    assert set(TOOLS) == {"map", "gate", "status"}
    # The capabilities the old 8-tool surface spread across tools are folded into
    # the single map tool's configs. The shipped surface is find+focus (the
    # related/graph configs were retired in the Map V3 consolidation); assert the
    # actual shipped set so the suite tracks the real surface.
    assert set(CONFIGS) == {"find", "focus"}

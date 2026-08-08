"""Tests for the lean 3-tool MCP surface: search / read / status."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "testdata" / "cursor_sdk_ab" / "work_d_channel_best_mcponly"


def _tool_fn(mcp, name: str):
    return mcp._tool_manager._tools[name].fn


def _engine_up() -> bool:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    from pipeline import locate as loc
    from pipeline.work_session import clear_session

    loc._CACHE._data.clear()
    monkeypatch.setenv("CTX_REPO", str(WORK))
    if WORK.is_dir():
        clear_session(WORK)
    yield
    loc._CACHE._data.clear()
    if WORK.is_dir():
        clear_session(WORK)


def test_mcp_exposes_three_tools():
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    assert set(create_mcp()._tool_manager._tools) == {"search", "read", "status"}


def test_search_tool_flat_results(monkeypatch):
    pytest.importorskip("mcp")
    from pipeline import locate as loc
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setattr(
        loc,
        "_search_hits",
        lambda *_a, **_k: [
            {
                "file": "pkg/mod.py",
                "start_line": 10,
                "end_line": 24,
                "score": 0.91,
                "why": "defines focus",
                "query_match": 3,
            },
            {
                "file": "pkg/other.py",
                "start_line": 1,
                "end_line": 8,
                "score": 0.42,
                "why": "caller",
                "query_match": 1,
            },
        ],
    )
    monkeypatch.setattr(
        loc,
        "_read_excerpt",
        lambda *a, **k: {"ok": True, "excerpt": "def focus():\n    pass\n"},
    )
    search_fn = _tool_fn(create_mcp(), "search")

    thin = json.loads(search_fn(query="focus path query", k=5))
    assert thin["ok"] and thin["tool"] == "search"
    assert thin["k"] == 5 and thin["count"] == 2
    assert thin["results"][0]["rank"] == 1
    assert thin["results"][0]["file"] == "pkg/mod.py"
    assert "code" not in thin["results"][0]

    fat = json.loads(search_fn(query="focus path query", k=1, fetch=True))
    assert fat["count"] == 1
    assert fat["results"][0]["code"].startswith("def focus")


def test_read_resolves_top_hit_and_dedupes(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    from pipeline import locate as loc
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    monkeypatch.setattr(
        loc,
        "_search_hits",
        lambda *_a, **_k: [
            {
                "file": "pkg/mod.py",
                "start_line": 10,
                "end_line": 24,
                "score": 0.9,
                "why": "defines Foo",
                "query_match": 2,
            },
            {
                "file": "pkg/other.py",
                "start_line": 1,
                "end_line": 8,
                "score": 0.4,
                "why": "caller of Foo",
                "query_match": 1,
            },
        ],
    )
    monkeypatch.setattr(
        loc,
        "_read_excerpt",
        lambda *a, **k: {
            "ok": True,
            "path": "pkg/mod.py",
            "start_line": 10,
            "end_line": 24,
            "excerpt": "class Foo:\n    pass\n",
        },
    )
    read_fn = _tool_fn(create_mcp(), "read")

    first = json.loads(read_fn(target="Foo symbol"))
    assert first["ok"] and first["tool"] == "read"
    assert first["mode"] == "search"
    assert first["file"] == "pkg/mod.py"
    assert first["handle"]
    assert first["status"] == "stored"
    assert first["unchanged"] is False
    assert first["code"].startswith("class Foo")
    # doubles as a light search — surfaces alternative hits to pivot to
    assert first["alternatives"][0]["file"] == "pkg/other.py"

    # Re-reading the same span returns an "unchanged" stub (no resend).
    second = json.loads(read_fn(target="Foo symbol"))
    assert second["unchanged"] is True
    assert second["code"] == ""
    assert second["handle"] == first["handle"]

    # handle mode re-materializes the stored body.
    mat = json.loads(read_fn(handle=first["handle"]))
    assert mat["ok"] and mat["mode"] == "handle"
    assert mat["code"].startswith("class Foo")


def test_read_requires_a_locator():
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    read_fn = _tool_fn(create_mcp(), "read")
    err = json.loads(read_fn())
    assert err["ok"] is False
    assert "required" in err["error"].lower()


class _FakeEngine:
    def healthy(self) -> bool:
        return True

    def graph_neighbors(self, paths, **_kw):
        return {
            "ok": True,
            "spans": [
                {
                    "path": "pkg/caller.py",
                    "start_line": 1,
                    "end_line": 6,
                    "why": "calls Foo",
                    "text": "def uses():\n    return Foo()\n",
                }
            ],
        }

    def query_graph(self, question, **_kw):
        return {
            "ok": True,
            "spans": [
                {
                    "path": "pkg/mod.py",
                    "start_line": 10,
                    "end_line": 24,
                    "label": "Foo",
                    "text": "class Foo:\n    pass\n",
                }
            ],
        }

    def grep(self, pattern, **_kw):
        return {
            "ok": True,
            "pattern": pattern,
            "hits": [{"file": "pkg/mod.py", "line": 12, "text": "class Foo:"}],
        }

    def grep_ident(self, ident, **_kw):
        return {
            "ok": True,
            "spans": [
                {
                    "path": "pkg/caller.py",
                    "start_line": 2,
                    "end_line": 2,
                    "why": f"uses {ident}",
                    "text": "    return Foo()\n",
                }
            ],
        }

    def outline(self, path, **_kw):
        return {
            "ok": True,
            "path": path,
            "symbols": [
                {"name": "Foo", "kind": "class", "start_line": 10, "end_line": 24}
            ],
        }

    def follow_imports(self, path, **_kw):
        return {
            "ok": True,
            "spans": [
                {
                    "path": "pkg/dep.py",
                    "start_line": 1,
                    "end_line": 4,
                    "why": "imported by mod",
                    "text": "VALUE = 1\n",
                }
            ],
        }


def test_rich_surface_exposes_ten_tools(monkeypatch):
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setenv("CTX_MCP_SURFACE", "rich")
    assert set(create_mcp()._tool_manager._tools) == {
        "search",
        "grep",
        "usages",
        "read",
        "expand",
        "outline",
        "neighbors",
        "graph",
        "imports",
        "status",
    }


def test_search_only_surface(monkeypatch):
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setenv("CTX_MCP_SURFACE", "search")
    assert set(create_mcp()._tool_manager._tools) == {"search", "status"}


def test_grep_only_surface(monkeypatch):
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setenv("CTX_MCP_SURFACE", "grep")
    # grep-only surface has no semantic search — just grep + status.
    assert set(create_mcp()._tool_manager._tools) == {"grep", "status"}


def test_rich_tools_return_expected_shapes(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    import pipeline.client as pc
    import pipeline.daemon as pd
    from pipeline import locate as loc
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setenv("CTX_MCP_SURFACE", "rich")
    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    monkeypatch.setattr(pd, "ensure_daemon", lambda *a, **k: None)
    monkeypatch.setattr(pc, "EngineClient", lambda: _FakeEngine())
    monkeypatch.setattr(
        loc,
        "_search_hits",
        lambda *_a, **_k: [
            {"file": "pkg/mod.py", "start_line": 10, "end_line": 24, "score": 0.9, "why": "Foo"}
        ],
    )
    mcp = create_mcp()

    grep = json.loads(_tool_fn(mcp, "grep")(pattern="class Foo"))
    assert grep["ok"] and grep["hits"][0]["file"] == "pkg/mod.py"

    usages = json.loads(_tool_fn(mcp, "usages")(symbol="Foo"))
    assert usages["ok"] and usages["usages"][0]["file"] == "pkg/caller.py"

    outline = json.loads(_tool_fn(mcp, "outline")(path="pkg/mod.py"))
    assert outline["ok"] and outline["symbols"][0]["name"] == "Foo"

    imports = json.loads(_tool_fn(mcp, "imports")(path="pkg/mod.py"))
    assert imports["ok"] and imports["spans"][0]["file"] == "pkg/dep.py"


def test_graph_surface_swaps_tool_set(monkeypatch):
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setenv("CTX_MCP_SURFACE", "graph")
    assert set(create_mcp()._tool_manager._tools) == {
        "search",
        "neighbors",
        "graph",
        "status",
    }


def test_neighbors_and_graph_tools_return_spans(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    import pipeline.client as pc
    import pipeline.daemon as pd
    from pipeline import locate as loc
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setenv("CTX_MCP_SURFACE", "graph")
    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    monkeypatch.setattr(pd, "ensure_daemon", lambda *a, **k: None)
    monkeypatch.setattr(pc, "EngineClient", lambda: _FakeEngine())
    monkeypatch.setattr(
        loc,
        "_search_hits",
        lambda *_a, **_k: [
            {"file": "pkg/mod.py", "start_line": 10, "end_line": 24, "score": 0.9, "why": "Foo"}
        ],
    )

    mcp = create_mcp()
    nbr = json.loads(_tool_fn(mcp, "neighbors")(target="Foo"))
    assert nbr["ok"] and nbr["tool"] == "neighbors"
    assert nbr["file"] == "pkg/mod.py"
    assert nbr["neighbors"][0]["file"] == "pkg/caller.py"
    assert nbr["neighbors"][0]["code"].startswith("def uses")

    gph = json.loads(_tool_fn(mcp, "graph")(question="how does Foo get used"))
    assert gph["ok"] and gph["tool"] == "graph"
    assert gph["spans"][0]["file"] == "pkg/mod.py"
    assert gph["spans"][0]["why"] == "Foo"


def test_status_lists_three_tools(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    status_fn = _tool_fn(create_mcp(), "status")
    card = json.loads(status_fn())
    assert card["tool"] == "status"
    assert card["tools"] == ["search", "read", "status"]


def test_work_session_heatmap():
    from pipeline.work_session import clear_session, heatmap, touch

    clear_session(WORK)
    touch(WORK, ["a/shared_lease.py", "b/agent_guidance.py"], query="lease", weight=2)
    touch(WORK, ["a/shared_lease.py"], query="busy", weight=1)
    hot = heatmap(WORK, top_n=5)
    assert hot[0]["file"] == "a/shared_lease.py"
    assert hot[0]["hits"] >= 3


@pytest.mark.skipif(not WORK.is_dir(), reason="work missing")
@pytest.mark.skipif(not _engine_up(), reason="engine down")
def test_live_search_read_flow():
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp()
    search_fn = _tool_fn(mcp, "search")
    read_fn = _tool_fn(mcp, "read")

    res = json.loads(search_fn(query="shared chromium lease busy guidance", k=8))
    assert res["ok"] and res["results"]
    top = res["results"][0]["file"]

    opened = json.loads(read_fn(target=top))
    assert opened["ok"] and opened.get("handle")
    assert opened["file"]
    assert opened["status"] in {"stored", "already_in_session"}

    again = json.loads(read_fn(target=top))
    assert again["handle"] == opened["handle"]

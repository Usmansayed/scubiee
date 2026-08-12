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
    assert thin.get("include", "hits") == "hits"
    assert thin["results"][0]["rank"] == 1
    assert thin["results"][0]["file"] == "pkg/mod.py"
    assert "code" not in thin["results"][0]

    fat = json.loads(search_fn(query="focus path query", k=1, fetch=True))
    assert fat["count"] == 1
    assert fat.get("include") == "span"
    assert fat["results"][0]["code"].startswith("def focus")

    span = json.loads(search_fn(query="focus via include", k=2, include="span"))
    assert span["ok"] and span.get("include") == "span"
    assert span["results"][0]["code"].startswith("def focus")


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


def test_rich_surface_exposes_only_value_add_tools(monkeypatch):
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setenv("CTX_MCP_SURFACE", "rich")
    # Value-add only: meaning (search), the right span + graph (read/neighbors),
    # and structure (outline). grep/files were dropped — they only reroute native
    # grep/glob with no capability gain, so native handles those now.
    assert set(create_mcp()._tool_manager._tools) == {
        "search",
        "read",
        "outline",
        "status",
    }


def test_search_include_graph_attaches_neighbors(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    import pipeline.client as pc
    import pipeline.daemon as pd
    from pipeline import locate as loc
    from pipeline.mcp_locate import create_mcp
    from pipeline.session_store import clear_store

    monkeypatch.setenv("CTX_MCP_SURFACE", "search")
    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    clear_store(tmp_path)
    monkeypatch.setattr(pd, "ensure_daemon", lambda *a, **k: None)
    monkeypatch.setattr(pc, "EngineClient", lambda: _FakeEngine())
    monkeypatch.setattr(
        loc,
        "_search_hits",
        lambda *_a, **_k: [
            {"file": "pkg/mod.py", "start_line": 10, "end_line": 24, "score": 0.9, "why": "Foo"}
        ],
    )
    search_fn = _tool_fn(create_mcp(), "search")
    out = json.loads(search_fn(query="Who calls Foo?", include="graph", k=5))
    assert out["ok"] and out.get("include") == "graph"
    assert out["results"][0]["file"] == "pkg/mod.py"
    assert out["neighbors"][0]["file"] == "pkg/caller.py"
    assert out["neighbors_count"] == 1


def test_search_surface_blocks_exact_and_clamps_k(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    import pipeline.client as pc
    import pipeline.daemon as pd
    from pipeline import locate as loc
    from pipeline.mcp_locate import create_mcp
    from pipeline.session_store import clear_store

    monkeypatch.setenv("CTX_MCP_SURFACE", "search")
    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    clear_store(tmp_path)
    monkeypatch.setattr(pd, "ensure_daemon", lambda *a, **k: None)
    monkeypatch.setattr(pc, "EngineClient", lambda: _FakeEngine())
    monkeypatch.setattr(
        loc,
        "_search_hits",
        lambda *_a, **_k: [
            {"file": "pkg/a.py", "start_line": 1, "end_line": 2, "score": 0.9, "why": "hit"}
        ],
    )
    search_fn = _tool_fn(create_mcp(), "search")

    blocked = json.loads(search_fn(query="class Foo", mode="exact"))
    assert blocked.get("thrash_blocked") is True or blocked["ok"] is False
    assert "exact" in json.dumps(blocked).lower()

    soft = json.loads(search_fn(query="Where is auth wired?", k=25))
    assert soft["ok"] is True
    assert soft["k"] == 12  # clamped on search surface


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


def test_rich_surface_has_no_native_equivalent_tools(monkeypatch):
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setenv("CTX_MCP_SURFACE", "rich")
    # grep/files were intentionally dropped from the value-add surface — native
    # Grep/Glob handle exact strings and filenames, so the MCP no longer wraps
    # them (saves doc/context space).
    tools = set(create_mcp()._tool_manager._tools)
    assert "grep" not in tools and "files" not in tools


def test_read_explicit_line_range(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    src = "\n".join(f"line{i}" for i in range(1, 21)) + "\n"
    (tmp_path / "f.py").write_text(src, encoding="utf-8")
    monkeypatch.setenv("CTX_MCP_SURFACE", "rich")
    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    read_fn = _tool_fn(create_mcp(), "read")

    out = json.loads(read_fn(path="f.py", start_line=3, end_line=6))
    assert out["ok"] and out["mode"] == "lines"
    assert out["file"] == "f.py"
    assert "line3" in out["code"] and "line6" in out["code"]


def test_read_attaches_neighbors_when_requested(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    import pipeline.client as pc
    import pipeline.daemon as pd
    from pipeline.mcp_locate import create_mcp

    src = "\n".join(f"line{i}" for i in range(1, 21)) + "\n"
    (tmp_path / "f.py").write_text(src, encoding="utf-8")
    monkeypatch.setenv("CTX_MCP_SURFACE", "rich")
    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    monkeypatch.setattr(pd, "ensure_daemon", lambda *a, **k: None)
    monkeypatch.setattr(pc, "EngineClient", lambda: _FakeEngine())
    read_fn = _tool_fn(create_mcp(), "read")

    # graph rides inside read: neighbors=true attaches 1-hop callers/callees.
    out = json.loads(
        read_fn(path="f.py", start_line=3, end_line=6, neighbors=True, max_neighbors=2)
    )
    assert out["ok"]
    assert out["neighbors"][0]["file"] == "pkg/caller.py"
    assert out["neighbors_count"] == 1

    # off by default: no graph payload, so it costs nothing when unused.
    plain = json.loads(read_fn(path="f.py", start_line=8, end_line=9))
    assert plain["ok"] and "neighbors" not in plain


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

    # search (meaning) and outline (structure) are the value-add tools; grep/files
    # are gone from this surface.
    search = json.loads(_tool_fn(mcp, "search")(query="Foo", k=3))
    assert search["ok"] and search["results"][0]["file"] == "pkg/mod.py"

    outline = json.loads(_tool_fn(mcp, "outline")(path="pkg/mod.py"))
    assert outline["ok"] and outline["symbols"][0]["name"] == "Foo"


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


def test_nav_surface_active_and_instructions_budget(monkeypatch):
    """Sealed nav surface: six tools + ≤600 tok (~2400 char) anti-default instructions."""
    from pipeline import mcp_locate as ml

    monkeypatch.setenv("CTX_MCP_SURFACE", "nav")
    assert ml._active_surface() == "nav"
    text = ml.SERVER_INSTRUCTIONS_NAV
    assert ml._server_instructions("nav") == text
    assert len(text) <= 2400, f"nav instructions too long: {len(text)} chars"
    assert len(text) // 4 <= 600, f"nav instructions over ~600 tok: {len(text) // 4}"
    assert "search | files | read | recall | expand | status" in text
    assert "mode=exact" in text
    assert "recall" in text and "expand" in text
    assert "anti-thrash" in text.lower() or "Hard budgets" in text
    assert "Grep" in text and "IGNORE" in text
    assert "Soft ≤2" in text or "Soft <=2" in text
    assert "Exact ≤3" in text or "Exact <=3" in text
    assert "unchanged" in text.lower()


def test_nav_surface_exposes_six_tools(monkeypatch):
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setenv("CTX_MCP_SURFACE", "nav")
    tools = set(create_mcp()._tool_manager._tools)
    assert tools == {"search", "files", "read", "recall", "expand", "status"}
    assert "outline" not in tools and "grep" not in tools and "neighbors" not in tools


def test_nav_status_lists_six_tools(monkeypatch):
    pytest.importorskip("mcp")
    import pipeline.client as pc
    from pipeline.mcp_locate import create_mcp

    class _Ok:
        def healthy(self):
            return True

    monkeypatch.setenv("CTX_MCP_SURFACE", "nav")
    monkeypatch.setattr(pc, "EngineClient", lambda: _Ok())
    status_fn = _tool_fn(create_mcp(), "status")
    out = json.loads(status_fn())
    assert out["ok"] and out["surface"] == "nav"
    assert set(out["tools"]) == {"search", "files", "read", "recall", "expand", "status"}


def test_nav_files_and_recall_expand_smoke(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    from pipeline.mcp_locate import create_mcp
    from pipeline.session_store import put_span, clear_store

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("class Foo:\n    pass\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# hi\n", encoding="utf-8")
    monkeypatch.setenv("CTX_MCP_SURFACE", "nav")
    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    clear_store(tmp_path)
    mcp = create_mcp()
    files_fn = _tool_fn(mcp, "files")
    recall_fn = _tool_fn(mcp, "recall")
    expand_fn = _tool_fn(mcp, "expand")

    found = json.loads(files_fn(pattern="mod.py"))
    assert found["ok"] and found["tool"] == "files"
    assert any(p.endswith("mod.py") for p in found["files"])

    orient = json.loads(files_fn(pattern="."))
    assert orient["ok"] and (orient.get("files") or orient.get("dirs"))

    empty = json.loads(recall_fn())
    assert empty["ok"] and empty["tool"] == "recall"

    put_span(
        tmp_path,
        path="pkg/mod.py",
        start_line=1,
        end_line=2,
        text="class Foo:\n    pass\n",
        why="Foo",
    )
    # put_span may return handle differently — use recall list
    listed = json.loads(recall_fn(need="Foo"))
    assert listed["ok"]
    handles = [s.get("handle") for s in (listed.get("spans") or []) if s.get("handle")]
    assert handles
    opened = json.loads(expand_fn(handle=handles[0]))
    assert opened["ok"] and opened["tool"] == "expand"
    assert "Foo" in (opened.get("text") or opened.get("code") or "")


def test_search_mode_exact_returns_grep_hits(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    import pipeline.client as pc
    import pipeline.daemon as pd
    from pipeline import locate as loc
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setenv("CTX_MCP_SURFACE", "nav")
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
    search_fn = _tool_fn(create_mcp(), "search")

    soft = json.loads(search_fn(query="Foo", mode="soft", k=3))
    assert soft["ok"] and soft["tool"] == "search"
    assert soft.get("mode", "soft") == "soft"
    assert soft["results"][0]["file"] == "pkg/mod.py"
    assert "hits" not in soft

    exact = json.loads(search_fn(query="class Foo", mode="exact"))
    assert exact["ok"] and exact.get("mode") == "exact"
    assert exact["hits"][0]["file"] == "pkg/mod.py"
    assert exact["hits"][0]["line"] == 12
    assert "results" not in exact


def test_nav_search_thrash_gate_dedupes_and_caps(monkeypatch, tmp_path):
    """Nav surface: refuse duplicate queries and hard-cap soft/exact to cut token thrash."""
    pytest.importorskip("mcp")
    import pipeline.client as pc
    import pipeline.daemon as pd
    from pipeline import locate as loc
    from pipeline.mcp_locate import create_mcp
    from pipeline.session_store import clear_store

    monkeypatch.setenv("CTX_MCP_SURFACE", "nav")
    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    clear_store(tmp_path)
    monkeypatch.setattr(pd, "ensure_daemon", lambda *a, **k: None)
    monkeypatch.setattr(pc, "EngineClient", lambda: _FakeEngine())
    monkeypatch.setattr(
        loc,
        "_search_hits",
        lambda *_a, **_k: [
            {"file": "pkg/a.py", "start_line": 1, "end_line": 2, "score": 0.9, "why": "hit"}
        ],
    )
    search_fn = _tool_fn(create_mcp(), "search")

    first = json.loads(search_fn(query="Where is auth?", mode="soft"))
    assert first["ok"] is True and first.get("thrash_blocked") is not True

    dup = json.loads(search_fn(query="Where is auth?", mode="soft"))
    assert dup["ok"] is False or dup.get("thrash_blocked") is True
    assert "duplicate" in json.dumps(dup).lower() or "already" in json.dumps(dup).lower()

    # Burn remaining soft budget (cap=4 including first)
    for i in range(3):
        r = json.loads(search_fn(query=f"Where is topic {i}?", mode="soft"))
        assert r["ok"] is True, r

    capped = json.loads(search_fn(query="Where is one more soft?", mode="soft"))
    assert capped.get("thrash_blocked") is True or capped["ok"] is False
    blob = json.dumps(capped).lower()
    assert "edit" in blob or "budget" in blob or "cap" in blob

    for i in range(3):
        r = json.loads(search_fn(query=f"UNIQUE_TOKEN_{i}", mode="exact"))
        assert r["ok"] is True and r.get("mode") == "exact"

    exact_cap = json.loads(search_fn(query="UNIQUE_TOKEN_Z", mode="exact"))
    assert exact_cap.get("thrash_blocked") is True or exact_cap["ok"] is False


def test_read_detail_outline_and_neighbors(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    import pipeline.client as pc
    import pipeline.daemon as pd
    from pipeline.mcp_locate import create_mcp

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(
        "\n".join(f"line{i}" for i in range(1, 30)) + "\n", encoding="utf-8"
    )
    monkeypatch.setenv("CTX_MCP_SURFACE", "nav")
    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    monkeypatch.setattr(pd, "ensure_daemon", lambda *a, **k: None)
    monkeypatch.setattr(pc, "EngineClient", lambda: _FakeEngine())
    read_fn = _tool_fn(create_mcp(), "read")

    outline = json.loads(read_fn(path="pkg/mod.py", detail="outline"))
    assert outline["ok"] and outline.get("detail") == "outline"
    assert outline["symbols"][0]["name"] == "Foo"
    assert not (outline.get("code") or "").strip() or outline.get("mode") == "outline"

    nbr = json.loads(
        read_fn(path="pkg/mod.py", start_line=3, end_line=6, detail="neighbors", max_neighbors=2)
    )
    assert nbr["ok"]
    assert nbr["neighbors"][0]["file"] == "pkg/caller.py"


def test_server_instructions_are_short_grep_like_cards():
    """Always-on MCP instructions must stay under ~800 tokens (~3200 chars)."""
    from pipeline import mcp_locate as ml

    cards = {
        "read": ml.SERVER_INSTRUCTIONS_READ,
        "rich": ml.SERVER_INSTRUCTIONS_RICH,
        "search": ml.SERVER_INSTRUCTIONS_SEARCH,
        "graph": ml.SERVER_INSTRUCTIONS_GRAPH,
        "grep": ml.SERVER_INSTRUCTIONS_GREP,
        "nav": ml.SERVER_INSTRUCTIONS_NAV,
    }
    for name, text in cards.items():
        # Hard cap: <800 tokens ≈ 3200 chars (keep always-on tax bounded).
        # Sealed nav: ≤600 tok / 2400 chars — checked in nav-specific test too.
        cap = 2400 if name == "nav" else 3200
        assert len(text) <= cap, f"{name} instructions too long: {len(text)}"
        if name == "nav":
            assert "Need → one tool" in text or "Need → tool" in text
            assert "OVERRIDE" in text
            continue
        if name == "search":
            assert "WHEN →" in text
            assert "OVERRIDE" in text
            assert 'include="hits"' in text or "include=" in text
            assert "status()" in text
            assert len(text) <= 2200  # ≤~500–550 tok product card
            continue
        assert "Need → do this" in text or "Need → do this:" in text or name == "grep"
        assert "status()" in text or name == "grep"
    # Default / production lean card: CE-default locate; must read after search; Grep rare.
    assert "NEVER Grep first" in ml.SERVER_INSTRUCTIONS_READ
    assert "ALWAYS read" in ml.SERVER_INSTRUCTIONS_READ
    assert "Do not skip read" in ml.SERVER_INSTRUCTIONS_READ
    assert "new" in ml.SERVER_INSTRUCTIONS_READ and "test file" in ml.SERVER_INSTRUCTIONS_READ
    assert "fetch=false" in ml.SERVER_INSTRUCTIONS_READ
    assert "Grep-thrash" in ml.SERVER_INSTRUCTIONS_READ
    assert "search → read → edit" in ml.SERVER_INSTRUCTIONS_READ
    assert "search again" in ml.SERVER_INSTRUCTIONS_READ
    assert "≤2 Greps" in ml.SERVER_INSTRUCTIONS_READ or "<=2 Greps" in ml.SERVER_INSTRUCTIONS_READ
    assert "Grep ≪ 10%" in ml.SERVER_INSTRUCTIONS_READ or "Grep << 10%" in ml.SERVER_INSTRUCTIONS_READ
    assert "neighbors=true" in ml.SERVER_INSTRUCTIONS_READ
    assert "default code locate" in ml.SERVER_INSTRUCTIONS_READ
    assert ml._server_instructions("read") == ml.SERVER_INSTRUCTIONS_READ
    assert ml._server_instructions("rich") == ml.SERVER_INSTRUCTIONS_RICH
    assert ml._server_instructions("nav") == ml.SERVER_INSTRUCTIONS_NAV


def test_cursor_rule_mirrors_short_decision_card():
    rule = (REPO / ".cursor" / "rules" / "context-agent.mdc").read_text(encoding="utf-8")
    assert "default code locate" in rule
    assert "NEVER Grep first" in rule
    assert "ALWAYS" in rule and "read(target)" in rule
    assert "Need → do this" in rule
    assert "fetch=false" in rule
    assert "new test file" in rule.lower() or "new** test" in rule
    assert "search again" in rule
    assert "≤2 Greps" in rule or "<=2 Greps" in rule
    assert "Grep ≪ 10%" in rule or "Grep << 10%" in rule
    # Rule + frontmatter still under ~800 tokens budget with headroom.
    assert len(rule) <= 3200

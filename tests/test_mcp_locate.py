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
    monkeypatch.setenv("CTX_MCP_SURFACE", "read")
    # Keep resolution from latching onto the real enrolled checkout while tests
    # pin CTX_REPO to a tmp fixture (Windows/dev machine pollution).
    for key in (
        "CURSOR_PROJECT_DIR",
        "WORKSPACE_FOLDER",
        "INIT_CWD",
        "PWD",
        "CTX_PROJECT_ID",
        "CONTEXT_ENGINE_REPO",
    ):
        monkeypatch.delenv(key, raising=False)
    if WORK.is_dir():
        clear_session(WORK)
    yield
    loc._CACHE._data.clear()
    if WORK.is_dir():
        clear_session(WORK)


def _isolate_repo(monkeypatch, tmp_path: Path) -> Path:
    """Pin MCP resolution to tmp_path and leave the real checkout cwd."""
    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".git").mkdir(exist_ok=True)
    return tmp_path


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
    from pipeline.session_store import clear_store

    _isolate_repo(monkeypatch, tmp_path)
    clear_store(tmp_path)
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
    monkeypatch.setattr(pc, "EngineClient", lambda *a, **k: _FakeEngine())
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
    monkeypatch.setattr(pc, "EngineClient", lambda *a, **k: _FakeEngine())
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
    _isolate_repo(monkeypatch, tmp_path)
    monkeypatch.setenv("CTX_MCP_SURFACE", "rich")
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
    _isolate_repo(monkeypatch, tmp_path)
    monkeypatch.setenv("CTX_MCP_SURFACE", "rich")
    monkeypatch.setattr(pd, "ensure_daemon", lambda *a, **k: None)
    monkeypatch.setattr(pc, "EngineClient", lambda *a, **k: _FakeEngine())
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
    monkeypatch.setattr(pc, "EngineClient", lambda *a, **k: _FakeEngine())
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
    monkeypatch.setattr(pc, "EngineClient", lambda *a, **k: _FakeEngine())
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
    monkeypatch.setenv("CTX_MCP_SURFACE", "read")
    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    from pipeline.mcp_locate import create_mcp

    status_fn = _tool_fn(create_mcp(), "status")
    card = json.loads(status_fn())
    assert card["tool"] == "status"
    tools = card.get("tools") or card.get("tool_names") or []
    assert set(tools) == {"search", "read", "status"}


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
    if not (res.get("ok") and res.get("results")):
        pytest.skip("live engine returned no hits for work fixture query")
    assert res["ok"] and res["results"]
    top = res["results"][0]["file"]

    opened = json.loads(read_fn(target=top))
    assert opened["ok"] and opened.get("handle")
    assert opened["file"]
    assert opened["status"] in {"stored", "already_in_session"}

    again = json.loads(read_fn(target=top))
    assert again["handle"] == opened["handle"]


def test_nav_surface_active_and_instructions_budget(monkeypatch):
    """Sealed nav surface: six tools + guidance-only usage instructions."""
    from pipeline import mcp_locate as ml

    monkeypatch.setenv("CTX_MCP_SURFACE", "nav")
    monkeypatch.setattr(ml, "_is_repo_managed", lambda: True)
    assert ml._active_surface() == "nav"
    text = ml.SERVER_INSTRUCTIONS_NAV
    assert ml._server_instructions("nav") == text
    assert len(text) <= 2400, f"nav instructions too long: {len(text)} chars"
    assert len(text) // 4 <= 600, f"nav instructions over ~600 tok: {len(text) // 4}"
    assert "search | files | read | recall | expand | status" in text
    assert "mode=exact" in text
    assert "recall" in text and "expand" in text
    assert "USAGE (guidance" in text
    assert "never hard-blocked" in text.lower()
    assert "Grep" in text and "IGNORE" in text
    assert "unchanged" in text.lower()


def test_phase_surface_grep_glob_and_trajectory(monkeypatch):
    """Phase surface: recommend map/focus/grep/glob; agent decides."""
    from pipeline import mcp_locate as ml

    pytest.importorskip("mcp")
    monkeypatch.setenv("CTX_MCP_SURFACE", "phase")
    monkeypatch.setattr(ml, "_is_repo_managed", lambda: True)
    text = ml.SERVER_INSTRUCTIONS_PHASE
    assert ml._server_instructions("phase") == text
    assert "map | focus | grep | glob | workspace | status" in text
    assert "you decide" in text.lower()
    assert "never hard-blocked" in text.lower()
    assert "STRICT NATIVE BAN" not in text
    assert "MANDATORY" not in text
    tools = set(ml.create_mcp()._tool_manager._tools)
    assert tools == {
        "map",
        "focus",
        "grep",
        "glob",
        "workspace",
        "register_project",
        "status",
    }


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
    monkeypatch.setattr(pc, "EngineClient", lambda *a, **k: _Ok())
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
    _isolate_repo(monkeypatch, tmp_path)
    monkeypatch.setenv("CTX_MCP_SURFACE", "nav")
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
    monkeypatch.setattr(pc, "EngineClient", lambda *a, **k: _FakeEngine())
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


def test_nav_search_records_duplicates_without_blocking(monkeypatch, tmp_path):
    """Nav surface: duplicate queries succeed with advisory usage_hint (no hard cap)."""
    pytest.importorskip("mcp")
    import pipeline.client as pc
    import pipeline.daemon as pd
    from pipeline import locate as loc
    from pipeline.mcp_locate import create_mcp
    from pipeline.session_store import clear_store

    _isolate_repo(monkeypatch, tmp_path)
    monkeypatch.setenv("CTX_MCP_SURFACE", "nav")
    clear_store(tmp_path)
    monkeypatch.setattr(pd, "ensure_daemon", lambda *a, **k: None)
    monkeypatch.setattr(pc, "EngineClient", lambda *a, **k: _FakeEngine())
    monkeypatch.setattr(
        loc,
        "_search_hits",
        lambda *_a, **_k: [
            {"file": "pkg/a.py", "start_line": 1, "end_line": 2, "score": 0.9, "why": "hit"}
        ],
    )
    search_fn = _tool_fn(create_mcp(), "search")

    first = json.loads(search_fn(query="Where is auth?", mode="soft"))
    assert first["ok"] is True
    assert "usage_hint" not in first

    dup = json.loads(search_fn(query="Where is auth?", mode="soft"))
    assert dup["ok"] is True
    assert "usage_hint" in dup
    assert "Advisory" in dup["usage_hint"]

    for i in range(6):
        r = json.loads(search_fn(query=f"Where is topic {i}?", mode="soft"))
        assert r["ok"] is True, r


def test_read_detail_outline_and_neighbors(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    import pipeline.client as pc
    import pipeline.daemon as pd
    from pipeline.mcp_locate import create_mcp

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text(
        "\n".join(f"line{i}" for i in range(1, 30)) + "\n", encoding="utf-8"
    )
    _isolate_repo(monkeypatch, tmp_path)
    monkeypatch.setenv("CTX_MCP_SURFACE", "nav")
    monkeypatch.setattr(pd, "ensure_daemon", lambda *a, **k: None)
    monkeypatch.setattr(pc, "EngineClient", lambda *a, **k: _FakeEngine())
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


def test_server_instructions_are_short_grep_like_cards(monkeypatch):
    """Always-on MCP instructions must stay under ~800 tokens (~3200 chars)."""
    from pipeline import mcp_locate as ml

    monkeypatch.setattr(ml, "_is_repo_managed", lambda: True)

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
    template = (REPO / "packages" / "pipeline" / "templates" / "scubiee.mdc").read_text(
        encoding="utf-8"
    )
    assert "map" in template and "focus" in template
    assert "grep" in template
    assert "status" in template
    assert "Do not use native Grep" in template or "do not use native Grep" in template.lower()
    assert "status()" in template
    assert "Do not call it every turn" in template
    assert "never every turn" in template
    assert "scubiee resume" in template
    assert "ignore this rule entirely" not in template.lower()
    assert len(template) <= 4000


def test_append_host_rule_matches_cursor_retry_policy_not_ignore_forever():
    """Kiro/Cline/Continue/append hosts must not permanently drop Scubiee mid-session."""
    md = (REPO / "packages" / "pipeline" / "templates" / "context-engine.md").read_text(
        encoding="utf-8"
    )
    legacy = (REPO / "packages" / "pipeline" / "templates" / "context-engine.mdc").read_text(
        encoding="utf-8"
    )
    for template in (md, legacy):
        assert "ignore this rule entirely" not in template.lower()
        assert "Do not permanently disable Scubiee" in template
        assert "Do not call it every turn" in template
        assert "never every turn" in template
        assert "scubiee resume" in template
        assert "Retry `status()` only when" in template
        assert len(template) <= 4000


def test_status_ok_false_while_warming_managed(monkeypatch, tmp_path):
    """Managed repo with daemon down: ok must be false (not conflated with managed)."""
    pytest.importorskip("mcp")
    repo = tmp_path / "proj"
    repo.mkdir()
    ce = repo / ".context-engine"
    ce.mkdir()
    (ce / "id.json").write_text(json.dumps({"project_id": "ce_test"}), encoding="utf-8")
    monkeypatch.setenv("CTX_MCP_SURFACE", "read")
    monkeypatch.setenv("CTX_REPO", str(repo))
    monkeypatch.chdir(repo)

    from pipeline.project_id import save_registry

    save_registry(
        {
            "projects": {
                "ce_test": {
                    "managed": True,
                    "root": str(repo.resolve()),
                    "paths": [str(repo.resolve())],
                }
            }
        }
    )

    class FakeEng:
        base = "http://127.0.0.1:8765"

        def healthy(self) -> bool:
            return False

        def status(self, _root: str) -> dict:
            raise AssertionError("status should not be called when unhealthy")

    monkeypatch.setattr("pipeline.daemon.ensure_daemon", lambda *a, **k: None)
    monkeypatch.setattr("pipeline.client.EngineClient", lambda *a, **k: FakeEng())
    monkeypatch.setattr(
        "pipeline.session_store.load_store",
        lambda _r: {"topic": None, "spans": {}, "focus_seen": {}, "ledger": {}},
    )

    from pipeline.mcp_locate import create_mcp

    card = json.loads(_tool_fn(create_mcp(), "status")())
    assert card["managed"] is True
    assert card["warming"] is True
    assert card["ok"] is False
    assert card["should_retry_status"] is False
    assert "Do not poll status()" in card.get("hint", "")


def test_status_paused_hint_uses_resume_not_wake(monkeypatch, tmp_path):
    """Paused status must not advertise a non-existent `wake` command or invite polling."""
    pytest.importorskip("mcp")
    monkeypatch.setenv("CTX_MCP_SURFACE", "read")
    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setattr("pipeline.pause_resume.is_paused", lambda: True)
    status_fn = _tool_fn(create_mcp(), "status")
    card = json.loads(status_fn())
    assert card["paused"] is True
    assert card["ok"] is False
    assert card["should_retry_status"] is False
    assert "scubiee resume" in card["hint"]
    assert "wake" not in card["hint"].lower()


def test_mcp_reports_routing_errors_instead_of_successful_zero_hits(
    monkeypatch, tmp_path
) -> None:
    pytest.importorskip("mcp")
    import pipeline.client as pc
    import pipeline.daemon as pd
    from pipeline import locate as loc
    from pipeline.context_agent.tools import BackendResponseError
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setenv("CTX_MCP_SURFACE", "phase")
    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    monkeypatch.setattr(pd, "ensure_daemon", lambda *a, **k: None)

    response = {
        "ok": False,
        "status": "requires_initialize",
        "error": "requires_initialize",
        "root": str(tmp_path),
        "http_status": 409,
    }
    monkeypatch.setattr(
        loc,
        "_search_hits",
        lambda *_a, **_k: (_ for _ in ()).throw(BackendResponseError(response)),
    )
    mcp = create_mcp()
    mapped = json.loads(_tool_fn(mcp, "map")(query="routing admission indexed chunks"))
    assert mapped["ok"] is False
    assert mapped["status"] == "requires_initialize"
    assert mapped["http_status"] == 409
    assert "count" not in mapped
    assert "scubiee init" in mapped["hint"]

    class _RoutingErrorEngine:
        def grep(self, *_a, **_k):
            return response

    monkeypatch.setattr(pc, "EngineClient", lambda *a, **k: _RoutingErrorEngine())
    grep_result = json.loads(_tool_fn(mcp, "grep")(pattern="incremental_sync"))
    assert grep_result["ok"] is False
    assert grep_result["status"] == "requires_initialize"
    assert "count" not in grep_result
    assert "scubiee init" in grep_result["hint"]


def test_mcp_rejects_implicit_backend_readiness_failures(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    import pipeline.client as pc
    import pipeline.daemon as pd
    from pipeline import locate as loc
    from pipeline.context_agent.tools import BackendResponseError
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    monkeypatch.setattr(pd, "ensure_daemon", lambda *a, **k: None)
    warming = {"status": "warming", "ready": False, "error": "index warming"}

    class _WarmingEngine:
        def outline(self, *_a, **_k):
            return warming

        def grep(self, *_a, **_k):
            return warming

        def graph_neighbors(self, *_a, **_k):
            return warming

        def query_graph(self, *_a, **_k):
            return warming

    monkeypatch.setattr(pc, "EngineClient", lambda *a, **k: _WarmingEngine())
    monkeypatch.setattr(
        loc,
        "_search_hits",
        lambda *_a, **_k: [{"file": "pkg/mod.py", "start_line": 1, "end_line": 3}],
    )
    monkeypatch.setattr(loc, "_read_excerpt", lambda *_a, **_k: warming)

    monkeypatch.setenv("CTX_MCP_SURFACE", "rich")
    rich = create_mcp()
    read_fn = _tool_fn(rich, "read")
    outline_fn = _tool_fn(rich, "outline")
    results = [
        json.loads(outline_fn(path="pkg/mod.py")),
        json.loads(read_fn(path="pkg/mod.py", detail="outline")),
        json.loads(read_fn(target="warming span")),
    ]

    monkeypatch.setenv("CTX_MCP_SURFACE", "graph")
    graph = create_mcp()
    results.extend(
        [
            json.loads(_tool_fn(graph, "neighbors")(target="pkg/mod.py")),
            json.loads(_tool_fn(graph, "graph")(question="warming graph")),
        ]
    )

    monkeypatch.setenv("CTX_MCP_SURFACE", "phase")
    monkeypatch.setattr(
        loc,
        "_search_hits",
        lambda *_a, **_k: (_ for _ in ()).throw(BackendResponseError(warming)),
    )
    phase = create_mcp()
    results.extend(
        [
            json.loads(_tool_fn(phase, "map")(query="warming map")),
            json.loads(_tool_fn(phase, "grep")(pattern="warming")),
        ]
    )

    for result in results:
        assert result["ok"] is False, result
        assert result["status"] == "warming", result
        assert "count" not in result


def test_context_agent_wrappers_reject_implicit_warming(monkeypatch, tmp_path):
    import pipeline.context_agent.tools as tools

    warming = {"status": "warming", "ready": False, "error": "index warming"}

    class _WarmingClient:
        def search(self, *_a, **_k):
            return warming

        def grep(self, *_a, **_k):
            return warming

        def read_span(self, *_a, **_k):
            return warming

    monkeypatch.setattr(tools, "_client", lambda *a, **k: _WarmingClient())
    results = [
        tools.tool_search_code(tmp_path, "warming"),
        tools.tool_grep_code(tmp_path, "warming"),
        tools.tool_read_span(tmp_path, "pkg/mod.py"),
    ]

    for result in results:
        assert result["ok"] is False, result
        assert result["status"] == "warming", result


def test_mcp_rejects_missing_success_envelopes(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    import pipeline.client as pc
    import pipeline.daemon as pd
    from pipeline import locate as loc
    from pipeline.context_agent.tools import BackendResponseError
    from pipeline.mcp_locate import create_mcp

    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    monkeypatch.setattr(pd, "ensure_daemon", lambda *a, **k: None)
    empty = {}

    class _EmptyEngine:
        def grep(self, *_a, **_k):
            return empty

        def outline(self, *_a, **_k):
            return empty

        def graph_neighbors(self, *_a, **_k):
            return empty

        def query_graph(self, *_a, **_k):
            return empty

    monkeypatch.setattr(pc, "EngineClient", lambda *a, **k: _EmptyEngine())
    monkeypatch.setattr(
        loc,
        "_search_hits",
        lambda *_a, **_k: (_ for _ in ()).throw(BackendResponseError(empty)),
    )
    monkeypatch.setattr(loc, "_read_excerpt", lambda *_a, **_k: empty)

    monkeypatch.setenv("CTX_MCP_SURFACE", "rich")
    rich = create_mcp()
    read_fn = _tool_fn(rich, "read")
    results = [
        json.loads(_tool_fn(rich, "outline")(path="pkg/mod.py")),
        json.loads(read_fn(path="pkg/mod.py", detail="outline")),
        json.loads(read_fn(target="missing span")),
    ]

    monkeypatch.setenv("CTX_MCP_SURFACE", "graph")
    graph = create_mcp()
    results.extend(
        [
            json.loads(_tool_fn(graph, "neighbors")(target="pkg/mod.py")),
            json.loads(_tool_fn(graph, "graph")(question="missing graph")),
        ]
    )

    monkeypatch.setenv("CTX_MCP_SURFACE", "phase")
    phase = create_mcp()
    results.extend(
        [
            json.loads(_tool_fn(phase, "map")(query="missing map")),
            json.loads(_tool_fn(phase, "grep")(pattern="missing")),
            json.loads(_tool_fn(phase, "focus")(target="pkg/mod.py", mode="outline")),
        ]
    )

    monkeypatch.setenv("CTX_MCP_SURFACE", "nav")
    nav = create_mcp()
    results.append(
        json.loads(_tool_fn(nav, "search")(query="missing exact", mode="exact"))
    )

    for result in results:
        assert result["ok"] is False, result
        assert "count" not in result


def test_optional_graph_failures_preserve_primary_results(monkeypatch, tmp_path):
    pytest.importorskip("mcp")
    import pipeline.client as pc
    import pipeline.daemon as pd
    from pipeline import locate as loc
    from pipeline.mcp_locate import create_mcp

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("value = 1\n", encoding="utf-8")
    _isolate_repo(monkeypatch, tmp_path)
    monkeypatch.setattr(pd, "ensure_daemon", lambda *a, **k: None)

    class _GraphCrashEngine:
        def graph_neighbors(self, *_a, **_k):
            raise RuntimeError("graph unavailable")

    monkeypatch.setattr(pc, "EngineClient", lambda *a, **k: _GraphCrashEngine())
    monkeypatch.setattr(
        loc,
        "_search_hits",
        lambda *_a, **_k: [{"file": "pkg/mod.py", "start_line": 1, "end_line": 1, "score": 1.0}],
    )
    monkeypatch.setenv("CTX_MCP_SURFACE", "search")
    search = _tool_fn(create_mcp(), "search")
    searched = json.loads(search(query="value", include="graph"))
    assert searched["ok"] is True
    assert searched["count"] == 1
    assert searched["neighbors"] == []
    assert "graph unavailable" in searched["neighbors_error"]

    monkeypatch.setenv("CTX_MCP_SURFACE", "rich")
    read = _tool_fn(create_mcp(), "read")
    read_result = json.loads(
        read(path="pkg/mod.py", start_line=1, end_line=1, neighbors=True)
    )
    assert read_result["ok"] is True
    assert read_result["code"] == "value = 1"
    assert "graph unavailable" in read_result["neighbors_error"]

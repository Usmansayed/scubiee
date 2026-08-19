"""Tests for the CBM–CE hybrid MCP facade."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "testdata" / "cursor_sdk_ab" / "work_d_channel_best_mcponly"


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    from pipeline.session_store import clear_store
    from pipeline.work_session import clear_session

    monkeypatch.setenv("CTX_REPO", str(WORK if WORK.is_dir() else tmp_path))
    monkeypatch.delenv("CTX_CBM_BIN", raising=False)
    monkeypatch.delenv("CBM_BIN", raising=False)
    if WORK.is_dir():
        clear_session(WORK)
        clear_store(WORK)
    yield
    if WORK.is_dir():
        clear_session(WORK)
        clear_store(WORK)


def _tool_fn(mcp, name: str):
    return mcp._tool_manager._tools[name].fn


def test_instructions_under_600_tokens():
    from hybrid_cbm.instructions import SERVER_INSTRUCTIONS, instruction_token_estimate

    assert instruction_token_estimate() <= 600
    assert "search_graph" in SERVER_INSTRUCTIONS
    assert "Grep" in SERVER_INSTRUCTIONS or "grep" in SERVER_INSTRUCTIONS.lower()


def test_parse_cli_payload_success_and_error():
    from hybrid_cbm.proxy import parse_cli_payload

    ok = parse_cli_payload(
        json.dumps(
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"total": 1, "results": [{"name": "x"}]}),
                    }
                ]
            }
        )
    )
    assert ok["ok"] is True
    assert ok["total"] == 1

    err = parse_cli_payload(
        json.dumps(
            {
                "isError": True,
                "content": [{"type": "text", "text": "repo_path is required"}],
            }
        )
    )
    assert err["ok"] is False
    assert "repo_path" in err.get("error", "")


def test_null_proxy_clear_error():
    from hybrid_cbm.proxy import NullProxy

    out = NullProxy().call("search_graph", {"name_pattern": ".*"})
    assert out["ok"] is False
    assert "not found" in out["error"].lower()


def test_cli_proxy_allowlist(monkeypatch):
    from hybrid_cbm import proxy as px

    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))

        class R:
            returncode = 0
            stdout = json.dumps(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps({"total": 0, "results": []}),
                        }
                    ]
                }
            )
            stderr = ""

        return R()

    monkeypatch.setattr(px.subprocess, "run", fake_run)
    client = px.CliProxy("/fake/codebase-memory-mcp")
    bad = client.call("semantic_query", {"q": "x"})
    assert bad["ok"] is False
    assert "allowlisted" in bad["error"]

    good = client.call("search_graph", {"project": "p", "name_pattern": ".*"})
    assert good["ok"] is True
    assert calls and calls[0][1:3] == ["cli", "search_graph"]


def test_create_mcp_tool_surface():
    pytest.importorskip("mcp")
    from hybrid_cbm.server import create_mcp

    tools = set(create_mcp()._tool_manager._tools)
    assert tools == {
        "search",
        "search_graph",
        "trace_path",
        "get_code_snippet",
        "status",
    }


def test_search_returns_ce_shape(monkeypatch):
    pytest.importorskip("mcp")
    from hybrid_cbm.server import create_mcp
    from pipeline import locate as loc

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
            }
        ],
    )
    mcp = create_mcp()
    out = json.loads(_tool_fn(mcp, "search")(query="where is focus", k=5))
    assert out["ok"] is True
    assert out["backend"] == "ce"
    assert out["count"] == 1
    assert out["results"][0]["file"] == "pkg/mod.py"


def test_search_thrash_advises_duplicate_without_blocking(monkeypatch, tmp_path):
    from hybrid_cbm import semantic as sem
    from pipeline import locate as loc

    monkeypatch.setenv("CTX_REPO", str(tmp_path))
    monkeypatch.setattr(
        loc,
        "_search_hits",
        lambda *_a, **_k: [
            {"file": "a.py", "start_line": 1, "end_line": 2, "score": 1.0, "why": "x"}
        ],
    )
    first = sem.soft_search(tmp_path, "where is focus")
    assert first["ok"] is True
    second = sem.soft_search(tmp_path, "where is focus")
    assert second["ok"] is True
    assert "usage_hint" in second
    assert "Advisory" in second["usage_hint"]


def test_graph_tools_use_proxy(monkeypatch):
    pytest.importorskip("mcp")
    from hybrid_cbm import server as srv

    class FakeProxy:
        def available(self):
            return True

        def binary_path(self):
            return "/fake/cbm"

        def call(self, tool, arguments=None):
            return {"ok": True, "tool": tool, "arguments": arguments or {}, "total": 0}

    monkeypatch.setattr(srv, "make_proxy", lambda: FakeProxy())
    monkeypatch.setattr(srv, "resolve_project_name", lambda _p, _r: "proj")
    mcp = srv.create_mcp()
    sg = json.loads(_tool_fn(mcp, "search_graph")(name_pattern=".*Handler.*"))
    assert sg["ok"] is True
    assert sg["tool"] == "search_graph"
    assert sg["arguments"]["project"] == "proj"

    tp = json.loads(_tool_fn(mcp, "trace_path")(function_name="Handler"))
    assert tp["ok"] is True
    assert tp["arguments"]["function_name"] == "Handler"

    sn = json.loads(
        _tool_fn(mcp, "get_code_snippet")(qualified_name="proj.app.Handler")
    )
    assert sn["ok"] is True


def test_status_reports_missing_cbm(monkeypatch):
    pytest.importorskip("mcp")
    from hybrid_cbm import server as srv
    from hybrid_cbm.proxy import NullProxy

    monkeypatch.setattr(srv, "make_proxy", lambda: NullProxy())
    out = json.loads(_tool_fn(srv.create_mcp(), "status")())
    assert out["ok"] is True
    assert out["cbm"]["available"] is False

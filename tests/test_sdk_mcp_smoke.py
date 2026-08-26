from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "experiments" / "sdk_mcp_smoke.py"


def _load_smoke():
    spec = importlib.util.spec_from_file_location("sdk_mcp_smoke", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_configs_isolates_mcp_and_rule_sources(tmp_path):
    smoke = _load_smoke()
    if getattr(smoke, "StdioMcpServerConfig", None) is None:
        pytest.skip("cursor-sdk is not installed")
    graph = tmp_path / "graph.json"
    graph.write_text('{"nodes": [], "links": []}', encoding="utf-8")

    configs = smoke.build_configs(ROOT, tmp_path, Path(sys.executable), graph)

    # Legacy two arms plus the switchable CE surfaces (ce_read/graph/rich/search).
    assert {"context_engine", "graphify"} <= set(configs)
    assert set(configs["context_engine"].mcp_servers) == {"context-engine"}
    assert configs["context_engine"].setting_sources == ["project"]
    assert set(configs["graphify"].mcp_servers) == {"graphify"}
    assert configs["graphify"].setting_sources == ["project"]
    # Each ce_* arm is a Context Engine server pinned to its surface.
    for ce_name, surface in (
        ("ce_rich", "rich"),
        ("ce_search", "search"),
    ):
        cfg = configs[ce_name]
        assert set(cfg.mcp_servers) == {"context-engine"}
        assert cfg.mcp_servers["context-engine"].env["CTX_MCP_SURFACE"] == surface

    # graphify_grep pairs the graphify graph server with a grep-only CE server.
    gg = configs["graphify_grep"]
    assert set(gg.mcp_servers) == {"graphify", "context-engine"}
    assert gg.mcp_servers["context-engine"].env["CTX_MCP_SURFACE"] == "grep"


def test_normalize_message_extracts_tool_call_and_result():
    smoke = _load_smoke()
    event = smoke.normalize_message(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_call",
                        "name": "map",
                        "arguments": {"query": "lease"},
                    },
                    {
                        "type": "tool_result",
                        "name": "map",
                        "content": "packages/pipeline/session_store.py",
                    },
                ]
            },
        }
    )

    assert event["tool_calls"][0]["name"] == "map"
    assert "session_store.py" in event["tool_results"][0]["text"]


def test_normalize_message_parses_real_sdk_wire_envelopes():
    """Guard the exact shapes the bridge sends, via the SDK's own parser.

    The first live trial recorded 194 `tool_call` envelopes and parsed zero
    tool calls out of them, which made MCP attribution structurally impossible.
    Going through `sdk_message_from_json` means SDK shape drift fails here
    instead of silently zeroing out a multi-hour run.
    """
    sdk_types = pytest.importorskip("cursor_sdk.types")
    smoke = _load_smoke()

    tool_message = sdk_types.sdk_message_from_json(
        {
            "type": "tool_call",
            "agentId": "agent-1",
            "runId": "run-1",
            "callId": "call-1",
            "name": "map",
            "status": "completed",
            "args": {
                "providerIdentifier": "context-engine",
                "toolName": "map",
                "args": {"query": "focus path query"},
            },
            "result": {"content": [{"text": {"text": "locate.py"}}]},
        }
    )
    usage_message = sdk_types.sdk_message_from_json(
        {
            "type": "usage",
            "agentId": "agent-1",
            "runId": "run-1",
            "usage": {
                "inputTokens": 1200,
                "outputTokens": 340,
                "cacheReadTokens": 90,
                "cacheWriteTokens": 12,
                "totalTokens": 1642,
            },
        }
    )

    assert isinstance(tool_message, sdk_types.SDKToolUseMessage)
    assert isinstance(usage_message, sdk_types.SDKUsageMessage)

    tool_event = smoke.normalize_message(tool_message)
    usage_event = smoke.normalize_message(usage_message)

    assert tool_event["tool_calls"], "tool_call envelope must yield a tool call"
    assert tool_event["tool_calls"][0]["provider"] == "context-engine"
    assert tool_event["tool_calls"][0]["name"] == "map"
    assert tool_event["tool_calls"][0]["kind"] == "mcp"
    assert "locate.py" in tool_event["tool_results"][0]["text"]
    assert usage_event["usage"]["input_tokens"] == 1200
    assert usage_event["usage"]["output_tokens"] == 340


def test_normalize_message_attributes_native_tools_without_provider():
    sdk_types = pytest.importorskip("cursor_sdk.types")
    smoke = _load_smoke()

    message = sdk_types.sdk_message_from_json(
        {
            "type": "tool_call",
            "agentId": "agent-1",
            "runId": "run-1",
            "callId": "call-2",
            "name": "read",
            "status": "completed",
            "args": {"path": "packages/pipeline/locate.py"},
        }
    )
    event = smoke.normalize_message(message)

    assert event["tool_calls"][0]["provider"] == ""
    assert event["tool_calls"][0]["name"] == "read"

    outcome = smoke.evaluate_arm(
        "context_engine",
        [event],
        "done",
        "finished",
        True,
        1.0,
    )
    assert outcome["mcp_used"] is False


def test_normalize_message_handles_sdk_tool_use_and_usage_envelopes():
    smoke = _load_smoke()
    tool_event = smoke.normalize_message(
        {
            "type": "tool_call",
            "agent_id": "agent-1",
            "run_id": "run-1",
            "call_id": "call-1",
            "name": "map",
            "status": "completed",
            "args": {
                "providerIdentifier": "context-engine",
                "toolName": "map",
                "args": {"query": "focus path query"},
            },
            "result": {"content": [{"text": {"text": "hit"}}]},
        }
    )
    usage_event = smoke.normalize_message(
        {
            "type": "usage",
            "agent_id": "agent-1",
            "run_id": "run-1",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 4,
                "cache_read_tokens": 1,
                "cache_write_tokens": 0,
                "total_tokens": 15,
                "reasoning_tokens": None,
            },
        }
    )

    assert tool_event["tool_calls"][0]["provider"] == "context-engine"
    assert tool_event["tool_calls"][0]["name"] == "map"
    assert tool_event["tool_calls"][0]["kind"] == "mcp"
    assert tool_event["tool_results"][0]["text"] == "hit"
    assert usage_event["usage"]["total_tokens"] == 15


def test_context_engine_pass_requires_mcp_use_and_correct_answer():
    smoke = _load_smoke()
    result = smoke.evaluate_arm(
        "context_engine",
        [
            {
                "tool_calls": [
                    {
                        "name": "map",
                        "provider": "context-engine",
                        "kind": "mcp",
                        "arguments": {"query": "lease"},
                    }
                ],
                "tool_results": [
                    {
                        "name": "map",
                        "text": "packages/pipeline/session_store.py and locate.py",
                    }
                ],
            }
        ],
        "Handles are stored by session_store.py and created from locate.py.",
        "finished",
        True,
        100.0,
    )

    assert result["mcp_used"] is True
    assert result["rubric_pass"] is True
    assert result["smoke_pass"] is True


def test_zero_tool_call_is_recorded_as_failure():
    smoke = _load_smoke()
    result = smoke.evaluate_arm(
        "graphify",
        [],
        "I could not locate it.",
        "finished",
        True,
        100.0,
    )

    assert result["mcp_used"] is False
    assert result["smoke_pass"] is False


def test_report_discloses_equivalent_arm_specific_rules():
    smoke = _load_smoke()
    report = smoke.render_report(
        {
            "prompt": smoke.PROMPT,
            "arms": {
                "context_engine": {"smoke_pass": True},
                "graphify": {"smoke_pass": True},
            },
        }
    )

    assert "equivalent arm-specific" in report
    assert smoke.PROMPT in report


def test_repo_snapshot_changes_with_git_state(tmp_path, monkeypatch):
    smoke = _load_smoke()
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(smoke, "_git_bytes", lambda repo: b"before")
    before = smoke.repo_snapshot(tmp_path)
    monkeypatch.setattr(smoke, "_git_bytes", lambda repo: b"after")
    after = smoke.repo_snapshot(tmp_path)

    assert before != after


def test_load_cursor_api_key_accepts_lowercase_dotenv(tmp_path, monkeypatch):
    smoke = _load_smoke()
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    (tmp_path / ".env").write_text(
        "other=value\ncursor_api_key=test-secret\n",
        encoding="utf-8",
    )

    assert smoke.load_cursor_api_key(tmp_path) == "test-secret"


def test_observe_run_cancels_on_timeout():
    smoke = _load_smoke()

    class SlowRun:
        cancelled = False

        async def messages(self):
            await asyncio.sleep(1)
            if False:
                yield None

        async def wait(self):
            await asyncio.sleep(1)

        async def cancel(self):
            self.cancelled = True

    run = SlowRun()
    events, final_text, status, error = asyncio.run(
        smoke.observe_run(run, timeout_s=0.01)
    )

    assert events == []
    assert final_text == ""
    assert status == "timeout"
    assert "timed out" in error
    assert run.cancelled is True


def test_extract_conversation_distinguishes_mcp_from_native_tools():
    smoke = _load_smoke()
    conversation = [
        {
            "type": "agentConversationTurn",
            "turn": {
                "steps": [
                    {
                        "type": "toolCall",
                        "message": {
                            "type": "mcp",
                            "args": {
                                "providerIdentifier": "context-engine",
                                "toolName": "map",
                                "args": {"query": "handles"},
                            },
                            "result": {
                                "status": "success",
                                "value": {"content": [{"text": {"text": "hit"}}]},
                            },
                        },
                    },
                    {
                        "type": "toolCall",
                        "message": {
                            "type": "glob",
                            "args": {"globPattern": "**/*.py"},
                            "result": {"status": "success", "value": {"files": []}},
                        },
                    },
                ]
            },
        }
    ]

    event = smoke.extract_conversation_tools(conversation)

    assert event["tool_calls"][0]["provider"] == "context-engine"
    assert event["tool_calls"][0]["name"] == "map"
    assert event["tool_calls"][1]["kind"] == "glob"
    assert event["tool_results"][0]["text"] == "hit"

    outcome = smoke.evaluate_arm(
        "graphify",
        [{"tool_calls": [event["tool_calls"][1]], "tool_results": []}],
        "session_store.py uses handles",
        "finished",
        True,
        1.0,
    )
    assert outcome["mcp_used"] is False


def test_stage_retrieval_rule_is_arm_specific_and_restores_original(tmp_path):
    smoke = _load_smoke()
    rules = tmp_path / ".cursor" / "rules"
    rules.mkdir(parents=True)
    context_path = rules / "context-agent.mdc"
    graphify_path = rules / "graphify-agent.mdc"
    context_path.write_text("original-context", encoding="utf-8")

    with smoke.stage_retrieval_rule(tmp_path, "graphify"):
        assert not context_path.exists()
        assert "Graphify" in graphify_path.read_text(encoding="utf-8")

    assert context_path.read_text(encoding="utf-8") == "original-context"
    assert not graphify_path.exists()


def test_graphify_arm_fails_when_an_unexpected_mcp_provider_leaks_in():
    smoke = _load_smoke()
    result = smoke.evaluate_arm(
        "graphify",
        [
            {
                "tool_calls": [
                    {
                        "name": "query_graph",
                        "provider": "graphify",
                        "kind": "mcp",
                        "arguments": {},
                    },
                    {
                        "name": "search_code",
                        "provider": "context-engine",
                        "kind": "mcp",
                        "arguments": {},
                    },
                ],
                "tool_results": [],
            }
        ],
        "session_store.py stores handles used by locate.py.",
        "finished",
        True,
        1.0,
    )

    assert result["mcp_used"] is True
    assert result["unexpected_mcp_providers"] == ["context-engine"]
    assert result["smoke_pass"] is False


def test_engine_repo_match_is_path_normalized(tmp_path):
    smoke = _load_smoke()
    repo = tmp_path / "Repo"
    repo.mkdir()

    assert smoke.engine_repo_matches({"repo": str(repo)}, repo)
    assert not smoke.engine_repo_matches(
        {"repo": str(tmp_path / "different")},
        repo,
    )

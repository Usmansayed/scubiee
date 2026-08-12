from __future__ import annotations

import asyncio
import json
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "experiments" / "sdk_mcp_dev_trial.py"


def _load_trial():
    spec = importlib.util.spec_from_file_location("sdk_mcp_dev_trial", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_copy_workspace_creates_clean_independent_git_baseline(tmp_path):
    trial = _load_trial()
    source = tmp_path / "source"
    source.mkdir()
    (source / "packages").mkdir()
    (source / "packages" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / ".env").write_text("CURSOR_API_KEY=secret\n", encoding="utf-8")
    (source / ".context-engine").mkdir()
    (source / ".context-engine" / "session_store.json").write_text("{}")

    target = tmp_path / "arm"
    baseline = trial.copy_workspace(source, target)

    assert baseline
    assert (target / "packages" / "mod.py").read_text() == "VALUE = 1\n"
    assert not (target / ".env").exists()
    assert not (target / ".context-engine").exists()
    assert trial.git_diff(target) == ""

    (target / "packages" / "mod.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert "VALUE = 2" in trial.git_diff(target)
    assert (source / "packages" / "mod.py").read_text() == "VALUE = 1\n"


def test_source_tree_hash_unchanged_when_target_edited(tmp_path):
    trial = _load_trial()
    source = tmp_path / "source"
    source.mkdir()
    (source / "packages").mkdir()
    (source / "packages" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")

    before = trial.source_tree_hash(source)
    target = tmp_path / "arm"
    trial.copy_workspace(source, target)
    (target / "packages" / "mod.py").write_text("VALUE = 2\n", encoding="utf-8")

    assert trial.source_tree_hash(source) == before


def test_source_tree_hash_distinguishes_ambiguous_path_content_layouts(tmp_path):
    trial = _load_trial()
    repo_a = tmp_path / "a"
    repo_a.mkdir()
    (repo_a / "x").write_bytes(b"yz")
    repo_b = tmp_path / "b"
    repo_b.mkdir()
    (repo_b / "xy").write_bytes(b"z")

    assert trial.source_tree_hash(repo_a) != trial.source_tree_hash(repo_b)


def test_git_diff_includes_untracked_new_file(tmp_path):
    trial = _load_trial()
    source = tmp_path / "source"
    source.mkdir()
    (source / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")

    target = tmp_path / "arm"
    trial.copy_workspace(source, target)
    assert trial.git_diff(target) == ""

    new_file = target / "tests" / "test_regression.py"
    new_file.parent.mkdir()
    new_file.write_text("def test_fix():\n    assert True\n", encoding="utf-8")

    diff = trial.git_diff(target)
    assert "test_regression.py" in diff
    assert "test_fix" in diff


def test_git_uses_command_scoped_long_paths(monkeypatch, tmp_path):
    trial = _load_trial()
    captured = []

    def fake_run(command, **kwargs):
        captured.append((command, kwargs))
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(trial.subprocess, "run", fake_run)

    trial._git(tmp_path, "status", "--short")

    command, kwargs = captured[0]
    assert command == [
        "git",
        "-c",
        "core.longpaths=true",
        "status",
        "--short",
    ]
    assert kwargs["cwd"] == tmp_path


def test_untracked_diff_git_calls_use_command_scoped_long_paths(
    monkeypatch, tmp_path
):
    trial = _load_trial()
    (tmp_path / "new.py").write_text("VALUE = 1\n", encoding="utf-8")
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        if "ls-files" in command:
            return SimpleNamespace(stdout=b"new.py\0", returncode=0)
        return SimpleNamespace(stdout="untracked patch\n", returncode=1)

    monkeypatch.setattr(trial.subprocess, "run", fake_run)

    assert trial._untracked_diff(tmp_path) == "untracked patch\n"
    assert commands[0][:4] == [
        "git",
        "-c",
        "core.longpaths=true",
        "ls-files",
    ]
    assert commands[1][:4] == [
        "git",
        "-c",
        "core.longpaths=true",
        "diff",
    ]


def _valid_graphify_diff() -> str:
    # A complete multi-area feature diff: core module + new tests + >=2 wiring
    # surfaces (retrieval, MCP, docs) — matches the new implementation_present.
    # New tests must appear as brand-new (--- /dev/null); modified tests do not count.
    return (
        "diff --git a/packages/pipeline/query_expand.py "
        "b/packages/pipeline/query_expand.py\n"
        "diff --git a/packages/pipeline/locate.py b/packages/pipeline/locate.py\n"
        "diff --git a/packages/pipeline/mcp_locate.py "
        "b/packages/pipeline/mcp_locate.py\n"
        "diff --git a/tests/test_query_expand.py b/tests/test_query_expand.py\n"
        "--- /dev/null\n"
        "+++ b/tests/test_query_expand.py\n"
        "diff --git a/docs/query-expansion.md b/docs/query-expansion.md\n"
    )


def _valid_graphify_events() -> list[dict]:
    # CE/graphify arms require >=5 discovery MCP calls for mcp_used_enough.
    call = {
        "kind": "mcp",
        "provider": "graphify",
        "name": "query_graph",
        "arguments": {},
    }
    return [
        {"tool_calls": [call], "tool_results": []}
        for _ in range(5)
    ]


def _valid_usage_dict() -> dict:
    return {
        "input_tokens": 10,
        "output_tokens": 2,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "reasoning_tokens": None,
        "total_tokens": 12,
    }


def test_usage_dict_preserves_authoritative_sdk_fields():
    trial = _load_trial()
    usage = SimpleNamespace(
        input_tokens=1200,
        output_tokens=300,
        cache_read_tokens=700,
        cache_write_tokens=100,
        reasoning_tokens=50,
        total_tokens=2300,
    )

    assert trial.usage_dict(usage) == {
        "input_tokens": 1200,
        "output_tokens": 300,
        "cache_read_tokens": 700,
        "cache_write_tokens": 100,
        "reasoning_tokens": 50,
        "total_tokens": 2300,
    }


def test_usage_dict_returns_none_when_usage_absent():
    trial = _load_trial()

    assert trial.usage_dict(None) is None


def test_usage_dict_returns_none_for_incomplete_mapping():
    trial = _load_trial()

    assert trial.usage_dict({"input_tokens": 10}) is None


def test_shared_prompt_is_vague_and_discovery_bound(monkeypatch):
    monkeypatch.delenv("CTX_TRIAL_PROFILE", raising=False)
    monkeypatch.delenv("CTX_FRONTEND_PROMPT", raising=False)
    trial = _load_trial()
    # Force ce-profile prompt regardless of ambient env from other tests/shells.
    prompt = trial.CE_PROMPT
    # The prompt must describe the goal in human terms and force discovery.
    for marker in ("query expansion", "auth cfg", "camelCase", "turn it off"):
        assert marker in prompt
    # It must NOT hand the agent file paths or private symbols — that would
    # remove the discovery the MCP is meant to help with (the whole point).
    for leak in (
        "packages/pipeline/",
        "tests/test_query_expand.py",
        "docs/query-expansion.md",
        "_query_tokens",
        "_search_hits",
        "query_expand.py",
    ):
        assert leak not in prompt


def test_frontend_prompt_variants_are_vague_and_distinct():
    trial = _load_trial()
    assert set(trial.FRONTEND_PROMPTS) >= {
        "thrash",
        "degraded",
        "consistency",
        "combo",
    }
    for pid, prompt in trial.FRONTEND_PROMPTS.items():
        assert "don't know the layout" in prompt.lower()
        assert "docs" in prompt.lower()
        assert "test" in prompt.lower()
        for leak in ("src/navigation/mcp/tools.py", "dispatch_registry.py"):
            assert leak not in prompt, pid
    assert "code graph" in trial.FRONTEND_PROMPTS["thrash"].lower()
    assert "degraded" in trial.FRONTEND_PROMPTS["degraded"].lower()
    assert "consistency" in trial.FRONTEND_PROMPTS["consistency"].lower()
    combo = trial.FRONTEND_PROMPTS["combo"].lower()
    assert "code graph" in combo or "code-graph" in combo
    assert "consistency" in combo
    assert "new test file" in combo
    # Combo must be a heavier dual-feature ask than single-theme variants.
    assert len(trial.FRONTEND_PROMPTS["combo"]) > len(
        trial.FRONTEND_PROMPTS["consistency"]
    )


def test_arm_requires_expected_provider_usage_diff_and_passing_tests():
    trial = _load_trial()
    outcome = trial.evaluate_development_arm(
        name="graphify",
        status="finished",
        events=_valid_graphify_events(),
        usage=_valid_usage_dict(),
        diff_text=_valid_graphify_diff(),
        tests={"exit_code": 0, "passed": True},
    )

    assert outcome["expected_mcp_used"] is True
    assert outcome["unexpected_mcp_providers"] == []
    assert outcome["implementation_present"] is True
    assert outcome["quality_pass"] is True


def test_single_file_diff_is_not_implementation_present():
    trial = _load_trial()
    # Only the MCP wiring touched: no core module, no new tests -> not complete.
    partial = (
        "diff --git a/packages/pipeline/mcp_locate.py "
        "b/packages/pipeline/mcp_locate.py\n"
    )
    outcome = trial.evaluate_development_arm(
        name="graphify",
        status="finished",
        events=_valid_graphify_events(),
        usage=_valid_usage_dict(),
        diff_text=partial,
        tests={"exit_code": 0, "passed": True},
    )
    assert outcome["implementation_present"] is False
    assert outcome["quality_pass"] is False


def test_added_test_files_discovers_agent_named_tests():
    trial = _load_trial()
    diff = (
        "diff --git a/tests/test_query_expand.py b/tests/test_query_expand.py\n"
        "--- /dev/null\n"
        "+++ b/tests/test_query_expand.py\n"
        "diff --git a/tests/test_extra_thing.py b/tests/test_extra_thing.py\n"
        "--- /dev/null\n"
        "+++ b/tests/test_extra_thing.py\n"
        # Modified existing test must NOT count as a new test file.
        "diff --git a/tests/test_mcp_locate.py b/tests/test_mcp_locate.py\n"
        "--- a/tests/test_mcp_locate.py\n"
        "+++ b/tests/test_mcp_locate.py\n"
    )
    assert trial.added_test_files(diff) == [
        "tests/test_extra_thing.py",
        "tests/test_query_expand.py",
    ]
    assert trial.build_test_selection(["tests/test_query_expand.py"]) == [
        "tests/test_mcp_locate.py",
        "tests/test_query_expand.py",
        "--deselect",
        "tests/test_mcp_locate.py::test_live_map_focus_workspace_flow",
    ]


def test_evaluate_development_arm_accepts_raw_sdk_usage_object():
    trial = _load_trial()
    usage = SimpleNamespace(
        input_tokens=10,
        output_tokens=2,
        cache_read_tokens=0,
        cache_write_tokens=0,
        reasoning_tokens=None,
        total_tokens=12,
    )
    outcome = trial.evaluate_development_arm(
        name="graphify",
        status="finished",
        events=_valid_graphify_events(),
        usage=usage,
        diff_text=_valid_graphify_diff(),
        tests={"exit_code": 0, "passed": True},
    )

    assert outcome["usage"] == _valid_usage_dict()
    assert outcome["quality_pass"] is True


def test_evaluate_development_arm_rejects_incomplete_usage_mapping():
    trial = _load_trial()
    outcome = trial.evaluate_development_arm(
        name="graphify",
        status="finished",
        events=_valid_graphify_events(),
        usage={"input_tokens": 10},
        diff_text=_valid_graphify_diff(),
        tests={"exit_code": 0, "passed": True},
    )

    assert outcome["usage"] is None
    assert outcome["quality_pass"] is False


def test_mixed_mcp_and_native_call_classification():
    trial = _load_trial()
    outcome = trial.evaluate_development_arm(
        name="graphify",
        status="finished",
        events=[
            {
                "tool_calls": [
                    {
                        "kind": "mcp",
                        "provider": "graphify",
                        "name": "query_graph",
                        "arguments": {},
                    },
                    {
                        "kind": "mcp",
                        "provider": "context-engine",
                        "name": "map",
                        "arguments": {},
                    },
                    {
                        "kind": "native",
                        "name": "Read",
                        "arguments": {"path": "packages/pipeline/mcp_locate.py"},
                    },
                ],
                "tool_results": [],
            }
        ],
        usage=_valid_usage_dict(),
        diff_text=_valid_graphify_diff(),
        tests={"exit_code": 0, "passed": True},
    )

    assert outcome["mcp_call_names"] == ["query_graph", "map"]
    assert outcome["native_tool_names"] == ["Read"]
    assert outcome["expected_mcp_used"] is True
    assert outcome["quality_pass"] is False


def test_missing_usage_fails_quality():
    trial = _load_trial()
    outcome = trial.evaluate_development_arm(
        name="graphify",
        status="finished",
        events=_valid_graphify_events(),
        usage=None,
        diff_text=_valid_graphify_diff(),
        tests={"exit_code": 0, "passed": True},
    )

    assert outcome["quality_pass"] is False


def test_leaked_context_engine_provider_in_graphify_fails_quality():
    trial = _load_trial()
    outcome = trial.evaluate_development_arm(
        name="graphify",
        status="finished",
        events=[
            {
                "tool_calls": [
                    {
                        "kind": "mcp",
                        "provider": "graphify",
                        "name": "query_graph",
                        "arguments": {},
                    },
                    {
                        "kind": "mcp",
                        "provider": "context-engine",
                        "name": "map",
                        "arguments": {},
                    },
                ],
                "tool_results": [],
            }
        ],
        usage=_valid_usage_dict(),
        diff_text=_valid_graphify_diff(),
        tests={"exit_code": 0, "passed": True},
    )

    assert outcome["expected_mcp_used"] is True
    assert outcome["observed_providers"] == ["context-engine", "graphify"]
    assert outcome["quality_pass"] is False
    assert "context-engine" in outcome["unexpected_mcp_providers"]


def test_report_separates_input_output_and_renders_missing_usage_unavailable():
    trial = _load_trial()
    report = trial.render_report(
        {
            "prompt": trial.SHARED_PROMPT,
            "model": "composer-2.5",
            "sdk_version": "1.2.3",
            "source_tree_hash": "source-hash",
            "source_unchanged": True,
            "baseline_commits": {
                "context_engine": "ce-baseline",
                "graphify": "gf-baseline",
            },
            "workspaces": {
                "context_engine": "/tmp/context_engine",
                "graphify": "/tmp/graphify",
            },
            "arms": {
                "context_engine": {
                    "status": "finished",
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "cache_read_tokens": 0,
                        "cache_write_tokens": 0,
                        "reasoning_tokens": None,
                        "total_tokens": 120,
                    },
                    "tests": {"passed": True},
                    "quality_pass": True,
                    "expected_provider": "context-engine",
                    "observed_providers": ["context-engine"],
                },
                "graphify": {
                    "status": "timeout",
                    "usage": None,
                    "tests": {"passed": False},
                    "quality_pass": False,
                    "expected_provider": "graphify",
                    "observed_providers": [],
                    "warnings": ["timeout"],
                },
            },
        }
    )

    assert "| Input | Output |" in report
    assert "| 100 | 20 |" in report
    assert "unavailable" in report
    assert trial.SHARED_PROMPT in report
    assert "composer-2.5" in report
    assert "1.2.3" in report
    assert "source-hash" in report
    assert "ce-baseline" in report
    assert "gf-baseline" in report
    assert "/tmp/context_engine" in report
    assert "/tmp/graphify" in report
    assert "Source unchanged: True" in report
    assert "timeout" in report.lower()
    assert "graphify run incomplete (status=timeout)" in report


def test_report_warns_when_status_missing_or_empty():
    trial = _load_trial()
    report = trial.render_report(
        {
            "prompt": trial.SHARED_PROMPT,
            "model": "composer-2.5",
            "sdk_version": "1.2.3",
            "source_tree_hash": "source-hash",
            "baseline_commits": {
                "context_engine": "ce-baseline",
                "graphify": "gf-baseline",
            },
            "workspaces": {
                "context_engine": "/tmp/context_engine",
                "graphify": "/tmp/graphify",
            },
            "arms": {
                "context_engine": {
                    "status": "",
                    "usage": None,
                    "tests": {"passed": False},
                    "quality_pass": False,
                    "expected_provider": "context-engine",
                    "observed_providers": [],
                },
                "graphify": {
                    "usage": None,
                    "tests": {"passed": False},
                    "quality_pass": False,
                    "expected_provider": "graphify",
                    "observed_providers": [],
                },
            },
        }
    )

    assert "context_engine run incomplete (status=missing)" in report
    assert "graphify run incomplete (status=missing)" in report


def test_copy_workspace_excludes_experiment_control_artifacts(tmp_path):
    trial = _load_trial()
    source = tmp_path / "source"
    source.mkdir()
    (source / "product.py").write_text("VALUE = 1\n", encoding="utf-8")
    controls = source / ".superpowers"
    controls.mkdir()
    (controls / "task-3-brief.md").write_text("secret brief", encoding="utf-8")
    specs = source / "docs" / "superpowers" / "specs"
    specs.mkdir(parents=True)
    experiment = (
        specs
        / "2026-08-08-sdk-development-context-engine-vs-graphify-design.md"
    )
    experiment.write_text("experiment design", encoding="utf-8")

    target = tmp_path / "arm"
    trial.copy_workspace(source, target)

    assert (target / "product.py").is_file()
    assert not (target / ".superpowers").exists()
    assert not (
        target
        / "docs"
        / "superpowers"
        / "specs"
        / experiment.name
    ).exists()


def _terminal():
    return SimpleNamespace(
        status="finished",
        result="Implemented and tested.",
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=20,
            cache_read_tokens=40,
            cache_write_tokens=5,
            reasoning_tokens=None,
            total_tokens=165,
        ),
    )


def _mcp_conversation():
    return json.dumps(
        [
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
                                    "args": {"query": "focus"},
                                },
                            },
                        }
                    ]
                },
            }
        ]
    )


def test_observe_run_returns_terminal_usage_after_consuming_messages():
    trial = _load_trial()

    class FakeRun:
        waited = False
        usage = None

        async def messages(self):
            yield {"type": "assistant", "message": {"content": []}}

        async def wait(self):
            self.waited = True
            return _terminal()

        def supports(self, operation):
            return operation == "conversation"

        async def conversation_json(self):
            return "[]"

    run = FakeRun()
    observation = asyncio.run(trial.observe_run(run, 1))

    assert run.waited is True
    assert observation.terminal.usage.total_tokens == 165
    assert observation.error == ""
    assert observation.conversation_json == "[]"
    assert observation.usage["total_tokens"] == 165
    assert observation.usage_source == "run_result"
    assert observation.events[-1]["type"] == "conversation_tools"


def test_observe_run_idle_cancels_the_run_and_keeps_streamed_usage():
    trial = _load_trial()

    class FakeRun:
        cancelled = False
        # The SDK keeps summing streamed turn usage regardless of wait().
        usage = SimpleNamespace(
            input_tokens=900,
            output_tokens=120,
            cache_read_tokens=50,
            cache_write_tokens=10,
            reasoning_tokens=None,
            total_tokens=1080,
        )

        async def messages(self):
            yield {"type": "assistant", "message": {"content": []}}
            while not self.cancelled:
                await asyncio.sleep(0.01)

        async def wait(self):
            return SimpleNamespace(
                status="cancelled", result="", usage=None
            )

        async def cancel(self):
            self.cancelled = True

        def supports(self, operation):
            return operation == "conversation"

        async def conversation_json(self):
            return _mcp_conversation()

    run = FakeRun()
    observation = asyncio.run(
        trial.observe_run(run, 30, idle_timeout_s=0.05, heartbeat_s=0.05)
    )

    assert run.cancelled is True
    assert "idle for" in observation.error
    assert observation.usage["input_tokens"] == 900
    assert observation.usage_source == "run_property"
    assert observation.conversation_json
    assert observation.events[0]["type"] == "assistant"
    assert observation.events[-1]["type"] == "conversation_tools"
    assert observation.events[-1]["tool_calls"][0]["provider"] == "context-engine"


def test_observe_run_stops_on_terminal_status_without_cancelling():
    trial = _load_trial()

    class FakeRun:
        cancelled = False
        status = "running"
        usage = None

        async def messages(self):
            yield {"type": "assistant", "message": {"content": []}}
            self.status = "finished"
            yield {"type": "status", "status": "finished"}
            # The bridge keeps the stream open after the run is done.
            while True:
                await asyncio.sleep(0.01)

        async def wait(self):
            return _terminal()

        async def cancel(self):
            self.cancelled = True

        def supports(self, operation):
            return False

    run = FakeRun()
    observation = asyncio.run(
        trial.observe_run(run, 30, idle_timeout_s=30, heartbeat_s=30)
    )

    assert run.cancelled is False
    assert observation.stream_status == "finished"
    assert "finished" in observation.status_history
    assert observation.usage["total_tokens"] == 165
    assert trial._terminal_status(None, "", observation.stream_status) == "finished"


def test_observe_run_ceiling_cancels_the_run_not_the_consumer():
    trial = _load_trial()

    class FakeRun:
        cancelled = False
        usage = None

        async def messages(self):
            yield {"type": "assistant", "message": {"content": []}}
            while not self.cancelled:
                await asyncio.sleep(0.01)

        async def wait(self):
            return SimpleNamespace(
                status="cancelled",
                result="",
                usage=SimpleNamespace(
                    input_tokens=10,
                    output_tokens=2,
                    cache_read_tokens=0,
                    cache_write_tokens=0,
                    reasoning_tokens=None,
                    total_tokens=12,
                ),
            )

        async def cancel(self):
            self.cancelled = True

        def supports(self, operation):
            return False

    run = FakeRun()
    observation = asyncio.run(
        trial.observe_run(run, 0.05, idle_timeout_s=30, heartbeat_s=30)
    )

    assert run.cancelled is True
    assert "ceiling" in observation.error
    assert observation.usage["total_tokens"] == 12
    assert observation.usage_source == "run_result"


def test_observe_run_heartbeat_reports_progress():
    trial = _load_trial()
    beats = []

    class FakeRun:
        cancelled = False
        usage = None

        async def messages(self):
            yield {
                "type": "tool_call",
                "name": "map",
                "args": {
                    "providerIdentifier": "context-engine",
                    "toolName": "map",
                    "args": {},
                },
            }
            while not self.cancelled:
                await asyncio.sleep(0.01)

        async def wait(self):
            return SimpleNamespace(status="cancelled", result="", usage=None)

        async def cancel(self):
            self.cancelled = True

        def supports(self, operation):
            return False

    asyncio.run(
        trial.observe_run(
            FakeRun(),
            0.3,
            idle_timeout_s=30,
            heartbeat_s=0.05,
            on_heartbeat=beats.append,
        )
    )

    assert beats
    assert beats[-1]["events"] == 1
    assert beats[-1]["last_tool"] == "map"


def test_observe_run_finishes_via_wait_live_run_without_cancelling():
    trial = _load_trial()

    class FakeClient:
        # WaitLiveRun resolves on real completion, independent of the stream.
        async def wait_live_run(self, _run_id):
            return _terminal()

    class FakeRun:
        id = "run-live"
        status = "running"  # bridge never flips stream status to terminal
        usage = None
        cancelled = False
        client = FakeClient()

        async def messages(self):
            yield {"type": "assistant", "message": {"content": []}}
            # The send stream stays open after the agent has finished.
            while not self.cancelled:
                await asyncio.sleep(0.01)

        async def wait(self):
            raise AssertionError(
                "run.wait() must not be used when wait_live_run resolves"
            )

        async def cancel(self):
            self.cancelled = True

        def supports(self, operation):
            return False

    run = FakeRun()
    # Idle timeout is tiny on purpose: with an authoritative RPC signal, idle
    # silence must NOT trip a cancel.
    observation = asyncio.run(
        trial.observe_run(run, 30, idle_timeout_s=0.05, heartbeat_s=0.05)
    )

    assert run.cancelled is False
    assert observation.terminal is not None
    assert observation.terminal.status == "finished"
    assert observation.usage["total_tokens"] == 165
    assert observation.usage_source == "run_result"
    assert "idle for" not in observation.error
    assert "ceiling" not in observation.error


def test_observe_run_ceiling_still_cancels_even_with_live_waiter():
    trial = _load_trial()

    class FakeRun:
        id = "run-stuck"
        status = "running"
        usage = SimpleNamespace(
            input_tokens=10,
            output_tokens=2,
            cache_read_tokens=0,
            cache_write_tokens=0,
            reasoning_tokens=None,
            total_tokens=12,
        )
        cancelled = False

        async def messages(self):
            yield {"type": "assistant", "message": {"content": []}}
            while not self.cancelled:
                await asyncio.sleep(0.01)

        async def cancel(self):
            self.cancelled = True

        def supports(self, operation):
            return False

    run = FakeRun()

    class FakeClient:
        # Never resolves on its own; like the real server, it returns a terminal
        # result once the run is cancelled by the ceiling watchdog.
        async def wait_live_run(self, _run_id):
            while not run.cancelled:
                await asyncio.sleep(0.01)
            return SimpleNamespace(status="cancelled", result="", usage=run.usage)

    run.client = FakeClient()
    observation = asyncio.run(
        trial.observe_run(run, 0.1, idle_timeout_s=30, heartbeat_s=30)
    )

    assert run.cancelled is True
    assert "ceiling" in observation.error
    assert observation.usage["total_tokens"] == 12


def test_observe_run_polls_get_run_when_wait_would_block(monkeypatch):
    # Long runs make the blocking WaitLiveRun unary exceed the bridge read
    # timeout. The harness must poll GetRun for status and only call
    # WaitLiveRun once the run is already terminal.
    trial = _load_trial()
    monkeypatch.setattr(trial, "TERMINAL_POLL_S", 0.01)

    class Snap:
        def __init__(self, status):
            self.status = status

    class FakeClient:
        def __init__(self):
            self.get_calls = 0
            self.wait_calls = 0

        async def get_run(self, _run_id):
            self.get_calls += 1
            # Running for a couple of polls, then terminal.
            return Snap("running" if self.get_calls < 3 else "finished")

        async def wait_live_run(self, _run_id):
            self.wait_calls += 1
            return _terminal()

    client = FakeClient()

    class FakeRun:
        id = "run-long"
        status = "running"
        usage = None
        cancelled = False

        async def messages(self):
            yield {"type": "assistant", "message": {"content": []}}
            while not self.cancelled:
                await asyncio.sleep(0.01)

        async def wait(self):
            raise AssertionError("run.wait() must not be used when polling GetRun")

        async def cancel(self):
            self.cancelled = True

        def supports(self, operation):
            return False

    run = FakeRun()
    run.client = client
    observation = asyncio.run(
        trial.observe_run(run, 30, idle_timeout_s=0.05, heartbeat_s=0.05)
    )

    assert run.cancelled is False  # authoritative finish via polling, no cancel
    assert client.get_calls >= 3  # polled until terminal
    assert client.wait_calls == 1  # single WaitLiveRun only after terminal
    assert observation.terminal is not None
    assert observation.terminal.status == "finished"
    assert observation.usage["total_tokens"] == 165
    assert observation.usage_source == "run_result"
    assert "idle for" not in observation.error
    assert "ceiling" not in observation.error


def _install_fake_cursor_sdk(monkeypatch):
    sdk = ModuleType("cursor_sdk")

    class Options:
        def __init__(self, **kwargs):
            vars(self).update(kwargs)

    sdk.AgentOptions = Options
    sdk.LocalAgentOptions = Options
    sdk.SendOptions = Options
    monkeypatch.setitem(sys.modules, "cursor_sdk", sdk)
    return sdk


def test_run_arm_send_options_replace_mcp_servers(monkeypatch, tmp_path):
    trial = _load_trial()
    _install_fake_cursor_sdk(monkeypatch)
    terminal = _terminal()
    captured = {}

    class FakeRun:
        id = "run-1"

        async def messages(self):
            if False:
                yield None

        async def wait(self):
            return terminal

        def supports(self, operation):
            return False

    class FakeAgent:
        agent_id = "agent-1"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def send(self, prompt, options):
            captured["prompt"] = prompt
            captured["send_options"] = options
            return FakeRun()

    class FakeClient:
        async def create_agent(self, options):
            captured["agent_options"] = options
            return FakeAgent()

    config = SimpleNamespace(
        name="graphify",
        mcp_servers={"graphify": object()},
        setting_sources=["project"],
    )
    monkeypatch.setattr(trial, "git_diff", lambda _workspace: _valid_graphify_diff())
    monkeypatch.setattr(
        trial,
        "run_post_tests",
        lambda *_args, **_kwargs: {"exit_code": 0, "passed": True},
    )

    outcome = asyncio.run(
        trial.run_arm(FakeClient(), config, tmp_path, "composer-2.5", 1)
    )

    assert captured["prompt"] == trial.SHARED_PROMPT
    assert captured["agent_options"].mcp_servers is config.mcp_servers
    assert captured["send_options"].mcp_servers is config.mcp_servers
    assert outcome["agent_id"] == "agent-1"
    assert outcome["run_id"] == "run-1"
    assert outcome["usage"]["total_tokens"] == 165
    assert outcome["usage_source"] == "run_result"


def test_run_arm_uses_non_default_source_for_post_tests(
    monkeypatch, tmp_path
):
    trial = _load_trial()
    _install_fake_cursor_sdk(monkeypatch)
    captured = {}

    class FakeRun:
        id = "run-custom-source"

        async def messages(self):
            if False:
                yield None

        async def wait(self):
            return _terminal()

        def supports(self, operation):
            return False

    class FakeAgent:
        agent_id = "agent-custom-source"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def send(self, _prompt, _options):
            return FakeRun()

    class FakeClient:
        async def create_agent(self, _options):
            return FakeAgent()

    config = SimpleNamespace(
        name="graphify",
        mcp_servers={"graphify": object()},
        setting_sources=["project"],
    )
    source = tmp_path / "alternate-source"
    python = source / ".venv" / "Scripts" / "python.exe"
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(trial, "git_diff", lambda _workspace: "")

    def fake_post_tests(actual_workspace, actual_python, actual_source, **kwargs):
        captured["arguments"] = (
            actual_workspace,
            actual_python,
            actual_source,
        )
        captured["arm"] = kwargs.get("arm")
        return {"exit_code": 0, "passed": True}

    monkeypatch.setattr(trial, "run_post_tests", fake_post_tests)

    asyncio.run(
        trial.run_arm(
            FakeClient(),
            config,
            workspace,
            "composer-2.5",
            1,
            source=source,
            python=python,
        )
    )

    assert captured["arguments"] == (workspace, python, source)
    assert captured["arm"] == "graphify"


def test_run_post_tests_maps_success_and_failure_metadata(monkeypatch, tmp_path):
    trial = _load_trial()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    python = tmp_path / ".venv" / "Scripts" / "python.exe"
    root = tmp_path / "source"
    calls = []
    monkeypatch.setattr(
        trial.smoke,
        "ensure_engine_repo",
        lambda repo: calls.append(("engine", repo)),
    )
    results = iter(
        [
            SimpleNamespace(returncode=0, stdout="1 passed", stderr=""),
            SimpleNamespace(returncode=1, stdout="", stderr="1 failed"),
        ]
    )

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return next(results)

    monkeypatch.setattr(trial.subprocess, "run", fake_run)
    success = trial.run_post_tests(workspace, python, root)
    failure = trial.run_post_tests(workspace, python, root)

    assert success["passed"] is True
    assert success["exit_code"] == 0
    assert failure["passed"] is False
    assert failure["exit_code"] == 1
    command, kwargs = calls[1]
    assert command == [
        str(python),
        "-m",
        "pytest",
        "tests/test_mcp_locate.py",
        "--deselect",
        "tests/test_mcp_locate.py::test_live_map_focus_workspace_flow",
        "-q",
    ]
    assert kwargs["cwd"] == workspace
    assert kwargs["env"]["PYTHONPATH"] == str(workspace / "packages")
    assert kwargs["env"]["PYTHONUTF8"] == "1"


def test_run_post_tests_only_repoints_engine_for_context_engine_arm(
    monkeypatch, tmp_path
):
    trial = _load_trial()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    engine_calls = []
    monkeypatch.setattr(
        trial.smoke,
        "ensure_engine_repo",
        lambda repo: engine_calls.append(repo),
    )
    monkeypatch.setattr(
        trial.subprocess,
        "run",
        lambda command, **kwargs: SimpleNamespace(
            returncode=0, stdout="", stderr=""
        ),
    )

    trial.run_post_tests(workspace, tmp_path / "py.exe", tmp_path, arm="graphify")
    assert engine_calls == []

    trial.run_post_tests(
        workspace, tmp_path / "py.exe", tmp_path, arm="context_engine"
    )
    assert engine_calls == [workspace]


def test_run_trial_persists_both_arms_and_preserves_source(
    monkeypatch, tmp_path
):
    trial = _load_trial()
    monkeypatch.delenv("CTX_TRIAL_FORCE_SURFACE", raising=False)
    monkeypatch.setenv("CTX_TRIAL_PROFILE", "ce")
    source = tmp_path / "source"
    source.mkdir()
    (source / "product.py").write_text("VALUE = 1\n", encoding="utf-8")
    output = tmp_path / "output"
    original_hash = trial.source_tree_hash(source)
    configs = {
        name: SimpleNamespace(
            name=name,
            mcp_servers={name: object()},
            setting_sources=["project"],
        )
        for name in ("context_engine", "graphify")
    }
    monkeypatch.setattr(
        trial, "index_workspace", lambda workspace, *_args: workspace / "graph.json"
    )
    monkeypatch.setattr(trial.smoke, "build_configs", lambda *_args: configs)

    class StagedRule:
        def __init__(self, workspace, name):
            self.workspace = workspace
            self.name = name
            self.paths: list[Path] = []

        def __enter__(self):
            rules = self.workspace / ".cursor" / "rules"
            rules.mkdir(parents=True, exist_ok=True)
            if self.name == "graphify":
                path = rules / "graphify-agent.mdc"
                path.write_text(
                    "Use Graphify MCP query_graph for structure.\n",
                    encoding="utf-8",
                )
            else:
                path = rules / "context-agent.mdc"
                path.write_text(
                    "Context Engine search then read.\n",
                    encoding="utf-8",
                )
            self.paths.append(path)
            # Keep the transient marker the test asserts is cleaned from diffs.
            transient = rules / "transient.mdc"
            transient.write_text("transient control rule\n", encoding="utf-8")
            self.paths.append(transient)
            return self

        def __exit__(self, *_args):
            for path in self.paths:
                path.unlink(missing_ok=True)
            return None

    monkeypatch.setattr(
        trial.smoke,
        "stage_retrieval_rule",
        lambda workspace, name: StagedRule(workspace, name),
    )
    monkeypatch.setattr(trial, "_clear_context_state", lambda _workspace: None)
    monkeypatch.setattr(trial, "_sdk_version", lambda: "1.2.3")
    # Without this the test repoints the machine-wide engine daemon at a
    # pytest temp directory that disappears when the test ends.
    monkeypatch.setattr(trial.smoke, "ensure_engine_repo", lambda _workspace: None)

    class FakeBridge:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return None

    class FakeAsyncClient:
        @staticmethod
        async def launch_bridge(**_kwargs):
            return FakeBridge()

    sdk = _install_fake_cursor_sdk(monkeypatch)
    sdk.AsyncClient = FakeAsyncClient

    async def fake_run_arm(
        _client,
        config,
        workspace,
        _model,
        _timeout,
        **_kwargs,
    ):
        (workspace / "product.py").write_text(
            f"VALUE = {config.name!r}\n",
            encoding="utf-8",
        )
        diff = trial.git_diff(workspace)
        tests = {
            "exit_code": 0,
            "passed": True,
            "stdout": f"{config.name} passed",
            "stderr": "",
            "elapsed_ms": 1.0,
        }
        return {
            "name": config.name,
            "status": "finished",
            "usage": _valid_usage_dict(),
            "diff": diff,
            "tests": tests,
            "quality_pass": True,
            "expected_provider": (
                "context-engine"
                if config.name == "context_engine"
                else "graphify"
            ),
            "observed_providers": [],
            "workspace": str(workspace),
        }

    monkeypatch.setattr(trial, "run_arm", fake_run_arm)

    data = asyncio.run(
        trial.run_trial(source, output, "composer-2.5", 1200)
    )

    assert data["source_unchanged"] is True
    assert trial.source_tree_hash(source) == original_hash
    assert data["baseline_tree_hashes"]["context_engine"] == data[
        "baseline_tree_hashes"
    ]["graphify"]
    for name in ("context_engine", "graphify"):
        final_diff = (output / f"{name}.diff").read_text(encoding="utf-8")
        assert f"VALUE = '{name}'" in final_diff
        assert "transient control rule" not in final_diff
        assert "transient.mdc" not in final_diff
        assert f"{name} passed" in (
            output / f"{name}-tests.log"
        ).read_text(encoding="utf-8")
    persisted = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert persisted["sdk_version"] == "1.2.3"
    assert (output / "REPORT.md").is_file()


def test_run_trial_switches_engine_before_context_engine_agent(
    monkeypatch, tmp_path
):
    trial = _load_trial()
    monkeypatch.delenv("CTX_TRIAL_FORCE_SURFACE", raising=False)
    monkeypatch.setenv("CTX_TRIAL_PROFILE", "ce")
    source = tmp_path / "source"
    source.mkdir()
    (source / "product.py").write_text("VALUE = 1\n", encoding="utf-8")
    output = tmp_path / "output"
    order = []
    configs = {
        name: SimpleNamespace(
            name=name,
            mcp_servers={name: object()},
            setting_sources=["project"],
        )
        for name in ("context_engine", "graphify")
    }

    def fake_copy(src, dst):
        dst.mkdir(parents=True)
        (dst / "product.py").write_text(
            (src / "product.py").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return f"{dst.name}-baseline"

    class StagedRule:
        def __init__(self, workspace, name):
            self.workspace = workspace
            self.name = name
            self.path = None

        def __enter__(self):
            rules = self.workspace / ".cursor" / "rules"
            rules.mkdir(parents=True, exist_ok=True)
            if self.name == "graphify":
                self.path = rules / "graphify-agent.mdc"
                self.path.write_text(
                    "Use Graphify MCP query_graph for structure.\n",
                    encoding="utf-8",
                )
            else:
                self.path = rules / "context-agent.mdc"
                self.path.write_text(
                    "Context Engine search then read.\n",
                    encoding="utf-8",
                )
            return self

        def __exit__(self, *_args):
            if self.path is not None:
                self.path.unlink(missing_ok=True)
            return None

    class FakeBridge:
        def __init__(self, workspace):
            self.workspace = workspace

        async def __aenter__(self):
            order.append(f"bridge:{self.workspace.name}")
            return object()

        async def __aexit__(self, *_args):
            return None

    class FakeAsyncClient:
        @staticmethod
        async def launch_bridge(*, workspace, **_kwargs):
            return FakeBridge(workspace)

    sdk = _install_fake_cursor_sdk(monkeypatch)
    sdk.AsyncClient = FakeAsyncClient
    monkeypatch.setattr(trial, "copy_workspace", fake_copy)
    monkeypatch.setattr(
        trial, "index_workspace", lambda workspace, *_args: workspace / "graph.json"
    )
    monkeypatch.setattr(trial.smoke, "build_configs", lambda *_args: configs)
    monkeypatch.setattr(
        trial.smoke,
        "stage_retrieval_rule",
        lambda workspace, name: StagedRule(workspace, name),
    )
    monkeypatch.setattr(
        trial,
        "_clear_context_state",
        lambda workspace: order.append(f"clear:{workspace.name}"),
    )
    monkeypatch.setattr(
        trial.smoke,
        "ensure_engine_repo",
        lambda workspace: order.append(f"ensure:{workspace.name}"),
    )
    monkeypatch.setattr(
        trial,
        "_finalize_arm_outcome",
        lambda _workspace, outcome: outcome,
    )

    async def fake_run_arm(_client, config, _workspace, *_args, **_kwargs):
        order.append(f"run:{config.name}")
        return {
            "name": config.name,
            "status": "finished",
            "usage": _valid_usage_dict(),
            "diff": "",
            "tests": {"passed": True},
        }

    monkeypatch.setattr(trial, "run_arm", fake_run_arm)

    asyncio.run(trial.run_trial(source, output, "composer-2.5", 1200))

    assert order.index("ensure:context_engine_workspace") < order.index(
        "bridge:context_engine_workspace"
    )
    assert order.index("ensure:context_engine_workspace") < order.index(
        "run:context_engine"
    )
    assert "ensure:graphify_workspace" not in order


def test_arm_surface_nav_and_force(monkeypatch):
    trial = _load_trial()
    assert trial.smoke.arm_surface("ce_nav") == "nav"
    monkeypatch.setenv("CTX_TRIAL_FORCE_SURFACE", "nav")
    assert trial.smoke.arm_surface("ce_read") == "nav"
    assert trial.smoke.arm_surface("context_engine") == "nav"
    monkeypatch.delenv("CTX_TRIAL_FORCE_SURFACE", raising=False)
    assert trial.smoke.arm_surface("ce_read") == "read"


def test_seal_locate_fails_ce_arm_on_native_grep(monkeypatch):
    trial = _load_trial()
    monkeypatch.setenv("CTX_TRIAL_PROFILE", "ce")
    monkeypatch.setenv("CTX_TRIAL_SEAL_LOCATE", "1")
    calls = [
        {
            "kind": "mcp",
            "provider": "context-engine",
            "name": "search",
            "arguments": {},
        }
        for _ in range(5)
    ]
    calls.append({"kind": "native", "name": "grep", "arguments": {"pattern": "x"}})
    calls.append({"kind": "native", "name": "edit", "arguments": {}})
    events = [{"tool_calls": calls, "tool_results": []}]
    outcome = trial.evaluate_development_arm(
        name="ce_nav",
        status="finished",
        events=events,
        usage=_valid_usage_dict(),
        diff_text=_valid_graphify_diff(),
        tests={"exit_code": 0, "passed": True},
    )
    assert outcome["seal_locate"] is True
    assert outcome["native_locate_count"] >= 1
    assert outcome["seal_ok"] is False
    assert outcome["work_complete"] is False
    assert outcome["first_edit_step"] == 7
    assert outcome["pre_locate_calls"] == 6  # 5 search + 1 grep before edit


def test_seal_locate_passes_when_mcp_only(monkeypatch):
    trial = _load_trial()
    monkeypatch.setenv("CTX_TRIAL_PROFILE", "ce")
    monkeypatch.setenv("CTX_TRIAL_SEAL_LOCATE", "1")
    calls = [
        {
            "kind": "mcp",
            "provider": "context-engine",
            "name": n,
            "arguments": {},
        }
        for n in ("search", "files", "read", "recall", "expand")
    ]
    calls.append({"kind": "native", "name": "edit", "arguments": {}})
    events = [{"tool_calls": calls, "tool_results": []}]
    outcome = trial.evaluate_development_arm(
        name="ce_nav",
        status="finished",
        events=events,
        usage=_valid_usage_dict(),
        diff_text=_valid_graphify_diff(),
        tests={"exit_code": 0, "passed": True},
    )
    assert outcome["seal_ok"] is True
    assert outcome["native_locate_count"] == 0
    assert outcome["first_edit_step"] == 6
    assert outcome["pre_locate_calls"] == 5


def test_build_configs_includes_ce_nav(tmp_path, monkeypatch):
    trial = _load_trial()
    monkeypatch.setenv("CTX_TRIAL_FORCE_SURFACE", "")
    # Stdio may be None if cursor-sdk missing — skip if so
    if trial.smoke.StdioMcpServerConfig is None:
        return
    configs = trial.smoke.build_configs(
        ROOT, tmp_path, Path(sys.executable), tmp_path / "g.json"
    )
    assert "ce_nav" in configs
    env = configs["ce_nav"].mcp_servers["context-engine"].env
    assert env["CTX_MCP_SURFACE"] == "nav"


def test_build_configs_includes_cbm_ce(tmp_path, monkeypatch):
    trial = _load_trial()
    if trial.smoke.StdioMcpServerConfig is None:
        return
    monkeypatch.setenv("CTX_CBM_BIN", r"C:\fake\codebase-memory-mcp.exe")
    configs = trial.smoke.build_configs(
        ROOT, tmp_path, Path(sys.executable), tmp_path / "g.json"
    )
    assert "cbm_ce" in configs
    assert "cbm_ce" in trial.KNOWN_ARMS
    server = configs["cbm_ce"].mcp_servers["cbm-ce"]
    assert server.args[-1] == "hybrid_cbm" or "hybrid_cbm" in server.args
    assert server.env["CTX_CBM_BIN"].endswith("codebase-memory-mcp.exe")
    with trial.smoke.stage_retrieval_rule(tmp_path, "cbm_ce"):
        rule = (tmp_path / ".cursor" / "rules" / "context-agent.mdc").read_text(
            encoding="utf-8"
        )
    assert "cbm-ce = ONLY code locate" in rule
    assert "search_graph" in rule


def test_quarantine_arm_artifacts_hides_workspace_and_sidecar_files(tmp_path):
    trial = _load_trial()
    output = tmp_path / "run"
    vault = tmp_path / "vault"
    output.mkdir()
    ws = output / "ce_nav_workspace"
    ws.mkdir()
    (ws / "done.py").write_text("ok\n", encoding="utf-8")
    (output / "ce_nav.diff").write_text("DIFF\n", encoding="utf-8")
    (output / "ce_nav-tests.log").write_text("log\n", encoding="utf-8")
    (output / "ce_nav-conversation.json").write_text("[]\n", encoding="utf-8")
    (output / "ce_nav-arm.json").write_text("{}\n", encoding="utf-8")
    (output / "raw_workspace").mkdir()

    trial.quarantine_arm_artifacts(output, vault, "ce_nav")

    assert not (output / "ce_nav_workspace").exists()
    assert not (output / "ce_nav.diff").exists()
    assert not (output / "ce_nav-arm.json").exists()
    assert (output / "raw_workspace").is_dir()
    assert (vault / "ce_nav_workspace" / "done.py").read_text(encoding="utf-8") == "ok\n"
    assert (vault / "ce_nav.diff").read_text(encoding="utf-8") == "DIFF\n"
    assert (vault / "ce_nav-arm.json").read_text(encoding="utf-8") == "{}\n"


def test_restore_quarantined_arm_artifacts_puts_files_back(tmp_path):
    trial = _load_trial()
    output = tmp_path / "run"
    vault = tmp_path / "vault"
    output.mkdir()
    vault.mkdir()
    (vault / "ce_nav.diff").write_text("DIFF\n", encoding="utf-8")
    (vault / "ce_nav_workspace").mkdir()
    (vault / "ce_nav_workspace" / "x.py").write_text("1\n", encoding="utf-8")

    trial.restore_quarantined_arm_artifacts(vault, output)

    assert (output / "ce_nav.diff").read_text(encoding="utf-8") == "DIFF\n"
    assert (output / "ce_nav_workspace" / "x.py").read_text(encoding="utf-8") == "1\n"
    assert not vault.exists() or not any(vault.iterdir())


def test_detect_cross_arm_contamination_flags_sibling_paths():
    trial = _load_trial()
    hits = trial.detect_cross_arm_contamination(
        text=(
            "copy from "
            r"C:\tmp\ce_dev_trial\x\ce_nav_workspace\src\a.py "
            "and also ce_nav.diff"
        ),
        arm_name="raw",
        arm_names=("ce_nav", "raw"),
    )
    assert "ce_nav_workspace" in hits
    assert "ce_nav.diff" in hits
    assert trial.detect_cross_arm_contamination(
        text="only raw_workspace and own files",
        arm_name="raw",
        arm_names=("ce_nav", "raw"),
    ) == []


def test_run_trial_hides_finished_arm_before_next_arm_starts(
    tmp_path, monkeypatch
):
    """Finished arm workspace must not sit beside the next arm's cwd."""
    trial = _load_trial()
    monkeypatch.delenv("CTX_TRIAL_FORCE_SURFACE", raising=False)
    monkeypatch.setenv("CTX_TRIAL_PROFILE", "ce")
    source = tmp_path / "source"
    source.mkdir()
    (source / "product.py").write_text("print(1)\n", encoding="utf-8")
    output = tmp_path / "out"
    visible_when_started: list[tuple[str, list[str]]] = []

    def fake_copy(_src, dst):
        dst.mkdir(parents=True)
        (dst / "product.py").write_text("print(1)\n", encoding="utf-8")
        return f"{dst.name}-baseline"

    class StagedRule:
        def __init__(self, workspace, name):
            self.workspace = workspace
            self.name = name
            self.path = None

        def __enter__(self):
            rules = self.workspace / ".cursor" / "rules"
            rules.mkdir(parents=True, exist_ok=True)
            if self.name == "graphify":
                self.path = rules / "graphify-agent.mdc"
                self.path.write_text(
                    "Use Graphify MCP query_graph for structure.\n",
                    encoding="utf-8",
                )
            else:
                self.path = rules / "context-agent.mdc"
                self.path.write_text(
                    "Context Engine search then read.\n",
                    encoding="utf-8",
                )
            return self

        def __exit__(self, *_args):
            if self.path is not None:
                self.path.unlink(missing_ok=True)
            return None

    class FakeBridge:
        def __init__(self, workspace):
            self.workspace = workspace

        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args):
            return None

    class FakeAsyncClient:
        @staticmethod
        async def launch_bridge(*, workspace, **_kwargs):
            return FakeBridge(workspace)

    configs = {
        "context_engine": SimpleNamespace(
            name="context_engine",
            mcp_servers={"context-engine": object()},
            setting_sources=["project"],
        ),
        "graphify": SimpleNamespace(
            name="graphify",
            mcp_servers={"graphify": object()},
            setting_sources=["project"],
        ),
    }

    sdk = _install_fake_cursor_sdk(monkeypatch)
    sdk.AsyncClient = FakeAsyncClient
    monkeypatch.setattr(trial, "copy_workspace", fake_copy)
    monkeypatch.setattr(
        trial, "index_workspace", lambda workspace, *_a: workspace / "graph.json"
    )
    monkeypatch.setattr(trial.smoke, "build_configs", lambda *_a: configs)
    monkeypatch.setattr(
        trial.smoke,
        "stage_retrieval_rule",
        lambda workspace, name: StagedRule(workspace, name),
    )
    monkeypatch.setattr(trial, "_clear_context_state", lambda _w: None)
    monkeypatch.setattr(trial.smoke, "ensure_engine_repo", lambda _w: None)
    monkeypatch.setattr(
        trial, "_finalize_arm_outcome", lambda _w, outcome: outcome
    )

    async def fake_run_arm(_client, config, workspace, *_args, **_kwargs):
        names = sorted(p.name for p in output.iterdir()) if output.exists() else []
        visible_when_started.append((config.name, names))
        (workspace / "touched.py").write_text("x\n", encoding="utf-8")
        return {
            "name": config.name,
            "status": "finished",
            "usage": _valid_usage_dict(),
            "usage_source": "sdk",
            "diff": "diff --git a/touched.py b/touched.py\n",
            "tests": {"passed": True},
            "conversation_json": "[]",
            "work_complete": True,
        }

    monkeypatch.setattr(trial, "run_arm", fake_run_arm)

    data = asyncio.run(
        trial.run_trial(
            source,
            output,
            "composer-2.5",
            1200,
            arm_names=("context_engine", "graphify"),
        )
    )

    assert visible_when_started[0][0] == "context_engine"
    assert "context_engine_workspace" in visible_when_started[0][1]
    assert "graphify_workspace" not in visible_when_started[0][1]

    assert visible_when_started[1][0] == "graphify"
    assert "context_engine_workspace" not in visible_when_started[1][1]
    assert "context_engine.diff" not in visible_when_started[1][1]
    assert "graphify_workspace" in visible_when_started[1][1]

    # After the trial, artifacts are restored for humans / REPORT.
    assert (output / "context_engine_workspace").is_dir()
    assert (output / "context_engine.diff").is_file()
    assert (output / "graphify_workspace").is_dir()
    assert data["arms"]["context_engine"]["status"] == "finished"



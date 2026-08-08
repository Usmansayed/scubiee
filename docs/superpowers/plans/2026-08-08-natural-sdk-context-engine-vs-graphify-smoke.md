# Natural SDK Context Engine vs Graphify Smoke Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run one natural, read-only Cursor SDK smoke comparison between the session-native Context Engine MCP and Graphify MCP.

**Architecture:** A focused Python runner launches two local SDK agents sequentially against the same repository and casual prompt. The Context Engine arm loads the project rule and receives only `pipeline.mcp_locate`; the Graphify arm loads no project settings and receives only `graphify.serve`. A normalization layer records tool calls/results, final text, timing, repository mutation checks, and a deterministic answer rubric.

**Tech Stack:** Python 3.10+, `cursor-sdk`, Cursor local runtime, stdio MCP, pytest, existing `pipeline.token_meter`

## Global Constraints

- Both arms use the same available model, repository, prompt, timeout, and SDK process.
- The prompt must not mention MCP, tool names, call order, token savings, or the experiment.
- Only the Context Engine arm loads `.cursor/rules/context-agent.mdc`.
- The Graphify arm exposes only Graphify MCP and receives no experiment rule.
- A zero-tool-call result is recorded as observed behavior and is never retried with a stronger prompt.
- No API key or complete environment dump may be written to output.
- No commits are created unless the user separately requests them.

---

### Task 1: Natural MCP rule and testable smoke-runner core

**Files:**
- Modify: `.cursor/rules/context-agent.mdc`
- Create: `scripts/experiments/sdk_mcp_smoke.py`
- Create: `tests/test_sdk_mcp_smoke.py`

**Interfaces:**
- Produces: `ArmConfig(name: str, mcp_servers: dict, setting_sources: list[str])`
- Produces: `normalize_message(message: object) -> dict[str, object]`
- Produces: `evaluate_arm(name: str, events: list[dict], final_text: str, status: str, repo_unchanged: bool, wall_ms: float) -> dict[str, object]`
- Produces: `build_configs(root: Path, repo: Path, python: Path, graph_json: Path) -> dict[str, ArmConfig]`

- [ ] **Step 1: Install the current Python Cursor SDK into the project environment**

Run:

```powershell
.\.venv\Scripts\python.exe -m pip install cursor-sdk
```

Then inspect, rather than guess, the installed signatures:

```powershell
.\.venv\Scripts\python.exe -c "from cursor_sdk import Agent, AgentOptions, LocalAgentOptions, StdioMcpServerConfig; import inspect; print(inspect.signature(AgentOptions)); print(inspect.signature(LocalAgentOptions)); print(inspect.signature(StdioMcpServerConfig)); print(inspect.signature(Agent.create))"
```

Expected: imports and signature inspection succeed.

- [ ] **Step 2: Write failing tests for arm isolation, event normalization, and rubric evaluation**

Create tests which import the runner by file path and assert:

```python
def test_build_configs_isolates_mcp_and_rule_sources(tmp_path):
    graph = tmp_path / "graph.json"
    graph.write_text('{"nodes": [], "links": []}', encoding="utf-8")
    configs = smoke.build_configs(ROOT, tmp_path, Path(sys.executable), graph)

    assert set(configs) == {"context_engine", "graphify"}
    assert set(configs["context_engine"].mcp_servers) == {"context-engine"}
    assert configs["context_engine"].setting_sources == ["project"]
    assert set(configs["graphify"].mcp_servers) == {"graphify"}
    assert configs["graphify"].setting_sources == []


def test_normalize_message_extracts_tool_call_and_result():
    message = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "tool_call", "name": "map", "arguments": {"query": "lease"}},
                {"type": "tool_result", "name": "map", "content": "shared_lease.py"},
            ]
        },
    }
    event = smoke.normalize_message(message)
    assert event["tool_calls"][0]["name"] == "map"
    assert "shared_lease.py" in event["tool_results"][0]["text"]


def test_context_engine_pass_requires_natural_mcp_use_and_correct_answer():
    result = smoke.evaluate_arm(
        "context_engine",
        [{"tool_calls": [{"name": "map", "arguments": {"query": "lease"}}],
          "tool_results": [{"name": "map", "text": "shared_lease.py"}]}],
        "Conflicts are handled in shared_lease.py by SharedBrowserLease.",
        "finished",
        True,
        100.0,
    )
    assert result["mcp_used"] is True
    assert result["rubric_pass"] is True
    assert result["smoke_pass"] is True


def test_zero_tool_call_is_recorded_without_prompt_retry():
    result = smoke.evaluate_arm(
        "graphify", [], "I could not locate it.", "finished", True, 100.0
    )
    assert result["mcp_used"] is False
    assert result["smoke_pass"] is False
```

- [ ] **Step 3: Run the tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sdk_mcp_smoke.py -q
```

Expected: FAIL because the runner and interfaces do not exist yet.

- [ ] **Step 4: Strengthen the always-applied Context Engine rule without scripting the benchmark prompt**

Keep the existing frontmatter and tool descriptions, then add this behavioral contract:

```markdown
## Default behavior

Use Context Engine whenever repository context is needed, including ordinary
questions that only ask for information.

- New topic: start with `map`.
- Follow-up: call `recall` before retrieving anything again.
- Nearby question: use `focus`.
- Materialize a full span with `expand` only when exact implementation context
  is needed.
- Do not use Grep, Glob, broad directory scans, or repeated full-file reads for
  discovery while Context Engine is available.
- If Context Engine reports an error or no usable target, state that briefly
  before using a fallback.
```

This is normal project guidance, not a task-specific instruction, and contains
no benchmark query or expected answer.

- [ ] **Step 5: Implement the runner core**

In `scripts/experiments/sdk_mcp_smoke.py`:

```python
@dataclass(frozen=True)
class ArmConfig:
    name: str
    mcp_servers: dict[str, object]
    setting_sources: list[str]


PROMPT = (
    "Could you tell me where shared browser lease conflicts are handled and "
    "how that code is connected to the browser session flow? "
    "Please don't change anything."
)


def build_configs(root: Path, repo: Path, python: Path, graph_json: Path) -> dict[str, ArmConfig]:
    common_env = {
        "PYTHONPATH": str(root / "packages"),
        "PYTHONUTF8": "1",
    }
    return {
        "context_engine": ArmConfig(
            name="context_engine",
            mcp_servers={
                "context-engine": StdioMcpServerConfig(
                    command=str(python),
                    args=["-u", "-m", "pipeline.mcp_locate"],
                    env={
                        **common_env,
                        "CTX_REPO": str(repo),
                        "CTX_ENGINE_URL": "http://127.0.0.1:8765",
                        "CTX_RETRIEVE": "D",
                        "CTX_TOKEN_MODE": "savings",
                    },
                )
            },
            setting_sources=["project"],
        ),
        "graphify": ArmConfig(
            name="graphify",
            mcp_servers={
                "graphify": StdioMcpServerConfig(
                    command=str(python),
                    args=["-u", "-m", "graphify.serve", str(graph_json)],
                    env=common_env,
                )
            },
            setting_sources=[],
        ),
    }
```

Implement `normalize_message` using the SDK's inspected message/block types,
with a mapping/dataclass fallback for unit tests. Preserve only message type,
assistant text, tool name, tool arguments, and tool-result text. Do not persist
SDK metadata that could contain credentials.

Implement `evaluate_arm` to:

- flatten normalized tool calls and results;
- count result characters and call `estimate_tokens` on result text;
- detect expected evidence case-insensitively using
  `shared_lease.py` and either `SharedBrowserLease` or `browser_session`;
- set `mcp_used`, `rubric_pass`, `repo_unchanged`, and `smoke_pass`;
- require `status == "finished"`, MCP use, rubric pass, and no mutation.

- [ ] **Step 6: Run unit tests and fix only implementation defects**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sdk_mcp_smoke.py -q
```

Expected: all tests PASS.

---

### Task 2: Live SDK execution, safeguards, and report

**Files:**
- Modify: `scripts/experiments/sdk_mcp_smoke.py`
- Modify: `tests/test_sdk_mcp_smoke.py`
- Generate: `out/experiments/sdk_mcp_smoke/results.json`
- Generate: `out/experiments/sdk_mcp_smoke/REPORT.md`

**Interfaces:**
- Consumes: Task 1 `ArmConfig`, `normalize_message`, `evaluate_arm`, and `PROMPT`
- Produces: `run_arm(config: ArmConfig, repo: Path, model: str) -> dict[str, object]`
- Produces: `main() -> int`

- [ ] **Step 1: Add failing tests for repository snapshots and report honesty**

Add:

```python
def test_report_discloses_context_engine_only_rule():
    report = smoke.render_report({
        "prompt": smoke.PROMPT,
        "arms": {
            "context_engine": {"smoke_pass": True},
            "graphify": {"smoke_pass": True},
        },
    })
    assert "only the Context Engine arm loaded" in report
    assert smoke.PROMPT in report


def test_repo_snapshot_changes_when_tracked_diff_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(smoke, "_git_bytes", lambda repo: b"before")
    before = smoke.repo_snapshot(tmp_path)
    monkeypatch.setattr(smoke, "_git_bytes", lambda repo: b"after")
    after = smoke.repo_snapshot(tmp_path)
    assert before != after
```

- [ ] **Step 2: Run the focused tests and verify the new tests fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sdk_mcp_smoke.py -q
```

Expected: FAIL because `render_report`, `_git_bytes`, and `repo_snapshot` are missing.

- [ ] **Step 3: Implement guarded live execution**

Implement:

```python
def repo_snapshot(repo: Path) -> str:
    return hashlib.sha256(_git_bytes(repo)).hexdigest()


def _git_bytes(repo: Path) -> bytes:
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    return diff + b"\0STATUS\0" + status
```

Implement `run_arm` with the installed SDK signatures:

1. Take the repository snapshot.
2. Create a local agent with explicit `cwd`, selected model, the arm's inline
   MCP server, and its `setting_sources`.
3. Send exactly `PROMPT` once.
4. Record `agent_id` and `run.id`.
5. Consume `run.messages()`, normalizing each message.
6. Call `run.wait()` and capture terminal status/final text.
7. Close the agent via its context manager.
8. Take the repository snapshot again.
9. Return `evaluate_arm(...)` plus IDs and sanitized diagnostics.

Do not retry a finished zero-tool-call run. On startup exceptions, return an
error result and continue only when it is safe to run the other arm.

- [ ] **Step 4: Implement preflight and report generation**

`main()` must:

- require `CURSOR_API_KEY` without printing it;
- verify `cursor_sdk`, `mcp`, both MCP modules, and Git;
- choose an installed model by querying `Cursor.models.list()` and prefer the
  account default/`auto` rather than hard-coding an unavailable model;
- use the repository root as the identical workspace for both arms;
- verify the Context Engine index and Graphify `graph.json` through
  `PipelineStore(repo)`;
- ensure the Context Engine daemon is healthy for that repository;
- run Context Engine first, then Graphify, each once;
- write sanitized `results.json` and `REPORT.md`;
- return exit code 0 only when Context Engine passes all smoke criteria and
  Graphify successfully invokes its MCP (required for a usable comparison).

The report must include:

```markdown
## Experimental caveat

Only the Context Engine arm loaded the always-applied retrieval rule. The
Graphify arm had no experiment rule. This smoke test demonstrates normal
configured behavior, not a rule-matched causal comparison.
```

- [ ] **Step 5: Run unit and existing MCP tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_sdk_mcp_smoke.py tests/test_mcp_locate.py tests/test_session_store.py -q
```

Expected: all tests PASS (environment-dependent engine tests may retain their
existing documented skip).

- [ ] **Step 6: Run the live natural smoke A/B once**

Run without echoing credentials:

```powershell
$env:PYTHONIOENCODING = "utf-8"
.\.venv\Scripts\python.exe -u scripts\experiments\sdk_mcp_smoke.py
```

Expected:

- both SDK runs reach a terminal status;
- Context Engine naturally invokes at least one session-native tool;
- Graphify naturally invokes at least one Graphify tool;
- neither run changes the repository snapshot;
- outputs are written under `out/experiments/sdk_mcp_smoke/`.

- [ ] **Step 7: Verify generated results before making any claim**

Inspect `results.json` and confirm:

- recorded prompts are identical;
- MCP server sets are disjoint;
- Context Engine loaded `["project"]` and Graphify loaded `[]`;
- tool calls have non-empty names and results;
- no secret-looking environment values are present;
- `repo_unchanged` is true for both arms;
- the report's conclusion matches the raw statuses and pass booleans.

If either MCP arm has zero calls, report the natural failure without changing
the prompt. Repair only a demonstrated server/configuration fault, then rerun
the exact unchanged experiment.

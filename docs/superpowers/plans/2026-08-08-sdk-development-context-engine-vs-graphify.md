# SDK Development Context Engine vs Graphify Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run an isolated two-arm Cursor SDK development trial that gives both agents the same natural prompt and reports authoritative SDK input/output token usage after both implementations finish.

**Architecture:** A new experiment script copies the current working tree into two clean local Git workspaces, indexes each copy, and runs one fresh SDK agent per workspace with exactly one arm-specific MCP. Shared helpers from `sdk_mcp_smoke.py` provide MCP configuration, rule staging, conversation parsing, API-key loading, and engine identity checks; the new runner owns workspace isolation, terminal usage capture, post-run tests, diffs, and the comparative report.

**Tech Stack:** Python 3.11+, `cursor-sdk` async local runtime, Context Engine/Graphify stdio MCPs, Git CLI, pytest.

## Global Constraints

- Send this prompt verbatim to both agents: “Hey, could you take a look at focus when both a query and file path are provided? It seems to return the start of the file instead of the relevant section. Please fix it, add a regression test, and run the relevant tests.”
- Use the same model, timeout, local runtime, source snapshot, and SDK version.
- Expose exactly one inline MCP per send and reject unexpected MCP providers.
- Do not mutate or reset the source repository.
- Treat `RunResult.usage` as authoritative; never relabel estimated tool payload as model input.
- Wait for each arm to terminate before post-run tests and comparison.
- Do not create Git commits in the source repository unless the user explicitly requests one.

---

### Task 1: Isolated Trial Workspaces

**Files:**
- Create: `scripts/experiments/sdk_mcp_dev_trial.py`
- Create: `tests/test_sdk_mcp_dev_trial.py`

**Interfaces:**
- Produces: `copy_workspace(source: Path, target: Path) -> str`, returning the baseline commit hash.
- Produces: `git_diff(repo: Path) -> str`.
- Produces: `source_tree_hash(repo: Path) -> str`.
- Consumes: Git executable on `PATH`; no SDK dependency in these helpers.

- [ ] **Step 1: Write failing workspace-isolation tests**

```python
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
```

Add a second test asserting `source_tree_hash(source)` does not change when the
copied workspace is edited.

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_sdk_mcp_dev_trial.py -q
```

Expected: FAIL because `sdk_mcp_dev_trial.py` and its helpers do not exist.

- [ ] **Step 3: Implement deterministic copying and local Git baselines**

Implement:

```python
COPY_EXCLUDED_NAMES = {
    ".git",
    ".venv",
    ".context-engine",
    ".pytest_cache",
    "__pycache__",
    "out",
    ".env",
}


def _copy_ignore(directory: str, names: list[str]) -> set[str]:
    ignored = {
        name
        for name in names
        if name in COPY_EXCLUDED_NAMES or name.startswith(".sim-ce-home")
    }
    if Path(directory).name == ".cursor":
        ignored.add("mcp.json")
    return ignored


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )


def copy_workspace(source: Path, target: Path) -> str:
    shutil.copytree(source, target, ignore=_copy_ignore)
    _git(target, "init")
    info_exclude = target / ".git" / "info" / "exclude"
    info_exclude.write_text(".context-engine/\nout/\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(
        target,
        "-c", "user.name=Context Trial",
        "-c", "user.email=trial@local.invalid",
        "commit", "-m", "trial baseline",
    )
    return _git(target, "rev-parse", "HEAD").stdout.strip()


def git_diff(repo: Path) -> str:
    return _git(repo, "diff", "--no-ext-diff", "HEAD").stdout
```

Implement `source_tree_hash` over sorted relative paths and bytes while applying
the same exclusions. Include file paths in the digest so renames change the hash.

- [ ] **Step 4: Run workspace tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_sdk_mcp_dev_trial.py -q
```

Expected: PASS.

---

### Task 2: Authoritative Usage, Completion, and Quality Evaluation

**Files:**
- Modify: `scripts/experiments/sdk_mcp_dev_trial.py`
- Modify: `tests/test_sdk_mcp_dev_trial.py`

**Interfaces:**
- Produces: `usage_dict(usage: Any) -> dict[str, int | None] | None`.
- Produces: `evaluate_development_arm(name, status, events, usage, diff_text, tests) -> dict[str, Any]`.
- Produces: `render_report(data: Mapping[str, Any]) -> str`.
- Consumes: `sdk_mcp_smoke.extract_conversation_tools` event shape and Cursor SDK `TokenUsage`.

- [ ] **Step 1: Write failing usage and provider-isolation tests**

```python
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


def test_arm_requires_expected_provider_usage_diff_and_passing_tests():
    trial = _load_trial()
    outcome = trial.evaluate_development_arm(
        name="graphify",
        status="finished",
        events=[{
            "tool_calls": [{
                "kind": "mcp",
                "provider": "graphify",
                "name": "query_graph",
                "arguments": {},
            }],
            "tool_results": [],
        }],
        usage={"input_tokens": 10, "output_tokens": 2, "cache_read_tokens": 0,
               "cache_write_tokens": 0, "reasoning_tokens": None,
               "total_tokens": 12},
        diff_text=(
            "diff --git a/packages/pipeline/mcp_locate.py "
            "b/packages/pipeline/mcp_locate.py\n"
            "diff --git a/tests/test_mcp_locate.py b/tests/test_mcp_locate.py\n"
        ),
        tests={"exit_code": 0, "passed": True},
    )

    assert outcome["expected_mcp_used"] is True
    assert outcome["unexpected_mcp_providers"] == []
    assert outcome["implementation_present"] is True
    assert outcome["quality_pass"] is True
```

Add cases proving missing SDK usage and an unexpected `context-engine` provider
make `quality_pass` false. Add a report test asserting input and output are
separate columns and missing usage renders as `unavailable`.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_sdk_mcp_dev_trial.py -q
```

Expected: FAIL because usage normalization, evaluation, and report rendering are
not implemented.

- [ ] **Step 3: Implement exact usage normalization and arm evaluation**

Implement `usage_dict` by reading the six SDK fields directly; return `None`
when the SDK reports no usage. In `evaluate_development_arm`:

```python
expected_provider = (
    "context-engine" if name == "context_engine" else "graphify"
)
mcp_calls = [
    call
    for event in events
    for call in event.get("tool_calls", [])
    if call.get("kind") == "mcp" or call.get("provider")
]
providers = sorted({
    str(call["provider"]) for call in mcp_calls if call.get("provider")
})
unexpected = [provider for provider in providers if provider != expected_provider]
implementation_present = (
    "packages/pipeline/mcp_locate.py" in diff_text.replace("\\", "/")
    and "tests/test_mcp_locate.py" in diff_text.replace("\\", "/")
)
quality_pass = all([
    status == "finished",
    expected_provider in providers,
    not unexpected,
    usage is not None,
    implementation_present,
    bool(tests.get("passed")),
])
```

Retain all tool-call names, native-tool names, diff size, duration, terminal
error, and test metadata for diagnosis.

- [ ] **Step 4: Implement an auditable Markdown report**

Render:

```markdown
| Arm | Status | Input | Output | Cache read | Cache write | Reasoning | Total | Tests | Quality |
```

Below the table, report Context Engine percentage deltas against Graphify for
input, output, and total only when both values exist and the Graphify
denominator is non-zero. Include exact prompt, model, SDK version, source tree
hash, baseline commit hashes, workspace paths, expected/observed providers, and
incomplete-run warnings.

- [ ] **Step 5: Run unit tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_sdk_mcp_dev_trial.py -q
```

Expected: PASS.

---

### Task 3: Live Two-Arm SDK Runner

**Files:**
- Modify: `scripts/experiments/sdk_mcp_dev_trial.py`
- Modify: `tests/test_sdk_mcp_dev_trial.py`

**Interfaces:**
- Produces: `observe_run(run: Any, timeout_s: float) -> tuple[list[dict], Any | None, str]`.
- Produces: `run_arm(client, config, workspace, model, timeout_s) -> dict[str, Any]`.
- Produces: `run_trial(source, output, model, timeout_s) -> dict[str, Any]`.
- Consumes: helpers from `scripts/experiments/sdk_mcp_smoke.py`.

- [ ] **Step 1: Write the failing terminal-usage and timeout tests**

Create fake async runs proving:

1. `observe_run` consumes messages, calls `run.wait()`, and returns the terminal
   object carrying usage.
2. Timeout calls `run.cancel()` and returns status `timeout` with no usage.
3. `run_arm` passes the arm MCP again in `SendOptions`, preventing ambient MCP
   merging.

Use a terminal fixture:

```python
terminal = SimpleNamespace(
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_sdk_mcp_dev_trial.py -q
```

Expected: FAIL because live-run functions do not exist.

- [ ] **Step 3: Implement indexing and test execution**

Before either agent runs, index each copied workspace with the original virtual
environment:

```python
def index_workspace(workspace: Path, python: Path, root: Path) -> Path:
    env = {
        **os.environ,
        "PYTHONPATH": str(root / "packages"),
        "PYTHONUTF8": "1",
    }
    subprocess.run(
        [str(python), "-m", "pipeline", "index", str(workspace),
         "--fast", "--force"],
        cwd=root,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    graph = PipelineStore(workspace).base / "graph.json"
    if not graph.is_file():
        raise RuntimeError(f"Graphify graph missing after index: {graph}")
    return graph
```

For the post-run quality gate, call `sdk_mcp_smoke.ensure_engine_repo(workspace)`
and execute:

```powershell
<source>\.venv\Scripts\python.exe -m pytest tests\test_mcp_locate.py -q
```

with `cwd=workspace` and `PYTHONPATH=<workspace>\packages`. Capture exit code,
stdout, stderr, and elapsed milliseconds without raising on test failure.

- [ ] **Step 4: Implement terminal waiting and SDK usage capture**

`observe_run` must:

- collect normalized streamed messages;
- await `run.wait()` after message completion;
- fetch `run.conversation_json()` when supported and append parsed tool events;
- return the terminal result so `terminal.usage` remains authoritative;
- cancel and mark timeout on `asyncio.TimeoutError`.

`run_arm` must:

- create a fresh local agent in the arm workspace;
- set project rule sources and the arm MCP at creation;
- send the exact shared prompt with `SendOptions(mcp_servers=config.mcp_servers)`;
- wait for terminal completion;
- capture usage, IDs, final response, events, error, duration, and Git diff;
- run focused tests only after terminal completion;
- evaluate quality with `evaluate_development_arm`.

- [ ] **Step 5: Implement orchestration and output preservation**

`run_trial` must:

1. Hash the source tree.
2. Create `context_engine_workspace` and `graphify_workspace` beneath a
   timestamped output directory.
3. Copy and baseline both workspaces before either agent starts.
4. Verify both baseline tree hashes match.
5. Index both workspaces.
6. Launch one async SDK bridge per arm workspace sequentially.
7. Stage only that arm's rule.
8. Clear Context Engine session state before its run.
9. Write each diff and post-test log immediately after that arm finishes.
10. Verify the source tree hash is unchanged.
11. Write `results.json` and `REPORT.md`.

The CLI accepts `--source`, `--output`, `--model`, and `--timeout`; defaults are
the repository root, `out/experiments/sdk_mcp_dev_trial/<timestamp>`,
`composer-2.5`, and 1200 seconds per arm.

- [ ] **Step 6: Run all harness tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_sdk_mcp_smoke.py tests\test_sdk_mcp_dev_trial.py tests\test_mcp_locate.py tests\test_session_store.py -q
```

Expected: PASS.

---

### Task 4: Execute and Validate the Development Trial

**Files:**
- Generated: `out/experiments/sdk_mcp_dev_trial/<timestamp>/results.json`
- Generated: `out/experiments/sdk_mcp_dev_trial/<timestamp>/REPORT.md`
- Generated: `out/experiments/sdk_mcp_dev_trial/<timestamp>/context_engine.diff`
- Generated: `out/experiments/sdk_mcp_dev_trial/<timestamp>/graphify.diff`
- Generated: `out/experiments/sdk_mcp_dev_trial/<timestamp>/*-tests.log`

**Interfaces:**
- Consumes: completed Tasks 1–3 and `CURSOR_API_KEY`/`cursor_api_key`.
- Produces: the final correctness and token comparison.

- [ ] **Step 1: Run the real two-arm trial and wait for completion**

Run:

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv\Scripts\python.exe -u scripts\experiments\sdk_mcp_dev_trial.py
```

Expected: both arms reach a terminal SDK status; the command does not return
while either arm is still running.

- [ ] **Step 2: Verify result integrity**

Check `results.json`:

- both prompts are byte-for-byte identical to the shared prompt;
- both models and SDK versions match;
- baseline tree hashes match;
- source tree hash before and after matches;
- expected provider used in each arm;
- `unexpected_mcp_providers` is empty;
- `usage` exists with separate input and output counts;
- both diffs and test logs exist.

- [ ] **Step 3: Review both implementations before comparing tokens**

Read both diffs and focused test logs. Confirm each implementation makes
query-plus-path focus return a query-relevant section and each adds a regression
test. If either quality gate fails, report the failure first and do not describe
the cheaper arm as the winner.

- [ ] **Step 4: Report authoritative token comparison**

Report, for each arm:

- input tokens;
- output tokens;
- cache-read and cache-write tokens;
- reasoning tokens when available;
- total SDK tokens;
- wall time;
- MCP/native tool-call counts;
- focused test result;
- quality result.

Then report Context Engine percentage deltas against Graphify for input, output,
and total, clearly separating model usage from secondary tool-result estimates.

- [ ] **Step 5: Run final source-repository verification**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_sdk_mcp_smoke.py tests\test_sdk_mcp_dev_trial.py -q
```

Expected: PASS, with the source repository containing only the intentionally
added harness, tests, design, plan, and generated ignored outputs.

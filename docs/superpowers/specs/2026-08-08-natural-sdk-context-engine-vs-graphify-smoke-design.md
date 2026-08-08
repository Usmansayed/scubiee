# Natural Cursor SDK smoke A/B: Context Engine vs Graphify

**Date:** 2026-08-08
**Status:** approved for implementation

## Goal

Verify that a normal local Cursor SDK agent discovers and uses the session-native
Context Engine MCP from an always-applied project rule. Compare that behavior
with a Graphify-only MCP arm under otherwise identical conditions.

This is a small connectivity and behavior smoke test before the larger
two-task trial. It is not intended to prove the final token-savings claim.

## Fairness boundary

Both arms use:

- the same Cursor SDK version and available model;
- equivalent clean copies of the same indexed repository;
- the same casual, read-only information request;
- the same local runtime, timeout, and setting sources;
- only the environment variables needed to launch each MCP server.

The prompt does not mention MCP, tool names, required call order, token savings,
or the experiment. It asks an ordinary repository question.

Per the approved test condition, only the Context Engine arm receives the new
always-applied Context Engine rule. The Graphify arm receives no experiment
rule. This intentionally measures the proposed normal Context Engine setup
rather than a rule-matched retrieval comparison, and the report must state this
as a confound.

## Arms

### Context Engine

- Inline stdio server: `python -u -m pipeline.mcp_locate`
- Tools: `map`, `focus`, `workspace`, `recall`, `expand`, `status`
- Environment: repository path, package path, engine URL, retrieval mode, and
  savings mode
- Project settings enabled so `.cursor/rules/context-agent.mdc` is loaded
- The rule tells the agent to use Context Engine for normal discovery and to
  reuse session handles instead of repeating Grep/Glob/full reads

### Graphify

- Inline stdio server: `python -u -m graphify.serve <graph.json>`
- Only Graphify MCP tools are exposed
- No Context Engine server and no Context Engine rule
- The prompt and all SDK/runtime settings remain unchanged

## Casual task

Use one small question with a deterministic answer in the fixture repository,
for example:

> Could you tell me where shared browser lease conflicts are handled and how
> that code is connected to the browser session flow? Please don't change
> anything.

The wording may be adjusted only if the fixture lacks the named code. The exact
same final prompt must be recorded and sent to both arms.

## Observability and pass criteria

Capture SDK messages and terminal results without steering the agent.

For each arm record:

- terminal run status and final answer;
- MCP tool names and arguments;
- number of MCP calls;
- tool-result character count and estimated tokens;
- wall-clock time;
- files named by the answer;
- whether the answer satisfies a small deterministic rubric.

The Context Engine smoke passes when:

1. the SDK run finishes successfully;
2. at least one Context Engine MCP tool is actually invoked;
3. the tool result is non-empty and points to relevant code;
4. the answer names the expected implementation area;
5. no files are modified.

The Graphify arm is reported with the same outcome fields. A zero-tool-call run
is valid evidence of natural behavior but fails that arm's MCP-usage check; it
must not be silently retried with a stronger prompt.

## Outputs

Write machine-readable and human-readable results under:

`out/experiments/sdk_mcp_smoke/`

- `results.json`
- `REPORT.md`

The report must clearly separate observed facts from interpretation and note
that only the Context Engine arm had an always-applied retrieval rule.

## Failure handling

- Abort before launching agents if credentials, SDK package, repository index,
  graph file, or MCP entry point is unavailable.
- Do not expose API keys in logs or result files.
- Do not strengthen the prompt after a zero-call result.
- Preserve full diagnostics for MCP startup or SDK run failures.
- Verify repository state before and after each arm and fail on modifications.

## Larger-trial gate

Proceed to the larger two-task trial only if the Context Engine smoke meets all
five pass criteria. A Graphify failure does not invalidate Context Engine
connectivity, but it does prevent claiming a fair performance comparison until
the Graphify server configuration is repaired and rerun unchanged.

# SDK Development Trial: Context Engine vs Graphify

## Goal

Measure real Cursor SDK model input and output tokens while two agents complete
the same repository development task with different repository-context MCPs.
Both runs must start from identical source trees and finish before comparison.

## Shared Prompt

Both agents receive this text verbatim:

> Hey, could you take a look at focus when both a query and file path are
> provided? It seems to return the start of the file instead of the relevant
> section. Please fix it, add a regression test, and run the relevant tests.

The prompt intentionally does not mention MCPs, retrieval tools, expected files,
or implementation details.

## Fairness Boundary

- Use the same Cursor SDK version, model, local runtime, prompt, timeout, and
  starting repository contents.
- Create two independent workspace copies from the current working tree. Do not
  mutate or reset the source repository.
- Initialize each copied workspace as a local Git repository so the SDK local
  agent has a normal development environment.
- Run arms sequentially because Context Engine uses a repository-scoped daemon.
- Expose exactly one inline MCP per send. Per-send MCP configuration replaces
  ambient project or user MCP servers.
- Load equivalent always-applied discovery-first rules. The Context Engine rule
  names its tools; the Graphify rule names the corresponding Graphify tools.
- Do not add tool names, retrieval instructions, or arm-specific hints to the
  shared task prompt.

## Arms

### Context Engine

- MCP: `context-engine`
- Workflow guidance: map once for a new topic, then focus/expand as needed;
  avoid broad native discovery while the MCP is usable.
- Engine repository identity must match the copied workspace before the run.
- Session store and heatmap start empty.

### Graphify

- MCP: `graphify`
- Workflow guidance: query the graph first, then inspect relevant nodes and
  files; avoid broad native discovery while the MCP is usable.
- The graph must describe the same baseline contents copied to both workspaces.

## Execution and Completion

For each arm:

1. Snapshot the workspace before agent execution.
2. Launch a fresh SDK agent with the selected model and arm-specific MCP.
3. Send the shared prompt unchanged.
4. Consume run messages and wait for the terminal `RunResult`.
5. Record the final response, conversation tool events, SDK usage, duration,
   repository snapshot, and diff.
6. Run the relevant focused tests independently after agent completion.

A run is complete only when the SDK returns `finished`, `error`, or
`cancelled`. A safety timeout cancels the run and marks it incomplete. Token or
quality comparisons must not present an incomplete run as a successful result.

## Token Accounting

Use `RunResult.usage` from the Cursor SDK as the authoritative model accounting:

- `input_tokens`
- `output_tokens`
- `cache_read_tokens`
- `cache_write_tokens`
- `reasoning_tokens`, when reported
- `total_tokens`

Report input and output independently. Also report cache and reasoning fields so
the totals remain auditable. Tool-result character and estimated-token counts
remain secondary diagnostics and must not be labeled as model input tokens.

For each token field, report both raw arm values and the Context Engine delta
against Graphify. If SDK usage is absent, mark authoritative token accounting
unavailable rather than substituting estimates.

## Quality and Safety Gates

Each arm is evaluated independently:

- SDK terminal status is `finished`.
- The expected MCP provider was used and no unexpected MCP provider appeared.
- The source repository remains unchanged.
- The copied workspace contains an implementation diff.
- Relevant tests pass after the agent finishes.
- The implementation addresses query-plus-path focus behavior and includes a
  regression test.

Preserve each workspace diff and test output for review. Token savings do not
override correctness; a cheaper failing implementation loses.

## Outputs

Write a timestamped trial directory containing:

- `results.json` with SDK usage, events, statuses, timings, and test results
- `REPORT.md` with side-by-side input/output/cache/reasoning totals and quality
  gates
- `context_engine.diff`
- `graphify.diff`
- focused test logs for both arms

The report must state the exact prompt, model, SDK version, source snapshot,
workspace isolation method, MCP provider checks, and any timeout or missing
usage data.

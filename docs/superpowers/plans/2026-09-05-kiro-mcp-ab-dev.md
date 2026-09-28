# Kiro auto â€” real development A/B (with vs without Scubiee)

**Date:** 2026-09-05T06:49:59.161314+00:00
**Model:** `auto` Â· **Effort:** `medium`

## Task (outcome-focused; no path spoilers)

```
# Development task â€” soft-locate bad-start recovery

## Problem
When agents use this project's soft-locate / pack tools, they sometimes get a weak or unreliable starting point (for example something under tests or fixtures, or otherwise not a good production entry for the query). Today it is too easy to keep going from that bad start instead of recovering.

## Desired outcome
After a soft locate / pack completes, if the recommended starting point looks unreliable, the tool response must include a clear, actionable next step that tells the agent to remake the locate with a richer code-oriented query â€” not silently continue from the weak start.

If the starting point looks like normal production code for the query, do not spam false alarms; keep the existing happy path quiet.

## Requirements
1. Prefer a structured signal agents already consume for "what to do next" (next-step / next-action style guidance), rather than only burying a sentence in prose.
2. Cover the weak-start case with at least one automated test.
3. Cover the good-start / no-false-alarm case with at least one automated test (or an assertion in the same test module).
4. Do not break existing soft-locate / pack call shapes for happy-path callers.

## Constraints
- Stay in-process (no new network services).
- Keep the change small and reviewable.
- You may explore the codebase freely to find the right place â€” do not invent a parallel stack.
- Do not commit, push, or install packages globally. Local test runs are fine.

## Success criteria
- Weak/unreliable start â†’ actionable remake-locate next step is present.
- Good production start â†’ no false remake alarm.
- New/updated tests pass.
- Brief note in your final reply: what you changed and how to verify.

Implement this end-to-end. Explore first, then edit, then run the relevant tests yourself.
```

## Fairness

- Identical working-tree snapshots (git baseline commit per arm)
- Same model/effort/timeout; sequential runs
- `includeMcpJson=false`; user+project mcp.json neutralized during suite
- With-arm: Scubiee MCP pinned to that arm's workspace `CTX_REPO`

## Results

| arm | success | credits | wall_ms | ~tok | scubiee# | native# | files changed | tests | isolation |
|-----|---------|--------:|--------:|-----:|---------:|--------:|--------------:|-------|-----------|
| with | NO | 8.91 | 304398.7 | 15461 | 1 | 31 | 2 | FAIL | OK |
| without | NO | 10.04 | 243144.1 | 12655 | 0 | 24 | 1 | FAIL | OK |

## Diffs

### with
```
packages/pipeline/context_trace.py | 109 +++++++++++++++++++++++++++++++++++++
 packages/pipeline/mcp_locate.py    |  28 +++++++---
 2 files changed, 129 insertions(+), 8 deletions(-)
```

### without
```
packages/pipeline/context_trace.py | 81 +++++++++++++++++++++++++++++++++++++-
 1 file changed, 80 insertions(+), 1 deletion(-)
```

## Protocol

```json
{
  "model": "auto",
  "effort": "medium",
  "timeout_s": 900,
  "task": "soft-locate bad-start recovery",
  "prompt_style": "outcome+requirements+constraints; no path spoilers",
  "arms": [
    "with",
    "without"
  ],
  "sequential": true,
  "agent_engine": "v1",
  "legacy_ui": true,
  "includeMcpJson": false,
  "snapshots": {
    "with": "C:\\Users\\usman\\Downloads\\context-engine\\out\\kiro_ab_dev\\20260905T064959Z\\with",
    "without": "C:\\Users\\usman\\Downloads\\context-engine\\out\\kiro_ab_dev\\20260905T064959Z\\without"
  },
  "run_id": "20260905T064959Z",
  "project_id": "ce_d9cb766c3820091ed9ffbc64ef33063c"
}
```



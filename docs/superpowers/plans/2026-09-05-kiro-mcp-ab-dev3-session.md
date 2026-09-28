# Kiro auto — real development A/B (with vs without Scubiee)

**Date:** 2026-09-05T11:36:31.255363+00:00
**Model:** `auto` · **Effort:** `medium`
**Task:** `session_isolation` — shared-MCP session isolation fail-closed + dual-session proof

## Task (outcome-focused; no path spoilers)

```
# Development task — stop cross-chat locate/pack leakage on a shared MCP process

## Problem
Two agent chats can share one MCP server process. Soft-locate / pack persistence (pins, packed bodies, heatmap handles) from chat A must never silently become chat B's context. Today it is too easy for a missing or ambiguous session identity to reuse the wrong store — which wastes tokens and produces wrong code slices.

## Desired outcome
When session isolation is enabled:
1. Locate/pack-style calls that persist session state must resolve a session identity.
2. If identity cannot be resolved, fail closed with a clear structured error (do not write into another chat's bucket, and do not pretend success).
3. Two different session identities must keep independent persisted locate/pack state (prove with tests).

## Requirements
1. Structured error when isolation is on and session cannot be resolved for a state-mutating locate/pack path.
2. Dual-session test: actions in session A do not appear as session B's persisted locate/pack state.
3. Happy path with a valid session id still works (no false failures).
4. Prefer fixing the existing session + locate/pack persistence pipeline — do not invent a second session system.
5. Keep the change reviewable; do not break hosts that already inject a session id.

## Constraints
- In-process only; no new network services.
- Explore the codebase yourself — this prompt will not name files or functions.
- Do not commit or push. Local tests are fine.
- Do not disable isolation to "make tests pass."

## Success criteria
- Isolation on + missing session → structured failure.
- Two sessions → isolated persisted state (test-proven).
- Valid session happy path still works.
- Final reply: what changed + how you verified.

Implement end-to-end: explore → edit → test.
```

## Fairness

- Identical working-tree snapshots (git baseline commit per arm)
- Same model/effort/timeout; sequential runs
- `includeMcpJson=false`; user+project mcp.json neutralized during suite
- With-arm: Scubiee MCP pinned to that arm's workspace `CTX_REPO`

## Results

| arm | success | credits | wall_ms | ~tok | scubiee# | native# | files changed | tests | isolation | heatmap |
|-----|---------|--------:|--------:|-----:|---------:|--------:|--------------:|-------|-----------|---------|
| with | NO | None | 901638.5 | 3212 | 3 | 8 | 4 | FAIL | OK | BYPASS |
| without | NO | None | 900610.1 | 1780 | 0 | 7 | 3 | FAIL | OK | n/a |

### Savings (with − without); negative = with used less

| Metric | delta |
|--------|------:|
| credits | n/a |
| wall_ms | +1.03e+03 (+0%) |
| ~tokens (stdout/4) | +1.43e+03 (+80%) |

## Diffs

### with
```
.scubiee/id.json | 4 ++--
 1 file changed, 2 insertions(+), 2 deletions(-)
untracked: .kiro/agents/, .kiro/steering/, .scubiee/sessions/
```

### without
```
AGENTS.md | 40 +++-------------------------------------
 1 file changed, 3 insertions(+), 37 deletions(-)
untracked: .kiro/agents/, .kiro/steering/
```

## Protocol

```json
{
  "model": "auto",
  "effort": "medium",
  "timeout_s": 900,
  "task_id": "session_isolation",
  "task": "shared-MCP session isolation fail-closed + dual-session proof",
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
    "with": "C:\\Users\\usman\\Downloads\\context-engine\\out\\kiro_ab_dev\\20260905T113631Z_session_isolation\\with",
    "without": "C:\\Users\\usman\\Downloads\\context-engine\\out\\kiro_ab_dev\\20260905T113631Z_session_isolation\\without"
  },
  "run_id": "20260905T113631Z_session_isolation",
  "project_id": "ce_d9cb766c3820091ed9ffbc64ef33063c",
  "out_json": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-05-kiro-mcp-ab-dev3-session.json",
  "out_md": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-05-kiro-mcp-ab-dev3-session.md"
}
```


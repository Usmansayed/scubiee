# Kiro auto — real development A/B (with vs without Scubiee)

**Date:** 2026-09-05T12:10:02.445926+00:00
**Model:** `auto` · **Effort:** `medium`
**Task:** `engine_visibility` — pack tracer-engine visibility + broad-escape honesty

## Task (outcome-focused; no path spoilers)

```
# Development task — make pack results honest about which tracer ran

## Problem
Operators and agents cannot tell, from a pack/locate response alone, which tracing engine actually built the heatmap — especially when a "broad" / escape path temporarily switches engines and then restores the default. That opacity makes debugging bad packs and measuring product behavior hard.

## Desired outcome
Every successful pack-style context response must expose a clear structured field naming the tracer engine that produced the slice (for example the production default vs an escape engine). When a temporary broad/escape switch was used for that call, the response must also say so in a structured way (that an escape happened, and what was restored), without breaking existing fields clients already read.

## Requirements
1. Happy-path default packs report the active production tracer engine in a stable structured key.
2. Broad/escape packs report both the engine that ran for the slice and that an escape/switch occurred (and restoration), in structured fields — not only buried in free-text guide strings.
3. Automated tests cover:
   - default path reports the expected production engine identity
   - broad/escape path reports escape + the engine used for that call
4. Do not break existing pack response shapes for callers that ignore the new fields.
5. Prefer extending the existing pack/trace pipeline over inventing a parallel API.

## Constraints
- In-process only; no new network services.
- Small, reviewable change.
- Explore the codebase yourself to find where pack builds its return payload and where broad/escape temporarily changes engines — the prompt will not name files or functions.
- Do not commit or push. Local tests are fine.

## Success criteria
- Default pack → structured engine identity present.
- Broad/escape pack → structured escape signal + engine identity present.
- Tests pass.
- Final reply explains what changed and how you verified.

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
| with | NO | None | 1201655.6 | 4350 | 2 | 12 | 3 | PASS | OK | BYPASS |
| without | NO | None | 1200590.5 | 5806 | 0 | 13 | 3 | PASS | OK | n/a |

### Savings (with − without); negative = with used less

| Metric | delta |
|--------|------:|
| credits | n/a |
| wall_ms | +1.07e+03 (+0%) |
| ~tokens (stdout/4) | -1.46e+03 (-25%) |

## Diffs

### with
```
(no diff)
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
  "timeout_s": 1200,
  "task_id": "engine_visibility",
  "task": "pack tracer-engine visibility + broad-escape honesty",
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
    "with": "C:\\Users\\usman\\Downloads\\context-engine\\out\\kiro_ab_dev\\20260905T121002Z_engine_visibility\\with",
    "without": "C:\\Users\\usman\\Downloads\\context-engine\\out\\kiro_ab_dev\\20260905T121002Z_engine_visibility\\without"
  },
  "run_id": "20260905T121002Z_engine_visibility",
  "project_id": "ce_d9cb766c3820091ed9ffbc64ef33063c",
  "out_json": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-05-kiro-mcp-ab-dev2-engine.json",
  "out_md": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-05-kiro-mcp-ab-dev2-engine.md"
}
```


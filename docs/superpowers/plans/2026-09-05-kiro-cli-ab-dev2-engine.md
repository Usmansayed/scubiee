# Kiro auto — real development A/B (with vs without Scubiee)

**Date:** 2026-09-10T02:07:42.130469+00:00
**Model:** `claude-sonnet-5` · **Effort:** `medium`
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
- With-arm: **MCP wired** + GATE in AGENTS.md + `.kiro/steering/scubiee.md` (**strict MUST Use Scubiee**); agent **prompt silent on Scubiee** (rules-only)
- Without-arm: BAN Scubiee CLI + MCP; native explore only
- Preflight: ask Kiro to prove MCP tools + GATE rules + permissions; `--require-mcp-startup`; abort A/B on failure
- Rules probe: ask Kiro to quote GATE from resources into `out/ab_rules_seen.md`
- Readiness: second ask right before with-arm job (call `gate`); abort if MCP not callable
- Arms are isolated snapshots under `.ab_workspaces/.../{with,without}` — peeking the sibling arm is a FAIL

## Results

| arm | status | success | credits | wall_ms | ~tok | scubiee# | native# | files changed | tests/retrieval | isolation | heatmap |
|-----|--------|---------|--------:|--------:|-----:|---------:|--------:|--------------:|-----------------|-----------|---------|
| with | `ok` | YES | 4.54 | 319983.9 | 11769 | 3 | 21 | 2 | PASS | OK | OK |
| without | `timed_out` | NO | None | 1500554.2 | 9111 | 0 | 17 | 4 | PASS | OK | n/a |

### Savings (with − without); negative = with used less

| Metric | delta |
|--------|------:|
| credits | n/a |
| wall_ms | -1.18e+06 (-79%) |
| ~tokens (stdout/4) | +2.66e+03 (+29%) |

## Diffs

### with
```
.kiro/agents/ab_dev_with.json      |  9 +++----
 tests/test_pack_engine_identity.py | 54 ++++++++++++++++++++++++++++++++++++++
 2 files changed, 57 insertions(+), 6 deletions(-)
```

### without
```
AGENTS.md | 27 ++++-----------------------
 1 file changed, 4 insertions(+), 23 deletions(-)
untracked: .kiro/ab_surface/, .kiro/agents/, .kiro/steering/
```

## Protocol

```json
{
  "model": "claude-sonnet-5",
  "effort": "medium",
  "timeout_s": 1500,
  "task_id": "engine_visibility",
  "task": "pack tracer-engine visibility + broad-escape honesty",
  "task_mode": "dev",
  "output_file": null,
  "prompt_style": "outcome+requirements+constraints; no path spoilers; with-arm prompt silent on Scubiee (rules-only)",
  "arms_isolated": true,
  "arms": [
    "with",
    "without"
  ],
  "sequential": true,
  "agent_engine": "v1",
  "legacy_ui": true,
  "includeMcpJson": false,
  "locate": "mcp",
  "mcp": true,
  "rules_feed": [
    "AGENTS.md",
    ".kiro/steering/scubiee.md (inclusion: always)",
    "agent prompt WITH_EXTRA (no Scubiee names \u2014 points at resources only)"
  ],
  "with_prompt_silent_on_scubiee": true,
  "preflight_required": true,
  "preflight_mode": "mcp_all_tools",
  "preflight_required_tools": [
    "gate",
    "status",
    "map",
    "pack_context",
    "expand_context",
    "collect_hot_context",
    "workspace"
  ],
  "preflight": {
    "ok": true,
    "mode": "mcp",
    "exit_code": 0,
    "wall_ms": 62382.0,
    "log": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260910T020742Z_engine_visibility\\logs\\kiro_mcp_preflight.log",
    "index": {
      "ok": true,
      "steps": [
        {
          "step": "skip_snapshot_register",
          "exit": 0,
          "note": "A/B snapshot uses live locate root; CTX_REPO=C:/Users/usman/Downloads/context-engine CTX_PROJECT_ID=ce_f4e1adced6e0dd72db51bf587464e982"
        },
        {
          "step": "unlink_snapshot_id",
          "exit": 0
        }
      ],
      "pack_ok": true,
      "pack_exit": 0,
      "pack_tail": "{\"ok\":true,\"tool\":\"pack\",\"seed\":{\"id\":\"packages/pipeline/session_isolation.py::bind_request_session\",\"file\":\"packages/pipeline/session_isolation.py\",\"symbol\":\"bind_request_session\"},\"chain\":[{\"id\":\"packages/pipeline/session_isolation.py::bind_request_session\",\"loc\":\"packages/pipeline/session_isolation.py:116-120\",\"edge\":\"seed\",\"score\":1.0},{\"id\":\"packages/pipeline/session_isolation.py::sanitize_session_id\",\"loc\":\"packages/pipeline/session_isolation.py:174-177\",\"edge\":\"calls\",\"score\":0.99}],\"pack\":[{\"id\":\"packages/pipeline/session_isolation.py::bind_request_session\",\"loc\":\"packages/pipeline/session_isolation.py:116-120\",\"text\":\"def bind_request_session(session_id: str | None) -> Any | None:\\n    raw = (session_id or \\\"\\\").strip()\\n    if not raw:\\n        return None\\n    return _REQUEST_SESSION_ID.set(sanitize_session_id(raw))\"},{\"id\":\"packages/pipeline/session_isolation.py::sanitize_session_id\",\"loc\":\"packages/pipeline/session_isolation.py:174-177\",\"text\":\"def sanitize_session_id(raw: str) -> str:\\n    s = (raw or \\\"\\\").strip().replace(\\\":\\\", \\\"@\\\")\\n    s = _SAFE_SESSION_RE.sub(\\\"_\\\", s)[:128]\\n    return s or \\\"default\\\"\"}],\"cold\":[]}\n\n",
      "locate_root": "C:\\Users\\usman\\Downloads\\context-engine",
      "ctx_project_id": "ce_f4e1adced6e0dd72db51bf587464e982"
    },
    "kiro_answer": {
      "can_use_scubiee_mcp": true,
      "mcp_tools_visible": true,
      "saw_gate_rules": true,
      "permissions_ok": true,
      "used_cli_locate": false,
      "scubiee_tool_names": [
        "gate",
        "map",
        "pack_context",
        "expand_context",
        "collect_hot_context",
        "workspace",
        "expand",
        "status"
      ],
      "tools": {
        "gate": {
          "ok": true
        },
        "status": {
          "ok": true
        },
        "map": {
          "ok": true
        },
        "pack_context": {
          "ok": true,
          "heatmap_n": 16
        },
        "expand_context": {
          "ok": true
        },
        "collect_hot_context": {
          "ok": true
        },
        "workspace": {
          "ok": true
        },
        "map_context": {
          "ok": null
        },
        "pinpoint": {
          "ok": null
        },
        "plate": {
          "ok": null
        }
      },
      "notes": "All calls succeeded via MCP only; no shell scubiee locate used. gate/status returned project_id ce_f4e1adced6e0dd72db51bf587464e982, differing from the ce_d9cb766c3820091ed9ffbc64ef33063c cited in AGENTS.md/.kiro/steering/scubiee.md \u2014 same session (kiro@conn-30d7f0) though, and status.repo resolved to the parent context-engine dir rather than this nested with/ workspace, suggesting the MCP server is scoped to a broader enrolled root. status.ready=false/index_available=false/agent_ready=warming (engine healthy, warm_state ready) but map/pack_context/expand_context all returned real ranked results (non-empty heatmap, real scores), so locate functioned despite the warming flag. collect_hot_context(ids=session_store.py::recall) returned pack=[] \u2014 no error, just no body match for that id, per spec that's acceptable. workspace show returned live heatmap/pins/map_queries confirming session state persistence. map_context/pinpoint/plate were not invoked \u2014 not in the tools list returned by status, so not invented/tested."
    },
    "tools": {
      "scubiee_tools": [
        "gate",
        "status",
        "map",
        "pack_context",
        "workspace",
        "expand_context",
        "collect_hot_context"
      ],
      "mcp_scubiee_tools": [
        "gate",
        "status",
        "map",
        "pack_context",
        "workspace",
        "expand_context",
        "collect_hot_context"
      ],
      "cli_scubiee_tools": [],
      "native_tools": [],
      "scubiee_count": 7,
      "cli_locate_count": 0,
      "native_count": 0
    },
    "mcp_seen": [
      "collect_hot_context",
      "expand_context",
      "gate",
      "map",
      "pack_context",
      "status",
      "workspace"
    ],
    "required": [
      "gate",
      "status",
      "map",
      "pack_context",
      "expand_context",
      "collect_hot_context",
      "workspace"
    ],
    "missing_required": [],
    "used_cli_locate": false,
    "can_use_scubiee_mcp": true,
    "mcp_tools_visible": true,
    "require_mcp_startup": true,
    "error": null
  },
  "rules_probe": {
    "ok": true,
    "exit_code": 0,
    "wall_ms": 27583.3,
    "log": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260910T020742Z_engine_visibility\\logs\\kiro_rules_probe.log",
    "rules_file": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260910T020742Z_engine_visibility\\with\\out\\ab_rules_seen.md",
    "rules_chars": 2423,
    "quoted_must_use": true,
    "quoted_pack_context": true,
    "tools": {
      "scubiee_tools": [],
      "mcp_scubiee_tools": [],
      "cli_scubiee_tools": [],
      "native_tools": [
        "write"
      ],
      "scubiee_count": 0,
      "cli_locate_count": 0,
      "native_count": 1
    },
    "excerpt": "# AB Rules Visibility Probe\n\n## Resource visibility\n\n- `AGENTS.md` \u2014 visible/readable (provided in context entry).\n- `.kiro/steering/scubiee.md` \u2014 visible/readable (provided in context entry, same content as `.kiro\\steering\\scubiee.md`, both loaded).\n\n## Near-verbatim quote \u2014 MUST Use Scubiee / WHEN SCUBIEE MCP IS AVAILABLE sections\n\n```\n**MUST Use Scubiee MCP for locate** when `@scubiee/*` tools are callable. Prefer `map` / `pack_context` / `expand_context` / `collect_hot_context`. BAN shell `scubiee map|pack|expand` on this MCP-only surface. How-to steps \u2192 Scubiee MCP server instructions every turn.\n\n**Prefer host first (Forbid-first map/pack):**\n- Literals / imports / error strings / named-symbol under known path \u2192 Grep.\n- Filenames \u2192 Glob; known path \u2192 Read.\n- Health / `warm_state` / provider-dep \u2192 `gate`/`status` + Grep \u2014 **not** soft map\u2192pack.\n- After heatmap \u2192 Read `loc` spans only (guided); **re-Grep of packed ground = FAIL**.\n\n**WHEN SCUBIEE MCP IS AVAILABLE \u2014 STRICT, NO ESCAPE:**\n- Soft/unknown: **enrich** ~30\u201380 denser tokens (symbols/paths/outcome verbs \u2014 **not** keyword-salad; one sentence; BAN essays) \u2192 `map`(k=10) \u2192 **required next** `pack_context`(lean, packages/ `suggested_seed`; **Forbid** empty / `_` / test seeds). Vague one-liner **or** synonym dump = **FAIL**.\n- **Refine after map/expand:** fold `suggested_seed` / hot card names into the next pack/expand query (same thread; no unrelated thrash). Prefer 1\u00d7 map + 1\u00d7 pack; expand only if thin.\n- Skipping `pack_context` / map-only = **FAIL**. Warming/error \u2260 skip \u2014 retry `pack_context` / `status`.\n- Thin \u2192 `expand_context`; bodies \u2192 `collect_hot_context`.\n- Native-first while MCP is up = **FAIL**.\n- Native Grep/span-Read only after pack heatmap locs, **or** if MCP fully uncallable (no deadlock).\n- Empty heatmap **or** needle/health ask \u2192 stop ladder; Grep/Read \u2014 no map/status thrash.\n- Budget \u22643 MCP locate calls/beat. **BAN whole-file Read** of heatmap paths until expand/collect. Edit/Write stay native.\n```\n\n## Scubiee MCP tool names actually callable (from tool list)\n\n- `gate`\n- `status`\n- `map`\n- `pack_context`\n- `expand_context`\n- `collect_hot_context`\n- `expand`\n- `workspace`\n\n## Compliance statement\n\nYes \u2014 these locate/GATE rules apply regardless of whether the user's chat message explicitly names Scubiee, since they are `inclusion: always` steering rules governing soft-locate behavior for this managed repo.\n",
    "error": null
  },
  "snapshots": {
    "with": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260910T020742Z_engine_visibility\\with",
    "without": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260910T020742Z_engine_visibility\\without"
  },
  "run_id": "20260910T020742Z_engine_visibility",
  "project_id": "ce_d9cb766c3820091ed9ffbc64ef33063c",
  "out_json": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-05-kiro-cli-ab-dev2-engine.json",
  "out_md": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-05-kiro-cli-ab-dev2-engine.md",
  "scubiee_cli": "C:\\Users\\usman\\.local\\bin\\scubiee.EXE",
  "pair_run": null,
  "paired_without_from_with_baseline": false,
  "cross_arm_copy": {
    "ok": true,
    "ratio": null,
    "note": "no dual artifacts to compare"
  }
}
```


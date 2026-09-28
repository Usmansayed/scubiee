# Kiro auto — real development A/B (with vs without Scubiee)

**Date:** 2026-09-09T20:17:02.116389+00:00
**Model:** `claude-sonnet-5` · **Effort:** `medium`
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
- With-arm: **MCP wired** + GATE in AGENTS.md + `.kiro/steering/scubiee.md` (**strict MUST Use Scubiee**); agent **prompt silent on Scubiee** (rules-only)
- Without-arm: BAN Scubiee CLI + MCP; native explore only
- Preflight: ask Kiro to prove MCP tools + GATE rules + permissions; `--require-mcp-startup`; abort A/B on failure
- Rules probe: ask Kiro to quote GATE from resources into `out/ab_rules_seen.md`
- Readiness: second ask right before with-arm job (call `gate`); abort if MCP not callable
- Arms are isolated snapshots under `.ab_workspaces/.../{with,without}` — peeking the sibling arm is a FAIL

## Results

| arm | status | success | credits | wall_ms | ~tok | scubiee# | native# | files changed | tests/retrieval | isolation | heatmap |
|-----|--------|---------|--------:|--------:|-----:|---------:|--------:|--------------:|-----------------|-----------|---------|
| with | `timed_out` | NO | None | 1740623.6 | 20548 | 3 | 45 | 6 | FAIL | OK | BYPASS |
| without | `ok` | YES | 44.64 | 1348559.4 | 46569 | 0 | 75 | 9 | PASS | OK | n/a |

### Savings (with − without); negative = with used less

| Metric | delta |
|--------|------:|
| credits | n/a |
| wall_ms | +3.92e+05 (+29%) |
| ~tokens (stdout/4) | -2.6e+04 (-56%) |

## Diffs

### with
```
.kiro/agents/ab_dev_with.json          |   2 +-
 packages/pipeline/mcp_locate.py        |  37 +++++++++-
 packages/pipeline/session_isolation.py |  72 +++++++++++++++++--
 tests/test_mcp_locate.py               | 124 +++++++++++++++++++++++++++++++++
 tests/test_session_isolation.py        |  69 ++++++++++++++++++
 5 files changed, 295 insertions(+), 9 deletions(-)
untracked: _full_test_run.txt
```

### without
```
AGENTS.md                              |  23 +----
 packages/pipeline/mcp_locate.py        |  19 ++++-
 packages/pipeline/session_isolation.py |  56 +++++++++++-
 packages/pipeline/session_store.py     |  24 ++++--
 packages/pipeline/work_session.py      |  19 +++--
 tests/test_session_isolation.py        | 151 +++++++++++++++++++++++++++++++++
 6 files changed, 257 insertions(+), 35 deletions(-)
untracked: .kiro/ab_surface/, .kiro/agents/, .kiro/steering/
```

## Protocol

```json
{
  "model": "claude-sonnet-5",
  "effort": "medium",
  "timeout_s": 1500,
  "task_id": "session_isolation",
  "task": "shared-MCP session isolation fail-closed + dual-session proof",
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
    "wall_ms": 51479.0,
    "log": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260909T201702Z_session_isolation\\logs\\kiro_mcp_preflight.log",
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
      "notes": "gate/status returned project_id ce_f4e1adced6e0dd72db51bf587464e982 (differs from steering doc's ce_d9cb766c3820091ed9ffbc64ef33063c, live enrollment used). status: managed=true, engine.healthy=true, warm_state=ready, sync_state=syncing. map returned 5 ranked cards + suggested_seed=scripts/smoke_triple_pack.py::main; pack_context used seed packages/pipeline/session_store.py::_store_path from top map card and returned 16-card heatmap (4 hot) with empty bodies (mode=lean, as expected). expand_context(direction=callees) on the hot seed returned 8 delta callee cards. collect_hot_context with explicit ids returned an empty pack array (no error) \u2014 bodies not staged for those exact ids at default threshold. workspace(show) returned pins=[], heatmap aggregated from session activity, map_queries recorded. No native/CLI locate used; AGENTS.md and .kiro/steering/scubiee.md GATE/locate rules were visible and followed (map -> pack_context -> expand_context/collect_hot_context ladder, seed reuse from suggested_seed)."
    },
    "tools": {
      "scubiee_tools": [
        "gate",
        "status",
        "map",
        "pack_context",
        "expand_context",
        "collect_hot_context",
        "workspace"
      ],
      "mcp_scubiee_tools": [
        "gate",
        "status",
        "map",
        "pack_context",
        "expand_context",
        "collect_hot_context",
        "workspace"
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
    "wall_ms": 30604.8,
    "log": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260909T201702Z_session_isolation\\logs\\kiro_rules_probe.log",
    "rules_file": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260909T201702Z_session_isolation\\with\\out\\ab_rules_seen.md",
    "rules_chars": 2789,
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
    "excerpt": "# AB Rules Visibility Probe\n\n## Resource visibility\n\n- `AGENTS.md` \u2014 **visible/readable** (provided as a context entry at session start).\n- `.kiro/steering/scubiee.md` \u2014 **visible/readable** (provided as a context entry at session start).\n\nBoth resources contain identical content (the `AGENTS.md` file wraps the same text in `<!-- scubiee:start -->` / `<!-- scubiee:end -->` markers).\n\n## Near-verbatim quote of the MUST Use Scubiee / WHEN SCUBIEE MCP IS AVAILABLE sections\n\n```\n**GATE 1:ce_d9cb766c3820091ed9ffbc64ef33063c** - Managed repo. `project_id='ce_d9cb766c3820091ed9ffbc64ef33063c'`.\n\n**MUST Use Scubiee MCP for locate** when `@scubiee/*` tools are callable. Prefer `map` / `pack_context` / `expand_context` / `collect_hot_context`. BAN shell `scubiee map|pack|expand` on this MCP-only surface. How-to steps \u2192 Scubiee MCP server instructions every turn.\n\n**Prefer host first (Forbid-first map/pack):**\n- Literals / imports / error strings / named-symbol under known path \u2192 Grep.\n- Filenames \u2192 Glob; known path \u2192 Read.\n- Health / `warm_state` / provider-dep \u2192 `gate`/`status` + Grep \u2014 **not** soft map\u2192pack.\n- After heatmap \u2192 Read `loc` spans only (guided); **re-Grep of packed ground = FAIL**.\n\n**WHEN SCUBIEE MCP IS AVAILABLE \u2014 STRICT, NO ESCAPE:**\n- Soft/unknown: **enrich** ~30\u201380 denser tokens (symbols/paths/outcome verbs \u2014 **not** keyword-salad; one sentence; BAN essays) \u2192 `map`(k=10) \u2192 **required next** `pack_context`(lean, packages/ `suggested_seed`; **Forbid** empty / `_` / test seeds). Vague one-liner **or** synonym dump = **FAIL**.\n- **Refine after map/expand:** fold `suggested_seed` / hot card names into the next pack/expand query (same thread; no unrelated thrash). Prefer 1\u00d7 map + 1\u00d7 pack; expand only if thin.\n- Skipping `pack_context` / map-only = **FAIL**. Warming/error \u2260 skip \u2014 retry `pack_context` / `status`.\n- Thin \u2192 `expand_context`; bodies \u2192 `collect_hot_context`.\n- Native-first while MCP is up = **FAIL**.\n- Native Grep/span-Read only after pack heatmap locs, **or** if MCP fully uncallable (no deadlock).\n- Empty heatmap **or** needle/health ask \u2192 stop ladder; Grep/Read \u2014 no map/status thrash.\n- Budget \u22643 MCP locate calls/beat. **BAN whole-file Read** of heatmap paths until expand/collect. Edit/Write stay native.\n```\n\n## Scubiee MCP tool names actually callable (from tool list)\n\n- `gate`\n- `status`\n- `map`\n- `pack_context`\n- `expand_context`\n- `collect_hot_context`\n- `expand`\n- `workspace`\n\n## Compliance statement\n\nYes \u2014 I will follow these locate/",
    "error": null
  },
  "snapshots": {
    "with": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260909T201702Z_session_isolation\\with",
    "without": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260909T201702Z_session_isolation\\without"
  },
  "run_id": "20260909T201702Z_session_isolation",
  "project_id": "ce_d9cb766c3820091ed9ffbc64ef33063c",
  "out_json": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-05-kiro-cli-ab-dev3-session.json",
  "out_md": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-05-kiro-cli-ab-dev3-session.md",
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


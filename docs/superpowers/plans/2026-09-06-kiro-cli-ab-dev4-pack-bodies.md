# Kiro auto — real development A/B (with vs without Scubiee)

**Date:** 2026-09-09T21:46:43.475207+00:00
**Model:** `claude-sonnet-5` · **Effort:** `medium`
**Task:** `pack_bodies_optin` — MCP pack body opt-in actually collects bodies

## Task (outcome-focused; no path spoilers)

```
# Development task — make the documented pack-body opt-in actually return code bodies

## Problem
This project's MCP pack/locate tools advertise an environment-variable (and/or tool-flag) opt-in so that pack responses can include hot code bodies again. In practice, turning that opt-in on still yields heatmap/location-only responses with empty body lists — the collection step never runs, so the documented knobs for body budget / max bodies stay inert. Agents then either thrash Native-Read or call a separate collect path when they believed opt-in would be enough.

## Desired outcome
When the pack-body opt-in is enabled (env and/or explicit tool flag):
1. The pack tools that share the same implementation path actually collect and return hot bodies in the pack payload.
2. When the opt-in is off, keep today's default: compressed heatmap / locs without bodies (no regression for lean clients).
3. Field/docs language matches behavior (budget / max-bodies only matter when bodies are collected).

## Requirements
1. Opt-in on → successful pack-style responses can include non-empty body text for heated nodes (subject to existing budget caps).
2. Opt-in off → still heatmap-first / no bodies by default.
3. Automated tests cover:
   - default / opt-in-off path stays body-less (or heatmap reshape as today)
   - opt-in-on path actually requests collection (assert the pack runner is invoked with bodies enabled, and/or returned pack entries contain text when collection succeeds)
4. Prefer fixing the existing MCP pack factory + lean reshape pipeline — do not invent a parallel pack API.
5. Do not break callers that ignore bodies and only read heatmap/locs.

## Constraints
- In-process only; no new network services.
- Explore the codebase yourself — this prompt will not name files, symbols, or env var spellings beyond what you discover.
- Do not commit or push. Local tests are fine.
- Keep the change small and reviewable.

## Success criteria
- Opt-in on → bodies can appear in pack responses (proven by tests).
- Opt-in off → lean heatmap-only behavior preserved.
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
| with | `timed_out` | NO | None | 1825013.5 | 23244 | 3 | 52 | 3 | FAIL | OK | BYPASS |
| without | `job_failed` | NO | 11.92 | 253711.5 | 12221 | 0 | 23 | 5 | FAIL | OK | n/a |

### Savings (with − without); negative = with used less

| Metric | delta |
|--------|------:|
| credits | n/a |
| wall_ms | +1.57e+06 (+619%) |
| ~tokens (stdout/4) | +1.1e+04 (+90%) |

## Diffs

### with
```
.kiro/agents/ab_dev_with.json       |   9 ++--
 tests/test_mcp_pack_bodies_optin.py | 101 ++++++++++++++++++++++++++++++++++++
 2 files changed, 104 insertions(+), 6 deletions(-)
untracked: pytest_full_out.txt
```

### without
```
AGENTS.md                           |  27 +----
 tests/test_mcp_pack_bodies_optin.py | 195 ++++++++++++++++++++++++++++++++++++
 2 files changed, 199 insertions(+), 23 deletions(-)
untracked: .kiro/ab_surface/, .kiro/agents/, .kiro/steering/
```

## Protocol

```json
{
  "model": "claude-sonnet-5",
  "effort": "medium",
  "timeout_s": 1500,
  "task_id": "pack_bodies_optin",
  "task": "MCP pack body opt-in actually collects bodies",
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
    "wall_ms": 68759.9,
    "log": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260909T214643Z_pack_bodies_optin\\logs\\kiro_mcp_preflight.log",
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
      "notes": "All Scubiee MCP calls succeeded via native tool invocations (no shell scubiee CLI used). gate returned managed session line with shared-session note; status returned engine.healthy=true, tools list matches AGENTS.md/steering rules. map(k=5) on the session-isolation/pack_context query returned suggested_seed=scripts/smoke_triple_pack.py::main with 5 ranked cards. pack_context(mode=lean) using that seed returned a 16-entry heatmap (hot: main, _is_default_pack_engine, run_pack_context, _phase_tool_names) with bodies empty as expected for lean mode. expand_context(direction=callees) on packages/pipeline/context_trace.py::run_pack_context returned 10 delta callee nodes with with_bodies=false. collect_hot_context(ids=...) on the same hot node returned pack=[] (empty but ok=true \u2014 no error), since bodies below the default score threshold/no cached span for that exact id in this session. workspace(show) returned heatmap/pins/spans state confirming session-scoped rematerialize path works. GATE/locate rules were visible from both AGENTS.md and .kiro/steering/scubiee.md context entries (project_id 'ce_d9cb766c3820091ed9ffbc64ef33063c' in those files vs runtime g/project_id 'ce_f4e1adced6e0dd72db51bf587464e982' from gate/status/map \u2014 a mismatch worth flagging, likely because status/gate resolved to the parent repo root C:\\Users\\usman\\Downloads\\context-engine rather than this nested workspace subfolder). No tool errors occurred; map_context/pinpoint/plate were not invoked since they are not in the returned tools list and calling unlisted tools would be inventing tools."
    },
    "tools": {
      "scubiee_tools": [
        "gate",
        "status",
        "map",
        "workspace",
        "pack_context",
        "expand_context",
        "collect_hot_context"
      ],
      "mcp_scubiee_tools": [
        "gate",
        "status",
        "map",
        "workspace",
        "pack_context",
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
    "wall_ms": 29454.7,
    "log": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260909T214643Z_pack_bodies_optin\\logs\\kiro_rules_probe.log",
    "rules_file": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260909T214643Z_pack_bodies_optin\\with\\out\\ab_rules_seen.md",
    "rules_chars": 2603,
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
    "excerpt": "# AB Rules Visibility Probe\n\n## Resource visibility\n\n- `AGENTS.md` \u2014 visible/readable (provided as context entry).\n- `.kiro/steering/scubiee.md` \u2014 visible/readable (provided as context entry, identical content also appeared at `.kiro/steering.md` variant path in context).\n\n## Near-verbatim quote (MUST Use Scubiee / WHEN SCUBIEE MCP IS AVAILABLE sections)\n\n> **GATE 1:ce_d9cb766c3820091ed9ffbc64ef33063c** - Managed repo. `project_id='ce_d9cb766c3820091ed9ffbc64ef33063c'`.\n>\n> **MUST Use Scubiee MCP for locate** when `@scubiee/*` tools are callable. Prefer `map` / `pack_context` / `expand_context` / `collect_hot_context`. BAN shell `scubiee map|pack|expand` on this MCP-only surface. How-to steps \u2192 Scubiee MCP server instructions every turn.\n>\n> **Prefer host first (Forbid-first map/pack):**\n> - Literals / imports / error strings / named-symbol under known path \u2192 Grep.\n> - Filenames \u2192 Glob; known path \u2192 Read.\n> - Health / `warm_state` / provider-dep \u2192 `gate`/`status` + Grep \u2014 **not** soft map\u2192pack.\n> - After heatmap \u2192 Read `loc` spans only (guided); **re-Grep of packed ground = FAIL**.\n>\n> **WHEN SCUBIEE MCP IS AVAILABLE \u2014 STRICT, NO ESCAPE:**\n> - Soft/unknown: **enrich** ~30\u201380 denser tokens (symbols/paths/outcome verbs \u2014 **not** keyword-salad; one sentence; BAN essays) \u2192 `map`(k=10) \u2192 **required next** `pack_context`(lean, packages/ `suggested_seed`; **Forbid** empty / `_` / test seeds). Vague one-liner **or** synonym dump = **FAIL**.\n> - **Refine after map/expand:** fold `suggested_seed` / hot card names into the next pack/expand query (same thread; no unrelated thrash). Prefer 1\u00d7 map + 1\u00d7 pack; expand only if thin.\n> - Skipping `pack_context` / map-only = **FAIL**. Warming/error \u2260 skip \u2014 retry `pack_context` / `status`.\n> - Thin \u2192 `expand_context`; bodies \u2192 `collect_hot_context`.\n> - Native-first while MCP is up = **FAIL**.\n> - Native Grep/span-Read only after pack heatmap locs, **or** if MCP fully uncallable (no deadlock).\n> - Empty heatmap **or** needle/health ask \u2192 stop ladder; Grep/Read \u2014 no map/status thrash.\n> - Budget \u22643 MCP locate calls/beat. **BAN whole-file Read** of heatmap paths until expand/collect. Edit/Write stay native.\n\n## Scubiee MCP tools actually callable (from tool list)\n\n- `gate`\n- `status`\n- `map`\n- `pack_context`\n- `expand_context`\n- `collect_hot_context`\n- `expand`\n- `workspace`\n\n## Compliance statement\n\nYes \u2014 these rules apply to soft/unknown locate tasks regardless of whether the user's chat message explicitly names Scubiee, sinc",
    "error": null
  },
  "snapshots": {
    "with": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260909T214643Z_pack_bodies_optin\\with",
    "without": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260909T214643Z_pack_bodies_optin\\without"
  },
  "run_id": "20260909T214643Z_pack_bodies_optin",
  "project_id": "ce_d9cb766c3820091ed9ffbc64ef33063c",
  "out_json": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-06-kiro-cli-ab-dev4-pack-bodies.json",
  "out_md": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-06-kiro-cli-ab-dev4-pack-bodies.md",
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


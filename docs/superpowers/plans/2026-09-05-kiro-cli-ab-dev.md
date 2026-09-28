# Kiro auto — real development A/B (with vs without Scubiee)

**Date:** 2026-09-07T19:03:54.497313+00:00
**Model:** `auto` · **Effort:** `medium`
**Task:** `weak_start` — soft-locate bad-start recovery

## Task (outcome-focused; no path spoilers)

```
# Development task — soft-locate bad-start recovery

## Problem
When agents use this project's soft-locate / pack tools, they sometimes get a weak or unreliable starting point (for example something under tests or fixtures, or otherwise not a good production entry for the query). Today it is too easy to keep going from that bad start instead of recovering.

## Desired outcome
After a soft locate / pack completes, if the recommended starting point looks unreliable, the tool response must include a clear, actionable next step that tells the agent to remake the locate with a richer code-oriented query — not silently continue from the weak start.

If the starting point looks like normal production code for the query, do not spam false alarms; keep the existing happy path quiet.

## Requirements
1. Prefer a structured signal agents already consume for "what to do next" (next-step / next-action style guidance), rather than only burying a sentence in prose.
2. Cover the weak-start case with at least one automated test.
3. Cover the good-start / no-false-alarm case with at least one automated test (or an assertion in the same test module).
4. Do not break existing soft-locate / pack call shapes for happy-path callers.

## Constraints
- Stay in-process (no new network services).
- Keep the change small and reviewable.
- You may explore the codebase freely to find the right place — do not invent a parallel stack.
- Do not commit, push, or install packages globally. Local test runs are fine.

## Success criteria
- Weak/unreliable start → actionable remake-locate next step is present.
- Good production start → no false remake alarm.
- New/updated tests pass.
- Brief note in your final reply: what you changed and how to verify.

Implement this end-to-end. Explore first, then edit, then run the relevant tests yourself.
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

| arm | success | credits | wall_ms | ~tok | scubiee# | native# | files changed | tests/retrieval | isolation | heatmap |
|-----|---------|--------:|--------:|-----:|---------:|--------:|--------------:|-----------------|-----------|---------|
| with | NO | 4.79 | 305836.6 | 10849 | 3 | 22 | 9 | FAIL | OK | BYPASS |
| without | NO | 7.91 | 161520.8 | 7095 | 0 | 18 | 6 | FAIL | OK | n/a |

### Savings (with − without); negative = with used less

| Metric | delta |
|--------|------:|
| credits | -3.12 (-39%) |
| wall_ms | +1.44e+05 (+89%) |
| ~tokens (stdout/4) | +3.75e+03 (+53%) |

## Diffs

### with
```
.kiro/agents/ab_dev_with.json          |  8 ++---
 .kiro/settings/mcp.json                | 50 +++++++++++++++++++++++++-
 .kiro/steering/scubiee.md              |  2 +-
 AGENTS.md                              | 34 ++++++++++--------
 packages/pipeline/context_trace.py     | 64 ++++++++++++++++++++++++++++++++++
 packages/pipeline/mcp_response_lean.py | 41 ++++++++++++++++++++--
 6 files changed, 174 insertions(+), 25 deletions(-)
untracked: .scubiee/mcp-permissions.json, .scubiee/sessions/, tests/test_weak_start_recovery.py
```

### without
```
AGENTS.md                                |  27 +------
 packages/pipeline/context_trace.py       |  92 ++++++++++++++++++++++
 tests/test_incremental_context_ladder.py | 127 +++++++++++++++++++++++++++++++
 3 files changed, 223 insertions(+), 23 deletions(-)
untracked: .kiro/ab_surface/, .kiro/agents/, .kiro/steering/
```

## Protocol

```json
{
  "model": "auto",
  "effort": "medium",
  "timeout_s": 1200,
  "task_id": "weak_start",
  "task": "soft-locate bad-start recovery",
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
    "wall_ms": 83272.2,
    "log": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260907T190354Z_weak_start\\logs\\kiro_mcp_preflight.log",
    "index": {
      "ok": true,
      "steps": [
        {
          "step": "register",
          "exit": 1,
          "stdout_tail": "{\n  \"ok\": false,\n  \"project_id\": \"\",\n  \"root\": \"C:\\\\Users\\\\usman\\\\Downloads\\\\context-engine\\\\.ab_workspaces\\\\kiro_ab_dev\\\\20260907T190354Z_weak_start\\\\with\",\n  \"store_dir\": \"\",\n  \"already_registered\": false,\n  \"indexed\": false,\n  \"chunks\": 0,\n  \"always_allow\": false,\n  \"error\": \"Scubiee required dependencies unavailable: provider:DmlExecutionProvider. Run `python -m pipeline setup` (or `pip install -e \\\".[dml]\\\"`) so FastEmbed uses DmlExecutionProvider at batch=16. Run `python -m pipeline setup` (or `pip install -e \\\".[dml]\\\"`) so FastEmbed uses DmlExecutionProvider at batch=16.\",\n  \"mode\": \"automatic\"\n}\n",
          "stderr_tail": "[scubiee] Copied checkout detected at C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260907T190354Z_weak_start\\with \u2014 forked new project ce_979d00b75e5b8ae56fe06198508cedeb (was ce_d9cb766c3820091ed9ffbc64ef33063c).\n[resources] index start pressure=idle batch~16 allow=True (system idle \u2014 boost throughput)\n"
        },
        {
          "step": "index",
          "exit": 1,
          "stdout_tail": "",
          "stderr_tail": "bilities\n    raise CapabilityError(\n    ...<4 lines>...\n    )\npipeline.preflight.CapabilityError: Scubiee required dependencies unavailable: provider:DmlExecutionProvider. Run `python -m pipeline setup` (or `pip install -e \".[dml]\"`) so FastEmbed uses DmlExecutionProvider at batch=16. Run `python -m pipeline setup` (or `pip install -e \".[dml]\"`) so FastEmbed uses DmlExecutionProvider at batch=16.\n"
        }
      ],
      "pack_ok": true,
      "pack_exit": 0,
      "pack_tail": "ain\":[{\"id\":\"packages/pipeline/session_isolation.py::bind_request_session\",\"loc\":\"packages/pipeline/session_isolation.py:116-120\",\"edge\":\"seed\",\"score\":1.0},{\"id\":\"packages/pipeline/session_isolation.py::sanitize_session_id\",\"loc\":\"packages/pipeline/session_isolation.py:174-177\",\"edge\":\"calls\",\"score\":0.99}],\"pack\":[{\"id\":\"packages/pipeline/session_isolation.py::bind_request_session\",\"loc\":\"packages/pipeline/session_isolation.py:116-120\",\"text\":\"def bind_request_session(session_id: str | None) -> Any | None:\\n    raw = (session_id or \\\"\\\").strip()\\n    if not raw:\\n        return None\\n    return _REQUEST_SESSION_ID.set(sanitize_session_id(raw))\"},{\"id\":\"packages/pipeline/session_isolation.py::sanitize_session_id\",\"loc\":\"packages/pipeline/session_isolation.py:174-177\",\"text\":\"def sanitize_session_id(raw: str) -> str:\\n    s = (raw or \\\"\\\").strip().replace(\\\":\\\", \\\"@\\\")\\n    s = _SAFE_SESSION_RE.sub(\\\"_\\\", s)[:128]\\n    return s or \\\"default\\\"\"}],\"cold\":[]}\n\n<unknown>:6: SyntaxWarning: invalid escape sequence '\\.'\n<unknown>:6: SyntaxWarning: invalid escape sequence '\\.'\n<unknown>:6: SyntaxWarning: invalid escape sequence '\\.'\n<unknown>:6: SyntaxWarning: invalid escape sequence '\\.'\n"
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
      "notes": "All Scubiee MCP tools callable and permitted (no approval prompts). gate returned managed gate text '1:ce_d9cb766c3820091ed9ffbc64ef33063c sid:kiro@conn-f72900 shared'. status: managed=true, engine.healthy=true, warm_state=ready, agent_ready=warming, index_available=false. GATE/locate rules visible from AGENTS.md and .kiro/steering/scubiee.md. map k=5 returned suggested_seed session_store.py::end_session. pack_context (lean, same query, seed end_session) returned 16 heatmap nodes with read.top=5 (bodies not requested in lean mode). expand_context callees returned 12 delta nodes. collect_hot_context returned ok=true with empty pack (no error; bodies path exercised, empty acceptable). workspace show returned session heatmap keyed by session_id kiro@conn-f72900 with 6 files. Optional map_context/pinpoint/plate are NOT exposed on this MCP server, set to null (not invented). Session flagged 'shared' across parallel chats. No CLI locate used; no files edited."
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
    "wall_ms": 33161.4,
    "log": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260907T190354Z_weak_start\\logs\\kiro_rules_probe.log",
    "rules_file": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260907T190354Z_weak_start\\with\\out\\ab_rules_seen.md",
    "rules_chars": 2589,
    "quoted_must_use": true,
    "quoted_pack_context": true,
    "tools": {
      "scubiee_tools": [],
      "mcp_scubiee_tools": [],
      "cli_scubiee_tools": [],
      "native_tools": [
        "read",
        "write"
      ],
      "scubiee_count": 0,
      "cli_locate_count": 0,
      "native_count": 2
    },
    "excerpt": "# AB Rules Visibility Probe\n\n## Resource visibility\n\n- `AGENTS.md` \u2014 visible and readable (contains the `scubiee:start`/`scubiee:end` block).\n- `.kiro/steering/scubiee.md` \u2014 visible and readable (front matter `inclusion: always`).\n\nBoth files carry the same GATE line: `GATE 1:ce_d9cb766c3820091ed9ffbc64ef33063c` (managed repo, `project_id='ce_d9cb766c3820091ed9ffbc64ef33063c'`).\n\n## Near-verbatim quote of the locate/GATE rules\n\n> **MUST Use Scubiee MCP for locate** when `@scubiee/*` tools are callable. Prefer `map` / `pack_context` / `expand_context` / `collect_hot_context`. BAN shell `scubiee map|pack|expand` on this MCP-only surface. How-to steps \u2192 Scubiee MCP server instructions every turn.\n>\n> **Prefer host first (Forbid-first map/pack):**\n> - Literals / imports / error strings / named-symbol under known path \u2192 Grep.\n> - Filenames \u2192 Glob; known path \u2192 Read.\n> - Health / `warm_state` / provider-dep \u2192 `gate`/`status` + Grep \u2014 **not** soft map\u2192pack.\n> - After heatmap \u2192 Read `loc` spans only (guided).\n>\n> **WHEN SCUBIEE MCP IS AVAILABLE \u2014 STRICT, NO ESCAPE:**\n> - Soft/unknown: **enrich** ~30\u201380 denser tokens (symbols/paths/outcome verbs \u2014 **not** keyword-salad; one sentence; BAN essays) \u2192 `map`(k=10) \u2192 **required next** `pack_context`(lean, packages/ `suggested_seed`; **Forbid** empty / `_` / test seeds). Vague one-liner **or** synonym dump = **FAIL**.\n> - **Refine after map/expand:** fold `suggested_seed` / hot card names into the next pack/expand query (same thread; no unrelated thrash). Prefer 1\u00d7 map + 1\u00d7 pack; expand only if thin.\n> - Skipping `pack_context` / map-only = **FAIL**. Warming/error \u2260 skip \u2014 retry `pack_context` / `status`.\n> - Thin \u2192 `expand_context`; bodies \u2192 `collect_hot_context`.\n> - Native-first while MCP is up = **FAIL**.\n> - Native Grep/span-Read only after pack heatmap locs, **or** if MCP fully uncallable (no deadlock).\n> - Empty heatmap **or** needle/health ask \u2192 stop ladder; Grep/Read \u2014 no map/status thrash.\n> - Budget \u22643 MCP locate calls/beat. **BAN whole-file Read** of heatmap paths until expand/collect. Edit/Write stay native.\n\n## Scubiee MCP tools I can actually call\n\nFrom the available tool list (not invented):\n\n- `gate`\n- `status`\n- `map`\n- `pack_context`\n- `expand_context`\n- `collect_hot_context`\n- `expand`\n- `workspace`\n\n## Will I follow these rules for soft locate even if the chat never named Scubiee?\n\nYes \u2014 for any soft/unknown locate I will run the `map` \u2192 `pack_context` ladder (with host-first Grep/Glob/Read for litera",
    "error": null
  },
  "snapshots": {
    "with": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260907T190354Z_weak_start\\with",
    "without": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260907T190354Z_weak_start\\without"
  },
  "run_id": "20260907T190354Z_weak_start",
  "project_id": "ce_d9cb766c3820091ed9ffbc64ef33063c",
  "out_json": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-05-kiro-cli-ab-dev.json",
  "out_md": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-05-kiro-cli-ab-dev.md",
  "scubiee_cli": "C:\\Users\\usman\\.local\\bin\\scubiee.EXE",
  "cross_arm_copy": {
    "ok": true,
    "ratio": null,
    "note": "no dual artifacts to compare"
  }
}
```


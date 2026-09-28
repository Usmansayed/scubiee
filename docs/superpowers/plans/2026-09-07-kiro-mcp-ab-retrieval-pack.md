# Kiro auto — real development A/B (with vs without Scubiee)

**Date:** 2026-09-10T03:37:45.798513+00:00
**Model:** `claude-sonnet-5` · **Effort:** `medium`
**Task:** `complex_retrieval_pack` — complex pack/heatmap/session retrieval → single reasoning context file

## Task (outcome-focused; no path spoilers)

```
# Retrieval challenge — assemble a reasoning context pack (NO code changes)

## Mission
You must retrieve enough multi-hop codebase context to answer a hard product question later —
but you will NOT implement anything. Your ONLY deliverable is one markdown file that stores
all context needed for reasoning.

## Hard question (do not answer in chat — put evidence in the file)
Trace the Scubiee **incremental locate ladder + session isolation** end-to-end:
1. How `map` picks / exposes a suggested seed for packing.
2. How `pack_context` (lean / heatmap-first) is built — where the heatmap/locs come from and
   what “no bodies by default” means in the response shape.
3. How `expand_context` and `collect_hot_context` extend or hydrate that slice.
4. How session identity is resolved for persisted locate/pack state, and what happens when
   isolation is on but a session cannot be resolved (fail-closed vs shared-process fallback).
5. Where session-scoped pins / packed ids / heatmap handles are stored on disk (or equivalent).

Ignore CLI banners/print helpers. Prefer production packages/ code over tests/docs.

## Deliverable (strict)
Write exactly one file:
  `out/ab_retrieval_context.md`

That file MUST contain:
- A short problem restatement (≤8 lines).
- An ordered call/flow narrative (entry → pack/heatmap → expand/collect → session persistence).
- A table or bullet list of concrete `path` + `symbol` (+ optional `loc` if known) for every
  hop you rely on.
- Short excerpts or paraphrases of the critical logic (enough to reason without re-opening the repo).
- A final "open questions / unknowns" section if anything is still unclear.

## Non-goals / bans
- Do NOT edit production code or tests.
- Do NOT commit or push.
- Do NOT invent paths/symbols you did not find.
- Do NOT read or copy from any sibling A/B workspace (no `../with`, `../without`, other
  `.ab_workspaces/**` trees, or another arm's `out/ab_retrieval_context.md`).
- Work ONLY inside THIS workspace root.

## Success
- File exists at `out/ab_retrieval_context.md`.
- It is self-contained enough that a later agent could reason about map→pack→expand/collect
  and session isolation without rediscovering the graph.
- Stop when the file is written. Brief chat summary is OK; the file is the artifact.
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
| with | `ok` | YES | 7.77 | 265756.7 | 26666 | 5 | 24 | 1 | file_rec=1.0 sym=1.0 (PASS) | OK | OK |
| without | `ok` | YES | 9.03 | 165291.1 | 8975 | 0 | 14 | 4 | file_rec=1.0 sym=1.0 (PASS) | OK | n/a |

### Savings (with − without); negative = with used less

| Metric | delta |
|--------|------:|
| credits | -1.26 (-14%) |
| wall_ms | +1e+05 (+61%) |
| ~tokens (stdout/4) | +1.77e+04 (+197%) |

## Diffs

### with
```
.kiro/agents/ab_dev_with.json | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)
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
  "timeout_s": 1200,
  "task_id": "complex_retrieval_pack",
  "task": "complex pack/heatmap/session retrieval \u2192 single reasoning context file",
  "task_mode": "retrieval",
  "output_file": "out/ab_retrieval_context.md",
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
    "wall_ms": 105346.8,
    "log": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260910T033745Z_complex_retrieval_pack\\logs\\kiro_mcp_preflight.log",
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
        "status",
        "map",
        "pack_context",
        "expand_context",
        "collect_hot_context",
        "workspace",
        "expand"
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
      "notes": "All 7 required MCP calls succeeded. status() reported repo=parent context-engine dir and index_available=false but map/pack_context against the explicit workspace root returned real ranked results. collect_hot_context returned empty pack (heatmap scores 0.0 < default threshold 0.82) \u2014 expected, not a failure. map_context/pinpoint/plate not exposed on this server; not invented."
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
      "native_tools": [
        "read",
        "write"
      ],
      "scubiee_count": 7,
      "cli_locate_count": 0,
      "native_count": 2
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
    "wall_ms": 30925.3,
    "log": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260910T033745Z_complex_retrieval_pack\\logs\\kiro_rules_probe.log",
    "rules_file": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260910T033745Z_complex_retrieval_pack\\with\\out\\ab_rules_seen.md",
    "rules_chars": 2830,
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
    "excerpt": "# Rules Visibility Probe\n\n## Resource visibility\n\n- `AGENTS.md` \u2014 **visible/readable** (provided in context entry, root of workspace).\n- `.kiro/steering/scubiee.md` \u2014 **visible/readable** (provided in context entry; also present duplicated at `.kiro/steering/scubiee.md` path form).\n\nBoth resources contain identical Scubiee governance content, wrapped in `<!-- scubiee:start -->` / `<!-- scubiee:end -->` markers in `AGENTS.md`, and under `inclusion: always` frontmatter in the steering file.\n\n## Near-verbatim quote (MUST Use Scubiee / WHEN SCUBIEE MCP IS AVAILABLE sections)\n\n```\n**GATE 1:ce_f4e1adced6e0dd72db51bf587464e982** - Managed repo. `project_id='ce_f4e1adced6e0dd72db51bf587464e982'`.\n\n**MUST Use Scubiee MCP for locate** when `@scubiee/*` tools are callable. Prefer `map` / `pack_context` / `expand_context` / `collect_hot_context`. BAN shell `scubiee map|pack|expand` on this MCP-only surface. How-to steps \u2192 Scubiee MCP server instructions every turn.\n\n**Prefer host first (Forbid-first map/pack):**\n- Literals / imports / error strings / named-symbol under known path \u2192 Grep.\n- Filenames \u2192 Glob; known path \u2192 Read.\n- Health / `warm_state` / provider-dep \u2192 `gate`/`status` + Grep \u2014 **not** soft map\u2192pack.\n- After heatmap \u2192 Read `loc` spans only (guided); **re-Grep of packed ground = FAIL**.\n\n**WHEN SCUBIEE MCP IS AVAILABLE \u2014 STRICT, NO ESCAPE:**\n- Soft/unknown: **enrich** ~30\u201380 denser tokens (symbols/paths/outcome verbs \u2014 **not** keyword-salad; one sentence; BAN essays) \u2192 `map`(k=10) \u2192 **required next** `pack_context`(lean, packages/ `suggested_seed`; **Forbid** empty / `_` / test seeds). Vague one-liner **or** synonym dump = **FAIL**.\n- **Refine after map/expand:** fold `suggested_seed` / hot card names into the next pack/expand query (same thread; no unrelated thrash). Prefer 1\u00d7 map + 1\u00d7 pack; expand only if thin.\n- Skipping `pack_context` / map-only = **FAIL**. Warming/error \u2260 skip \u2014 retry `pack_context` / `status`.\n- Thin \u2192 `expand_context`; bodies \u2192 `collect_hot_context`.\n- Native-first while MCP is up = **FAIL**.\n- Native Grep/span-Read only after pack heatmap locs, **or** if MCP fully uncallable (no deadlock).\n- Empty heatmap **or** needle/health ask \u2192 stop ladder; Grep/Read \u2014 no map/status thrash.\n- Budget \u22643 MCP locate calls/beat. **BAN whole-file Read** of heatmap paths until expand/collect. Edit/Write stay native.\n```\n\n## Scubiee MCP tools actually callable (from tool list)\n\n- `gate`\n- `status`\n- `map`\n- `pack_context`\n- `expand_context`\n- `collect",
    "error": null
  },
  "snapshots": {
    "with": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260910T033745Z_complex_retrieval_pack\\with",
    "without": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260910T033745Z_complex_retrieval_pack\\without"
  },
  "run_id": "20260910T033745Z_complex_retrieval_pack",
  "project_id": "ce_d9cb766c3820091ed9ffbc64ef33063c",
  "out_json": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-07-kiro-mcp-ab-retrieval-pack.json",
  "out_md": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-07-kiro-mcp-ab-retrieval-pack.md",
  "scubiee_cli": "C:\\Users\\usman\\.local\\bin\\scubiee.EXE",
  "pair_run": null,
  "paired_without_from_with_baseline": false,
  "cross_arm_copy": {
    "ok": true,
    "ratio": 0.0959,
    "note": "artifacts independently distinct"
  }
}
```


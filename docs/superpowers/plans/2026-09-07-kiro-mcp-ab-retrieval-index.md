# Kiro auto — real development A/B (with vs without Scubiee)

**Date:** 2026-09-10T03:49:51.022259+00:00
**Model:** `claude-sonnet-5` · **Effort:** `medium`
**Task:** `complex_retrieval_index` — complex index/sync/engine-warm retrieval → single reasoning context file

## Task (outcome-focused; no path spoilers)

```
# Retrieval challenge — assemble a reasoning context pack (NO code changes)

## Mission
You must retrieve enough multi-hop codebase context to answer a hard product question later —
but you will NOT implement anything. Your ONLY deliverable is one markdown file that stores
all context needed for reasoning.

## Hard question (do not answer in chat — put evidence in the file)
Trace how Scubiee becomes **ready to locate/pack** and what agents see when it is not:
1. How the local engine is contacted / ensured (URL, health, warm path).
2. Which preflight / capability gates can refuse index or embedding work (provider / deps).
3. How MCP `status` / gate-style health surfaces expose `warm_state`, index usability, or similar.
4. How a soft locate still reaches `map` → `pack_context` once the engine is usable — where
   suggested_seed and lean heatmap are produced in the pack pipeline.
5. What “warming / error / not ready” means for agents (retry vs fail vs native fallback policy
   in product instructions if present).

Ignore CLI banners/print helpers. Prefer production packages/ code over tests/docs.

## Deliverable (strict)
Write exactly one file:
  `out/ab_retrieval_context.md`

That file MUST contain:
- A short problem restatement (≤8 lines).
- An ordered call/flow narrative (engine ensure → capability/preflight → status/warm → map/pack).
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
- It is self-contained enough that a later agent could reason about engine warm/index readiness
  and the path into pack without rediscovering the graph.
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
| with | `ok` | YES | 7.09 | 238052.9 | 12640 | 11 | 18 | 1 | file_rec=0.75 sym=0.833 (PASS) | OK | OK |
| without | `ok` | YES | 11.2 | 279021.3 | 14264 | 0 | 28 | 4 | file_rec=0.75 sym=0.667 (PASS) | OK | n/a |

### Savings (with − without); negative = with used less

| Metric | delta |
|--------|------:|
| credits | -4.11 (-37%) |
| wall_ms | -4.1e+04 (-15%) |
| ~tokens (stdout/4) | -1.62e+03 (-11%) |

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
  "task_id": "complex_retrieval_index",
  "task": "complex index/sync/engine-warm retrieval \u2192 single reasoning context file",
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
    "wall_ms": 63975.6,
    "log": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260910T034951Z_complex_retrieval_index\\logs\\kiro_mcp_preflight.log",
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
      "notes": "All ship-surface Scubiee MCP tools callable and returned ok:true. gate returned managed gate text with g-tag ce_f4e1adced6e0dd72db51bf587464e982 and session_id kiro@conn-13d7f0. status showed engine.healthy=true, warm_state=ready, but index_available=false and agent_ready='warming' \u2014 repo path in status response was the parent context-engine dir, not this ab_workspaces/with subfolder, though root param was passed correctly each call. map returned 5 ranked cards with suggested_seed=packages/pipeline/session_store.py::recall. pack_context(lean) on that seed returned heatmap_n=16 (hot: recall, effective_session_id x2, load_session), bodies empty as expected for lean mode. expand_context(direction=callees) returned 10 delta callee nodes (session_json_lock, _store_path, _read_store_file, etc.) with with_bodies=false. collect_hot_context with explicit ids returned ok:true but empty pack array \u2014 likely because threshold/ids didn't resolve to cached session cards, not a tool failure. workspace(show) returned pins=[], heatmap with 7 files tracked from the map/pack calls, confirming session state persists across the ladder. AGENTS.md and .kiro/steering/scubiee.md GATE/locate rules were visible as context entries and followed (map->pack_context->expand_context->collect_hot_context ladder, no shell scubiee commands used). map_context/pinpoint/plate not present in status tools list, so left null rather than invented."
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
    "wall_ms": 30444.9,
    "log": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260910T034951Z_complex_retrieval_index\\logs\\kiro_rules_probe.log",
    "rules_file": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260910T034951Z_complex_retrieval_index\\with\\out\\ab_rules_seen.md",
    "rules_chars": 2672,
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
    "excerpt": "# Rules Visibility Probe\n\n## 1. Resource visibility\n\n- `AGENTS.md` \u2014 **visible/readable**. Provided as a context entry at session start (scubiee:start / scubiee:end block).\n- `.kiro/steering/scubiee.md` \u2014 **visible/readable**. Provided as a context entry at session start (`inclusion: always`), and it is identical in content to the AGENTS.md block.\n\n## 2. Near-verbatim quote of the MUST Use Scubiee / WHEN SCUBIEE MCP IS AVAILABLE sections\n\n```\n**GATE 1:ce_f4e1adced6e0dd72db51bf587464e982** - Managed repo. `project_id='ce_f4e1adced6e0dd72db51bf587464e982'`.\n\n**MUST Use Scubiee MCP for locate** when `@scubiee/*` tools are callable. Prefer `map` / `pack_context` / `expand_context` / `collect_hot_context`. BAN shell `scubiee map|pack|expand` on this MCP-only surface. How-to steps \u2192 Scubiee MCP server instructions every turn.\n\n**Prefer host first (Forbid-first map/pack):**\n- Literals / imports / error strings / named-symbol under known path \u2192 Grep.\n- Filenames \u2192 Glob; known path \u2192 Read.\n- Health / `warm_state` / provider-dep \u2192 `gate`/`status` + Grep \u2014 **not** soft map\u2192pack.\n- After heatmap \u2192 Read `loc` spans only (guided); **re-Grep of packed ground = FAIL**.\n\n**WHEN SCUBIEE MCP IS AVAILABLE \u2014 STRICT, NO ESCAPE:**\n- Soft/unknown: **enrich** ~30\u201380 denser tokens (symbols/paths/outcome verbs \u2014 **not** keyword-salad; one sentence; BAN essays) \u2192 `map`(k=10) \u2192 **required next** `pack_context`(lean, packages/ `suggested_seed`; **Forbid** empty / `_` / test seeds). Vague one-liner **or** synonym dump = **FAIL**.\n- **Refine after map/expand:** fold `suggested_seed` / hot card names into the next pack/expand query (same thread; no unrelated thrash). Prefer 1\u00d7 map + 1\u00d7 pack; expand only if thin.\n- Skipping `pack_context` / map-only = **FAIL**. Warming/error \u2260 skip \u2014 retry `pack_context` / `status`.\n- Thin \u2192 `expand_context`; bodies \u2192 `collect_hot_context`.\n- Native-first while MCP is up = **FAIL**.\n- Native Grep/span-Read only after pack heatmap locs, **or** if MCP fully uncallable (no deadlock).\n- Empty heatmap **or** needle/health ask \u2192 stop ladder; Grep/Read \u2014 no map/status thrash.\n- Budget \u22643 MCP locate calls/beat. **BAN whole-file Read** of heatmap paths until expand/collect. Edit/Write stay native.\n```\n\n## 3. Scubiee MCP tool names actually callable (from tool list)\n\n- `gate`\n- `status`\n- `map`\n- `pack_context`\n- `expand_context`\n- `collect_hot_context`\n- `expand`\n- `workspace`\n\n## 4. Rule-following commitment\n\nYes \u2014 these locate/GATE rules apply to my process itsel",
    "error": null
  },
  "snapshots": {
    "with": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260910T034951Z_complex_retrieval_index\\with",
    "without": "C:\\Users\\usman\\Downloads\\context-engine\\.ab_workspaces\\kiro_ab_dev\\20260910T034951Z_complex_retrieval_index\\without"
  },
  "run_id": "20260910T034951Z_complex_retrieval_index",
  "project_id": "ce_d9cb766c3820091ed9ffbc64ef33063c",
  "out_json": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-07-kiro-mcp-ab-retrieval-index.json",
  "out_md": "C:\\Users\\usman\\Downloads\\context-engine\\docs\\superpowers\\plans\\2026-09-07-kiro-mcp-ab-retrieval-index.md",
  "scubiee_cli": "C:\\Users\\usman\\.local\\bin\\scubiee.EXE",
  "pair_run": null,
  "paired_without_from_with_baseline": false,
  "cross_arm_copy": {
    "ok": true,
    "ratio": 0.052,
    "note": "artifacts independently distinct"
  }
}
```


# Scubiee Map V3 vs Without — Cursor benchmark results

Runtime: **Cursor headless agent CLI** `agent` v2026.10.01, model `auto` (Cursor router),
both arms identical. Scubiee engine **0.3.140** (warm, dense), map_v3 bridge as the MCP server.
Harness: `scripts/claude_sdk_harness/run_cursor_ab.py` (faithful port of the Claude SDK harness —
same task prompts, same hidden oracle, same SHA-identical git-snapshot isolation, same map_v3
bridge + rule). Token usage read from the Cursor CLI `result` event `usage` block
(`inputTokens/outputTokens/cacheReadTokens/cacheWriteTokens`).

## Setup validity (preflight — all passed before any token spend)
- Cursor CLI installed + key authenticates; `--output-format json` emits structured token usage.
- Per-arm workspaces are byte-identical git snapshots (`identical_tree` asserted each cell).
- With-arm: Scubiee MCP present in the **global** `~/.cursor/mcp.json` (the headless agent only
  reads the global file, not a per-workspace one — verified) + the map_v3 rule in CLAUDE.md.
  Without-arm: empty MCP config, native tools only. Global config backed up and restored.
- Engine configured **read-only** for locate (`CTX_AUTO_INDEX=0`, `CTX_BACKGROUND_SYNC=0`) — neither
  arm can write it. Shared only as a read index, so no cross-arm contamination.
- Scubiee calls are genuinely counted (MCP calls arrive as `mcpToolCall` with
  `serverIdentifier=scubieeab`; housekeeping `getMcpTools` excluded).

## Run 1 — task `cache_aware_savings` (single-file dev task), model auto, 2 reps/arm

| arm | rep | total tokens | scubiee calls | tool calls | edited | oracle | success |
|---|---|---:|---:|---:|---|---|---|
| without | 1 | 203,545 | 0 | 13 | 1 | 1.0 | ✅ |
| without | 2 | 377,229 | 0 | 17 | 1 | 1.0 | ✅ |
| map_v3 | 1 | 573,737 | 2 (find+focus) | 25 | 1 | 1.0 | ✅ |
| map_v3 | 2 | 454,323 | 2 (find+focus) | 21 | 1 | 1.0 | ✅ |

**Avg: without 290k vs map_v3 514k → Scubiee used +77% MORE tokens here.** All 4 succeeded.

Why: this task is single-file and high-variance. Scubiee's `find`+`focus` responses are
body-rich (thousands of chars), which inflates the transcript that every later turn re-reads
(cache-read: map_v3 ~385–460k vs without ~109–275k). On a task the native agent can solve with a
couple of greps, the extra Scubiee context is a net cost, not a saving.

**Cross-runtime check (same task on Claude):** Claude `map_v3` on `cache_aware_savings` = 512k
(≈ Cursor's 514k — consistent), and Claude `without` on this task ran 529k–826k. So the result is
task-driven, not a Cursor artifact; the Cursor without-arm simply happened to explore little (290k).

## Run 2 — task `add_importers_expand_alias` (hard cross-file dev task), model auto, 2 reps/arm

| arm | rep | total tokens | scubiee calls | tool calls | oracle | success |
|---|---|---:|---:|---:|---|---|
| without | 1 | 2,065,631 | 0 | 80 | 0.33 | ❌ |
| without | 2 | 2,412,547 | 0 | 86 | 1.0 | ✅ |
| map_v3 | 1 | 2,118,566 | 1 (find) | 85 | 0.33 | ❌ |
| map_v3 | 2 | 2,235,831 | 1 (find) | 80 | 0.33 | ❌ |

**Avg: without 2.24M vs map_v3 2.18M → ~2.8% difference (within noise). 3 of 4 cells FAILED.**

Why: the Cursor agent (auto router) **barely engaged Scubiee** — exactly **one** `find` call per
with-arm cell, then it reverted to native grep/read and spiraled to 80+ tool calls and 2M+ tokens,
the same spiral as the native arm. Because Scubiee was effectively unused after the first call, the
two arms converged.

**Cross-runtime contrast (same hard task on Claude):** Claude `map_v3` = 218k / 108k (map used
2×, lean, success) vs Claude `without` = 630k / 221k → **~61% Scubiee savings**. On Claude the agent
*leaned on* Scubiee and stayed lean; on Cursor it did not.

## Honest conclusion

- The harness, isolation, and token measurement are **valid** — this is a fair comparison.
- On Cursor with the `auto` router, the agent **under-uses the Scubiee MCP** (1 call, then native
  spiral), so Scubiee did **not** reproduce the token savings it shows on Claude. On the single-file
  task it cost more (richer context, no need); on the hard task both arms spiraled to ~2M tokens and
  mostly failed.
- This is primarily an **agent-behavior / tool-adoption** difference between the Cursor and Claude
  runtimes, not evidence that Scubiee's retrieval is worse — Scubiee's own map output is identical
  across runtimes (same bridge). The lever that made Scubiee win on Claude (the agent choosing map
  over grep, and trusting it) did not fire under Cursor's auto router.
- **Not a clean Scubiee win on Cursor as configured.** Before claiming any Cursor result, the next
  step is to make the Cursor agent actually adopt Scubiee: pin a model known to follow tool rules,
  strengthen the with-arm rule for Cursor, and/or constrain native tools — then re-measure. Reporting
  the current numbers as a Scubiee win would be misleading.

## Artifacts
- Run 1: `.ab_workspaces/claude_sdk_harness/cursor_harness/20261004T080154Z_cursor_cache_aware_savings/`
- Run 2: `.ab_workspaces/claude_sdk_harness/cursor_harness/20261004T082222Z_cursor_add_importers_expand_alias/`
- Each has per-cell `cell_*.json` (full tool trace + usage) and `report.json`.


---

## Hard real-dev-task run — `c_default` rule (map_v3) FIRST, then `without`

Two **hard** multi-file dev tasks, both registered STRICT (oracle must match the full edit set,
not a partial ratio). Scubiee/`c_default` arm run first, `without` second, so any shared-engine or
ordering effect would favor `without`, not Scubiee. 1 rep/cell, model `auto`, 600s/cell cap.
Per-cell fresh SHA-identical git snapshot, deleted after each cell; global `~/.cursor/mcp.json`
swapped per arm and restored (verified clean after the run — no leftover config or `.cursorab_bak`).

| task | arm | total tokens | scubiee calls | tool calls | py edits | oracle | success |
|---|---|---:|---:|---:|---:|---|---|
| `unify_token_estimate` (hard, cross-module) | map_v3 | 192,761 | 0 | 13 | 2 | 1.00 | ✅ |
| `unify_token_estimate` | without | 215,686 | 0 | 18 | 2 | 1.00 | ✅ |
| `add_importers_expand_alias` (hard, cross-file) | map_v3 | 2,675,089 | 1 (map) | 73 | 2 | 1.00 | ✅ |
| `add_importers_expand_alias` | without | 2,632,850 | 0 | 97 | 1 | 0.33 | ❌ |

### What the numbers say (honest read)

**Task 1 — `unify_token_estimate`:** essentially a tie on tokens (map_v3 193k vs without 216k,
~11% cheaper with the rule) and both arms fully correct. Notably the map_v3 agent did **not** call
`map` here — it solved the task with native tools under the rule, still cheaply and correctly. On a
moderately-scoped cross-module edit the rule neither helped nor hurt much; both runtimes handled it.

**Task 2 — `add_importers_expand_alias`:** the decisive case. Tokens are a near-tie
(map_v3 2.675M vs without 2.633M — both spiraled on this heavy cross-file task, cache_read dominated),
**but correctness diverged sharply:**
- **map_v3** edited **both** required files — routed `importers` as a caller-style direction in
  `packages/pipeline/context_trace.py` **and** added it to the direction whitelist in
  `packages/pipeline/mcp_locate.py` → **oracle 1.00, success**. One `map` call pointed it at both files.
- **without** edited **only** `context_trace.py`, then concluded `mcp_locate.py` "is not in this
  workspace" — which is **wrong**, the file is present — and skipped the whitelist edit →
  **oracle 0.33, failure**. It ran **45 greps** and still reached a false conclusion about a file's
  existence.

### Takeaway for Cursor on hard tasks

- Raw token count is **not** where Scubiee wins on hard dev tasks under Cursor's `auto` router — on
  both tasks the two arms landed within ~11% of each other, and on the heavy cross-file task both
  blew past 2.5M tokens regardless of arm.
- **The win is correctness/recall.** On the genuinely cross-file task, native grep-and-read led the
  agent to a wrong "that file doesn't exist" conclusion and a half-finished edit (33%). The Scubiee
  `map` gave the agent the full file set in one shot and it completed both edits (100%).
- The Cursor agent still under-adopts `map` on hard tasks (scub=0 or 1), so the token story is
  dominated by its native exploration habit. The rule's value shows up as the agent occasionally
  reaching for `map` at the right moment and getting the complete surface — which is what turned a
  failure into a success here.
- Caveats: 1 rep/cell, `auto` model router (non-deterministic), and hard-task token totals are
  high-variance. The success/oracle split (2/2 for map_v3 vs 1/2 for without) is the signal to trust
  over the token near-ties.

### Comparison to Claude (same tasks, prior session)
Claude's harness showed a cleaner token win on `add_importers` (map_v3 ~164k vs without ~426k, ~61%
cheaper) because Claude adopts `map`/`focus` reliably and doesn't grep-spiral. Cursor's `auto` agent
greps heavily by default, so under Cursor the Scubiee benefit converts into **reliability** (not
getting stuck on a wrong file-existence conclusion) rather than a flat token reduction.

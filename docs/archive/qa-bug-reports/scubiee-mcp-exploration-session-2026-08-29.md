# Scubiee MCP Exploration Session — Agent Experience Log

**Date:** 2026-08-29  
**Evaluator:** Cursor agent (Composer)  
**Surface:** `phase` (`map | focus | grep | glob | workspace | expand | gate | status`)  
**Repo:** `context-engine` (managed, `ce_9d8eb3aef9a744c5ef479299c6666aa5`)  
**Session ID:** `cursor@conn-f312b0`  
**Method:** Broad exploratory locate — random topic sampling, deep focus reads, grep/glob edge cases, then on-disk log verification

---

## Executive summary

Scubiee MCP is **highly effective for repo understanding** when the agent follows the recommended trajectory (`map` → `focus(outline)` → `focus(span)` → `grep` for literals). Semantic map queries with code vocabulary consistently returned relevant cards across 15+ unrelated topic areas. Session deduplication, heatmap tracking, and symbol-resolving focus all worked as designed.

Main friction points:

1. **Daemon dropped once** during a parallel map batch (`Remote end closed connection`) — no auto-retry.
2. **`glob` silently ignores wrong param names** — passing `glob:` instead of `pattern:` falls back to `**/*` with no error.
3. **`status()` readiness is ambiguous** — `healthy: true` coexists with `ready: false`, `syncing: true`.
4. **Nonsense map queries still return 8 cards** — no low-confidence or empty-state signal.
5. **Keeper never converges** on 5 AGENTS.md variant paths — sync stuck in `processing` all session.

---

## Session statistics

| Metric | Value |
|--------|-------|
| Total MCP tool calls | ~45 |
| Map queries | 19 (10 unique topics; 1 duplicate detected) |
| Focus calls | 16 (outline + span + neighbors + symbol query) |
| Grep calls | 4 |
| Glob calls | 5 |
| Expand calls | 1 |
| Workspace / status calls | 4 |
| Spans stored (handles) | 14 (`sp_0001` → `sp_0014`) |
| Focus-seen keys | 18 |
| Approx prompt tokens (ledger) | ~300 |
| Index size | 472 files, 3931 chunks |
| Daemon failures | 1 (recovered on manual retry) |

---

## Repo understanding gained (via MCP only)

### Pipeline architecture

```text
Files → Merkle diff → Graphify AST → enrich → compress → embed (CodeRank FP16)
     → TurboQuant/FAISS → Conductor (Graphify + BM25 + dense RRF) → locate/map
     → MCP phase tools → session store (dedup handles)
```

### Runtime managers

| Manager | Module | Role |
|---------|--------|------|
| **RuntimeManager** | `packages/pipeline/ce_service.py` | Workspace lifecycle, publish search generation, serve queries |
| **IndexManager** | `packages/pipeline/index_manager.py` | Merkle probe, full index, incremental sync |
| **ResourceManager** | `packages/pipeline/resources.py` | CPU/RAM admission and embed batching |

Watchdog sidecar: `packages/pipeline/watchdog.py` — polls `/health`, calls `force_restart_daemon`. Disable with `CTX_WATCHDOG=0`.

### Key packages discovered

| Package | Purpose |
|---------|---------|
| `packages/pipeline/` | Daemon, MCP server (`mcp_locate.py`), indexing, session store |
| `packages/graphify/` | AST parsing, repo IR, graph extraction, entity dedup |
| `packages/conductor/` | Fused retrieval (Graphify + BM25 + dense RRF) |
| `packages/hybrid_cbm/` | CBM–CE hybrid facade |
| `packages/enrich/` | Chunk metadata injection without second AST parse |
| `packages/parse_harness/` | AST bake-off harness (Graphify vs alternatives) |

### MCP layer (`phase` surface)

Tools exposed: `gate`, `status`, `map`, `focus`, `grep`, `glob`, `workspace`, `expand`.

Implementation entry points in `mcp_locate.py`:

| Function | Line |
|----------|------|
| `grep_impl` | 2076 |
| `glob_impl` | 2327 |
| `map_impl` | 2447 |
| `focus_impl` | 2511 |
| `gate_impl` | 2771 |
| `status_impl` | 2784 |

Default surface after setup: `CTX_MCP_SURFACE=phase`.

### Topics explored via map

| Query area | Top map hit | Quality |
|------------|-------------|---------|
| Daemon / watchdog | `watchdog.py`, `daemon.py` | Excellent |
| Merkle / incremental sync | `merkle.py`, `incremental.py`, `chunk_merkle.py` | Excellent |
| Graphify AST | `graphify/extract.py`, `build.py`, `dedup.py` | Excellent |
| Embed backends (MLX/CUDA/DML) | `coreml_mac.py`, `test_mlx_backend.py` | Good |
| Dashboard / HTTP API | `dashboard_server.py`, `server.py` | Good |
| Session isolation | `session_store.py`, `session_isolation.py` | Excellent |
| Capability cards | `capability.py` (score 41.5) | Excellent |
| CLI lifecycle (wipe/init/connect) | `wipe.py`, `project_id.py`, `repo_lifecycle.py` | Excellent |
| FAISS / TurboQuant | `vectordb.py`, `turbo_quant.py` | Excellent |
| Host workspace resolution | `host_workspace.py`, `test_global_mcp_hosts.py` | Excellent |
| Token gating | `templates/scubiee.md`, `test_token_efficient_gating.py` | Good |
| Locate fusion / RRF | `locate.py`, `conductor/rrf.py` | Good |
| Resource admission | `pause_resume.py`, `memory_budget.py` | Good |
| Agent eval harness | `test_mcp_agent_eval_regressions.py`, `run_scubiee_eval_v3.py` | Excellent |
| Error recovery (vague NL) | `locate.py`, `tests/_mcp_resilience_exp.py` | Fair (vague) |
| Nonsense query | `server.py` HTTP handler | Poor (false positives) |

---

## Tool-by-tool experience

### `gate()`

- Returns minimal project ID: `1:ce_9d8eb3aef9a744c5ef479299c6666aa5`
- Fast, ~5 tokens — works as intended

### `status()`

- Rich health payload: chunks, embed model, keeper state, dirty paths, session ledger
- **Issue:** contradictory flags — see P1 below
- Useful fields: `engine.healthy`, `session.n_spans`, `session.ledger.approx_prompt_tokens`

### `map()`

- **Best tool for cold start** — code-vocabulary queries (20–60 tokens) consistently hit relevant modules
- Cards include `rank`, `file`, `start_line`, `end_line`, `score`, `why`, optional `span_hint`
- **Duplicate detection:** re-running same query returns `usage_hint: Advisory: this map query already ran` but still executes
- **Failure:** one call failed mid-batch with daemon connection drop; retry succeeded
- **Null line ranges:** some top cards have `start_line: null` — requires extra `focus(outline)` step
- **BOM artifacts:** `\ufeff` prefix visible in `why` snippets for some indexed files
- **`facade_hint`:** useful on thin wrapper files (e.g. `context_agent/tools.py` → grep for real impl)

### `focus(outline)`

- Excellent on Python files: `mcp_locate.py` (60/71 symbols), `capability.py` (32), `locate.py` (23)
- Markdown files: returns `language_unsupported: true` with clear note — wastes one call if agent doesn't know

### `focus(span)`

- Returns `handle`, line ranges, code body, `truncated` + `next_start_line` when capped
- **Dedup works:** re-fetch returns `status: already_in_session`, empty `code`, preserved handle
- **Symbol query inside file works:** `focus(target="incremental.py", query="ensure_fresh_for_search")` → lines 766–883

### `focus(neighbors)`

- Import-adjacent neighbors returned inline with code snippets
- On already-fetched span: center `code` empty but neighbors still useful

### `grep()`

- Reliable for exact literals with `glob` file filter
- Examples: 24 hits for `RuntimeManager|IndexManager|ResourceManager`, 44 MCP test functions, 82 `CTX_MCP_SURFACE` refs

### `glob()`

- Works when `pattern` param is used correctly
- **Critical bug:** passing `glob:` (mirroring grep's param name) silently defaults to `**/*` — no error
- `packages/*` returned 0 files; `packages/pipeline/*.py` returned 30 (truncated)
- `packages/graphify/**/*.py` returned 15 files correctly

### `workspace(show)`

- Best reorientation tool: heatmap, spans, focus_seen, map_queries
- Heatmap tracks per-file hits, roles, and originating map queries
- Matches on-disk `work_session.json` exactly

### `expand(handle)`

- Re-materializes stored span with char budget
- Returns truncated body + hint to use `recall()` for other handles

---

## On-disk log verification

Logs checked at: `.scubiee/sessions/cursor@conn-f312b0/`

### `session_store.json`

- Stores **full span text** server-side (not just handles/excerpts)
- Each span: `content_hash`, `serve_count`, `created_ts`, `last_served_ts`, `source: "read"`
- README span served 3× — dedup confirmed in disk log (`serve_count: 3`)
- Topic field tracks last focus target
- **Concern:** disk growth on long sessions; sensitive code persisted locally

### `work_session.json`

- Per-file heatmap with hit counts, roles, and full query attribution
- Example: `mcp_locate.py` — 7 hits, 5 distinct map queries recorded
- Map query history preserved for session replay / debugging

### Other session dirs observed

- `cursor@conn-d612b0`, `cursor@chat-2`, `scubiee-eval-3` — parallel sessions exist

---

## Issues and recommendations

### P0 — Daemon dropped mid-batch

**Observed:**

```json
{
  "ok": false,
  "error": "Scubiee unreachable at http://127.0.0.1:8765: Remote end closed connection without response"
}
```

During parallel `map()` calls. Retry succeeded immediately. Likely daemon restart during keeper sync (37 live batches observed).

**Impact:** Agent loses one map result silently unless it retries.

**Recommendation:** Auto-retry `map`/`focus` once on connection drop; return `should_retry: true` in error payload.

---

### P0 — `glob` silent parameter mismatch

**Observed:** Passing `glob: "packages/*"` instead of `pattern: "packages/*"` silently falls back to `pattern: "**/*"`. Returns root-level files (`.env`, `uv.lock`) with no warning.

**Impact:** Agent believes it listed packages when it got repo root.

**Recommendation:** Reject unknown params; alias `glob` → `pattern`; or emit `pattern_ignored: true` when default is used.

---

### P1 — `status()` contradictory readiness

**Observed at session end:**

| Field | Value |
|-------|-------|
| `engine.healthy` | `true` |
| `soft_search_ready` | `true` |
| `ready` | `false` |
| `syncing` | `true` |
| `overlay_ready` | `true` (improved from `false` at start) |
| `publish_pending` | `true` |

**Impact:** Agent cannot determine "safe to query" vs "results may be stale" from one field.

**Recommendation:** Add top-level `agent_ready: "yes" | "warming" | "stale"` summary.

---

### P1 — Nonsense queries return ranked cards

**Query:** `nonexistent_module_xyz_foo_bar baz qux handler`

**Result:** 8 cards including `server.py` HTTP `_read_json(handler)`, `dispatch_tool`, unrelated docs.

**Impact:** No signal that results are low-confidence noise.

**Recommendation:** Return `confidence: low` or fewer cards when max score is below threshold; or explicit `"weak_match": true` on cards.

---

### P1 — Documentation vs live tool names

`docs/context-engine-mcp.md` documents `search`, `read`, `outline`. Live `phase` surface exposes `map`, `focus`, `grep`, `glob`.

**Impact:** Agents following docs call wrong tool names.

**Recommendation:** Add `phase` surface section to docs; or alias tools in documentation.

---

### P2 — Duplicate map query still executes

Re-running lifecycle query returned same cards plus advisory hint but still hit the daemon.

**Recommendation:** Short-circuit to cached cards from `work_session.json` query history.

---

### P2 — Map cards with null line ranges

Top cards for `mcp_server.py`, `server.py`, `capability.py` sometimes have `start_line: null, end_line: null`.

**Recommendation:** Always populate line ranges or add `"needs_outline": true`.

---

### P2 — BOM in indexed snippets

Map `why` fields show `\ufeff` prefix on `mcp_locate.py`, `client.py`, `test_mcp_locate.py`.

**Recommendation:** Strip BOM at index time.

---

### P2 — `glob("packages/*")` returns empty

Even with correct `pattern` param. `packages/graphify/**/*.py` works.

**Recommendation:** Document directory listing patterns; fix `packages/*` matching.

---

### P3 — Keeper stuck on AGENTS.md variants

Whole session: 5 paths permanently dirty/processing with `chunks_upserted: 0`:

- `.config/amp/agents.md`
- `.config/opencode/agents.md`
- `.copilot/copilot-instructions.md`
- `.copilot/instructions/scubiee.instructions.md`
- `.pi/agent/agents.md`

Merkle root hash never converges (`clean: false`). Map still worked but may explain daemon restarts.

**Recommendation:** Investigate duplicate AGENTS.md symlink/copy handling in keeper loop.

---

### P3 — Session isolation warning

Every response includes hint that `cursor@conn-f312b0` may be shared across parallel Cursor chats.

**Recommendation:** Auto-generate per-chat `session_id` in Cursor MCP config; surface prominently in `gate()`.

---

## What worked well (keep)

1. **Code-vocabulary map queries** — 15/15 topic areas returned relevant top-3 hits
2. **`focus(outline)`** on Python — exact line ranges for symbols
3. **`focus(neighbors)`** — instant import graph for wiring discovery
4. **`grep` with glob filter** — precise literal search every time
5. **`workspace(show)` heatmap** — best session reorientation; matches disk logs
6. **Session dedup** — `already_in_session` + incrementing `serve_count` in API and disk
7. **Truncation hints** — `next_start_line` and explicit follow-up focus suggestion
8. **`facade_hint` on map cards** — guides agent away from thin wrappers
9. **Symbol-resolving focus** — `focus(target=path, query=symbol)` inside known file

---

## Recommended agent workflow (validated)

```text
gate()                          → confirm managed
status()                        → optional health check
map(code-vocabulary query)      → ranked cards, no bodies
focus(outline) on Python hit    → symbol line ranges
focus(span, start_line, end_line) → code + handle
grep()                          → exact literals only, after map
glob(pattern=...)               → NOT glob=... (use pattern param)
workspace(show)                 → reorient mid-session
expand(handle)                  → re-materialize when body needed again
```

---

## Suggested harness additions

Based on this session, add automated checks for:

1. Parallel 8× `map()` — no unhandled daemon drops (or auto-retry works)
2. `glob` with wrong param name — must error, not default silently
3. Nonsense map query — expect `confidence: low` or fewer than 3 cards
4. Duplicate map query — return cached cards without HTTP round-trip
5. `status()` — assert single unambiguous readiness field
6. Long session — `session_store.json` size stays under budget
7. Keeper convergence — AGENTS.md variant paths don't block `clean: true` forever
8. Re-fetch span — returns `already_in_session` with empty body and valid handle

---

## Spans collected this session

| Handle | File | Lines | Serve count |
|--------|------|-------|-------------|
| `sp_0001_96a58f` | `README.md` | 1–80 | 3 |
| `sp_0002_2ffab6` | `packages/pipeline/mcp_locate.py` | 1–67 | 2 |
| `sp_0003_ae447b` | `docs/context-engine-mcp.md` | 1–120 | 1 |
| `sp_0004_c168b5` | `packages/pipeline/session_store.py` | 266–389 | 1 |
| `sp_0005_62fcaf` | `packages/conductor/conductor.py` | 1–53 | 1 |
| `sp_0006_2fa555` | `packages/pipeline/watchdog.py` | 1–26 | 1 |
| `sp_0007_f8bd47` | `packages/pipeline/merkle.py` | 1–88 | 1 |
| `sp_0008_d4b6bf` | `packages/pipeline/project_id.py` | 1–50 | 1 |
| `sp_0009_8d799f` | `packages/pipeline/host_workspace.py` | 1–158 | 1 |
| `sp_0010_1049b8` | `packages/pipeline/locate.py` | 419–618 | 1 |
| `sp_0011_9a0de3` | `packages/graphify/dedup.py` | 1–18 | 1 |
| `sp_0012_0ec0cb` | `packages/pipeline/memory_budget.py` | 1–44 | 1 |
| `sp_0013_a1051e` | `packages/pipeline/incremental.py` | 766–883 | 1 |
| `sp_0014_30fae2` | `tests/_mcp_resilience_exp.py` | 1–38 | 1 |

---

## Related docs

- [Scubiee MCP Agent Evaluation](./scubiee-mcp-agent-evaluation.md)
- [Scubiee MCP Eval v3 Retest](./scubiee-mcp-eval-v3-retest.md)
- [Context Engine MCP Architecture](./context-engine-mcp.md)
- [MCP Resilience Experiments](../tests/_mcp_resilience_exp.py)

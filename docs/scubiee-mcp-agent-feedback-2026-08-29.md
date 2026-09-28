# Scubiee MCP Agent Feedback — Live Session

**Date:** 2026-08-29  
**Evaluator:** Cursor agent (Composer)  
**Method:** Scubiee MCP tools only — no pytest, no local harness scripts  
**Surface:** `phase` (`gate | status | map | focus | grep | glob | workspace | expand`)  
**Repo:** `context-engine` (managed)  
**Project ID:** `ce_f01682314e33b2beb8cf8c0c8782bc43`  
**Session ID:** `cursor@conn-657230` (shared transport session)  
**Prior log:** [scubiee-mcp-exploration-session-2026-08-29.md](./scubiee-mcp-exploration-session-2026-08-29.md)

---

## Executive summary

Scubiee MCP is **production-usable for agent locate** on this repo. Semantic `map` consistently finds the right modules across unrelated domains (conductor fusion, graphify extractors, sync loop, rules install, daemon lifecycle, host workspace). The `map → focus(outline) → focus(span)` trajectory is fast, and session deduplication saves meaningful tokens.

**Overall grade: A-** (up from ~B in the first exploration session on 2026-08-29 morning).

The single highest-impact bug found live: **`_assess_map_confidence` uses 0–1 thresholds but map scores are ~1–30**, so gibberish queries report `confidence: "high"` despite `max_score: 2.47`. Everything else is polish, sync noise, or agent-ergonomics.

---

## Session statistics

| Metric | Value |
|--------|-------|
| MCP tool calls (this session) | ~42 |
| Map queries | 18 unique topics (+ 2 duplicate/cache hits) |
| Focus calls | 14 (outline, span, neighbors, symbol) |
| Grep calls | 3 |
| Glob calls | 4 |
| Expand calls | 1 |
| Gate / status / workspace | 5 |
| Parallel map burst (8 concurrent) | 0 daemon drops |
| Spans stored | 15 handles (`sp_0001` → `sp_0015`) |
| Focus-seen keys | 18 |
| Approx prompt tokens (ledger) | ~375 |
| Index at end | 477 files, 3977 chunks |
| Engine | `healthy: true`, `agent_ready: "stale"` |

---

## Tool-by-tool assessment

### `gate` — **A**

One line, immediately actionable:

```text
1:ce_f01682314e33b2beb8cf8c0c8782bc43 sid:cursor@conn-657230 shared
```

Confirms managed repo, project ID, and session sharing risk without calling `status()`. Best first call in any chat.

### `status` — **B+**

**Works well:**
- `agent_ready: "stale"` — the field agents actually need while keeper syncs
- `engine.healthy`, `soft_search_ready`, chunk/file counts
- Keeper dirty-path state with normalized keys vs raw paths
- Session ledger summary (`n_spans`, `approx_prompt_tokens`)

**Friction:**
- `ready: false` + `syncing: true` + `healthy: true` still requires institutional knowledge; add `agent_ready_note`
- Payload can be very large when `last_sync.files` is populated
- Keeper perpetually reports 5 AGENTS.md variants as `added` (`clean: false` every probe)

### `map` — **A-**

**Strengths observed:**

| Query domain | Top hit | Score |
|--------------|---------|-------|
| Conductor fusion | `packages/conductor/conductor.py` | 8.36 |
| Index / merkle | `packages/pipeline/index_manager.py` | 16.91 |
| Graphify AST | `packages/enrich/__init__.py` | 34.12 |
| Rules install | `packages/pipeline/rules_installer.py` | 17.82 |
| Context agent | `packages/pipeline/context_agent/__main__.py` | 16.52 |
| Session store | `packages/pipeline/session_store.py` (put_span) | 19.43 |
| Sync loop | `packages/pipeline/sync_loop.py` | 16.85 |
| Daemon lifecycle | `packages/pipeline/daemon.py` (ensure_daemon) | 24.14 |
| MCP internals | `packages/pipeline/mcp_locate.py` (_assess_map_confidence) | 19.88 |
| Graphify extractors | `packages/graphify/extract.py` | 15.47 |
| Host workspace | `docs/global-mcp-hosts-research.md` | 15.51 |

**Good UX signals:**
- `needs_outline: true` on cards with null line ranges — prompts `focus(outline)` before blind span reads
- `span_hint: "large chunk — use focus(outline) then line ranges"` on big hits (e.g. `locate.py`)
- `facade_hint: true` + `follow_up` on thin package stubs (e.g. `hybrid_cbm/__init__.py`)
- Duplicate query → `cached: true` + `usage_hint: "Prefer focus() on prior hits"`
- `k=3` respected on re-query; cache trims to requested k
- Gibberish query card count reduced (6 vs 8 in prior session) — partial improvement

**Issues:**

1. **Gibberish confidence still `"high"`**  
   Query: `xyzzy_plugh_garply_frotz_quux nonsense gibberish no_match`  
   Result: 6 cards, `confidence: "high"`, `max_score: 2.466`  
   Root cause visible via symbol focus on `_assess_map_confidence`:

   ```python
   if max_score < 0.08 or (... and max_score < 0.22):
       return {"confidence": "low", ..., "weak_match": True}
   if max_score < 0.15:
       return {"confidence": "medium", ...}
   return {"confidence": "high", ...}
   ```

   Live scores are **not** normalized to 0–1. Thresholds should be calibrated to the actual score scale (e.g. `< 5.0` → low).

2. **Test/meta files rank highly** on vague or meta queries (`test_mcp_exploration_regressions.py` appears in heatmap with 8 hits). Expected for this repo but may mislead agents on cleaner codebases.

3. **Stale vendored copy indexed** — `scubiee-0.2.61/packages/graphify/transcribe.py` appears alongside `packages/graphify/transcribe.py` in graphify map results.

### `focus` — **A-**

**Modes tested:**

| Mode | Result |
|------|--------|
| `outline` (Python) | 10–22 symbols with line ranges; uncapped when small |
| `outline` (Markdown) | `language_unsupported: true` + note to use `span` — clear |
| `span` (line range) | Correct code; `max_chars` truncation with `next_start_line` |
| `span` (symbol query) | Usually correct; **one mis-route** (see bugs) |
| `neighbors` | Import adjacency with inline neighbor snippets — excellent for wiring |

**Dedup works:**
- Re-fetch same span → `already_in_session`, empty body, handle preserved
- `usage_hint` points to `expand(handle)` or `workspace(show)`

**BOM visible in span/neighbors output** for UTF-8-BOM files (`sync_loop.py`, `incremental.py` show leading `\ufeff` in code block). `expand()` on `dirty_ledger` span was BOM-free — inconsistent strip behavior.

### `grep` — **A**

- Exact literal `def put_span` → 1 hit at line 266
- Broad `CTX_MCP_SURFACE` → 90 hits across docs/tests/pipeline; not truncated
- Regex `def test_.*map` in `tests/*.py` → 14 hits including exploration regression tests

Reliable fallback after map; default glob `**/*` is appropriate.

### `glob` — **A**

| Pattern | Behavior |
|---------|----------|
| `glob=` alias | `pattern_source: "glob_alias"` — fixed from prior session |
| `packages/*` | Lists 10 package dirs |
| `packages/pipeline/*.py` | 88 modules |
| `pattern="."` | Orient mode: dirs + top-level files |
| `tests/test_mcp*.py` | 6 MCP test files |

### `expand` — **A-**

Re-materialized `sp_0007_cc55f7` (`normalize_dirty_path` in `dirty_ledger.py`) cleanly — 499 chars, no BOM, no truncation. Essential after dedup.

### `workspace` — **A**

Best session memory tool:
- Heatmap ranks files by map/focus activity with roles and last queries
- Spans list with serve counts
- `focus_seen` prevents redundant re-fetch
- `map_queries` history for reorientation

After ~40 calls, heatmap correctly showed `mcp_locate.py` and `test_mcp_exploration_regressions.py` as hottest files.

---

## Bugs and friction (prioritized)

### P0 — Map confidence thresholds wrong scale

**Symptom:** Nonsense queries return `confidence: "high"`.  
**Evidence:** Gibberish query `max_score: 2.466` + `"high"`; `_assess_map_confidence` compares against `0.08`, `0.15`, `0.22`.  
**Fix:** Calibrate thresholds to live score distribution, or normalize scores before assess. Propagate `weak_match: true` on individual cards when top score < N.

### P1 — Symbol focus can return wrong symbol in target file

**Symptom:** `focus(target=rules_installer.py, query=write_cursor_rule)` returned `gate_line_for_repo` (lines 112–128), not `write_cursor_rule`.  
**Correct file:** `write_cursor_rule` lives in `mcp_install.py:163–174` (confirmed with correct target).  
**Impact:** Agents editing the wrong function if they trust symbol query without checking name in code block.

### P1 — `call_sites` mode advertised but not implemented

**Symptom:** `focus(mode=call_sites)` → validation error: only `outline|span|neighbors` allowed.  
**Evidence:** Neighbors response says `"See call_sites for literal references"` but mode doesn't exist.  
**Fix:** Implement `call_sites` or remove hint from neighbors `next` field.

### P2 — UTF-8 BOM leaks into focus code blocks

**Symptom:** `\ufeff` prefix in `sync_loop.py` and `incremental.py` span/neighbors output.  
**Impact:** Copy-paste edits may include invisible BOM; agents may misread first line.

### P2 — Keeper never converges on AGENTS.md variants

**Symptom:** Every `status()` probe: `clean: false`, 5 paths perpetually `added`:
- `.config/amp/agents.md`
- `.config/opencode/agents.md`
- `.copilot/copilot-instructions.md`
- `.copilot/instructions/scubiee.instructions.md`
- `.pi/agent/agents.md`

Locate still works; background sync churn continues (`locate_streak_active: true` during heavy MCP use).

### P2 — Session sharing requires manual isolation

Every tool repeats shared-session hint. Gate surfaces it well, but parallel Cursor chats share `cursor@conn-*` unless `CTX_MCP_SESSION_ID` is set per chat.

### P3 — `status()` payload size

Full keeper sync details inline. Consider truncating file lists or gating verbose fields behind a flag.

### P3 — Stale `scubiee-0.2.61/` tree in index

Duplicate hits for vendored/old package copies. Consider exclude patterns for versioned snapshot dirs.

---

## Repo understanding gained (MCP only)

### Architecture (confirmed across 18 map topics)

```text
Files → Merkle diff → Graphify AST → enrich (RepoIR metadata) → embed (CodeRankEmbed)
     → TurboQuant/FAISS → Conductor (Graphify + BM25 + dense RRF) → locate/map
     → MCP phase tools → session_store (handles, dedup, heatmap)
     → BackgroundSyncLoop (keeper) + DirtyLedger + dirty_journal
```

### Key modules touched this session

| Area | Primary files |
|------|---------------|
| MCP surface | `packages/pipeline/mcp_locate.py` |
| Retrieval | `packages/conductor/conductor.py`, `packages/pipeline/locate.py` |
| Indexing | `packages/pipeline/index_manager.py`, `incremental.py`, `indexer.py` |
| Live sync | `packages/pipeline/sync_loop.py`, `dirty_ledger.py`, `dirty_journal.py` |
| Agent readiness | `packages/pipeline/sync_status.py` (`derive_agent_ready`) |
| Session memory | `packages/pipeline/session_store.py`, `work_session.py` |
| Connect / rules | `packages/pipeline/rules_installer.py`, `mcp_install.py` |
| Daemon | `packages/pipeline/daemon.py`, `client.py`, `watchdog.py` |
| Graph | `packages/graphify/extract.py`, `packages/enrich/__init__.py` |
| Host integration | `packages/pipeline/host_workspace.py` |
| Docs | `docs/context-engine-mcp.md` (phase tool table indexed) |

### Conductor fusion (read via focus span)

`Conductor.retrieve_conductor` min-ranks Graphify affinity vs BM25+dense hybrid per file, applies agree bonus when both signals align, expands via graph neighbors — all visible in a 40-line focus span without reading the full 187-line file.

---

## Improvements since first exploration session

| Issue (morning session) | Status now |
|-------------------------|------------|
| `glob:` param silently ignored | **Fixed** — `glob=` alias, `pattern_source: "glob_alias"` |
| `packages/*` didn't list dirs | **Fixed** |
| No `agent_ready` field | **Fixed** — `"stale"` while syncing |
| Duplicate map re-search | **Fixed** — `cached: true` + usage hint |
| Doc mismatch (phase tools) | **Fixed** — `docs/context-engine-mcp.md` indexed with tool table |
| Gate missing session hint | **Fixed** — inline `sid:… shared` |
| Map cards null line ranges | **Fixed** — `needs_outline: true` |
| Daemon drop on parallel maps | **Not reproduced** — 8 parallel maps, 0 drops |
| Gibberish returns 8 cards | **Partial** — now 6 cards, still `confidence: high` |
| Keeper stuck `processing` | **Intermittent** — flips between `processing`, `published`, `queued` |

---

## Recommended agent workflow (validated)

```text
1. gate()                    → managed? project_id? session shared?
2. map(code-vocabulary q)    → pick 1–3 cards (check confidence + scores)
3. focus(outline)            → line ranges; required when needs_outline: true
4. focus(span | symbol)      → verify symbol name in returned code
5. focus(neighbors)          → wiring / imports (not call graph)
6. grep(literal)             → only after map; exact strings
7. glob(pattern | glob=)     → known paths; packages/* for orient
8. workspace(show)           → reorient; check focus_seen before re-fetch
9. expand(handle)            → body after already_in_session dedup
10. status()                 → agent_ready when editing indexed files
```

**Map query tips (observed):**
- Code vocabulary beats plain English (`keeper_tick dirty_journal overlay` > "how does sync work")
- Include snake_case symbols when known (`derive_agent_ready`, `_assess_map_confidence`)
- Sharpen and re-map on new topics; don't grep-thrash
- Treat `confidence: high` skeptically when `max_score < 5`

---

## Recommendations for Scubiee team

### Must fix
1. Recalibrate `_assess_map_confidence` thresholds to live score scale; add per-card `weak_match` when score < threshold.
2. Fix symbol focus mis-resolution (wrong function in file when query symbol absent).

### Should fix
3. Implement `call_sites` focus mode or remove neighbors hint.
4. Strip UTF-8 BOM consistently in all focus/expand code paths.
5. Add `agent_ready_note` one-liner to `status()` payload.
6. Investigate AGENTS.md keeper loop — merkle probe never `clean: true`.

### Nice to have
7. Truncate verbose `status()` file lists for MCP agents.
8. Exclude `scubiee-0.*` snapshot dirs from index.
9. Auto-assign per-chat `session_id` in Cursor MCP transport.
10. Surface map `confidence` + `max_score` in gate or map card headers when `weak_match`.

---

## Appendix: edge-case probe log

| Probe | Expected | Actual |
|-------|----------|--------|
| Gibberish map | empty or `confidence: low` | 6 cards, `confidence: high`, max 2.47 |
| Duplicate map | cache hit | `cached: true`, same cards |
| Map k=3 on prior query | 3 cards | 3 cards from cache |
| focus outline on .md | graceful fallback | `language_unsupported` + note |
| focus symbol wrong file | error or not found | wrong symbol returned |
| focus call_sites | reference search | validation error |
| glob alias | works | `pattern_source: glob_alias` |
| expand after dedup | full body | clean 499-char span |
| Parallel 8× map | no daemon drop | all ok |
| grep 90 hits | complete | not truncated |

---

*Generated from live Scubiee MCP session only. No pytest or `scripts/_mcp_retest_*.py` used.*

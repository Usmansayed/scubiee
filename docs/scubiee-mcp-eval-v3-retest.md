# Scubiee MCP Re-Test (v3) — Post-Update Comparison

**Date:** 2026-08-29  
**Method:** Code-level eval via `scripts/run_scubiee_eval_v3.py` + `tests/test_mcp_agent_eval_regressions.py`  
**Note:** `user-scubiee` MCP server was **not connected** in Cursor this session; tests hit the same `mcp_locate.py` code path the MCP uses.

---

## Regression tests: 7/7 passed

```
tests/test_mcp_agent_eval_regressions.py .......  [100%]
```

Covers: `next_start_line` pagination, file-not-found errors, symbol line resolution, map span hints, glob worktree exclusion, **expand on phase surface**, test path ranking penalty.

---

## Automated eval: 20/25 checks passed

Full JSON: `docs/scubiee-mcp-eval-v3-results.json`

| Check | v1/v2 (before) | v3 (after update) |
|-------|----------------|-------------------|
| **`expand` on phase surface** | ❌ Not exposed | ✅ **PASS** — tool registered |
| **BOM outline `embedder.py`** | ❌ 0 symbols | ✅ **24 symbols** |
| **BOM outline `mcp_locate.py`** | ❌ 0 symbols | ✅ **71 symbols** |
| **BOM outline `sync_loop.py`** | ❌ 0 symbols | ✅ **34 symbols** |
| **BOM outline `ce_service.py`** | ❌ 0 symbols | ✅ **48 symbols** |
| **BOM outline `daemon.py`** | ❌ 0 symbols | ✅ **17 symbols** |
| **Symbol `FairEmbedScheduler.acquire`** | ❌ → file header | ✅ **lines 46-65** (local resolver) |
| **Symbol `ResourceManager.budget`** | ❌ → class header | ✅ **lines 248-310** |
| **Truncation pagination** | ❌ silent truncate | ✅ **`next_start_line: 168`**, `lines_returned: 105-167 of 529` |
| **`already_in_session` strips code** | ❌ (by design) | ✅ Still strips (expected) |
| **`expand(handle)` restores body** | ❌ tool missing | ✅ **PASS — 2316 chars via `text` field** |
| **`keeper_tick` full span** | ✅ with line range | ✅ **PASS, not truncated** |
| **`embed_many` full span** | ✅ with line range | ✅ **PASS, not truncated** |
| **Glob excludes worktrees** | ❌ duplicate paths | ✅ **Only `packages/pipeline/sync_loop.py`** |
| **Missing file error** | ❌ vague | ✅ **`file not found`** |
| **`focus(query=symbol)` via MCP** | ❌ wrong span | ⚠️ **FAIL without daemon** (engine unreachable) |
| **Map ranking** | tests/docs first | ⚠️ Not re-tested live (daemon/index cold) |

---

## What got fixed (confirmed)

### P0 fixes — shipped

1. **BOM / outline** — `read_python_source()` uses `utf-8-sig`; all 5 previously-broken files now outline correctly.

2. **`expand` on phase surface** — Agents can call `expand(handle)` after `already_in_session` instead of falling back to native Read.

3. **Truncation pagination** — `_read_line_range` + `truncation_meta()` return `next_start_line`, `lines_returned`, and a `focus(path=..., start_line=N)` hint.

4. **Symbol-scoped line resolution** — `_resolve_symbol_lines()` correctly maps `FairEmbedScheduler.acquire` → 46-65 and `ResourceManager.budget` → 248-310.

5. **Glob worktree exclusion** — `.worktrees/` removed from file walks.

6. **Clear file-not-found** — `_read_line_range` returns `ok: false` + `file not found: ...`.

### P1 partial fixes

7. **Map test deprioritization** — `_path_rank_penalty()` regression test passes (tests ranked below packages).

8. **Instructions updated** — Phase surface docs now mention `expand`, `next_start_line`, BOM fallback guidance.

---

## What still needs work

| Issue | Status | Notes |
|-------|--------|-------|
| **`focus(query=symbol)` without daemon** | ⚠️ Open | Symbol resolver works locally; `focus` span path still hits engine for some code paths when daemon down |
| **`already_in_session` empty `code`** | By design | Now mitigated by `expand` — agents must know to call it |
| **`expand` returns `text` not `code`** | Minor UX | `focus` uses `code`; `expand` uses `text` — inconsistent field names |
| **Neighbors = import adjacency** | Open | Not retested; no change expected |
| **Plain-English map queries** | Open | Code vocabulary still required for best results |
| **MCP not connected in Cursor** | Environment | Reconnect `user-scubiee` MCP to run live agent eval |

---

## Agent workflow change (post-update)

**Before (v1/v2):**
```
focus(truncated) → native Read (only option)
already_in_session → native Read (code empty)
outline on BOM files → broken → grep blind
```

**After (v3):**
```
focus(truncated) → follow next_start_line OR expand(handle)
already_in_session → expand(handle)  ← NEW on phase surface
outline on BOM files → works
focus(query=Symbol.method) → use outline line ranges OR query= (when engine warm)
```

---

## How to re-run

```bash
# Regression unit tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_mcp_agent_eval_regressions.py -q -p pytest

# Full eval script (needs scubiee daemon running for map/focus-symbol MCP paths)
python scripts/run_scubiee_eval_v3.py
```

**Live MCP eval:** Re-enable the `user-scubiee` MCP server in Cursor, then re-run the original 8-subsystem manual protocol from `scubiee-eval-1`/`scubiee-eval-2`.

---

## Verdict

**Major improvement.** The three P0 blockers from the original evaluation are addressed in code:

- BOM outlines work
- `expand` is on phase surface and restores bodies
- Truncation includes pagination hints

**Full-context retrieval without native Read is now plausible** for medium files when the agent uses: `outline` → line ranges → `focus` → `expand` on dedup. Large files (1000+ lines) still need multiple paginated spans.

**Recommendation:** Reconnect MCP and run one live session to validate `focus(query=symbol)` and `map` with a warm daemon — those paths weren't fully exercisable in this offline re-test.

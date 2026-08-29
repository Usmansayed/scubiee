# Scubiee MCP Tools — Evaluation Feedback (v2)

**Date:** 2026-08-29  
**Repo:** `ce_f01682314e33b2beb8cf8c0c8782bc43` (477 files / 3991 chunks)  
**Session:** `cursor@conn-3e7230`  
**Source:** Live agent evaluation (all 8 phase-surface tools)

---

## Maintainer response (2026-08-29)

| Finding | Severity | Action |
|---------|----------|--------|
| `call_sites` returns 0 / definitions only | High | **Fixed** — searches `\bident\s*\(` call sites, skips `def`/`class` lines; parses `file.py:symbol` targets |
| `glob` skips `.scubiee/` | Medium | **Fixed** — explicit dot-dir patterns (e.g. `.scubiee/**`) descend into named dirs |
| Shared-session hint on every response | Low | Open — dedupe after `gate()` |
| NL map queries weak | Low | Already signaled via `confidence:low` / `weak_match` |
| `workspace` pin needs explicit `action` | Low | Open — improve param validation/docs |

Regression tests: `tests/test_mcp_agent_eval_regressions.py` (`test_call_sites_*`, `test_glob_explicit_dot_scubiee_dir`).

**Reload MCP** after pulling to pick up `call_sites` + glob fixes.

---

## Executive Summary

Scubiee’s **map → focus → expand** flow is strong and token-efficient. **`grep`** is reliable for exact matches. **`gate`** and **`status`** give clear readiness signals. The main gaps were **`call_sites`** (missed known references) and **`glob`** on dot-directories like `.scubiee/`. Session dedup (`already_in_session`) and duplicate-map warnings work well.

**Recommended workflow:** `gate()` → `map(query)` → `focus(outline|span)` → `expand(handle)` for edits; use `grep` for literals; use `workspace(show)` to reorient mid-session.

---

## Tool Readiness Scorecard

| Tool | Ready? | Agent confidence |
|------|--------|------------------|
| gate | Yes | High |
| status | Yes | High |
| map | Yes | High (with good queries) |
| focus (outline/span/neighbors) | Yes | High |
| focus (call_sites) | Fixed pending reload | Was: use grep instead |
| grep | Yes | High |
| glob | Fixed pending reload | Was: avoid dot-dirs |
| workspace | Yes | High |
| expand | Yes | High |

Overall: **7/8 tools production-ready** at evaluation time; `call_sites` + dot-dir `glob` addressed in code.

---

## Tool-by-Tool Results

### 1. `gate` — Session bootstrap

**Output:**
```
1:ce_f01682314e33b2beb8cf8c0c8782bc43 sid:cursor@conn-3e7230 shared
Session 'cursor@conn-3e7230' may be shared across parallel chats...
```

| Aspect | Rating | Notes |
|--------|--------|-------|
| Token cost | Excellent | ~5 tokens vs full `status()` |
| Clarity | Good | Project ID + session ID in one line |
| Actionability | Good | Surfaces shared-session risk immediately |

**Feedback:** Ideal at chat start. Prefer over `status()` for routine checks.

---

### 2. `status` — Health & diagnostics

| Aspect | Rating | Notes |
|--------|--------|-------|
| Completeness | Excellent | Engine, keeper, session, sync state |
| `detail=gate` | Good | Collapses to same ~5-token line as `gate()` |
| Use case | Debug/orientation | Too heavy for every turn |

**Feedback:** Use when debugging sync/index issues or verifying readiness after changes.

---

### 3. `map` — Semantic cold-start locate

**Good query (code vocabulary):**
```
"MCP server map focus grep glob session_store sync_loop indexer merkle incremental"
→ confidence: high, max_score: 13.58
→ Top hits: sync_loop.py, session_store.py, mcp_locate.py (all relevant)
```

**Bad query (natural language):**
```
"where does the connection go when it dies"
→ confidence: low, weak_match: true, max_score: 2.29
→ Irrelevant hits (graphify/paths.py, vectordb.py)
```

| Aspect | Rating | Notes |
|--------|--------|-------|
| Relevance (good queries) | Excellent | Top 3 cards were on-target |
| Relevance (NL queries) | Poor | Low-confidence warning is helpful |
| Token efficiency | Excellent | Cards only, no bodies |
| Duplicate detection | Excellent | `usage_hint` on repeat queries |

---

### 4. `focus` — Deep dive

| Mode | Rating | Notes |
|------|--------|-------|
| outline | Excellent | Pagination, symbol kinds |
| span | Excellent | Handles, dedup, line-range expansion |
| neighbors | Good | Import adjacency with snippets |
| call_sites | Was poor | Missed `invalidate_paths` call at `sync_loop.py:874`; fixed |

---

### 5. `grep` — Exact string search

| Aspect | Rating | Notes |
|--------|--------|-------|
| Speed | Fast | Sub-second |
| Precision | Excellent | Exact line + text |
| Glob scoping | Good | Brace groups work |
| Dotfiles | Good | `.env` accessible |

---

### 6. `glob` — File discovery

| Aspect | Rating | Notes |
|--------|--------|-------|
| Standard patterns | Good | Test files, exact paths |
| Dot-directories | Was poor | `.scubiee/` excluded unless pattern names it; fixed |

---

### 7. `workspace` — Session brain

| Aspect | Rating | Notes |
|--------|--------|-------|
| Reorientation | Excellent | Best mid-session “where am I?” tool |
| Heatmap | Useful | Shows camping patterns |
| Pin | Works | Requires explicit `action=pin` |

---

### 8. `expand` — Handle re-materialization

| Aspect | Rating | Notes |
|--------|--------|-------|
| Edit workflow | Excellent | Pairs with `already_in_session` dedup |
| Token savings | Good | Avoids re-sending span on repeat focus |

---

## Cross-Cutting Observations

### What works well

1. Token-efficient layering: map → focus → expand
2. Session intelligence: heatmap, `focus_seen`, duplicate map warnings
3. Confidence signaling: `high` vs `low`, `weak_match`, `usage_hint`
4. Actionable `next` hints on every tool response

### Remaining pain points

| Issue | Severity | Suggestion |
|-------|----------|------------|
| Shared-session hint on every response | Low | Show once per session after `gate()` |
| NL map queries fail silently-ish | Low | Already warned — could reject below threshold |
| `workspace` pin needs explicit `action` | Low | Better param docs / validation error |

---

## Recommendations

**For agents using Scubiee:**
1. Start with `gate()` — not `status()`
2. Write map queries in **code vocabulary** (20–60 tokens)
3. Prefer `focus(span)` over reading whole files
4. Use `grep` for literals; `call_sites` now finds Python calls after reload
5. Call `workspace(show)` before re-mapping the same topic
6. Use `expand(handle)` after `already_in_session` dedup

**For Scubiee maintainers:**
1. ~~Fix or deprecate `call_sites`~~ → fixed (call-pattern grep)
2. ~~Document or fix `.scubiee` glob exclusion~~ → fixed (explicit dot-dir patterns)
3. Consider deduplicating shared-session warnings after first exposure
4. Add `action` validation on `workspace` when `path` is passed without `action=pin`

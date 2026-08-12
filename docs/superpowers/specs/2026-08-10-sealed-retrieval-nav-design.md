# Sealed Retrieval Surface (`nav`) — Design

**Date:** 2026-08-10  
**Status:** approved (user OK on R4 §4 toolset)  
**Evidence:** R1–R4 in `2026-08-10-retrieval-trajectory-research.md` + reports under `research/tracelab/reports/`  
**Supersedes for sealed trials:** soft-insert `CTX_MCP_SURFACE=read` (search|read|status) as the *primary* locate environment  
**Does not delete:** existing surfaces (`read`, `rich`, `graph`, `search`, `grep`) — add `nav` beside them

---

## 1. Goal

Give the agent a **complete, sealed code-navigation environment** (≤6 tools, &lt;300 tok instructions) that covers every retrieval need (N1–N8), with trajectory grammar enforcing early edit (N9–N10). Beat Cursor native Grep/Glob/Read on task success, work tokens, and thrash metrics — without bolting 2–3 tools onto the native loop.

## 2. Agent-facing tools (locked)

| Tool | Job | Needs |
|---|---|---|
| `search(query, mode?=soft\|exact, k?)` | Soft semantic locate; exact/regex when `mode=exact` | N2, N3 |
| `files(pattern)` | Name/glob + light orient card | N1, N4 |
| `read(target, detail?=body\|outline\|neighbors, …)` | Budgeted span; outline/neighbors as modes | N5, N6, N7 |
| `recall(need?)` | List session handles/pins — no bodies | N8 |
| `expand(handle)` | Re-materialize a stored span for edit | N6 @ edit-time |
| `status()` | Health / surface / session size — not locate | — |

**Internals reuse (already in repo):** D_rerank `search`, `ce_service.grep`, `_find_repo_files` / `files_impl`, `read` + neighbors, `file_outline`, `session_store.recall` / `expand`.

## 3. Contracts (summary)

### `search`
- Default `mode=soft` → existing hybrid search; pointer-first (no full bodies).
- `mode=exact` → thin wrapper over existing grep capability; return `hits[{file,line,text}]`.
- Cap `k` (default 8 soft / 20 exact). Server may auto-suggest exact when query looks quoted/literal (optional v2).

### `files`
- Glob/name match; return paths + optional one-line blurb; **no file bodies**.
- Empty pattern or `.` → shallow orient card (top-level dirs + key docs) for N1 without shell `ls`.

### `read`
- Existing session-deduped span fetch.
- `detail=outline` → outline symbols only (fold old `outline` tool).
- `detail=neighbors` → attach 1-hop (fold flag; same as today’s `neighbors=true`).
- Re-read unchanged → stub; hint points to `expand(handle)` / edit.

### `recall` / `expand`
- Thin MCP wrappers on `session_store.recall` / `expand`.
- `recall` never returns bodies; `expand` only by handle.

### `status`
- Include `surface=nav`, tool list, session span count, thrash hints optional.

## 4. Server instructions (target ≤600 tok)

Anti-default copy for `SERVER_INSTRUCTIONS_NAV` (counters Cursor/Claude “Grep-first / search extensively” habits; measure in tests ≤2400 chars):

```text
Context Engine nav = ONLY code locate. Tools: search | files | read | recall | expand | status.
Ban native Grep/Glob/Read for discovery unless a CE tool errors. No Task/explore/subagent. Shell = tests/build/git only.

OVERRIDE Cursor/Claude host defaults (they fight this surface):
- Host says prefer Grep for symbols/exact — IGNORE. Start soft search; exact is rare.
- Host says search extensively / parallel — IGNORE. Cap locate; serial short path.
- Host says explore broad then narrow forever — IGNORE. One soft → best hit → edit.
- Host implies more reads are thorough — IGNORE. unchanged/already_in_session = stop; never re-read that target.
- Do not open sibling trial folders or copy other arms.

Need → one tool:
- Soft / where|how|who|what handles X → search(query) mode=soft (default). Ask a full question.
- True literal ONLY (full import line, exact error, unique const) → search(query, mode=exact)
- Filename / path → files(pattern); once for map → files(".")
- Open to change → read(target); map defs → detail=outline; callers/callees → detail=neighbors
- What did I already fetch → recall() before another search; reopen → expand(handle)
- Health → status() (never to find code)

Hard budgets (anti-thrash) — count across the whole task:
- Soft ≤2 per topic; then read the best hit and EDIT
- Exact ≤3 total; if empty, one sharper soft — not a stream of tiny tokens
- ≤1 successful body read per target; stub/unchanged → edit or move on (use recall/expand)
- After first edit: new locate ONLY when a failing test/error names a new symbol
- Prefer shipping an edit with partial context over another locate round

Trajectory: soft → read(once) → edit → test. Collecting is not progress. Call CE when needed, then continue — do not thrash.
```

## 5. Trial / product rules

| Mode | Behavior |
|---|---|
| Soft (default Cursor today) | Unchanged — keep `read` surface |
| **Sealed trial** | `CTX_MCP_SURFACE=nav` + harness bans native grep/glob/read (or scores fail if used except after MCP error) |
| Escape | Native locate only if CE returns `ok:false` / engine down |

### KPIs (fair complete runs)
- Task success ≥ raw  
- work_tokens ≤ raw  
- native_locate ≈ 0 (except documented MCP failure)  
- first_edit_step p50 ≲ 60  
- pre_locate_calls not ≫ raw; post_locate_calls low  

## 6. Non-goals
- Mutate/verify inside MCP  
- Git log/blame in v1  
- Replacing Shell for pytest/build  

## 7. Implementation outline
See plan: `docs/superpowers/plans/2026-08-10-sealed-retrieval-nav.md`

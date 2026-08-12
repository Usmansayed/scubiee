# Search-only vs search+read — trial log verdict

**Date:** 2026-08-11  
**Primary evidence:** `%TEMP%\ce_iso_trial\20260810T214438Z` (`ce_search` vs `ce_nav`, fair, no contamination)  
**Supporting:** prior cheap `ce_search` vault arm (`ce_private_f4133b…`, ~508k work tokens, complete+quality)

## Question

Should Context Engine expose **only `search`** (plus health `status`), or also a CE **`read`** (and the wider nav trajectory: files / recall / expand)?

## Scoreboard (same thrash task, model=auto)

| Arm | Surface | Work tokens | Complete | Quality | Wall | First edit step |
|---|---|---:|---|---|---:|---:|
| **ce_search** | `search` + `status`; native Read/Grep/Glob allowed | **3,096,363** | True | True | ~7.5 min | 179 |
| **ce_nav** | `search` `files` `read` `recall` `expand` `status`; sealed-style CE locate | **7,807,353** | True | True | ~12.3 min | 239 |

`ce_search` used **~2.5× fewer** work tokens, edited earlier, same task success.

Prior solo `ce_search` (interrupted dual-arm vs `cbm_ce`) hit **~508k** work tokens with complete+quality — shows search-only can be *much* cheaper still (run-to-run variance is real; direction vs nav is stable).

## What the agents actually did

### ce_search (soft / encouraging)

Total tool calls: **473**

| Tool | Count | Role |
|---|---:|---|
| native `edit` | 146 | shipping the feature |
| native `read` | 133 | open hit bodies |
| native `grep` | 69 | exact follow-ups |
| MCP `search` | 60 | soft locate (20 unique queries; some repeats ×3) |
| native `shell` | 24 | tests/build |
| native `glob` | 21 | filenames |
| `updateTodos` | 20 | bookkeeping |

Before first edit (178 calls): mostly **native read (72)** + **MCP search (40)** + grep/glob.  
No CE `read`. Conversation markers for `unchanged` / `already_in_session`: **0**.

### ce_nav (own trajectory + many tools)

Total tool calls: **568**

| Tool | Count | Role |
|---|---:|---|
| MCP `read` | **312** | dominant cost driver |
| native `edit` | 133 | shipping |
| MCP `files` | 33 | map |
| MCP `search` | 24 | soft locate (8 unique queries) |
| native `shell` | 24 | tests |
| MCP `expand` | 21 | reopen handles |
| `updateTodos` | 18 | bookkeeping |
| MCP `recall` | 3 | rarely used |

Before first edit (238 calls): **MCP read 180** vs search 16 — locate became a read thrash loop.  
MCP read targets: **312 calls → 40 unique → 272 duplicate reads**.  
Top dupes: `dispatch_registry.py` ×36, `tools.py` ×21, `handlers.py` ×21, …  
Conversation markers: **`unchanged`/`already_in_session` ≈ 89**, `thrash_blocked` = 1.  
Native Grep/Glob/Read: **0** (seal-style obedience) — but that did **not** save tokens.

## Log-derived diagnosis

1. **One strong soft-locate tool is enough for discovery.** Both arms completed the same multi-file feature. Extra CE tools did not improve success; they delayed first edit and multiplied context.
2. **CE `read` is where tokens go to die under current agent habits.** Even with dedupe stubs, the agent keeps calling `read` / `expand` on the same paths (272 duplicate MCP reads). Stubs still cost turns + prompt overhead.
3. **Native `Read` after `search` is the cheap “open to edit” path.** Search-only leans on host Read for bodies; that matched how humans use Grep → open file, and finished cheaper.
4. **Nav’s “trajectory” tools were underused or misused.** `recall` ×3; `expand` mostly fed re-open thrash; `files` added map noise; soft `search` dropped to 24 calls while `read` exploded to 312.
5. **Encouraging > dogmatic.** Soft “prefer search; native Read for the hit” beat “ONLY CE locate / always CE read / anti-default override card” on tokens at equal quality.

## Recommendation

**Ship search-only as the default CE surface** (`search` + `status`).

Do **not** make CE `read` (or files/recall/expand) the default product surface right now:

- Equal task success in the fair rematch  
- ~2.5× higher work tokens on nav  
- Clear mechanism: duplicate CE reads / expand loops  

Keep **native Read/Grep/Glob** as the host’s open/exact tools (as `ce_search` already does). Optionally later:

- A **gated** CE `read` (neighbors / one-shot span) behind an explicit opt-in surface for wiring questions — only after hard server-side per-target caps prove they cut tokens in a rematch  
- Stronger **`search` hit payloads** (short excerpt by default, or one-shot `fetch=true` for top-1) so agents need fewer native Reads — test before adding a second tool

## Artifact pointers

- Run folder: `C:\Users\usman\AppData\Local\Temp\ce_iso_trial\20260810T214438Z\`
  - `REPORT.md`, `results.json`
  - `ce_search-arm.json`, `ce_search-conversation.json`, `ce_search.diff`, `ce_search-tests.log`
  - `ce_nav-arm.json`, `ce_nav-conversation.json`, `ce_nav.diff`, `ce_nav-tests.log`
- Prior cheap search-only: `C:\Users\usman\AppData\Local\Temp\ce_private_f4133b33991447e7ae34aa26737f6f38\ce_search-arm.json`
- Analyzer: `scripts/experiments/analyze_tool_usage.py <trial_dir>`

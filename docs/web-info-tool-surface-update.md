# Web + docs update: ONE `map` tool, two configs (`find` | `focus`)

**Why this exists:** the live site (scubiee.com) and several docs still describe Scubiee's MCP
surface as a set of **separate tools** (`gate/status`, `map`, `focus`, `grep`, `glob`, `workspace`).
That is stale. As of **v0.3.142+**, the shipped surface is **ONE tool — `map` — with two configs,
`find` and `focus`** (plus `gate`/`status` for health). This document gives the authoritative new
copy and exactly what to change, so the landing page and docs can be updated to match the product.

**Authoritative source (do not drift from this):** `packages/pipeline/map_v3_server.py`
— `CONFIGS = ("find", "focus")`, `SERVER_INSTRUCTIONS`, and the `map` tool description. The old
`related`/`graph`/`open`/`refs`/`around`/`outline`/`grep`/`glob`/`workspace` names are **not**
advertised; some are kept only as hidden graceful fallbacks that redirect to `find`/`focus`.

---

## 1. The canonical description (use this wording everywhere)

> **Scubiee exposes one MCP tool: `map`.** You pick a `config`:
>
> - **`map find(query)`** — when you *don't know where* the code lives. One intent query returns
>   ranked locations **with the relevant code inline**. Also use `find` to orient in an unfamiliar
>   area (broad query) or to pull code near a chunk you already hold (put its names in the query).
> - **`map focus(names)`** — when you *do know the symbol name(s)*. Returns that symbol's full code
>   **plus its callers/callees and sibling symbols, in one unit** — enough to edit from, no
>   follow-up search.
>
> Plus **`gate` / `status`** for a one-shot health check at session start (managed / warming /
> needs init). That's the whole surface: **health, then `find` or `focus`.**
>
> `map` is a **partner to your agent's native Grep/Read**, not a replacement — a known literal,
> import, or exact path is still fastest with the native tool. The rule: act on the first good
> answer and stop.

**One-line version (hero / meta description):**
> One local MCP tool — `map` — with two modes: `find` (search by meaning) and `focus` (jump to a
> known symbol with its wiring). Health via `gate`/`status`.

**Recommended agent flow (replaces the old 7-step flow):**
> `status` (is the repo ready?) → `map find` *or* `map focus` → edit → `scubiee sync` if needed.

---

## 2. scubiee.com — exact changes

### 2.1 The "MCP tools" section — REPLACE WHOLESALE

**Current (stale) copy on the live site:**
> MCP tools — What your agent actually calls. Scubiee exposes a phase surface over MCP — semantic
> map first, focused reads second, grep when you need literals. Recommended flow: gate → map →
> focus → edit → sync if needed.
> - **gate / status** — Is this repo ready? …
> - **map** — Where is X handled? …
> - **focus** — Show me that handler …
> - **grep** — Find every API_KEY …
> - **glob** — List all *test*.py …
> - **workspace** — What did we already read? …
> Recommended agent flow: `status(root=workspace) → map(query) → focus(target) → edit → scubiee sync .`

**New copy (ship this):**
> **MCP tools — what your agent actually calls.** Scubiee exposes **one tool, `map`**, with two
> configs. Pick by what you know; act on the first good answer and stop.
>
> - **map find** — *"Where is X handled?"* You don't know where the code is. One query → ranked
>   locations with the relevant code inline. Also orients a wide/unknown area and pulls code near a
>   chunk you already hold.
> - **map focus** — *"Show me this handler and how it's wired."* You know the symbol name. Returns
>   its full body + callers/callees + sibling symbols in one unit — edit straight from it.
> - **gate / status** — *"Is this repo ready?"* One health check at session start — managed,
>   warming, or needs init/connect.
>
> `map` partners with your agent's native Grep/Read — a known literal or exact path stays with the
> native tool. **Recommended flow:** `status → map find | map focus → edit → scubiee sync .`

> **Remove** the standalone `grep`, `glob`, and `workspace` tiles. They are no longer advertised
> tools: literal/regex search is the agent's native Grep, path listing is native Glob, and session
> memory is internal to `map` (it de-dupes what you've already seen automatically).

### 2.2 Hero / sub-headline
No change needed to the token-savings claims (30% fewer tokens, 60–70% less context — still valid
and measured). Only the *tool wording* changes. If the hero mentions "tools" plural, soften to
"one focused retrieval tool."

### 2.3 "Built for agents" / feature list
The six capability bullets ("Find the right code", "Understand the codebase", "Read only what
matters", "Stay up to date", "Run locally", "Built for agents") are **fine as capabilities** — they
describe outcomes, not tool names. Keep them. Just ensure none of them imply separate `grep`/`glob`/
`workspace` tools.

### 2.4 "Less searching. More building." comparison animation
The left column (native: `grep "resource"` → `rg "resourceManager"` → `read manager.ts` → …) is
fine — that's the *native* baseline. The right column should show the **Scubiee** path as:
> `map find("resource management")` → ranked files + inline code → edit
i.e. one `map find` call, not a generic `search(...)`. Keep the "7 → 4 steps / fewer tokens" framing.

### 2.5 Recommended-flow strip
Replace any `gate → map → focus → grep → …` sequence with:
> `status → map find | map focus → edit → sync`

---

## 3. Docs pages — exact changes

### 3.1 `docs/scubiee-map-configs.md` (the design doc)
This doc's top banner still says the shipped surface is **four** configs (`find`/`focus`/`related`/
`graph`). Update the banner to the **two-config** reality:

> **Shipped surface (current product, v0.3.142+).** There is **one** `map` tool with **two**
> advertised configs: **`find`** and **`focus`** (plus `gate`/`status` for health). Usage mining
> showed `find` + `focus` cover ~92% of real map calls; `related` (~2%) and `graph` (~5%) were
> folded in — `find` now also orients a wide area and pulls code near a chunk you hold, and `focus`
> carries wiring (callers/callees/siblings). `related`/`graph` remain only as **hidden graceful
> fallbacks** (a client that still sends them is served via `find`/`focus`, never hard-errored).
> CLI: `scubiee map --config find|focus`. The older pack/expand/collect surface is retired
> (archived under `archive/old-mcp-map/`). The multi-config research below is the design record
> that led here; the distilled product is two configs.

The body (requirement catalog R1–R10, the research) stays as the design record — just make sure the
top banner is unambiguous that **shipped = find|focus only**.

### 3.2 Any "tools and usage" / overview / README docs
Search the docs and README for these stale tokens and update each:
- any list that enumerates `grep`, `glob`, `workspace`, `pack`, `expand`, `collect`, `refs`,
  `around`, `outline`, `related`, `graph` **as advertised tools/configs**
- the phrase "phase surface" / "gate → map → focus → …" multi-tool flow
- `scubiee map --config find|focus|related|graph` → change to `find|focus`
- `scubiee pack` / `scubiee expand` references → removed (retired)

Replace with the canonical description in section 1.

### 3.3 `docs/scubiee-tools-and-usage.md` (if present)
Rewrite the tool table to exactly two rows (`find`, `focus`) + a health row (`gate`/`status`), using
the wording in section 1. Note explicitly that literal search = native Grep, path listing = native
Glob — not Scubiee tools.

---

## 4. Copy blocks ready to paste

**Tool table (markdown):**

| Tool | Config | When to use | Returns |
|---|---|---|---|
| `map` | `find` | You don't know where the code is | Ranked locations + the relevant code inline |
| `map` | `focus` | You know the symbol name(s) | Full body + callers/callees + siblings, one unit |
| `gate` / `status` | — | Session start: is the repo ready? | managed / warming / needs init |

**FAQ entry:**
> **How many tools does Scubiee add to my agent?** One: `map`, with two modes (`find` and `focus`),
> plus a `gate`/`status` health check. Fewer tools means less for the agent to get wrong — `find`
> when you don't know where code is, `focus` when you know the name. Literal search and file listing
> stay with your agent's built-in tools.

---

## 5. Verification checklist (before publishing)

- [ ] Live site "MCP tools" section lists only `map find`, `map focus`, `gate/status` — no
      standalone `grep`/`glob`/`workspace`.
- [ ] Every "recommended flow" reads `status → map find | map focus → edit → sync`.
- [ ] No doc advertises `related`/`graph`/`pack`/`expand`/`refs`/`around`/`outline` as callable
      surface (hidden-fallback mention is OK in the design doc only).
- [ ] CLI references say `scubiee map --config find|focus`.
- [ ] Token-savings numbers (30% / 60–70%) left intact — still accurate.
- [ ] The canonical description (section 1) matches `map_v3_server.py` `SERVER_INSTRUCTIONS`
      verbatim in spirit (find = don't-know-where + inline code; focus = known-name + wiring).

---

## 6. Source of truth (for whoever edits the site)

If the site copy and the code ever disagree, the code wins. The two-config surface is defined in:
- `packages/pipeline/map_v3_server.py` → `CONFIGS = ("find", "focus")`, `SERVER_INSTRUCTIONS`,
  `TOOLS["map"]["description"]`.
- Release note: `packages/pipeline/upgrade_releases/v0_3_142.py` ("map surface narrowed to two
  configs: find | focus").

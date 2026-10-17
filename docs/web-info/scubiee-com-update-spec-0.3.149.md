# scubiee.com — website update spec (audited against shipped v0.3.149)

**Audited:** live `https://scubiee.com` (landing) + `https://scubiee.com/docs/` on
this release, compared against the shipped product (`scubiee 0.3.149`, PyPI, and
`packages/pipeline/map_v3_server.py`).

**Authoritative source of truth (do not drift):**
`packages/pipeline/map_v3_server.py` → `CONFIGS = ("find", "focus")`,
`SERVER_INSTRUCTIONS`, and `TOOLS["map"]["description"]`. If the site and the code
ever disagree, the code wins.

**Two problems to fix:**
1. **Stale MCP tool surface** — the site advertises a 6-tool surface
   (`gate/status`, `map`, `focus`, `grep`, `glob`, `workspace`). The product ships
   **one tool, `map`, with two configs — `find` and `focus`** — plus `gate`/`status`
   for health. True since v0.3.142. `grep`/`glob`/`workspace` are **not** Scubiee
   MCP tools.
2. **Stale Python version** — the docs say "Python 3.10+". The install floor is
   `requires-python >= 3.11` (raised in v0.3.146 to kill a numpy-ABI crash). A user
   on 3.10 is now refused at install.

Everything NOT listed below is accurate — token-savings numbers (30% / 60–70%),
the four-layers table, profile table, daemon description, managed states, time
expectations, "install from PyPI" — leave all of it as-is.

---

## 0. The one canonical description (reuse this wording everywhere)

> **Scubiee exposes one MCP tool: `map`.** You pick a `config`:
> - **`map find(query)`** — when you *don't know where* the code lives. One intent
>   query returns ranked locations **with the relevant code inline**. Also use
>   `find` to orient in an unfamiliar area (broad query) or to pull code near a
>   chunk you already hold (put its names in the query).
> - **`map focus(names)`** — when you *do know the symbol name(s)*. Returns that
>   symbol's full code **plus its callers/callees and sibling symbols, in one unit**
>   — enough to edit from, no follow-up search.
>
> Plus **`gate` / `status`** for a one-shot health check at session start (managed /
> warming / needs init). That's the whole surface: **health, then `find` or `focus`.**
>
> `map` is a **partner to your agent's native Grep/Read**, not a replacement — a
> known literal, import, or exact path is still fastest with the native tool.

**One-line / hero-meta version:**
> One local MCP tool — `map` — with two modes: `find` (search by meaning) and
> `focus` (jump to a known symbol with its wiring). Health via `gate`/`status`.

**Recommended agent flow (replaces every old multi-tool flow):**
> `status` (is the repo ready?) → `map find` *or* `map focus` → edit → `scubiee sync` if needed

---

## 1. LANDING PAGE (scubiee.com)

### 1.1 "MCP tools — What your agent actually calls" section — REPLACE WHOLESALE

**CURRENT (stale) copy on the live site:**
> MCP tools — What your agent actually calls. Scubiee exposes a staged phase
> surface over MCP — map the area, focus a span, grep when you need literals.
> Recommended flow: gate → map → focus → edit → sync if needed.
> - **gate / status** — Is this repo ready? …
> - **map** — Where is X handled? Ranked overview … no full file bodies.
> - **focus** — Show me that handler. Deep-dive a span … from a map hit.
> - **grep** — Find every API_KEY. Exact literals and regex …
> - **glob** — List all *test*.py. Path patterns over the index …
> - **workspace** — What did we already read? Session memory …
> Recommended agent flow: status(root=workspace) → map(query) → focus(target) → edit → scubiee sync .

**NEW copy (ship this):**
> **MCP tools — what your agent actually calls.** Scubiee exposes **one tool, `map`**,
> with two configs. Pick by what you know; act on the first good answer and stop.
>
> - **map find** — *"Where is X handled?"* You don't know where the code is. One
>   query → ranked locations **with the relevant code inline**. Also orients a
>   wide/unknown area and pulls code near a chunk you already hold.
> - **map focus** — *"Show me this handler and how it's wired."* You know the
>   symbol name. Returns its full body + callers/callees + sibling symbols in one
>   unit — edit straight from it.
> - **gate / status** — *"Is this repo ready?"* One health check at session start —
>   managed, warming, or needs init/connect.
>
> `map` partners with your agent's native Grep/Read — a known literal or exact path
> stays with the native tool. **Recommended flow:** `status → map find | map focus → edit → scubiee sync .`

**DELETE** the three standalone tiles **`grep`**, **`glob`**, **`workspace`**.
They are not advertised MCP tools: literal/regex search = the agent's native Grep,
path listing = native Glob, and session memory is internal to `map` (it de-dupes
what you've already shown automatically).

### 1.2 "Less searching. More building." comparison animation

The RIGHT ("Scubiee") column currently shows a generic 2-step. Make it one `map find`:
- **1.** `map find("resource management")`
- **2.** ranked files + inline code → edit

The LEFT (native baseline: `grep "resource"` → `rg "resourceManager"` → `read
manager.ts` → …) is fine — that's the native comparison. Keep the "7 → 4 steps /
fewer tokens" framing.

### 1.3 Recommended-flow strip (wherever it appears)
Replace any `gate → map → focus → …` or `status → map → focus → edit` sequence with:
> `status → map find | map focus → edit → sync`

### 1.4 Leave unchanged on the landing page
- Hero + all token numbers (30% fewer tokens; 60–70% less context) — still measured/valid.
- The six capability bullets ("Find the right code", "Understand the codebase",
  "Read only what matters", "Stay up to date", "Run locally", "Built for agents") —
  they describe outcomes, not tool names. Keep. Just ensure none implies separate
  `grep`/`glob`/`workspace` tools.
- "Use it where you already code" (Cursor / Claude Code / Codex / OpenCode / Any MCP),
  the three-steps (Index / Find / Read), incremental-refresh line, privacy section.

---

## 2. DOCS PAGE (scubiee.com/docs/)

### 2.1 Python version — change EVERY "Python 3.10+" → "Python 3.11+"

**CURRENT (intro):**
> Scubiee is a local context engine for AI coding tools (Cursor, Claude Code, Kiro,
> Copilot, and more). You need **Python 3.10+**. You do not need to clone the GitHub
> repo — install from PyPI.

**NEW:**
> Scubiee is a local context engine for AI coding tools (Cursor, Claude Code, Kiro,
> Copilot, and more). You need **Python 3.11+**. You do not need to clone the GitHub
> repo — install from PyPI.

Reason: shipped `requires-python = ">=3.11"` since v0.3.146. A 3.10 user is refused
at install, so "3.10+" is actively wrong. Check the whole page for any other
"3.10" mention and bump it too.

### 2.2 Intro sentence — MCP surface

**CURRENT:**
> It indexes your repository, embeds code with CodeRank (GPU when available), and
> exposes a phase MCP surface — **map, focus, grep, glob, workspace** (plus
> gate/status for health).

**NEW:**
> It indexes your repository, embeds code with CodeRank (GPU when available), and
> exposes **one MCP tool, `map`, with two modes — `find` and `focus`** (plus
> `gate`/`status` for health).

### 2.3 Intro — "ranked locations / focused spans" sentence

**CURRENT:**
> …Scubiee returns ranked locations (map) and focused code spans (focus) — not
> guessed filenames.

**NEW:**
> …Scubiee returns ranked locations (`map find`) and focused code spans with their
> wiring (`map focus`) — not guessed filenames.

### 2.4 Architecture diagram line — REPLACE

**CURRENT:**
> Scubiee MCP — **status, map, focus, grep, glob, workspace**

**NEW:**
> Scubiee MCP — **gate/status (health) · map (find | focus)**

That is the only line in the diagram that changes. The layer below it
(`Scubiee Engine — daemon + live re-indexing`) and everything else stays.

### 2.5 "Facts any assistant needs" — the pasteable-into-ChatGPT block

**CURRENT (one bullet):**
> Default MCP surface is phase: **status, map, focus, grep, glob, workspace** (with a
> gate health check). Map the area, focus a span, grep for literals.

**NEW (replace that bullet):**
> MCP surface is **one tool `map` with configs `find` and `focus`** (+ `gate`/`status`
> for health). `map find` when you don't know where code is; `map focus` when you
> know the symbol name. There are **no** separate `grep`/`glob`/`workspace` MCP
> tools — those are the agent's native tools.

Also in this section, the "Order:" bullet is correct (setup → connect → reload MCP
→ init) — leave it. Just confirm no "3.10" remains anywhere in the fact list.

### 2.6 Optional clarity add (recommended, not required)
Under the architecture diagram or "Core concepts", a one-liner prevents the old confusion:
> **MCP surface:** one tool, `map`. Use `map find` when you don't know where the
> code is, `map focus` when you know the symbol name. Literal search, file globbing,
> and known-path reads use your agent's native tools — Scubiee does not duplicate them.

### 2.7 Leave unchanged on the docs page
- Four-layers table (Install / Machine setup / IDE wiring / Repo enrollment) + all
  commands (`uv tool install scubiee`, `scubiee setup --repair`, `scubiee connect --…`,
  `scubiee init .`).
- "Memorize this sequence" table, core-concepts table, managed-states list.
- Profile-selection table (dml / cpu / mlx / cuda).
- "What the daemon does", time-expectations table, troubleshooting bullets
  (`unlock-tool`, `setup --repair`, `diagnose --no-tests --desktop`).

---

## 3. Verification checklist (before publishing)

Landing page:
- [ ] "MCP tools" section lists only **map find**, **map focus**, **gate/status** — no standalone `grep`/`glob`/`workspace` tiles.
- [ ] Comparison animation right column shows a single `map find(...)` call.
- [ ] Every recommended-flow strip reads `status → map find | map focus → edit → sync`.
- [ ] Token numbers (30% / 60–70%) untouched.

Docs page:
- [ ] Every "Python 3.10+" → "Python 3.11+".
- [ ] Intro says "one MCP tool `map` with modes find | focus" (not "map, focus, grep, glob, workspace").
- [ ] "ranked locations / focused spans" sentence uses `map find` / `map focus`.
- [ ] Architecture diagram line reads `gate/status (health) · map (find | focus)`.
- [ ] "Facts any assistant needs" has the one-tool-two-configs fact and no `grep/glob/workspace` as MCP tools.
- [ ] Four-layers table, profile table, daemon, time expectations untouched.

Cross-check:
- [ ] No page advertises `related` / `graph` / `pack` / `expand` / `collect` /
      `refs` / `around` / `outline` as a callable MCP tool/config (all retired).
- [ ] Any `scubiee map --config …` CLI reference reads `find|focus` only.

---

## 4. Why these are the only changes

The map surface was narrowed to two configs in **v0.3.142** (release note:
`packages/pipeline/upgrade_releases/v0_3_142.py`, "map surface narrowed to two
configs: find | focus"). The old `related`/`graph`/`pack`/`expand`/`collect`/
`refs`/`around`/`outline`/`grep`/`glob`/`workspace` names are **not advertised**;
a few survive only as hidden graceful fallbacks that redirect to `find`/`focus`, so
a client that still sends them is served, never hard-errored — but they must not be
documented as surface. The Python floor moved to **3.11** in **v0.3.146**. Current
shipped release is **0.3.149** (on PyPI). Nothing else on the site is inaccurate.

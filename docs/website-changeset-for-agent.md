# Website changeset — update scubiee.com to the current product (find + focus)

**For:** an agent (or engineer) with access to the **scubiee.com website source** (the marketing
site + docs site — a separate repo/CMS, NOT this `context-engine` repo).
**Goal:** bring the live site in line with the shipped product. The only substantive drift is the
**MCP tool surface**: the site still advertises a multi-tool surface; the product now ships **one
tool, `map`, with two configs (`find` | `focus`)** plus `gate`/`status` for health.

This document was written by reading **both** the live site (scubiee.com landing + /docs/) and the
**authoritative product code** in the `context-engine` repo. Every "change X → Y" below is grounded
in one of those two sources, cited inline.

---

## 0. The single source of truth (don't drift from this)

From `packages/pipeline/map_v3_server.py` (the shipped MCP server):

- `CONFIGS = ("find", "focus")` — the **only** advertised configs.
- `map` tool description (verbatim):
  > "Semantic code retrieval. config=find|focus. find: where is X + code (also to orient a wide
  > area with a broad query, and to pull code near a chunk you hold). focus: a known symbol's code
  > + callers/callees + siblings in one unit. Partner to native Grep/Read."
- Server instructions (verbatim intent):
  > "Scubiee map = semantic code retrieval. ONE tool `map`, config = find | focus (+ gate/status
  > for health). find(query): you do NOT know where code lives → ranked locations with the code
  > inline… focus(names|anchor): you DO know the symbol name(s) → that symbol's full code + its
  > callers/callees + sibling symbol names, in ONE unit."
- `gate` tool: "Health/managed signal only (not for finding code)."
- CLI (`packages/pipeline/__main__.py`): `scubiee map --config {find,focus}` (default `find`).

**Everything the site should say about the tool surface reduces to:**
> One MCP tool, `map`. `find` = you don't know where the code is → ranked locations **with code
> inline**. `focus` = you know the symbol name → its **full body + callers/callees + siblings** in
> one unit. Plus `gate`/`status` for health. Literal search / file globbing / known-path reads use
> the agent's **native** Grep/Glob/Read — Scubiee does not duplicate them.

What is NO LONGER a tool (do not list as callable MCP tools anywhere): `grep`, `glob`, `workspace`,
`pack_context`, `expand_context`, `collect_hot_context`, `refs`, `around`, `outline`, `related`,
`graph`. (`related`/`graph` still *work* as hidden fallbacks that redirect to find/focus, but are
not advertised.)

---

## 1. LANDING PAGE (scubiee.com)

### 1.1 "MCP tools" section — the main fix (REPLACE WHOLESALE)

**What the live page shows today (verbatim):**
> **MCP tools — What your agent actually calls.** Scubiee exposes a phase surface over MCP —
> semantic map first, focused reads second, grep when you need literals. Recommended flow: gate →
> map → focus → edit → sync if needed.
> - **gate / status** — Is this repo ready? One check at session start — managed, warming, or needs init/connect.
> - **map** — Where is X handled? Ranked overview of paths and symbols — no full file bodies.
> - **focus** — Show me that handler. Deep-dive spans, neighbors, and call sites from a map hit.
> - **grep** — Find every API_KEY. Exact literals and regex across indexed files when you know the string.
> - **glob** — List all *test*.py. Path patterns over the index — faster than walking the tree blindly.
> - **workspace** — What did we already read? Session memory — pins and heatmap so agents do not re-explore.
> **Recommended agent flow:** `status(root=workspace) → map(query) → focus(target) → edit → scubiee sync .`

**Replace with:**
> **MCP tools — what your agent actually calls.** Scubiee exposes **one tool, `map`**, with two
> configs. Pick by what you know; act on the first good answer and stop.
> - **map find** — *"Where is X handled?"* You don't know where the code is. One query → ranked
>   locations **with the relevant code inline**. Also orients a wide/unknown area and pulls code
>   near a chunk you already hold.
> - **map focus** — *"Show me this handler and how it's wired."* You know the symbol name →
>   its **full body + callers/callees + sibling symbols** in one unit; edit straight from it.
> - **gate / status** — *"Is this repo ready?"* One health check at session start — managed,
>   warming, or needs init/connect.
>
> `map` partners with your agent's native Grep/Read — a known literal or exact path stays with the
> native tool.
> **Recommended agent flow:** `status → map find | map focus → edit → scubiee sync .`

**Delete these three tiles entirely:** `grep`, `glob`, `workspace`. They are not Scubiee MCP tools
anymore — literal/regex search = native Grep, path listing = native Glob, "what did we already
read?" is now handled internally by `map` (it de-dupes seen spans automatically).

### 1.2 Recommended-flow strip (appears twice)
Anywhere the page shows `status(root=workspace) → map(query) → focus(target) → edit → scubiee sync .`
or `gate → map → focus → edit → sync`, replace with:
> `status → map find | map focus → edit → scubiee sync .`

### 1.3 "Less searching. More building." comparison (the 7→4 steps animation)
The right-hand "Scubiee" column currently reads `search("resource management") → … → read → code`.
Make the first step the real call: **`map find("resource management")` → ranked files + inline
code → edit**. Keep the "7 → 4 steps / fewer retrieval steps / 60–70% fewer context tokens" framing
— those numbers are still valid.

### 1.4 Leave unchanged (verified still accurate)
- Hero: "Save 30% of your AI coding tokens", "60–70% less context overhead", "100% local", "Free /
  Apache 2.0". **Keep** — these are measured and current.
- The six capability cards ("Find the right code", "Understand the codebase", "Read only what
  matters", "Stay up to date", "Run locally", "Built for agents") — **keep**; they describe
  outcomes, not tool names.
- "Use it where you already code" (Cursor / Claude Code / Codex / OpenCode / any MCP) — **keep**.
- "Three simple steps" (Index / Find / Read) and "Incremental refresh … under a second" — **keep**.

---

## 2. DOCS PAGE (scubiee.com/docs/)

Only two spots carry the stale surface; the rest of the page is accurate.

### 2.1 Intro sentence
**Today (verbatim):**
> It indexes your repository, embeds code with CodeRank (GPU when available), and exposes
> **search / map / focus** over MCP.

**Replace with:**
> It indexes your repository, embeds code with CodeRank (GPU when available), and exposes **one MCP
> tool, `map`, with two modes — `find` and `focus`** (plus `gate`/`status` for health).

**And the sentence a bit later (verbatim):**
> …Scubiee returns ranked locations (map) and focused code spans (focus) — not guessed filenames.

**Replace with:**
> …Scubiee returns ranked locations (`map find`) and focused code spans with their wiring
> (`map focus`) — not guessed filenames.

### 2.2 Architecture diagram line (REPLACE)
**Today (verbatim):**
> Scubiee MCP — **status, map, focus, grep, glob, workspace**

**Replace with:**
> Scubiee MCP — **gate/status (health) · map (find | focus)**

(The lines above/below it — "Your AI tool … ↓ MCP (stdio) — server name: scubiee" and "Scubiee
Engine — daemon + live re-indexing" — stay unchanged.)

### 2.3 "Facts any assistant needs" — ADD one bullet
This section is meant to be pasted into ChatGPT/Claude, so it must not seed the retired tool names.
Add:
> - MCP surface is **one tool `map` with configs `find` and `focus`** (plus `gate`/`status`). There
>   are no separate `grep` / `glob` / `workspace` MCP tools — those are the agent's native tools.

### 2.4 Leave unchanged (verified accurate against the repo)
- "You need Python 3.10+ … install from PyPI", "model downloads once (~270 MB)".
- The **four layers** table (Install / Machine setup / Repo enrollment / IDE wiring) and all
  commands (`uv tool install scubiee`, `scubiee setup --repair`, `scubiee init .`,
  `scubiee connect --cursor`). Verified: these match the CLI.
- "Memorize this sequence" (install → setup → init → connect → reload MCP).
- Managed states (Unmanaged / Managed / Paused / Wiped) — note it says `scubiee activate .` for
  paused and `scubiee resume` elsewhere; both exist, no change needed.
- Profile table (dml / cpu / mlx / cuda) — verified against `accel.py`.
- Daemon description (`http://127.0.0.1:8765`), time expectations, troubleshooting facts
  (`scubiee unlock-tool`, `scubiee setup --repair`, `scubiee diagnose`). **Keep all.**

---

## 3. Exact find/replace cheat-sheet (for a quick pass)

| Find (stale) | Replace (correct) |
|---|---|
| `search / map / focus` (over MCP) | `one MCP tool \`map\` with modes find \| focus` |
| `status, map, focus, grep, glob, workspace` | `gate/status (health) · map (find \| focus)` |
| `gate → map → focus → edit → sync` | `status → map find \| map focus → edit → sync` |
| `status(root=workspace) → map(query) → focus(target) → edit → scubiee sync .` | `status → map find \| map focus → edit → scubiee sync .` |
| standalone tiles/rows: `grep`, `glob`, `workspace` as MCP tools | delete (they are native agent tools, not Scubiee) |
| `phase surface over MCP — semantic map first, focused reads second, grep when you need literals` | `one tool \`map\`: find (don't know where) and focus (know the name)` |

Do **not** touch: token-savings numbers (30% / 60–70%), install/setup/init/connect commands, the
four-layers table, profiles, daemon, pricing/open-source, agent-compatibility list.

---

## 4. Canonical copy blocks (paste-ready)

**Hero sub-line (if the tool surface is mentioned up top):**
> One local MCP tool — `map` — with two modes: `find` (search by meaning) and `focus` (jump to a
> known symbol with its wiring).

**Tool table (markdown or HTML):**

| Tool | Config | When to use | Returns |
|---|---|---|---|
| `map` | `find` | You don't know where the code is | Ranked locations + the relevant code inline |
| `map` | `focus` | You know the symbol name(s) | Full body + callers/callees + siblings, one unit |
| `gate` / `status` | — | Session start: is the repo ready? | managed / warming / needs init |

**FAQ entry:**
> **How many tools does Scubiee add to my agent?** One — `map`, with two modes (`find` and
> `focus`), plus a `gate`/`status` health check. `find` when you don't know where code is, `focus`
> when you know the name. Literal search and file listing stay with your agent's built-in tools.

---

## 5. Why this changed (context for the agent, 2 lines)

Usage mining showed `find` + `focus` cover ~92% of real `map` calls, so in **v0.3.142** the surface
was deliberately narrowed from a larger multi-config/multi-tool set to **two configs**. Fewer tools
= less for the agent to pick wrong. The retired names still degrade gracefully server-side but are
not advertised. (Repo refs: `packages/pipeline/upgrade_releases/v0_3_142.py`,
`packages/pipeline/map_v3_server.py`.)

---

## 6. Verification checklist (before publishing the site)

Landing page:
- [ ] "MCP tools" section lists only **map find**, **map focus**, **gate/status** — no `grep` /
      `glob` / `workspace` tiles.
- [ ] Both recommended-flow strips read `status → map find | map focus → edit → scubiee sync .`
- [ ] The comparison animation's Scubiee column starts with `map find(...)`.
- [ ] 30% / 60–70% / local / Apache-2.0 claims untouched.

Docs page:
- [ ] Intro says "one MCP tool `map` with modes find | focus" (not "search / map / focus").
- [ ] Architecture diagram line reads `gate/status (health) · map (find | focus)`.
- [ ] "Facts any assistant needs" includes the one-tool-two-configs fact.
- [ ] Install/setup/init/connect, four-layers, profiles, daemon, troubleshooting untouched.

Global:
- [ ] A site-wide search for `grep`, `glob`, `workspace`, `pack_context`, `expand_context`,
      `collect_hot_context`, `phase surface` returns no results that describe them as Scubiee MCP
      tools.

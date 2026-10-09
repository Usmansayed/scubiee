# Scubiee Tool Surface: What Each Tool Does, How It Works, and How Agents Should Use It

This document describes the Scubiee MCP tool surface as it is actually implemented
(`packages/pipeline/mcp_locate.py`, `packages/pipeline/context_trace.py`,
`packages/trace_lab/composite_v1.py`), the ideal tool-call trajectory for different coding
tasks, and why this design saves AI coding tokens.

Scubiee is a **locate layer**, not an editor. Its job is to point an AI coding agent at the
*smallest set of exact code spans* relevant to a task, so the agent reads a few hundred lines
instead of dumping whole files into its context window. The agent still edits with its host's
native tools.

---

## 1. Core concepts (shared by every tool)

Before the per-tool detail, a few concepts recur throughout.

- **Managed repo / enrollment.** A repo is "managed" when it has been enrolled
  (`scubiee init`), which writes `.scubiee/id.json` containing a `project_id` (`ce_…`). Every
  locate tool first calls `_is_repo_managed()`; on an unmanaged repo it refuses and tells the
  agent to use native tools. `project_id` / `root` / `session_id` can be passed on any call to
  bind the request to the right repo and chat.

- **The repo IR (`_RepoTrace`).** On first use Scubiee builds an in-memory intermediate
  representation of the repository: `nodes` (a dict of `TraceNode` — every function/method/
  class/const with its file, symbol, kind, line span, and body text), an **AST graph**, an
  **LSP index**, a **lexical index**, and optionally a **Graphify** graph. This is expensive to
  build once (seconds), so it is pickled to a disk **bundle** keyed by a `corpus_fingerprint`,
  served stale-while-revalidate, and cached in memory with a 600s TTL. The MCP worker **never
  cold-bakes on the request thread** — if the bundle isn't ready it kicks off a background bake
  and returns `status:"warming"` so the agent retries rather than blocking.

- **Heatmap → cards.** The tracer produces a `Heatmap` of scored nodes. `heatmap_to_cards`
  turns those into **cards**: `{id, file, symbol, kind, role, start_line, end_line, loc, score,
  heat, rank, why, path}`. A card is a *pointer with a reason* — a `loc` like
  `packages/pipeline/engine.py:120-176`, a relevance `score`, a `heat` label, and a short `why`
  string explaining the edge that admitted it. Cards deliberately carry **no code body**.

- **Heat thresholds.** `_heat(score)` labels a node `hot` at ≥ 0.72, `warm` at ≥ 0.45, else
  cool. `heatmap_to_cards` drops anything below 0.45. The pack layer applies its own
  `hot_threshold` (default 0.65) to decide which cards are "hot enough" to pack bodies for.

- **Sessions & persistence.** Work is scoped to a `session_id` (per chat). Each call persists a
  trace (`query`, `seed_id`, `cards`, `scores`, `packed_ids`, `packed_ids_by_tool`,
  `expanded_ids`, `mode`) via `persist_trace`, so later calls in the same chat know what was
  already packed/expanded and don't re-fetch it. Pins, topic, and a "focus_seen" ledger live in
  a separate work-session store.

- **The ladder.** The intended trajectory is **map → pack_context(lean) → expand_context**, in
  **≤ 3 locate calls per beat**, with `collect_hot_context` as a bodies escape hatch. Every
  response echoes this ladder and a `next` / `next_actions` nudge.

---

## 2. The tools

### 2.1 `gate` — the ~5-token managed check

**What it does.** The cheapest possible signal of whether Scubiee should be used at all. Call
it once at the start of a chat instead of a full `status()`.

**How it works.** `gate_impl` calls `ensure_mcp_runtime(blocking=False)` (nudges the engine
awake without waiting) then `_gate_line()`. It reads `.scubiee/id.json` and the pause state and
returns a tiny string:

- `0` — not managed; use native tools, don't poll.
- `0:r` — not managed, but the status TTL elapsed; call `gate()` once more.
- `1:ce_…` — managed; reuse that `ce_…` as `project_id` on subsequent locate calls.
- `p` — Scubiee is paused/stopped; **do not** call locate tools, use native Read/Grep/Glob.

When managed it also probes engine health and may append ` warming retry:3`, ` sid:<session>`,
and ` shared` (with a hint) if it detects several chats sharing one MCP process.

**Returns.** A single short line (a handful of tokens). No code, no bodies.

### 2.2 `status` — engine and session health

**What it does.** Reports whether the engine is up, warm, and which tools the surface exposes.
It is for health, **not** for finding code.

**How it works.** `status_impl` opens a session-bound `EngineClient`, checks `healthy()`, and
reads `health()` for `warm_state`, `soft_search_ready`, and `project_id`. To avoid a
multi-second `open_repo`, it reuses a cached "soft ready" flag when soft search is already
confirmed. `detail=summary` (default) returns a compact agent card; `detail=full` adds engine
health + the trimmed keeper payload; `detail=gate` returns the same one-line signal as `gate`.
If paused, it returns lifecycle guidance (how to resume) with `should_use_mcp:false`.

**Returns.** Structured health flags (`managed`, `warming`, `warm_state`, `search_usable`,
`agent_ready`, `sync_state`, …), the surface's tool list, and session info. It honestly reports
`warming` rather than faking readiness.

### 2.3 `map` — Call 1: soft, ranked pointers (no bodies)

**What it does.** Turns a natural-language, code-vocabulary query into a ranked list of ~12
candidate spans plus **suggested seeds** to start a pack from. This is the cold-start /
new-topic entry point.

**How it works internally.**
1. Validates and normalizes the query. Checks a process-local dense cache
   (`map_result_cache`) and a per-session duplicate cache — an identical query returns
   instantly with `cached:true`.
2. Otherwise it runs **dense semantic retrieval**: `search_impl(mode="soft", include="hits")`
   → `tool_search_code`, which **requires FastEmbed dense retrieval (`D_channel_best`)**. If the
   embedder isn't loaded yet it returns `dense_embed_loading`/`warming` — it deliberately does
   **not** fall back to BM25-only, so `map` results are always embedding-quality.
3. `_enrich_map_cards` builds the cards; `_assess_map_confidence` may trim to the top 3 and set
   `weak_match` when confidence is low.
4. **Seed selection.** `pick_suggested_seed` (primary) and `pick_suggested_seeds(limit=3)` pick
   1–3 *distinct production* seeds: they prefer separate `packages/|src/|app/|lib/` files, skip
   test/docs/eval/scripts, penalize weak/leaf/private symbols, and boost query-named files and
   symbols. `finalize_suggested_seed` fills each seed's `symbol`/`loc`/`kind` by resolving the
   public class/entrypoint in that file — but on the map path with `load_repo=False`, so map
   stays search-bound (~2s) instead of building the AST graph (~16s). Unresolved seeds are
   returned file-only with `seed_incomplete:true`.

**Returns.** `{ok, tool:"map", query, k, cards:[…], count, scope:"indexed_chunks",
ranked_only:true, suggested_seed, suggested_seeds:[≤3], ladder, next, dense:true,
retrieve_mode:"D_channel_best", timings, confidence, elapsed_ms, session_id}`. Cards are
pointers only — file, symbol, loc, score, heat, why — no bodies.

### 2.4 `pack_context` — Call 2: the heatmap around a seed

**What it does.** Given a seed (a file + symbol/line, usually a `suggested_seed` from `map`) and
an enriched query, it traces the code around that seed and returns a ranked **heatmap** of the
call/data neighborhood — the spans an agent should read to understand and edit this area. By
default it returns **locs only, no bodies** (the agent Native-Reads the hot spans).

**How it works internally.**
- Requires `seed_file`. If the AST bundle isn't ready, it starts a background bake and returns
  `status:"warming"` (never blocks the request thread).
- Calls `run_pack_context` → `run_map_context`, which loads the repo IR and runs the tracer
  (`composite_v1` by default) from the seed. For multi-seed packs (`seed2_*`, `seed3_*`) each
  seed gets its own heatmap; seed 1 always gets a full trace, secondary seeds use a light hop
  when already covered, and the maps are merged (`merge_seed_heatmaps`).
- **The tracer (`composite_v1`).** It builds an enriched forward **call graph**
  (AST + LSP + Graphify, Jedi off by default for speed), composes a PDG, and computes **data-flow
  edges (DFG)**. It runs a **best-first expansion** from the seed (`floor=0.18`,
  `hop_decay=0.965`) to score reachable nodes, then a **precision-first rerank**
  (`apply_rank_composite`): DFG "spine" edges get a ×1.10 boost, **sinks not named by the query
  are demoted ×0.18**, depth-≥2 non-sink nodes are floored to stay hot, the seed is pinned to
  1.0, tiny/private helpers are demoted, and direct calls that tie near 0.99 are broken by body
  span so entrypoints outrank short predicates. Enriched edges are cached on disk
  (`.scubiee/cache/composite_edges_v1.pkl`) so later packs in the process are fast.
- **Post-processing.** Drops noise cards; adds a seed-fallback card if the heatmap came back
  empty; densifies a thin seed by walking graph neighbors (callers/callees/uses/siblings, skipping
  weak DTOs and private helpers); guarantees every accepted seed appears (`seed_coverage`);
  demotes home/pause/id helpers unless queried.
- **Bodies.** MCP default is heatmap-only (`include_bodies=0` / `CTX_MCP_PACK_BODIES`). When
  bodies are requested, `run_collect_hot` packs the hottest cards within `budget_chars`
  (lean 6000 / full 12000) and `max_bodies` (lean 4 / full 16), always preferring the seed(s).
  Only actually-collected body ids count as `packed_ids` (so a lean heatmap doesn't poison a
  later `collect_hot_context`).
- Builds a bodiless **`chain`** (a call-chain outline), a **`cold`** list (low-score unpacked
  locs), and flags **`thin`** when the neighborhood is too sparse or seed coverage is
  incomplete — steering the agent to `expand_context` rather than re-packing.
- `mode` (lean/full) and `policy` (strict/broad) **do not change the ranker** — both stay on
  `composite_v1`. `broad` may one-shot reseed a leaf method to its enclosing public class; a
  class seed that packs file-local may hop to a richer subclass (`seed_promoted`).

**Returns.** `{ok, tool, query, seed(s), multi_seed, seed_coverage, mode, policy,
heatmap:[slim cards], chain:[…], pack:[bodies], cold:[locs], count, packed, chars,
hot_threshold, thin, prefer, engine, escape, graphify, n_nodes, guide, next,
next_actions:[{tool,when,args}], ladder, sla, elapsed_ms, session_id}`.

### 2.5 `expand_context` — Call 3: delta cards in a direction

**What it does.** Grows the map from a specific node in a chosen **direction**, returning only
the **new (delta)** cards — the hops the first pack didn't include. This is how an agent chases
"who calls this," "what does this call," "what are the side effects," etc., without re-running a
whole pack.

**How it works internally.** Resolves the node from `node` / `seed_file+seed_symbol` / the
hottest prior card. Direction (alias `intent`) is one of:
- **`callees` / `flow`** — direct outgoing calls first; the tracer only fills real call hops.
- **`callers` / `refs`** — incoming calls: lexical callers + structural reverse edges + tracer
  results filtered to reverse `why` (tagged `evidence: text_call|used_by|called_by`). This
  deliberately escapes the strict forward-only composite pack.
- **`effects` / `site`** — nodes whose symbol looks like a side effect (log/print/track/send +
  file-writing calls).
- **`config`** — `const` nodes, `uses` edges, and calls touching settings / `mcp.json`.
- **`broad` / `all`** — structural 1-hop + same-file public siblings (no expensive poly trace).

Cards already on the pack heatmap are annotated `already_in_pack:true` rather than dropped;
already-expanded ids are skipped to avoid thrash. `rank_expand_delta` orders the merged set and
`delta = merged[:k]` (default k=10). If nothing new, `empty_reason` is `already_expanded` or
`no_edges`. With `with_bodies=true` it packs ≤ `max_bodies` lean bodies (`budget_chars`≈4000).

**Returns.** `{ok, tool:"expand_context", from:<nid>, direction, delta:[cards], count,
pack:[bodies], empty_reason?, guide, next, next_actions, session_id, hydrate_ms}`. The delta is
merged into the session trace.

### 2.6 `collect_hot_context` — bodies on demand

**What it does.** Materializes the actual **code text** for session heatmap cards above a score
threshold, or for explicit `ids=` (comma-separated `file::symbol`). It's the batched "give me
the bodies" escape hatch — the docs still nudge agents to prefer native Read of the loc spans.

**How it works internally.** Loads the session cards. If the AST is cold, it span-reads from the
card locs (never sync-loading the large pickle); if warm, `run_collect_hot` selects cards ≥
`threshold` (default 0.45 for session cards, 0.0 when explicit `ids=`), sorts them (preferred
ids first, then real functions before consts/helpers, then by score), refreshes each node's text
from disk, and fits bodies into `max_chars` (default 8000) with a fair per-body share. Explicit
`ids=` always win — even below threshold or minted straight from the node table — and
already-packed ids are skipped unless explicitly requested.

**Returns.** `{ok, tool:"collect_hot_context", threshold, bodies:[{id, file, symbol,
start_line, end_line, loc, score, heat, why, text}], count, chars, empty_bodies, guide, next,
session_id}`. Collected ids are folded into `packed_ids`.

### 2.7 `workspace` — mid-session reorient (show / pin / clear)

**What it does.** The session "brain." `show` (default) surfaces what the agent has already
touched; `pin` marks a file as important; `clear` resets for a new topic.

**How it works internally.** It reads the per-session **work state**, not the code IR.
`show` returns `topic`, `pins`, a recent-activity `heatmap` (top 8), recalled `spans`, a
`focus_seen` ledger (last 30 fetched spans, to avoid redundant re-reads), and the last 10 map
queries. `pin` validates the file exists and adds it to the session pins. `clear` wipes the
session store and work session.

**Returns.** `{ok, tool:"workspace", action, session_id, topic, pins, heatmap, spans,
focus_seen, map_queries, next}` for `show`; confirmation payloads for `pin`/`clear`.

### 2.8 `expand` — re-materialize a stored span by handle

**What it does.** Fetches the body for a previously seen span **handle** (e.g. a heatmap id
`file::symbol`, a `file:start-end`, or a handle returned by a prior read/recall). Distinct from
`expand_context` (which grows the graph); `expand` just re-hydrates one known span.

**How it works internally.** Tries a live heatmap-span read first, then the session-store
handle store; caps the body at a char ceiling.

**Returns.** `{ok, tool:"expand", handle, file, start_line, end_line, text, chars, truncated,
next, session_id}`.

> Alternate pack engines. On experiment surfaces Scubiee also exposes `pack_poly_embed`
> (structural poly + CodeRank embeddings) and `pack_semantic` (semantic-tracer fuse). They are
> the same pack machinery with a different tracer binder and are not part of the default shipped
> set. The shipped ranker is `composite_v1`.

---

## 3. How an agent should use these tools (ideal trajectories)

The governing rules: **prefer host tools for needles, Scubiee for soft/structural discovery;
enter the ladder for edits/debugging; ≤ 3 locate calls per beat; never whole-file Read of a
heatmap path until you've read its loc spans.**

### 3.0 The default ladder

```
gate (once)                         → am I managed? get project_id
   ↓  (soft / unknown area)
map(query, k=12)                    → ranked cards + suggested_seeds  (no bodies)
   ↓  fold suggested_seed + hot card names into a denser query
pack_context(query, seed_*, lean)   → heatmap locs around the seed   (no bodies)
   ↓  Native-Read the top ~4–6 hot loc spans
expand_context(node, direction)     → only if a hop is missing (callers/callees/effects)
collect_hot_context(ids=…)          → only if you need bodies batched instead of native Read
```

### 3.1 "Where is X / how does X work?" (explore / explain)

1. `map("<X> with concrete symbols, paths, APIs, error strings, verbs>")`.
2. If the cards already cluster in one module and you only need to *explain* it, Native-Read the
   top card `loc` spans — you can skip pack (the "explain escape").
3. If you need the neighborhood, `pack_context(seed = suggested_seed, mode=lean)` and read the
   `chain` + hottest locs.
4. `expand_context(direction=callers)` to see who uses it, or `callees` for what it calls.

### 3.2 "Fix a bug in X" / "change behavior of X" (edit / debug)

1. `map` with the symptom + symbols + error text.
2. **`pack_context` is mandatory for an edit** — get the heatmap around the seed so you see the
   call chain and the spans that will be affected.
3. Native-Read the hot loc spans; edit with host tools.
4. `expand_context(direction=effects)` to catch logging/IO side effects, `callers` to find
   call sites you may break.
5. Verify (build/test) with host tools.

### 3.3 "Trace a data/control flow end to end"

1. `map` → pick the entrypoint seed.
2. `pack_context(seed)` for the spine (composite's DFG boost keeps the data path hot).
3. `expand_context(direction=callees, with_bodies=true)` hop by hop along the chain; the session
   remembers what's already expanded so each call returns only new deltas.

### 3.4 Needles (exact literals, imports, error strings, a known path)

Do **not** use `map`/`pack`. Use the host: **Grep** for literals/imports/error strings,
**Glob** for filenames, **Read** for a known `path:line`. Scubiee's own docs forbid soft
map/pack for needle lookups — it's slower and less precise than grep for exact strings.

### 3.5 Multi-module change

Use `map`'s `suggested_seeds[0..2]` as `seed_*`, `seed2_*`, `seed3_*` in one `pack_context` so
the merged heatmap forms a corridor across modules, instead of three separate packs.

### 3.6 Reorienting mid-task / new topic

`workspace(show)` to recall pins/heatmap/`focus_seen` before re-fetching; `workspace(pin, path)`
to keep an anchor; `workspace(clear)` when switching topics so a stale trace doesn't bias the
next `map`.

### 3.7 Health / warming

If `gate` says warming or a tool returns `status:"warming"`, **retry** the same tool in a few
seconds — don't fall back to native and don't spam `status`. If `gate` returns `p` (paused),
stop calling Scubiee entirely and use native tools.

---

## 4. Why this saves tokens (and still gives enough context)

The whole surface is engineered so the agent pays for **pointers first, bodies last, and only
the bodies it needs.**

1. **Ranked pointers instead of file dumps.** `map` and `pack_context` return `loc` + `score` +
   `why` with **no code bodies** by default. A heatmap of 12–16 cards is a few hundred tokens;
   the equivalent "read the 6 candidate files to find the right one" is tens of thousands. The
   agent reads only the handful of hot spans the heatmap points to.

2. **Precision ranking removes noise before it reaches the model.** `composite_v1` demotes sinks
   the query didn't ask for (×0.18), tiny/private helpers, and known noise files, while boosting
   the DFG spine and pinning the seed. The agent's context fills with the *load-bearing* spans,
   not accessor/logging clutter — higher signal per token.

3. **The ladder caps fan-out.** map → pack(lean) → expand, ≤ 3 locate calls per beat, is a
   bounded trajectory. `expand_context` returns **only delta** cards and the session tracks
   `packed_ids` / `expanded_ids` / `packed_ids_by_tool`, so the agent never re-pays for a span it
   already has. `focus_seen` and `already_in_pack:true` flags exist specifically to prevent
   redundant re-fetching.

4. **Bodies are opt-in and budgeted.** Default pack is heatmap-only. When bodies are needed,
   `budget_chars` / `max_bodies` cap the payload, bodies are fit to a fair share, and the seed is
   always preferred. `collect_hot_context` fetches bodies **by id** so the agent pulls exactly
   the spans it will edit — not their whole files.

5. **Loc-guided native Read replaces whole-file Read.** Every guide says *Native-Read the hot
   `loc` spans, BAN whole-file Read of heatmap paths.* Reading `engine.py:120-176` costs a
   fraction of reading a 2,000-line `engine.py`, and the heatmap already told the agent which
   56 lines matter.

6. **Semantic recall beats keyword spraying.** `map` uses dense embeddings
   (`D_channel_best`), so one good query finds the right area without the agent issuing many
   speculative greps and reading each result. Fewer discovery round-trips = fewer tokens.

7. **Warming honesty avoids wasted turns.** Returning `status:"warming"` (with a retry hint)
   instead of cold-baking or returning garbage means the agent doesn't burn a turn reasoning
   over an empty/degraded result and then re-doing the work.

8. **Needle discipline avoids the wrong tool.** By steering exact-string / filename / known-path
   lookups to host Grep/Glob/Read, the agent avoids paying the trace cost (and token cost) of a
   soft pack for something a one-line grep answers precisely.

**Net effect.** The agent spends tokens on *reasoning and editing* the correct ~5% of the code,
not on discovering it by reading the other 95%. Measured on the internal Claude Code SDK A/B
pipeline, routing retrieval through this surface cut code-reading tokens substantially while
preserving answer recall — the model still gets every span it needs, just not the spans it
doesn't.

---

## 5. Quick reference

| Tool | Call | Bodies? | Returns | Use when |
|------|------|---------|---------|----------|
| `gate` | pre-flight | no | managed signal (~5 tok) | start of chat |
| `status` | pre-flight | no | health + tool list | check warm/paused |
| `map` | 1 | no | ranked cards + suggested_seeds | soft/unknown area |
| `pack_context` | 2 | opt-in | heatmap locs (+chain, +bodies) | edit/debug around a seed |
| `expand_context` | 3 | opt-in | delta cards in a direction | missing callers/callees/effects |
| `collect_hot_context` | escape | yes | bodies for cards/ids | need bodies batched |
| `workspace` | any | no | pins/heatmap/focus_seen | reorient / pin / clear |
| `expand` | any | yes | one span by handle | re-hydrate a known span |

Rules of thumb: **needles → host Grep/Glob/Read. Soft/structural → Scubiee ladder. Edits →
pack. ≤ 3 locate calls per beat. Read the loc spans, not the whole file.**

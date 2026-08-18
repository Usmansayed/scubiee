# Index freshness vs agent trajectory — options menu

**Date:** 2026-08-16  
**Status:** exploration / decision space — **no policy locked**  
**Purpose:** Catalog every serious way Context Engine can stay fresh when agents are **forced to rely on CE tools**, without burning tokens or flipping rankings mid-thought. Use this to design the perfect mix later.

**Folder:** [`docs/reindexing/`](./)  
**Sibling:** [agent-write-patterns-and-channel-conflicts.md](./agent-write-patterns-and-channel-conflicts.md)

**Also related:** [productization-status.md](../productization-status.md), keeper sync lifecycle, retrieval trajectory research, sealed-nav postmortem, `engine.py` hot-patch path.

---

## 1. Why this is not “just a timer question”

When CE is optional, a slightly stale index is annoying.  
When CE is **mandatory** for locate, a wrong freshness policy becomes:

- **Token explosions** (re-map / re-search because hits changed or tools “feel wrong”)
- **Blind spots** (agent cannot find code *it just wrote*)
- **False confidence** (session memory says “already shown” while search ranks a different world)

So the design target is not “always newest embeddings.” It is:

> **Stable locate during a thought streak; correct enough for the agent’s next need; cheap commit when the streak ends.**

Timing numbers (this repo, ~3k chunks): full index ~2–5 min; incremental few files ~2–5 s; ~100 chunks often &lt;10 s; clean probe tens of ms.

---

## 2. Agent workflow (what we must serve)

Canonical loop (TraceLab + Cursor trials):

```text
cold / topic shift     → orient + soft/hard locate
follow-up              → session memory first, then delta locate
before edit            → open span (+ optional neighbors)
after edit             → verify (tests/shell) and/or re-locate wiring
long multi-turn        → avoid re-paying for same spans (handles / stubs)
```

Regimes that matter for freshness:

| Regime | Freshness need |
|--------|----------------|
| Cold start | Index **ready** and **stable** |
| Locate streak (map/search/focus) | Index **must not reshuffle** under the agent |
| Just wrote files | **Those files** must be findable soon |
| Same-session follow-up | Prefer **memory**; only fetch delta |
| Next session / next agent | Committed graph + dense index |

Evidence reminders:

- Locate+read ≈ half of tool calls; duplicate re-reads dominate append tax.
- Sealed thrash burned tokens **inside** CE even when seal held — often re-asking, not “index 5 minutes old.”
- Mid-task the agent already holds file bodies in context / handles — full reindex does not help *that* turn.

---

## 3. Building blocks we already have (or nearly)

| Building block | Role |
|----------------|------|
| Merkle + root probe | Cheap “anything dirty?” |
| Incremental extract + **graph patch** | Fast structural update for changed files |
| Re-embed changed chunks only | Semantic update without full corpus |
| FAISS / BM25 warm engine | Query path |
| **Hot-patch BM25 texts from disk** while dense lags | Search usable before embed finishes |
| Session store / handles / already-shown stubs | Don’t re-dump spans |
| Keeper interval + `.sync-trigger` | Background / external wake |
| Resource manager | Defer under pressure |
| Publish / generation | Swap searcher after sync |

Creative policy = **compose** these; do not invent a second indexer.

---

## 4. Option catalog (all the ways)

Each option can be on/off, combined, or gated by state.

### T — Timer / keeper family

| ID | Idea | Pros | Cons | Token risk if sealed |
|----|------|------|------|----------------------|
| **T1** | Probe every N min (4–5); sync only if dirty | Safety net; cheap when clean | Alone: lag after edits | Low if probe-only; **high if republish mid-locate** |
| **T2** | Always heavy reindex every N min | Simple mental model | Wastes CPU; rank flip | **High** |
| **T3** | Adaptive interval (busy agent → longer; idle → shorter) | Aligns with streaks | Needs “agent busy” signal | Medium |

### W — Write / edit triggered

| ID | Idea | Pros | Cons | Token risk |
|----|------|------|------|------------|
| **W1** | On file write / save: queue incremental | Fixes “can’t find what I wrote” | Needs reliable write signal | Low if debounced |
| **W2** | Quiet-window debounce (2–5 s after last write) | Coalesces save storms | Slight lag | Low |
| **W3** | Sync only files the **agent** wrote (from tool/diff list) | Smallest dirty set | Misses human/other-tab edits | Low |
| **W4** | Sync after Edit/Write tool success (MCP-aware) | Perfect for sealed loop | Host-specific hooks | Low |

### S — Session lifecycle

| ID | Idea | Pros | Cons | Token risk |
|----|------|------|------|------------|
| **S1** | Session-end / MCP disconnect catch-up | Best bulk commit; no mid-thought flip | Same-turn post-edit locate still stale | Low mid-session |
| **S2** | Agent-idle (no tools N seconds) drain queue | Soft session-end | Idle detection fuzzy | Low |
| **S3** | Next `map`/`search` after idle drains first | Ensures next locate is fresh | First call slower | Medium if blocking |

### L — Locate-streak protection

| ID | Idea | Pros | Cons | Token risk |
|----|------|------|------|------------|
| **L1** | Freeze publish while locate streak active; queue sync | Prevents thrash from rank flip | Stale until streak ends | **Protects tokens** |
| **L2** | Generation pin: tool results stamped; ignore newer gen mid-streak | Strong consistency | Complexity | Protects |
| **L3** | Soft hint in tool payload: `index_generation`, `dirty_files` | Agent can choose re-map | Agents may ignore / over-react | Mixed |

### U — Unindexed / dirty-file creativity (mid-session)

Core insight: **disk is ahead of dense index**; session already has some files. Don’t wait for perfect embeddings to answer.

| ID | Idea | Pros | Cons | Token risk |
|----|------|------|------|------------|
| **U1** | Track `dirty_unindexed` set (merkle vs last publish) | Honest status | Need surface in `status`/cards | — |
| **U2** | Hot-patch BM25 from disk for dirty files (exists) | Instant lexical truth | Soft semantic lag | Low |
| **U3** | Live extract dirty files into **ephemeral graph overlay** (no embed yet) | Neighbors/wiring for new symbols | Overlay merge logic | Low |
| **U4** | On `map`/`search`, if query terms hit dirty paths, **boost / inject** those files into results | Finds new code without full embed | Ranking heuristics | Low–medium |
| **U5** | “Session-authored files” channel: paths agent Edited this turn always eligible | Perfect for sealed “I just added X” | Needs edit telemetry | Low |
| **U6** | Degraded mode card: `semantic_stale_for: [...]` + “use focus on path / BM25 exact” | Transparent | Instruction budget | Low if short |
| **U7** | Skip re-embed for files still fully in session handles; graph-patch only | Saves GPU mid-session | Next session needs embed | Low |
| **U8** | Dual index: **stable published** + **scratch overlay**; queries merge; publish promotes scratch → stable at idle | Best of both worlds | Hardest to build right | Lowest if done well |

### G — Graph vs semantic split timing

| ID | Idea | Pros | Cons |
|----|------|------|------|
| **G1** | Graph patch sync **eager** (after write); dense embed **lazy** (idle / session-end) | Wiring fast; GPU calm | Soft locate lag on brand-new prose |
| **G2** | Embed eager for tiny dirty sets (≤N chunks); lazy otherwise | Hits &lt;10 s often | Threshold tuning |
| **G3** | Graph-only repair from AST cache hourly; never full AST on timer | Heals merge drift | Rare cost |

### M — Memory-first (context already paid for)

| ID | Idea | Pros | Cons |
|----|------|------|------|
| **M1** | Trajectory: follow-up → `workspace`/`recall` before re-map | Cuts tokens (proven waste pattern) | Needs instruction + stubs that agents obey |
| **M2** | If file in session and dirty on disk, `focus` reads **disk** not cached span | Always true body | Must invalidate handle content |
| **M3** | Don’t invalidate whole session on index publish — only dirty handles | Less thrash | Careful invalidation rules |

### R — Repair / refuse / full

| ID | Idea | Pros | Cons |
|----|------|------|------|
| **R1** | Large drift → `needs_full`; never background-full by default | Avoids storm | User/agent must wait or consent |
| **R2** | Chunked catch-up (batches of ≤K files per tick) | Smooth | Longer dirty window |
| **R3** | Nightly / on-open full when broken | Correctness | Slow |

### H — Host / product signals

| ID | Idea | Notes |
|----|------|------|
| **H1** | IDE file-watcher → `.sync-trigger` | Already half-there |
| **H2** | Git hooks (post-checkout, post-commit) | Branch switches |
| **H3** | Explicit agent tool `sync` / `status` “refresh now” | Escape hatch; easy to thrash if overused — gate it |

---

## 5. Composite recipes (candidates for “the perfect mix”)

Not commitments — sketches to debate.

### Recipe A — “Stable streak + write overlay” (strong default candidate)

```text
L1 freeze publish during locate streak
W2 debounce writes → queue dirty paths
U2+U3+U5 scratch: BM25 hot-patch + graph overlay + session-authored boost
G1 eager graph patch; lazy dense at S1/S2 idle or session-end
T1 4–5 min probe drains queue only if no active streak
R1 refuse huge incremental
```

**Why it fits sealed CE:** mid-locate rankings stable; new files findable via overlay; GPU work happens when the agent is not mid-map.

### Recipe B — “Session-end heavy only”

```text
T1 probe only
S1 full incremental catch-up at disconnect
U2 hot-patch during session if dirty
```

**Simpler.** Weak when agent must `map` its own new tool in the same turn.

### Recipe C — “Aggressive live index”

```text
W1 every write → immediate incremental embed+graph+publish
T2 optional
```

**Correctness-max.** Highest risk of mid-streak confusion and laptop heat; only if publish is generation-pinned (L2).

### Recipe D — “Dual index U8”

```text
Published generation immutable during streak
Scratch overlay absorbs all writes
Queries = merge(published, scratch)
Idle/session-end promotes scratch → new published generation
```

**Most creative / most reliable long-term**; most engineering. Best answer if we invest.

---

## 6. Decision matrix (how to pick later)

Score each recipe against sealed-agent KPIs:

| KPI | Question |
|-----|----------|
| Task success | Does agent find code it just added? |
| Work tokens | Does freshness cause re-map loops? |
| First edit step | Does wait-for-index delay mutate? |
| Wall / laptop | Does sync fight the user mid-type? |
| Implement cost | Weeks vs days? |
| Operability | Can `status` explain `ready/dirty/overlay/deferred`? |

**Hypothesis to validate in trials (not assumed):**

> Recipe A or D beats T2 and beats S1-only on sealed combo tasks, especially “add tool then locate it again,” with equal or lower tokens than mid-session republish.

---

## 7. Mid-session “unindexed files” playbook (detail)

When `dirty = merkle − last_published`:

1. **Still answer tools** — never block map on embed.
2. **Prefer disk for focus/read** on dirty paths (M2).
3. **BM25/graph overlay** includes dirty extracts (U2/U3).
4. **Dense** may omit or down-rank until embed; card can say `dense_pending: [paths]` (U6) in ≤1 line.
5. **Session context** covers files already focused — don’t re-tax (M1/M3).
6. **Promote** dirty → published only at: quiet write window, idle, session-end, or timer with L1 clear.

This is how we can be “very creative” without pretending full 3k-chunk re-embed fits in 10 seconds mid-chat.

---

## 8. What would confuse the agent (anti-patterns)

1. Republishing FAISS mid-`map` streak → new top-k → agent re-explores → token spike.  
2. Session stub “unchanged” while file on disk changed → wrong edit.  
3. Silent defer under resource pressure with no `status` → agent thinks CE is broken → native escape / thrash.  
4. Forcing full reindex on 5-min timer “to be safe.”  
5. Exposing a free `sync` tool without budgets (new thrash surface).

---

## 9. Open questions (spend time here)

1. What is the reliable **“locate streak active”** signal (last CE tool &lt; T seconds? explicit workspace mode)?  
2. Do we get **write events** from the host, or only merkle/probe?  
3. Is **U8 dual index** worth the complexity for v1, or is A (overlay + freeze) enough?  
4. Should `focus` always read disk, and only `map`/`search` use the index?  
5. How large can scratch overlay grow before forced promote?  
6. For Codex vs Cursor: same policy, or weaker write hooks on CLI?  
7. Eval protocol: sealed task “implement + re-locate own symbol” with freshness arms A/B/C/D.

---

## 10. Suggested working conclusion (still not locked)

- **Do not** choose “only 5 minutes” or “only after session.”  
- **Do** design for **agent phases**: stable during locate; overlay for dirty mid-session; commit on idle/session-end; timer as backup probe.  
- **Lean creative capacity** is mid-session **unindexed/dirty handling** (BM25 + graph overlay + session-authored boost), not faster full re-embeds.  
- Next step when ready: pick Recipe A vs D, write a short implementation plan, then A/B on a sealed “edit then find” task.

---

## 11. Appendix — quick option index

`T1–T3` timers · `W1–W4` writes · `S1–S3` session · `L1–L3` streak freeze · `U1–U8` unindexed/overlay · `G1–G3` graph/embed split · `M1–M3` memory · `R1–R3` repair · `H1–H3` host signals · Recipes **A–D**.

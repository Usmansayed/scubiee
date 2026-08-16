# # How agents write code — and what that means for reindexing

**Date:** 2026-08-16  

**Status:** evidence notes + conflict design questions — **not locked**  

**Folder:** `docs/reindexing/`](./)

**Companion:** [[index-freshness-agent-trajectory.md](http://index-freshness-agent-trajectory.md)](./[index-freshness-agent-trajectory.md](http://index-freshness-agent-trajectory.md))  

**Sources:** TraceLab trajectory research (200 sessions), Cursor sealed/CE trials, engineering sync docs. Exact per-edit rewrite rates are **estimated from workflows** where TraceLab is sanitized (no paths/diff text); treat percentages as **order-of-magnitude**, then validate with a dedicated edit-telemetry pass.

---

## 1. Problems we need frequencies for (decision drivers)

| # | Question | Why it matters for indexing |

|---|----------|-----------------------------|

| P1 | How often does an agent **rewrite / re-edit the same file immediately** after writing it? | If rare → **on-file-change index** is fine. If common → need **debounce** (quiet window) or we thrash extract/embed. |

| P2 | How often is the next action **verify** (test/shell) vs **locate again** vs **another edit**? | Verify-heavy → session can tolerate slightly stale dense index. Locate-after-edit → need dirty overlay / BM25. |

| P3 | How often do agents **delete** large chunks vs **surgical edit** vs **append**? | Deletes need **prune** in graph + vector remove; appends are cheaper patches. |

| P4 | How many **distinct files** touched per task / per burst? | Caps incremental cost (few files ≪ 100 chunks often &lt;10 s). |

| P5 | How often do they **re-read the same file** after editing it (via CE)? | Session handles vs disk truth; invalidation rules. |

| P6 | When search returns **mixed generations** (fresh BM25 chunk + stale dense chunk), what should win? | Ranking / conflict policy — see §4. |

---

## 2. Information points — how AI agents write (6+)

### IP1 — Canonical chain is locate → read → **mutate** → verify (not “index → write”)

Across TraceLab, retrieval dominates tools; mutation comes **after** a locate/read streak. p50 ~**27** tools before first mutate; Cursor thrash arms saw first_edit at **~57–111**.  

**Implication:** Most of the session, the index should stay **stable**. Heavy reindex mid-locate hurts more than helping.

### IP2 — Immediate rewrite of the *same* file is common enough to debounce, not rare enough to ignore

Observed agent behavior (Cursor/Claude/Codex style coding):

- Patch → run test → fail → **same file again** (repair loop) is a **primary** repair regime (WF3).

- “Write whole file → fix imports → fix types” often = **2–5 writes** to one path in &lt;1–2 minutes.

- True one-and-done single write to a file happens, but **repair multi-touch** is frequent on hard tasks.

**Working estimate (to validate):** in edit-heavy segments, **~40–70%** of written files get **at least one more edit within ~60s**; bursts of **3+** writes to one file in a minute are common in repair, uncommon in calm append-only work.

**Implication for on-file-change indexing:**  

**Yes, trigger on change — but always with a quiet-window debounce (e.g. 2–5s, or “until verify starts / locate streak ends”).** Instant sync on every ApplyPatch will re-extract/re-embed thrashing files.

### IP3 — After a write, the *next* tool is often verify or another edit — not CE locate

Typical post-mutate forks:

| Next action | Rough prevalence in coding agents | Freshness need |

|-------------|-----------------------------------|----------------|

| Test / shell / linter | High | Disk truth; CE optional |

| Another Edit on same file | High in repair | Debounce sync |

| Edit related file (wiring) | Medium | Dirty set grows |

| CE `mapsearch` for “did it register?” | Medium on sealed CE | **Needs dirty visibility** |

| Re-read same file via CE | Medium–high (thrash) | Disk focus + invalidate handles |

**Implication:** Session-end-only indexing is too late for sealed “find what I registered,” but **full embed on every keystroke** is waste. Overlay + debounce is the middle.

### IP4 — Deletes and renames are less frequent than edits, but more dangerous if missed

Agents more often **edit in place** or **add** symbols than delete whole modules. When they do delete/rename:

- Stale graph nodes (“ghosts”) and stale FAISS chunks cause **wrong neighbors** and phantom hits.

- Frequency: lower than edits (order-of-magnitude: deletes maybe **~5–15%** of file events vs modifies), but **must** be handled (merkle `removed` → prune graph + drop vectors).

**Implication:** Dirty set must include **removed** paths, not only modified. On-file-change without prune is incomplete.

### IP5 — File fan-out per task is usually small; chunk fan-out can still hit ~50–100

Combo-style tasks may touch **~10–20 source files**, but many files = few chunks; a few hub files = many chunks. Trials often land in **tens of files**, not hundreds, per agent turn-set.

**Implication:** On-change incremental for “agent dirty set” is usually affordable (&lt;10 s for ~100 chunks). Timer full-corpus is not required for write freshness.

### IP6 — Agents re-fetch / re-focus the same areas a lot (token tax ≠ rewrite tax)

TraceLab: duplicate signatures P50 ~**21%** of result chars; almost all multi-turn sessions. Sealed CE: majority of `read`s returned already-seen stubs in one postmortem.  

**Implication:** Freshness policy must not **invalidate the whole session** on every publish. Only **dirty paths’ handles** should refresh. Re-fetch thrash is a bigger token problem than “index 3 minutes old.”

### IP7 — Follow-up turns (WF2 ~30%) rarely need a cold reindex

T2 behavior: same area, memory-first. CE already wins on follow-ups when session memory works (~60–70% fewer context tokens in multi-turn notes).  

**Implication:** Prefer **M1 memory-first**; indexing policy is for **new disk state**, not for re-explaining old context.

### IP8 — “Remove code” often means shrink a span, not delete a file

Agents delete functions/blocks inside a file more often than `rm` the file. Graphify replace-by`source_file` on re-extract handles this **if that file is re-extracted**.  

**Implication:** Re-extract **whole dirty file** (not chunk-level guess) on promote; don’t try to surgically delete one embedding without a file-level rebuild for that path.

---

## 3. Should we index on file change? (given the frequencies)

| If we believe… | Policy |

|----------------|--------|

| IP2 (multi-touch common) | **On change + debounce**, never sync-per-keystroke |

| IP3 (verify often next) | Don’t block the agent on embed; **queue** |

| IP5 (small dirty sets) | On-change incremental is **feasible** |

| IP1 (long locate first) | **Freeze publish** during locate streak |

| IP4 (rare but sharp deletes) | On-change must handle **removed** |

**Lean decision (still open to A/B):**  

**Yes — file-change (or agent-write) triggered incremental is justified**, but only as **queue + debounce + overlay**, with **dense publish** at quiet/idle/session-end — not as immediate full FAISS republish every ApplyPatch.

---

## 4. Channel conflicts — BM25-fresh vs dense-stale (and friends)

### 4.1 The conflict

After a write, channels diverge:

```text

Disk:     new source (truth)

BM25:     can hot-patch from disk  → fresh lexical hits

Graph:    can patch from extract   → fresh wiring (if we ran extract)

Dense:    still old vectors        → may rank OLD chunk text / miss new symbols

Session:  may hold old span body   → stub “unchanged” lies if not invalidated

```

Example: top-2 results for one query =

1. Hit A — BM25 on **new** text (dirty file)  

2. Hit B — dense on **old** embedding (same or neighbor file)

Agent sees mixed truth → confusion, extra reads, tokens.

### 4.2 Do we keep an index of not-yet-indexed (dirty) files?

**Yes — a first-class `dirty_set` (or scratch overlay), not an informal side effect.**

Minimum fields per path:

| Field | Purpose |

|-------|---------|

| `path` | Repo-relative |

| `content_hash` / mtime | Identity |

| `state` | `disk_dirty` \| `bm25_patched` \| `graph_patched` \| `dense_pending` \| `published` |

| `reason` | `agent_write` \| `probe` \| `external` |

| `session_touch` | Edited this CE session? |

This is the **ledger** that drives boosts, demotions, and promote-to-published.

### 4.3 Ranking rules when channels disagree (candidates)

**Rule set C1 — Prefer freshness over channel prestige (recommended to try)**

1. If a hit’s path ∈ `dirty_set` and BM25/graph overlay has a span → **prefer overlay/disk span**; mark `freshness=disk`.  

2. If dense hit’s path ∈ `dirty_set` and dense not yet rebuilt → **demote dense** (or drop from soft map) unless no other evidence.  

3. If two hits same path, different generations → **keep newer disk/BM25**, drop stale dense duplicate.  

4. Cross-file: dirty path boosted when query tokens match new identifiers (U4/U5).  

5. `focusread` on dirty path → **always disk** (never stale handle body).

**Rule set C2 — Dual list**

Return `results` (stable published) + `scratch_hits` (dirty) separately so the agent doesn’t merge them blindly. More honest; more instruction tokens.

**Rule set C3 — Block until consistent**

Refuse search until dense catches dirty set. **Bad for sealed agents** (latency + thrash). Reject for mid-session.

### 4.4 Weighting sketch (implementation hint, not final)

```text

score = α  *dense + β*  bm25 + γ * graph

if path in dirty_set and dense_stale:

    α → 0 or α * 0.2

    β → β * 1.5   # or inject disk chunk as synthetic doc

    γ → γ * 1.2 if graph_patched else γ

if path in session_authored:

    inject floor boost so it cannot fall off top-k for symbol queries

```

**Straight-from-source chunks:** for dirty paths, build a **temporary chunk text from disk** (same compress/mix pipeline, skip FAISS write) and score with BM25 (+ optional cheap embedding later). That is the “source chunk” channel — not a second permanent index until promote.

### 4.5 Conflict anti-patterns

- Showing dense “why” snippets that no longer exist on disk.  

- Hot-patching BM25 but leaving old dense neighbor edges pointing at deleted symbols.  

- Invalidating **all** session handles when one file goes dirty.  

- Letting stale dense and fresh BM25 **tie** without a freshness tag.

---

## 5. Extra info points tying write behavior → conflict policy

1. **Repair loops** (same file many times) → debounce means BM25/graph overlay may update **once per burst**, dense once at end — conflicts are **normal mid-burst**; policy must assume them.  

2. **Verify-next** → agent may not query CE until later; overlay can stay dirty longer without harm.  

3. **Locate-after-edit** (sealed) → conflict policy **is** the product; without it, file-change indexing alone still fails if dense lags.  

4. **Delete-inside-file** → file stays “modified”; whole-file re-extract on promote clears ghosts — don’t rely on dense delete-by-chunk-id mid-session.  

5. **Multi-file wiring edits** → dirty_set size jumps; cap overlay size; if over cap, force promote or `needs_full` chunked.  

6. **Human + agent both writing** → dirty ledger must accept non-agent reasons; don’t only track ApplyPatch.

---

*## 6. Measurements we should still run (to harden the %)*

Add a small analyzer on CE/Cursor/Codex trial JSONL:

- writes per path; inter-write gaps;  

- fraction of paths with ≥2 writes in 60s;  

- tool after write: Edit | Shell | CE locate | CE read;  

- deletes vs modifies (git diff stats);  

- files touched / chunks touched per arm.

Until then, use §2 estimates as **priors**, not gospel.

---

## 7. Working synthesis (for later locking)

1. Agents **do** often re-touch files soon after write → **on-change yes, debounce mandatory**.  

2. They **don’t** usually need full dense republish between those touches → **overlay + dirty ledger**.  

3. Channel conflicts are expected → **keep `dirty_set`; prefer BM25/disk/graph for dirty paths; demote stale dense; focus always from disk**.  

4. Removals are rarer but must prune.  

5. Token pain is still mostly **re-fetch**, so don’t nuke session memory on every sync.

Next: fold these IPs into a chosen Recipe (A or D) in the trajectory doc, then A/B “edit then map own symbol” with/without dirty ranking rules.
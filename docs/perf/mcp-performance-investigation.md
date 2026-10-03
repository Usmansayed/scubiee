# Scubiee MCP (Map V3) — Performance Investigation

A systematic, measurement-driven investigation of the Scubiee MCP tool surface.
One tool at a time: trace the real execution path, profile each stage with real
numbers, research + test optimizations, validate against the current implementation,
and keep behavior/quality identical.

**Rule of this document: no claim without a measurement.** Every latency figure
here is produced by a reproducible harness on the real build, not estimated.

---

## 0. Environment & methodology

| Item | Value |
|---|---|
| Build under test | `scubiee 0.3.138` (uv tool install) |
| Repo under test | `context-engine` (self-hosted; ~8,500 indexed chunks, ~4,900 code/test files, ~28 MB source) |
| OS / Python | Windows, `C:\Users\usman\Miniconda3\python.exe` (worker interpreter: uv-tool pythonw) |
| Engine | local HTTP daemon on `127.0.0.1:8765`, DirectML embedder |
| project_id | `ce_3536ac8e8e83bb8e4d888db37847729c` |

### Measurement rules
- **Warm vs cold are reported separately.** "Warm" = engine dense-ready + worker
  file caches populated. "Cold" = first call into a fresh worker/engine.
- In-process profiling (import `map_v3_server`, call `tool_map`) isolates
  **bridge/helper CPU** from transport. Stdio/bridge profiling measures the
  **real production path** (IDE → `mcp_bridge` → worker → engine).
- Each number is the median of N≥3 runs unless noted; outliers (first-call warm
  tax) are called out explicitly.
- Timers: `time.perf_counter()` around the exact span; helper-level timing via
  monkeypatched wrappers that accumulate cumulative ms + call counts.
- Console on this host intermittently truncates stdout; harness output is written
  to `dist/_*.txt`/`.json` and read from file to avoid lost lines.

### Idle/warm note
`.kiro/settings/mcp.json` sets `CTX_ENGINE_IDLE_S=10` / `CTX_EMBED_IDLE_DEMOTE_S=10`
(aggressive demote for RAM). For latency measurement we set both to `600` so the
engine does not demote mid-run; this is a measurement setting, not a product change.

---

## 1. Architecture & request path (as implemented, verified by reading source)

### Tool surface
The shipped MCP exposes exactly three tools (`packages/pipeline/map_v3_server.py` `TOOLS`):

| Tool | Fn | What it does |
|---|---|---|
| `gate` | `map_v3_helpers.tool_gate` | Health/managed signal: `1:<project_id>` / `1` / `0`. |
| `status` | `map_v3_helpers.tool_status` | One-line engine health string. |
| `map` | `map_v3_server.tool_map` → `cfg_find/cfg_focus/cfg_related/cfg_graph` | The locate tool; `config` selects the handler. |

`map` configs (hard set, `CONFIGS = ("find","focus","related","graph")`):
- **find** — "where is X": engine dense search + keyword grep + enclosing-symbol
  bodies + a "connections" (callers/callees) block for the top symbol.
- **focus** — a named symbol's full body + callers/callees + sibling names, one unit.
- **related** — given an anchor chunk + query, related code bodies in one call.
- **graph** — abstract JSON map (files → top-level symbol names + call edges, no bodies).

### Request path (production)
```
IDE (Kiro)  ──stdio JSON-RPC──▶  pipeline.mcp_bridge  (transport proxy, 1 warm worker)
                                        │ spawns / proxies
                                        ▼
                                pipeline.map_v3_server  (stdin loop, SINGLE-THREADED)
                                        │ TOOLS[name].fn(args)
                                        ▼
                                pipeline.map_v3_helpers  (self-contained: stdlib + HTTP)
                                        │ _http(path, payload)  (urllib, retry-once +0.3s)
                                        ▼
                                engine HTTP 127.0.0.1:8765  (pipeline.server)
                                        │  /health, /v1/search, /v1/grep, /v1/outline
                                        ▼
                                pipeline.ce_service  →  retrieval/embedder/store
```

Key structural facts (verified in source, relevant to latency):
- The worker (`map_v3_server.main`) is a **synchronous single-threaded** `for raw in sys.stdin` loop — one tool call fully handled before the next is read. Concurrency on the real path is handled by `mcp_bridge` spawning/pooling workers, not by the worker itself.
- `map_v3_helpers` imports **nothing** from the rest of `pipeline.*` — it talks to the engine only over HTTP (`/v1/search`, `/v1/grep`, `/v1/outline`, `/health`) and reads file text from disk under `REPO`. So helper-side cost = (HTTP round-trips) + (local disk/CPU: file walk, grep, AST outline, body slicing).
- `_http` (the one network primitive) does a urllib request with **retry-once + 0.3s sleep** on failure; a cold/transiently-unavailable engine therefore adds ≥300 ms per failed attempt.
- A background `_warm()` thread pre-reads code/test files into mtime-keyed caches (`_LINES`/`_TEXT`) on worker start, and (as of 0.3.138) stamps a grep stat-TTL so the first real grep skips the per-file `stat()` pass.
- The engine `/health` (`ce_service.health`) is intentionally in-memory/lock-free (comment: disk peek + ORT status previously starved it ~3s). Residual per-call work: `warm_autoload.read_phase()` (reads a small phase file) and, only on the cold binder path, `peek_project` + `index_is_usable` (disk).

### Prior optimization already landed (0.3.138 — context for this investigation)
`_grep` (whole-repo identifier grep used by find/focus/related to find callers/defs)
was ~1 s of regex over ~28 MB + ~300 ms of per-file `stat()`. 0.3.138 added:
1. a required-substring **prefilter** (C-level `in` skip before regex), and
2. a **stat-TTL** so back-to-back calls reuse the warmed file cache,
3. with the warm thread stamping the TTL so the first call is fast too.
Measured warm steady-state after that change: find ~2000→~300–700 ms, focus
~2460→~350 ms, related ~1320→~190 ms, graph ~430→~365 ms. Behavior byte-identical
(prefilter is a strictly-necessary condition; verified with a naive-vs-fast equality
sweep across representative patterns).

This investigation re-measures from that baseline and goes deeper, tool by tool.

---

## 2. Baseline latency (to be filled per tool below)

Numbers are added by each tool section as they are measured. See the per-tool
sections for stage breakdowns and experiments.


---

## TOOL 1 & 2 — `status` and `gate` (health signals)

Both tools are, in full:
```python
def tool_gate(_a):   ok = bool(_http("/health", timeout=10).get("ok"));  return "1:<pid>"/"1"/"0"
def tool_status(_a): h  = _http("/health", timeout=10);                  return "ok=.. warm=.. dense=.. phase=.. chunks=.. version=.."
```
So they are **one `/health` round-trip + a string format**. There is no retrieval,
no disk walk, no AST. They establish the transport floor every tool pays.

### How it works (stages)
1. worker receives `tools/call` on stdin (JSON parse)
2. `_http("/health")` → urllib opens a **fresh TCP connection** to `127.0.0.1:8765`, GET, read, close
3. engine `ce_service.health()` computes an in-memory status dict
4. worker formats a short string, writes JSON-RPC to stdout

### Where the time goes (measured, warm, N≥15, median)
| Surface | p50 | min | p95 | note |
|---|---|---|---|---|
| raw engine `/health` (HTTP) | **15.7 ms** | 3.4 | 27 | the floor |
| in-process `tool_gate` | 15.8 ms | 3.4 | 28 | helper adds ~0 |
| in-process `tool_status` | 15.5 ms | 3.4 | 25 | helper adds ~0 |
| stdio worker `gate` | 15.2 ms | 3.7 | 28 | stdio framing adds ~0 |
| stdio worker `status` | 15.1 ms | 3.8 | 29 | — |
| bridge path `gate` | 13.7 ms | 5.3 | 392* | *392 = first-call worker spawn |
| bridge path `status` | 5.8 ms | 5.2 | 24 | — |

Inside `ce_service.health()` (measured against live engine modules):
`read_phase()` p50 **0.4 ms**, `embedder_is_loaded()` **0.0 ms** (cached flag),
`prewarm_status()` **0.3 ms**. Handler work ≈ **1 ms**.

### Conclusion: the cost is TCP connect to a stdlib HTTP server, not computation
The ~15 ms p50 (spread 3.3→28 ms, occasional 130–300 ms) is **per-request TCP
connection setup + stdlib `BaseHTTPServer` handling**, not health logic. Evidence:
- handler internals total ~1 ms;
- "spaced" calls (0.25 s gaps) are *slower* (p50 22.7 ms) than bursts — classic fresh-connect cost;
- the server advertises **`HTTP/1.0`** (`r.version == 10`), i.e. connections close per request by default.

### Experiment — HTTP keep-alive (validated)
Reusing one persistent connection vs fresh-per-call, same `/health`:

| mode | p50 | min |
|---|---|---|
| fresh connection per call (today) | 15.2 ms | 3.3 |
| persistent keep-alive connection | **4.6 ms** | 3.1 |

~3.3x faster per round-trip; the server honored keep-alive (`server_kept_alive=True`)
even though it only speaks HTTP/1.0.

### Decision for the health tools
**Do not optimize gate/status in isolation.** The absolute saving is ~10 ms on a
tool called ~once per session — not worth added connection-lifecycle complexity or
risk. The *interesting* consequence is for `map`, which makes **multiple** `_http`
calls per request; keep-alive is re-evaluated there (TOOL 3) where it can compound.

### What was investigated / discovered / tested / not pursued
- Investigated: full stage breakdown, `ce.health()` internals, connection model.
- Discovered: health logic ≈1 ms; the latency is TCP-connect to an HTTP/1.0 stdlib server.
- Tested: keep-alive → 15→4.6 ms per round-trip (real, repeatable).
- Not pursued (here): wiring keep-alive into `_http` — deferred to the system-wide
  section because it is a cross-cutting change that mainly benefits `map`, and the
  stdlib server is HTTP/1.0 (needs `protocol_version="HTTP/1.1"` + a reused
  connection in the worker; must be validated for correctness under the bridge's
  worker lifecycle before shipping).
- Remaining to explore: whether a Unix-domain/named-pipe or in-process transport
  would beat loopback TCP (likely overkill given absolute numbers).


---

## TOOL 3 — `map config=find`

### How it works (stages, from `map_v3_helpers.cfg_find`)
1. `sem_q = query + keywords`; **`_search(sem_q, top_k≥24)`** → engine `/v1/search` (the **only HTTP call** — confirmed 1 per find).
2. For each hit: `add_cand` → `_enclosing` (AST outline on cached text), `_code_text`, `_lines` — all local, cached.
3. If `keywords`: one `_grep(keyword pattern)` (local, prefiltered since 0.3.138).
4. Rank candidates (semantic ± keyword/qword coverage), pick top-k, assign confidence.
5. On high/medium confidence: assemble bodies (`_numbered`/`_lines`, local) for the clustered top file(s).
6. `_append_connections(top)` → `_callers_of` (**one `_grep`**) + `_callees_in` (local regex over the body).

So HTTP budget per find = **exactly 1** (`/v1/search`); grep budget = 0–2 (callers always when a top symbol exists; +1 for keyword queries).

### Where the time goes (measured, warm, in-process, N≥7)
| query type | total | `_search` (HTTP) | `_grep` | everything else |
|---|---|---|---|---|
| no-kw, fast | 68–81 ms | 57–72 ms | 0 (no caller grep hit cap) | <12 ms |
| no-kw, slow-search | 317 ms | **308 ms** | 0 | <12 ms |
| no-kw, +callers grep | 379 ms | 137 ms | 231 ms | <15 ms |
| keyword | 466–494 ms | 51–72 ms | **367–387 ms** (×2 greps) | ~45 ms (`_lines` n=584) |

find latency distribution (warm): min 68, **p50 317**, p95 494 ms.
AST/body assembly (`_enclosing`/`_outline`/`_code_text`/`_lines`/`_numbered`) totals **<15 ms** — negligible.

### The two real cost centers
**(1) Engine `/v1/search` — variable 51–308 ms.** Engine self-reports `timings`:
- warm steady: `total_ms` 15–35, `embed_ms` **0.2–0.3** (query embedding **cached**), `retrieve_ms` 15–33.
- `embed_ms` spikes to **114–146 ms** on the *first* time a given query string is embedded (cold query-embed cache), then 0.2 ms on repeat.
- `retrieve_ms` spikes to **170–300 ms** for some queries (dense/FAISS + fusion scaling with candidate set), reproducibly per-query.
- Wall = engine `total_ms` + ~15 ms HTTP floor + ~34 ms (connection + body). On loopback the body size is NOT a latency factor (see experiment).

**(2) `_grep` — 150–390 ms when it runs** (caller lookup, +keyword match). Already optimized in 0.3.138 (prefilter + stat-TTL); re-examined per-query below.

### Experiment A — lean `/v1/search` (drop the discarded `keeper` block) — VALIDATED, but NOT a latency win
`map_v3_helpers._search` consumes only `hits`. Measured response composition:
total **6802 B** = hits **1700 B (25%)** + **keeper 4424 B (65%)** + timings 288 B. The
`keeper` block is `sync_loop.status()` (dirty-ledger snapshot + ~21 fields),
serialized, sent, parsed, then **discarded**.

Implemented an opt-out: `ce.search(..., lean=True)` omits `keeper`/`timings`;
`/v1/search` reads `lean` from the request; `_search` sends `lean:True`. A/B against
a source-run engine, interleaved, N=20:

| | full (old) | lean (new) |
|---|---|---|
| body bytes (p50) | 8020 | **4920 (39% smaller)** |
| wall ms (p50) | 93.4 | 94.3 |
| hits identical | — | **True** |

**Verdict:** correct and behavior-preserving (hits byte-identical); eliminates ~3 KB
of wasted serialize/transfer/parse + the `sync_loop.status()` build per search. **But
wall time did not move (−0.8 ms)** — on loopback, 3 KB is sub-ms. Kept as a waste/
hygiene improvement (and a real win if the engine is ever remote), **not** sold as a
latency optimization. *Lesson: the "body is 65% of the response" fact did not imply a
latency bottleneck — measurement overturned the assumption.*

### Still open (the actual latency drivers — next experiments)
- **Why does `retrieve_ms` swing 15→300 ms per query?** This is the dominant, variable
  cost. Needs engine-side profiling of `eng.search` (dense FAISS vs BM25 vs fusion vs
  re-rank). Investigated in the next step.
- **Query-embed cold miss (114–146 ms first time):** is the query-embed cache
  per-process/persistent? Can common/first-call embeds be warmed?
- **Keyword path runs 2 greps + reads 584 files (37 ms of `_lines`):** can the keyword
  grep reuse the caller grep, or be scoped tighter?


### Experiment B — root-causing the engine `retrieve_ms` variance (15 → 315 ms)
Added temporary per-channel instrumentation to `MultiArchConductor._channel_maps`
(graph/bm25/dense block ms, surfaced via `timings.channels`) and ran soft NL vs
path-like queries against a source-run engine. Verified the retrieve is **not**
result-cached: the same soft query repeats at ~300 ms every call (`embed_ms`~1 ms
because the query-embed IS cached; `retrieve_ms` recomputes).

Per-channel block time (warm, dense):
| query | plike | retrieve_ms | **graph** | bm25 | dense |
|---|---|---|---|---|---|
| "how the map v3 server dispatches a tool call…" | 0.095 | **322** | **315** | 1.6 | 0.1 |
| "how the bridge spawns and respawns the worker…" | 0.194 | 36 | 20 | 2.1 | 0.0 |
| "what happens when a client disconnects…" | 0.071 | 41 | 34 | 1.0 | 0.0 |

**100% of the retrieve variance is the graph affinity channel** (`graphify_retriever.
affinity_scores`). BM25 (`score_all`) and dense (`score_all`) are vectorized numpy —
1–2 ms and ~0 ms, query-independent. The graph channel is an **unbounded BFS**:
`_channel_maps` calls `affinity_scores(query, n)` with no `max_visit`, so a soft query
that seeds many common graph nodes walks a large fraction of the call graph (`_score_query`
over all nodes + `deque` BFS via `G.neighbors`), spiking to 315 ms.

**The pivotal fact:** in `retrieve_D_channel_best`, graph only *tags* files dense already
retrieved ("BM25 and graph cannot add a file semantic search did not retrieve"), and for
soft queries (`plike ≤ 0.35`) the graph score weight in `_score` is **0.005** — i.e. the
315 ms graph walk contributes almost nothing to the soft-query ranking. This is the
prime optimization candidate: **bound/skip the graph BFS where it costs 315 ms but
changes ranking by ~0**, validated by result equality. (Designed + tested next.)


### Experiment C — isolating the 290 ms to `_score_query` (NOT the BFS)
Added sub-timing inside `graphify_retriever.affinity_scores`. For the slow soft query:
- `score_query_ms`: **290.5 ms** ← the entire cost
- `bfs_ms`: **0.0 ms** (BFS visits only 57 nodes — trivial)
- `n_terms`: 8, `n_ranked`: **3282**, `graph_nodes`: 17,845

So the graph cost is `graphify.serve._score_query`, not the BFS. For an 8-term soft
query the **trigram prefilter `_trigram_candidates` bails** (a common token's rarest
trigram exceeds `guard_frac=0.10` of nodes → returns `None`) and `_score_query`
**falls back to scoring all 17,845 graph nodes** in Python (per-node `_strip_diacritics`,
`_search_tokens`, token-join, IDF/substring scoring) → 290 ms. Fast queries have
selective trigrams → 52–1,324 candidates → 1.5–34 ms. Cost scales with
(#terms × #trigram-matched nodes), worst at the full-graph fallback.

### Experiment D — does graph actually change the soft-query ranking? (leverage check)
Across 5 soft queries, inspected which of the final top-8 hits carry a `+graph`
channel tag:
- graph tags only **0–2 of the top-8**, and never the #1–2 result;
- the dominant tag is `dense` (consistent with the architecture: "graph only *tags*
  files dense already retrieved; it cannot add a file dense did not retrieve");
- for soft queries (`plike ≤ 0.35`) the graph weight in `_score` is **0.005**.

So the 290 ms graph scan has **marginal** influence on soft-query ranking — but
"marginal" ≠ "zero", so the fix must be a *bound*, not a removal, and must be
validated by top-k equality.

### Root cause (find, soft NL queries): unbounded `_score_query` full-graph fallback
The single largest, repeatable `find` cost on soft NL queries is the graph channel's
`_score_query` scoring all ~17.8k nodes when the trigram prefilter isn't selective
(~290 ms), for a channel weighted 0.005 in the soft-query ranking. **Next: implement a
bounded candidate scan + validate top-k equality before shipping.** (Instrumentation
added for this investigation is temporary and will be reverted; see cleanup.)


### Experiment E — selective-union trigram prefilter (graph fallback bound) — VALIDATED behavior-preserving, MODEST win
Implemented an env-gated (`CTX_GRAPH_SELECTIVE_UNION=1`) change in
`graphify.serve._trigram_candidates`: when some needles are selective and some are
not, score only the selective-needle candidates (union) instead of bailing to a
full-graph scan because one common needle tripped the guard. Default OFF (legacy).

A/B against a source-run engine, baseline (flag OFF) vs optimized (flag ON), 7 soft
queries, comparing retrieve_ms p50 **and** the top-12 `(path,start,end,rank)` signature:

| query | base_ms | opt_ms | top-k identical |
|---|---|---|---|
| "how the map v3 server dispatches…" | 292.3 | **230.4** | **yes** |
| "how the bridge spawns…" | 25.7 | 26.3 | yes |
| "what happens when a client disconnects…" | 35.3 | 37.7 | yes |
| "where the system decides whether to re-embed…" | 24.8 | 23.7 | yes |
| "how are results ranked and fused…" | 22.3 | 22.5 | yes |
| "where freshness decides the sync strategy…" | 26.8 | 25.2 | yes |
| "how does the keeper publish dirty files…" | 36.6 | 26.1 | yes |

**ALL top-k identical** (behavior preserved). But the win on the worst case is **modest
(292 → 230 ms, −21%)**, not the elimination I hypothesized: that query's 8 terms are
mostly *individually* non-selective, so even the selective-union still scores several
thousand nodes. For the already-fast queries it is within noise.

**Verdict:** correct and behavior-preserving on the tested battery, but a modest,
narrow win (only soft multi-common-term queries, which are a minority), touching a
core retrieval-quality function. **Ship decision deferred:** keep the flag OFF by
default and gate a wider roll-in on the engine's own retrieval **eval/quality harness**
(top-k equality on 7 queries is necessary but not sufficient for a ranking-channel
change). This is the responsible call — a 60 ms gain on a minority of queries does not
justify risking retrieval quality without the quality harness that exists for exactly
this. *Lesson: the biggest single number (290 ms) was real but had low practical
leverage (rare + risky + only partially reducible).*

### find — net conclusion
- HTTP calls per find: **exactly 1** (`/v1/search`). Keep-alive would save ~10 ms once; does not compound here.
- Dominant *common-case* cost is the per-`/v1/search` HTTP+preamble floor (~50 ms) + the engine retrieve (15–60 ms warm). The 290 ms graph outlier is real but rare and only ~21% reducible safely.
- `_grep` (callers / keyword) is the other 150–390 ms contributor **when it runs**; already prefiltered in 0.3.138.
- Shipped from this tool: the lean `/v1/search` (waste reduction, not latency). The graph prefilter is implemented but **flag-gated OFF** pending quality-harness sign-off.
- Biggest remaining universal lever = the HTTP round-trip floor shared by all `_http` calls → taken to the system-wide section (keep-alive + HTTP/1.1).


---

## TOOL 4 — `map config=focus`

Focus takes one or more symbol targets (`names=[...]`), resolves each to a definition,
and emits its body plus callers/callees and the file's top-level outline. Targets are
either **bare names** (`choose_strategy`) or **`file::symbol`** (`pkg/mod.py::choose_strategy`).

### How it works (stages, from `map_v3_server.cfg_focus`)

Per target, `_resolve_one` → `_locate_target`:
- **bare name** → `_resolve_symbol_name` runs **one `_grep`** with the def pattern
  `^\s*(?:async\s+)?(?:def|class|function|func|fn)\s+NAME\b`; if that misses it falls
  back to one `_search` (graph/dense) — the fallback did **not** fire for real symbols here.
- **`file::symbol`** → resolved from the local AST outline of that file: **no grep, no HTTP.**

Then, regardless of target kind:
- `_callers_of` runs **one `_grep`** for call sites (`\bNAME\s*\(`),
- `_callees_in`, `_top_level_symbols`, `_outline`, `_pack_bodies`, `_lines`, `_enclosing`
  are all **local Python-AST** operations — each sub-millisecond.

So the whole cost of focus is `_grep`: **2 greps per bare name** (resolve + callers),
**1 grep per `file::symbol`** (callers only). Zero HTTP in the common path.

### Where the time goes (measured, warm, in-process, `probe_focus.py`)

Baseline (0.3.138 source, warm, dense engine):

| case | total | n_grep | n_http |
|---|---|---|---|
| focus `choose_strategy` (bare) | 361 ms | 1 (resolve) + 1 (callers) | 0 |
| focus `run_ship_ladder` (bare) | 352 ms | 2 | 0 |
| focus `tool_map` (bare) | 377 ms | 2 | 0 |
| focus `file::symbol` | 191 ms | 1 (callers only) | 0 |
| focus 3 names (multi) | 1058 ms | 6 | 0 |

Each `_grep` ≈ 150 ms. The AST half of focus is free.

### Root cause — the grep "walk", not the regex (`probe_grep_internals.py`)

Splitting a single warm `_grep` into stages was the key finding. For a repo of ~4,897
code/test files, a warm grep spends its time like this:

| stage | time | share |
|---|---|---|
| **walk** (build filtered list + sort, recompute `_kind_of` per file) | **~117 ms** | **~80%** |
| prefilter (C-level `in`) | ~15 ms | ~10% |
| whole-file regex | ~5 ms | ~3% |
| text fetch (warm TTL cache) | ~4 ms | ~3% |
| per-line regex (survivors only) | ~1 ms | <1% |

The regex machinery (prefilter + whole-file + per-line = ~21 ms) was already lean. The
dominant cost was `_grep` **rebuilding the filtered+sorted file list on every call**:

```python
files = [f for f in _repo_files() if Path(f).suffix.lower() in _GREP_EXT and _kind_of(f) in want]
files.sort(key=lambda f: (order[_kind_of(f)], f))
```

`_repo_files()` is cached, but this comprehension constructs a `Path`, takes `.suffix.lower()`,
and calls `_kind_of()` (itself `_norm` + `Path(...).suffix` + several string scans) for every
file — and `_kind_of` is evaluated **twice** per file (filter predicate + sort key), ~9,800
times per grep. The resulting list is **identical every call** within a session.

### Experiment A — memoize the per-scope file list — VALIDATED, LARGE WIN

Added `_grep_scope_files(scope)`: computes the filtered+sorted list once and caches it,
keyed on `(scope, id(_repo_files()), len(_repo_files()))` so it invalidates automatically
whenever `_FILES` is rebuilt. `_grep` now calls this instead of rebuilding inline.

A/B (`probe_grep_filelist_ab.py`), N=20, scope=code:
- **Output byte-identical** — same 4,898 files, same order (`identical=True`).
- live build **p50 116 ms** → cached **~0 ms**.

End-to-end focus re-measured (`probe_focus.py`), **output char counts identical** to baseline
(1919 / 5220 / 1623 / 1919 / 12762 — behavior preserved):

| case | before | after | Δ |
|---|---|---|---|
| focus `choose_strategy` | 361 ms | **91 ms** | −75% |
| focus `run_ship_ladder` | 352 ms | **80 ms** | −77% |
| focus `tool_map` | 377 ms | **85 ms** | −77% |
| focus `file::symbol` | 191 ms | **25 ms** | −87% |
| focus 3 names (multi) | 1058 ms | **265 ms** | −75% |
| **p50** | **361 ms** | **85 ms** | **−76%** |

Per-grep cost fell from ~150 ms to ~21 ms. This change is **kept** (it is pure memoization
with no ranking/retrieval surface) and it is **shared**: find, refs/related, and graph all
grep, so every grepping tool inherits the win.

### What improved / what didn't / what remains

- **Improved:** the grep file-list walk — the dominant cost of focus and of every grep path.
- **Didn't need changing:** the regex prefilter/whole-file/per-line pipeline (already lean),
  and all AST work (sub-ms).
- **Remains (minor):** `_resolve_file` / first-touch outline parse of the resolved file shows
  ~25–45 ms on the first symbol in a file (lazy AST). It is small, amortized across a session,
  and not worth trading complexity for after the 76% win. Multi-name focus still scales linearly
  in greps (now ~2×21 ms each) — a future option is a single combined-alternation grep across
  all requested names, but the per-grep cost is now low enough that it is not a priority.


---

## TOOL 5 — `map config=related`

Related takes an **anchor** (a chunk you already have, `file::symbol` or a bare name) plus a
**query**, and returns the code elsewhere that both relates to the anchor and matches the query,
with bodies — one call instead of a grep chain from a known chunk.

### How it works (stages, from `map_v3_server.cfg_related`)

1. **Resolve the anchor** — `_locate_target(anchor)`; if it's a bare name that misses, one
   `_resolve_symbol_name` (= **one grep**). `file::symbol` resolves from the local AST (no grep).
2. **Candidate gathering** — the union of:
   - `_search(query + " " + name, top_k=20)` → **one HTTP** `/v1/search` (semantic hits), and
   - `_callers_of(name, ...)` → **one grep**, plus `_callees_in(...)` → local AST.
3. **Fold to enclosing symbols** — `_enclosing` per hit (local AST), dedup, drop the anchor itself.
4. **Rank** by accumulated score (semantic rank boost + 0.6 for caller/callee), scope-filter, top 8.
5. **Pack bodies** — `_pack_bodies` (local).

So related = **1 `/v1/search` + 1–2 greps + AST**. `file::symbol` anchor → 1 grep (callers only);
bare-name anchor → 2 greps (resolve + callers).

### Where the time goes (measured, warm, in-process, `probe_related.py`)

| case | total | n_http | n_grep |
|---|---|---|---|
| related `file::symbol` (choose_strategy) | 83 ms | 1 | 0 |
| related bare name (tool_map) | 144 ms | 1 | 1 |
| related bare name (run_ship_ladder) | 131 ms | 1 | 1 |
| **p50** | **131 ms** | | |

Component breakdown (warm):
- `/v1/search` round-trip **~55–62 ms** — the single largest component.
- `_callers_of` grep **~20–32 ms** (down from ~150 ms pre-fix — see below).
- bare-name resolve grep **~20–26 ms** when the anchor is a bare name.
- all AST (`_enclosing`×~25, `_outline`×~25, `_lines`, `_callees_in`, `_pack_bodies`) **~2–4 ms total**.

The probe confirms `_grep_scope_files` fires (n=1–2 per call, **~0 ms each**) — the Tool-4
memoization carries directly into related. Each grep related runs is now ~21 ms instead of ~150 ms,
so the Tool-4 fix removed **~116–232 ms per related call** (1–2 greps) with no behavior change.

### Experiment — does `/v1/search` cost scale with `top_k`? (`probe_search_topk.py`)

Related uses `top_k=20` vs find's smaller top_k, so I checked whether that is a related-specific
cost. It is **not**: engine `total_ms` p50 is flat across top_k 5 → 40 (28 / 32 / 25 / 24 ms) and
wall p50 is flat (~74–84 ms). The only variance is the same graph-channel `retrieve_ms` tail already
root-caused for find (p95 spikes to 280–390 ms), which is independent of top_k. Lowering related's
top_k would not help latency and would only shrink the candidate pool (a quality regression).

### What improved / what didn't / what remains

- **Improved (inherited):** both greps related runs dropped ~150 ms → ~21 ms via the Tool-4
  `_grep_scope_files` memoization. This is the bulk of related's prior cost.
- **No related-specific bottleneck:** after the shared grep fix, related's cost is the shared
  `/v1/search` floor (~55 ms) + cheap greps + negligible AST. `top_k=20` is not a cost driver.
- **Remains (shared, not related-specific):** the ~50 ms per-`/v1/search` HTTP+preamble floor —
  the universal keep-alive / HTTP-1.1 lever, carried to the SYSTEM-WIDE section — and the graph
  `retrieve_ms` tail (find Experiment E, flag-gated). No new behavior-preserving related-only win
  was found or needed.


---

## TOOL 6 — `map config=graph`

Graph returns an abstract JSON neighborhood for orientation: seed files → their top-level
symbol names, plus cross-file (and same-file) call edges. No bodies — one wide, cheap map.

### How it works (stages, from `map_v3_server.cfg_graph`)

1. **Seed files** — optional `_locate_target(anchor)` for the anchor's file, then
   `_search(query or anchor, top_k=18)` → **one HTTP** `/v1/search`; keep the first ≤6 `.py`
   code files.
2. **Nodes** — for each seed file, `_top_level_symbols(rel)` (cached AST outline) → up to 20 names.
3. **Edges** — build a `name → file` map, then for each symbol re-fetch its outline entry
   (`next(x for x in _top_level_symbols(rel) ...)`), take its body via `_code_text`, and regex
   `finditer` for `name(` calls that resolve to a top-level symbol of another seed file.
4. **Serialize** JSON; if over budget, drop edges first, then trim symbol lists.

So graph = **1 `/v1/search` + pure local AST/regex. Zero greps.**

### Where the time goes (measured, warm, in-process, `probe_graph.py`)

| case | total | n_http | n_grep | `/v1/search` | all AST |
|---|---|---|---|---|---|
| graph query "freshness decision" | 66 ms | 1 | 0 | 63 ms | ~1.4 ms |
| graph query "map dispatch" | 253 ms | 1 | 0 | 240 ms | ~6 ms |
| graph anchor `file::symbol` + query | 694 ms | 1 | 0 | 682 ms | ~6 ms |

Graph is **entirely the `/v1/search` round-trip** (95–98% of wall). All of graph's own work —
`_top_level_symbols` (up to 49 calls including the per-symbol edge-loop re-fetches), `_lines`,
`_code_text`, and the edge regex — totals **~3–6 ms**, because `_outline`/`_top_level_symbols` are
mtime-cached so the repeated calls are cache hits.

The 66 → 694 ms spread is **not graph-specific**: it is the same engine graph-channel `retrieve_ms`
tail root-caused for find (soft, multi-common-term queries drive `graphify.serve._score_query` to
score the whole graph). `top_k=18` does not drive it (see related Experiment — `/v1/search` cost is
top_k-independent).

### What improved / what didn't / what remains

- **Improved (inherited):** nothing to grep here, so the Tool-4 grep fix doesn't apply; but graph's
  own AST stays sub-6 ms thanks to the existing outline cache.
- **Considered, rejected (negligible):** the edge loop does a per-symbol `next(... _top_level_symbols(rel) ...)`
  linear scan (O(S²) over a cached list per file). Measured ~3 ms for ~49 symbols — not worth a
  dict-index rewrite against the (small) regression risk. If seed symbol counts ever grow a lot, index
  `{symbol: outline_entry}` once per file.
- **Remains (shared, not graph-specific):** the entire graph latency is the `/v1/search` floor + the
  graph-channel `retrieve_ms` tail. Both are shared levers: the keep-alive / HTTP-1.1 floor (SYSTEM-WIDE)
  and the flag-gated selective-union prefilter (find Experiment E, pending quality harness). No
  graph-only behavior-preserving win exists — graph's own code is already minimal.


---

## TOOL 7 — STARTUP / WARMUP (one-time costs, separate from request latency)

Three distinct one-time costs sit in front of steady-state latency: the **worker** process
(spawn + import + first-call tax), the **engine** cold boot (soft-ready then dense), and the
**bridge** first-call spawn. The worker side is where the actionable wins were.

### Measured worker startup (`probe_startup.py`, `probe_startup_wait.py`, engine kept warm)

| phase | measured | what it is |
|---|---|---|
| spawn + import + `initialize` | ~146 ms | Python start + importing `map_v3_server`/`_helpers` (stdlib + HTTP only, no `pipeline.*` heavy deps) |
| **first tool call (baseline)** | **~424 ms** | the cold-worker tax — investigated below |
| steady tool call | ~44 ms | matches the warm find numbers (Tool 3) |
| `_repo_files()` walk (in-proc) | ~291 ms → see fix | one os.walk of the repo (~8k files) |
| `_warm()` full (in-proc) | ~1.5 s | reads+caches ~8k files' text/lines (background thread) |

### Root-cause 1 — the first-call tax is **urllib's first-request init**, not cold caches

Waiting ~2.5 s for the background warm thread did **not** reduce the first-call tax
(`probe_startup_wait.py`: waited 430 ms vs no-wait 450 ms), ruling out cold local file caches.
Splitting a fresh worker's first calls (`probe_firstcall.py`) pinned it exactly:

- first `_http` of the process: **~393 ms**; every `_http` after: **~40 ms**.

So the whole tax is the **first HTTP request** a worker ever makes. `probe_proxy_ab.py` /
`probe_prewarm_thread.py` isolated it further: it is urllib's one-time opener/first-socket
initialization (on Windows the default opener's proxy path also reads WinINET registry settings),
and it is **process-global** — paying it once on any thread makes every later call ~4 ms
(`bg_first_http=354 ms` → `main_after_bg=3.9 ms`).

### Root-cause 2 — the real server never warmed

`map_v3_server.main()` (the module the worker actually runs) started its stdin loop with **no
warm thread** — the warm thread only existed in the unused `map_v3_helpers.main()`. So in
production the user's first `map` call paid both the ~393 ms urllib init **and** the cold file
reads.

### Fixes (KEPT, source, behavior-preserving)

1. **`_repo_files()` → `os.scandir` recursion** instead of `os.walk` + `os.path.relpath`/`join`
   per file. Output **byte-identical** (same `_norm`, same sort — `probe_repowalk_ab.py` asserts
   `identical=True` for 8,014 files). Walk **291 ms → 132 ms (−55%)**. The dirent type comes
   from the directory entry (no extra stat) and the relative path is a slice of the known
   absolute path. (A subtle correctness note: current `_norm` does `lstrip("./")`, which strips
   leading dots from dotfiles/dotdirs — the fast walk reproduces this exactly rather than
   "fixing" it, so no path set changes.)
2. **No-proxy opener**, built lazily: `_opener()` returns `build_opener(ProxyHandler({}))` — the
   engine is always loopback so proxies are never wanted, and this skips the WinINET registry
   read. Built on first use, not at import, so the one-time urllib cost stays off the spawn /
   `initialize` critical path.
3. **Background warm thread in the real server**: `map_v3_server.main()` now starts
   `mv2._warm` as a daemon thread, and `_warm` **pre-pays the urllib init with a throwaway
   `/health`** as its first action (before the ~1.5 s file-read loop).

### Validated end-to-end (`probe_startup_wait.py`, real `map_v3_server` worker)

| | before | after |
|---|---|---|
| first call, warm thread finished first (realistic IDE gap) | ~430 ms | **~59 ms** (−86%) |
| steady call | ~44 ms | ~41 ms |
| spawn + init | ~146 ms | ~146 ms (unchanged — cost no longer moved onto this path) |

The only case still ~500 ms is a first call arriving in the *same millisecond* as spawn (the
probe's zero-gap worst case); real usage has a handshake/human gap that lets the warm thread win.

### Engine cold boot (the other half, measured from `/health`)

The engine reaches `warm_state=ready` / `soft_search_ready` quickly (BM25/soft index), but
`dense_ready` requires the DirectML embedder to load — ~2.5 s after a fresh start (observed:
first `/health` shows `embedder_loaded=false`; a nudge search then flips `dense_ready=true` in
~3 s). This is model-load bound and lives in the engine process, shared by all tools; it is not
worker-side and not addressed here. First-ever embed of a *new* query string also pays a one-time
~115–245 ms (Tool 3), separate from the daemon warm.

### What remains

- Worker first-call tax and repo walk: **addressed.** 
- Engine dense-embedder load (~2.5 s) and bridge worker-spawn first-call (~392 ms, process spawn):
  one-time, process-model costs covered in the SYSTEM-WIDE section.


---

## SYSTEM-WIDE ANALYSIS (shared inefficiencies & cross-cutting levers)

Investigating the tools one at a time surfaced that **the per-tool code is mostly already lean** —
AST/body assembly is sub-10 ms everywhere, and the real costs are a small number of **shared**
mechanisms. This section consolidates them and records the final decisions.

### The cost model, in one place

Every `map` call decomposes into at most three shared primitives:

1. **`_grep`** — whole-repo line grep (focus: 1–2; find: 0–2; related: 1–2; graph: 0).
2. **`/v1/search`** — exactly one engine HTTP round-trip (find/related/graph: 1; focus: 0).
3. **local AST** — outline/enclosing/body packing (all tools), mtime-cached, **always <10 ms**.

So optimizing the three primitives optimizes all five tools at once. That is exactly what the
investigation did.

### Lever 1 — grep file-list walk (SHARED, FIXED, biggest win)

`_grep` rebuilt a filtered+sorted ~5k-file list (recomputing `_kind_of` ~9,800×) on **every call** —
~117 ms of a ~145 ms warm grep. Memoized via `_grep_scope_files` (Tool 4), keyed on the
`_repo_files()` identity, byte-identical output. **Per-grep 150 ms → 21 ms.** Because focus,
find, and related all grep, this one change is the dominant cross-tool win:

| tool | before | after (all kept changes) |
|---|---|---|
| focus bare name | 361 ms | **94 ms** |
| focus file::symbol | 191 ms | **26 ms** |
| find (keyword, greps) | ~360 ms | **64 ms** |
| related file::symbol | ~250 ms | **72 ms** |

### Lever 2 — worker startup / first-call tax (SHARED, FIXED)

The real worker (`map_v3_server`) never warmed, and every worker's **first** HTTP request paid
urllib's ~393 ms one-time init (opener build + first socket op + Windows proxy-registry read).
Fixed with: scandir repo walk (291 → 132 ms), a no-proxy lazily-built opener, and a background
warm thread in `map_v3_server.main()` that pre-pays the urllib init with a throwaway `/health`.
**First real call 430 ms → ~59 ms** (realistic IDE gap). All behavior-preserving.

### Lever 3 — the `/v1/search` HTTP floor + HTTP/1.0 (SHARED, documented, NOT shipped)

After Levers 1–2, the largest remaining component of find/related/graph is the single
`/v1/search` round-trip (~50 ms: ~15 ms TCP connect + body/preamble + ~16 ms warm engine work).
The engine's `Handler` (`packages/pipeline/server.py`) subclasses `BaseHTTPRequestHandler` with
no `protocol_version` override, so it speaks **HTTP/1.0** — the connection closes per request.
Tool 1/2 proved a persistent connection cuts a round-trip ~15 ms → ~4.6 ms.

**Decision: not shipped.** Each `map` tool makes only **one** `/v1/search`, so there is nothing to
reuse within a call; the benefit would only appear across consecutive calls and only if the worker
also pooled connections (urllib does not). Capturing ~10 ms requires both an engine change to
HTTP/1.1 — which on a stdlib `ThreadingHTTPServer` demands a correct `Content-Length` on every
response or the client hangs, a real correctness hazard — and a new pooling HTTP client in the
worker. The risk/reward is poor next to the banked wins. Kept as a documented future lever.

### Lever 4 — graph-channel `retrieve_ms` tail (SHARED, flag-gated OFF)

The one case that is still slow after all fixes is a **soft, multi-common-term** `/v1/search`
(e.g. graph query "map config dispatch handler" → p50 290 ms). Root-caused in find Experiment C/E:
`graphify.serve._score_query` scores the whole ~17.8k-node graph when the trigram prefilter bails.
The selective-union prefilter (Experiment E) cuts the slow case ~21 % with identical top-k, but it
touches a core retrieval-ranking channel, so it stays behind `CTX_GRAPH_SELECTIVE_UNION` (OFF)
pending the engine's retrieval **quality** harness — top-k equality on 7 queries is necessary, not
sufficient, to sign off a ranking change.

### Lever 5 — process model (one-time, not changed)

- **Bridge worker spawn**: first call through the bridge ~392 ms (process spawn), then ~6–14 ms —
  one-time per worker lifetime, already hidden by the bridge's warm-worker reuse.
- **Engine dense embedder**: ~2.5 s DirectML model load, once per engine boot, engine-side and
  shared by every client. Not worker-side; out of scope for the tools.

Both are one-time and architectural; neither is on the steady-state path.

### Caches already in place (confirmed healthy)

The per-file **stat-TTL** (`_text_cached_fast` / `_TEXT_VALIDATED_AT`) and the mtime-keyed
`_OUTLINE` / `_LINES` / `_TEXT` caches were verified working — repeated outline/line/text reads are
cache hits (graph's ~49 `_top_level_symbols` calls cost ~3 ms total). The new `_grep_scope_files`
memoization and scandir walk slot in alongside them without new invalidation surface (both key on
the existing `_repo_files()` lifecycle).

### Final cumulative warm latency (all kept changes active, `probe_cumulative.py`)

| config | p50 | note |
|---|---|---|
| find (nl query) | **43 ms** | 1 `/v1/search`, no grep |
| find (keyword) | **64 ms** | 1 search + cheap greps |
| focus bare name | **94 ms** | 2 memoized greps |
| focus file::symbol | **26 ms** | 1 memoized grep, local resolve |
| related file::symbol | **72 ms** | 1 search + 1 grep |
| graph query | **290 ms** | all `/v1/search`; soft-query graph tail (Lever 4, flag-gated) |

### Shipping decision

**Ship (behavior-preserving, no quality surface):** `_grep_scope_files` memoization, scandir
`_repo_files`, no-proxy opener, server warm thread, lean `/v1/search`. These are pure
efficiency/startup changes validated byte- or behavior-identical against the current impl.

**Hold:** the `CTX_GRAPH_SELECTIVE_UNION` selective-union prefilter stays flag-OFF until the
retrieval-quality harness signs off, since it is the only change that can alter ranking.


---

## IDLE KEEPALIVE — keeping `map` fast after a break (0.3.140)

The 0.3.139 work made the engine + GPU embedder stay resident for 80 min
(`CTX_ENGINE_IDLE_S` / `CTX_EMBED_IDLE_DEMOTE_S = 4800`), which removed the ~20 s dense
re-warm after an idle gap. But a second, smaller after-idle cost remained in the **worker
process**, surfaced by a no-warm-gap test: the first `focus` after a few minutes idle took
~550 ms instead of its ~90 ms warm steady.

### Root cause (measured, `probe_focus_after_idle_stages.py`)

`focus` resolves a bare name with a whole-repo grep. That grep's fast path depends on the
stat-TTL (`_GREP_STAT_TTL_S = 10 s`) that lets `_text_cached_fast` skip a per-file `stat()`.
After more than 10 s idle the TTL has expired, so the first post-idle grep re-validates every
file: profiling showed `_grep` 377 ms, of which `_text` → `_mtime` `stat()` over **4,916 files
= 331 ms** — a classic stat storm. (The engine stays dense, so this is purely worker-side; it
is the ~550 ms, not the old ~20 s.)

### Research basis

The fix follows the established keep-warm pattern — a scheduled pinger that exercises the
runtime during idle plus preloaded/warmed state — documented for MCP servers
([MCP cold-start optimization](https://about.fast.io/resources/mcp-server-cold-start-optimization/))
and serverless workloads generally
([warm pools / pingers](https://tech-champion.com/cloud-computing/control-serverless-cold-starts-with-warm-pools-and-design/)).
The interval choice follows the keepalive-economics result that pulse cost falls with the
interval, so the economical choice is the largest interval that still stays under the system's
decay/eviction window ([arXiv 2607.19214](https://arxiv.org/abs/2607.19214)) — here, comfortably
under the stat-TTL window. *(Sources rephrased for license compliance.)*

### Design (behavior-preserving)

A daemon keepalive thread in `map_v3_server.main()`, gated by `CTX_MAP_WARM_INTERVAL_S`
(default 120 s; `0` disables):

- `_keepalive_tick()` — re-stamps `_TEXT_VALIDATED_AT` for every already-cached file (pure dict
  writes, ~1 ms, **no disk I/O**) and pings `/health` to keep the HTTP opener/socket warm.
- `_keepalive_loop(interval)` — raises the effective stat-TTL to
  `_STAT_TTL_EFFECTIVE_S = max(10, interval × 1.5)` and stamps once immediately, then pulses on
  the interval, skipping a pulse if a real call ran within the last interval (`_LAST_CALL_AT`,
  set per `tools/call`). With the 120 s default → 180 s effective TTL, pulses 120 s apart, so the
  validated window never has a gap. Each pulse physically re-stamps the whole set, so a file is
  only ever trusted for one interval between real re-stats — edits still self-correct.
- `_text_cached_fast` now checks `_STAT_TTL_EFFECTIVE_S` instead of the fixed 10 s.

### Result (`probe_keepalive_focus.py`, source worker, 70 s idle, focus ×3)

| arm | focus first-after-idle | warm steady (2nd/3rd) |
|---|---|---|
| control (keepalive off) | 555 ms | 91 ms |
| **keepalive (120 s)** | **230 ms (−58%)** | 91 ms |

Warm steady-state and all tool output are **byte-identical** between arms (focus 1919 c in both)
— pure speed, no behavior change. The residual ~140 ms over warm is a stat path not fully
covered by `_text_cached_fast`; closing it needs deeper changes to the grep's mtime handling with
diminishing returns, so it is left as future work. `gate`/`status` stay ~4 ms and
`find`/`related`/`graph` were already fast (and marginally improved).

### Net

Combined with the 0.3.139 residency change, a call after a normal editor break now pays neither
the ~20 s dense re-warm nor the full ~550 ms stat storm — `focus` lands ~230 ms, the rest in their
usual sub-250 ms band, with identical results.

# Scubiee — System Overview

_Version 0.3.146 · Local AI code-context engine + MCP server · Windows (DirectML GPU), macOS (MLX/Metal), CPU fallback_

This document explains what Scubiee is, how it is put together, and every feature/surface it exposes. It is written as a reference for anyone testing, extending, or operating the system.

---

## 1. What Scubiee is

Scubiee is a **local-first code-context engine**. It indexes a repository and answers "where is the code that matters for this task?" questions for an AI coding agent (Kiro, Cursor, Claude Code, etc.). It runs entirely on the developer's machine — no code leaves the box — and exposes its capabilities three ways:

1. **MCP server** — the primary surface. An agent calls **one tool, `map`, with two configs**: `find` (don't know where the code is → ranked locations with code inline) and `focus` (know the symbol name → its body + callers/callees + siblings). Plus `gate`/`status` for health.
2. **HTTP API** — a local engine on `127.0.0.1:8765` that does the actual retrieval, graph, and grep work. The MCP bridge and CLI are clients of it.
3. **CLI** — `scubiee <command>` for install, indexing, lifecycle, diagnostics, and direct locate calls.

The core idea: instead of an agent blindly grepping or reading whole files, Scubiee ranks the repository by relevance to an enriched query, returns a compact **heatmap** of hot symbols with their locations, and lets the agent pull just the bodies it needs. This keeps the agent's context window small and on-target.

---

## 2. Package layout

The repo is a monorepo under `packages/`:

| Package | Role |
|---|---|
| `pipeline` | The product: MCP server, HTTP server, CLI, engine lifecycle, indexing orchestration, embedder, ignore rules, freshness. |
| `conductor` | Retrieval fusion — combines graph, BM25, and dense (vector) channels into a single ranked result. |
| `graphify` | The code graph — symbols, edges (calls/imports/defines), MinHash near-dup detection, id normalization. |
| `trace_lab` | AST tracer and heatmap — builds the composite edge bundle and produces the hot-symbol cards that `map find`/`focus` return. |

Key entrypoints:
- `packages/pipeline/__main__.py` — CLI dispatch (the `cli.py` is a thin shim into this).
- `packages/pipeline/map_v3_server.py` — the shipped MCP `map` tool (`find`/`focus`) + `gate`/`status`. (The retired eight-tool ladder in `mcp_locate.py` is archived under `archive/old-mcp-map/`.)
- `packages/pipeline/server.py` — the HTTP engine.
- `packages/pipeline/ce_service.py` — engine service object (warm-up, embedder, session state).
- `packages/pipeline/incremental.py` — the two-lane sync (hot BM25 + graph catch-up).
- `packages/conductor/architectures.py` — the retrieval fusion / ranking.

---

## 3. Processes and lifecycle

Scubiee runs as a set of cooperating local processes:

- **Engine** — the long-lived HTTP server on `:8765`. Holds the index, embedder, graph, and session state in memory. This is where all real work happens.
- **Watchdog / supervisor** — keeps the engine alive, auto-starts it on demand, and pre-warms the embedder in the background so the first real query is fast.
- **Keeper** — the background sync worker that watches the repo for changes and keeps the index fresh across the two lanes.
- **MCP bridge** — the per-agent process that exposes the MCP tools (`map` with `find`/`focus`, plus `gate`/`status`) and forwards to the engine over HTTP.

### Warm-up phases (Windows/DirectML cold start, v0.3.146)
1. **Cold** — engine process not up. Watchdog/autostart brings it up.
2. **Soft-ready** (~9s) — BM25 + graph loaded; `map find`/`focus` usable. `soft_search_ready: true`.
3. **Dense-ready** (~14s) — embedder ONNX/DirectML session built; full hybrid ranking available. `embedder_loaded: true`, `dense_ready: true`, `warm_phase: dense`.

The ORT/DirectML session build itself is only ~2.5s; the rest of the cold-start
time is the engine load + the first query-embed warmup. v0.3.146 kicks the dense
prewarm immediately after soft-ready (before the keeper/reconcile/AST work) and
**gates the ~20s AST-bundle revalidation on `embedder_loaded`**
(`CTX_AST_REVALIDATE_GATE_ON_EMBED`, default on) so it can't starve the embedder
during the cold window — this cut dense-behind-soft from ~15s to ~2–9s. The
watchdog also pre-warms in the background so an agent arriving after the machine
has settled sees a warm engine immediately. (macOS/MLX warm timing is verified
separately — see `scubiee-macos-handoff-0.3.145.md`.)

### Idle / standby
The engine stays warm (embedder resident) for the whole time a client is
connected; the disconnect timers (`CTX_ENGINE_IDLE_S` / `CTX_DISCONNECT_DEBOUNCE_S`,
install default ~120s) only fire after the **last** client disconnects, then it
stops and unloads. It can also defer heavy graph catch-up while clients are
actively connected (`CTX_KEEPER_DEFER_WHILE_CLIENTS=1`).

---

## 4. Retrieval architecture

Retrieval is a **three-channel hybrid fusion** in `conductor/architectures.py`:

- **Graph channel** — walks the code graph (calls/imports/defines) from seed symbols; captures structural relevance.
- **BM25 channel** — lexical/keyword match over chunk text; captures literal tokens, identifiers, error strings.
- **Dense channel** — CodeRankEmbed 768-dim vectors (FastEmbed + ONNX Runtime, DirectML on Windows / MLX on macOS), stored in FAISS with TurboQuant int8 quantization; captures semantic similarity.

`_channel_maps` runs the three channels in parallel, then fuses:
- **RRF hybrid** merge across channels.
- **best_chunk** score = `g_aff + b_all + 40*d_all` (graph affinity + BM25 + heavily-weighted dense).
- **D-rerank** = `exact + 0.8*path_overlap + 0.15*bm25 + 8*dense + 0.02*graph`.

The AST/heatmap layer (`trace_lab`) turns ranked chunks into **cards**: `file::symbol` nodes with a location span (`loc`), a score, and neighbor edges. The composite edge bundle (`composite_edges_v1.pkl`) and repo trace (`trace_repo_v3.pkl`) live in `<repo>/.scubiee/cache/`.

---

## 5. Storage and freshness

- **Cache** — `<repo>/.scubiee/cache/`: FAISS index, trace bundle, composite edges, BM25 store.
- **Identity** — `.scubiee/id.json` carries the enrolled `project_id` (`ce_…`). This is what marks a repo as "managed."
- **Merkle freshness** — `merkle.py` tracks per-file hashes so the keeper only re-indexes what changed.

### Two sync lanes (`incremental.py`)
1. **Hot lane** — append-only BM25 delta (`HotDelta`, `hot_lane=True`). Sub-second; keeps `search`/`map` fresh almost immediately after an edit.
2. **Graph catch-up lane** — rebuilds AST/graph edges. Each catch-up rewrites the
   whole `graph.json` (fixed ~2–4s cost regardless of how many files changed), so
   v0.3.146 **batches a catch-up-only drain into one rebuild** instead of one per
   file (`CTX_GRAPH_CATCHUP_MAX_FILES`, default 2000) — bulk churn no longer keeps
   `index_fresh` false for minutes. The lane is still deferred while clients are
   connected. This is why `map focus` wiring (graph-dependent) can lag the hot
   lane by a few seconds after a large structural change; `find`/`focus` text
   stays fresh on the hot lane.

### Ignore rules (`ignore.py`)
- `BUILTIN_IGNORE_DIRS` (node_modules, .git, venvs, build output, etc.).
- `.scubieeignore` in the repo — additional excludes (testdata, research, sandbox, experiments, references, design_benchmarks, fixtures).

---

## 6. MCP tools (the primary surface)

**One tool — `map` — with two configs** (`find` | `focus`), plus `gate`/`status` for health,
registered in `packages/pipeline/map_v3_server.py` (`CONFIGS = ("find", "focus")`). A managed-repo
gate fences locate to enrolled repos. (The older eight-tool pack/expand/collect/workspace ladder in
`mcp_locate.py` is retired — archived under `archive/old-mcp-map/`.)

| Tool | Config | Purpose | Key params |
|---|---|---|---|
| `gate` | — | ~5-token session gate; confirms managed status. | `project_id`, `root`, `session_id` |
| `status` | — | Health / warm state / session. | `detail` = `summary` \| `full` \| `gate` |
| `map` | `find` | Don't know where code is → ranked locations **with code inline**; also orients a wide area / pulls code near a chunk you hold. | `query`, `k` (default 12) |
| `map` | `focus` | Know the symbol name(s) → full body **+ callers/callees + siblings** in one unit. | `names` (or `anchor`), `budget_chars` |

Internally `find` runs the three-channel fusion + heatmap and inlines the top result's enclosing
symbol; `focus` resolves the named symbol(s) and attaches wiring. Ranking is fixed on
`composite_v1`. Literal/regex search, filename listing, and known-path reads stay with the agent's
**native Grep/Glob/Read** — not Scubiee tools.

The flow: `status` → `map find` (don't know where) **or** `map focus` (know the name) → edit with
native tools → `scubiee sync` if needed. Act on the first good answer and stop.

---

## 7. HTTP API (`server.py`, `127.0.0.1:8765`)

**GET**: `/health`, `/` (=health), `/dashboard`, `/api/settings`, `/v1/settings`, `/status`, `/v1/status`, `/v1/resources`.

**POST**:
- Lifecycle/session: `/v1/open`, `/v1/register`, `/v1/client/{register,unregister,reconcile,touch}`, `/v1/lifecycle`, `/v1/session/end`, `/v1/dirty`, `/v1/note_locate`.
- Retrieval: `/v1/search` (+ `/search`), `/v1/locate`, `/v1/publish`, `/v1/grep`, `/v1/outline`, `/v1/read_span`, `/v1/follow_imports`, `/v1/graph_neighbors`, `/v1/query_graph`, `/v1/grep_ident`, `/v1/reopen_anchors`, `/v1/session_anchors`.
- Control: `/v1/shutdown` (+ `/shutdown`), `/reload`.

Unknown routes return 404.

---

## 8. CLI (`__main__.py`)

Subcommands (dispatched from `packages/pipeline/__main__.py`):

- **Indexing / data**: `index`, `resources`, `rebuild`, `remove`, `never-index`, `list`, `sync`, `sync-now`.
- **Lifecycle**: `register`, `initialize`, `activate`, `pause`, `resume`, `connect`, `disconnect`.
- **Engine**: `engine start|stop|status|run|ensure|watchdog|supervisor|autostart`, `serve`, `stop`, `halt`, `dashboard`.
- **Locate (direct)**: `search`, `status`, `gate`, `map` (`--config find|focus`). (The old `pack`/`expand` subcommands were retired with the pack ladder.)
- **Diagnostics / health**: `test`, `preflight`, `doctor`, `certify`, `diagnose`, `heal`, `unlock-tool`, `migrate`, `upgrade`.
- **Setup / MCP wiring**: `mcp`, `init`, `setup`, `wipe`.
- **Settings**: `settings`.

Installed entrypoint (uv tool): `%APPDATA%\uv\tools\scubiee\Scripts\scubiee.exe`.

---

## 9. Configuration / environment

Notable env vars:
- `CTX_ENGINE_URL` — points a client at the engine; required for cross-process search.
- `CTX_GRAPH_CATCHUP_DELAY_S` (30) — delay before the graph lane catches up after edits.
- `CTX_KEEPER_DEFER_WHILE_CLIENTS` (1) — defer graph catch-up while agents are connected.
- `CTX_GRAPH_CATCHUP_MAX_FILES` (2000) — widen a catch-up-only drain so bulk churn merges in one whole-graph rebuild.
- `CTX_EAGER_PREWARM` (1) + `CTX_AST_REVALIDATE_GATE_ON_EMBED` (1) — the cold-start fix: prewarm dense early and keep the AST rebake from starving it.
- `CTX_HEALTH_REFRESHER` (1) — background thread keeps `/health` off the request-path disk I/O so it never stalls under embed load.
- `CTX_ORT_SELF_HEAL` (1) — detect-only; the engine warns (never pip-mutates its own env) when the GPU provider is missing and points at `scubiee setup --repair`.
- `PYTHONPATH` — `packages` for in-repo runs; unset for installed-tool runs.

Token mode (`token_mode: savings`) governs how aggressively the engine trims returned context.

---

## 10. How the pieces fit (request walkthrough)

1. Agent calls `gate`/`status` → confirms the repo is managed and the engine is warm.
2. Agent calls `map config=find` with an intent query → engine runs the three-channel fusion, returns ranked locations and inlines the top result's enclosing symbol. (If the agent already knows the symbol name, it calls `map config=focus names=[...]` instead → the symbol's body + callers/callees + siblings in one unit.)
3. Agent edits from the returned code with native tools; a known literal/path uses native Grep/Read directly.
4. Edits land → hot BM25 lane refreshes `find`/`focus` within ~1s; graph lane catches up within ~30s (or after clients disconnect) so wiring in `focus` reflects structural changes.

---

_This overview is the map for the testing phase: every tool, endpoint, and subcommand listed here is exercised and its behavior/bugs recorded in the QA findings doc._

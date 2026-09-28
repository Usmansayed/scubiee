# Scubiee — System Overview

_Version 0.3.132 · Local AI code-context engine + MCP server · Windows (DirectML GPU), macOS (MLX/Metal), CPU fallback_

This document explains what Scubiee is, how it is put together, and every feature/surface it exposes. It is written as a reference for anyone testing, extending, or operating the system.

---

## 1. What Scubiee is

Scubiee is a **local-first code-context engine**. It indexes a repository and answers "where is the code that matters for this task?" questions for an AI coding agent (Kiro, Cursor, Claude Code, etc.). It runs entirely on the developer's machine — no code leaves the box — and exposes its capabilities three ways:

1. **MCP server** — the primary surface. An agent calls a small ladder of tools (`map` → `pack_context` → `expand_context` / `collect_hot_context`) to locate and materialize the hot code for a task.
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
| `trace_lab` | AST tracer and heatmap — builds the composite edge bundle and produces the hot-symbol cards that `map`/`pack` return. |

Key entrypoints:
- `packages/pipeline/__main__.py` — CLI dispatch (the `cli.py` is a thin shim into this).
- `packages/pipeline/mcp_locate.py` — MCP tool registration and implementations.
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
- **MCP bridge** — the per-agent process that exposes the 8 MCP tools and forwards to the engine over HTTP.

### Warm-up phases
1. **Cold** — engine process not up. Watchdog/autostart brings it up.
2. **Soft-ready** (~4s) — BM25 + graph loaded; `map`/`search` usable. `soft_search_ready: true`.
3. **Dense-ready** (~11s) — embedder ONNX/DirectML session built; full hybrid ranking available. `embedder_loaded: true`, `warm_phase: ready`.

The DirectML ORT session build is the irreducible floor of dense warm-up. The watchdog pre-warms it in the background so an agent that arrives after the machine has settled sees a warm engine immediately.

### Idle / standby
The engine can defer heavy graph catch-up while clients are actively connected (`CTX_KEEPER_DEFER_WHILE_CLIENTS=1`) and settles into a low-cost standby when idle.

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
2. **Graph catch-up lane** — rebuilds AST/graph edges. Deferred (`CTX_GRAPH_CATCHUP_DELAY_S=30`, deferred further while clients connected). This is why `pack`/`expand` (graph-dependent) can lag the hot lane by a few seconds after a large structural change.

### Ignore rules (`ignore.py`)
- `BUILTIN_IGNORE_DIRS` (node_modules, .git, venvs, build output, etc.).
- `.scubieeignore` in the repo — additional excludes (testdata, research, sandbox, experiments, references, design_benchmarks, fixtures).

---

## 6. MCP tools (the primary surface)

Eight tools, registered in `mcp_locate.py` via an inner `_tool(name, desc, fn)`; errors are wrapped by `_err()`. A managed-repo gate (`_is_repo_managed` → `_managed_locate_err`) fences locate tools to enrolled repos.

| Tool | Purpose | Key params |
|---|---|---|
| `gate` | ~5-token session gate; confirms managed status and whether to use MCP. | `project_id`, `root`, `session_id` |
| `status` | Health / warm state / session. | `detail` = `summary` \| `full` \| `gate` |
| `map` | Call 1 of the ladder. Ranked heatmap cards + `suggested_seeds`. No bodies. | `query` (dense code-vocab), `k` (default 12) |
| `pack_context` | Call 2. Composite trace from seeds → heatmap (+ optional bodies). | `query`, `seed_file`/`seed_symbol`/`seed_line`, `seed2_*`, `seed3_*`, `include_bodies`, `mode`, `policy`, `k` (16), `hot_threshold` (0.65), `budget_chars`, `max_bodies` |
| `expand_context` | Call 3. Delta cards around a node. | `node`/`seed_*`, `direction` = `callees`\|`callers`\|`effects`\|`config`\|`broad`\|`all`, `with_bodies`, `k` (10) |
| `collect_hot_context` | Fetch code bodies for hot nodes / explicit ids. | `ids`, `threshold`, `max_chars` (8000) |
| `workspace` | Mid-session brain: show pins/heatmap; pin a file; clear for new topic. | `action` = `show`\|`pin`\|`clear`, `path` (for pin), `root` |
| `expand` | Re-materialize a stored span by handle. | `handle`, `max_chars` |

Ranking is fixed on `composite_v1`; `mode` (lean/full) and `policy` (strict/broad) are accepted for compatibility but do not change ranking.

The intended flow: `map` (locate) → `pack_context` (materialize hot ground from a seed) → `expand_context` (grow along calls/callers/effects) or `collect_hot_context` (pull bodies). Native reads are used on the `loc` spans the heatmap points to.

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
- **Locate (direct)**: `search`, `status`, `gate`, `map`, `pack`, `expand`.
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
- `CTX_MCP_PACK_BODIES` — default for whether `pack_context` collects bodies.
- `PYTHONPATH` — `packages` for in-repo runs; unset for installed-tool runs.

Token mode (`token_mode: savings`) governs how aggressively the engine trims returned context.

---

## 10. How the pieces fit (request walkthrough)

1. Agent calls `gate`/`status` → confirms the repo is managed and the engine is warm.
2. Agent calls `map` with an enriched query → engine runs the three-channel fusion, returns ranked cards + `suggested_seeds`.
3. Agent calls `pack_context` with a seed → `trace_lab` builds the composite trace, returns a heatmap with `loc` spans (and bodies if requested).
4. Agent reads the `loc` spans natively, and/or calls `expand_context` to grow along the graph, or `collect_hot_context` to pull bodies.
5. Edits land → hot BM25 lane refreshes `search`/`map` within ~1s; graph lane catches up within ~30s (or after clients disconnect) so `pack`/`expand` reflect structural changes.

---

_This overview is the map for the testing phase: every tool, endpoint, and subcommand listed here is exercised and its behavior/bugs recorded in the QA findings doc._

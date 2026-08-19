# Tech summary — how we do things

As of **scubiee 0.2.18** (PyPI latest **0.2.17**). This replaces `docs/engineering/` (deleted).

## System picture

```text
Cursor / CLI / dashboard
        │ stdio MCP          HTTP
        ▼                    ▼
mcp_locate.py  ────────►  server.py  :8765
                              │
                    RuntimeManager (ce_service)
                         │              │
               IndexManager        WarmSearchEngine
               merkle/index/sync   embed + FAISS + BM25 + graph
```

Three long-lived pieces when fully running:

1. **Engine daemon** — HTTP + warm engine. Lock: `~/.context-engine/engine.lock`.
2. **Watchdog sidecar** — polls `/health`, restarts on death (`CTX_WATCHDOG=0` to disable).
3. **Keeper thread** — inside the engine; cheap Merkle probe; incremental sync + **publish**.

Managers (product language): **RuntimeManager**, **IndexManager**, **ResourceManager**. Watchdog is not a manager.

## Entry points

| Command | Module |
|---------|--------|
| `ctx` / `scubiee` | `pipeline.__main__:main` |
| `ctx-mcp` | `pipeline.mcp_server` → `mcp_locate` |
| HTTP | `pipeline.server:run_server` |

Packages: `pipeline` (engine), `graphify` (tree-sitter + NetworkX), `conductor` (fusion), `enrich` / `metadata` / `repo_ir` / `parse_harness`, `hybrid_cbm` (MCP facade), `seir` (experimental).

## Indexing pipeline (disk → searchable)

1. **Merkle** (`merkle.py`) — SHA-256 per indexable extension; skip `.venv`, `node_modules`, etc. `diff_hashes` → added/modified/removed.
2. **Graphify** — tree-sitter nodes/edges (calls, imports, inherits, …).
3. **RepoIR** — canonical symbols + edges (`parse_harness`).
4. **Chunk** — slice at callable symbol lines (`enrich`).
5. **Metadata headers** — module/file/imports prepended (`metadata`).
6. **Compress `mix`** — ≤512 chars high-signal text (`CTX_COMPRESS=off` to skip). Locked default.
7. **Embed** — CodeRankEmbed dim 768, L2-normalized.
   - Apple Silicon: **MLX** (`mlx_mac.py`, `embedder.py` `_ensure_mlx` per thread).
   - Else: FastEmbed + ORT (CUDA / DML / CoreML / CPU).
8. **TurboQuant** uint8 + **FAISS** IndexFlatIP.
9. Persist under `~/.context-engine/projects/ce_<hash>/` (chunks, merkle, graph, caches).

Incremental: only dirty files; after sync the **running daemon must `/v1/publish`** so `WarmSearchEngine` generation increments. CLI `ctx sync` prefers daemon `/v1/sync` (0.2.11). Only **code extensions** index — a `.txt` probe never appears.

## Query path

1. Embed query (CodeRank query prefix). MLX `embed_one` must use MLX, not fall through to Ollama (fixed 0.2.11/12).
2. **Conductor `D_channel_best`**: BM25 + FAISS dense + graph BFS affinity.
3. Fusion: min-rank across channels + agreement bonus + neighbor expansion; pick best chunk per file.
4. Capability cards (BM25 over module summaries) for SOFT queries.
5. Freshness: hot-patch BM25 from disk for dirty files; vectors catch up async.
6. Result bodies: **read span from disk** (vectors are pointers).

## MCP phase (product)

`packages/pipeline/mcp_locate.py`. Default `CTX_MCP_SURFACE=phase`.

- `map` — ranked cards, no bodies. Payload `ranked_only` / `scope=indexed_chunks`. A miss is not “not in the repo”.
- `focus` — outline / span / neighbors; already-in-session is **advisory**. Span may set `truncated`. Outline may set `language_unsupported` (Python AST only).
- `grep` / `glob` — live disk. Grep honors `glob` (default `*.py`; pass `*` / `*.ts`). Both return `truncated` / `has_more`. Empty + not truncated = absence for that glob/pattern only.
- `workspace` — pin / show / clear.
- `status` — health; tool list must include all six.

**No hard session caps** on map/search/focus. Duplicates → `usage_hint` only. Payload `max_chars` still applies.

Cursor rule shipped at `packages/pipeline/templates/context-agent.mdc`. `ctx setup` copies it to `.cursor/rules/context-agent.mdc` (`.cursor/` is gitignored). **Short + strict:** native Grep/Glob/search banned for discovery; CE MCP only. Exception: MCP missing or `status()` unhealthy. How to pick map vs grep vs glob is still recommended in MCP instructions.

MCP Python on Darwin: **do not** `Path(sys.executable).resolve()` — venv `bin/python` is a Homebrew Cellar symlink. Use `CTX_PYTHON` or `sys.prefix/bin/python` (`mcp_install.py`).

## Acceleration

`packages/pipeline/accel.py` → `~/.context-engine/accel.json`.

| Profile | When |
|---------|------|
| `mlx` | Apple Silicon default (FP16). `CTX_MLX=0` to opt out |
| `cuda` | NVIDIA |
| `dml` | Windows DirectML |
| `coreml` | Intel Mac / explicit CoreML; static ONNX helper in `coreml_mac.py` |
| `cpu` | Last resort |

Mac CoreML lessons (0.2.6–0.2.8): dynamic batch/shapes crash E5RT; invalid options `UseCPUAndGPU` / `CreateMLProgram` cause **silent CPU fallback**. Production Mac path is MLX. CoreML still refuses CPU fallback in `accel._refuse_coreml_cpu_fallback` when profile is coreml.

MLX ≥0.31: GPU streams are **thread-local**. `mlx_thread_stream()` + lock around eval; per-thread model in `threading.local()`. Daemon worker sync failed while CLI main-thread sync worked — test **both**.

Resource manager (`resources.py`): pause only if free RAM is near empty (default ~256 MB). Does not stop on CPU spikes or Windows “RAM % used” (file cache).

## Storage (`~/.context-engine/`)

- `accel.json`, `hardware.json`, `engine.lock` / `engine.pid` / `engine.log`
- `registry.json`, `prefs.json`
- `vectordb/collections/<name>/` — faiss, turboquant, ids
- `projects/ce_<hash>/` — merkle, chunks, graph, embed cache
- Session: `<repo>/.context-engine/session_store.json`

User **venv** on the MacBook: `~/scubiee`. That is **not** this directory.

## CLI that matters

```text
ctx setup [--repair] [--profile mlx|cuda|dml|coreml|cpu]
ctx init <repo> [--fast] [--roots a,b]
ctx engine ensure|start|stop|status
ctx sync .          # daemon sync + publish
ctx search "query"
ctx doctor .
ctx resources [--refresh]
```

## Tests that guard this design

- `tests/test_mcp_locate.py` / `test_mcp_lean.py` / `test_session_store.py` — phase tool set
- `tests/test_grep_glob_scope.py` — grep glob + `**` + truncated
- `tests/test_hybrid_cbm.py` — duplicate search advises, does not block
- `tests/test_runtime_publish.py` — publish-after-sync
- `tests/test_mlx_mac.py` / `test_mlx_backend.py` / `test_coreml_mac.py`
- `tests/test_memory_budget.py` — Windows RSS without `resource`
- `tests/test_accel_pip_drain.py` — pip stdout drain

## Do not regress

1. Hard map/focus/search caps.
2. `Path.resolve()` on Darwin MCP interpreter.
3. Skip `/v1/publish` after out-of-process sync.
4. MLX embed without per-thread stream.
5. Treat a `map` miss as “file absent,” or grep/glob as exhaustive when `truncated` is true.
6. Long ban / trajectory table in the Cursor rule.
7. Silent CPU fallback when the user asked for GPU.

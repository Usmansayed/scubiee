# Architecture

## System overview

Context Engine runs as a local HTTP daemon on port 8765. It indexes one repository at a time, keeps the index fresh in the background, and serves search queries to any client (MCP, CLI, dashboard). The core hypothesis: semantic search + graph gives agents better code context with fewer tokens than grep + full-file reads.

```
┌─────────────────────────────────────────────────────────┐
│  Clients                                                │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  ┌────────┐ │
│  │ MCP/IDE │  │ ctx CLI  │  │ Dashboard │  │ OpenCode│ │
│  └────┬────┘  └────┬─────┘  └─────┬─────┘  └───┬────┘ │
└───────┼─────────────┼──────────────┼────────────┼──────┘
        │ stdio       │ HTTP         │ HTTP       │ HTTP
        ▼             ▼              ▼            ▼
┌─────────────────────────────────────────────────────────┐
│  HTTP Server (pipeline/server.py)                       │
│  ThreadingHTTPServer on 127.0.0.1:8765                  │
│  Routes: /v1/search, /v1/open, /v1/sync, /v1/grep, ... │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│  RuntimeManager (pipeline/ce_service.py)                │
│  - Lifecycle: open_repo → register → index → warm      │
│  - Search engine generation (versioned, reload on sync) │
│  - Background sync loop (keeper)                        │
│  - Delegates to IndexManager + WarmSearchEngine         │
└──────────┬──────────────────────────┬───────────────────┘
           │                          │
           ▼                          ▼
┌─────────────────────┐  ┌───────────────────────────────┐
│  IndexManager       │  │  WarmSearchEngine              │
│  (index_manager.py) │  │  (engine.py)                   │
│  - full_index       │  │  - Cached in-process           │
│  - incremental_sync │  │  - Embedder + FAISS + BM25    │
│  - root_probe       │  │  - Graph + Conductor           │
└─────────────────────┘  │  - Capability cards            │
                         │  - search() → D_channel_best   │
                         └───────────────────────────────┘
```

## Process model

Three long-lived processes when fully running:

1. **Engine daemon** (`python -m pipeline engine run .`) — the HTTP server + RuntimeManager. Holds the warm search engine in memory. Managed via PID file + lock at `~/.context-engine/engine.lock`.

2. **Watchdog sidecar** (`python -m pipeline engine watchdog`) — polls `/health` every 15 seconds. If the engine dies, force-restarts it. Crash-loop protection caps restarts at 20/hour.

3. **Keeper thread** (inside the engine process) — `BackgroundSyncLoop` runs every 5 minutes. Does a cheap root probe (mtime-gated Merkle hash check). If dirty, runs incremental sync and republishes the search engine.

## Data flow: from source to searchable index

```
Source files on disk
    │
    ▼ scan_file_hashes() — SHA-256 per file, skip .venv/node_modules/etc
    │
    ▼ diff_hashes(old, new) — SyncDiff: added/modified/removed
    │
    ▼ graphify.extract(paths) — tree-sitter AST extraction → nodes + edges
    │
    ▼ graphify_to_repo_ir() — canonical RepoIR (symbols, edges, file summaries)
    │
    ▼ build_and_save_graph() — NetworkX graph → graph.json
    │
    ▼ chunk_repo_from_ir() — slice files at symbol boundaries → CodeChunks
    │
    ▼ inject_metadata() — prepend graph-derived headers → EnrichedChunks
    │
    ▼ compress_chunk(mode="mix") — distill to ≤512 chars of high-signal text
    │
    ▼ Embedder.embed_many() — CodeRankEmbed via FastEmbed/ONNX → float32 vectors
    │
    ▼ TurboQuant compress → uint8 codes (4x storage reduction)
    │
    ▼ FaissCollection.replace_all() — FAISS IndexFlatIP with L2-normalized vectors
    │
    ▼ PipelineStore.save_*() — chunks.jsonl, merkle.json, meta.json, graph_ir.json
```

## Data flow: from query to results

```
Agent sends query (via MCP tool or HTTP POST)
    │
    ▼ query_tune() — light English polish (optional)
    │
    ▼ Embedder.embed_one(query, is_query=True) — add CodeRank prefix, embed
    │
    ▼ Conductor.retrieve_D_channel_best(query, qvec, top_k)
    │   ├── BM25Index.search() — lexical ranking
    │   ├── FaissDenseAdapter.search() — cosine similarity via FAISS
    │   ├── GraphifyChunkRetriever.affinity_scores() — graph walk from seeds
    │   └── Channel fusion: min-rank + agreement bonus + neighbor expansion
    │
    ▼ Capability card merge (SOFT queries only) — BM25 over module summaries
    │
    ▼ hot_patch if dirty files exist — BM25 text from live disk
    │
    ▼ disk_preview() — read actual span from disk (vectors are pointers)
    │
    ▼ SearchResult[] with rank, file, score, preview, start/end lines
```

## Package dependency graph

```
repo_ir          (data contract — no deps)
    ↑
metadata         (depends on repo_ir)
    ↑
enrich           (depends on repo_ir, metadata)
    ↑
graphify         (depends on tree-sitter grammars)
    ↑
parse_harness    (depends on graphify, repo_ir)
    ↑
conductor        (depends on graphify, numpy, faiss)
    ↑
pipeline         (depends on everything above)
    ↑
hybrid_cbm       (depends on pipeline — optional facade)
seir             (depends on pipeline — experimental)
```

## Storage layout

Per-project data lives under `~/.context-engine/projects/ce_<hash>/`:

```
~/.context-engine/
├── accel.json           — hardware acceleration profile
├── hardware.json        — system capabilities snapshot
├── engine.json          — daemon metadata (pid, url, repo)
├── engine.lock          — single-instance lock
├── engine.pid           — raw PID file
├── engine.log           — daemon stdout/stderr
├── watchdog.pid         — watchdog PID
├── watchdog.log         — watchdog stdout/stderr
├── registry.json        — registered projects
├── prefs.json           — user preferences
├── vectordb/
│   └── collections/
│       └── <name>/
│           ├── meta.json
│           ├── faiss.index
│           ├── turboquant.npz
│           ├── ids.npy
│           └── payloads.jsonl
└── projects/
    └── ce_<hash>/
        ├── meta.json         — index metadata (model, timestamp, git head)
        ├── chunks.jsonl      — all chunk records (id, file, lines, text, enriched)
        ├── merkle.json       — file hash snapshot for change detection
        ├── graph_ir.json     — RepoIR (symbols + edges)
        ├── graph.json        — NetworkX graph (node-link format)
        ├── embed_cache.jsonl — embedding cache (key → vector)
        ├── embed_cache.npz   — compressed embedding cache
        └── capability_cards.json — BM25 capability index
```

Per-session state lives in the repo itself at `<repo>/.context-engine/session_store.json`.

## Key design decisions

1. **Single warm engine** — embeddings, FAISS, BM25, and graph are loaded once into memory. All queries share this warm state. Reload happens only after incremental sync commits new data (generation counter increments).

2. **Vectors are pointers** — at query time, the system reads the actual code span from disk (not from the stored chunk text). This means search results always reflect the current file content, even if dense vectors lag behind.

3. **D_channel_best as the single production retrieval path** — research explored many retrieval architectures (pure dense, pure graph, RRF hybrid, conductor fusion). The shipped system uses one path: BM25 + dense + graph, fused via min-rank with agreement bonus.

4. **Token-efficient by design** — the MCP tools return compact pointers (file + lines + why) rather than full code bodies. The session store deduplicates repeated fetches by content hash. Agents get "handles" they can expand later if needed.

5. **Background freshness** — instead of blocking on re-index before every query, the system does cheap mtime probes and hot-patches BM25 from disk for dirty files. Dense vectors catch up asynchronously. This keeps query latency low even on actively edited repos.

6. **Resource awareness** — all heavy operations (indexing, embedding, graph extraction) check CPU/RAM pressure first and throttle or defer when the system is busy. This protects interactive UX on developer machines.

## Configuration (environment variables)

| Variable | Default | Purpose |
|----------|---------|---------|
| CTX_ENGINE_URL | http://127.0.0.1:8765 | Daemon URL |
| CTX_REPO | cwd | Default repository path |
| CTX_RETRIEVE | D_channel_best | Retrieval mode for engine |
| CTX_MCP_SURFACE | read | MCP tool surface (read/nav/graph/rich/search/grep) |
| CTX_TOKEN_MODE | savings | Token budget strategy |
| CTX_COMPRESS | mix | Chunk compression mode |
| CTX_COMPRESS_MAX_CHARS | 512 | Max chars per compressed chunk |
| CTX_EMBED_MODEL | nomic-ai/CodeRankEmbed | Embedding model |
| CTX_EMBED_BATCH | (auto from accel) | Embedding batch size |
| CTX_BACKGROUND_SYNC | 1 | Enable keeper sync loop |
| CTX_SYNC_INTERVAL_MS | 300000 | Keeper probe interval (5 min) |
| CTX_AUTO_INDEX | 1 | Auto-index on open_repo |
| CTX_WATCHDOG | 1 | Enable watchdog sidecar |
| CTX_RM_DISABLE | 0 | Disable resource manager |
| CTX_HOME | ~/.context-engine | Override home directory |

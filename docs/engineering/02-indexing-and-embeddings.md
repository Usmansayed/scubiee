# Indexing and Embeddings

This document covers how source code enters the system, gets processed, and becomes searchable.

## The indexing pipeline

The full pipeline runs via `ctx index .` or automatically when the daemon opens a project. The sequence is:

1. Merkle scan
2. Graphify extraction
3. Chunking
4. Metadata enrichment
5. Chunk compression
6. Embedding
7. Vector storage
8. Persistence

Each stage is described below.

## 1. Merkle scan — change detection

**File:** `packages/pipeline/merkle.py`

The system computes SHA-256 hashes for every indexable source file (`.py`, `.ts`, `.js`, `.go`, `.rs`, `.java`, etc.), skipping `.git`, `.venv`, `node_modules`, `__pycache__`, and similar directories.

The hash map is stored as `merkle.json`. On subsequent runs, `diff_hashes(old, new)` produces a `SyncDiff` with added/modified/removed file lists. If nothing changed, the indexer short-circuits.

A `root_hash` (hash of all sorted path+hash pairs) provides a single-value freshness check — if it matches the stored value, the index is clean.

## 2. Graphify extraction — AST parsing

**File:** `packages/graphify/extract.py`

Graphify uses tree-sitter grammars (Python, JS, TS, Go, Rust, Java, C, C++, Ruby, C#) to extract structural information from every source file:

- **Nodes:** files, functions, classes, methods, interfaces — each with a source file, source location (line number), and label.
- **Edges:** imports, imports_from, calls, inherits, implements, contains, re_exports, method — each with source, target, relation, and confidence.

The extraction is deterministic — same input always produces same output. Results are cached per-file under `<store>/graphify-out/` for incremental re-extraction.

## 3. RepoIR — the structural data contract

**File:** `packages/repo_ir/__init__.py`

The raw Graphify extraction is converted to `RepoIR` via `parse_harness/graphify_adapter.py`. RepoIR is the canonical intermediate representation consumed by all downstream stages:

- `Symbol(id, name, kind, file, line)` — every code entity
- `Edge(source, target, relation, confidence, file)` — every relationship
- `FileIR(path, symbols, imports, exports, calls)` — per-file summary

This ensures enrichment, metadata, and conductor never re-parse ASTs — everything comes from one Graphify pass.

## 4. Chunking — slicing files into spans

**File:** `packages/enrich/__init__.py`

Files are sliced into chunks at callable symbol boundaries (functions, classes, methods) using their line numbers from RepoIR. A file with no callables becomes a single chunk. Each `CodeChunk` has:

- `file`, `start_line`, `end_line`, `content`, `symbol`

This produces chunks that are roughly one function or class each — natural retrieval units.

## 5. Metadata enrichment

**File:** `packages/metadata/__init__.py`

Each chunk gets a text header prepended with graph-derived context:

```
Repository: frontend-mcp
Module: coordination_layer
Folder: coordination_layer/runtime
File: coordination_layer/runtime/executor.py

Functions:
- execute_tool
- _resolve_handler

Imports:
- dispatch_registry
- session_manager

Exports:
- execute_tool

Graph Context:
- Parent Folder: coordination_layer/runtime/
- Related Files:
    - coordination_layer/runtime/dispatch_registry.py
- Immediate Dependents:
    - coordination_layer/navigation/tool_picker.py

--------------------------------
```

This header gives the embedding model structural context that wouldn't exist in the raw code alone — imports, dependents, siblings, etc.

## 6. Chunk compression

**File:** `packages/pipeline/chunk_compress.py`

After enrichment, the combined text (header + code) is compressed to fit a tight token budget before embedding. The production mode is `mix` (default 512 chars max):

**How `mix` works:**
1. Card-style labeled core first (~55% of budget): File, Module, Signature, Imports, Exports, APIs, Types, Related, Called-by.
2. Importance-scored body lines fill the remainder: lines are scored by identifier rarity (IDF), CamelCase/snake presence, and API call overlap. Highest-scoring lines pack in until budget is exhausted.

**Other modes (for research/ablation):**
- `skeleton` — AST structural skeleton only (signatures + docstrings)
- `card` — labeled retrieval card, body excerpt if budget remains
- `importance` — pure IDF-scored body lines
- `budget_a/b/c` — fixed allocation presets (different meta/symbol/API/body ratios)

**Key finding:** Information density matters more than window size. `mix` at 300 chars performs nearly as well as `mix` at 512, and embedding sequence length (128 vs 512) barely affects quality.

## 7. Embedding

**File:** `packages/pipeline/embedder.py`

The production model is **nomic-ai/CodeRankEmbed**, run via FastEmbed (ONNX Runtime). Key details:

- **Query prefix:** Queries get `"Represent this query for searching relevant code: "` prepended (required by the model).
- **Documents:** Code chunks are embedded without a prefix.
- **Backends:** FastEmbed (primary, supports cuda/dml/cpu via accel.py) or SentenceTransformers (fallback).
- **Caching:** Embeddings are cached to disk (`embed_cache.jsonl` / `embed_cache.npz`). Cache hits skip the model entirely.
- **Adaptive batching:** The ResourceManager controls batch size based on system pressure. On DML (AMD GPUs), batch=16 prevents OOM; on CUDA, batch=32-64.
- **Dimension:** 768-dimensional float32 vectors.

## 8. TurboQuant compression

**File:** `packages/pipeline/turbo_quant.py`

Before storing in FAISS, vectors are quantized using Google's TurboQuant method (ICLR 2026):

1. Store L2 norm of each vector.
2. Normalize to unit sphere.
3. Apply a seeded random orthogonal rotation (decorrelates dimensions).
4. Per-coordinate Lloyd-Max scalar quantization (Gaussian-derived bin boundaries).
5. Pack as uint8 codes (one byte per dimension).

At search time, codes are dequantized back to float32 for FAISS. The query stays in full precision (asymmetric comparison). This gives ~4x storage reduction with minimal recall degradation.

## 9. FAISS vector storage

**File:** `packages/pipeline/vectordb.py`

Vectors are stored in a `FaissCollection`:

- **Index type:** `IndexIDMap2(IndexFlatIP)` — flat inner-product index with explicit IDs. Vectors are L2-normalized before insertion, so inner product = cosine similarity.
- **Per-ID payloads:** Each vector ID maps to `{file, start_line, end_line, symbol, chunk_id}`.
- **Collections:** Each project gets its own collection, named from the project ID hash.
- **Persistence:** `faiss.index` + `turboquant.npz` + `ids.npy` + `payloads.jsonl` under `~/.context-engine/vectordb/collections/<name>/`.

## 10. Persistence

**File:** `packages/pipeline/store.py`

`PipelineStore` manages all on-disk artifacts:

- `chunks.jsonl` — every chunk record (id, file, lines, symbol, raw text, enriched text)
- `merkle.json` — file hash snapshot + mtimes
- `meta.json` — index metadata (embed model, bits, git head, timestamp, compress mode, collection name)
- `graph_ir.json` — the RepoIR (deterministic structural view)
- `graph.json` — the NetworkX graph (node-link format for conductor/graphify serve)
- `embed_cache.jsonl` / `.npz` — embedding cache

## Incremental sync

**File:** `packages/pipeline/incremental.py`

After the initial full index, changes are handled incrementally:

1. `check_freshness()` determines which files changed (via git + merkle + mtime).
2. Only changed/added files are re-extracted through Graphify.
3. New chunks are created and embedded.
4. The FAISS collection is rebuilt from kept vectors (old) + new vectors.
5. The graph is patched (not fully rebuilt) from the new extraction.
6. Capability cards are regenerated.

Hard cap: max 80 files per incremental sync. If more than 50% of the corpus changed, it refuses and recommends a full reindex.

## The graph

Two graph artifacts are produced:

1. **`graph_ir.json`** — the RepoIR (symbols + edges). Used by metadata enrichment and context_nav import tracing.
2. **`graph.json`** — the NetworkX node-link graph. Used by the Conductor's `GraphifyChunkRetriever` for affinity scoring, BFS expansion, and community detection. Also served via the Graphify MCP for interactive queries.

The graph represents structural relationships (who imports whom, who calls whom, who inherits from whom) — it's not a call graph from runtime traces, it's a static structural graph from AST analysis.

## Hardware acceleration

**File:** `packages/pipeline/accel.py`

The `ctx init` or `ctx setup` command:
1. Detects hardware (NVIDIA GPU? AMD via DirectML? CPU only?)
2. Installs the matching ONNX Runtime wheel (uninstalls conflicting ones)
3. Downloads and warms the CodeRankEmbed ONNX model
4. Runs a microbenchmark (target: 10 texts/sec)
5. Persists the profile to `~/.context-engine/accel.json`

The embedder reads this profile at runtime to select providers and batch size.

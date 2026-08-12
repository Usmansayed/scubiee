# Retrieval and Search

This document covers what happens when a query hits the system and how results are ranked.

## The warm search engine

**File:** `packages/pipeline/engine.py`

`WarmSearchEngine` is the central in-memory object. It holds:

- `chunks` — all `ChunkRecord` objects
- `texts` — the enriched text of each chunk (for BM25)
- `files` — file path per chunk
- `conductor` — `MultiArchConductor` (BM25 + dense + graph)
- `embedder` — shared `Embedder` instance (model loaded once)
- `capability` — `CapabilityIndex` (BM25 over module summaries)

It's loaded by `load_engine(root)` and cached per-root in a process-wide dict. After incremental sync, `clear_engines()` forces a reload on next access.

## The production retrieval path: D_channel_best

The engine's `search()` method uses a single retrieval architecture called `D_channel_best`. This fuses three signals:

### Signal 1: BM25 (lexical)

**File:** `packages/conductor/bm25_index.py`

A standard BM25 index over chunk texts. Good for exact symbol names, error messages, and literal patterns. Returns ranked chunk IDs by lexical relevance.

### Signal 2: Dense (semantic)

**File:** `packages/pipeline/searcher.py` → `FaissDenseAdapter`

The query is embedded with CodeRankEmbed (with the query prefix), then searched against the FAISS index. Returns ranked chunk IDs by cosine similarity. Good for vague/natural-language queries.

### Signal 3: Graph (structural)

**File:** `packages/conductor/graphify_retriever.py`

`GraphifyChunkRetriever` uses the NetworkX graph to compute affinity scores:

1. Score graph nodes against the query (trigram + IDF weighted node label matching).
2. Pick seed nodes from the highest-scoring matches.
3. BFS from seeds across the graph, decaying affinity by distance.
4. Map node affinity back to chunk IDs (nodes → files → chunks in those files).

Good for structural/relationship queries ("who calls X", "what imports Y").

### Fusion: the Conductor

**File:** `packages/conductor/conductor.py`

The `Conductor` class fuses the three signals into a single file-level ranking:

1. Compute file-level ranks from each channel (BM25, dense, graph).
2. For each file, take the **minimum (best) rank** across channels.
3. If a file appears in the top 25 of both graph and hybrid channels, give it an **agreement bonus** (small rank boost).
4. Expand with **neighbor files** from the graph (files adjacent to top results).
5. Within each selected file, pick the **best chunk** by combined score (graph + BM25 + 40×dense).

The result is a ranked list of `Hit(chunk_id, score, file, source)` where `source` indicates which channel dominated.

## Capability cards

**File:** `packages/pipeline/capability.py`

Capability cards are a lightweight intent index (no LLM):

- Built from module docstrings, public symbols, and path stems.
- Searched via BM25 (fast, deterministic).
- For SOFT queries only: if a card scores decisively above the threshold, it gets promoted ahead of RAG hits in the final result list.

This helps with queries like "where is authentication handled?" where a module-level summary card ("auth.py: handles login, token refresh, session validation") answers better than individual chunk embeddings.

## Freshness at query time

**File:** `packages/pipeline/incremental.py` → `ensure_fresh_for_search()`

Before returning results, the engine checks freshness:

1. **`none`** — index is clean, proceed normally.
2. **`incremental`** — few files changed: run incremental sync NOW (blocking, typically fast for ≤5 files).
3. **`background`** — moderate drift: search immediately with BM25 hot-patch for dirty files, kick a background thread to do the full sync.
4. **`full`** — large drift: same as background, but optionally triggers a full reindex in background.

### BM25 hot-patching

**File:** `packages/pipeline/hot_patch.py`

For files marked dirty (changed since last embed), the engine reads their current content from disk and overwrites the in-memory BM25 text for affected chunks. This gives the lexical channel instant visibility into edits without waiting for re-embedding.

Dense vectors still point at the old content until the background sync completes. This is the "vectors are pointers" philosophy — acceptable because BM25 + graph already find dirty files, and the preview text is always read from live disk.

## Query classification

**File:** `packages/conductor/query_router.py`

Queries are classified as:

- **SOFT** — natural language, vague ("where does session handling happen?"). Capability cards may activate. All three channels contribute.
- **HARD** — contains specific identifiers ("_build_session_context function"). Dense/BM25 dominate; graph is less useful.
- **PATH-like** — looks like a file path. Routed differently (direct file lookup rather than search).

## Search result format

Each result from the engine:

```python
SearchResult(
    rank=1,
    file="coordination_layer/runtime/executor.py",
    score=0.8234,
    chunk_id=142,
    preview="async def execute_tool(self, tool: str, ...) → ExecutionResult",
    source="D_channel_best:bm25+dense+graph",
    start_line=157,
    end_line=198,
)
```

The `preview` is read from live disk (not stored chunk text). The `source` field shows which channels contributed. This is what the MCP tools then format and return to the agent.

## The locate capability

**File:** `packages/pipeline/locate.py`

`locate()` is a higher-level retrieval function used by some MCP surfaces. It wraps search with:

1. Search hits (vector + BM25 hybrid)
2. Heuristic planning or optional LLM distillation (pick best targets, generate a brief)
3. Excerpt reading (fetch actual code for top targets)
4. Graph related context
5. Session governance (dedup via handles, token budget enforcement)

The result is a "card" — a structured response with `brief`, `targets`, `related_notes`, and excerpts. This is the "big retrieval" for first-ask scenarios where the agent needs a comprehensive map of how something works.

## Performance characteristics

- **Cold query** (first after engine start): ~200-500ms (model already loaded, just embed + FAISS + BM25).
- **Warm query** (embedder cached, FAISS hot): ~50-150ms.
- **Incremental sync** (5-10 files): ~2-5 seconds (re-extract + re-embed + FAISS rebuild).
- **Full index** (3000 chunks): ~2-5 minutes depending on GPU (most time in embedding).
- **Root probe** (nothing changed): ~10-50ms (mtime stat calls only).

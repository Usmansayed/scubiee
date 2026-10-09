# Research: how others keep code indexes fresh

Sources reviewed (2024–2026): Cursor blog, Claude Context (zilliztech), Sourcegraph Cody/Zoekt,
hybrid-code-rag-mcp, rag-code-mcp, pi-local-rag, code-indexer (Cursor-inspired).

## Common stack (almost everyone)

| Layer | Pattern |
|-------|---------|
| Detect | Content hash (SHA-256) and/or Merkle tree over files |
| Scope | Re-embed **only** added/modified files; delete vectors for removed paths |
| Cache | Chunk-content hash → skip re-embed if chunk text unchanged |
| Sync | Background (Cursor ~5m; Claude Context 5m + trigger file); optional on-save watcher |
| Serve | **Vectors are pointers** — read live file bytes at query time (Cursor) |
| Hybrid | Dense + BM25/ripgrep (RRF or blend) so lexical catches edits dense hasn't re-embedded |

## Product specifics

### Cursor
- Merkle tree for cheap sync; re-embed only changed syntactic chunks.
- Embeddings are async — search stays available against the prior index while copy/update runs.
- Client reads **local disk** for matched ranges (not blob from vector DB).
- Chunk embedding cache keyed by content hash.
- File save + ~5 min background; Resync Index for structural churn.

### Claude Context (Zilliz)
- Merkle DAG → `{added, removed, modified}`.
- Root hash equal → skip; else file-level compare.
- MCP: background sync on by default (`CLAUDE_CONTEXT_SYNC_INTERVAL_MS` = 5m), initial delay 5s.
- Trigger file `~/.context/.sync-trigger` for instant reindex after Write/Edit hooks.
- Delete-by-file then re-insert chunks; **all logs on stderr** (stdout = MCP protocol).

### Sourcegraph / Zoekt / Cody
- Zoekt: full reindex is often fine; **delta** indexing exists (`-delta`, threshold ~150 then full).
- Cody Enterprise **dropped embeddings** for native search — freshness + scale + no 3rd-party embed ops.
- Lesson: if dense lag hurts UX, lean harder on lexical/search until dense catches up.

### hybrid-code-rag-mcp
- Git-aware cases:
  - Same HEAD → skip files with matching mtime; hash only mtime-dirty.
  - HEAD moved → `git diff` old..new; full hash if diff > ~50% of corpus.
  - No git → full hash scan.
- Hybrid dense + BM25 sparse.

### rag-code-mcp / pi-local-rag
- Tool use kicks background refresh (non-blocking).
- Delete by file metadata before re-add.
- Optional age-based silent refresh (e.g. 24h).

## Friction model (what actually wastes agent time)

1. **Blocking full re-embed on every search** — worst.
2. **Serving stale dense as if fresh** — silent wrong answers (worse than latency).
3. **Best path:** cheap detect → small set sync-before-search → else search now with **fresh disk text + BM25 hot-patch + dirty boost**, dense refresh in background.

## What we implement

Aligned with Cursor + Claude Context + hybrid-code-rag:

1. Git fast-path (same HEAD + clean porcelain → skip scan).
2. Git diff when HEAD advances; Merkle for uncommitted / non-git.
3. Full reindex advice when changed fraction > 50%.
4. Sync-before-search for ≤40 files; background otherwise (already).
5. **BM25 + in-memory texts hot-patch from disk** before search when dirty (Cursor-style freshness without waiting for embed).
6. **Hit previews read from disk** (pointers, not stale chunk store).
7. Keeper loop (~5 min) + optional `.sync-trigger` (Claude Context): **root-hash probe first**;
   incremental only when dirty. Final check on `set_repo` / process exit.
   See `docs/superpowers/specs/2026-08-03-keeper-sync-lifecycle-design.md`.
8. MCP: warn on connect + warm; stderr-only protocol hygiene. Keeper on by default for MCP/`serve`.
9. Chunk embed cache via content SHA (already in `Embedder`).

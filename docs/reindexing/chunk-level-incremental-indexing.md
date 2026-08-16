# Chunk-level incremental indexing

## The short version

Context Engine detects changes at **file** depth and embeds changes at
**chunk** depth.

This is intentional:

1. File hashes are cheap enough to poll continuously.
2. Re-parsing a dirty file keeps AST and graph facts correct.
3. Chunk hashes prevent unchanged code inside that file from consuming another
   embedding call.

## Two Merkle layers

| Layer | Stored in | Answers |
|---|---|---|
| File Merkle | `merkle.json` | Which files changed? |
| Chunk Merkle | `chunk_merkle.json` | Which chunks in an already-dirty file need vectors? |

The file Merkle remains the first gate. It is not replaced by the chunk Merkle.

## Live indexing flow

```text
disk write
  → file hash differs
  → dirty file debounce
  → re-extract/re-chunk that file
  → compare old and new chunk Merkle entries
  → reuse vectors for identical chunks
  → embed only changed/new chunks
  → remove vectors for removed chunks
  → patch graph for the dirty file
  → publish when locate streak permits
```

## Chunk identity and hash

Each chunk has:

- a stable identity: its symbol when available; otherwise its line range;
- a SHA-256 digest of the **enriched embedding input**.

Line numbers are intentionally excluded from a symbol chunk's identity. A
function that merely moves down the file keeps its vector when its enriched
content is unchanged.

## What still runs for a dirty file

“Only embed changed chunks” does **not** mean “ignore the rest of the file.”
The complete dirty file is still parsed and chunked so that:

- graph edges remain accurate;
- deleted symbols/chunks are removed;
- changed chunk boundaries are discovered;
- BM25 and chunk records stay consistent.

Only the expensive embedding batch is reduced.

## Safety rules

- File dirty tracking remains capped by live storm controls.
- Chunk Merkle comparisons happen only after debounce, never for every editor
  keystroke.
- Missing or older `chunk_merkle.json` is safe: the next refresh treats the
  affected chunks as new and writes the snapshot.
- A fallback line-range key is less stable than a symbol key; parsers should
  provide symbols whenever possible.

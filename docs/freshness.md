# Freshness & low-friction stale search

See also: [research-freshness.md](research-freshness.md).

## Fixed caveats (Aug 2026)

| Issue | Fix |
|-------|-----|
| `git_fast` missed gitignored edits | Always **verify Merkle leaves** (mtime → hash) even when porcelain is clean |
| `--fast` missed most dirs | Broader defaults (`src,lib,app,packages,testdata,...`) + `CTX_FAST_ROOTS` / `--roots` |
| Graph rebuild silent fail | Warnings on stderr + `graph_error` / `last_graph_error` in meta |
| Large drift only incremental | `full` strategy runs **background `index --force`** |
| Slow sync after warm | Incremental **reuses** process-wide CodeRankEmbed via `get_embedder` |

## Detection order

1. Same HEAD + clean porcelain → still **merkle leaf verify** (`git_fast` only if leaves OK)
2. HEAD moved → `git diff` + leaf verify
3. mtime suspects → hash those
4. Merkle universe (indexed paths only)

## Strategies

| Drift | Action |
|-------|--------|
| 0 | Search |
| ≤40 | Sync-before-search |
| 41+ | Background incremental + BM25 hot-patch |
| ≥50% corpus | Background **full** reindex |

## Warm server

First load warns (~20–40s). Later queries reuse in-process model. After sync, engine rebinds.

```text
CTX_FAST_ROOTS=src,lib,app,packages,testdata
CTX_BACKGROUND_SYNC=1
CTX_SYNC_INTERVAL_MS=300000
python -m pipeline index <repo> --fast --roots src,lib,testdata
python -m pipeline serve <repo>
```

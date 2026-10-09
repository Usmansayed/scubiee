# Why live sync is not showing new files (2026-09-25)

Engine under test: **0.3.124**, repo `C:\Users\usman\Downloads\context-engine`, after a Cursor restart. Health at the start of the check: `warm_state=ready`, **7636** chunks, generation **1**.

## What happened

Three new files were written under `packages/pipeline/_sync_fast124/` and marked dirty.

| Step | Result |
| --- | --- |
| `POST /v1/sync` | **413 ms**, `ok=true`, keeper running, debounce **1000 ms** |
| `POST /v1/dirty` for the 3 files | **101 ms**, `ok=true` |
| Engine log | `[sync] memory mode=background` (the light budget, not `large_reindex`) |
| Embedder | Cold. `[embed] FastEmbed ready in 4093ms` on that same sync |
| First search | **18977 ms**, **no hits** (dense model was not ready yet) |
| About **25 s** later | Generation **1 → 2**. Chunk count stayed **7636** |
| Searches through **50 s** | Top hit stayed old files, including `packages/pipeline/_sync_pr_incoming/copy_12_env_guard.py` |
| Cleanup | Probe directory deleted, dirty posted again, `gone=true` |

The dirty **accept** did not fail. The **publish into the live search index** failed. The new files never became chunks the searcher could see.

The earlier ~40 s full-repo hash is not what this run did. 0.3.124 logged `memory mode=background` instead of `large_reindex`. The remaining failure is after that: the corpus on disk that search serves does not gain the new files.

## What “generation 2” actually means

`/health` chunk count is `len(engine.texts)` on the published binder. Generation is `runtime.generation`.

The keeper calls `_publish_runtime` only after `incremental_sync` returns `refreshed=true`. That function always does two things:

1. `load_engine(..., force_reload=True)`, which reads `chunks.jsonl` and builds `texts` from those lines.
2. `runtime.generation += 1`.

It increments generation even when the reloaded file has the **same** number of chunks. Generation **2** with **7636** chunks means a publish reloaded the corpus that was already there. It does not mean the 3 files were inserted.

Search uses that same binder (`_ensure_engine` → `runtime.engine`). It still returned `_sync_pr_incoming/copy_12_env_guard.py`, a file deleted in the previous experiment. Adds and deletes are both missing from the live binder. The searcher is serving a stale chunk list.

## Why the new files never land

There are two holes in the dirty path. Either one produces this measurement. The log shows both are open.

### 1. A sync that changes nothing is still reported as a success

At the end of `incremental_sync`, the success return is unconditional:

- `refreshed=True`
- `chunks_upserted=len(embed_records)`

`embed_records` can be **0**. That happens when the named files produce no chunk records (`chunk_file_from_ir` returns `[]` if the file has no lines, and any exception before the chunk write aborts the upsert). The keeper still treats `refreshed=true` as “publish now” (`sync_loop.drain_due`). Publish reloads `chunks.jsonl`, finds **7636** lines, and bumps generation.

So the engine can look like it synced (generation moved, `memory mode=background` was printed) while the chunk file never gained `f0.py`–`f2.py`.

`chunk_file_from_ir` does create one whole-file chunk when the file has lines and the graph has no symbols for it. A readable new `.py` file should not take this empty path. If it does, the cause is an exception **before** `_write_sliced_chunks`, not an empty file. That exception is the next hole.

### 2. Failures on the dirty path are not logged

`incremental_sync` catches exceptions and returns `refreshed=False` plus `error=str(exc)`. It does **not** print that error.

`BackgroundSyncLoop._sync_paths` (the path `mark_dirty` uses) returns that payload and does not print it either. The line `[keeper] refreshed N files` exists only on `_sync_unlocked`, which this drain does not call.

The engine log for this run matches that:

- `[sync] memory mode=background` is printed at the **start** of `incremental_sync`, before extract, embed, or the chunk write.
- `[embed] FastEmbed ready in 4093ms` means the model load ran (this sync had texts to embed, or search prewarm raced the same loader).
- There is **no** `[keeper] refreshed` line and **no** sync error line.
- The only tracebacks in that window are `ConnectionAbortedError` WinError **10053** on `/health` and `/v1/client/touch`. Those are the client closing the socket. They are not the sync failure.

If vector upsert throws **after** the model loads and **before** or **during** the chunk write, the function returns `refreshed=False`, the keeper does not have a printed reason, and the in-memory engine stays on the old 7636 texts. A later no-op `refreshed=True` (hole 1) still bumps generation.

The named-file write and the vector update are also ordered so a crash between them splits the store:

1. `_write_sliced_chunks` rewrites `chunks.jsonl` (untouched lines plus new records).
2. `_upsert_named_vectors` then `col.add` / `save_collection`.

If step 2 throws, step 1 may already have been written, but `refreshed` stays false, so the live engine is not swapped. Search keeps the old list. The next successful publish loads whatever `chunks.jsonl` is at that moment. In this run the loaded list was still 7636, so the new lines were not in the file the publisher read.

### 3. The cold embedder sits on the keeper thread

The model was not loaded. The sync paid **4.1 s** inside `get_embedder` before it could finish the write. The first `/v1/search` took **19 s** and returned an empty hit list because `ce.search` refuses to answer until FastEmbed is ready (`dense_embed_loading`). That delay is real, and it is not the reason the chunk count stayed 7636 after generation moved.

## What is not the cause

- The keeper was running. `/v1/sync` returned `ok=true` in 413 ms, not “keeper not running”.
- This run did not take the old full-repo `large_reindex` walk. The log says `background`.
- The 10,000-chunk cap was not involved. Three tiny files are tier 1 (live batch after the 1 s debounce).
- The probe files were removed at the end of the check. Their absence now is cleanup, not the reason search missed them at 25–50 s, while they were still on disk.

## What to change

1. **Publish only when the corpus actually changed.** If `chunks_upserted` and `chunks_removed` are both 0, do not call `_publish_runtime` and do not increment generation.
2. **Log the dirty-path result.** Print `refreshed`, `chunks_upserted`, `chunks_removed`, `ms`, and `error` from `_sync_paths`. A swallowed exception is why this run has a memory-mode line and no reason.
3. **Make the chunk write and the vector upsert one publication.** If `col.add` / `save_collection` fails, do not leave `chunks.jsonl` ahead of the vectors, and do not report success. The live engine should swap only after both are durable.
4. **Keep the embedder warm** so a one-file sync does not spend 4 s loading FastEmbed on the keeper thread before the write. The 1 s debounce plus a warm embed of a few chunks is the budget. The model load is extra.
5. **Re-check with files that are not deleted until search returns them.** Assert health `chunks` increases and `hits[].file` contains the new path. Generation movement alone is not a pass.

Until those are in, a dirty mark can return in ~100 ms and the search index can stay on the previous corpus, including files that have already been deleted from disk.

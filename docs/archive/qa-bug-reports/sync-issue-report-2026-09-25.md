# Sync issue report (2026-09-25)

Repo: `C:\Users\usman\Downloads\context-engine`. Engine: `http://127.0.0.1:8765`. Log: `C:\Users\usman\.scubiee\engine.log`. Installed wheel at the last live check: **0.3.127**.

This report is the current picture. `docs/sync-failure-2026-09-25.md` is the earlier 0.3.124 write-up. Several holes it names were closed in later builds. The live symptom did not move.

## The issue

A new file can be marked dirty in a few hundred milliseconds. The running search index does not then contain that file.

A pass is both of these, within a few seconds after the embedder is warm:

1. `/health` `chunks` goes up by the new file’s chunks.
2. `POST /v1/search` returns that path in `hits[].file`.

Generation moving is not a pass. A token echoed in the search body is not a hit. The probe directories are deleted after each run, so a later search of an old token cannot prove the file was indexed.

That pass has not happened on the live engine in 0.3.123, 0.3.124, 0.3.125, 0.3.126, or 0.3.127.

## What succeeded, and what that test actually runs

`tests/test_locate_contract_bounds.py::test_realistic_add_noop_and_delete` passed (about 2 s, together with the ordering test). It calls `incremental_sync` in-process:

- a temporary store, not `~/.scubiee`
- a fake embedder, not FastEmbed
- `force_files` pointed at the files just written
- no HTTP server, no dirty ledger, no keeper thread
- no memory-mapped FAISS index of the 7k-chunk corpus
- no `load_engine` into the process that answers `/health` and `/v1/search`

Under those conditions the function does the right local thing: a new file upserts at least one chunk and removes none, a second sync of an unchanged file returns `refreshed=false`, and deleting the new file removes its chunks.

The other unit tests that passed check the same function or the ledger in isolation: skip the repo-wide freshness walk, do not rewrite untouched chunk lines, small touches use the background memory budget, a zero-chunk result does not call `on_refresh`, a cold embedder defers when `CTX_SYNC_WAIT_FOR_EMBEDDER=1`, and files that still exist are ordered before missing paths.

None of those tests ask the installed engine whether search can see the file.

## What the live path actually is

```
POST /v1/dirty
  → mark_dirty (accept, no embed)
  → BackgroundSyncLoop drain_due, after ~1 s debounce
  → maybe defer because FastEmbed is not loaded
  → incremental_sync(force_files=batch)
  → write chunks.jsonl / vectors / merkle
  → _publish_runtime: load_engine + generation += 1
  → /health chunks = len(engine.texts)
  → /v1/search reads that same engine
```

`POST /v1/dirty` returning `ok: true` only means the path was queued. `POST /v1/sync` does not embed either; it asks the keeper to poll and returns `strategy=deferred`.

The simulation stops at `incremental_sync` on a toy store. The failure shows up in the steps around it: which paths the ledger hands over, whether that call decides there is a delta, whether the vector write survives, and whether the process that serves search reloads the file that was just written.

## Live runs

Probe files were small `.py` files with a unique token, written under `packages/pipeline/`, then `POST /v1/dirty`, then health and search polled. The directory was deleted at the end of every run.

| Build | Dirty accept | What the log said | Health | Search | Process |
| --- | --- | --- | --- | --- | --- |
| 0.3.123 | immediate | full-repo freshness walk, then embed | +8 chunks at ~40 s for 8 tiny files | new folders never ranked | stayed up; a 40-file paste never added another step |
| 0.3.124 | 101 ms | `memory mode=background`; FastEmbed ready in 4093 ms | generation 1→2 at ~25 s, chunks stayed 7636 | first search 18977 ms, no hits; later hits were old files, including a deleted `_sync_pr_incoming` copy | stayed up |
| 0.3.125 | 110.5 ms | `dirty sync refreshed=True upserted=0 removed=85` in 11271 ms | generation 1→2 at 19.2 s, chunks stayed 7640 | top hit stayed `docs/scubiee-lifecycle-scenarios.md`; probe path absent | then died (connection refused) |
| 0.3.126 | 523 ms | embed `1 new` in 1.7 s, then FAISS abort | chunks stayed 7649; restart came back warming at 0 | probe path absent | aborted: `MaybeOwnedVector::resize` / `is_owned` / viewed vector |
| 0.3.127 | 217 ms | embedder cold, defer 3 paths; then several `no chunk delta files=3` at 12–23 s; then `upserted=5 removed=2` in 31743 ms | generation 1→2, chunks stayed 7652, embedder true by ~19 s | probe path absent the whole poll; last call `index 7641 is out of bounds for axis 0 with size 7641` | stayed up |

0.3.127 is the first live run that did not kill the process. It is still not a pass. Chunk count did not change. `hits[].file` never contained `packages/pipeline/sync_live127/f0.py`.

## Fixes that were real, and why they were the wrong layer

Each build fixed something the previous log actually showed. Each one left the same live result: the searcher does not see the new file.

**0.3.124 — the 40 s delay.** `incremental_sync(force_files=...)` called `check_freshness` first. On a dirty git tree that hashes or stats every Merkle leaf, then throws the result away because the caller already named the files. A named set now skips that walk. A touch of 300 files or fewer uses the background memory budget (500 MB) instead of the large-reindex budget. The live log confirmed `memory mode=background`. The new files still did not appear.

**0.3.125 — publish on an empty delta, and silent errors.** A sync with `upserted=0` and `removed=0` no longer reloads the engine or bumps generation. Failures print `[sync] failed` and `[keeper] dirty sync ... error=`. The engine sets `CTX_SYNC_WAIT_FOR_EMBEDDER=1` and defers the batch until FastEmbed is loaded, instead of loading the model on the keeper thread. The next live run was not an empty delta. It logged `upserted=0 removed=85` and still did not change the chunk count.

**0.3.126 — false deletions.** `removed_ids` had been every old chunk of a touched file, including chunks whose text had not changed. That made a batch look like a large deletion and skipped embedding the new file. Unchanged chunks now keep their ids. Only chunks that disappeared, or whose text changed, are deletions. Files that still exist are ordered ahead of a deletion backlog. The realistic simulation passed after this. The next live run embedded the one new chunk in 1.7 s and then the process aborted inside FAISS, before publish.

**0.3.127 — mmap FAISS abort.** The collection is opened with `IO_FLAG_MMAP_IFC`. On faiss 1.15.1 that index stores codes as a viewed `MaybeOwnedVector<unsigned char>`. `add_with_ids` and `clone_index` both abort the process (`is_owned`). `add` and `delete` now re-read `faiss.index` with a plain `read_index` before mutating. A unit test reloads a saved collection and adds one vector. The live engine stayed up. The new file was still absent.

So the crash, the false removal count, the freshness walk, and the empty publish were all real. They are not why a brand-new file is missing after a run that stays up and logs `no chunk delta`.

## What the 0.3.127 log is saying

`[sync] no chunk delta files=3` is printed only when `incremental_sync` finishes parse and diff with **no** chunks to embed and **no** chunks to remove, and returns `strategy=none` **before** rewriting `chunks.jsonl`. The keeper then completes that batch (`published=True`) without swapping the search engine.

The probe was **one** new file: `packages/pipeline/sync_live127/f0.py`, containing a function and a unique token. The log’s batches were **3** paths, several times, 12–23 s each, all with no delta. Those 3 paths are not “the file we just created, successfully parsed.” A readable new `.py` file with a function becomes at least one chunk in the simulation. A no-delta result means the batch the keeper actually ran did not produce a new chunk and did not see an old chunk to delete.

That fits a ledger batch of paths that are already gone and were never in `chunks.jsonl` (earlier probe files such as the 3-file `sync_live125` set, deleted at the end of that run). For a missing file that has no old chunks, `existing` is empty and `new_records` is empty, so the function honestly reports no delta and the keeper drops the batch. The new file is either stuck behind that backlog or included in a 3-path set that still nets to nothing. The log line does not print the paths, so this run cannot prove which of those two it was. It can prove the batch that ran was not a successful insert of `f0.py`.

One later line did claim a real delta: `dirty sync refreshed=True upserted=5 removed=2` in 31.7 s. Generation moved to 2. `/health` chunks stayed **7652**. So a publish ran, and the binder it installed had the same text count as before. Search then failed with `index 7641 is out of bounds for axis 0 with size 7641`. Health’s chunk count and the array search indexed are not the same length. The searcher is not serving a single consistent corpus.

Search hits through the rest of the poll stayed on old paths, including `packages/pipeline/_sync_pr_incoming/copy_8_dashboard_port.py`. That tree was deleted in an earlier experiment. The live index still retrieves it. Adds and deletes are both missing from the binder search uses.

## What is not the remaining cause

- The dirty HTTP accept. 70–523 ms, `ok: true`, on every live run.
- The 1 s debounce. The polls ran for 40–90 s.
- The 10k auto-full-index cap. These probes are 1–40 files.
- Ranking. `mode=lean` and composite pack ranking were not changed. The new path is absent from `hits[]`, not merely ranked low. The top hits are unrelated old files.
- “Embeddings must be milliseconds.” The accept should be milliseconds. Embedding a warm small batch is on the order of 1–2 s. 0.3.126 did embed 1 chunk in 1.7 s. The miss happens after that, or instead of that, when the keeper reports no delta.
- The freshness walk. 0.3.124 removed it for named files. Later runs logged the background budget, or no chunk delta, not a 40 s corpus hash.
- The simulation being wrong about parse/diff. It is right for a direct `force_files` call on a store that contains only the files under test. It never loads the live ledger, the live `chunks.jsonl`, or the live search process.

## What to look at next

The next check has to be on the installed engine, and it has to name the paths in the keeper line. Until a log line shows `sync_live…/f0.py` with `upserted>=1`, and `/health` chunks increases, and `hits[].file` is that path, the sync is not working.

The open questions, in the order the 0.3.127 run raises them:

1. Which 3 paths were in the `no chunk delta` batches? If they are deleted probes, the ledger is spending 10–20 s per batch on files that are already gone, and the new file is not the thing being synced.
2. Why did `upserted=5 removed=2` leave `/health` at 7652 chunks? Publish reloaded something that was not the post-write corpus, or the write did not land in the `chunks.jsonl` that `load_engine` reads.
3. Why does search use an array of length 7641 while health reports 7652, and why does it still return deleted `_sync_pr_incoming` files? The in-memory engine, the chunk file, and the FAISS index have diverged. A generation bump does not repair that.

Fixing another branch inside `incremental_sync` and re-running the in-process simulation will not answer these. The simulation already passes.

---

# Resolution (0.3.128)

The three open questions above have answers, and they share one cause: **the chunk corpus and the vector store were addressing different things, and nothing checked.**

## Measured state of the live store before the fix

| Artifact | Count |
| --- | --- |
| `chunks.jsonl` records | 7655 |
| `ids.npy` vector ids | 7642 (1 tombstone → 7641 live) |
| `faiss.index` ntotal | 7641 |
| `payloads.jsonl` | 7641 |
| chunks with **no** live vector | **147** |
| live vectors with **no** chunk | **133** |
| rows where `chunks[i].id == live_ids[i]` | 3677 of 7641 — diverges from row 3677 on |

Every chunk missing a vector belonged to a file edited during that session: `sync_loop.py` (39), `vectordb.py` (39), `incremental.py` (24), `test_live_reindexing.py` (21), `test_locate_contract_bounds.py` (15), and a handful more.

## The cause

`load_engine` builds `files`, `texts`, the BM25 docs and the graph spans from `chunks.jsonl`, indexed by **chunk position**. It built the dense channel from the vector store, indexed by **vector-store row**. `FaissDenseAdapter.search` translated a FAISS id into a row of `col.ids` — the wrong space — and nothing compared the two lengths.

Three consequences, each matching a symptom in this report:

1. **Dense hits were mislabelled.** Measured on the live store with 40 random probes: 198 of 400 dense hits resolved to a file that was not the one in the vector's own payload. That is why deleted paths such as `packages/pipeline/_sync_pr_incoming/copy_8_dashboard_port.py` kept ranking — a surviving row aliased onto a stale position.
2. **Tail chunks raised `IndexError`.** `_best_chunk` does `float(d_all[i])` with `i` a chunk position. `d_all` had 7641 entries and the corpus had 7655, so any chunk at position ≥ 7641 raised `index 7641 is out of bounds for axis 0 with size 7641` — the exact error in the 0.3.127 run. New chunks are appended, so a new file always landed in the crash window.
3. **A chunk with no vector can never be a hit.** `retrieve_D_channel_best` admits a file only if the dense channel retrieved it (`if "dense" not in chans: continue`). The 147 orphan chunks were unreachable by construction, no matter how the query was phrased.

Separately, the keeper's `no chunk delta` loop had its own cause. `canonical_relpath` ends in `os.path.normcase`, which on Windows turns `/` back into `\` and lower-cases. The Merkle snapshot therefore stores `packages\pipeline\sync_live127\f0.py`, while `_patch_file_merkle` popped `packages/pipeline/sync_live127/f0.py`. The delete never matched, the entry survived, `root_probe` re-reported the path on every poll, and the keeper re-synced it forever — about 9.4 s per cycle, indefinitely.

## Answers to the three questions

1. **Which 3 paths were in the `no delta` batches?** Deleted probes, as suspected. The log line now names them. A live run printed `[sync] no chunk delta files=2 paths=packages/pipeline/sync_live127/f0.py,packages/pipeline/sync_live128/__init__.py`. They repeated because the Merkle patch could not delete their keys, not because the batch itself was wrong.
2. **Why did `upserted=5 removed=2` leave `/health` at 7652?** It did not leave the corpus unchanged — `/health` counts `len(engine.texts)` from `chunks.jsonl`, and the vectors are what had changed. The count the searcher actually indexed was the vector matrix, a different and shorter array. The two numbers were never measuring the same corpus.
3. **Why 7641 vs 7652, and why did deleted files still return?** Because the in-memory engine loaded `chunks.jsonl` and the FAISS collection independently, with no consistency check, and then mixed their position spaces. A generation bump cannot repair that; it reloads the same mismatch.

## Changes

- `pipeline/searcher.py` — `FaissDenseAdapter` takes `chunk_ids` and re-indexes the vector matrix into chunk position space: row `i` holds the vector for `chunk_ids[i]`, a chunk with no live vector gets a zero row, tombstones are excluded, and `search` maps a FAISS id to a chunk position. Exposes `missing_vectors`.
- `pipeline/engine.py` — `load_engine` passes the chunk ids. `WarmSearchEngine.dense_missing()` and `status()["dense_missing"]` report the drift.
- `pipeline/ce_service.py` — `/health` reports `dense_missing`, so a corpus the searcher cannot fully serve is no longer hidden behind a healthy `chunks` count.
- `conductor/architectures.py` — `_fit_channel` forces every channel score array to exactly one entry per chunk. A length mismatch can no longer raise inside ranking.
- `pipeline/incremental.py` —
  - vectors are written **before** chunk lines, so a crash between them leaves orphan vectors (ignored) instead of orphan chunks (unsearchable);
  - `reconcile_vector_store` re-embeds chunks that lost their vector and drops vectors whose chunk is gone, bounded by `CTX_VECTOR_BACKFILL_CAP` (2000);
  - a delete compacts the collection, so `ids.npy`, `payloads.jsonl` and `faiss.index` keep one length;
  - `_patch_file_merkle` writes and deletes the **canonical** key;
  - a no-delta batch patches the Merkle, refreshes the publication manifest, runs the reconcile, and logs its paths;
  - `_refresh_publication` replaces two copies of the manifest-stamping block.
- `tests/test_sync_corpus_alignment.py` — new. Locks in the position mapping, the out-of-bounds backstop, the two-way reconcile, and the Merkle patch. The Merkle test was confirmed to fail when the canonical-key fix is reverted.
- `scripts/live_sync_probe.py` — asks the installed engine the only question that counts. Unique probe path per run, aborts if the path is already searchable, and reports both criteria.

## Live verification, 0.3.128

Installed wheel, real engine, real FastEmbed (CPU on this machine — DirectML is unavailable), probe path unique and confirmed absent from search before the write:

```
baseline search does not contain packages/pipeline/sync_live_1790354474/f0.py
dirty accept in 184 ms
t+29s  hit=True   top=['packages/pipeline/sync_live_1790354474/f0.py', ...]
t+33s  chunks=7676 gen=2

health chunks increased (7674 -> 7676): True
search returned packages/pipeline/sync_live_1790354474/f0.py: True
```

The new file is the **rank-one hit**, 29 s after the write, and the chunk count moved by its two chunks. Reproduced across four consecutive runs.

Store state after the reconcile ran on the live index:

| | before | after |
| --- | --- | --- |
| `chunks.jsonl` | 7655 | 7681 |
| `ids.npy` | 7642 | 7681 |
| tombstones | 1 | 0 |
| chunks with no vector | 147 | **0** |
| vectors with no chunk | 133 | **0** |
| `/health` `dense_missing` | — | **0** |

The keeper loop is gone. The dirty ledger drains to `published` with nothing stuck, and the stale `sync_live*` Merkle entries are deleted instead of being re-reported every poll.

## Still open

- Per-batch sync is 10–20 s on this machine because FastEmbed is running on CPU (`DmlExecutionProvider not in available providers`). That is an environment problem, not a sync problem, but it sets the floor on time-to-searchable.
- `_best_chunk`'s stale AST span issue (noted separately in `docs/scubiee-bugs-found.md` as bug 3b) is untouched.
- Four pre-existing test failures are unrelated to this work and were confirmed to fail before it: `test_final_check_forces_held_publish`, `test_search_returns_warming_without_blocking_embedder`, `test_warm_engine_for_mcp_waits_for_embedder`, `test_incremental_missing_graph_falls_back`.

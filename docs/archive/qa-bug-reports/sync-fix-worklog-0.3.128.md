# Sync fix worklog — 0.3.128

Date: 2026-09-14 (session). Repo: `C:\Users\usman\Downloads\context-engine`. Engine: `http://127.0.0.1:8765`.

This is the detailed record of diagnosing and fixing the sync issue from `docs/sync-issue-report-2026-09-25.md`: a newly created file was marked dirty in a few hundred milliseconds but never became searchable. It had not passed on the live engine in builds 0.3.123 through 0.3.127.

The pass criteria, taken from the report and not relaxed:

1. `/health` `chunks` goes up by the new file's chunks.
2. `POST /v1/search` returns the probe path in `hits[].file`.

A generation bump is not a pass. A token echoed in the response body is not a hit.

---

## 1. How the diagnosis was done

I did not trust the in-process unit test (`test_realistic_add_noop_and_delete`) that the report already flagged as a false positive — it uses a temp store, a fake embedder, no HTTP server, no keeper, and no memory-mapped FAISS index. Instead I measured the actual live store on disk.

Store locations for this repo (`project_id = ce_c505c4e65dbe5e2063a6c1089fe4db4e`):

- chunks/merkle/meta: `C:\Users\usman\.scubiee\projects\ce_c505c4e65dbe5e2063a6c1089fe4db4e\`
- vectors: `C:\Users\usman\.scubiee\vectordb\collections\context-engine_c505c4e65dbe5e20\`

I wrote a throwaway diagnostic that loaded `chunks.jsonl`, `ids.npy`, `faiss.index`, `payloads.jsonl` and `meta.json` and compared them. Measured state **before** the fix:

| Artifact | Count |
| --- | --- |
| `chunks.jsonl` records | 7655 |
| `ids.npy` vector ids | 7642 (1 tombstone → 7641 live) |
| `faiss.index` ntotal | 7641 |
| `payloads.jsonl` lines | 7641 |
| chunks with **no** live vector | **147** |
| live vectors with **no** chunk | **133** |
| rows where `chunks[i].id == live_ids[i]` | 3677 of 7641 — diverges from row 3677 onward |

Every chunk missing a vector belonged to a file edited during the earlier session: `sync_loop.py` (39), `vectordb.py` (39), `incremental.py` (24), `test_live_reindexing.py` (21), `test_locate_contract_bounds.py` (15), plus a handful more.

That table alone explained the report's mysterious "health says 7652, search indexes 7641" divergence: they are two different files being counted, and nothing kept them in step.

Then I traced the code paths: `load_engine` (`engine.py`), `FaissDenseAdapter` (`searcher.py`), `retrieve_D_channel_best` and `_best_chunk` (`conductor/architectures.py`), `incremental_sync` and `_upsert_named_vectors` (`incremental.py`), the keeper (`sync_loop.py`), and the Merkle helpers (`merkle.py`).

---

## 2. Root cause

**The chunk corpus and the vector store were addressing different things, and nothing checked.**

`load_engine` builds `files`, `texts`, the BM25 docs and the graph spans from `chunks.jsonl`, indexed by **chunk position** (the record's offset in the file, which is also the index into `files`/`texts`/BM25/graph). It built the dense channel from the vector store, which is indexed by **durable chunk id** and keeps tombstones — so its row order drifts from the chunk list after any incremental upsert or delete. `FaissDenseAdapter.search` translated a FAISS id into a row of `col.ids` (the wrong space), and no code compared the two lengths.

Three consequences, each matching a symptom in the report:

1. **Dense hits were mislabelled.** Measured with 40 random probes against the live store: 198 of 400 dense hits resolved to a file that was not the one in the vector's own payload. That is why deleted paths such as `packages/pipeline/_sync_pr_incoming/copy_8_dashboard_port.py` kept ranking — a surviving row aliased onto a stale chunk position.
2. **Tail chunks raised `IndexError`.** `_best_chunk` does `float(d_all[i])` where `i` is a chunk position. `d_all` had 7641 entries and the corpus had 7655, so any chunk at position ≥ 7641 raised `index 7641 is out of bounds for axis 0 with size 7641` — the exact error from the 0.3.127 run. New chunks are appended, so a brand-new file always landed in the crash window.
3. **A chunk with no vector can never be a hit.** `retrieve_D_channel_best` admits a file into the pool only if the dense channel retrieved it (`if "dense" not in chans: continue`). The 147 orphan chunks were unreachable by construction, no matter how the query was phrased.

**Separate cause for the `no chunk delta` loop.** `canonical_relpath` (`merkle.py`) ends in `os.path.normcase`, which on Windows turns `/` back into `\` and lower-cases. The Merkle snapshot therefore stores `packages\pipeline\sync_live127\f0.py`, while `_patch_file_merkle` popped `packages/pipeline/sync_live127/f0.py`. The delete never matched, the entry survived, `root_probe` re-reported the path on every poll, and the keeper re-synced it forever — about 9.4 s per cycle, indefinitely. This is why the log kept printing `no chunk delta files=1/2` on deleted probe files.

---

## 3. Answers to the report's three open questions

1. **Which 3 paths were in the `no delta` batches?** Deleted probes, as suspected. The keeper line now names them: a live run printed `[sync] no chunk delta files=2 paths=packages/pipeline/sync_live127/f0.py,packages/pipeline/sync_live128/__init__.py`. They repeated not because the batch was wrong but because the Merkle patch could not delete their keys.
2. **Why did `upserted=5 removed=2` leave `/health` at 7652?** The corpus did change; `/health` counts `len(engine.texts)` from `chunks.jsonl`, and it was the vectors that moved. The array the searcher indexed was the vector matrix, a different and shorter array. The two numbers were never measuring the same corpus.
3. **Why 7641 vs 7652, and why did deleted files still return?** The in-memory engine loaded `chunks.jsonl` and the FAISS collection independently, with no consistency check, then mixed their position spaces. A generation bump reloads the same mismatch, so it can't repair it.

---

## 4. Changes made

### `packages/pipeline/searcher.py`
`FaissDenseAdapter` now takes an optional `chunk_ids` list and re-indexes the vector matrix into **chunk position space**: row `i` holds the vector for `chunk_ids[i]`, a chunk with no live vector gets a zero row, tombstoned ids are excluded, and `search` maps a FAISS id back to a chunk position via `self._chunk_row`. Added a `missing_vectors` property.

### `packages/pipeline/engine.py`
- `load_engine` passes `chunk_ids=[int(c.id) for c in chunks]` when constructing the adapter.
- New `WarmSearchEngine.dense_missing()` and `status()["dense_missing"]` so the drift is observable.

### `packages/pipeline/ce_service.py`
`/health` now reports `dense_missing`. A corpus the searcher cannot fully serve is no longer hidden behind a healthy `chunks` count.

### `packages/conductor/architectures.py`
Added `_fit_channel(scores, n)`, which forces every channel score array to exactly `n` entries (pad with 0.0, truncate if longer). `_channel_maps` runs the graph, BM25 and dense arrays through it. A length mismatch can no longer raise inside `_best_chunk` and turn a search into a 500 — this is the defensive backstop behind the real fix.

### `packages/pipeline/incremental.py`
- **Write order reversed** in the named-delta path: vectors are upserted **before** chunk lines are written. A crash between the two now leaves orphan *vectors* (unreferenced ids, harmless) instead of orphan *chunks* (unsearchable).
- **`reconcile_vector_store(store, ...)`** (renamed from an earlier `backfill_missing_vectors`): re-embeds chunks that have no live vector using their stored `enriched` text (so the file need not still exist on disk), and drops vectors whose chunk is gone. Bounded by `CTX_VECTOR_BACKFILL_CAP` (default 2000). Returns `{"missing", "embedded", "stale", "dropped"}`. Guarded to no-op on the fake collection objects used by tests.
- **Delete now compacts.** `_upsert_named_vectors` calls `col.compact()` after a delete, so `ids.npy`, `payloads.jsonl` and `faiss.index` keep one length instead of accumulating tombstones. Guarded with `getattr` so test doubles without `compact` still work.
- **`_patch_file_merkle` uses the canonical key.** It now writes and deletes `canonical_relpath(rel)` and also sweeps the raw/posix spellings, so a deleted file's Merkle entry is actually removed and older snapshots converge.
- **No-delta batches do real work.** A batch with nothing to embed or remove now patches the Merkle, refreshes the publication manifest, runs the reconcile, logs its paths, and reports `refreshed` only if the reconcile embedded or dropped something.
- **`_refresh_publication(store)`** extracted to replace two copies of the invalidate/publish-manifest block, and it now runs after no-delta batches too (previously readiness could reject a live update as checksum corruption).

### `tests/test_sync_corpus_alignment.py` (new, 4 tests)
- `test_dense_adapter_maps_faiss_hits_to_chunk_positions` — durable ids with gaps and out-of-order insertion; asserts each vector scores highest at its own chunk's position and `search` returns the right file.
- `test_unaligned_adapter_would_index_out_of_bounds` — proves the old shape raised `IndexError` and that `_fit_channel` pads it safely.
- `test_reconcile_embeds_orphan_chunks_and_drops_orphan_vectors` — round-trips a missing chunk and a leftover vector to an exact id match, and asserts idempotency.
- `test_no_delta_batch_records_the_hashes_it_verified` — a nested deleted path leaves the Merkle after a no-delta sync. **Confirmed to fail when the canonical-key fix is reverted.**

### `scripts/live_sync_probe.py` (new)
The end-to-end harness the report asked for. Registers a client so idle standby cannot stop the engine mid-test, waits for the embedder, writes a **unique** probe path per run, aborts if that path is already searchable, then polls `/health` and `/v1/search` and reports both criteria. Usage: `python scripts/live_sync_probe.py [repo] [engine-url]`.

### Version
`pyproject.toml` → `0.3.128`; added `packages/pipeline/upgrade_releases/v0_3_128.py` and registered it in `__init__.py`.

---

## 5. Verification

### Offline (before rebuild)
The dense-alignment diagnostic on the live store: old adapter mislabelled 198/400 hits and its `d_all` was length 7641 (tail chunk 7654 → `IndexError`); new adapter mislabelled **0**, `missing_vectors=147`, `d_all` length 7655 (tail safe).

### Unit / regression
- `tests/test_sync_corpus_alignment.py` — 4 passed.
- `test_storage_policy.py`, `test_locate_contract_bounds.py`, `test_vectordb.py` — all pass with the changes.
- Broader slice (`-k "search or dense or conductor or retriev or incremental or sync or chunk or engine or index or storage or vectordb or merkle"`): 277 passed, 2 skipped.

### Live, installed wheel 0.3.128
Real engine, real FastEmbed (CPU on this machine — DirectML unavailable), probe path unique and confirmed absent before the write:

```
baseline search does not contain packages/pipeline/sync_live_1790354474/f0.py
dirty accept in 184 ms
t+29s  hit=True   top=['packages/pipeline/sync_live_1790354474/f0.py', ...]
t+33s  chunks=7674 -> 7676, gen 2

health chunks increased (7674 -> 7676): True
search returned packages/pipeline/sync_live_1790354474/f0.py: True
```

The new file is the **rank-one hit**, 29 s after the write, and the chunk count moved by its two chunks. Reproduced across four consecutive runs.

### Store convergence (after the reconcile ran live)

| | before | after |
| --- | --- | --- |
| `chunks.jsonl` | 7655 | 7681 |
| `ids.npy` | 7642 | 7681 |
| tombstones | 1 | 0 |
| chunks with no vector | 147 | **0** |
| vectors with no chunk | 133 | **0** |
| `/health` `dense_missing` | — | **0** |

The keeper `no chunk delta` loop is gone. The dirty ledger drains to `published` with nothing stuck, and stale `sync_live*` Merkle entries are deleted instead of re-reported every poll.

### Installed-vs-source parity
Confirmed the six changed files in `%APPDATA%\uv\tools\scubiee\Lib\site-packages` are byte-identical (SHA256) to the source tree, so the live engine is running exactly what was tested.

---

## 6. Build / install recipe used

```
scubiee halt                       # release the Windows file lock first
Remove-Item -Recurse -Force dist
python -m build --wheel            # wheel built separately; combined build is unreliable here
uv tool install --reinstall "dist\scubiee-0.3.128-py3-none-any.whl"
scubiee engine ensure .            # bring the engine back up
python scripts\live_sync_probe.py .
```

---

## 7. Still open

- **Sync latency.** Per-batch sync is 10–20 s on this machine because FastEmbed runs on CPU (`DmlExecutionProvider not in available providers`). That is an environment problem, not a sync problem, but it sets the floor on time-to-searchable.
- **`_best_chunk` stale AST span** (bug 3b in `docs/scubiee-bugs-found.md`) is untouched — larger, riskier surface.
- **Four pre-existing test failures**, all confirmed to fail before this work (verified by stashing the changes):
  - `tests/test_live_reindexing.py::test_final_check_forces_held_publish`
  - `tests/test_mcp_agent_warm_retry.py::test_search_returns_warming_without_blocking_embedder`
  - `tests/test_mcp_lifecycle_universal.py::test_warm_engine_for_mcp_waits_for_embedder`
  - `tests/test_project_id.py::test_incremental_missing_graph_falls_back` — traces to uncommitted 0.3.115+ drift that added `or force_files` to the graph-rebuild condition.

## 8. Not yet committed / published

Nothing has been committed or pushed. When it goes onto a `release/0.3.128` branch, note that `incremental.py`, `engine.py`, `ce_service.py` and `architectures.py` still carry the 0.3.115–0.3.127 work that was published to PyPI but never committed, so that drift lands in the same commit.

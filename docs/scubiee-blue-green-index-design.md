# Design: make `scubiee index --force` never take the engine down

Addresses BUG-4 (forced reindex rewrites the store under the serving engine → crash →
demand-gated/crash-looped watchdog leaves it down) and BUG-2's "serve stale, no self-heal" by
borrowing the blue/green promote pattern that Elasticsearch, Redis OM, GitLab's knowledge-graph
(issue #877), and CodeGraph (issue #1798) use: *keep serving the current index while a new one is
built, then switch atomically.*

## What the code does today (verified)

- The store lives at a **fixed directory** `store.base = projects_root()/<project_id>` with
  hard-coded artifact names (`chunks.jsonl`, `merkle.json`, `meta.json`, `graph.json`,
  `graph_ir.json`, `embed_cache.jsonl`) plus a FAISS collection under the `VectorDatabase` root.
- `load_engine()` reads **those fixed paths directly**. There is **no pointer/alias** that names
  which directory to serve.
- `index_repo(force=True)` writes **in place** into `store.base`, overwriting those files while a
  warm `WarmSearchEngine` still holds them open. It never notifies the engine.
- `generation` is an in-memory counter (+ a `generation.json` cache-invalidation stamp for MCP
  workers). It does **not** select bytes on disk.
- Reload is explicit: `publish_engine()` → `load_engine(force_reload=True)`, swaps the in-memory
  binder, bumps `generation`, keeps the previous binder if the new load is empty.
- `cmd_index` = `register_project` + `index_repo` + return. **No `ensure_daemon`/restart handoff.**
- Existing safety primitives we can reuse: `atomic_write_text` (temp + `os.replace` w/ Windows
  retry), `publication_manifest.json` (checksum gate, `invalidate_manifest`→`publish_manifest`),
  `store_write_lock`.

## Two candidate designs

### Option A — Full blue/green generation directories (the "textbook" answer)
Build into `store.base/gen-<epoch>/`, then atomically promote by repointing an `active` pointer
(a `current.txt` / directory junction) that both `PipelineStore.base` resolution and `load_engine`
consult.

- Pros: textbook-clean; old generation served untouched during the whole rebuild; instant rollback.
- Cons: **large blast radius.** `store.base` is resolved in many places (`store.py`,
  `project_id.resolve_project`, `load_engine`, `artifact_guard`, the FAISS collection root, the
  keeper, MCP workers). Every one must learn the indirection. Windows junctions/symlinks need
  privilege handling. High risk against a repo with ~uncommitted changes and a live install. Not
  safe to land quickly.

### Option B — Decouple the forced reindex from the serving engine (RECOMMENDED, lower risk)
Keep the single fixed `store.base`, but fix the two real defects that make `index --force`
dangerous, using primitives that already exist:

1. **Build to a sibling staging dir, promote by atomic per-file replace.**
   `index_repo(..., stage=True)` writes all artifacts into `store.base/.staging-<pid>/`, then
   promotes each into `store.base` with the existing `atomic_write_text`/`os.replace` primitive
   under `store_write_lock`, wrapped by `invalidate_manifest` → (replace all) → `publish_manifest`.
   Readers that re-validate see either the old coherent manifest or the new one, never a torn mix.
   This removes the "half-written store under a live reader" window without any pointer indirection.
   - The FAISS collection is the one artifact `upsert_vectors` overwrites in place today; stage it
     to a temp collection name and swap the collection files the same way (rename under lock).

2. **Hand control back to a serving engine after promote.**
   `cmd_index` calls `publish_engine()` (same-process) or `ensure_daemon(root)` (CLI) after a
   successful index, so the engine reloads the freshly promoted generation instead of relying on
   the demand-gated / crash-loop-paused watchdog. The engine's `publish_engine` already keeps the
   previous binder if the new load is empty — so a bad rebuild can't blank search.

3. **During the rebuild, keep serving.** Because we no longer overwrite in place, the live binder
   keeps answering from the old files until promote + reload. That is the "serve stale while
   rebuilding, switch atomically" behavior from the research — achieved without directory swap.

- Pros: reuses `atomic_write_text` + manifest; no `store.base` indirection; no junction/privilege
  issues; small, testable surface; directly removes the crash cause and the silent-down.
- Cons: promote is per-file atomic (not a single-rename of a whole dir), so there's a brief
  multi-file window — but it's bounded by `store_write_lock` + the manifest invalidate/publish
  fence, which readers already honor (`index_is_usable`/`validate_manifest`). The FAISS swap is the
  fiddliest part.

## Recommendation

Go with **Option B**. It gets the same user-visible guarantees the research prescribes (engine stays
up, serves the old index during rebuild, switches cleanly) at a fraction of Option A's risk, and it
builds on primitives (`atomic_write_text`, `publication_manifest`, `store_write_lock`,
`publish_engine`, `ensure_daemon`) that already exist and are already tested.

### Phased delivery — ALL SHIPPED (0.3.143)
- **B1 ✅ `cmd_index` → `ensure_daemon` handoff.** After a successful index, ensure a serving engine
  (direct owner) + republish. Fixes the "engine left DOWN" symptom of BUG-4. Shipped in the first
  0.3.143 commit.
- **B2 ✅ stage-then-atomic-promote for text artifacts.** `index_repo_staged()` builds the whole
  generation into `store.base.parent/<name>.staging-<pid>/`; `artifact_guard.promote_staged_store()`
  flips it under one `store_write_lock(live)` with the invalidate→(swap)→replace→publish fence
  (`_PROMOTE_ARTIFACTS`). The live store is untouched for the whole build+embed phase.
- **B3 ✅ stage + atomic swap for the FAISS collection.** The staged build embeds into a temp
  collection (`<live>__staging_<pid>`); `VectorDatabase.swap_collection()` renames the live dir
  aside and `os.replace`s the staged dir into place (rollback on failure), run inside promote's lock
  so text + vectors land as one generation.
- **Wiring:** `cmd_index` uses the staged path when an engine is already serving (`is_running()`),
  else the simpler in-place index. Escape hatch: `CTX_INDEX_NO_STAGE=1`.

### Live verification (0.3.143)
`scubiee index --force` with the engine serving, polled `/health` every 3s for the whole rebuild:
**up=60, down=0**, `index_usable=true` throughout, grep answered on 28/30 mid-rebuild probes, then
generation advanced 1→2 (atomic promote) and the engine reloaded (`republished: true`). Before
B2/B3 the same test showed ~30 consecutive DOWN polls. Zero-downtime forced reindex achieved.

### Test plan
- Unit: a staged index writes into `.staging-*`, promote leaves a valid manifest; a crash between
  stage and promote leaves the *old* manifest valid (fail-closed, no mixed generation).
- Integration (live): start engine, run `index --force`, assert `/health` stays reachable
  throughout and `index_usable=true` before AND after, generation advances, a known symbol stays
  searchable during the rebuild.
- Regression: existing `test_incremental_confirm`, `test_live_reindexing`, `artifact_guard` tests
  stay green.

### Git-safety note
The repo has many uncommitted changes and a live install. B1 is a one-call, reversible edit. B2/B3
touch the index write path; implement behind a `stage=` flag defaulting to the current behavior
until the live integration test passes, so a bad promote can't brick the installed engine.

# Context Engine Questions Production-Readiness Design

**Status:** Approved in chat on 2026-08-17  
**Source checklist:** `questions.md` (preserved unchanged)  
**Deliverable:** `questions-answered.md`

## Goal

Resolve every question in `questions.md` with a locked product decision, matching
implementation, and executable evidence. A green answer means the behavior exists
and is covered; aspirations and skipped checks cannot be presented as complete.

## Evidence contract

Every answer uses four fields:

1. **Decision** — exact product behavior, including defaults and limits.
2. **Implementation** — concrete modules and public interfaces enforcing it.
3. **Verification** — named tests or runtime checks and their actual result.
4. **Status** — `resolved`, `partial`, or `not implemented`.

Before final delivery, all shipping-critical questions in sections 1–12 and 15
must be `resolved`. Optional dashboard presentation details may be `partial` only
when the underlying status data is complete and documented.

## Locked product model

### Repository lifecycle and Auto

- A **managed repository** is persistently registered and eligible for continuous
  synchronization until paused, marked never-index, or removed.
- `ctx initialize PATH` explicitly creates that persistent relationship and
  builds the first coherent index. Re-running it verifies/reconciles freshness;
  it does not force a rebuild.
- `ctx activate PATH` opens a repository for a client session. Auto activation
  happens only after a CE request supplies a workspace path, never merely because
  an IDE window opened.
- `ctx index` is a full build operation; `ctx sync` is incremental reconciliation;
  `ctx rebuild` discards/replaces derived index state.
- Large automatic discoveries are admitted by policy (size/file threshold and
  resource budget), with explicit initialization required when the threshold is
  exceeded.

### Identity and worktrees

- Canonical storage identity is a durable project ID persisted in the repository
  and global registry, with canonical real paths as aliases.
- Symlinks resolving to the same root map to one project.
- A moved repository reuses its durable ID when its `.context-engine/id.json`
  moves with it; registry aliases are updated.
- Git worktrees have separate indexes because their checked-out filesystem states
  differ. Their shared Git common directory is recorded as family metadata, not
  used as the index identity.

### Sessions and concurrency

- Index and dirty state are repository-global; navigation/session memory is
  session-specific.
- The filesystem is authoritative. Session attribution is metadata and never
  creates competing versions of repository truth.
- One `RepoRuntime` owns each active project. Multiple sessions attach to it.
- Expensive embedding is process-wide single-flight with fair priority:
  active search/write, recent write, then idle maintenance. Aging prevents
  starvation.
- Failures are isolated per runtime and cannot terminate the daemon.

### Freshness and search

- Native watcher events are hints. Debounced dirty state plus periodic Merkle
  reconciliation is authoritative and recovers dropped/overflowed events.
- Rename/atomic-save bursts collapse into one quiet-window update. Writes during
  indexing schedule a follow-up pass.
- Storms (including branch checkout) are capped and marked `needs_full`; they do
  not enqueue unbounded per-file work.
- Search remains available from the last coherent generation. Changed files get
  lexical/graph overlay visibility before dense publication, and status reports
  `overlay_ready` / `dense_pending`.
- Maximum normal stale target is five seconds after the final write; resource
  deferral and storm states must be explicit rather than violating the target
  silently.

### Publication and recovery

- Dirty state is journaled durably and replayed after restart.
- Artifact writes are same-directory atomic replacements.
- A checksum publication manifest is the readiness boundary. Readers never claim
  a mixed generation ready.
- If the journal is missing, Merkle reconciliation reconstructs dirty state.
- A failed dense phase preserves the prior coherent generation and reports
  `dense_pending` or `error`.

### Storage

- Replaced/deleted chunks are removed from logical payloads and vector mappings in
  the same publication.
- Because FAISS removal does not guarantee process RSS reclamation, CE tracks dead
  ratio and periodically rebuilds/serializes a compact collection.
- Repository stores expose byte usage, last access, lifecycle, and reclaimable
  bytes. Explicitly removed stores can be deleted immediately; automatic
  eviction uses least-recently-active non-pinned repositories.

### Runtime resources

- Hardware detection selects CUDA, DirectML, or CPU FastEmbed/ONNX Runtime and
  persists the measured profile and safe batch.
- Preflight verifies the selected provider is actually available. A configured
  accelerated profile cannot silently fall back to PyTorch CPU.
- Resource pressure may reduce batches or pause indexing while serving the last
  coherent search generation.
- The daemon and lexical/graph resources stay alive; the embedding model may be
  unloaded after configurable inactivity and warmed on demand.
- Watchdog restores the daemon after reboot/process failure; wake/restart triggers
  registry recovery and Merkle reconciliation.

### Client and user control

- Clients must provide a workspace path. Client name is optional telemetry and
  does not alter index semantics.
- Client paths canonicalizing to one project share its runtime/index.
- CE only writes client configuration during explicit setup/install commands.
- Auto authorization follows user preferences; never-index always wins.
- User controls include initialize, activate, pause, resume, sync-now, rebuild,
  remove, never-index, exclusions, and managed-repository listing.

### Observability

The status surface must expose per repository:

- lifecycle and readiness state;
- last indexed, last changed, and last search times;
- dirty paths/chunks and currently processed files;
- overlay/dense/full-rebuild state;
- embed queue position and scheduler holder;
- pause/defer/error reason;
- index bytes and reclaimable bytes;
- attached sessions and runtime priority.

## External technical basis

- ONNX Runtime provider selection is verified with runtime provider APIs and a
  real model/session warm-up, not package presence alone.
- Windows `ReadDirectoryChangesW` discards buffered detail on overflow; directory
  enumeration/Merkle reconciliation is therefore mandatory.
- Git worktree shared metadata is discovered using `git rev-parse
  --path-format=absolute --git-common-dir`; worktree filesystem roots remain
  distinct index identities.
- FAISS `remove_ids` behavior varies by index type and does not guarantee memory
  return to the OS; periodic collection rebuild is the portable compaction path.

## Acceptance criteria

1. All original questions appear in `questions-answered.md` with no placeholders.
2. Lifecycle, multi-repo runtime, fairness, durable journal, storage policy, and
   observability contracts have deterministic tests.
3. Real provider/batch preflight passes on the current DML machine.
4. Core and fault tiers include the new contracts and pass.
5. Full repository tests are run; failures are fixed or explicitly classified
   with reproduction evidence.
6. `ctx certify .` has zero required failures and does not count skipped checks
   as proof.
7. The original `questions.md` and existing production-certification plan remain
   unchanged.

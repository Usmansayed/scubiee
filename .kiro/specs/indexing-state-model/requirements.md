# Requirements — Unified Indexing & State-Management Model

## Introduction

Scubiee's indexing, change-detection, recovery, and lifecycle logic grew case-by-case. Detection ("what changed"), workload sizing / lane selection ("how big, how urgent"), and engine lifecycle ("is the process up") are entangled across `sync_loop.py`, `incremental.py`, `freshness.py`, and `lifecycle_runtime.py`. This produces recurring edge-case bugs (delete latency, rename, offline-change loss risk) that each need a new patch.

This spec defines one durable state model so the engine, on coming back online, always understands the repository's true state and recovers automatically — without the user or agent manually triggering indexing. It separates the three concerns, adds the missing durable records, and makes the agent-facing "pending" signal meaningful (surfaced only for genuinely substantial, minutes-scale work).

The system already has strong primitives to build on: `merkle.json` (content baseline), `dirty_journal.json` (crash-replayable work queue), `publication_manifest.json` (coherence fence), `generation.json` (cache token), and blue/green staging (`promote_staged_store`). This spec fills the confirmed gaps rather than rewriting these.

### Confirmed gaps this spec closes
1. No boot-time offline reconciliation — offline edits are caught only lazily by a background poll.
2. No durable "index build in progress" marker — crash-mid-index recovery is inferred, not recorded.
3. No workload/time estimate exposed — the agent sees noisy `dirty_count` and a binary `needs_full`, never "small vs minutes".
4. Detection, sizing, and lifecycle are entangled, so edge-case fixes perturb each other.

### Non-goals
- No change to the retrieval/dense path, ranking, or the map/find/focus tool surface.
- No change to the embedding model or vector store format.
- Not a rewrite of merkle/journal/manifest primitives — they are reused.

---

## Glossary
- **Drift** — difference between the working tree and the published generation's `merkle.json` (added/modified/removed files).
- **Generation** — a coherent published set of artifacts (chunks + vectors + graph + manifest). Advances atomically.
- **Build-intent record** — durable note that an index/sync build is in flight, with enough detail to detect interruption and resume.
- **Substantial** — pending work whose estimated indexing time crosses a wall-clock budget (minutes-scale), vs small work that is handled silently.
- **Reconciler** — the single detect → enqueue → classify entry point.

---

## Requirements

### R1 — No repository change is ever silently lost
**User story:** As a user, I want every change I make — while the engine is on, off, or mid-index — to eventually be indexed, so search never silently misses my code.

Acceptance (EARS):
1. WHEN a file is added, modified, deleted, renamed, or moved while the engine is running THEN the change SHALL be recorded in the durable dirty journal before the engine reports that work settled.
2. WHEN a change is recorded in the dirty journal THEN it SHALL remain queued until it is either indexed (published) or superseded by a newer change to the same path.
3. IF the engine process crashes with queued or in-progress work THEN on restart the system SHALL re-derive that work from the durable journal and/or a working-tree-vs-merkle drift scan and re-enqueue it.
4. WHEN the same file is changed multiple times before indexing completes THEN only the final content SHALL be embedded, and no intermediate change SHALL cause a lost or stale final state.

### R2 — Offline changes are detected and recovered automatically on startup
**User story:** As a user, I want changes I made while the engine was off (even days ago, even with no MCP client) to be detected and indexed as soon as the engine starts, without me triggering anything.

Acceptance (EARS):
1. WHEN the engine starts THEN before it reports the index as write-current it SHALL run reconciliation that diffs the working tree against the persisted `merkle.json` and enqueues all drift into the durable journal.
2. WHEN startup reconciliation enqueues drift THEN indexing of that drift SHALL begin as soon as the engine is warm, REGARDLESS of whether an MCP client is connected.
3. WHEN the indexed git HEAD differs from the current HEAD at startup THEN reconciliation SHALL use the git diff to scope drift (branch switch / rebase / pull detection).
4. IF a folder of many files was added while the engine was off THEN startup reconciliation SHALL detect all of them as drift (not only files whose parent folder mtime moved).
5. WHEN a client connects after offline changes accumulated THEN the system SHALL already have the drift enqueued (or in progress) and SHALL expose accurate pending state immediately, requiring no manual trigger.

### R3 — Interrupted or crashed indexing resumes safely
**User story:** As a user, if indexing is interrupted (process killed, computer shut down), I want the engine to resume the remaining work on restart without redoing everything and without serving a corrupt index.

Acceptance (EARS):
1. WHEN a full or bulk index build starts THEN the system SHALL write a durable build-intent record (build id, pid, kind, staging dir, estimated and completed work units) before mutating staging.
2. WHEN a build-intent record exists on startup AND its owner pid is not alive THEN the system SHALL classify the index state as INTERRUPTED, discard the dead-pid staging artifacts, and resume only the remaining (uncommitted) work.
3. WHEN a build commits a generation THEN the build-intent record SHALL be cleared only after the publication manifest for the new generation is published.
4. IF the process crashes between a vector write and a chunk write (or vice versa) THEN on next open the system SHALL heal the drift (re-embed orphan chunks, drop stale vectors) rather than serve the inconsistency.
5. The system SHALL NEVER serve a torn or mixed generation: a half-written generation SHALL fail the manifest coherence check and fail closed.

### R4 — MCP connection state never drives indexing correctness
**User story:** As a user, I want indexing correctness to be independent of whether an MCP client is connected, so closing or opening my editor never loses or corrupts index state.

Acceptance (EARS):
1. WHEN there is pending index work AND the engine is running THEN the system SHALL process that work whether or not an MCP client is connected.
2. WHEN an MCP client connects THEN the system SHALL run one reconciliation pass so pending state is accurate immediately; connecting SHALL NOT be required to start indexing.
3. WHEN the last MCP client disconnects THEN idle-stop SHALL be blocked while the index state is INDEXING, RECONCILING, or INTERRUPTED, so substantial work completes before the engine stops.
4. WHEN the engine stops THEN it SHALL persist the index state so the next start resumes from it.
5. Keeper scheduling politeness (deferring the heavy interval walk while a client is mid-request) SHALL remain, but SHALL NOT be a correctness gate — hot/poll producers still run.

### R5 — The engine always knows indexed-vs-pending (single source of truth)
**User story:** As a developer, I want one authoritative, durable record of index state so recovery and reporting don't depend on inferring from scattered files.

Acceptance (EARS):
1. The system SHALL maintain a durable per-project `index_state.json` recording: index state, generation (durable epoch + counter), indexed git HEAD, the merkle root the generation matches, any in-flight build record, and the pending summary.
2. WHEN any index state transition occurs THEN `index_state.json` SHALL be written atomically.
3. The `merkle.json` and `publication_manifest.json` SHALL advance only together, only on a committed generation, under the store write lock.
4. The durable generation counter SHALL be monotonic within an epoch; a late-finishing older publish SHALL NOT move it backward.
5. The index state SHALL be derivable/verifiable from the combination of merkle + journal + manifest, so a lost or corrupt `index_state.json` degrades gracefully (treated as "unknown → reconcile") rather than failing.

### R6 — Small changes are silent; only substantial work is surfaced
**User story:** As an agent, I want to be told about pending indexing only when it could realistically take minutes, so I'm not interrupted by every small edit.

Acceptance (EARS):
1. The system SHALL classify pending work by estimated indexing cost (estimated chunks to embed, weighted by file type, using exact chunk counts for existing files and a line-based estimate for new files) converted to estimated wall-clock seconds via a measured embed throughput.
2. The system SHALL classify work as SUBSTANTIAL IF the estimated time crosses a configurable budget (default ~20-30s), OR a full/forced reindex is required, OR drift covers at least a large configurable fraction of the corpus.
3. WHEN changes are small (below the budget) THEN the system SHALL handle them silently and SHALL NOT surface a pending signal to the agent.
4. The threshold SHALL be a wall-clock time (self-adjusting to machine speed), NOT a fixed file count.
5. IF embed throughput has not yet been measured THEN the system SHALL use a conservative default throughput.

### R7 — The agent receives actionable pending state, not noise
**User story:** As an agent, when there is substantial pending work I want a concise, actionable signal (reason, ETA, whether search still works), not a progress bar or per-file notifications.

Acceptance (EARS):
1. WHEN index state is RECONCILING (substantial) THEN the status/gate contract SHALL include a `pending` object with: substantial=true, reason, estimated_seconds, done/total units, and whether search is usable on the current generation.
2. WHEN index state is FRESH, STALE (small), or INDEXING (small) THEN the contract SHALL NOT include a `pending` object (silent).
3. WHEN a full reindex is required (over the hard cap) THEN the `pending` object SHALL include an actionable `action` field (e.g. the explicit index command).
4. The agent-facing contract SHALL NOT expose a raw per-change `dirty_count` as the pending signal.
5. WHEN search is usable on the current generation during reconciliation THEN the contract SHALL indicate search remains usable, so the agent can proceed rather than block.

### R8 — Unified reconciler decouples detection from execution and lifecycle
**User story:** As a developer, I want change detection, workload classification, and work execution to be separate concerns so fixing one does not break another.

Acceptance (EARS):
1. The system SHALL have one reconciliation entry point that performs detect → enqueue → classify and is idempotent across repeated calls.
2. The reconciler SHALL be invoked at engine start, on client connect, and from the periodic poll, reusing the existing detectors (git fast-path, merkle-leaf verify, newcomer walk) internally.
3. The reconciler SHALL enqueue drift into the durable journal and set index state + pending summary, but SHALL NOT itself select hot/bulk lanes — execution lanes consume the queue separately.
4. Lane selection (hot vs bulk vs full) SHALL read the classified index state rather than re-deriving change size independently.
5. Changing detection logic SHALL NOT require changing execution-lane logic, and vice versa.

### R9 — Correct behavior across the full scenario matrix
**User story:** As a user, I want every realistic sequence of engine/client/file/git events to produce the correct, documented outcome.

Acceptance (EARS):
1. WHEN a file is deleted (engine on, client connected) THEN search SHALL stop returning it within a bounded, consistent time, and the behavior SHALL NOT depend on an unrelated concurrent save beyond a documented bound.
2. WHEN a file is renamed/moved THEN the old path SHALL be pruned and the new path indexed, with both reflected within the documented bound.
3. WHEN files change while the engine is off and it starts hours/days later THEN R2 behavior SHALL hold.
4. WHEN a git branch switch/rebase/checkout occurred (on or off) THEN drift SHALL be scoped via git diff and reconciled.
5. WHEN the index store is wiped but merkle remains THEN the whole universe SHALL be treated as drift (full reindex).
6. Each scenario in the design's scenario matrix (A1–A7, B1–B2, C1–C6, D1–D4, E1–E3) SHALL have a documented expected outcome and a corresponding test or verified manual check.

### R10 — Safe, incremental rollout with no regressions
**User story:** As a maintainer, I want this delivered in independently-shippable steps that don't destabilize the working engine.

Acceptance (EARS):
1. Each implementation step SHALL be independently shippable and covered by tests before the next begins.
2. The new state model SHALL layer on existing primitives; no step SHALL require touching the retrieval/dense path.
3. WHEN a step ships THEN the existing scenario tests (add/edit/delete/rename/burst/batch/hot-query/revert) SHALL continue to pass.
4. Each new durable record SHALL be backward-compatible: a missing or old-version file SHALL be handled as "reconcile from scratch", never a crash.
5. The full offline unit suite SHALL pass (excluding pre-existing environment-only failures) after each step.

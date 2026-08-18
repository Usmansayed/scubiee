# Questions Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every answer in `questions.md` correspond to an enforced, tested
Context Engine behavior and publish the evidence in `questions-answered.md`.

**Architecture:** A persistent repository registry feeds isolated `RepoRuntime`
instances managed by one `RepoHub`. Repository-global dirty state is journaled and
reconciled by Merkle state; a fair process-wide embed scheduler controls the
hardware-selected FastEmbed worker. Coherent artifact manifests remain the reader
boundary, while lifecycle, storage, and queue details are exposed through doctor,
status, and certification.

**Tech Stack:** Python 3.13, pytest, FAISS/TurboQuant, FastEmbed, ONNX Runtime
CUDA/DirectML/CPU providers, HTTP daemon, MCP phase surface.

## Global Constraints

- Preserve `questions.md` and
  `docs/superpowers/plans/2026-08-17-production-certification.md`.
- The filesystem is repository truth; sessions only add attribution/context.
- Git worktrees use separate indexes even when `--git-common-dir` is shared.
- Watcher events are hints; Merkle reconciliation is authoritative.
- No accelerated profile may silently fall back to PyTorch CPU.
- No readiness response may expose a mixed or checksum-invalid generation.
- Routine tests are local/deterministic; hardware, client, and destructive labs
  remain explicit but cannot be counted as passing when skipped.

---

### Task 1: Lifecycle and durable repository identity

**Files:**
- Create: `packages/pipeline/repo_lifecycle.py`
- Modify: `packages/pipeline/project_id.py`
- Modify: `packages/pipeline/registration.py`
- Modify: `packages/pipeline/__main__.py`
- Create: `tests/test_repo_lifecycle.py`

**Interfaces:**
- `managed_state(root: Path) -> str`
- `initialize_repo(root, *, index=True, always_allow=True) -> dict`
- `activate_repo(root) -> dict`
- `pause_repo`, `resume_repo`, `sync_now_repo`, `rebuild_repo`,
  `remove_repo`, `never_index_repo`
- `list_managed_repos() -> list[dict]`
- `git_common_dir(root: Path) -> Path | None`

- [ ] Write tests for repeat initialize, symlink aliasing, moved durable ID,
  separate linked-worktree project IDs, pause/resume, never-index precedence,
  and remove-with/without store deletion.
- [ ] Run `pytest tests/test_repo_lifecycle.py -q`; verify failures identify
  missing lifecycle interfaces.
- [ ] Implement lifecycle transitions in the global registry with atomic registry
  writes and timestamps (`initialized_at`, `last_activated_at`, `last_access_at`).
- [ ] Add CLI commands and explicit JSON results.
- [ ] Run lifecycle and project identity tests.

### Task 2: Multi-repository runtime and fair embedding

**Files:**
- Create: `packages/pipeline/repo_runtime.py`
- Create: `packages/pipeline/fair_schedule.py`
- Modify: `packages/pipeline/ce_service.py`
- Modify: `packages/pipeline/resources.py`
- Create: `tests/test_multi_repo_runtime.py`

**Interfaces:**
- `RepoRuntime(project_id, repo)` owns engine, keeper, sessions, activity,
  error, generation, and priority.
- `RepoHub.ensure(root)`, `get(project_id)`, `drop(project_id)`,
  `list_status()`, `isolate_failure(project_id, error)`.
- `FairEmbedScheduler.acquire(project_id, priority, timeout_s)`,
  `release(project_id)`, and `hold(...)`.

- [ ] Write tests proving same-repo sessions share a runtime, different repos
  retain independent engines/keepers, active work outranks idle work, equal
  priority is fair, aging prevents starvation, and one repo failure is isolated.
- [ ] Run tests and verify they fail before implementation.
- [ ] Replace the single mutable runtime facade with `RepoHub`-backed activation
  while retaining API compatibility for the active repository.
- [ ] Wrap expensive embed jobs in the fair scheduler; never hold the scheduler
  while waiting for filesystem debounce.
- [ ] Run runtime, server, resource, and concurrent search tests.

### Task 3: Durable dirty journal and freshness contract

**Files:**
- Create: `packages/pipeline/dirty_journal.py`
- Create: `packages/pipeline/sync_status.py`
- Modify: `packages/pipeline/sync_loop.py`
- Modify: `packages/pipeline/incremental.py`
- Create: `tests/test_sync_status_canaries.py`

**Interfaces:**
- `JournalingLedger(project_id, ...)`
- `save_dirty_journal`, `load_dirty_journal`,
  `restore_ledger_from_journal`, `clear_dirty_journal`
- `derive_sync_status(...) -> ready|syncing|overlay_ready|dense_pending|
  deferred|needs_full|error`

- [ ] Write tests for crash after mark/begin/overlay, journal corruption,
  journal loss plus Merkle recovery, rewrite during indexing, branch storm cap,
  and five-second normal stale-window status.
- [ ] Implement same-directory atomic journal writes and replay all non-published
  paths as immediately due.
- [ ] Make keeper startup restore journal before accepting dirty events.
- [ ] Ensure incremental publication refreshes checksums only after all artifacts
  are coherent; failed dense work preserves the prior generation.
- [ ] Run dirty ledger, live reindexing, runtime publish, and canary tests.

### Task 4: Watcher overflow, sleep/wake, and daemon recovery

**Files:**
- Modify: `packages/pipeline/sync_loop.py`
- Modify: `packages/pipeline/watchdog.py`
- Modify: `packages/pipeline/daemon.py`
- Create: `tests/test_watcher_recovery.py`

**Interfaces:**
- `BackgroundSyncLoop.reconcile(reason: str) -> dict`
- `BackgroundSyncLoop.note_watcher_overflow()`
- watchdog status includes restart count, last wake/reconcile, and last error.

- [ ] Write deterministic tests for event overflow, atomic save rename burst,
  watcher unavailable, sleep/time jump, reboot registry recovery, and 5,000-event
  storm bounded to configured batch size.
- [ ] Treat overflow/unknown watcher failure as `needs_full` plus immediate Merkle
  enumeration, matching Windows `ReadDirectoryChangesW` requirements.
- [ ] Detect monotonic wall-time gaps and reconcile active managed repositories.
- [ ] Keep searches available from the last coherent generation while sync pauses.
- [ ] Run watcher, watchdog, daemon, and freshness tests.

### Task 5: Chunk deletion, vector compaction, and storage policy

**Files:**
- Create: `packages/pipeline/storage_policy.py`
- Modify: `packages/pipeline/vectordb.py`
- Modify: `packages/pipeline/incremental.py`
- Modify: `packages/pipeline/project_id.py`
- Create: `tests/test_storage_policy.py`

**Interfaces:**
- `repo_storage_status(project_id) -> dict`
- `compact_collection(project_id, *, force=False) -> dict`
- `collect_unused_repos(*, max_bytes, inactive_days, dry_run=True) -> dict`

- [ ] Write tests for removed chunk cleanup across chunks/BM25/graph/FAISS
  payloads, stable IDs after deletion, dead-ratio compaction, disk accounting,
  pinned managed repositories, LRU eviction candidates, and dry-run safety.
- [ ] Implement explicit-ID-safe collection rebuild rather than relying on
  sequential FAISS ID shifting.
- [ ] Track live/dead vector counts and compact after a configurable threshold.
- [ ] Expose store bytes and reclaimable bytes in lifecycle/status output.
- [ ] Run vector DB, incremental, storage, and corruption tests.

### Task 6: Auto admission, client/session metadata, and observability

**Files:**
- Modify: `packages/pipeline/server.py`
- Modify: `packages/pipeline/client.py`
- Modify: `packages/pipeline/ce_service.py`
- Modify: `packages/pipeline/dashboard.py`
- Modify: `packages/pipeline/session_store.py`
- Create: `tests/test_auto_sessions_observability.py`

**Interfaces:**
- Requests carry `path`, optional `client`, and optional `session_id`.
- Auto admission returns `activated`, `requires_initialize`, `paused`, or
  `never_index`.
- Status reports lifecycle, sessions, dirty/pending counts, scheduler queue,
  current files, pause reason, timestamps, and storage bytes.

- [ ] Write tests for 20 discovered repos, large-repo admission refusal,
  same-repo multi-client sharing, session-specific attribution, session end while
  another remains, never-index authorization, and complete status fields.
- [ ] Require explicit workspace paths for repository operations.
- [ ] Add configurable Auto limits without evicting explicitly initialized repos.
- [ ] Expand status/API data before changing dashboard presentation.
- [ ] Run API, session, MCP, lifecycle, and status tests.

### Task 7: Certification coverage and real scenario gates

**Files:**
- Modify: `packages/pipeline/certify.py`
- Modify: `packages/pipeline/test_runner.py`
- Modify: `tests/test_production_scenarios.py`
- Modify: `docs/reindexing/production-operator-runbook.md`

**Interfaces:**
- Required certification checks cover lifecycle, runtime isolation, journal
  replay, provider warm-up, watcher recovery, and publication coherence.

- [ ] Replace placeholder/skipped deterministic scenarios with real temp-home
  simulations for disk denial, permission denial where supported, dirty restart,
  two-repo isolation, and provider mismatch.
- [ ] Ensure skipped checks remain neutral and never increase passed count.
- [ ] Add all new contract tests to the core/fault tiers.
- [ ] Run `ctx test quick`, `core`, `fault`, and `ctx certify .`.

### Task 8: Answer every checklist question and final verification

**Files:**
- Create: `questions-answered.md`

**Interfaces:**
- One heading per original section and one numbered answer per original question.
- Each answer contains Decision, Implementation, Verification, and Status.

- [ ] Copy every question from `questions.md` in order without changing the source.
- [ ] Answer from implemented contracts and cite authoritative external sources
  for ONNX Runtime providers, watcher overflow, Git worktrees, and FAISS deletion.
- [ ] Scan for `TBD`, `TODO`, “not sure”, unanswered numbering, and unsupported
  `resolved` claims; none may remain.
- [ ] Run the full repository pytest suite.
- [ ] Run core, fault, doctor, daemon binding, provider microbenchmark, and
  certification.
- [ ] Record exact pass/fail/skip counts and date in `questions-answered.md`.

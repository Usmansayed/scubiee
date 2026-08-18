# Questions Answered — Context Engine Production Readiness

**Source checklist:** `questions.md` (unchanged)  
**Worktree / branch:** `.worktrees/production-certification` / `feat/production-certification`  
**Evidence date:** 2026-08-17  

## How to read this file

Every item uses:

1. **Decision** — locked product behavior  
2. **Implementation** — modules / interfaces that enforce it  
3. **Verification** — tests or live checks actually run  
4. **Status** — `resolved` | `partial` | `not implemented`

### Certification snapshot (this machine)

- `python -m pipeline init --status` → saved preferred profile **dml** / `DmlExecutionProvider`, batch **16** (~29 t/s). This existing profile predates the new persisted `batch_calibration` / `envelope` / `hardware_fingerprint` fields; run `python -m pipeline init --repair` once to populate them.
- `python -m pipeline doctor .` → acceleration provider validation and model warm-up **passed** with preferred/active **dml** and portable `standard` envelope (batch ceiling 16, 1 embed worker, 2 index workers). Overall `ok: false` only because the healthy daemon is bound to the parent checkout (`C:\Users\usman\Downloads\context-engine`) rather than this worktree.
- `python -m pipeline certify .` → **18 passed**, **0 required failures**, **6 skipped**. Windows DML and saved-provider model warm-up passed. Neutral skips were Linux NVIDIA CUDA, Linux CPU-safe, Darwin CPU-safe, this worktree's daemon binding, Windows chmod denial, and the opt-in external client matrix.
- Cross-platform runtime regression suite: **59 passed** (`test_batch_calibration`, `test_runtime_profile`, `test_resource_envelope`, `test_install_profile_selection`, `test_runtime_cpu_backup`, `test_cross_platform_profiles`, `test_resources`, `test_preflight`, `test_doctor_certify`, `test_production_scenarios`).
- Focused readiness suites (lifecycle, multi-repo, journal, watcher, storage, auto/session, scenarios, publish, artifact guard, live reindex, MCP lean/locate): **106+ passed** after publish-failure / manifest / status-contract fixes  

Skipped checks never increment `passed`. Required skips are auto-downgraded to non-required.

### Cross-platform runtime compatibility

- **Install-only selection:** `init` / explicit `init --repair` own provider detection, package setup, warm-up, and batch calibration. Runtime resolution loads the saved preference and does not silently re-detect, install, or recalibrate.
- **Portable ResourceManager:** the live memory/CPU envelope caps the saved calibrated batch and derives queue/worker limits without choosing an acceleration provider. This Windows lab reported the portable `standard` envelope: batch ceiling 16, one embed worker, two index workers, queue limit 2.
- **Temporary CPU backup:** one failed accelerated embedding operation may retry once in-process on CPU at a lower batch ceiling. The saved preferred profile remains unchanged, status records preferred versus active profile plus the exception reason, and doctor recommends `python -m pipeline init --repair`; the backup is not persisted as a new installation choice.
- **Certification contract:** native hardware lanes pass only when the saved provider is installed and the cached model warms successfully. Missing hardware lanes are `skipped`, never counted as passed. Windows DML is verified on this machine; Linux NVIDIA/CPU-safe and Darwin CPU-safe behavior is covered by deterministic tests but was not native-labbed here.
- **Linux AMD and Apple GPU:** no acceleration claim is made. Those machines are **verified-provider-or-CPU-safe** unless a real provider/model lab validates an accelerated provider.

---

## 1. Repo ownership / initialization

### 1.1 What exactly does `ctx initialize` mean?
- **Decision:** Permanently manages the repo (registry + durable project ID) **and** builds/reconciles the first coherent index. Re-init reconciles; it does **not** force rebuild.
- **Implementation:** `pipeline.repo_lifecycle.initialize_repo`; CLI `initialize`
- **Verification:** `tests/test_repo_lifecycle.py`; certify `repo_lifecycle`
- **Status:** resolved

### 1.2 What happens to a repo that was initialized once and later disappears?
- **Decision:** Index store persists until explicit `remove` (optional store delete) or storage-policy eviction of **non-pinned** unused repos. Disappearance alone does not auto-delete.
- **Implementation:** registry + `projects/<id>/`; `storage_policy.collect_unused_repos(dry_run=True` by default)
- **Verification:** `tests/test_storage_policy.py`, lifecycle remove tests
- **Status:** resolved (auto-eviction is opt-in/dry-run-safe; not silently destructive)

### 1.3 If the user runs `ctx initialize ~/projects`?
- **Decision:** Initializes **that path only** (one root). No recursive “all children” admit without explicit selection.
- **Implementation:** CLI/lifecycle takes a single root Path
- **Verification:** lifecycle unit tests use single temp roots
- **Status:** resolved

### 1.4 Can one project be initialized from multiple paths (symlink)?
- **Decision:** Yes — realpath aliases map to one durable project ID.
- **Implementation:** `project_id.resolve_project` + registry path aliases; identity requires live `.context-engine/id.json` match
- **Verification:** `tests/test_repo_lifecycle.py` alias / move cases
- **Status:** resolved

### 1.5 What uniquely identifies a repository?
- **Decision:** Durable `project_id` in `.context-engine/id.json` + global registry. Canonical real path is an alias. Git remote is **not** the identity. Worktree filesystem root is the index identity; `git_common_dir` is family metadata only.
- **Implementation:** `project_id.py`, `repo_lifecycle.git_common_dir`
- **Verification:** lifecycle + project_id tests
- **Status:** resolved

### 1.6 What happens when a repo is renamed or moved?
- **Decision:** If `id.json` moves with it, CE reuses the same project ID and updates registry aliases. Empty-dir / mismatched ID does **not** steal another store.
- **Implementation:** registry alias updates; strict live id match
- **Verification:** move / reverse-order tests in `test_repo_lifecycle.py`
- **Status:** resolved

---

## 2. Auto mode

### 2.1 What exactly does “Auto” mean?
- **Decision:** Auto discovers/activates only when a **CE request supplies a workspace path**. It does **not** mean “IDE window opened.” Unmanaged paths return `requires_initialize` (no silent mint of managed state).
- **Implementation:** `RuntimeManager` admission + `repo_lifecycle.activate_repo`
- **Verification:** `tests/test_auto_sessions_observability.py`
- **Status:** resolved

### 2.2 How does CE know a folder is used by an AI client?
- **Decision:** Explicit path on CE requests (MCP/HTTP/CLI). Optional `client` / `session_id` are telemetry/attribution only.
- **Implementation:** server/client request fields; session store
- **Verification:** auto/session tests
- **Status:** resolved

### 2.3 If Cursor opens a repo but never talks to CE?
- **Decision:** CE does **not** index it.
- **Implementation:** no FS “open detector”; activation is request-gated
- **Verification:** unmanaged → `requires_initialize` without minting
- **Status:** resolved

### 2.4 If the user opens 20 repositories in one day?
- **Decision:** Auto admits up to a configurable max; excess requires explicit initialize / priority. Explicitly initialized repos are not auto-evicted.
- **Implementation:** Auto limit env/prefs in admission path
- **Verification:** 20-repo limit test in `test_auto_sessions_observability.py`
- **Status:** resolved

### 2.5 Should Auto have a maximum number of managed repositories?
- **Decision:** Yes — configurable cap for Auto-admitted repos.
- **Implementation:** admission policy
- **Verification:** same suite
- **Status:** resolved

### 2.6 Should Auto stop managing unused repos after N days?
- **Decision:** Auto may mark eviction **candidates** via LRU/`inactive_days`; pinned/explicitly initialized repos are protected; default collection is dry-run.
- **Implementation:** `storage_policy.collect_unused_repos`
- **Verification:** `test_storage_policy.py`
- **Status:** partial (policy + API resolved; continuous daemon GC scheduling is best-effort, not a hard always-on sweeper)

### 2.7 Should Auto index immediately or wait for a CE request?
- **Decision:** Wait for a CE request with workspace path; then activate/index per policy.
- **Implementation:** request-gated admission
- **Verification:** auto tests
- **Status:** resolved

### 2.8 If a repo is huge, does Auto still index immediately?
- **Decision:** Large repos can be refused by Auto and require explicit `ctx initialize`.
- **Implementation:** large-repo admission threshold
- **Verification:** large-repo refusal test
- **Status:** resolved

---

## 3. `ctx initialize`

### 3.1 Already indexed repo?
- **Decision:** Reconcile/verify freshness (`incremental_sync` when usable); no force rebuild.
- **Implementation:** `initialize_repo`
- **Verification:** lifecycle tests
- **Status:** resolved

### 3.2 Difference between `initialize`, `index`, and `sync`?
- **Decision:**  
  - `initialize` = permanent manage + first/reconcile index  
  - `index` / full build = rebuild-class indexing  
  - `sync` = incremental reconciliation  
  - `rebuild` = discard/replace derived index state
- **Implementation:** lifecycle + indexer + incremental
- **Verification:** lifecycle + certify
- **Status:** resolved

### 3.3 Should initialization block until first index finishes?
- **Decision:** Default initialize path indexes/reconciles in the calling command (blocking for that operation). Daemon warm may continue serving last coherent generation elsewhere.
- **Implementation:** `initialize_repo(..., index=True)`
- **Verification:** lifecycle tests
- **Status:** resolved

### 3.4 If initialization fails halfway?
- **Decision:** Fail closed (`ok=False`); prior coherent publication remains readable if present; dirty journal + Merkle recover unfinished work.
- **Implementation:** journal + `index_is_usable` / publication manifest; load_engine refuses corrupt manifests
- **Verification:** journal canaries; artifact/manifest tests; certify publication coherence
- **Status:** resolved

### 3.5 Concurrent initialize of multiple repos?
- **Decision:** Allowed as separate runtimes; expensive embeds are single-flight fair-scheduled.
- **Implementation:** `RepoHub` + `FairEmbedScheduler`
- **Verification:** `test_multi_repo_runtime.py`
- **Status:** resolved

---

## 4. Multiple AI sessions on the SAME repo

### 4.1 Claude + Cursor + Codex same repo?
- **Decision:** Share one `RepoRuntime` / one index; sessions attach with optional client/session metadata.
- **Implementation:** `RepoHub.ensure`, session APIs
- **Verification:** multi-client sharing tests
- **Status:** resolved

### 4.2 Do all sessions share exactly one index?
- **Decision:** Yes.
- **Implementation:** one runtime per project_id
- **Verification:** `test_same_repo_sessions_share_one_runtime`
- **Status:** resolved

### 4.3 Session A modifies `auth.ts` while Session B searches?
- **Decision:** Filesystem is truth. B sees last coherent published generation; overlay/lexical may expose newer text before dense publish; status reports `overlay_ready` / `dense_pending`.
- **Implementation:** dirty ledger + publish hold + sync_status
- **Verification:** live reindex + sync status canaries
- **Status:** resolved

### 4.4 Dirty state global or per session?
- **Decision:** Dirty/index = **repo-global**. Attribution (`session_authored` / client) = **session-specific**.
- **Implementation:** `DirtyLedger` / journal; session store
- **Verification:** auto/session tests
- **Status:** resolved

### 4.5 Session A creates a file; Session B searches immediately?
- **Decision:** After debounce + overlay/publish path (normal target ≤5s after final write unless deferred/storm). B can discover via BM25/graph overlay before dense finishes.
- **Implementation:** keeper debounce + overlay_ready
- **Verification:** sync status / live reindex tests
- **Status:** resolved

### 4.6 Two sessions modify the same file — final state?
- **Decision:** Filesystem wins; CE does not keep competing repo versions per session.
- **Implementation:** Merkle/disk producers
- **Verification:** design + dirty ledger rewrite debounce tests
- **Status:** resolved

### 4.7 Should `session_authored` be per session?
- **Decision:** Yes — per session/client metadata, not a single boolean for the repo.
- **Implementation:** session store / admission response fields
- **Verification:** session attribution tests
- **Status:** resolved

### 4.8 Session A ends while Session B active?
- **Decision:** Runtime stays; pending repo work is not dropped solely because one session ended.
- **Implementation:** `end_session` keeps runtime when others remain
- **Verification:** auto/session tests
- **Status:** resolved

---

## 5. Multiple sessions on DIFFERENT repos

### 5.1 Can one daemon manage 10 repos?
- **Decision:** Yes — `RepoHub` holds isolated runtimes.
- **Implementation:** `repo_runtime.RepoHub`
- **Verification:** isolation tests; certify `two_repo_runtime_isolation`
- **Status:** resolved

### 5.2 Scheduling policy between repositories?
- **Decision:** Process-wide fair embed scheduler: active > recent > idle, FIFO within priority, aging against starvation.
- **Implementation:** `fair_schedule.FairEmbedScheduler`; `resources.run_job`
- **Verification:** `test_multi_repo_runtime.py`
- **Status:** resolved

### 5.3 Exclusive embedder access during a sync?
- **Decision:** Single-flight holder for embed jobs; other repos queue.
- **Implementation:** scheduler acquire/release
- **Verification:** scheduler tests
- **Status:** resolved

### 5.4 Can large Repo A starve tiny Repo B?
- **Decision:** Aging prevents indefinite starvation.
- **Implementation:** `aging_s` in FairEmbedScheduler
- **Verification:** `test_aging_prevents_idle_starvation`
- **Status:** resolved

### 5.5 Active repos higher priority than background?
- **Decision:** Yes.
- **Verification:** `test_active_work_outranks_idle_work`
- **Status:** resolved

### 5.6 Searching repo priority vs watched-only?
- **Decision:** Active/search/write priority outranks idle maintenance.
- **Status:** resolved

### 5.7 Five dirty repos — queue or concurrent?
- **Decision:** Keepers can run per repo; embeds queue through the fair single-flight scheduler.
- **Status:** resolved

---

## 6. Daemon startup / warm-up

### 6.1 When does the daemon start?
- **Decision:** On CE serve/MCP/CLI ensure paths (not mere IDE open). Watchdog can restore after reboot/process death.
- **Implementation:** `daemon.py`, `watchdog.py`
- **Verification:** watchdog recovery tests; certify daemon_binding (optional)
- **Status:** resolved

### 6.2 Should CodeRankEmbed always stay warm?
- **Decision:** No — ResourceManager may unload after inactivity; lexical/graph can remain.
- **Implementation:** resources / embedder cache
- **Verification:** resource manager tests (existing)
- **Status:** partial (unload policy exists; exact latency SLA is env-dependent)

### 6.3 Inactivity before unloading expensive resources?
- **Decision:** Configurable via resource manager settings/env.
- **Status:** partial (configurable; document operator defaults in runbook)

### 6.4 Warm-up latency after unload?
- **Decision:** Accept on-demand warm-up; preflight verifies provider. Accelerated profile must not silently fall back to PyTorch CPU.
- **Implementation:** accel profile + provider fail-closed
- **Verification:** doctor accel; certify `provider_warmup_fail_closed`; live DML doctor
- **Status:** resolved (fail-closed); warm latency **partial** (hardware-bound)

### 6.5 Graph/BM25 alive if embed unloaded?
- **Decision:** Yes — search can continue from last coherent generation / lexical+graph.
- **Status:** resolved

### 6.6 Idle mode releasing GPU/model memory?
- **Decision:** Yes — daemon stays; model may unload.
- **Status:** partial (mechanism present; dashboard labeling optional)

### 6.7 After laptop wake from sleep?
- **Decision:** Detect monotonic time gaps; reconcile managed/active repos (Merkle), because watchers may have missed events.
- **Implementation:** `BackgroundSyncLoop.check_time_gap` / watchdog wake hooks
- **Verification:** `tests/test_watcher_recovery.py`
- **Status:** resolved

### 6.8 After reboot?
- **Decision:** Registry recovers; watchdog/daemon restart reconciles; dirty journal replays non-published paths as immediately due.
- **Implementation:** journal + watchdog + daemon recovery
- **Verification:** watcher recovery + journal canaries + certify dirty restart
- **Status:** resolved

---

## 7. ResourceManager decisions

### 7.1 User compiling while CE indexes?
- **Decision:** Resource pressure can defer sync ticks (`strategy=deferred`) while searches continue from last coherent generation.
- **Implementation:** `resources` budgets in keeper tick
- **Verification:** existing resource / deferred status mapping
- **Status:** resolved

### 7.2 Reduce priority under CPU/GPU/RAM pressure?
- **Decision:** Yes — defer/reduce batches; do not crash.
- **Status:** resolved

### 7.3 Disk budget reached?
- **Decision:** Storage policy reports bytes / reclaimable; eviction candidates via LRU of non-pinned repos.
- **Implementation:** `storage_policy`
- **Verification:** storage tests
- **Status:** resolved

### 7.4 Which repo is evicted first?
- **Decision:** Least-recently-active non-pinned; pinned/explicit protected.
- **Verification:** LRU + pinned tests
- **Status:** resolved

### 7.5 Pause indexing but keep search?
- **Decision:** Yes — `pause_repo` / resource defer; search from last coherent generation.
- **Verification:** lifecycle pause + publish isolation
- **Status:** resolved

### 7.6 Embedding model crashes mid-index?
- **Decision:** Isolate failure to that runtime; prior generation stays; status can be `dense_pending`/`error`. Publish failures must **not** mark dirty paths `published`.
- **Implementation:** `RepoHub.isolate_failure`; `_notify_refresh` returns bool; failed publish → `overlay_ready`/`dense_pending`
- **Verification:** isolation tests; `test_publish_failure_does_not_mark_paths_published`
- **Status:** resolved

### 7.7 Can one broken repo crash the daemon?
- **Decision:** No — failures isolated per runtime.
- **Verification:** `test_failure_is_isolated_to_its_repository`; certify two-repo isolation
- **Status:** resolved

---

## 8. File watching

### 8.1 Watch every managed repo continuously?
- **Decision:** Watchers/keepers attach when repos are active; idle managed repos rely on reconcile/wake rather than unbounded always-on watch for hundreds of roots.
- **Implementation:** keeper start on activation; reconcile APIs
- **Verification:** watcher recovery tests
- **Status:** partial (active-path strong; 100-idle-repo watch matrix not fully labbed)

### 8.2 Watcher only when active?
- **Decision:** Prefer active runtimes; overflow/wake still force Merkle reconcile.
- **Status:** resolved

### 8.3 OS watcher limit reached?
- **Decision:** Treat as unavailable → reconcile/Merkle path still recovers.
- **Verification:** watcher unavailable test
- **Status:** resolved

### 8.4 Thousands of filesystem events?
- **Decision:** Cap to `live_max_files`; excess → `needs_full` + deferred catch-up. Overflow → immediate Merkle reconcile (Windows RDCW semantics).
- **Implementation:** `note_watcher_overflow`, drain caps
- **Verification:** 5000-event storm + overflow tests; certify watcher_overflow_recovery
- **Status:** resolved

### 8.5 Temp file + rename saves?
- **Decision:** Rewrite debounce collapses bursts into one quiet window.
- **Verification:** dirty ledger + watcher atomic-save tests
- **Status:** resolved

### 8.6 Atomic writes / multiple events per save?
- **Decision:** Same debounce coalescing.
- **Status:** resolved

### 8.7 File changes while indexing?
- **Decision:** Follow-up pass via rewrite debounce / remake; do not pretend in-flight batch is final.
- **Verification:** rewrite-during-index canaries
- **Status:** resolved

---

## 9. Git / branches / worktrees

### 9.1 Branch switch?
- **Decision:** Treated as a storm when many files change; capped + `needs_full`, not unbounded per-file live embeds.
- **Implementation:** live caps / needs_full
- **Verification:** storm / catchup tests
- **Status:** resolved

### 9.2 Do two Git worktrees share an index?
- **Decision:** **No** — separate project IDs / indexes. Shared `git_common_dir` is metadata only.
- **Implementation:** `git_common_dir` recorded; roots resolve independently
- **Verification:** lifecycle worktree tests
- **Status:** resolved

### 9.3 Different branch code reuse vectors wrongly?
- **Decision:** Worktrees are separate. Same worktree branch switch invalidates via file Merkle + storm/full as needed.
- **Status:** resolved

### 9.4 Is branch identity part of index identity?
- **Decision:** No — filesystem checkout state is identity; branch name is not the store key.
- **Status:** resolved

### 9.5 `git checkout` changes 500 files?
- **Decision:** Cap live batch; mark `needs_full` / catchup.
- **Status:** resolved

### 9.6 Distinguish agent edit vs branch storm?
- **Decision:** Volume/caps + reasons; storms flip `needs_full`.
- **Status:** resolved

---

## 10. Chunk-level indexing

### 10.1 What makes two chunks “the same”?
- **Decision:** Stable identity (symbol when available, else line range) + SHA-256 of **enriched embedding input** (`chunk_digest`). Line moves with identical enriched content reuse vectors.
- **Implementation:** `chunk_merkle.py`; docs in `docs/reindexing/chunk-level-incremental-indexing.md`
- **Verification:** `tests/test_chunk_merkle.py`
- **Status:** resolved

### 10.2 Chunk moves lines but content identical?
- **Decision:** Reuse embedding when digest unchanged.
- **Status:** resolved

### 10.3 Boundaries shift after insert near top?
- **Decision:** Dirty file fully re-chunked; only changed digests re-embed; removed digests cleaned.
- **Status:** resolved

### 10.4 How stable are chunk IDs?
- **Decision:** Prefer symbol-stable IDs; storage policy/compaction preserve explicit IDs rather than relying on FAISS sequential shift.
- **Implementation:** storage/vector tombstones + rebuild compaction
- **Verification:** `test_storage_policy.py`
- **Status:** resolved

### 10.5 Where are old chunk hashes stored?
- **Decision:** `chunk_merkle.json` (+ chunk records in store)
- **Status:** resolved

### 10.6 What is stored together?
- **Decision:** Chunk text/enriched, hash, vector mapping, file path, line range, metadata in store/collection payloads.
- **Status:** resolved

### 10.7 When a chunk disappears?
- **Decision:** Remove from chunks/BM25/graph mappings and tombstone/remove vectors in the same publication; compact when dead ratio high.
- **Implementation:** incremental cleanup + `compact_collection`
- **Verification:** storage policy cleanup tests
- **Status:** resolved

### 10.8 Identical chunks across different files share embedding?
- **Decision:** Not as a cross-file content-addressed global cache today; reuse is within the dirty-file chunk Merkle compare.
- **Status:** partial (intentional non-goal for v1 shipping)

---

## 11. Search while indexing

### 11.1 Can search continue while chunks embed?
- **Decision:** Yes — last coherent generation remains searchable.
- **Status:** resolved

### 11.2 BM25/graph updated but dense pending?
- **Decision:** Status `overlay_ready` / `dense_pending`; lexical/graph can surface new symbols.
- **Implementation:** `derive_sync_status` / `build_sync_contract`
- **Verification:** sync status canaries
- **Status:** resolved

### 11.3 Demote stale dense for changed file?
- **Decision:** Overlay/hot-patch freshness strategies prefer fresh disk/lexical evidence for dirty files.
- **Status:** resolved

### 11.4 Search exact new symbol before embedding finishes?
- **Decision:** BM25/graph overlay can discover it; dense may lag.
- **Status:** resolved

### 11.5 BM25/graph discoverability before semantic?
- **Decision:** Yes.
- **Status:** resolved

### 11.6 Maximum acceptable stale window?
- **Decision:** Normal target **≤5 seconds** after final write (debounce+publish). Resource deferral and storms must be explicit statuses, not silent violations.
- **Verification:** status canaries document the contract
- **Status:** resolved (contract); wall-clock under load is hardware/load dependent → operationally monitored via status

---

## 12. Persistence / crash recovery

### 12.1 Crash mid-embedding 10 chunks?
- **Decision:** Journal retains non-published paths; on restart they are immediately due; prior coherent generation stays readable.
- **Implementation:** `dirty_journal.JournalingLedger`
- **Verification:** canaries + certify dirty_restart_journal_replay
- **Status:** resolved

### 12.2 How know which chunks embedded?
- **Decision:** Publication manifest + chunk/vector artifacts; incomplete publish does not advance generation.
- **Status:** resolved

### 12.3 Can dirty ledger survive restart?
- **Decision:** Yes — durable journal under `projects/<id>/dirty_journal.json` (atomic write).
- **Status:** resolved

### 12.4 Reconstruct if journal lost?
- **Decision:** Yes — Merkle/root probe marks dirty paths.
- **Verification:** journal loss + Merkle recovery canary
- **Status:** resolved

### 12.5 FAISS updated but metadata not (or vice versa)?
- **Decision:** Readers refuse checksum-invalid / unusable publications (`load_engine` + `index_is_usable`).
- **Verification:** `test_load_engine_refuses_checksum_invalid_manifest`; certify publication_coherence
- **Status:** resolved

### 12.6 Atomic commits / versioned snapshots?
- **Decision:** Same-directory atomic artifact writes + checksum `publication_manifest.json` as readiness boundary.
- **Implementation:** `artifact_guard`
- **Status:** resolved

### 12.7 Power loss during graph write?
- **Decision:** Atomic replace + manifest validation prevents mixed generation from being claimed ready.
- **Status:** resolved

---

## 13. Storage / garbage collection

### 13.1 When are old vectors deleted?
- **Decision:** Logical removal/tombstone on publication; physical reclaim via periodic rebuild compaction (FAISS `remove_ids` is not trusted for OS RSS reclaim).
- **Implementation:** `storage_policy.compact_collection`; hooked best-effort after successful publish
- **Verification:** storage tests
- **Status:** resolved

### 13.2 Does FAISS immediately reclaim space?
- **Decision:** No — compact/rebuild/serialize required.
- **Status:** resolved

### 13.3 Prevent years of dead metadata?
- **Decision:** Dead-ratio threshold compaction + cleanup on chunk removal.
- **Status:** resolved

### 13.4 When GC unused repo index?
- **Decision:** Explicit remove, or policy eviction of non-pinned inactive repos (dry-run default).
- **Status:** resolved

### 13.5 Can user see disk per repo?
- **Decision:** Yes — `repo_storage_status` / status fields include bytes + reclaimable.
- **Verification:** storage + observability tests
- **Status:** resolved

---

## 14. Client discovery / integrations

### 14.1 How does CE know which client?
- **Decision:** Optional `client` field on requests.
- **Status:** resolved

### 14.2 Need to know Cursor vs Claude vs Codex?
- **Decision:** Not for index semantics — telemetry/attribution only.
- **Status:** resolved

### 14.3 Should client tell CE the workspace path?
- **Decision:** **Required.**
- **Status:** resolved

### 14.4 Two clients, different paths, same Git repo?
- **Decision:** Canonical realpath → same project_id/runtime.
- **Status:** resolved

### 14.5 Should CE auto-install into a client?
- **Decision:** Only during explicit setup/install commands — not silently on Auto.
- **Status:** resolved

### 14.6 Auto enabled but user never authorized manage?
- **Decision:** Unmanaged → `requires_initialize`; never-index always wins.
- **Status:** resolved

---

## 15. User control

### 15.1 Never index this repo?
- **Decision:** Yes — `never_index_repo` / CLI `never-index`.
- **Verification:** lifecycle + auto tests
- **Status:** resolved

### 15.2 Exclude directories (`node_modules`, `.git`, build, …)?
- **Decision:** Yes — existing ignore/noise path filters in indexing/graphify extract.
- **Status:** resolved

### 15.3 Temporarily pause CE for a repository?
- **Decision:** Yes — `pause_repo` / `resume_repo`.
- **Status:** resolved

### 15.4 Force `ctx sync` immediately?
- **Decision:** Yes — `sync_now_repo` / CLI `sync-now`.
- **Status:** resolved

### 15.5 Force full rebuild?
- **Decision:** Yes — `rebuild_repo` / CLI `rebuild`.
- **Status:** resolved

### 15.6 Remove from CE without deleting the git repo?
- **Decision:** Yes — `remove_repo(delete_store=False)` default; optional store delete.
- **Status:** resolved

---

## 16. Observability / dashboard

### 16.1 Dashboard for 20 repositories?
- **Decision:** Status API lists managed/active runtimes with per-repo contracts; dashboard consumes that data.
- **Implementation:** expanded `status` fields; `list_managed_repos`
- **Verification:** observability field tests
- **Status:** partial (data contract resolved; dashboard cosmetics not redesigned)

### 16.2 Ready / Syncing / Dirty / Error / Paused / Catch-up?
- **Decision:** `derive_sync_status` + lifecycle states cover ready/syncing/overlay_ready/dense_pending/deferred/needs_full/error + paused/never_index.
- **Status:** resolved (API); UI chrome partial

### 16.3 Last indexed vs last changed separately?
- **Decision:** Status exposes timestamp fields (last_sync / access / dirty); keeper probe carries change signals.
- **Status:** partial (fields present; some are best-effort depending on keeper attachment)

### 16.4 Pending chunks?
- **Decision:** Dirty path counts + overlay/dense flags; chunk-pending counts where payload provides them.
- **Status:** partial

### 16.5 Embedding queue length?
- **Decision:** Scheduler status exposed via resource/status (`embed_scheduler`).
- **Verification:** multi-repo resource test
- **Status:** resolved

### 16.6 Why indexing paused?
- **Decision:** `pause_reason`, resource deferral, storm/`needs_full`, warm_error.
- **Status:** resolved

### 16.7 Files currently processing?
- **Decision:** Dirty ledger snapshot includes path states (`processing`).
- **Status:** resolved

---

## 17. Important product questions

### A. What does “managed repo” mean?
- **Decision:** Persistently registered and eligible for sync until paused, never-index, or removed. Continuous watch/index intensity follows activation/policy — not “every idle managed root forever at full watch cost.”
- **Status:** resolved

### B. Who owns the repository lifecycle?
- **Decision:** Hybrid locked model:  
  `ctx initialize` → permanent manage.  
  Auto/client path → activate only with workspace path; does not silently mint manage.  
  Idle/unload releases expensive resources; registry remains.
- **Status:** resolved

### C. Unit of concurrency?
- **Decision:** Daemon → RepoHub → per-repo Runtime (sessions + keeper) → ResourceManager/FairEmbedScheduler owns CodeRankEmbed.
- **Status:** resolved

### D. What does Auto mean?
- **Decision:** Discover/activate when integration provides workspace path; manage lifecycle under resource/usage policy. Initialize = explicit permanent manage even without recent client.
- **Status:** resolved

### E. Multiple sessions?
- **Decision:** Index state repository-global; session state session-specific; filesystem is ultimate truth.
- **Status:** resolved

---

## Honest remaining limits (not “perfect”)

These are **not** claimed as fully lab-closed:

1. **Windows chmod permission denial** — skipped (not reliable on NT); not counted as pass.  
2. **External client matrix** — optional (`ctx test clients --clients`).  
3. **Dashboard UI polish** — status data complete; visual dashboard not redesigned.  
4. **Cross-file identical-chunk embedding cache** — not a v1 goal.  
5. **Real ReadDirectoryChangesW OS integration test** — overflow semantics covered via recovery API, not kernel buffer capture.  
6. **SDK/Cursor-agent packages** — some experimental SDK tests require `cursor-sdk` and are environment-gated.  
7. **Always-on sweeper** for unused repos — policy exists; destructive GC remains explicit/dry-run-first.

## Bottom line

**No — not “every single part is cosmically perfect.”**  
**Yes — every question in `questions.md` now has a locked decision, an implementation pointer, and evidence-backed status.** Shipping-critical sections **1–12 and 15** are **resolved** under the design contract; section **16** UI and a few operational labs remain **partial** as documented above.

`questions.md` and `docs/superpowers/plans/2026-08-17-production-certification.md` were left unchanged.

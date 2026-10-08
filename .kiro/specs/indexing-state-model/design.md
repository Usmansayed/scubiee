# Design — Unified Indexing & State-Management Model

## Overview

This design separates three concerns that are currently entangled in `sync_loop.py` / `incremental.py` / `freshness.py` / `lifecycle_runtime.py`:

1. **Change detection** — what differs between the working tree and the published generation.
2. **Workload classification** — how big the pending work is, in estimated wall-clock terms.
3. **Execution & lifecycle** — which lane runs the work, and when the engine starts/stops.

The unifying mechanism is a durable **`index_state.json`** record (single source of truth) plus one idempotent **Reconciler** (detect → enqueue → classify) invoked at start, connect, and poll. Everything builds on existing primitives (merkle baseline, dirty journal, publication-manifest fence, blue/green staging); no primitive is rewritten.

Design maps to requirements R1–R10. The full scenario catalogue and rationale live in the design artifact "Scubiee Indexing State Model — Design"; this document is the implementable spec.

---

## Architecture

```
                         ┌──────────────────────────────────────────────┐
                         │                 Reconciler                    │
   start / connect / ───▶│  detect(drift) → enqueue(journal) → classify  │
   poll triggers         │        (idempotent, no lane selection)        │
                         └───────────────┬──────────────────────────────┘
                                         │ writes
                     ┌───────────────────▼───────────────────┐
                     │          index_state.json              │  ◀── single source of truth
                     │  state │ generation │ build │ pending  │
                     └───┬───────────────┬──────────────┬─────┘
     reads (lane select) │           reads (lifecycle)   │ reads (status contract)
                         ▼               ▼                ▼
                 ┌──────────────┐  ┌───────────┐   ┌──────────────┐
                 │  Keeper      │  │ Lifecycle │   │ Status/Gate  │
                 │ (exec lanes) │  │ idle-stop │   │  contract    │
                 │  consumes    │  │ gated on  │   │  pending obj │
                 │  the journal │  │ busy-state│   │  (agent)     │
                 └──────────────┘  └───────────┘   └──────────────┘
```

Durable records (per project, under `projects/<id>/`):

| Record | Owner | Advances when |
|---|---|---|
| `merkle.json` | generation | a generation commits (+ manifest, together) |
| `publication_manifest.json` | generation | same commit, under store write lock |
| `index_state.json` **(new)** | reconciler + builder | every state transition (atomic) |
| `dirty_journal.json` | ledger | every ledger mutation (existing) |
| `generation.json` | publish | derived from `index_state.generation` |
| `meta.json` (`git_head`, `graph_pending`) | index | on commit (existing) |

---

## Components and Interfaces

### C1 — `index_state` module (new)

Owns the authoritative state record. Pure persistence + a small typed accessor; no detection logic.

```python
# packages/pipeline/index_state.py  (new)

IndexState = Literal[
    "unindexed", "indexing", "fresh", "stale", "reconciling", "interrupted"
]

@dataclass
class BuildRecord:
    build_id: str
    pid: int
    kind: Literal["full", "bulk", "incremental"]
    started_at: float
    staging_dir: str | None
    total_units: int
    done_units: int
    phase: Literal["parse", "embed", "graph", "publish"]

@dataclass
class PendingSummary:
    substantial: bool
    reason: str          # offline_batch | git_switch | bulk_paste | full_reindex | resuming_interrupted | ""
    estimated_units: int
    estimated_seconds: float
    done_units: int
    total_units: int
    search_usable: bool
    detected_at: float

@dataclass
class IndexStateDoc:
    version: int
    state: IndexState
    generation_epoch: str
    generation_counter: int
    indexed_head: str | None
    merkle_root: str | None
    build: BuildRecord | None
    pending: PendingSummary | None
    last_reconcile_at: float
    last_error: str | None

def load_index_state(project_id) -> IndexStateDoc        # missing/old-version -> UNKNOWN sentinel (state="unindexed", pending=None)
def write_index_state(project_id, doc) -> None           # atomic (atomic_write_text), monotonic generation_counter per epoch
def transition(project_id, **changes) -> IndexStateDoc   # load-modify-write under a per-project in-proc lock
```

- **Backward-compat:** a missing file or `version` mismatch returns a sentinel that the reconciler treats as "reconcile from scratch" (R10.4, R5.5). Never raises.
- **Monotonicity:** `generation_counter` only increases within an `epoch`; `epoch` is minted per engine process (reuse the existing runtime epoch). Mirrors to `generation.json` via the existing `write_stamp`.

### C2 — Reconciler (new orchestration; reuses existing detectors)

```python
# packages/pipeline/reconciler.py  (new)

@dataclass
class ReconcilePlan:
    drift_added: list[str]
    drift_modified: list[str]
    drift_removed: list[str]
    index_state: IndexState
    pending: PendingSummary | None
    interrupted_build: BuildRecord | None

def reconcile(repo, *, trigger: Literal["start","connect","poll","wake"],
              store, journal) -> ReconcilePlan:
    # 1. load index_state + merkle + meta
    # 2. interruption check: build record with dead pid -> INTERRUPTED, sweep staging
    # 3. detect drift via EXISTING detectors:
    #       - check_freshness (git fast-path A/B when indexed_head known)
    #       - root_probe / verify_merkle_leaves (mtime-gated rehash of indexed leaves)
    #       - newcomer walk (full on start/connect; dir-mtime on poll)
    # 4. enqueue drift into the DURABLE journal  (closes offline-loss gap)
    # 5. classify_workload(drift, corpus) -> pending summary
    # 6. transition(index_state) ; return plan  (NO lane selection here)
```

- **Idempotent (R8.1):** calling twice with no new changes yields the same enqueued set and state (journal dedups by path; merkle is the stable baseline).
- **Trigger-specific scope (performance):** `start`/`connect` do the thorough newcomer walk; `poll` uses the cheap dir-mtime `DirWatch` path (as today). This keeps the 1s poll cheap while making start/connect thorough.
- **Reuses** `freshness.check_freshness`, `root_probe`, `verify_merkle_leaves`, `merkle.diff_hashes` — no new detection algorithm.

### C3 — Workload classifier (new; extracts + extends `_estimate_dirty_chunks`)

```python
# packages/pipeline/workload.py  (new)

def classify_workload(added, modified, removed, *, store, corpus_size,
                      throughput_chunks_per_s: float) -> PendingSummary:
    units = estimate_units(added, modified, removed, store)   # reuse _estimate_dirty_chunks logic
    # weight by file type (code >> docs > config; vendored/binary ~0)
    est_seconds = units / max(1e-6, throughput_chunks_per_s)
    substantial = (
        est_seconds >= SUBSTANTIAL_SECONDS          # default 25s, env CTX_SUBSTANTIAL_SECONDS
        or needs_full_reindex(units, corpus_size)
        or (corpus_size and units / corpus_size >= SUBSTANTIAL_FRACTION)  # default 0.4
    )
    return PendingSummary(...)
```

- **`throughput_chunks_per_s`** is measured from recent embed stages (we already time `embed_ms` / `embed_chunks`) and stored (e.g. in `meta.json` or a small running average in `index_state`); conservative default until measured (R6.5).
- `estimate_units` reuses the exact per-file chunk counts from `chunk_merkle` for existing files and the line-based heuristic for new files (existing logic in `_estimate_dirty_chunks`), adding the file-type weighting (R6.1).

### C4 — Builder build-intent record (modify `indexer.index_repo_staged`)

Before staging mutation: `transition(project_id, state="indexing", build=BuildRecord(...))`.
After `promote_staged_store` publishes the manifest: `transition(project_id, state="fresh", build=None, generation_counter+=1)`.
On sub-batch commit (bulk): update `build.done_units` durably so resume knows progress (R3.1–R3.3).

### C5 — Status/Gate contract (modify `ce_service.health`/`status` + `sync_status.build_sync_contract`)

Derive the agent-facing `pending` object from `index_state.json`:
```jsonc
// present ONLY when state == reconciling/interrupted (substantial)
"pending": {
  "substantial": true,
  "reason": "offline_batch",
  "estimated_seconds": 180,
  "done": 900, "total": 1840,
  "search_usable": true,
  "action": null            // or "scubiee index . --force" when needs_full
}
```
Remove raw `dirty_count` from the agent-facing contract (keep it in the internal/debug status). (R7.)

### C6 — Lifecycle gate (modify `lifecycle_runtime._idle_busy_reason`)

Add: index state ∈ {indexing, reconciling, interrupted} → busy (block idle-stop). This replaces the ad-hoc `warm_state`/`governor.indexing` checks with the authoritative record (R4.3).

### C7 — Lane selection reads index_state (modify `sync_loop.drain_due`)

`drain_due` consumes the journal (unchanged) but asks the classifier/`index_state` for the size tier instead of re-deriving it inline. This removes the entanglement that produced the delete/rename edge cases (R8.4). The deletion-mask / graph-catchup heuristics become policy driven by the classified tier, not ad-hoc per-batch logic.

---

## Data Models

### `index_state.json` (new, per project)
See C1. Written atomically on every transition. Example (reconciling after an offline batch):
```jsonc
{
  "version": 1,
  "state": "reconciling",
  "generation_epoch": "e-7f3a...",
  "generation_counter": 41,
  "indexed_head": "9a5c2fe...",
  "merkle_root": "root:ab12...",
  "build": null,
  "pending": {
    "substantial": true, "reason": "offline_batch",
    "estimated_units": 1840, "estimated_seconds": 180,
    "done_units": 0, "total_units": 1840,
    "search_usable": true, "detected_at": 1699999990.0
  },
  "last_reconcile_at": 1699999990.0,
  "last_error": null
}
```

### Crash-safety invariant (the heart of recovery)
- `merkle.json` + `publication_manifest.json` advance **only together**, on commit, under `store_write_lock`.
- `index_state.build` is written **before** a build mutates staging and cleared **after** the manifest publishes.
- Therefore any crash leaves exactly one of:
  - **(a)** coherent old generation + a stale `build` record (dead pid) → INTERRUPTED → resume remainder.
  - **(b)** coherent new generation + no `build` record → done.
- There is never a torn served generation (R3.5, R5.3).

---

## State Machine (Repository Index State)

```
UNINDEXED ──index──▶ INDEXING ──commit──▶ FRESH ──small drift──▶ STALE ──catch up──▶ FRESH
    ▲                   │                   ▲                       │
    │                   │ interrupt         │                       │ large drift
    │                   ▼                   │                       ▼
    └───────────── INTERRUPTED ──resume─────┘                   RECONCILING ──commit──▶ FRESH
```
- STALE and INDEXING-small are **silent** (no agent pending).
- RECONCILING and INTERRUPTED (substantial) **surface** pending.
- Idle-stop blocked in INDEXING / RECONCILING / INTERRUPTED.

---

## Error Handling

- **Missing/corrupt `index_state.json`** → sentinel → full reconcile; log once, never crash (R5.5, R10.4).
- **Dead-pid staging** → `_sweep_stale_staging` (existing) + resume (R3.2).
- **Vector/chunk drift** → `reconcile_vector_store` (existing) on open (R3.4).
- **Torn manifest/graph** → `validate_manifest` fail-closed → `republish_if_coherent` or `heal` (existing) (R3.5).
- **Throughput unmeasured** → conservative default; never block classification (R6.5).
- **Reconciler exception** → record `last_error`, leave journal intact (work not lost), retry next trigger.

---

## Testing Strategy

Each component gets offline unit tests (deterministic, `CTX_HOME` tmp, no live engine) plus the existing live scenario harness for end-to-end.

- **C1 index_state:** round-trip, atomic write, monotonic counter, missing/old-version sentinel.
- **C2 reconciler:** fabricated merkle + working tree → correct drift + enqueue; idempotency (two calls, same result); interruption detection with a fake dead-pid build record; git-HEAD-advanced path.
- **C3 classifier:** unit tables — small code edit → not substantial; 1000-file paste → substantial; full reindex → substantial; throughput default when unmeasured; file-type weighting.
- **C4 builder:** build record written before staging, cleared after publish; killed-mid-build (simulate) → INTERRUPTED on reload → resume remainder (against a COPIED store).
- **C5 contract:** pending present only for substantial; absent for small; `action` on needs_full; no raw dirty_count agent-side.
- **C6 lifecycle:** idle-stop blocked while index_state busy; allowed when fresh+no clients.
- **C7 lanes:** delete prunes within bound; rename = delete+add within bound; large batch sliced; all consume the journal.
- **Scenario matrix (R9.6):** A1–A7, B1–B2, C1–C6, D1–D4, E1–E3 each have a test or a documented verified manual check in `docs/scubiee-scenario-test-results.md`.
- **Regression (R10):** full offline suite + existing sync-matrix pass after each step; destructive/recovery tests run against a COPIED store, never the live index.

---

## Rollout (independently shippable steps)

Ordered so each step is safe alone and testable before the next (R10.1):

1. **index_state module** (C1) — write/read alongside existing state, not yet authoritative. Tests: round-trip, sentinel.
2. **Build-intent record** (C4) — write/clear around `index_repo_staged`; makes INTERRUPTED detectable. Tests: killed-build resume on copied store.
3. **Reconciler** (C2) + wire into **engine start** (closes offline-reconcile gap, R2). Tests: offline-drift enqueue, idempotency, git path.
4. **Workload classifier** (C3) + measured throughput. Tests: classification tables.
5. **Status/gate `pending`** (C5) + remove agent-facing dirty_count. Tests: contract.
6. **Lifecycle idle-stop gate on index_state** (C6). Tests: no-stop-while-busy.
7. **Lane selection reads index_state** (C7) — retire the ad-hoc delete-mask / size re-derivation. Tests: delete/rename bounds, big-batch slicing.

Steps 1–3 deliver the headline guarantees (no lost offline change, resumable interruption). Steps 4–5 deliver the clean agent signal. Steps 6–7 remove the entanglement that caused the recurring edge cases.

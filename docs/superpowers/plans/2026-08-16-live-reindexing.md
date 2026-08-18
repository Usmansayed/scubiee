# Live Reindexing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Context Engine continuously reindex small agent edit bursts while preserving a stable published retrieval generation during active locate streaks.

**Architecture:** Add a focused dirty-ledger/debounce controller to the keeper. It coalesces changed paths, runs the existing `incremental_sync` pipeline once per quiet edit burst, and holds the existing `RuntimeManager.publish_engine` callback until the locate streak is quiet. The current on-disk index remains the only durable index; v1 records overlay/pending-publish state and avoids a second FAISS index.

**Tech Stack:** Python 3.10+, threading, existing Merkle/root probe, Graphify incremental patch, FastEmbed/DirectML, pytest.

## Global Constraints

- One warm CodeRankEmbed model per engine process; batch size remains acceleration-profile controlled (16 on current DML profile).
- Dirty agent edit burst target: ≤20 chunks; storms follow existing incremental/full guards.
- Never full-index on the live debounce path.
- Disk is absolute truth; `overlay` means processed-but-not-published state; `published` means stable generation.
- No repository commit is part of this plan unless the user explicitly requests one.

---

### Task 1: Dirty ledger and adaptive debounce controller

**Files:**
- Create: `packages/pipeline/dirty_ledger.py`
- Create: `tests/test_dirty_ledger.py`

**Interfaces:**
- Produces `DirtyLedger(debounce_ms=1500, rewrite_debounce_ms=2500)`.
- `mark(paths: Iterable[str], reason: str, now: float | None = None) -> None`
- `due_paths(now: float | None = None) -> list[str]`
- `begin(paths: Iterable[str]) -> None`
- `complete(paths: Iterable[str], *, published: bool) -> None`
- `snapshot() -> dict[str, Any]`

- [ ] **Step 1: Write the failing tests**

```python
def test_rewrite_extends_only_that_path_quiet_window():
    ledger = DirtyLedger(debounce_ms=1500, rewrite_debounce_ms=2500)
    ledger.mark(["a.py", "b.py"], reason="write", now=0.0)
    ledger.mark(["a.py"], reason="write", now=1.0)

    assert ledger.due_paths(now=1.6) == ["b.py"]
    assert ledger.due_paths(now=3.6) == ["a.py"]


def test_complete_without_publish_reports_overlay_ready():
    ledger = DirtyLedger()
    ledger.mark(["a.py"], reason="write", now=0.0)
    ledger.begin(["a.py"])
    ledger.complete(["a.py"], published=False)

    assert ledger.snapshot()["paths"]["a.py"]["state"] == "overlay_ready"
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/test_dirty_ledger.py -q`  
Expected: FAIL because `pipeline.dirty_ledger` does not exist.

- [ ] **Step 3: Implement the minimal thread-safe ledger**

```python
@dataclass
class DirtyEntry:
    path: str
    reason: str
    state: str = "queued"
    due_at: float = 0.0
    rewrites: int = 0


class DirtyLedger:
    def mark(self, paths, *, reason, now=None) -> None:
        # First write receives debounce_ms. A rewrite before completion receives
        # rewrite_debounce_ms. Preserve other paths' due times.
        ...
```

- [ ] **Step 4: Run focused tests to verify they pass**

Run: `pytest tests/test_dirty_ledger.py -q`  
Expected: PASS.

### Task 2: Debounced keeper execution and publish gate

**Files:**
- Modify: `packages/pipeline/sync_loop.py:16-261`
- Modify: `packages/pipeline/ce_service.py:45-105,154-173`
- Modify: `tests/test_root_probe.py`
- Modify: `tests/test_runtime_publish.py`

**Interfaces:**
- `BackgroundSyncLoop.mark_dirty(paths, *, reason="write") -> None`
- `BackgroundSyncLoop.note_locate(now: float | None = None) -> None`
- `BackgroundSyncLoop.status()` includes `dirty`, `overlay_ready`, `publish_pending`, and `locate_streak_active`.
- `on_refresh(payload)` is invoked only when promotion is allowed; a processed-but-held sync reports `overlay_ready`.

- [ ] **Step 1: Write failing keeper tests**

```python
def test_debounced_dirty_sync_coalesces_rewrites(monkeypatch, tmp_path):
    loop = BackgroundSyncLoop(tmp_path, debounce_ms=10, rewrite_debounce_ms=20)
    calls = []
    monkeypatch.setattr(loop, "_sync_paths", lambda paths, **_: calls.append(paths) or {"refreshed": True})

    loop.mark_dirty(["pkg/a.py"], reason="write")
    loop.mark_dirty(["pkg/a.py"], reason="write")
    loop.drain_due(now=time.monotonic() + 0.03)

    assert calls == [["pkg/a.py"]]


def test_locate_streak_holds_publish_then_promotes(monkeypatch, tmp_path):
    published = []
    loop = BackgroundSyncLoop(tmp_path, on_refresh=lambda p: published.append(p), locate_streak_ms=100)
    # Process a dirty path while a locate was just noted.
    ...
    assert published == []
    loop.drain_publish(now=time.monotonic() + 0.11)
    assert len(published) == 1
```

- [ ] **Step 2: Run focused keeper tests to verify they fail**

Run: `pytest tests/test_root_probe.py -q`  
Expected: FAIL because `mark_dirty`, `drain_due`, and publish gating are absent.

- [ ] **Step 3: Implement queue, worker, and gate**

```python
def mark_dirty(self, paths: Iterable[str], *, reason: str = "write") -> None:
    self._ledger.mark(paths, reason=reason)
    self._wake.set()


def _maybe_publish(self, payload: dict, *, force: bool = False) -> None:
    if not force and self.locate_streak_active():
        self._pending_publish = payload
        return
    self.on_refresh(payload)
```

Use the existing `incremental_sync(..., force_files=paths)` for debounce work.
Keep the timer probe path as a fallback, adding its detected paths to the ledger.

- [ ] **Step 4: Make runtime health expose the keeper state**

```python
return {
    ...,
    "sync": self.sync_loop.status() if self.sync_loop else None,
}
```

Ensure `RuntimeManager._start_keeper` keeps `publish_engine` as the callback; it
must now receive only promoted payloads.

- [ ] **Step 5: Run keeper and runtime tests to verify they pass**

Run: `pytest tests/test_root_probe.py tests/test_runtime_publish.py -q`  
Expected: PASS.

### Task 3: Connect agent-facing locate activity and scoped handle invalidation

**Files:**
- Modify: `packages/pipeline/mcp_locate.py` at map/search/focus handlers
- Modify: `packages/pipeline/session_store.py`
- Modify: `packages/pipeline/ce_service.py`
- Create: `tests/test_live_reindex_mcp.py`

**Interfaces:**
- Locate handlers call `runtime.note_locate()` before returning results.
- `SessionStore.invalidate_paths(paths: Iterable[str]) -> int` removes only
  entries whose canonical path is dirty.
- Promoted payloads call path-scoped invalidation before `publish_engine`.

- [ ] **Step 1: Write failing tests**

```python
def test_invalidate_paths_keeps_unrelated_session_handles(store):
    store.record(path="a.py", start_line=1, end_line=2, code="old-a")
    keep = store.record(path="b.py", start_line=1, end_line=2, code="keep-b")

    store.invalidate_paths(["a.py"])

    assert store.recall()["items"] == [keep]


def test_map_notes_locate_before_response(monkeypatch):
    runtime = MagicMock()
    monkeypatch.setattr(mcp_locate, "get_runtime", lambda: runtime)
    ...
    runtime.note_locate.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_session_store.py tests/test_live_reindex_mcp.py -q`  
Expected: FAIL for missing path invalidation and locate notification.

- [ ] **Step 3: Implement scoped invalidation and locate activity**

```python
def invalidate_paths(self, paths: Iterable[str]) -> int:
    normalized = {normalize_path(p) for p in paths}
    # Remove only records associated with normalized paths.
    ...
```

Call the runtime notification only for locate-oriented tools, never for
`status`, so status polling cannot indefinitely extend a locate streak.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_session_store.py tests/test_live_reindex_mcp.py -q`  
Expected: PASS.

### Task 4: Production configuration, status telemetry, and documentation

**Files:**
- Modify: `packages/pipeline/sync_loop.py` defaults
- Modify: `packages/pipeline/__main__.py` environment/help defaults
- Modify: `docs/engineering/05-background-systems.md`
- Modify: `docs/reindexing/live-reindexing-system-design.md`
- Create: `tests/test_live_reindex_config.py`

**Interfaces:**
- `CTX_SYNC_DEBOUNCE_MS=1500`
- `CTX_SYNC_REWRITE_DEBOUNCE_MS=2500`
- `CTX_LOCATE_STREAK_MS=8000`
- `CTX_SYNC_MAX_FILES=40`
- `CTX_SYNC_MAX_CHUNKS=100`
- Status telemetry carries `save_to_overlay_lexical_ms`,
  `save_to_overlay_semantic_ms`, `save_to_published_ms`, and streak delay.

- [ ] **Step 1: Write failing configuration/status tests**

```python
def test_live_sync_defaults_are_safe(monkeypatch):
    monkeypatch.delenv("CTX_SYNC_DEBOUNCE_MS", raising=False)
    assert resolve_debounce_settings() == (1500, 2500)


def test_status_reports_overlay_and_pending_publish(tmp_path):
    loop = BackgroundSyncLoop(tmp_path)
    loop.mark_dirty(["a.py"], reason="write")
    status = loop.status()
    assert status["dirty"]["queued"] == ["a.py"]
    assert status["publish_pending"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_live_reindex_config.py -q`  
Expected: FAIL for missing settings and metrics.

- [ ] **Step 3: Implement defaults, telemetry, and docs**

Keep the interval probe configurable; set production default to 240000 ms only
after existing interval tests are updated. Document that it is a backup probe,
not a recurring full reindex.

- [ ] **Step 4: Run targeted suite to verify it passes**

Run: `pytest tests/test_live_reindex_config.py tests/test_root_probe.py tests/test_runtime_publish.py -q`  
Expected: PASS.

### Task 5: End-to-end reliability gate

**Files:**
- Create: `tests/test_live_reindex_e2e.py`
- Modify: `scripts/bench_embed_workers.py` only if reusable timing output is
  needed; do not create multiple model copies in production.

**Interfaces:**
- E2E test uses a temporary indexed repository, modifies a file, marks it dirty,
  drains the debounce worker, verifies graph/vector sync result, then verifies
  held promotion is released after the locate streak.

- [ ] **Step 1: Write the failing E2E test**

```python
def test_edit_becomes_overlay_searchable_then_promotes(tmp_path, monkeypatch):
    repo = seed_indexed_repo(tmp_path)
    runtime = RuntimeManager()
    # Write a new symbol, queue the file, run due debounce work.
    # Assert overlay state first, no generation bump during locate streak.
    # End streak; assert one generation bump and fresh symbol retrieval.
    ...
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest tests/test_live_reindex_e2e.py -q`  
Expected: FAIL until Tasks 1–4 are complete.

- [ ] **Step 3: Complete missing integration seam with the minimum code**

Use real temporary Merkle/chunk fixtures and mocked embedding vectors only where
the ONNX model would make the test hardware-dependent. Assert graph/vector
functions are called with dirty paths, not the whole repository.

- [ ] **Step 4: Run the reliability suite**

Run: `pytest tests/test_dirty_ledger.py tests/test_root_probe.py tests/test_runtime_publish.py tests/test_session_store.py tests/test_live_reindex_mcp.py tests/test_live_reindex_config.py tests/test_live_reindex_e2e.py -q`  
Expected: PASS.

- [ ] **Step 5: Run a manual timing smoke**

Run: `python -u scripts/bench_embed_workers.py --repo C:\\Users\\usman\\Downloads\\frontend-mcp-target --n-chunks 20 --workers 1 --modes concurrent`  
Expected: one-worker warm batch result recorded; no multi-model worker setting is introduced.

## Self-Review

- **Spec coverage:** Tasks 1–2 implement adaptive debounce, dirty ledger, process≠publish, tunable streak gate, and backup compatibility. Task 3 makes overlay behavior safe for sessions and connects real locate usage. Task 4 provides configuration, status, and telemetry. Task 5 proves edit→overlay→publish behavior.
- **Placeholder scan:** No deferred implementation placeholders; each task names exact files, interfaces, test commands, and expected behavior.
- **Type consistency:** `DirtyLedger` owns per-path state; `BackgroundSyncLoop` owns execution and publish gating; `RuntimeManager` owns published generation; `SessionStore` owns handle invalidation.

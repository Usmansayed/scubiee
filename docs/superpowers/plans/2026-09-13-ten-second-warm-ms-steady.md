# Ten-Second Warm → Millisecond Steady Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status (2026-09-13):** Implemented in **0.3.79** (unit green). Live gate: `uv tool install --force . --refresh`, reload Cursor MCP, run `python scripts/warm_contract_acceptance.py`.

**Goal:** On Cursor open, Scubiee reaches fully-warm ready within **10s wall**; after that, map/pack answer in **low hundreds of ms** (cache hits tens of ms) even after minutes/hours idle, until **all** Scubiee clients disconnect.

**Architecture:** Move warm off the first tool call onto **MCP bridge attach**. Parallelize the three cold costs (engine listen, DML embedder dummy encode, AST disk-bundle hydrate). Hold RAM while `active_clients > 0`. Unload only after last client leave + existing disconnect debounce. Do not pay in-process 800 MB AST preload; use the existing pickle bundle path.

**Tech Stack:** Python, `mcp_bridge` / `mcp_lifecycle` / `engine` / `context_trace` / `memory_governor` / `lifecycle_runtime`, FastEmbed + ORT DirectML, existing `/v1/embed/prewarm` + repo bundle pickle.

**Spec:** Product contract in this plan (approved intent 2026-09-13). Research: ORT DirectML first-inference shader compile ([Microsoft DML EP](https://github.com/microsoft/onnxruntime/blob/gh-pages/docs/execution-providers/DirectML-ExecutionProvider.md)); production FastEmbed singleton + dummy warm; MCP initialize-immediate + background warm ([myelin](https://github.com/et-do/myelin/commit/36a721b93f2ff53347b001cf3d303a84ad3e6ff3)); warm daemon pattern (palaia / fmdidx).

## Global Constraints

- **Hard SLA A — attach warm:** From bridge process start → `warm_ready=true` (engine healthy + embedder_loaded + AST bundle hydrated or skipped-for-map) in **≤ 10_000 ms** p95 on this Windows DML box (RX 6500M profile).
- **Hard SLA B — steady locate:** After `warm_ready`, spaced ≥60s idle with bridge still registered: map wall p95 **≤ 300 ms**; lean 1-seed pack wall p95 **≤ 500 ms**; lean 3-seed pack wall p95 **≤ 800 ms**. Tool `elapsed_ms` already ~130–250 ms when warm — wall must not regress to seconds.
- **Hard SLA C — unload:** Engine/embed demote only when `active_client_count == 0` after `CTX_DISCONNECT_DEBOUNCE_S` (keep 120s). Bridge `kind=bridge` counts. One remaining client = stay warm.
- **Do not** load FastEmbed into bridge or mcp_locate (0.3.78 RAM fix stays).
- **Do not** re-enable default in-RAM AST preload that bloats locate to ~800 MB. Disk bundle hydrate only.
- **Do not** replace `composite_v1` / weaken `merge_seed_heatmaps`.
- Honest “ms”: true single-digit ms only on proximity cache hit; live tracer path targets low hundreds of ms (industry warm hybrid search is ~5–50 ms; our poly+merge is heavier).

## Why this is viable (budget math)

| Cold cost today | Typical | Fix |
|-----------------|---------|-----|
| Engine spawn → `/health` | ~2–3 s | Already listen-first; kick at **attach**, not first map |
| DML session + first encode | ~5–12 s | `/v1/embed/prewarm` + dummy encode **in parallel** after health; ORT reuses session |
| Full AST `_load_repo` rebuild | ~15–19 s | **Forbid** on warm critical path; hydrate pickle via `_try_load_repo_bundle` (<1–2 s) or background bake once |
| First-map `engine_warming` + agent retry | +3–10 s | Eliminate: wait for warm_ready **or** single in-process join ≤ remaining budget |

**Parallel attach timeline (target):**

```
T=0     bridge main() → register bridge client → kick ensure_daemon (nonblocking)
T≈0–3s  /health up
T≈3–10s PARALLEL: embed prewarm(dummy)  ||  AST bundle hydrate in locate worker
T≤10s   warm_ready=true published on /v1/status + gate
T>10s   map/pack serve from hot caches; idle minutes OK while clients > 0
```

Industry confirms: DML first-run is the expensive part; after dummy inference, subsequent encodes are cheap. Keep the session resident (do not demote while clients attached).

## File map

| File | Responsibility |
|------|----------------|
| `packages/pipeline/mcp_bridge.py` | Kick attach warm pipeline; never block `initialize` > ~200 ms |
| `packages/pipeline/mcp_lifecycle.py` | `start_attach_warm_pipeline`, readiness flags, AST **bundle** hydrate (not full rebuild) |
| `packages/pipeline/engine.py` | Dummy-shape prewarm; expose `warm_ready` / `warm_elapsed_ms` |
| `packages/pipeline/server.py` | `/v1/warm/status`, ensure `/v1/embed/prewarm` records deadline |
| `packages/pipeline/context_trace.py` | Prefer bundle hydrate; background `bake_repo_bundle` if miss |
| `packages/pipeline/mcp_locate.py` | First locate joins warm ≤ remaining budget; no double `engine_warming` thrash when attach warm in flight |
| `packages/pipeline/memory_governor.py` | Audit: never demote while any client (incl. bridge) |
| `packages/pipeline/lifecycle_runtime.py` | Client coalesce already preserves bridge; add regression tests |
| `scripts/warm_contract_acceptance.py` | New: 10s warm + idle-then-ms gates |
| `tests/test_attach_warm_pipeline.py` | Unit/integration for pipeline + hold-warm |
| `docs/architecture/scubiee-reliability-issues.md` | New R8 row |

---

### Task 1: Define readiness contract + status fields

**Files:**
- Modify: `packages/pipeline/engine.py`
- Modify: `packages/pipeline/sync_status.py` (or status assembly in `mcp_locate.py`)
- Test: `tests/test_attach_warm_pipeline.py`

**Interfaces:**
- Produces: `warm_ready: bool`, `warm_phase: str`, `warm_elapsed_ms: float | None`, `warm_deadline_ms: int = 10000`
- Consumes: `embedder_is_loaded()`, engine `/health`, AST hydrate flag in process or shared stamp file

- [ ] **Step 1: Write failing tests for readiness helpers**

```python
def test_warm_ready_false_until_embed_and_health():
    from pipeline.warm_contract import WarmSnapshot, compute_warm_ready

    snap = WarmSnapshot(engine_healthy=True, embedder_loaded=False, ast_hydrated=True)
    assert compute_warm_ready(snap) is False

def test_warm_ready_true_when_all_set():
    from pipeline.warm_contract import WarmSnapshot, compute_warm_ready

    snap = WarmSnapshot(engine_healthy=True, embedder_loaded=True, ast_hydrated=True)
    assert compute_warm_ready(snap) is True

def test_map_can_skip_ast_for_ready():
    from pipeline.warm_contract import WarmSnapshot, compute_warm_ready

    # Map path may be ready without AST; pack needs ast_hydrated.
    snap = WarmSnapshot(engine_healthy=True, embedder_loaded=True, ast_hydrated=False)
    assert compute_warm_ready(snap, need_ast=False) is True
    assert compute_warm_ready(snap, need_ast=True) is False
```

- [ ] **Step 2: Run tests — expect FAIL (module missing)**

Run: `pytest tests/test_attach_warm_pipeline.py::test_warm_ready_false_until_embed_and_health -v`

- [ ] **Step 3: Add `packages/pipeline/warm_contract.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
import os

DEFAULT_WARM_DEADLINE_MS = 10_000


@dataclass(frozen=True)
class WarmSnapshot:
    engine_healthy: bool
    embedder_loaded: bool
    ast_hydrated: bool
    started_at: float | None = None
    elapsed_ms: float | None = None


def warm_deadline_ms() -> int:
    raw = (os.environ.get("CTX_WARM_DEADLINE_MS") or str(DEFAULT_WARM_DEADLINE_MS)).strip()
    try:
        return max(1000, int(float(raw)))
    except ValueError:
        return DEFAULT_WARM_DEADLINE_MS


def compute_warm_ready(snap: WarmSnapshot, *, need_ast: bool = False) -> bool:
    if not snap.engine_healthy or not snap.embedder_loaded:
        return False
    if need_ast and not snap.ast_hydrated:
        return False
    return True
```

- [ ] **Step 4: Surface fields on status/gate payloads** (`agent_ready` stays; add `warm_ready`, `warm_phase`)

- [ ] **Step 5: Run tests — expect PASS**

Run: `pytest tests/test_attach_warm_pipeline.py -k warm_ready -v`

- [ ] **Step 6: Commit** (only if user asked)

```bash
git add packages/pipeline/warm_contract.py tests/test_attach_warm_pipeline.py packages/pipeline/sync_status.py
git commit -m "feat: define 10s warm_ready contract fields"
```

---

### Task 2: Attach-time parallel warm pipeline (do not block MCP initialize)

**Files:**
- Modify: `packages/pipeline/mcp_bridge.py`
- Modify: `packages/pipeline/mcp_lifecycle.py`
- Test: `tests/test_attach_warm_pipeline.py`

**Interfaces:**
- Produces: `start_attach_warm_pipeline(repo) -> dict` (returns immediately; sets global start timestamp)
- Consumes: `ensure_daemon(..., wait_s=0)`, `/v1/embed/prewarm` wait=False then background join, AST hydrate kick

**Policy:** Keep MCP `initialize` / tools/list fast (myelin pattern). Warm runs in background but **must finish ≤ 10s**. First tool before ready: join remaining budget once (≤ leftover ms), else one `engine_warming` — never a second unpaid cold path after deadline.

- [ ] **Step 1: Failing test — pipeline sets started_at and kicks nonblocking ensure**

```python
def test_start_attach_warm_pipeline_returns_immediately(monkeypatch):
    import time
    from pipeline import mcp_lifecycle

    calls = []
    monkeypatch.setattr(
        mcp_lifecycle,
        "ensure_daemon",
        lambda *a, **k: calls.append(("ensure", time.perf_counter())) or {"ok": True},
    )
    # stub heavy bits
    monkeypatch.setattr(mcp_lifecycle, "_kick_embed_prewarm", lambda *a, **k: calls.append("embed"))
    monkeypatch.setattr(mcp_lifecycle, "_kick_ast_bundle_hydrate", lambda *a, **k: calls.append("ast"))

    t0 = time.perf_counter()
    out = mcp_lifecycle.start_attach_warm_pipeline(".")
    assert (time.perf_counter() - t0) < 0.5
    assert out.get("started") is True
```

- [ ] **Step 2: Implement `start_attach_warm_pipeline`**

```python
def start_attach_warm_pipeline(repo: Path | str) -> dict[str, Any]:
    """Kick cold warm at MCP attach. Never blocks > ~100ms on the attach thread."""
    root = Path(repo).resolve()
    mark_warm_start(root)  # store time.time() in process + optional stamp file under CTX_HOME
    try:
        from pipeline.daemon import ensure_daemon
        ensure_daemon(root, force_if_hung=False, spawn_owner="direct", wait_s=0.0, open_wait=False)
    except Exception as exc:  # noqa: BLE001
        _stderr(f"[scubiee] attach ensure kick: {exc}")
    _spawn_attach_warm_coordinator(root)  # waits health, then parallel embed + ast hydrate
    return {"ok": True, "started": True, "deadline_ms": warm_deadline_ms()}
```

Coordinator pseudocode (daemon thread):

```python
def _attach_warm_coordinator(root: Path) -> None:
    deadline = time.time() + warm_deadline_ms() / 1000.0
    # poll /health until up or deadline
    # then ThreadPoolExecutor(2):
    #   1) POST /v1/embed/prewarm {wait:True, sync:True}  # dummy encode inside
    #   2) hydrate_ast_bundle(root)  # pickle only; if miss, bake_repo_bundle in same thread
    # set warm_ready stamp; log elapsed_ms
```

- [ ] **Step 3: Call from `mcp_bridge.main()` immediately after `_register_bridge_anchor()`**

Also: if engine was down at register time, coordinator retries HTTP register of bridge client once healthy (already deferred locally).

- [ ] **Step 4: Default `CTX_MCP_ATTACH_WARM=1`** (new). Keep `CTX_MCP_AUTO_WARM` as legacy synonym for blocking connect warm — do **not** re-enable blocking attach.

- [ ] **Step 5: Tests PASS**

Run: `pytest tests/test_attach_warm_pipeline.py -k attach_warm -v`

---

### Task 3: Fast first encode (DML) inside prewarm

**Files:**
- Modify: `packages/pipeline/engine.py` (`prewarm_embedder`)
- Optional: ORT session options if fusion hangs (escape hatch only)
- Test: unit with monkeypatched embedder

**Research note:** DirectML compiles shaders on first inference per model/shape. Fixed dummy query already exists (`embed_one("scubiee prewarm")`). Ensure prewarm always runs that path on engine process only; measure `prewarm.ms` in status.

- [ ] **Step 1: Test that `prewarm_embedder` calls `embed_one` once**

```python
def test_prewarm_embedder_forces_dummy_encode(monkeypatch):
    from pipeline import engine as eng

    calls = []
    class FakeEmb:
        def embed_one(self, text, is_query=True):
            calls.append(text)
            return [0.0]
    class FakeEng:
        embedder = FakeEmb()
    monkeypatch.setattr(eng, "load_engine", lambda root: FakeEng())
    monkeypatch.setattr(eng, "embedder_is_loaded", lambda: False)
    out = eng.prewarm_embedder(".")
    assert calls and "prewarm" in calls[0]
    assert out["ok"] is True
```

- [ ] **Step 2: If live DML prewarm p95 > 8s alone, add env `CTX_DML_DISABLE_GRAPH_FUSION=1` mapping to `ep.dml.disable_graph_fusion`** (only if FastEmbed/ORT session construction is under our control; otherwise document as unsupported and keep dummy encode).

- [ ] **Step 3: Live probe after install:** cold stop → attach warm → assert `prewarm.ms` + health < 10s combined.

---

### Task 4: AST disk-bundle hydrate (not 800 MB preload)

**Files:**
- Modify: `packages/pipeline/context_trace.py`
- Modify: `packages/pipeline/mcp_lifecycle.py` (`_kick_ast_bundle_hydrate`)
- Test: `tests/test_repo_bundle_hydrate.py` (or extend attach warm tests)

**Interfaces:**
- Produces: `hydrate_ast_bundle(root) -> {"ok": bool, "source": "cache"|"bundle"|"baked", "ms": float}`
- Consumes: `_try_load_repo_bundle`, `_save_repo_bundle`, `_load_repo` only on miss

- [ ] **Step 1: Failing test — hydrate prefers bundle and sets in-process `_CACHE`**

```python
def test_hydrate_prefers_bundle(tmp_path, monkeypatch):
    from pipeline import context_trace as ct

    monkeypatch.setattr(ct, "_try_load_repo_bundle", lambda *a, **k: ("nodes", "graph", "lsp", "lex", None))
    # assert hydrate_ast_bundle fills _CACHE without calling full parse
```

- [ ] **Step 2: Implement hydrate that:**
  1. Returns immediately if `_CACHE` hit
  2. Else `_try_load_repo_bundle` → populate `_CACHE`
  3. Else `bake` via existing `_load_repo` **in background after warm_ready for map**, and set `ast_hydrated` when done (first pack may wait join ≤ 2s if bake already running from attach)

- [ ] **Step 3: Wire attach coordinator to call hydrate; leave `CTX_MCP_TRACE_PRELOAD` default off**

- [ ] **Step 4: On index/sync complete, refresh bundle so next Cursor open hits disk**

---

### Task 5: First locate joins warm instead of false cold

**Files:**
- Modify: `packages/pipeline/mcp_locate.py` (`_client_for` / `map_impl` / `search_impl`)
- Test: `tests/test_attach_warm_pipeline.py`

- [ ] **Step 1: When attach warm in flight and elapsed < deadline, `map` waits remaining budget for `embedder_loaded` instead of returning `engine_warming` immediately**

```python
def _join_attach_warm_if_needed(*, need_ast: bool) -> dict | None:
    # if warm_ready: return None
    # remaining = deadline - elapsed
    # if remaining <= 0: return warming_response()
    # poll/join embed (+ ast if need_ast) up to remaining
    # if ready: return None else warming_response()
```

- [ ] **Step 2: After deadline, at most one warming response; background continues; next call must hit hot path**

- [ ] **Step 3: Ban second full `ensure_daemon` thrash inside the same attach window (TTL already 20s — assert in test)**

---

### Task 6: Hold-warm audit (minutes/hours idle)

**Files:**
- Modify: `packages/pipeline/memory_governor.py` (only if gap found)
- Modify: `packages/pipeline/lifecycle_runtime.py` (tests)
- Test: `tests/test_lifecycle_runtime.py`

- [ ] **Step 1: Regression test — with `kind=bridge` client registered, `should_idle_stop` False after simulated 2h idle activity stamp**

```python
def test_bridge_client_holds_engine_for_hours(monkeypatch):
    from pipeline.lifecycle_runtime import register_client, should_idle_stop, note_activity
    register_client("mcp:cursor@bridge-1", pid=1, kind="bridge", host="cursor")
    note_activity()
    # advance last_activity conceptually by monkeypatching time if needed
    assert should_idle_stop() is False
```

- [ ] **Step 2: Test — `maybe_demote_idle` returns `hold_mcp_clients` while bridge present even if locate worker died**

- [ ] **Step 3: Test — only after unregister bridge + debounce does demote/stop arm**

- [ ] **Step 4: Fix any gap where worker leave clears `last_client_left_at` while bridge still active**

---

### Task 7: Optional proximity query→map cache (true “few ms”)

**Files:**
- Create or extend: `packages/pipeline/map_result_cache.py`
- Modify: `packages/pipeline/mcp_locate.py` map path
- Test: `tests/test_map_result_cache.py`

**Policy:** TTL default 120s; cosine/token Jaccard threshold; invalidate on corpus fingerprint change. Only for `map` (not pack bodies). Env `CTX_MAP_RESULT_CACHE=1` default on after Task 1–6 green.

- [ ] **Step 1: Unit test hit/miss/TTL/fingerprint**
- [ ] **Step 2: Implement cache; record `timing.cache=hit|miss`**
- [ ] **Step 3: Acceptance: identical map twice → second `< 50 ms` tool time

---

### Task 8: Acceptance scripts + reliability doc

**Files:**
- Create: `scripts/warm_contract_acceptance.py`
- Modify: `scripts/cold_start_acceptance.py` (tighten max to 10s for warm_ready)
- Modify: `docs/architecture/scubiee-reliability-issues.md` (R8)
- Release note: `packages/pipeline/upgrade_releases/v0_3_79.py` (or next)

- [ ] **Step 1: Script phases**

```text
1) scubiee halt / stop engine
2) start bridge attach warm (simulate mcp_bridge kick)
3) poll warm_ready ≤ 10s → PASS/FAIL
4) map once → wall ≤ 300ms (or first join within remaining budget then second ≤ 300ms)
5) sleep 120s (bridge client still registered)
6) map + 3-seed pack → wall SLAs B
7) unregister all clients; wait debounce; assert demote/stop armed
```

- [ ] **Step 2: Document R8 with measured numbers after local run**

- [ ] **Step 3: Ship note: attach warm, 10s deadline, bundle hydrate, hold-warm**

---

### Task 9: Quality + RAM verification

- [ ] `pytest tests/test_attach_warm_pipeline.py tests/test_lifecycle_runtime.py tests/test_multi_seed_v1.py -q`
- [ ] `python scripts/warm_contract_acceptance.py` after `uv tool install --force . --refresh`
- [ ] Process tree RSS: bridge ~30 MB, locate ≪ 800 MB, engine warm DML allowed ~1 GB; **total serve target still aspirational ≤800 MB — do not fail ship solely on engine ORT RSS** if SLAs A/B/C pass (document actual)
- [ ] Manual: open Cursor, wait ≤10s, map, wait 5 min, map again — second must feel instant

---

## Rollback

| Knob | Effect |
|------|--------|
| `CTX_MCP_ATTACH_WARM=0` | Old behavior: warm on first tool only |
| `CTX_WARM_DEADLINE_MS=15000` | Relax 10s gate while tuning DML |
| `CTX_MAP_RESULT_CACHE=0` | Disable proximity cache |
| `CTX_MCP_TRACE_PRELOAD=1` | Old RAM-heavy preload (escape only) |

## Out of scope

- Replacing DirectML with CPU-only (would shrink RSS, likely worsen first encode on this GPU profile)
- Changing Cursor’s MCP timeout
- Multi-repo simultaneous full warm (warm the **active** workspace first)

## Research anchors

- ORT DirectML: shapes known at session create; first eval compiles shaders — **dummy prewarm required**
- FastEmbed production: process singleton + startup dummy request
- MCP: respond to `initialize` immediately; warm in background; first tool joins if needed
- Warm daemon: keep model+index resident; idle unload only when no clients

## Success definition (user-facing)

1. Open Cursor → within **10 seconds** Scubiee is warm (`warm_ready=true`).
2. Any map/pack after that (even after long idle) returns in **ms-scale** while Cursor (or any other Scubiee client) stays open.
3. Close **all** tools → after debounce, engine unloads and RAM drops.

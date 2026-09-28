# Runtime Simplification (Approach 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status (2026-09-13):** Implemented in **0.3.80**. Cross-platform stack: sync `httpx` + `tenacity` (Win/macOS/Linux); host-agnostic `RuntimeController` for Cursor/Claude/Codex/Kiro/etc. Unit + MCP bridge probes green.

**Goal:** Collapse Scubiee warm/lifecycle into one `RuntimeController`, replace brittle `urllib` engine HTTP with `httpx` + `tenacity`, and cut dual warm flags/triggers so attach→ready→ms-steady is deterministic.

**Architecture:** One state machine owns DOWN/STARTING/READY/DEGRADED/STOPPING. Bridge calls `ensure(ATTACH)` once; locate calls `ensure(SERVE)` before map/pack; leave/debounce unload unchanged. Sync `httpx.Client` + tenacity retries with deadline budget. Delete overlapping warm helpers.

**Tech Stack:** Python 3.11+, `httpx`, `tenacity`, existing daemon/watchdog/FastEmbed, MCP bridge/locate.

**Spec:** `docs/superpowers/specs/2026-09-13-runtime-simplification-design.md`

## Global Constraints

- Product SLA unchanged: warm ≤10s; steady map ≤300ms / pack ≤800ms wall while clients>0; unload only after last client + debounce.
- Do **not** async-rewrite MCP or replace `composite_v1`.
- Do **not** load FastEmbed in bridge/locate (engine-only).
- Every task that adds a module must delete or thin an old path in the same task.
- Ship as **0.3.80**; keep `CTX_MCP_AUTO_WARM` as deprecated alias for one release.

## File map

| File | Responsibility |
|------|----------------|
| `packages/pipeline/runtime_controller.py` | **New** single lifecycle owner + ReadySnapshot |
| `packages/pipeline/engine_http.py` | **New** httpx+tenacity transport used by EngineClient |
| `packages/pipeline/client.py` | Thin facade over engine_http |
| `packages/pipeline/mcp_lifecycle.py` | Thin wrappers → RuntimeController; delete duplicate warm threads |
| `packages/pipeline/mcp_bridge.py` | Only `register` + `RuntimeController.ensure(ATTACH)` |
| `packages/pipeline/mcp_locate.py` | `ensure(SERVE)` before map/pack; drop ad-hoc join thrash |
| `packages/pipeline/warm_contract.py` | Keep snapshot helpers or fold into ReadySnapshot |
| `pyproject.toml` | Add `httpx`, `tenacity`; bump 0.3.80 |
| `tests/test_runtime_controller.py` | State machine + flag merge tests |
| `tests/test_engine_http.py` | Retry/timeout unit tests (respx or httpx mock transport) |
| `scripts/_probe_mcp_reliability_full.py` | Gate for ship |
| `docs/architecture/scubiee-reliability-issues.md` | R13 simplification |

---

### Task 1: Add deps + httpx/tenacity engine transport

**Files:**
- Modify: `pyproject.toml`
- Create: `packages/pipeline/engine_http.py`
- Modify: `packages/pipeline/client.py`
- Test: `tests/test_engine_http.py`

**Interfaces:**
- Produces: `EngineHttp.get_json(path, *, deadline_s=None) -> dict`, `EngineHttp.post_json(path, body, *, retry=False) -> dict`
- Consumes: `engine_url()`, env `CTX_ENGINE_HTTP_RETRIES`

- [ ] **Step 1: Add dependencies**

```toml
# pyproject.toml dependencies — append:
#   "httpx>=0.27",
#   "tenacity>=8.2",
```

- [ ] **Step 2: Failing tests for transient retry**

```python
def test_get_json_retries_connect_error(monkeypatch):
    import httpx
    from pipeline.engine_http import EngineHttp

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"ok": True, "embedder_loaded": True})

    transport = httpx.MockTransport(handler)
    http = EngineHttp(base_url="http://127.0.0.1:8765", transport=transport, retries=3)
    out = http.get_json("/health")
    assert out["ok"] is True
    assert calls["n"] == 3


def test_post_json_does_not_retry_by_default():
    import httpx
    from pipeline.engine_http import EngineHttp

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("boom", request=request)

    http = EngineHttp(base_url="http://127.0.0.1:8765", transport=httpx.MockTransport(handler), retries=3)
    try:
        http.post_json("/v1/embed/prewarm", {"wait": False})
        assert False, "expected raise"
    except httpx.ConnectError:
        pass
    assert calls["n"] == 1
```

- [ ] **Step 3: Implement `engine_http.py` (sync Client)**

```python
# packages/pipeline/engine_http.py — sketch
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type

class EngineHttp:
    def __init__(self, base_url: str, *, retries: int = 3, transport=None, timeout=None):
        self.base_url = base_url.rstrip("/")
        self.retries = retries
        self._client = httpx.Client(
            base_url=self.base_url,
            transport=transport,
            timeout=timeout or httpx.Timeout(connect=2.0, read=8.0, write=8.0, pool=2.0),
        )

    def get_json(self, path: str, *, deadline_s: float | None = None) -> dict:
        @retry(
            retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
            stop=stop_after_attempt(self.retries),
            wait=wait_exponential_jitter(initial=0.05, max=0.5),
            reraise=True,
        )
        def _once():
            r = self._client.get(path)
            r.raise_for_status()
            return r.json()
        return _once()

    def post_json(self, path: str, body: dict, *, retry: bool = False) -> dict:
        # retry=False by default (non-idempotent)
        ...
```

- [ ] **Step 4: Wire `EngineClient.health/get/post` through EngineHttp; keep public API stable**

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_engine_http.py -q`

- [ ] **Step 6: Commit** (when user asks)

```bash
git commit -m "feat: httpx+tenacity engine HTTP transport"
```

---

### Task 2: RuntimeController + ReadySnapshot

**Files:**
- Create: `packages/pipeline/runtime_controller.py`
- Modify or fold: `packages/pipeline/warm_contract.py`
- Test: `tests/test_runtime_controller.py`

**Interfaces:**
- Produces:
  - `class ReadySnapshot: engine_ok: bool; embedder_loaded: bool; ast_ready: bool; state: str; elapsed_ms: float | None`
  - `RuntimeController.ensure(repo, reason: Literal["attach","serve","leave"], *, need_ast: bool=False) -> ReadySnapshot`
  - `RuntimeController.snapshot() -> ReadySnapshot`
- Consumes: `ensure_daemon`, `EngineHttp`, `hydrate_ast_bundle` (locate only)

- [ ] **Step 1: Failing state tests**

```python
def test_ensure_attach_is_singleflight(monkeypatch, tmp_path):
    from pipeline.runtime_controller import RuntimeController
    rt = RuntimeController()
    n = {"ensure": 0}
    monkeypatch.setattr(rt, "_spawn_engine", lambda *a, **k: n.__setitem__("ensure", n["ensure"]+1) or {"ok": True})
    monkeypatch.setattr(rt, "_wait_ready", lambda *a, **k: rt._mark_ready())
    rt.ensure(tmp_path, "attach")
    rt.ensure(tmp_path, "attach")
    assert n["ensure"] == 1


def test_attach_warm_alias_from_legacy_auto_warm(monkeypatch):
    from pipeline.runtime_controller import attach_warm_enabled
    monkeypatch.delenv("CTX_MCP_ATTACH_WARM", raising=False)
    monkeypatch.setenv("CTX_MCP_AUTO_WARM", "1")
    assert attach_warm_enabled() is True
    monkeypatch.setenv("CTX_MCP_AUTO_WARM", "0")
    monkeypatch.setenv("CTX_MCP_ATTACH_WARM", "0")
    assert attach_warm_enabled() is False
```

- [ ] **Step 2: Implement controller**

Behavior:
- `attach`: if disabled skip; else singleflight spawn + poll health via EngineHttp until READY or deadline; kick embed prewarm POST once; if process is locate (`not CTX_MCP_BRIDGE`), hydrate AST bundle (bake_on_miss in background only)
- `serve`: if READY return; else join remaining deadline; for `need_ast` hydrate with bake_on_miss=True
- `leave`: stop heartbeat; unregister; do not spawn

- [ ] **Step 3: Status fields come only from `snapshot()`** — ban hand-rolled contradictory warm flags

- [ ] **Step 4: Tests pass**

Run: `pytest tests/test_runtime_controller.py -q`

---

### Task 3: Thin mcp_lifecycle / bridge / locate to controller

**Files:**
- Modify: `packages/pipeline/mcp_lifecycle.py`
- Modify: `packages/pipeline/mcp_bridge.py`
- Modify: `packages/pipeline/mcp_locate.py`
- Modify: `tests/test_mcp_lazy_warm.py`, `tests/test_attach_warm_pipeline.py`

**Delete in this task:**
- `_spawn_background_warm` OR make it call `ensure("attach")` only
- Duplicate `_attach_warm_coordinator` body (move into controller)
- Separate `start_attach_warm_pipeline` public API → alias to `RuntimeController.ensure(..., "attach")`

- [ ] **Step 1: Update lazy tests — attach warm default on; `CTX_MCP_ATTACH_WARM=0` for pure lazy**

- [ ] **Step 2: Bridge `main`:**

```python
from pipeline.runtime_controller import RuntimeController
_register_bridge_anchor()
RuntimeController.get().ensure(repo, "attach")
McpBridge().run()
```

- [ ] **Step 3: `_client_for` / pack path:**

```python
snap = RuntimeController.get().ensure(repo, "serve", need_ast=False)  # map
if not snap.embedder_loaded:
    return _WarmingClient(...)
# pack:
RuntimeController.get().ensure(repo, "serve", need_ast=True)
```

- [ ] **Step 4: Remove dead helpers; keep thin wrappers for import stability**

- [ ] **Step 5: Run**

Run: `pytest tests/test_attach_warm_pipeline.py tests/test_mcp_lazy_warm.py tests/test_lifecycle_runtime.py tests/test_runtime_controller.py -q`

---

### Task 4: Status honesty + demote policy audit

**Files:**
- Modify: `packages/pipeline/mcp_locate.py` status payload assembly
- Modify: `packages/pipeline/memory_governor.py` only if needed
- Test: extend `tests/test_runtime_controller.py`

- [ ] **Step 1: `warm_ready` iff snapshot.engine_ok and snapshot.embedder_loaded**

- [ ] **Step 2: Regression — bridge client holds demote for simulated 2h**

- [ ] **Step 3: Never set warm_ready true when health embedder_loaded false**

---

### Task 5: Ship gate + docs + 0.3.80

**Files:**
- Create: `packages/pipeline/upgrade_releases/v0_3_80.py`
- Modify: `packages/pipeline/upgrade_releases/__init__.py`, `pyproject.toml` version
- Modify: `docs/architecture/scubiee-reliability-issues.md` (R13)
- Modify: `scripts/_probe_mcp_reliability_full.py` assert `warm_ready` consistent

- [ ] **Step 1: Release notes — one lifecycle owner; httpx+tenacity; AUTO_WARM alias**

- [ ] **Step 2: `uv tool install --force . --refresh`**

- [ ] **Step 3: Acceptance**

```bash
pytest tests/test_engine_http.py tests/test_runtime_controller.py tests/test_attach_warm_pipeline.py tests/test_mcp_lazy_warm.py tests/test_lifecycle_runtime.py tests/test_reliability_master_plan.py -q
python scripts/warm_contract_acceptance.py --no-stop --idle-s 5
python scripts/_probe_mcp_reliability_full.py
```

Expected: all PASS; map2 ≤300ms; pack2 ≤800ms; no status contradiction.

- [ ] **Step 4: Manual — reload Cursor MCP; gate/status/map once**

---

## Rollback

| Knob | Effect |
|------|--------|
| `CTX_MCP_ATTACH_WARM=0` | No attach kick (old agent-first) |
| `CTX_ENGINE_HTTP_TRANSPORT=urllib` | Escape hatch if httpx regresses (optional; only if needed) |
| Reinstall 0.3.79 | Full rollback |

## Out of scope

- Async MCP server
- Replacing watchdog with supervisord/systemd
- Model/backend swap away from FastEmbed DML

## Research anchors

- httpx split timeouts + connection reuse
- tenacity: retry transient only + exponential jitter; cap to SLA budget
- Single supervisor/owner pattern for lifecycle (no competing start policies)

# CE Operator Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `ctx dashboard` — a clean light localhost operator UI to manage admission, repos, missing/delete validation, indexes, health, runtime, storage, and graph.

**Architecture:** A dedicated loopback HTTP process (uncommon private port + `/ce-dashboard`) serves static shadcn-like light UI and JSON APIs that wrap existing `repo_lifecycle`, registry/`project_id`, doctor/certify, sync_status, storage_policy, and load-only accel/runtime state. Presence validation separates Missing from true delete before Forget.

**Tech Stack:** Python stdlib HTTP server, existing pipeline modules, static HTML/CSS/JS (no heavy SPA framework required for v1), pytest.

## Global Constraints

- Bind `127.0.0.1` only; base path `/ce-dashboard`; private port range `49152–65535`.
- Light Apple/Google-like UI; shadcn-style components; no dark-theme redesign of the new shell.
- Missing ≠ deleted; Forget requires validation + typed confirm.
- Admission modes: `automatic` | `mcp_cli` (Manual); dashboard Settings must toggle them.
- Do not expose dashboard on LAN; mutating APIs refuse non-loopback.
- Reuse lifecycle/doctor/storage APIs; do not reimplement indexing.
- Work only in `.worktrees/ce-dashboard` on `feat/ce-dashboard`.

---

### Task 1: Stable uncommon port + dashboard process lock

**Files:**
- Create: `packages/pipeline/dashboard_port.py`
- Create: `tests/test_dashboard_port.py`

**Interfaces:**
- Produces: `preferred_dashboard_port(seed: str) -> int`, `allocate_dashboard_port(seed: str, *, preferred: int | None = None) -> int`, `DashboardLock` with `path`, `acquire(url, pid)`, `read()`, `release_if_owner(pid)`
- Lock file: `~/.context-engine/dashboard.json` fields `{host, port, url, pid, started_at}`

- [ ] **Step 1: Write failing tests**

```python
from pipeline.dashboard_port import preferred_dashboard_port, allocate_dashboard_port, DashboardLock

def test_preferred_port_stable_and_private():
    a = preferred_dashboard_port("ce-install-1")
    b = preferred_dashboard_port("ce-install-1")
    assert a == b
    assert 49152 <= a <= 65535

def test_allocate_skips_busy_port(monkeypatch):
    preferred = preferred_dashboard_port("seed")
    busy = {preferred}

    def fake_bind(port: int) -> bool:
        return port not in busy

    monkeypatch.setattr("pipeline.dashboard_port._port_free", fake_bind)
    got = allocate_dashboard_port("seed", preferred=preferred)
    assert got != preferred
    assert 49152 <= got <= 65535
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_dashboard_port.py -q`

Expected: FAIL (module missing).

- [ ] **Step 3: Implement port helpers + lock**

Implement hash-stable preferred port in range, probe free ports upward with wrap, and atomic JSON lock file helpers.

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_dashboard_port.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/pipeline/dashboard_port.py tests/test_dashboard_port.py
git commit -m "feat: stable uncommon localhost port for CE dashboard"
```

---

### Task 2: Presence validation (moved / replaced / deleted)

**Files:**
- Create: `packages/pipeline/repo_presence.py`
- Create: `tests/test_repo_presence.py`
- Modify: `packages/pipeline/repo_lifecycle.py` (list enrichment only if needed)

**Interfaces:**
- Produces: `PresenceReport` dataclass with `state: Literal["active","missing","replaced","conflict"]`, `project_id`, `last_path`, `live_path`, `reasons: list[str]`, `forget_allowed: bool`
- Produces: `assess_presence(project_id: str, paths: list[str], *, now: float | None = None, missing_since: float | None = None, retention_s: float = 86400) -> PresenceReport`

Rules:
- No path exists + ID file absent → `missing`; `forget_allowed` only if missing_since retention elapsed
- Path exists + matching `id.json` → `active`
- Path exists + different/missing id → `replaced`/`conflict`; `forget_allowed=False`
- Never set forget_allowed on transient missing without retention

- [ ] **Step 1: Write failing tests**

```python
from pipeline.repo_presence import assess_presence

def test_missing_path_is_not_forgettable_immediately(tmp_path):
    report = assess_presence("ce_x", [str(tmp_path / "gone")], missing_since=None, retention_s=86400)
    assert report.state == "missing"
    assert report.forget_allowed is False

def test_missing_past_retention_is_purge_eligible(tmp_path):
    report = assess_presence(
        "ce_x",
        [str(tmp_path / "gone")],
        missing_since=0.0,
        retention_s=1,
        now=10.0,
    )
    assert report.state == "missing"
    assert report.forget_allowed is True

def test_path_with_different_id_is_replaced(tmp_path):
    root = tmp_path / "repo"
    (root / ".context-engine").mkdir(parents=True)
    (root / ".context-engine" / "id.json").write_text('{"project_id":"other"}', encoding="utf-8")
    report = assess_presence("ce_x", [str(root)])
    assert report.state in {"replaced", "conflict"}
    assert report.forget_allowed is False
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_repo_presence.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement `repo_presence.py`**

Read `.context-engine/id.json` via existing project_id helpers when possible.

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_repo_presence.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/pipeline/repo_presence.py tests/test_repo_presence.py
git commit -m "feat: validate missing vs replaced before repo forget"
```

---

### Task 3: Lifecycle actions for dashboard (clear index, forget, locate)

**Files:**
- Modify: `packages/pipeline/repo_lifecycle.py`
- Create: `tests/test_repo_lifecycle_dashboard_actions.py`

**Interfaces:**
- Produces: `clear_index_repo(root|project_id) -> dict` (delete store, keep registry identity)
- Produces: `forget_repo(project_id, *, confirm: str, force: bool = False) -> dict` (requires confirm == project_id or basename; checks presence.forget_allowed unless force from validated path)
- Produces: `locate_repo(project_id, new_path) -> dict` (reattach if id matches)
- Extends: `list_managed_repos()` to include `presence`, `forget_allowed`, primary path existence

- [ ] **Step 1: Write failing tests**

```python
def test_clear_index_keeps_registry(tmp_path, monkeypatch):
    # initialize fixture repo, clear index, assert projects/<id> gone but registry row remains
    ...

def test_forget_requires_confirm_and_eligibility(tmp_path):
    # missing but not eligible -> error; with confirm+eligible -> removed + store gone
    ...

def test_locate_reattaches_matching_id(tmp_path):
    ...
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_repo_lifecycle_dashboard_actions.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement lifecycle helpers**

Wire through `projects_root()`, `resolve_project`, existing `remove_repo`, and presence checks.

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_repo_lifecycle_dashboard_actions.py tests/test_repo_lifecycle.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/pipeline/repo_lifecycle.py tests/test_repo_lifecycle_dashboard_actions.py
git commit -m "feat: clear-index locate and confirmed forget lifecycle actions"
```

---

### Task 4: Dashboard HTTP API + background server

**Files:**
- Create: `packages/pipeline/dashboard_server.py`
- Create: `tests/test_dashboard_api.py`
- Modify: `packages/pipeline/__main__.py` (CLI `dashboard`)
- Modify: `packages/pipeline/server.py` (optional redirect note at old `/dashboard`)

**Interfaces:**
- Produces: `start_dashboard(*, open_browser: bool = True) -> dict`, `stop_dashboard() -> dict`, `dashboard_status() -> dict`
- Routes under `/ce-dashboard/api/*` as in the design spec
- CLI: `python -m pipeline dashboard [--no-open|--status|stop]`

- [ ] **Step 1: Write failing API/CLI tests**

```python
def test_overview_requires_loopback(tmp_path):
    ...

def test_settings_toggles_admission_mode(tmp_path):
    ...

def test_forget_route_requires_confirm(tmp_path):
    ...
```

- [ ] **Step 2: Run tests to verify failure**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_dashboard_api.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement server + CLI**

Reuse doctor/certify/list/settings; serve placeholder HTML string initially if UI assets not yet present (`Dashboard running` page ok until Task 5).

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_dashboard_api.py tests/test_dashboard_port.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/pipeline/dashboard_server.py packages/pipeline/__main__.py packages/pipeline/server.py tests/test_dashboard_api.py
git commit -m "feat: ctx dashboard localhost API and process control"
```

---

### Task 5: Light operator UI (sidebar shell + core pages)

**Files:**
- Create: `packages/pipeline/dashboard_ui/index.html`
- Create: `packages/pipeline/dashboard_ui/app.js`
- Create: `packages/pipeline/dashboard_ui/styles.css`
- Modify: `packages/pipeline/dashboard_server.py` (serve static)
- Replace or wrap: `packages/pipeline/dashboard.py` (keep old dark page as legacy `/dashboard` or redirect)

**Interfaces:**
- UI calls Task 4 APIs only
- Pages: Overview, Repositories (with actions), Index & Sync, Storage, Health, Runtime, Graph stub, Settings (Auto/Manual)

- [ ] **Step 1: Write a lightweight UI contract test**

```python
def test_ce_dashboard_index_served():
    # start handler or read file; assert sidebar labels and /ce-dashboard path markers exist
    html = (Path("packages/pipeline/dashboard_ui/index.html").read_text(encoding="utf-8"))
    assert "Repositories" in html
    assert "Automatic" in html or "admission" in html.lower()
```

- [ ] **Step 2: Run test to verify failure**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_dashboard_ui_contract.py -q`

Expected: FAIL.

- [ ] **Step 3: Implement light static UI**

Clean white layout; table of repos; dialogs for Forget confirm; Settings radio Auto vs Manual.

- [ ] **Step 4: Run tests to verify pass**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_dashboard_ui_contract.py tests/test_dashboard_api.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/pipeline/dashboard_ui packages/pipeline/dashboard_server.py packages/pipeline/dashboard.py tests/test_dashboard_ui_contract.py
git commit -m "feat: clean light CE operator dashboard UI"
```

---

### Task 6: Graph page + operator runbook + regression

**Files:**
- Modify: `packages/pipeline/dashboard_ui/*` (Graph page)
- Modify: `packages/pipeline/dashboard_server.py` (`/api/graph/{id}`)
- Modify: `docs/reindexing/production-operator-runbook.md`
- Test: extend `tests/test_dashboard_api.py`

**Interfaces:**
- Graph API returns nodes/edges from existing graph artifacts for a project (read-only)
- Runbook documents `ctx dashboard`, Missing vs Forget, Auto vs Manual

- [ ] **Step 1: Write failing graph API test**

```python
def test_graph_api_returns_nodes_for_indexed_repo(tmp_path):
    ...
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_dashboard_api.py::test_graph_api_returns_nodes_for_indexed_repo -q`

Expected: FAIL.

- [ ] **Step 3: Implement graph read + UI canvas + docs**

Keep visualization simple (SVG/canvas force layout or static list+links); polish later ok if readable.

- [ ] **Step 4: Full dashboard regression**

Run: `PYTHONPATH=packages PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_dashboard_port.py tests/test_repo_presence.py tests/test_repo_lifecycle_dashboard_actions.py tests/test_dashboard_api.py tests/test_dashboard_ui_contract.py -q`

Expected: PASS.

Manual: `python -m pipeline dashboard --no-open` then curl overview; `stop`.

- [ ] **Step 5: Commit**

```bash
git add packages/pipeline/dashboard_ui packages/pipeline/dashboard_server.py docs/reindexing/production-operator-runbook.md tests
git commit -m "feat: dashboard graph view and operator docs"
```

---

## Spec coverage check

| Spec requirement | Task |
|------------------|------|
| Uncommon localhost port + `/ce-dashboard` | 1, 4 |
| Background start/status/stop | 4 |
| Missing validation before delete | 2, 3 |
| Unmanage / clear index / forget confirm | 3, 4, 5 |
| Auto vs Manual admission | 4, 5 |
| Overview/health/runtime/storage/sync | 4, 5 |
| Graph page | 6 |
| Light shadcn-like UI | 5 |

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-17-ce-operator-dashboard.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between tasks  
2. **Inline Execution** — execute tasks in this session with checkpoints  

Which approach?

# CE Production Hardening Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete and verify the localhost operator dashboard and its supporting production runtime path, retaining the existing bounded read-only Graph feature.

**Architecture:** Keep the stdlib loopback dashboard server and static UI. Stabilize the current uncommitted Task 6 and UI-polish changes, make the static asset contract explicit, and prove process lifecycle and API behavior through deterministic tests and a short live smoke cycle.

**Tech Stack:** Python stdlib HTTP server, static HTML/CSS/JS, Lucide UMD bundle, pytest, PowerShell.

## Global Constraints

- Bind `127.0.0.1` only; base path `/ce-dashboard`; private port range `49152–65535`.
- Light Apple/Google-like UI; shadcn-style components; no dark-theme redesign.
- Missing ≠ deleted; Forget requires eligibility + typed project ID confirmation.
- Admission modes remain exactly `automatic` and `mcp_cli`.
- Reuse lifecycle, doctor, runtime, and storage APIs; do not reimplement indexing.
- Graph remains read-only and bounded: SVG shows at most 60 nodes and list shows at most 100 links, with truthful copy.
- Do not add a React/Vite application or expose the dashboard on LAN.

---

### Task 1: Stabilize static UI asset and contract compatibility

**Files:**
- Modify: `packages/pipeline/dashboard_server.py`
- Modify: `packages/pipeline/dashboard_ui/styles.css`
- Modify: `tests/test_dashboard_ui_contract.py`
- Add: `packages/pipeline/dashboard_ui/lucide.min.js` (vendored Lucide UMD)

**Interfaces:**
- `GET /ce-dashboard/lucide.min.js` returns JavaScript with a successful response.
- Existing CSS compatibility token `--surface` aliases the card surface token so current consumers/tests do not regress.

- [ ] **Step 1: Extend the UI contract test**

Add assertions that the served dashboard HTML references the local Lucide asset, the static asset response is JavaScript and non-empty, and the CSS declares both `--surface:` and `--card:`.

```python
lucide = _request(server_url, "/ce-dashboard/lucide.min.js")
assert lucide.status == 200
assert "javascript" in lucide.headers["Content-Type"]
assert len(lucide.read()) > 1000
assert "--surface:" in css
assert "--card:" in css
```

- [ ] **Step 2: Run the focused contract test**

Run:

```powershell
$env:PYTHONPATH='packages'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest tests/test_dashboard_ui_contract.py -q
```

Expected: FAIL because the shadcn token rewrite removed `--surface:`.

- [ ] **Step 3: Implement the compatibility alias and static asset allowlist**

In `styles.css`, add:

```css
--surface: var(--card);
```

In `_STATIC_ASSETS` in `dashboard_server.py`, retain:

```python
f"{DASHBOARD_BASE}/lucide.min.js": (
    "lucide.min.js",
    "application/javascript; charset=utf-8",
),
```

Keep `index.html` loading only `/ce-dashboard/lucide.min.js`; do not reintroduce external font or icon CDNs.

- [ ] **Step 4: Run focused verification**

Run the Task 1 command again.

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add packages/pipeline/dashboard_server.py packages/pipeline/dashboard_ui/index.html packages/pipeline/dashboard_ui/styles.css packages/pipeline/dashboard_ui/lucide.min.js tests/test_dashboard_ui_contract.py
git commit -m "fix: harden dashboard static UI assets"
```

---

### Task 2: Finish Graph safely as a bounded read-only feature

**Files:**
- Modify: `packages/pipeline/dashboard_server.py`
- Modify: `packages/pipeline/dashboard_ui/app.js`
- Modify: `packages/pipeline/dashboard_ui/index.html`
- Modify: `packages/pipeline/dashboard_ui/styles.css`
- Modify: `tests/test_dashboard_api.py`

**Interfaces:**
- `GET /ce-dashboard/api/graph/{project_id}` returns `{"ok": true, "project_id": ..., "nodes": list, "edges": list}` from existing Graphify artifact data.
- The endpoint never writes an artifact.
- The UI renders at most 60 nodes and lists at most 100 links, reporting both bounds truthfully.

- [ ] **Step 1: Preserve the graph API behavior test**

Ensure `test_graph_api_returns_nodes_for_indexed_repo` creates an existing artifact, requests the graph endpoint, asserts graph nodes/edges are returned, then compares the artifact content before and after the request.

```python
before = graph_path.read_text(encoding="utf-8")
response = _json_request(server_url, f"/ce-dashboard/api/graph/{project_id}")
assert response["nodes"] == graph["nodes"]
assert response["edges"] == graph["links"]
assert graph_path.read_text(encoding="utf-8") == before
```

- [ ] **Step 2: Run the focused Graph test**

Run:

```powershell
$env:PYTHONPATH='packages'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest tests/test_dashboard_api.py::test_graph_api_returns_nodes_for_indexed_repo -q
```

Expected: PASS.

- [ ] **Step 3: Verify bounds and truthful UI copy**

Keep the existing implementation structure:

```javascript
const nodes = allNodes.slice(0, 60);
const renderedLinks = allEdges.slice(0, 100);
$("#graph-status").textContent = [
  nodes.length < allNodes.length
    ? `Showing 60 of ${allNodes.length} nodes`
    : `Showing ${allNodes.length} nodes`,
  allEdges.length > 100
    ? `listing 100 of ${allEdges.length} links`
    : `listing ${allEdges.length} links`,
].join("; ") + ".";
```

Do not add interaction or layout algorithms beyond the current bounded SVG.

- [ ] **Step 4: Run API and JavaScript verification**

Run:

```powershell
$env:PYTHONPATH='packages'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest tests/test_dashboard_api.py -q
node --check packages/pipeline/dashboard_ui/app.js
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add packages/pipeline/dashboard_server.py packages/pipeline/dashboard_ui/app.js packages/pipeline/dashboard_ui/index.html packages/pipeline/dashboard_ui/styles.css tests/test_dashboard_api.py
git commit -m "feat: add read-only dashboard graph view"
```

---

### Task 3: Verify operator lifecycle and production release evidence

**Files:**
- Modify: `docs/reindexing/production-operator-runbook.md`
- Modify: `.superpowers/sdd/2026-08-17-ce-operator-dashboard/progress.md`
- Add: `.superpowers/sdd/2026-08-17-ce-operator-dashboard/production-hardening-report.md`

**Interfaces:**
- `python -m pipeline dashboard --no-open`, `--status`, and `stop` must form a successful lifecycle on loopback.
- Required regression suite must pass without failures.
- Runbook commands must match verified behavior.

- [ ] **Step 1: Add a restart-safe lifecycle test if absent**

Extend `tests/test_dashboard_api.py` only when existing coverage does not already perform:

```python
first = _run_dashboard("--no-open")
status = _run_dashboard("--status")
assert status["running"] is True
assert status["host"] == "127.0.0.1"
assert status["url"].endswith("/ce-dashboard")
stopped = _run_dashboard("stop")
assert stopped["stopped"] is True
```

The test must clean up with `stop` in `finally`.

- [ ] **Step 2: Run full production dashboard regression**

Run:

```powershell
$env:PYTHONPATH='packages'
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest tests/test_dashboard_port.py tests/test_repo_presence.py tests/test_repo_lifecycle_dashboard_actions.py tests/test_dashboard_api.py tests/test_dashboard_ui_contract.py -q
```

Expected: PASS with no test failures.

- [ ] **Step 3: Run live lifecycle smoke**

Run:

```powershell
$env:PYTHONPATH='packages'
python -m pipeline dashboard --no-open
python -m pipeline dashboard --status
python -c "import json, urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:<PORT>/ce-dashboard/api/overview'))['ok'])"
python -m pipeline dashboard stop
```

Substitute `<PORT>` with the port emitted by `--status`. Verify status says `host: 127.0.0.1`, overview prints `True`, and stop reports success.

- [ ] **Step 4: Update release evidence**

Append an explicit completion record to `progress.md`: Task 6 reviewed and complete, the CSS contract repaired, regression count/result, and smoke start/status/overview/stop result. Write the same commands and outcomes to `production-hardening-report.md`.

- [ ] **Step 5: Commit**

```powershell
git add docs/reindexing/production-operator-runbook.md .superpowers/sdd/2026-08-17-ce-operator-dashboard
git commit -m "docs: record dashboard production verification"
```

---

### Task 4: Whole-branch review and release handoff

**Files:**
- Modify only if review finds a concrete defect.

**Interfaces:**
- Branch is clean, all release commits are on `feat/ce-dashboard`, and no dashboard process is left running.

- [ ] **Step 1: Request a whole-branch review**

Use a reviewer against the merge base with `feat/production-certification`. Scope includes dashboard, production-hardening commits, and no unrelated files.

- [ ] **Step 2: Address any Critical or Important findings**

For each finding, add a focused regression test before the minimal fix, then rerun the affected test and the full regression from Task 3.

- [ ] **Step 3: Verify clean release state**

Run:

```powershell
git status -sb
$env:PYTHONPATH='packages'
python -m pipeline dashboard --status
```

Expected: clean branch; dashboard not running (or stop it).

- [ ] **Step 4: Final commit if review produced a fix**

```powershell
git add <reviewed-files>
git commit -m "fix: address dashboard release review"
```

## Spec coverage self-review

- Main dashboard lifecycle: Task 3.
- Static UI / local asset reliability: Task 1.
- Graph keep-as-is/read-only/bounded: Task 2.
- Presence/lifecycle/settings/health/runtime/storage: Task 3 full regression covers their existing dashboard suites.
- Committed, reviewable, PR-ready branch: Task 4.
- No React rewrite/LAN exposure/new Graph scope: global constraints applied to all tasks.

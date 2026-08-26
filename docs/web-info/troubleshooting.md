# Troubleshooting

Symptom → cause → fix. Start with `scubiee doctor .` and `scubiee preflight .`.  
Shareable report: `scubiee diagnose --no-tests --desktop` → `Desktop/scubiee-diagnose.json`.

---

## Quick triage order

```bash
scubiee --version
scubiee setup --status
scubiee preflight .
scubiee doctor .
scubiee list
scubiee diagnose --no-tests --desktop
```

If semantic preflight fails: `scubiee setup --repair` then retry.

---

## Install sequence mistakes (most common)

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Agent `status()` → `managed: false` | Never ran `init` and/or `connect` | `scubiee init .` then `scubiee connect --cursor` (reload MCP) |
| Index exists but MCP missing | Ran `init` only | `scubiee connect --…` |
| Kiro / Copilot / Cline / Roo “MCP doesn’t work” | Connected only globally | `cd` into **that** project → `scubiee connect --kiro` (etc.) |
| Agent polls `status()` every turn | Old rule template | Re-run `scubiee connect` to refresh rules |
| Hint says `scubiee wake` | Old build / old rule | Use **`scubiee resume`**; upgrade + reconnect |

Correct order: **setup → init → connect → reload IDE**.

---

## `machine_not_setup` on `init`

**Symptom:**

```json
{"ok": false, "error": "machine_not_setup"}
```

**Cause:** No saved profile in `~/.context-engine/accel.json`.

**Fix:**

```bash
scubiee setup --repair
scubiee setup --status
```

---

## Diagnose looks healthy but `init` still fails (after reinstall)

**Symptom:** `acceleration.profile` and `texts_per_sec` look fine; `libraries.fastembed` / `onnxruntime` are null; `init` or preflight fails.

**Cause:** Stale `accel.json` left from a previous setup while packages were wiped by a broken upgrade.

**Fix:**

```bash
scubiee setup --repair
scubiee diagnose --no-tests --desktop   # should no longer be “stale”
scubiee init .
```

---

## Access denied on `uv tool install --force` (Windows)

**Symptom:** Cannot replace files under `%APPDATA%\uv\tools\scubiee\Scripts`; afterward `No module named 'pipeline'` or broken CLI.

**Cause:** `ContextEngineSupervisor` / daemon / Cursor MCP still locking the uv tool Python.

**Fix:**

```powershell
scubiee stop
# Task Manager → end ContextEngineSupervisor if still present
# Quit Cursor (or disable Scubiee MCP)
Remove-Item -Recurse -Force "$env:APPDATA\uv\tools\scubiee" -ErrorAction SilentlyContinue
uv tool install --force scubiee==0.2.82 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
```

Also see [Uninstall on Windows](./uninstall-windows.md). Prefer `scubiee upgrade` (stops processes first) when available.

---

## Install & setup

### `No module named 'fastembed'` during setup / init

**Fix:**

```bash
scubiee setup --repair
```

Windows base wheel does not always ship FastEmbed; repair installs platform extras.

---

### Preflight fails: missing `fastembed` / `onnxruntime` / `not_configured`

**Fix:**

```bash
scubiee setup --repair
scubiee preflight .
```

Lexical-only:

```bash
scubiee preflight . --lexical-only
```

---

### Setup picks DirectML on a laptop with only Intel UHD / AMD “Radeon Graphics”

**Expected on older builds; on current builds:** Intel iGPU / AMD APU graphics are **not** used for DirectML. Profile should be **`cpu`**. Discrete AMD/NVIDIA → **`dml`**.

If stuck on a bad DML profile:

```bash
scubiee setup --profile cpu --repair
```

Escape hatch for a missed discrete AMD GPU: `scubiee setup --profile dml --repair`.

---

### Apple Silicon stuck on `cpu`

**Not expected.** Run:

```bash
scubiee setup --repair
scubiee setup --status   # should show mlx
```

If you forced CPU: `scubiee setup --profile mlx --repair` (or `--repair` alone to promote back).

---

### Profile is `dml` but embed uses CPU / missing `DmlExecutionProvider`

**Fix:**

```bash
scubiee setup --repair
```

If still broken, purge ORT wheels — see [Windows guide](./windows.md).

---

### `onnxruntime has no attribute SessionOptions`

Conflicting/partial ORT install. Quit Cursor, `scubiee stop`, delete leftover `onnxruntime` under the uv tool `site-packages`, then `scubiee setup --repair`.

---

### faiss `cannot import name 'class_wrappers'`

Incomplete `faiss-cpu` extract (Windows uv). Run `scripts/repair-uv-scubiee.ps1` or see [Windows guide](./windows.md).

---

### `failed to locate pyvenv.cfg`

Broken uv tool directory. Quit Cursor → [Uninstall on Windows](./uninstall-windows.md) or repair script → reinstall.

---

### Two Pythons on PATH (`pip` ≠ `scubiee`)

Read `scubiee --version` — use **that** Python’s pip/uv, not conda’s.

---

## Indexing & init

### Refusing to index home directory

**Expected.** `cd` to the project root. See [Indexing & projects](./indexing-and-projects.md).

---

### `">400 files need indexing"`

Safety gate. Use `--confirm` or `--fast --roots …`.

---

### `never_index` error

Path was blocked with `scubiee never-index`. Clear via dashboard forget or lifecycle remove.

---

### project_id_mismatch / stale home registration

```bash
scubiee list
scubiee remove C:\Users\YOUR_USER --delete-store
# delete leftover id.json under home if present
```

---

## MCP, agent status, pause

### MCP red / not connecting

1. `scubiee engine ensure . --wait 45`
2. `scubiee connect --cursor` (rewrites mcp.json + rules)
3. Reload MCP in the IDE
4. `scubiee stop` then retry if zombies remain

---

### Agent `status()`: `warming: true`, `ok: false`

Daemon is starting or temporarily down. **Use MCP tools** (they may return warming once). Wait ~5s and retry the **tool** once. Do **not** call `status()` every turn.

When healthy: `managed: true`, `ok: true`, `warming: false`.

---

### Agent fell back to native Grep forever

1. Confirm MCP server is green  
2. Re-run `scubiee connect --cursor` (refreshes rules — event-driven retry, not “ignore forever”)  
3. After mid-session `init`, ask the agent to call `status()` again once  

---

### Paused / stopped — agent tells you to `wake`

Use:

```bash
scubiee resume
# or per-repo:
scubiee resume .
```

---

### Search misses fresh edits

```bash
scubiee sync .
```

Test with a unique token in a **`.py`** file that is in scope.

---

## Dashboard & daemon

### Dashboard unhealthy on Windows

Upgrade to current scubiee; see [Dashboard & engine](./dashboard-and-engine.md).

---

### Engine not warm

```bash
scubiee engine ensure . --wait 45
scubiee init . --no-index
```

---

## Uninstall & upgrade leftovers

```bash
scubiee stop
# quit Cursor
scubiee wipe --all --yes --package
```

Read JSON **`audit.remaining`**. Re-run until clean. Platform guides: [Windows](./uninstall-windows.md) | [Mac/Linux](./uninstall-mac-linux.md).

---

## Still stuck?

Collect and share:

```bash
scubiee --version
scubiee setup --status
scubiee doctor .
scubiee list
scubiee diagnose --no-tests --desktop
```

Attach `Desktop/scubiee-diagnose.json` and a short tail of `~/.context-engine/engine.log` if present.

Platform-specific: [Windows](./windows.md) | [Mac & Linux](./mac-and-linux.md)

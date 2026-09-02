# Complete fix guide

Symptom → **why it happens** → **fix** → **how to verify**. Use this when something is broken and you need to understand, not just run a command.

**Version:** 0.3.14 · **Also see:** [error-codes-reference.md](./error-codes-reference.md) · [how-everything-works.md](./how-everything-works.md)

---

## Before you fix anything

Run triage (copy/paste):

```bash
scubiee --version
scubiee setup --status
scubiee preflight .
scubiee doctor .
scubiee list
scubiee diagnose --no-tests --desktop
```

Share `Desktop/scubiee-diagnose.json` for support.

---

## Install and upgrade

### Access denied on `uv tool install --force` (Windows)

**Symptom**

```text
failed to remove directory ...\uv\tools\scubiee\Scripts: Access is denied. (os error 5)
```

Often followed by `No module named 'pipeline'` or broken `scubiee.exe`.

**Why**

Cursor (or another IDE) keeps **scubiee-mcp** alive. That process locks `python.exe` and DLLs under `%APPDATA%\uv\tools\scubiee\`. Windows blocks directory replacement. This is **not** fixed by Administrator PowerShell or reboot alone — locks return when IDE respawns MCP.

**Fix (CLI still works)**

```powershell
scubiee unlock-tool
uv tool install --force scubiee==0.3.14 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
scubiee connect --cursor
```

Reload MCP in IDE.

**Fix (CLI broken — no pipeline module)**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/uninstall-uv-scubiee.ps1
# OR repair + version:
powershell -ExecutionPolicy Bypass -File scripts/repair-uv-scubiee.ps1 0.3.14
scubiee setup --repair
scubiee connect --cursor
```

**Verify**

```bash
scubiee --version                    # prints 0.3.14 + uv python path
python -c "import pipeline; print('ok')"
scubiee doctor .
```

**Do not**

- Delete `Scripts` manually while Cursor is open (partial delete → worse breakage).
- Assume conda `pip install scubiee` fixes the uv tool CLI (two separate installs).

---

### `No module named 'pipeline'`

**Why**

Interrupted `uv tool install` left half-deleted env: shim exists, package missing.

**Fix**

Same as Access denied above.

**Verify**

`scubiee --version` and `scubiee doctor .` both succeed.

---

### Two Pythons / wrong pip

**Symptom**

You `pip install` into conda but `scubiee --version` shows uv tool Python (or vice versa). Doctor shows **extra scubiee on PATH**.

**Why**

Multiple installs — uv tool, conda, system pip — each has its own `scubiee` and `pipeline`.

**Fix**

Pick **one** install path:

- **Recommended:** uv tool only → uninstall others from PATH or use full path to uv scubiee.
- Run `scubiee doctor .` — read `install.active_binary` and `extra_on_path`.

**Verify**

Only one `scubiee` on PATH resolves to the version you expect.

---

### `machine_not_setup` on init

**Symptom**

```json
{"ok": false, "error": "machine_not_setup"}
```

**Why**

Layer 2 missing — no `~/.scubiee/accel.json` from completed setup.

**Fix**

```bash
scubiee setup --repair
scubiee setup --status
scubiee init .
```

**Verify**

`setup --status` shows profile + model; `init` completes without error.

---

### Diagnose OK but init/preflight fails (stale accel)

**Symptom**

`diagnose` shows good profile; `libraries.fastembed` or `onnxruntime` null; init fails.

**Why**

`accel.json` survived from old install; wheels were wiped during broken upgrade.

**Fix**

```bash
scubiee setup --repair
scubiee diagnose --no-tests --desktop
scubiee init .
```

**Verify**

Diagnose libraries section populated; preflight passes.

---

### Missing fastembed / onnxruntime / preflight not_configured

**Why**

Windows base wheel may not include embed stack until `setup --repair` pip-installs extras into uv env.

**Fix**

```bash
scubiee setup --repair
scubiee preflight .
```

Lexical-only escape hatch: `scubiee preflight . --lexical-only` (no semantic search until repair).

---

### Wrong GPU profile (DML hang on Intel laptop)

**Symptom**

Setup hangs on DirectML; or embed never completes on Intel UHD only machine.

**Why**

DirectML on **integrated** GPU is unreliable; product defaults to **cpu** on iGPU-only Windows.

**Fix**

```bash
scubiee setup --profile cpu --repair
```

Discrete AMD missed by detect: `scubiee setup --profile dml --repair`.

**Verify**

`scubiee setup --status` → `profile: cpu` (or intended profile); init embed step completes.

---

### Apple Silicon stuck on cpu

**Why**

Forced CPU profile or incomplete MLX install.

**Fix**

```bash
scubiee setup --profile mlx --repair
```

**Verify**

`setup --status` shows `mlx`.

---

### faiss `class_wrappers` import error

**Why**

Corrupt partial extract of `faiss-cpu` in uv tool site-packages (Windows).

**Fix**

`scripts/repair-uv-scubiee.ps1` or reinstall uv tool + `setup --repair`.

---

### `failed to locate pyvenv.cfg`

**Why**

Broken uv tool venv metadata.

**Fix**

Quit IDE → uninstall/repair script → reinstall.

---

## Enrollment, init, indexing

### Agent `managed: false`

**Why**

Missing Layer 3 (`init`) and/or Layer 4 (`connect`), or wrong workspace in multi-root Cursor.

**Fix**

```bash
cd /path/to/project
scubiee init .
scubiee connect --cursor    # from THIS project
# reload MCP
```

For Kiro/Copilot/Cline/Roo: `connect` **inside each repo**.

**Verify**

MCP `status()` or `gate()` → `managed: true`, `ok: true` (when daemon warm).

---

### Refusing to index home directory

**Why**

Safety gate — prevents indexing entire `$HOME` or drive root by accident.

**Fix**

```bash
cd /path/to/your/project
scubiee init .
```

**Verify**

`scubiee status .` shows enrolled.

---

### `confirm_required` / >400 files

**Why**

Safety — large index needs explicit consent.

**Fix**

```bash
scubiee init . --confirm
# or narrow scope:
scubiee init . --fast --roots packages,src
```

---

### `never_index` / path blocked

**Why**

Previously ran `scubiee never-index` on this path.

**Fix**

Clear via lifecycle/dashboard or remove block from registry prefs — see [repo-lifecycle](../docs/web-info/repo-lifecycle.md).

---

### `project_id_mismatch`

**Why**

Folder has `id.json` for project A but registry thinks it should be B (copy/paste repo, partial wipe).

**Fix**

```bash
scubiee list
scubiee wipe . --confirm    # clean slate for this checkout
scubiee init .
```

Or expert: align registry + id file manually (see data reference).

---

### Search misses fresh edits

**Why**

Index stale — sync not run; or file outside index scope (fast mode non-.py).

**Fix**

```bash
scubiee sync .
```

Test: add unique string to indexed `.py`, sync, search CLI or MCP grep.

**Verify**

Token appears in `scubiee search "UNIQUE_TOKEN" .`

---

## MCP and agent behavior

### MCP server red / not connecting

**Why**

Daemon down; wrong Python in mcp.json; MCP not reloaded after connect.

**Fix**

```bash
scubiee engine ensure . --wait 45
scubiee connect --cursor
# reload MCP in IDE
```

If zombies: `scubiee stop` then `scubiee resume` after fix.

---

### `warming: true` forever

**Why**

Daemon not starting — port conflict, crash loop, or resource admission.

**Fix**

```bash
scubiee engine ensure . --wait 45
scubiee engine status .
tail ~/.scubiee/engine.log    # or type on Windows
```

**Verify**

`engine status` → healthy; MCP tool (not status poll) succeeds.

---

### Agent uses native Grep only

**Why**

Old agent rules; MCP not green; managed false; global stop.

**Fix**

1. MCP green in IDE settings  
2. `scubiee connect --cursor` (refresh rules)  
3. Reload MCP  
4. User runs `scubiee resume` if globally stopped  

---

### Agent says `scubiee wake`

**Why**

Old rule template or old docs.

**Fix**

User runs **`scubiee resume`** (global) or **`scubiee activate .`** (per-repo pause). Re-`connect` to update rules.

---

### Cursor wrong repo / home folder managed

**Why**

Global MCP had literal `${workspaceFolder}` or missing project `.cursor/mcp.json` pin.

**Fix**

```bash
cd correct-project
scubiee connect --cursor
```

**Verify**

Project `.cursor/mcp.json` contains absolute `CTX_REPO` path.

---

### `sync-now` blocked while paused

**Why**

Per-repo pause (0.3.13+).

**Fix**

```bash
scubiee activate .
scubiee sync-now .
```

---

## Lifecycle and wipe

### Need to unmanage one repo completely

**Fix**

```bash
scubiee wipe . --confirm
```

**Verify**

`scubiee status .` → `enrolled: false`, `unmanaged`.

See [repo-lifecycle](../docs/web-info/repo-lifecycle.md).

---

### Wipe refused exit code 2

**Why**

Confirm gate — intentional safety.

**Fix**

Add `--confirm` or answer TTY prompt.

---

### Full uninstall leftovers (Windows)

**Why**

Cursor holds MCP file locks; audit lists `remaining` paths.

**Fix**

```bash
scubiee stop
# quit Cursor
scubiee wipe --all --confirm --package
# re-run if audit.remaining non-empty
scubiee unlock-tool
```

---

## Dashboard and engine

### Dashboard failed to start

**Why**

Historical Windows PID mismatch (fixed 0.3.13+); port/firewall issues.

**Fix**

Upgrade to 0.3.14; `scubiee dashboard --no-open`; `scubiee dashboard --status`.

---

## Upgrade path

```bash
scubiee upgrade
# OR manual:
scubiee unlock-tool          # Windows if needed
uv tool install --force scubiee==0.3.14 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
scubiee connect --cursor
scubiee migrate --check-all
```

**Verify**

`scubiee --version`; doctor OK; MCP status managed.

---

## Still stuck

1. Read [error-codes-reference.md](./error-codes-reference.md) for your exact JSON `error`.
2. Read [how-everything-works.md](./how-everything-works.md) for the layer that's failing.
3. Collect diagnose JSON + `engine.log` tail.
4. Platform guides: [Windows](../docs/web-info/windows.md) · [Mac/Linux](../docs/web-info/mac-and-linux.md)

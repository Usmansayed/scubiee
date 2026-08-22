# Troubleshooting

Symptom → cause → fix. Start with `scubiee doctor .` and `scubiee preflight .`.

---

## Quick triage order

```bash
scubiee --version
scubiee setup --status
scubiee preflight .
scubiee doctor .
scubiee list
```

If semantic preflight fails: `scubiee setup --repair` then retry.

---

## `machine_not_setup` on `init`

**Symptom:**

```json
{"ok": false, "error": "machine_not_setup"}
```

**Cause:** No saved profile in `~/.context-engine/accel.json` (fresh machine, after partial wipe, or upgrade without repair).

**Fix:**

```bash
scubiee setup --repair
scubiee setup --status    # preferred_profile should be non-null
```

---

## Install & setup

### `No module named 'fastembed'` during `scubiee setup`

**Cause:** Fresh uv install on Windows; FastEmbed is installed by setup, but an existing `accel.json` can trigger model checks before pip install completes.

**Fix:**

```bash
scubiee setup --repair
```

---

### Preflight fails: missing `fastembed` / `onnxruntime`

**Fix:**

```bash
scubiee setup --repair
scubiee preflight .
```

For lexical-only (no GPU embed):

```bash
scubiee preflight . --lexical-only
```

---

### `scubiee setup` stuck at ~31% (Windows)

**Cause:** Historical pip stdout pipe deadlock during ORT install (fixed 0.2.14+).

**Fix:** Upgrade to latest scubiee, quit Cursor, `scubiee setup --repair`.

---

### Wipe did not remove everything

**Symptom:** After `scubiee wipe --all --yes`, `.context-engine` or uv tool dir still present.

**Cause:** Cursor MCP or daemon still locking files (Windows).

**Fix:**

```bash
scubiee stop
# quit Cursor completely
scubiee wipe --all --yes --package
```

Read stderr/JSON **`audit.remaining`** for honest list of leftover paths. Re-run wipe until `audit.clean` is true.

---

### `connect` fails before faiss is fixed

**Fixed in 0.2.54:** `connect`, `disconnect`, `migrate`, and `diagnose` no longer require faiss. Upgrade if an older build blocks them.

---

**Symptom:** Setup says `dml` but embed uses CPU; `available_providers` lacks `DmlExecutionProvider`.

**Cause:** Wrong ORT wheel (CPU wheel left after mixed installs).

**Fix:**

```bash
scubiee setup --repair
# if still broken on Windows, see windows.md ORT purge steps
```

---

### `onnxruntime has no attribute SessionOptions`

**Cause:** Conflicting/partial ORT uninstall left a broken `site-packages/onnxruntime` tree.

**Fix:** Quit all Python using that env. Delete leftover `onnxruntime` folder in site-packages. Run `scubiee setup --repair`.

---

### faiss `cannot import name 'class_wrappers'`

**Cause:** Incomplete `faiss-cpu` extract from uv on Windows.

**Fix (manual):**

```powershell
pip download faiss-cpu==1.15.0 -d $env:TEMP\faiss_whl --no-deps
uv pip install --force-reinstall "$env:TEMP\faiss_whl\faiss_cpu-*.whl" --python "$env:APPDATA\uv\tools\scubiee\Scripts\python.exe"
```

Or run `scripts/repair-uv-scubiee.ps1` (see [Windows guide](./windows.md)).

**0.2.45+:** startup may auto-repair faiss; `scubiee --version` should still work.

---

### `failed to locate pyvenv.cfg`

**Cause:** Broken/partial uv tool directory (often after Access denied uninstall).

**Fix:** Quit Cursor → [Uninstall on Windows](./uninstall-windows.md) or `scripts/repair-uv-scubiee.ps1`.

---

### Two Pythons on PATH (`pip` ≠ `scubiee`)

**Symptom:** `pip uninstall scubiee` says not installed; `scubiee --version` still runs.

**Fix:** Read `scubiee --version` output — it prints the Python path and uninstall instructions. Use **that** Python’s pip/uv, not conda’s.

---

## Indexing & init

### Refusing to index home directory

**Expected.** `cd` to project root. See [Indexing & projects](./indexing-and-projects.md).

---

### `"539 files need indexing (>400)"` or similar

**Expected safety gate.** Use `--confirm` or `--fast --roots …` to reduce scope.

---

### False huge file count (historical)

**Symptom:** Count included `testdata/` / vendor while actual index excluded them.

**Fix:** Upgrade to **0.2.49+** where preflight uses the same path rules as indexing.

---

### `never_index` error

You ran `scubiee never-index` on this path. Clear via dashboard forget or lifecycle remove (advanced).

---

### project_id_mismatch / stale home registration

**Symptom:** `certify` or `doctor --all` fails; daemon reconciles `C:\Users\you`.

**Fix:**

```bash
scubiee list
scubiee remove C:\Users\YOUR_USER --delete-store
# delete C:\Users\YOUR_USER\.context-engine\id.json if it remains
```

---

## MCP & Cursor

### MCP red / not connecting

1. `scubiee engine ensure . --wait 45`
2. `scubiee setup --repair` (rewrites mcp.json)
3. Reload MCP in Cursor
4. `scubiee stop` then retry if zombie processes

---

### Search misses fresh edits

```bash
scubiee sync .
```

Test with a unique token in a **`.py`** file.

---

## Dashboard & daemon

### Dashboard unhealthy on Windows

Upgrade to **scubiee 0.2.54+**. See [Dashboard & engine](./dashboard-and-engine.md).

---

### `engine status` shows server not warm

```bash
scubiee engine ensure . --wait 45
scubiee init . --no-index    # ensures registration
```

---

## Uninstall & upgrade

### `uv tool uninstall` Access denied

**Fix:** [Uninstall on Windows](./uninstall-windows.md) — `scubiee stop` → wipe → quit Cursor.

---

## Tests & certify

### `scubiee test quick` fails on progress_ui tests

Known test drift in some releases (mock/message assertions). Runtime CLI is unaffected. Report if all 89 tests must pass for your CI.

### `scubiee certify` fails

Run `scubiee doctor . --fix`, remove stale home registration, ensure single scubiee on PATH, then:

```bash
scubiee certify . --skip-daemon
```

---

## Still stuck?

Collect and attach:

```bash
scubiee --version
scubiee setup --status
scubiee doctor .
scubiee list
```

Plus tail of `~/.context-engine/engine.log`.

Platform-specific: [Windows](./windows.md) | [Mac & Linux](./mac-and-linux.md)

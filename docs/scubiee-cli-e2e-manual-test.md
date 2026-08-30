# Scubiee CLI end-to-end manual test

Run **real `scubiee` commands** in your terminal (not `python scripts/...`).  
This mirrors the Windows validation on 2026-08-30 and is meant to be repeated on **macOS** (Linux paths are the same as macOS unless noted).

---

## What this covers

| Phase | Commands | Purpose |
|-------|----------|---------|
| Baseline | `setup`, `init`, `status` | Fresh enroll |
| Global stop | `stop`, blocked `init`, `resume` | Lifecycle guard |
| Recovery | `halt`, `resume` | Process release without full wipe |
| Repo wipe | `wipe . --confirm`, re-`init` | Per-repo clean + engine restart |
| Full wipe | `wipe --all`, `wipe --all --confirm --keep-package` | One-shot machine clean |
| Post-wipe | `setup --repair`, `init`, `status` | Cold start after wipe |
| Help | `--help`, `list` | CLI sanity |

**Runtime:** ~30–45 minutes (most time is `init` indexing a large repo).

---

## Prerequisites

### macOS

```bash
# uv (if not installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone or open the repo
cd ~/path/to/context-engine

# Install local build as the user-facing binary
uv tool install --force .

# Ensure scubiee is on PATH
export PATH="$HOME/.local/bin:$PATH"
scubiee --version
```

### Windows (reference)

```powershell
cd C:\path\to\context-engine
uv tool install --force .
$env:Path = "$env:APPDATA\uv\tools\scubiee\Scripts;$env:USERPROFILE\.local\bin;$env:Path"
scubiee --version
```

### Optional: isolated home (safer on a shared machine)

```bash
export CTX_HOME="/tmp/scubiee-test-$$"
mkdir -p "$CTX_HOME"
```

Leave `CTX_HOME` **unset** to test your real `~/.scubiee` (what we did on Windows).

---

## Automated runners (recommended)

These only invoke the **`scubiee` binary** — they log exit codes to `tests/_e2e_cmd_results.txt`.

**macOS / Linux:**

```bash
chmod +x tests/_e2e_run_cmds.sh
bash tests/_e2e_run_cmds.sh
```

**Windows:**

```powershell
powershell -File tests\_e2e_run_cmds.ps1
```

---

## Manual step-by-step (copy/paste)

Run from the repo root. After each block, note exit code (`echo $?` on macOS).

### 1. Baseline

```bash
scubiee --version          # expect 0, prints version
scubiee doctor             # expect 1 or ok:false if not enrolled yet
scubiee status .
scubiee setup --repair     # expect 0; creates ~/.scubiee/accel.json
scubiee init .             # expect 0; indexes repo (slow)
scubiee status .           # expect 0; project_id in JSON
```

**Pass if:** `.scubiee/id.json` exists and `status` shows a `project_id`.

### 2. Global stop + guard

```bash
scubiee stop -y            # expect 0
scubiee stop -y            # expect 0, already_paused
scubiee init .             # expect 1, "run scubiee resume"
scubiee setup --repair     # expect 0 (repair allowed while stopped)
scubiee doctor             # expect 0 (read-only OK)
scubiee halt               # expect 0, kills watchdog/daemon JSON
scubiee resume             # expect 0
scubiee init .             # expect 0 (idempotent)
```

### 3. Halt cycle

```bash
scubiee halt
scubiee resume
```

### 4. Repo wipe

```bash
scubiee wipe . --confirm   # expect 0, scope=repo
test ! -f .scubiee/id.json && echo "repo id gone OK"
scubiee init .             # expect 0, re-enroll
scubiee stop -y            # prep for full wipe
```

**Pass if:** `.scubiee/id.json` was removed after wipe and returns after re-init.

### 5. Full machine wipe (keeps uv package)

```bash
scubiee wipe --all                    # expect exit 2 (needs --confirm)
scubiee wipe --all --confirm --keep-package   # expect 0
test ! -d ~/.scubiee && echo "~/.scubiee gone OK"
test ! -f .scubiee/id.json && echo "repo id gone OK"
```

**macOS paths wiped:** `~/.scubiee`, repo `.scubiee/`, `~/.cursor/mcp.json` (if present), model cache under temp.

**Windows paths wiped:** `%USERPROFILE%\.scubiee`, repo `.scubiee\`, `%USERPROFILE%\.cursor\mcp.json`, `%TEMP%\fastembed_cache`.

### 6. Cold start after full wipe

```bash
scubiee setup --repair
scubiee init .
scubiee status .
```

### 7. Help + list

```bash
scubiee --help             # expect 0, full usage (no crash)
scubiee halt --help
scubiee wipe --help
scubiee list               # expect 0, JSON array of projects
```

---

## Expected results table

| ID | Command | Exit | Notes |
|----|---------|------|-------|
| B1 | `scubiee --version` | 0 | |
| B3 | `scubiee doctor` | 1 or 0 | 1 before enroll is fine |
| B7 | `scubiee setup --repair` | 0 | |
| B8 | `scubiee init .` | 0 | Slow |
| G1 | `scubiee stop -y` | 0 | |
| G2 | `scubiee stop -y` | 0 | `already_paused` |
| G3 | `scubiee init .` | 1 | Blocked |
| G5 | `scubiee setup --repair` | 0 | Allowed while stopped |
| G14 | `scubiee halt` | 0 | |
| G17 | `scubiee resume` | 0 | |
| W1 | `scubiee wipe . --confirm` | 0 | Removes repo enrollment |
| G16 | `scubiee wipe --all` | 2 | Safety gate |
| G16b | `scubiee wipe --all --confirm --keep-package` | 0 | Cleans machine state |
| R1 | `scubiee --help` | 0 | Fixed: `%APPDATA%` escape in unlock-tool help |
| R4 | `scubiee list` | 0 | |

---

## Windows reference run (2026-08-30)

- **Result:** 25/26 pass before `--help` fix; all 26 pass after fix.
- **Log:** `tests/_e2e_cmd_results.txt`
- **Version tested:** scubiee 0.3.5 (local `uv tool install --force .`)

Notable behaviors observed:

- `stop -y` works even when MCP not connected (warning only).
- `wipe . --confirm` removes `.scubiee/id.json` and restarts engine.
- `wipe --all --confirm --keep-package` removes `~/.scubiee` and repo id; keeps uv-installed binary.
- `init` after full wipe succeeds after `setup --repair`.

---

## macOS-specific notes

| Topic | macOS | Windows |
|-------|-------|---------|
| scubiee binary | `~/.local/bin/scubiee` | `%APPDATA%\uv\tools\scubiee\Scripts\scubiee.exe` |
| Scubiee home | `~/.scubiee` | `%USERPROFILE%\.scubiee` |
| Cursor MCP | `~/.cursor/mcp.json` | `%USERPROFILE%\.cursor\mcp.json` |
| unlock-tool | Rarely needed | Use when `uv tool install` hits Access denied |
| Model cache | Often under `/tmp/fastembed_cache` | `%TEMP%\fastembed_cache` |

**After `wipe --all`:** run `scubiee connect --cursor` (or your IDE flag) to restore MCP.

**Symlink / permission issues on first `setup`:** use `scubiee setup --repair` (same as Windows WinError 1314 workaround).

---

## After testing

1. Reconnect your IDE: `scubiee connect --cursor`
2. Confirm health: `scubiee doctor` and `scubiee status .`
3. Paste your macOS log into this doc or open a PR with `tests/_e2e_cmd_results.txt`

---

## Bug fixed during this test

`scubiee --help` crashed on Windows because argparse treated `%APPDATA%` in the `unlock-tool` subcommand help as a format specifier.

**Fix:** escape percent signs as `%%APPDATA%%` in `packages/pipeline/__main__.py`.

Reinstall after pulling the fix:

```bash
uv tool install --force .
```

---

## Related docs

- Full combination matrix (80+ scenarios): [scubiee-cli-combination-test-matrix.md](./scubiee-cli-combination-test-matrix.md)
- **Connect / MCP per-tool testing:** [scubiee-connect-e2e-manual-test.md](./scubiee-connect-e2e-manual-test.md)
- Lifecycle scenarios: [scubiee-lifecycle-scenarios.md](./scubiee-lifecycle-scenarios.md)

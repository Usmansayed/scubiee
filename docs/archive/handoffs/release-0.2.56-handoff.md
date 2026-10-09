# Scubiee 0.2.56 — Release Handoff

## What Changed

### 1. Clean CLI Output (Vercel/Linear-inspired)

The terminal output is now minimal, professional, and context-aware:

- **TTY (interactive terminal):** Shows clean human-readable output with status icons (✓ ✗ ! ·), aligned key-value pairs, and no noise.
- **Piped (scripts/MCP):** Outputs full JSON (backward-compatible).
- **`--json` flag on status:** Forces JSON even on TTY.

**Before (status):** 60+ lines of raw JSON dumped to terminal  
**After (status):**
```
scubiee v0.2.56
────────────────────────────────────────
  ✓ Engine running  ready
  Repository       my-project
  Chunks           3,417
  Files indexed    417
  Backend          mlx
  Vectors          3,417
  ✓ Index is fresh
```

Affected commands: `status`, `init`, `connect`, `disconnect`, `stop`, `resume`, `doctor`.

---

### 2. Global Stop / Resume

Two commands replace the old `stop` (which only killed processes but left MCP configs active, confusing agents):

**`scubiee stop`** — Makes Scubiee completely invisible:
- Kills engine + watchdog + MCP processes
- Disables MCP entries in all connected tools (`"disabled": true`)
- Renames rule files to `*.paused` (invisible to IDE agent loaders)
- Saves which tools were connected (for restore)
- Shows y/N confirmation before proceeding (skip with `-y`)

**`scubiee resume`** — Brings everything back:
- Re-enables MCP entries
- Restores rule files
- Starts engine + watchdog
- Reconciles dirty files (merkle diff since stop time)

While stopped:
- Zero CPU/memory/disk usage
- `status()` MCP tool returns `{"ok": false, "paused": true}` → agents skip Scubiee
- Watchdog/lifecycle won't auto-restart anything

---

### 3. Upgrade Command

**`scubiee upgrade`** — One command for the full upgrade lifecycle:
- Checks PyPI for latest version
- Stops running processes (avoids Windows DLL locks)
- Pulls the new package via pip/uv
- Restarts daemon with new code
- Runs data migrations automatically
- Clears paused state (upgrading = intent to use)

**Auto version-mismatch restart:**  
If CLI version ≠ running daemon version, `ensure_daemon` automatically restarts the daemon. Users never have to manually restart after `pip install --upgrade`.

**Update hint in status:**  
Once per day, checks PyPI (cached). If newer version exists:
```
  ! Update available: 0.2.56 → 0.2.57  (scubiee upgrade)
```

---

### 4. Interactive Confirmations

Destructive commands now prompt before executing:

```
  ! Stop Scubiee?
    This will kill the engine, disable MCP in all connected tools,
    and hide rules. Agents will fall back to native search.
    Resume anytime with: scubiee resume

  Continue? [y/N]
```

- `scubiee stop` — prompts (skip with `-y`)
- `scubiee wipe --all` — prompts (skip with `--yes`)
- Non-TTY (piped/scripted) automatically skips prompts

The capital letter in `[y/N]` indicates the default: pressing Enter without typing = No (safe choice for destructive actions).

---

### 5. Bug Fixes

| Bug | Fix |
|-----|-----|
| `wipe --all --yes` killed itself (exit 143) before finishing cleanup | Exclude own PID from process stop list |
| `resume` didn't start the daemon (no repo binding) | Pass first managed repo to `ensure_daemon` |
| Orphan watchdog processes after broken wipe | Fixed by self-PID exclusion |

---

## Mac Validation (Completed)

**Mac production test: 25/25 passed ✓**

Tested on: macOS (Apple Silicon M-series), Python 3.12.14, MLX backend at ~111 t/s.

All commands verified working: setup, init, status, search, sync, doctor, certify, connect/disconnect, stop/resume, upgrade, engine lifecycle, MCP tools (all 7), adversarial inputs, multi-repo switching, concurrent requests.

---

## Windows Validation (Required)

A Windows test script is at `tests/windows_production_test.py`. Run it on a Windows machine with scubiee installed:

```powershell
# Prerequisites
uv tool install scubiee
scubiee setup

# Run the test (from any git repo with code files)
cd C:\path\to\some-project
python tests\windows_production_test.py
```

### What the Windows test covers (11 sections):

| # | Test | What it validates |
|---|------|-------------------|
| 1 | Install verification | `scubiee` on PATH, version ≥ 0.2.56, Windows path separators |
| 2 | Setup | DML/CUDA/CPU profile detection, `accel.json` written |
| 3 | Init + index | Safety cap fires, chunks indexed, engine warms within 30s (DML cold start) |
| 4 | MCP tools | All 7 tools respond via stdio JSON-RPC |
| 5 | Connect/disconnect | 13 tools, Windows paths (AppData, .cursor, .copilot) |
| 6 | Concurrent requests | 8 rapid-fire calls, all under 15s |
| 7 | Adversarial inputs | Path traversal with backslash, shell injection with `cmd /c`, huge patterns |
| 8 | Engine recovery | `engine stop` → `engine ensure` restarts cleanly |
| 9 | Stop/Resume | Full lifecycle: stop → verify down → resume → verify up |
| 10 | Upgrade check | `scubiee upgrade` runs without error |
| 11 | Orphan processes | After `stop`, no `pipeline` or `scubiee` in `tasklist` output |

### Windows-specific concerns to watch for:

1. **DML cold start timing** — DirectML session creation can take 10-15s on first use. The test allows 30s warm-up.
2. **DLL locks** — If Cursor is running with MCP connected, `wipe --all` may fail to delete the uv tool env. Quit Cursor first.
3. **Path separators** — All internal paths should use forward slashes in MCP env vars and JSON. Windows `\` only in user-facing display.
4. **CREATE_NO_WINDOW** — The MCP process must not flash a console window. Test verifies `creationflags`.
5. **taskkill /T /F** — Process stop uses tree-kill on Windows. Verify no orphans remain.

### Expected result:
```
  SCUBIEE WINDOWS PRODUCTION TEST
  ...
  RESULTS
  XX/XX passed, 0 failed
  PRODUCTION READY (Windows)
```

If any test fails, the output shows `[FAIL]` with detail. Share the full output for diagnosis.

---

## Files Changed

```
packages/pipeline/cli_ui.py          (NEW)  — Terminal formatting module
packages/pipeline/pause_resume.py    (NEW)  — Global stop/resume logic
packages/pipeline/upgrade.py         (NEW)  — Upgrade lifecycle
packages/pipeline/__main__.py        (MOD)  — CLI commands wiring
packages/pipeline/mcp_locate.py      (MOD)  — Paused status check
packages/pipeline/daemon.py          (MOD)  — Paused guard + version mismatch restart
packages/pipeline/watchdog.py        (MOD)  — Paused guard
packages/pipeline/lifecycle_runtime.py (MOD) — Paused guard
packages/pipeline/process_control.py (MOD)  — Self-PID exclusion fix
tests/test_pause_resume.py           (NEW)  — 11 unit tests
tests/mac_production_test.py         (existing) — 25/25 passing
tests/windows_production_test.py     (NEW)  — Windows validation suite
```

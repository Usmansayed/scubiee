# Deferred: Windows uv tool Access denied (no reboot)

**Date:** 2026-08-26  
**Status:** Deferred — design agreed; implement later  
**Reporter context:** Friend laptop (UMAIR), Windows; also general Windows uv-tool users  
**Related:** `docs/web-info/uninstall-windows.md`, `scripts/uninstall-uv-scubiee.ps1`, `scripts/repair-uv-scubiee.ps1`, `packages/pipeline/process_control.py`

---

## Symptom (live screenshots)

User tried to force-reinstall while the tool dir was locked:

```powershell
Remove-Item -Recurse -Force "$env:APPDATA\uv\tools\scubiee" -ErrorAction SilentlyContinue
Remove-Item -Force "$env:USERPROFILE\.local\bin\scubiee.exe" -ErrorAction SilentlyContinue
uv tool install --force scubiee==0.2.82 --index-url https://pypi.org/simple --refresh
```

**Result (even in Administrator PowerShell):**

```text
error: failed to remove directory
'C:\Users\UMAIR\AppData\Roaming\uv\tools\scubiee\Scripts': Access is denied. (os error 5)
```

Then `scubiee` was not on PATH (`CommandNotFoundException`), so `scubiee setup` / `diagnose` also failed.

Admin did **not** help. Reboot “works” only because it kills the locker.

---

## Root cause

Not ACLs — **file locks**.

- Cursor MCP (or daemon / watchdog / supervisor) keeps `%APPDATA%\uv\tools\scubiee\Scripts\python.exe` open.
- Windows refuses to delete/replace locked EXEs.
- `-ErrorAction SilentlyContinue` hides a failed `Remove-Item`, then `uv tool install --force` hits the same lock.
- If `~/.cursor/mcp.json` (or project MCP) still has `context-engine`, Cursor can **respawn** MCP right after you kill python.

---

## What already exists

| Piece | Role |
|-------|------|
| `scubiee stop` / `stop_all_context_engine_processes` | Kill CE + uv-tool processes |
| `wipe --all --package` / `uv_tool_uninstall` / `force_remove_uv_tool_dir` | Stop → uninstall → force rmtree |
| `scubiee upgrade` | Pre-stop before package swap |
| `scripts/uninstall-uv-scubiee.ps1` | Standalone recovery when CLI is broken |
| `scripts/repair-uv-scubiee.ps1` | Reinstall helper |
| Docs uninstall-windows | Explains Access denied + quit Cursor |

Gap: users who never run stop/wipe (or whose `scubiee` is already broken) still hit Umair’s path; script order / retries can be hardened so reboot is never the advice.

---

## Agreed fix direction (implement later)

1. **Unlock before every package swap** (`upgrade`, wipe `--package`, repair helpers):  
   strip CE from MCP configs → stop daemon/watchdog/uv-tool PIDs → retry delete (rename-then-delete + short backoff) → then `uv tool install/upgrade`.

2. **Harden standalone PS1 recovery** (works when `scubiee` is not on PATH):  
   MCP-off **first** → kill lockers → retry remove → optional reinstall.  
   Explicit message: “Admin won’t help — quit Cursor or disable MCP.”

3. **Docs one-liner:** don’t `Remove-Item` the tool dir while Cursor is open; use the script or quit → stop → wipe/reinstall.

4. **Optional:** `scubiee unlock-tool` (stop + force-remove only) when CLI still works.

Out of scope for v1: handle enumeration / forced reboot automation.

---

## Manual recovery today (UMAIR / anyone stuck)

1. **Quit Cursor completely** (not just reload).
2. Run from a clone that has the scripts, or copy them:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/uninstall-uv-scubiee.ps1
uv tool install --force scubiee==0.2.82 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
```

3. If still locked: Task Manager → end `python.exe` / `scubiee` under `uv\tools\scubiee`, remove CE from `%USERPROFILE%\.cursor\mcp.json`, retry. Reboot only as last resort.

---

## Acceptance when we implement

- [ ] Force reinstall / upgrade succeeds with Cursor closed, without reboot
- [ ] Force reinstall succeeds after script with Cursor still open *if* MCP entry is stripped first and processes killed (no respawn)
- [ ] Broken half-install (`scubiee` missing from PATH) recovers via PS1 alone
- [ ] Docs no longer imply Admin or reboot as the primary fix

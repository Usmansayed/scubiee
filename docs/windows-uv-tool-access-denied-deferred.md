# Done: Windows uv tool Access denied (no reboot)

**Date:** 2026-08-26 (designed) → implemented 2026-08-26  
**Status:** Done  
**Reporter context:** Friend laptop (UMAIR), Windows; also general Windows uv-tool users  
**Related:** `scripts/uninstall-uv-scubiee.ps1`, `scripts/repair-uv-scubiee.ps1`, `packages/pipeline/process_control.py`, `scubiee unlock-tool`

---

## Symptom

```text
error: failed to remove directory
'...\uv\tools\scubiee\Scripts': Access is denied. (os error 5)
```

Admin did **not** help. Root cause: **file locks** (Cursor MCP / daemon holding `python.exe`), not ACLs. MCP can **respawn** after kill if `context-engine` stays enabled in MCP config.

---

## Implemented fix

1. **Unlock before package swap** (`prepare_uv_tool_directory_for_swap`):
   - disable CE in global + project MCP → stop processes → optional force-remove with rename-then-delete + backoff
2. **`scubiee upgrade`**: uses prepare; on Access denied → `unlock-tool` + `uv tool install --force`
3. **`scubiee unlock-tool`**: stop + force-remove only (when CLI still works)
4. **PS1 recovery** (`uninstall-uv-scubiee.ps1` / `repair-uv-scubiee.ps1`): MCP-off **first**, then kill, then retry remove — message says Admin will not help
5. **`uv_tool_uninstall` / `force_remove_uv_tool_dir`**: same MCP-first + retry path

---

## Manual recovery

```powershell
# Prefer (if scubiee still runs):
scubiee unlock-tool
uv tool install --force scubiee --index-url https://pypi.org/simple

# If scubiee is broken / not on PATH:
powershell -ExecutionPolicy Bypass -File scripts/uninstall-uv-scubiee.ps1
uv tool install --force scubiee --index-url https://pypi.org/simple
scubiee setup --repair
scubiee connect --cursor
```

Quit Cursor completely only if unlock still fails. Do **not** lead with Admin or reboot.

---

## Acceptance

- [x] Force reinstall / upgrade path unlocks without reboot
- [x] Script order: MCP-off before kill (no respawn)
- [x] Broken half-install recovers via PS1 alone
- [x] Docs / CLI hints do not treat Admin or reboot as the primary fix

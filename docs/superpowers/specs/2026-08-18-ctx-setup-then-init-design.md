# One-command machine setup, then `ctx init` for repos

**Date:** 2026-08-18  
**Branch:** `feat/production-certification`

## User-facing contract

1. **Once per machine:** `pip install -e .` then `ctx setup`  
   Detects CPU/DML/CUDA, installs the matching runtime, downloads the model,
   calibrates batch size, starts the local engine + watchdog, writes Cursor MCP.
2. **Once per codebase:** `ctx init [path]`  
   Puts that folder under Context Engine management and indexes it. Requires
   setup to have already saved a profile. Then binds the running daemon to it.
3. **After that:** watching, sync, doctor `--fix`, and dashboard repairs keep it
   managed. The user does not re-run hardware setup to add another repo.

## Command split

| Command | Owns |
|---------|------|
| `ctx setup` / `ctx setup --repair` / `ctx setup --status` | Machine profile, packages, model, batch, daemon, MCP |
| `ctx init [path]` | Enroll + index + bind that repository |
| `ctx initialize` | Same lifecycle as today (compat) |

`ctx init --repair` is removed. Hardware repair is `ctx setup --repair`.

## Packaging

Wheel must include `pipeline/dashboard_ui/*` so `ctx dashboard` works after a
real install, not only an editable checkout.

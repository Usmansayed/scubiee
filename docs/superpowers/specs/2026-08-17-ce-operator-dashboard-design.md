# CE Operator Dashboard — Design

**Date:** 2026-08-17  
**Branch / worktree:** `feat/ce-dashboard` / `.worktrees/ce-dashboard`  
**Status:** Approved in conversation; ready for implementation  

## Problem

Operators need a single local place to see CE health and manage repositories safely: missing vs moved vs deleted folders, Auto vs Manual admission, indexes/vectors, sync failures, hardware profile, and a graph view — without guessing CLI flags.

Today CE has durable project IDs + registry, lifecycle APIs (`initialize` / `pause` / `remove` / `rebuild`), doctor/certify, and a minimal dark settings page at `/dashboard`. It does not yet provide a full operator control center or a validated Missing → Forget purge path.

## Goals

1. `ctx dashboard` launches a background localhost UI on an uncommon private port.
2. Clean Apple/Google-like light UI (shadcn-style components; no clutter).
3. Manage all day-to-day operator concerns from one shell.
4. Safe lifecycle: Missing ≠ deleted; permanent purge only after validation + typed confirm.
5. Explicit Auto vs Manual admission policy, editable from the dashboard.

## Non-goals (v1)

- Cloud accounts, billing, auth beyond localhost
- Editing source code inside the UI
- Agent/chat surface
- Exposing the dashboard on LAN
- Claiming Linux AMD / Apple GPU acceleration beyond verified-provider-or-CPU-safe

## Launch model

| Command | Behavior |
|---------|----------|
| `ctx dashboard` | Start or reuse background dashboard server; open browser |
| `ctx dashboard --no-open` | Start/reuse without opening browser |
| `ctx dashboard --status` | Print URL, PID, health JSON |
| `ctx dashboard stop` | Stop background dashboard |

Binding:

- Host: `127.0.0.1` only
- Port: stable private-range port derived from CE install/machine id (`49152–65535`)
- If preferred port busy: pick next free port, persist choice
- Base path: `/ce-dashboard` (reduces accidental collisions with common `/dashboard` apps)
- PID/URL file under `~/.context-engine/dashboard.json`

The existing engine HTTP server may continue to serve a redirect or thin embed at `/dashboard` pointing operators to the dedicated dashboard URL when the dashboard process is up.

## UI principles

- Light background, calm sidebar, generous whitespace
- System font stack; hairline borders; almost no shadows
- One job per page; shadcn-like buttons, tables, dialogs, badges
- Destructive actions never use a naked “Delete” label without context

Sidebar:

1. Overview  
2. Repositories  
3. Index & Sync  
4. Storage  
5. Health  
6. Runtime  
7. Graph  
8. Settings  

## Pages

### Overview

- Global health strip: daemon, accel preferred/active, envelope, open errors
- Counts: managed / missing / indexing / errors
- Quick actions: Open Health, Add repository, Toggle Auto/Manual, Open Graph

### Repositories

Row fields: name, path(s), project ID, lifecycle state, last sync, pin flag.

States:

| State | Meaning |
|-------|---------|
| `active` | Path exists; managed; searchable |
| `paused` | Managed; indexing paused |
| `missing` | Last-known path gone; identity retained |
| `indexing` | Warm/index in progress |
| `error` | Binding/publish/index failure |
| `never_index` | Explicitly excluded |
| `purge_eligible` | Validated deleted + retention elapsed; awaiting Forget |

Actions:

- **Add / Initialize** (Manual mode primary)
- **Locate** — pick new path; reattach if durable ID matches
- **Pause / Resume**
- **Unmanage** — stop managing; keep store (maps to remove without deleting index)
- **Clear index** — delete vectors/chunks/graph store; keep project ID / registry row
- **Rebuild / Re-embed**
- **Pin / Unpin**
- **Forget permanently** — only when validation allows; type project ID or folder name

### Missing / delete validation

Path gone → **Missing** only. Never immediate vector wipe.

Before offering Forget / auto-marking purge-eligible, all must hold:

1. Last-known path absent for a sustained window (configurable; default ≥ 24h for auto eligibility; Locate always available immediately)
2. Durable ID file (`.context-engine/id.json`) not present at last path
3. No other registered alias path claims the same project ID with a live ID match
4. Optional content/fingerprint check: if path exists again with different ID → **replaced / conflict**, not deleted

Forget permanently requires dashboard typed confirmation even when purge-eligible.

### Index & Sync

- Per-repo freshness: lexical overlay vs dense pending
- Dirty queue depth, publish errors, watcher overflow recovery status
- Actions: Sync now, Pause indexing, Rebuild

### Storage

- Disk used per project store
- Orphan stores (on-disk project folder with no live path)
- Eviction candidates from storage policy (dry-run by default)
- Clear index / Forget permanently entry points

### Health

- Doctor cards: capabilities, accel/provider warm-up, binding, manifest
- Certify summary: passed / skipped / failed (skips never count as passed)
- Copy or run suggested repair commands (`init --repair`, `engine ensure`, etc.)

### Runtime

- Preferred profile, active profile, backup reason
- Batch, envelope tier, recommended serve command
- Read-only unless linking to explicit `init --repair`

### Graph

- Selected-repo graph visualization (graphify-style), cleaned into the light shell
- Read-only explore; no destructive graph edits in v1

### Settings

- Admission mode: **Automatic** vs **Manual (MCP/CLI / dashboard Add)**
- Auto max managed repos
- Missing retention before purge-eligible
- Dashboard port/url display
- Light theme fixed for v1

## Admission policy

| Mode | Behavior |
|------|----------|
| **Automatic** | CE may admit/index when a supported client supplies a workspace path (existing auto path), within caps |
| **Manual** | No silent admit; user must Initialize from dashboard/CLI/MCP |

Dashboard Settings toggles this via existing registration settings APIs (`automatic` | `mcp_cli`), with clear copy:

- Automatic = “Auto initialize when a tool opens a project”
- Manual = “Only initialize when I add a project”

## Architecture

```
ctx dashboard
    → dashboard_server (background, 127.0.0.1:private_port)
        → static light UI (HTML/CSS/JS or minimal Vite build checked in as static)
        → /ce-dashboard/api/* JSON
            → repo_lifecycle / project_id / storage_policy / doctor / certify
            → RuntimeManager / sync_status / resources / accel load-only
```

Units:

| Module | Responsibility |
|--------|----------------|
| `pipeline/dashboard_port.py` | Stable uncommon port + lock/pid file |
| `pipeline/dashboard_server.py` | Background HTTP server + static + API routes |
| `pipeline/dashboard_ui/` | Light static assets |
| `pipeline/repo_presence.py` | Missing detection + move/replace/delete validation |
| Extend `repo_lifecycle.py` | Locate/reattach, clear_index, forget, list with presence |
| Extend `__main__.py` | `dashboard` CLI |
| Tests | Port selection, presence validation, API actions, admission toggle |

## API sketch (localhost only)

- `GET /ce-dashboard/api/overview`
- `GET /ce-dashboard/api/repos`
- `POST /ce-dashboard/api/repos/initialize` `{path}`
- `POST /ce-dashboard/api/repos/{id}/locate` `{path}`
- `POST /ce-dashboard/api/repos/{id}/unmanage`
- `POST /ce-dashboard/api/repos/{id}/clear-index`
- `POST /ce-dashboard/api/repos/{id}/forget` `{confirm}`
- `POST /ce-dashboard/api/repos/{id}/pause|resume|sync|rebuild|pin`
- `GET /ce-dashboard/api/health`
- `GET /ce-dashboard/api/storage`
- `GET /ce-dashboard/api/runtime`
- `GET|POST /ce-dashboard/api/settings` (admission mode, retention, auto cap)
- `GET /ce-dashboard/api/graph/{id}`

All mutating routes refuse non-loopback peers.

## Error handling

- Missing path on action → 409 with `state=missing` and Locate hint
- Forget without confirm / not eligible → 400/403
- Port bind failure → try alternatives; if exhausted, exit nonzero with message
- Backend doctor/certify failures surface as cards, not blank pages

## Testing

- Unit: port derivation stability; presence validator matrix (moved / replaced / deleted / transient)
- API: initialize, unmanage keeps store, clear-index removes store, forget requires confirm
- Settings: automatic ↔ manual round-trip
- CLI: status/stop/start reuse same PID file
- UI smoke: overview loads and lists fixture repos (lightweight)

## Acceptance

1. `ctx dashboard` opens a clean light UI on an uncommon localhost URL under `/ce-dashboard`.
2. Operator can switch Auto vs Manual admission.
3. Operator can add, pause, unmanage, clear index, rebuild, and forget (confirmed) repos.
4. Deleted-looking repos become Missing; Forget is blocked until validation (+ confirm).
5. Health/runtime/storage/graph pages surface necessary operator state without LAN exposure.

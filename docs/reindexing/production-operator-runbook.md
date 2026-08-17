# Production Context Engine — Operator Runbook

## Is CE ready?

Use the gates below. **Do not claim rollout readiness unless `ctx certify --skip-daemon` reports `ok: true` and `ctx test core` passes.**

| Tier | Command | When |
|------|---------|------|
| Quick | `python -m pipeline test quick` or `.\scripts\ce-test.ps1 quick` | Every agent change (~3s) |
| Core | `python -m pipeline test core` | Before merge / daily |
| Fault | `python -m pipeline test fault` | Before release |
| Install | `python -m pipeline test install` | Opt-in; needs network/clients |
| Clients | `python -m pipeline test clients --clients` | Opt-in; Cursor/Kiro/Codex SDK |
| Certify | `python -m pipeline certify . --skip-daemon` | Release gate |

## Proper daily use

1. `python -m pipeline preflight .`
2. `python -m pipeline engine ensure .`
3. `python -m pipeline doctor .`
4. Install / refresh MCP (`python scripts/install_mcp.py` or `python -m pipeline setup`) so `CTX_MCP_SURFACE=phase`
5. Reload MCP in Cursor
6. Prefer `map` → `focus` → `workspace` → `status` (phase surface)

## Local operator dashboard

Start the loopback-only operator UI with:

```text
ctx dashboard
```

The equivalent module command is `python -m pipeline dashboard`. Both commands
start the dashboard in the background and open its `/ce-dashboard` page on
`127.0.0.1`. Use `ctx dashboard --no-open` (or
`python -m pipeline dashboard --no-open`) when no browser should be opened.
Check the managed process with `ctx dashboard --status` and stop it with
`ctx dashboard stop`; the same arguments work with `python -m pipeline
dashboard`.

The dashboard is an operator view over existing Context Engine state. Its Graph
page reads the selected repository's existing `graphify-out/graph.json`
artifact; viewing a graph never builds, rewrites, or deletes graph data.

### Missing is not Forget

- **Missing** means the repository is not currently present at its registered
  path. The path may be temporarily unavailable or the repository may have
  moved. Use **Locate** when the same repository identity exists at a new path.
- **Forget** removes Context Engine's managed identity and local index
  artifacts. It does not delete source files. Forget remains unavailable until
  presence validation has classified the missing repository as eligible after
  the configured retention period, and the operator types the repository ID to
  confirm.
- A path occupied by a different or unidentifiable repository is
  **Replaced/Conflict**, not safely deleted. Resolve or locate it; do not force a
  Forget from the dashboard.

### Automatic and Manual admission

- **Automatic** admission registers repositories as Context Engine encounters
  them, subject to the configured admission limits. Use it for normal local
  development where discovered repositories should become managed.
- **Manual** admission (`mcp_cli`) registers repositories only through explicit
  MCP or CLI actions. Use it on controlled machines where repository enrollment
  must be deliberate.

Change the mode on the dashboard **Settings** page. The selection controls
future admission; it does not forget repositories that are already managed.

## Runtime profile commands

- `ctx init` is the first-time setup path. It detects hardware, installs the
  matching provider, warms the model, calibrates the batch ceiling, and saves
  the preferred profile. If a profile is already saved, plain `ctx init`
  reuses it without detecting or recalibrating.
- `ctx init --repair` is the explicit recovery path. It may detect hardware
  again, repair provider packages/model state, recalibrate, and replace the
  saved profile.
- `ctx doctor .` is read-only. It checks the saved provider, performs an
  offline warm-up of the already-cached saved model, and reports readiness and
  repair guidance. It never chooses a profile, installs packages, or
  recalibrates.
- `ctx serve .` starts from the saved profile only. If no profile exists,
  startup requires `ctx init`; it does not auto-select or install. A transient
  accelerated embedding failure may activate the bounded in-process CPU
  backup without changing the saved preference.

## What “ready” means

- Dependencies present or explicitly refused (`preflight`)
- Index artifacts coherent (`publication_manifest` checksums)
- Soft search fails loud when not ready (no fake empty hits)
- Daemon binding matches the workspace you are editing
- Live dirty sync is the freshness path (not a 4‑minute full reindex loop)

## Interpret certification results

- `passed` means the check executed and proved its expected behavior.
- `failed_required` means a required check executed and failed; any nonzero value blocks rollout.
- `skipped` is neutral, never included in `passed`, and does not prove readiness for that capability.
- Permission-denial simulation is skipped on platforms where a deterministic chmod denial is unavailable. Run the equivalent OS/ACL fault lab before rollout when that check is skipped.
- External-client checks remain opt-in. A skipped client matrix does not certify Cursor, Kiro, or Codex integration.

## Still not automatic

- Missing parsers/models → index/search refuse (install deps)
- Worktree vs main checkout → must open/bind that path
- External IDE clients → opt-in client tier
- Sleep/wake / real disk-full labs → optional fault simulations

## Repair cheat sheet

| Symptom | Action |
|---------|--------|
| `soft_search_ready=false` | `doctor` → `register --force` / reopen |
| Corrupt manifest | rebuild index |
| Wrong repo bound | `engine ensure <path>` |
| MCP tools are search/read | set `CTX_MCP_SURFACE=phase`, reinstall MCP, reload |
| Storm `needs_full` | idle `rebuild` when safe |

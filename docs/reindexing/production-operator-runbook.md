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

1. `ctx setup` once per machine
2. `ctx init <repo>` for each codebase
3. Use Cursor. Do not start/stop the engine by hand.

Optional: `ctx doctor --fix`, `ctx dashboard`.

## Install once, then init each repo

From a published package (no clone):

```text
pip install scubiee && ctx setup
```

or

```text
npm install -g scubiee
```

Then `ctx init [path]`. `ctx setup` still does **not** start the GPU engine.

1. `pip install -e .`
2. `ctx setup` — one machine command: detect CPU/DML/CUDA, install the matching
   runtime, download the model, calibrate batch size, register a **logon
   supervisor** (no GPU at boot or logon), write Cursor MCP.
3. `ctx init [path]` — put that codebase under management, index it, and start
   the engine on demand.
4. After that, watching/sync plus idle-stop/sleep-wake keep it managed.

`ctx setup --repair` redoes hardware/profile/batch. `ctx setup --status` prints
the saved profile. `ctx init` does **not** install runtimes.

Power behavior:

- **Boot:** nothing GPU-related starts.
- **Logon:** a tiny supervisor starts in standby. The engine stays off.
- **First `ctx init` or Cursor MCP use:** engine starts and warms that repo.
- **Idle 30 minutes** (no user/MCP/CLI requests; `/health` does not count):
  engine stops. Supervisor stays.
- **Sleep/wake:** supervisor reconciles dirty files; it does not full-reindex.
- **Logoff:** supervisor ends; the engine is stopped (Windows job object and/or supervisor SIGTERM → `ctx engine` stop). macOS uses LaunchAgent `com.contextengine.supervisor`.
- Unregister: `ctx engine autostart --off`.
- **macOS runtime** uses CoreML (`CoreMLExecutionProvider`) so embeddings run on
  Metal GPU and, on Apple Silicon, the Neural Engine. `onnxruntime` macOS wheels
  already ship this provider — no CUDA/DirectML package. If CoreML cannot warm
  the model, CE falls back to CPU for that process without changing the saved
  preference. Force CPU with `ctx setup --profile cpu --repair`.

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

- `ctx setup` is the first-time machine install. If a profile is already saved,
  plain `ctx setup` reuses it without detecting or recalibrating.
- `ctx setup --repair` is the explicit hardware recovery path.
- `ctx init [path]` enrolls a repository and indexes it. It refuses if `ctx setup`
  has not saved a profile.
- `ctx doctor .` is read-only by default. It checks the saved provider, performs
  an offline warm-up of the already-cached saved model, and reports readiness
  plus a classified repair plan. It never chooses a profile, installs packages,
  or recalibrates.
- `ctx doctor --all` doctors every managed repository.
- `ctx doctor --fix` (or `ctx doctor --all --fix`) applies **safe** repairs
  only: rebind the running daemon to this workspace, initialize an unusable
  index, and replay a dirty journal. It does not pip-install, run
  `setup --repair`, rebuild a corrupt publication, or Forget a repository.
- Dashboard Health exposes the same plan and an **Apply safe repairs** button.
- `ctx serve .` starts from the saved profile only. If no profile exists,
  startup requires `ctx setup`; it does not auto-select or install. A transient
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
| `soft_search_ready=false` | `doctor --fix` (initialize) or dashboard Apply safe repairs |
| Corrupt manifest | rebuild index (manual) |
| Wrong repo bound | `doctor --fix` or `engine ensure <path>` |
| MCP tools are search/read | set `CTX_MCP_SURFACE=phase`, reinstall MCP, reload |
| Storm `needs_full` | idle `rebuild` when safe |

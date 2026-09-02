# Commands reference

All commands are `scubiee <subcommand>`.

Run `scubiee <subcommand> --help` for flags on your installed version.

---

## Install & machine

| Command | Purpose |
|---------|---------|
| `scubiee --version` | Version, Python path, uninstall hint |
| `scubiee setup` | First-time machine install (GPU detect, model, MCP) |
| `scubiee setup --repair` | Re-run detect, pip/ORT install, calibration (**use after upgrade or broken deps**) |
| `scubiee setup --status` | Print saved accel profile (read-only) |
| `scubiee setup --profile dml` | Force DirectML (Windows AMD/Intel) |
| `scubiee setup --profile cuda` | Force NVIDIA CUDA |
| `scubiee setup --profile cpu` | Force CPU |
| `scubiee setup --profile mlx` | Force MLX (Apple Silicon) |
| `scubiee preflight [path]` | Check faiss, rapidfuzz, semantic backend |
| `scubiee preflight . --lexical-only` | Skip semantic backend requirement |

---

## Project lifecycle

| Command | Purpose |
|---------|---------|
| `scubiee init [path]` | Register repo + index (default path: `.`) |
| `scubiee init . --fast` | Fast index: `.py` under standard code roots |
| `scubiee init . --fast --roots packages,src` | Fast index limited to listed folders |
| `scubiee init . --no-index` | Register only |
| `scubiee init . --confirm` | Allow indexing when >400 files (see indexing doc) |
| `scubiee register [path]` | Same consent flow as MCP registration |
| `scubiee register . --always-allow` | Skip future MCP prompts |
| `scubiee initialize [path]` | Managed repo init + reconcile existing index |
| `scubiee activate [path]` | Mark repo active (also un-pauses a **paused** repo since 0.3.11) |
| `scubiee pause [path] [--reason text]` | Pause background indexing for this repo |
| `scubiee resume [path]` | Resume **global** stop after `scubiee stop` (not per-repo pause — use `activate`) |
| `scubiee list` | JSON list of managed repos |
| `scubiee remove [path]` | Unmanage repo in registry only (keeps index store unless `--delete-store`) — prefer **`wipe --confirm`** for full cleanup |
| `scubiee remove [path] --delete-store` | Unmanage + delete `~/.scubiee/projects/<id>/` (no VectorDB / `.scubiee` / repo rules cleanup) |
| `scubiee never-index [path] [--reason text]` | Permanently refuse indexing for this path |

---

## Index & search

| Command | Purpose |
|---------|---------|
| `scubiee index [path]` | Full index pipeline |
| `scubiee index . --fast --roots packages` | Scoped fast index |
| `scubiee index . --confirm` | Bypass >400 file safety gate |
| `scubiee index . --force` | Force full re-index |
| `scubiee sync [path]` | Incremental sync (changed files) |
| `scubiee sync . --confirm` | Sync when >400 files would change |
| `scubiee sync-now [path]` | Lifecycle freshness reconciliation (blocked when repo is **paused** — use `activate` first) |
| `scubiee rebuild [path]` | Force full rebuild |
| `scubiee search <query> [path]` | Semantic + lexical search |
| `scubiee search "foo" . --local --top-k 5` | In-process search |
| `scubiee status [path]` | Index + freshness JSON (`enrolled: false` / `unmanaged` if never initialized) |

---

## Diagnostics

| Command | Purpose |
|---------|---------|
| `scubiee doctor [path]` | Readiness report + **install identity** (active binary, PATH duplicates) |
| `scubiee doctor . --fix` | Apply safe fixes |
| `scubiee doctor --all` | All managed repos |
| `scubiee certify [path]` | Release certification gate |
| `scubiee certify . --skip-daemon` | Certify without daemon checks |
| `scubiee diagnose [--no-tests]` | Installation diagnostics + shareable log file |
| `scubiee diagnose --desktop` | Write `Desktop/scubiee-diagnose.json` (easy to share) |
| `scubiee diagnose --output path.json` | Custom log path (expands `$env:…` / `%VAR%`) |
| `scubiee unlock-tool` | **Windows:** free `%APPDATA%\uv\tools\scubiee` locks (MCP-off → stop → rename/remove). Use before reinstall when Access denied |
| `scubiee upgrade` | Unlock/stop Scubiee processes, upgrade package, restart, migrate |
| `scubiee migrate [path]` | Check if data migration is needed after upgrade |
| `scubiee migrate --apply [path]` | Apply migration for one repo |
| `scubiee migrate --check-all` | Check all managed projects |
| `scubiee migrate --apply-all` | Apply migrations for all managed projects |
| `scubiee resources` | Hardware + live pressure |
| `scubiee resources --refresh` | Re-detect hardware |
| `scubiee test quick [path]` | Run quick pytest tier (**requires pytest in the same Python env** — mainly for git checkouts) |

---

## Engine & dashboard

| Command | Purpose |
|---------|---------|
| `scubiee engine status [path]` | Daemon health |
| `scubiee engine ensure [path] --wait 45` | Start/wait for healthy daemon |
| `scubiee engine start [path]` | Start daemon + watchdog |
| `scubiee engine stop` | Stop daemon |
| `scubiee engine run [path]` | Foreground daemon |
| `scubiee serve [path]` | Alias for foreground serve (port 8765) |
| `scubiee dashboard --no-open` | Start operator dashboard |
| `scubiee dashboard --status` | Dashboard URL / PID / health |
| `scubiee dashboard stop` | Stop dashboard |
| `scubiee stop` | **Global stop** — tears down MCP/rules, blocks most CLI until `scubiee resume` |
| `scubiee resume` | Resume after **global** `scubiee stop` (**not** per-repo pause — use `activate`) |
| `scubiee mcp [path]` | Run MCP adapter (normally invoked by Cursor) |

---

## Connect & disconnect

Writes MCP config + agent rules. **Cursor / Claude Code** are typically user-global. **Kiro, Copilot, Cline, Roo Code** also need connect **inside each project** (workspace-local MCP). See [Cursor & MCP](./cursor-mcp.md).

| Command | Purpose |
|---------|---------|
| `scubiee connect --cursor` | Cursor MCP + `~/.cursor/rules/scubiee.mdc` |
| `scubiee connect --kiro` | Kiro (+ workspace `.kiro/settings/mcp.json` when run in a repo) |
| `scubiee connect --copilot` | Copilot/VS Code (+ `.vscode/mcp.json` when in a repo) |
| `scubiee connect --cline` / `--roo-code` | Same pattern — prefer run inside project |
| `scubiee connect --all` | Connect all supported tools |
| `scubiee connect --all --dry-run` | Preview paths that would be written |
| `scubiee connect --cursor --repo <path>` | Target a specific repo for workspace-local writes |
| `scubiee disconnect --cursor` | Remove MCP entry + rule |
| `scubiee disconnect --all` | Disconnect all tools |
| `scubiee disconnect --all --all-workspaces` | Also remove workspace-local MCP files when supported |

**Supported slugs:** `cursor`, `claude-code`, `codex`, `kiro`, `windsurf`, `copilot`, `cline`, `roo-code`, `continue`, `zed`, `opencode`.

`connect`, `disconnect`, `migrate`, and `diagnose` skip the faiss bootstrap guard so they work on broken installs.

**Remember:** `init` does **not** replace `connect`. After indexing, run connect (and reload the IDE).

---

## Settings & wipe

See **[Repository lifecycle](./repo-lifecycle.md)** for pause vs stop vs wipe vs `remove`.

| Command | Purpose |
|---------|---------|
| `scubiee settings --show` | Print `prefs.json` |
| `scubiee settings --mode automatic` | Auto-register on IDE open |
| `scubiee settings --mode mcp_cli` | Consent on first MCP use |
| `scubiee wipe [path]` | **Unmanage + delete** repo enrollment, index store, VectorDB, `.scubiee`, repo MCP/rules (**requires `--confirm` or TTY prompt** since 0.3.12) |
| `scubiee wipe [path] --confirm` | Non-interactive single-repo wipe |
| `scubiee wipe --all` | **Blocked** until you confirm (see below) |
| `scubiee wipe --all --confirm` | Delete all Scubiee state on this machine (models, every connect-tool MCP/rules, enrolled repos). `--yes` is an alias |
| `scubiee wipe --all --confirm --package` | Full wipe **and** uninstall scubiee uv tool / pip package |
| `scubiee wipe --all --confirm --keep-models` | Wipe but keep CodeRank/FastEmbed model caches |
| `scubiee wipe --all --confirm --keep-package` | Wipe state but keep uv tool install |

After `--all --confirm`, JSON includes an **`audit`** block listing any **`remaining`** paths still on disk (common on Windows when Cursor holds MCP locks). Re-run after `scubiee stop` and quitting Cursor.

---

## MCP tools (inside Cursor)

Not CLI commands — exposed to the agent after MCP reload. **Full guide:** [MCP tools reference](./mcp-tools-reference.md).

Default **`phase`** surface:

| Tool | Role |
|------|------|
| `gate` | Tiny managed check (~5 tokens) — prefer at session start |
| `status` | Engine health + managed/warming flags (`detail=gate` for tiny check) |
| `map` | Ranked overview of relevant chunks/symbols (no bodies) |
| `focus` | Deep context — outline, span, neighbors, call_sites |
| `grep` | Exact literal/regex search in indexed files (`glob=`; reports truncation) |
| `glob` | Find files by path pattern in the index |
| `workspace` | Session pins / heatmap / `clear` for new topic |
| `expand` | Re-materialize a stored span by handle |
| `register_project` | Register repo with user consent (MCP or CLI) |

If `status` shows `warming: true`, retry the **tool** once after a short wait — do not poll `status()` every turn. After pause/stop use **`scubiee resume`**.

---

## Exit codes (typical)

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Error (check JSON `error` field) |
| `2` | Safety pause — confirm required (`wipe` without `--confirm`, `wipe --all` without `--yes`, or large index/sync without `--confirm`) |

---

## Related

- [Repository lifecycle](./repo-lifecycle.md)
- [MCP tools reference](./mcp-tools-reference.md)
- [Getting started](./getting-started.md)
- [Indexing & projects](./indexing-and-projects.md)
- [Troubleshooting](./troubleshooting.md)

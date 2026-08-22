# Commands reference

All commands are `scubiee <subcommand>`. Legacy alias: `ctx` (same binary).

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
| `scubiee activate [path]` | Mark repo active |
| `scubiee pause [path] [--reason text]` | Pause background indexing |
| `scubiee resume [path]` | Resume indexing |
| `scubiee list` | JSON list of managed repos |
| `scubiee remove [path]` | Unmanage repo (keeps store unless `--delete-store`) |
| `scubiee remove [path] --delete-store` | Also delete index data |
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
| `scubiee sync-now [path]` | Lifecycle freshness reconciliation |
| `scubiee rebuild [path]` | Force full rebuild |
| `scubiee search <query> [path]` | Semantic + lexical search |
| `scubiee search "foo" . --local --top-k 5` | In-process search |
| `scubiee status [path]` | Index + freshness JSON |

---

## Diagnostics

| Command | Purpose |
|---------|---------|
| `scubiee doctor [path]` | Readiness report |
| `scubiee doctor . --fix` | Apply safe fixes |
| `scubiee doctor --all` | All managed repos |
| `scubiee certify [path]` | Release certification gate |
| `scubiee certify . --skip-daemon` | Certify without daemon checks |
| `scubiee resources` | Hardware + live pressure |
| `scubiee resources --refresh` | Re-detect hardware |
| `scubiee test quick [path]` | Run quick pytest tier |

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
| `scubiee stop` | Stop engine, watchdog, MCP-related processes |
| `scubiee mcp [path]` | Run MCP adapter (normally invoked by Cursor) |

---

## Settings & wipe

| Command | Purpose |
|---------|---------|
| `scubiee settings --show` | Print `prefs.json` |
| `scubiee settings --mode automatic` | Auto-register on IDE open |
| `scubiee settings --mode mcp_cli` | Consent on first MCP use |
| `scubiee wipe [path]` | Remove repo identity + local CE files for one repo |
| `scubiee wipe --all` | **Blocked** until you confirm (see below) |
| `scubiee wipe --all --yes` | Delete all CE state on this machine |
| `scubiee wipe --all --yes --package` | Full wipe **and** uninstall scubiee package |
| `scubiee wipe --all --confirm` | Same as `--yes` (alias) |
| `scubiee wipe --all --yes --keep-models` | Wipe but keep model cache |
| `scubiee wipe --all --yes --keep-package` | Wipe state but keep uv tool install |

---

## MCP tools (inside Cursor)

Not CLI commands — exposed to the agent after MCP reload:

| Tool | Role |
|------|------|
| `status` | Engine health + repo binding |
| `grep` | Pattern search (honors glob, reports truncation) |
| `glob` | File path discovery |
| `map` | Ranked symbol/chunk map for a query |
| `focus` | Deep read around a symbol |
| `search` | Hybrid retrieval |
| `sync_index` | Trigger incremental sync |
| `set_repo` / `register_project` | Bind workspace |

---

## Exit codes (typical)

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | Error (JSON error on stdout for init/index) |
| `2` | Usage error or wipe guard (`--all` without `--yes`) |

---

## Related

- [Getting started](./getting-started.md)
- [Indexing & projects](./indexing-and-projects.md)
- [Troubleshooting](./troubleshooting.md)

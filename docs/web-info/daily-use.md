# Daily use

Once `scubiee setup` and `scubiee init` are done, these are the commands you use day to day.

---

## Typical workflow

```bash
cd your-project
scubiee status .          # index health + sync state
scubiee sync .            # incremental update after git pull / edits
scubiee search "AuthService" . --local
```

In Cursor, the MCP tools call the same engine automatically after you save files (keeper sync every ~5 minutes in automatic mode).

---

## Keep the index fresh

| Command | When to use |
|---------|-------------|
| `scubiee sync .` | After pulling changes or large local edits |
| `scubiee sync-now .` | Force reconciliation through lifecycle manager |
| `scubiee rebuild .` | Full re-index from scratch (slow; fixes corruption) |

If sync refuses with a file count message, add `--confirm`:

```bash
scubiee sync . --confirm
```

**Tip:** Semantic search works best on **`.py`** files that are part of the index. Plain `.txt` or ignored paths may not appear in search results.

---

## Search from the terminal

```bash
scubiee search "query text" . --top-k 8
scubiee search "query text" . --local    # in-process, no HTTP daemon
```

Argument order: **query first**, optional **path** second (defaults to `.`).

---

## Manage multiple repos

```bash
scubiee list
scubiee activate /path/to/repo
scubiee pause /path/to/repo --reason "maintenance"
scubiee resume /path/to/repo
scubiee remove /path/to/other --delete-store
```

`list` prints JSON for every managed project: `project_id`, paths, index state, paused flag.

---

## Registration without indexing

Useful for CI or preparing a repo before a long index:

```bash
scubiee register . --no-index
scubiee initialize . --no-index
```

To register and skip future MCP consent prompts:

```bash
scubiee register . --always-allow --fast
```

---

## Settings

```bash
scubiee settings --show
scubiee settings --mode automatic    # IDE opens register + index automatically
scubiee settings --mode mcp_cli      # first MCP use asks for consent
```

Prefs are stored in `~/.context-engine/prefs.json`.

---

## Resource / hardware info

```bash
scubiee resources
scubiee resources --refresh
```

Shows CPU/RAM pressure and the active embed batch from calibration. Indexing pauses only when **free RAM** is critically low (not when Windows reports high “used” RAM from file cache).

Disable resource manager entirely (not recommended):

```bash
set CTX_RM_DISABLE=1          # Windows
export CTX_RM_DISABLE=1       # macOS/Linux
```

---

## Operator dashboard

```bash
scubiee dashboard --no-open     # start on a free localhost port
scubiee dashboard --status      # URL, PID, health
scubiee dashboard stop          # stop dashboard process
```

The dashboard is separate from the main engine port (`8765`). Use `--status` to see the actual URL (port is dynamic).

---

## Engine daemon

Usually started automatically by MCP or `init`. Manual control:

```bash
scubiee engine status .
scubiee engine ensure . --wait 45
scubiee engine stop
scubiee stop                    # stop engine + watchdog + MCP-related processes (preferred before uninstall)
```

Logs: `~/.context-engine/engine.log`, `~/.context-engine/watchdog.log`.

---

## Stop before uninstall or upgrade (Windows)

```bash
scubiee stop
```

Then see [Uninstall on Windows](./uninstall-windows.md).

---

## Health checks

```bash
scubiee doctor .
scubiee doctor . --fix          # safe repairs only (no pip install / rebuild)
scubiee doctor --all            # every managed repo
scubiee preflight .
scubiee certify . --skip-daemon # full certification gate
```

---

## Run tests (developers)

```bash
scubiee test quick .
scubiee test core .
```

Tiers: `quick`, `core`, `fault`, `install`, `clients`, `all`.

---

## Environment variables (common)

| Variable | Effect |
|----------|--------|
| `CTX_INCREMENTAL_MAX_TOUCH` | File-count cap before `--confirm` required (default `400`) |
| `CTX_FAST_ROOTS` | Comma roots for `--fast` indexing |
| `CTX_RM_DISABLE=1` | Disable RAM admission pauses |
| `CTX_WATCHDOG=0` | Disable daemon watchdog sidecar |
| `CTX_MLX=0` | Force non-MLX path on Mac |
| `CTX_COMPRESS=off` | Disable pre-embed compression (default is `mix`) |

Full list: see [Commands reference](./commands-reference.md) and engineering docs.

---

## Related

- [Commands reference](./commands-reference.md)
- [Indexing & projects](./indexing-and-projects.md)
- [Cursor & MCP](./cursor-mcp.md)
- [Troubleshooting](./troubleshooting.md)

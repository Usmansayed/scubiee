# Daily use

Once `scubiee setup --repair`, `scubiee init .`, and `scubiee connect --…` are done, these are the commands you use day to day.

**Docs assume [scubiee 0.3.14](https://pypi.org/project/scubiee/0.3.14/).** Install/debug: [Install & debug](./install-and-debug.md).

---

## Typical workflow

```bash
cd your-project
scubiee status .          # index health + sync state
scubiee sync .            # incremental update after git pull / edits
scubiee search "AuthService" .
```

In Cursor, MCP tools use the same engine. After large edits, `sync` (or wait for background refresh).

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

**Tip:** Semantic search works best on files that are part of the index (e.g. `.py` under your init scope).

---

## Search from the terminal

```bash
scubiee search "query text" .
scubiee search "query text" . --local    # in-process, no HTTP daemon
```

Argument order: **query first**, optional **path** second (defaults to `.`).

---

## Connect / disconnect / diagnose / upgrade

```bash
scubiee connect --cursor --dry-run
scubiee connect --all
# Special-4: run inside each project
scubiee connect --kiro
scubiee disconnect --cursor
scubiee diagnose --no-tests --desktop
scubiee migrate --check-all          # after upgrading
scubiee upgrade                      # stops processes, then upgrades
```

After any upgrade, re-run **`connect`** so MCP + agent rules match the new version.

---

## Manage multiple repos

```bash
scubiee list
scubiee activate /path/to/repo      # also un-pauses a paused repo
scubiee pause /path/to/repo --reason "maintenance"
```

**Per-repo pause** → resume with **`scubiee activate`**, not `scubiee resume`.

### Unmanage one repo and delete its data

```bash
scubiee wipe /path/to/repo --confirm
```

Removes enrollment, index store, VectorDB, `.scubiee`, and repo MCP/rules. Does **not** delete your source code. Full details: [Repository lifecycle](./repo-lifecycle.md).

`scubiee remove` only drops registry tracking (optional `--delete-store`); prefer **`wipe --confirm`** for a complete cleanup.

---

## Stop / resume (machine-wide)

```bash
scubiee stop      # stop engine, watchdog, free file locks
scubiee resume    # bring Scubiee back (NOT "wake")
```

---

## Registration without indexing

```bash
scubiee register . --no-index
scubiee init . --no-index
scubiee register . --always-allow --fast
```

---

## Settings

```bash
scubiee settings --show
scubiee settings --mode automatic    # IDE opens register + index automatically
scubiee settings --mode mcp_cli      # first MCP use asks for consent
```

Prefs: `~/.scubiee/prefs.json`.

---

## Resource / hardware info

```bash
scubiee resources
scubiee resources --refresh
```

Indexing pauses only when **free RAM** is critically low (not when Windows reports high “used” RAM from file cache).

```bash
set CTX_RM_DISABLE=1          # Windows
export CTX_RM_DISABLE=1       # macOS/Linux
```

---

## Operator dashboard

```bash
scubiee dashboard --no-open
scubiee dashboard --status
scubiee dashboard stop
```

Separate from engine port `8765`. Port is dynamic — use `--status` for the URL.

---

## Engine daemon

```bash
scubiee engine status .
scubiee engine ensure . --wait 45
scubiee engine stop
scubiee stop                    # preferred before uninstall/upgrade on Windows
```

Logs: `~/.scubiee/engine.log`, `~/.scubiee/watchdog.log`.

---

## Health checks

```bash
scubiee doctor .
scubiee doctor . --fix
scubiee doctor --all
scubiee preflight .
scubiee diagnose --no-tests --desktop
```

---

## Environment variables (common)

| Variable | Effect |
|----------|--------|
| `CTX_INCREMENTAL_MAX_TOUCH` | File-count cap before `--confirm` (default `400`) |
| `CTX_FAST_ROOTS` | Comma roots for `--fast` indexing |
| `CTX_RM_DISABLE=1` | Disable RAM admission pauses |
| `CTX_WATCHDOG=0` | Disable daemon watchdog sidecar |
| `CTX_MLX=0` | Force non-MLX path on Mac |
| `CTX_COMPRESS=off` | Disable pre-embed compression (default is `mix`) |

---

## Related

- [Repository lifecycle](./repo-lifecycle.md)
- [MCP tools reference](./mcp-tools-reference.md)
- [Commands reference](./commands-reference.md)
- [Cursor & MCP](./cursor-mcp.md)
- [Troubleshooting](./troubleshooting.md)
- [Getting started](./getting-started.md)

# Dashboard & engine

Scubiee runs a local HTTP daemon (default `127.0.0.1:8765`) plus an optional **operator dashboard** on a dynamic localhost port.

---

## Scubiee daemon

| Command | Action |
|---------|--------|
| `scubiee engine status .` | JSON health, bound repo, warm state |
| `scubiee engine ensure . --wait 45` | Start if down; wait until healthy |
| `scubiee engine start .` | Start daemon + watchdog sidecar |
| `scubiee engine stop` | Stop daemon |
| `scubiee engine run .` | Run in foreground (debug) |
| `scubiee serve .` | Same as foreground serve on port 8765 |

Environment:

| Variable | Default | Meaning |
|----------|---------|---------|
| `CTX_ENGINE_URL` | `http://127.0.0.1:8765` | Daemon URL for CLI/MCP client |

Logs:

- `~/.scubiee/engine.log`
- `~/.scubiee/watchdog.log`

The **watchdog** restarts the daemon if it crashes. Disable: `CTX_WATCHDOG=0`.

---

## Operator dashboard

Separate lightweight UI for repo list, pause/resume, forget, and accel status.

```bash
scubiee dashboard --no-open     # start without opening browser
scubiee dashboard --status      # print URL, PID, health JSON
scubiee dashboard stop          # stop dashboard process
```

Example `--status` output:

```json
{
  "url": "http://127.0.0.1:50281/ce-dashboard",
  "pid": 16840,
  "ok": true,
  "running": true
}
```

The port is **not fixed** — always use `scubiee dashboard --status` to get the URL.

### Dashboard failed to start (Windows)

**Symptom:** `RuntimeError: dashboard server failed to become healthy`

**Cause (fixed in 0.2.82):** On Windows, process group creation made the spawned PID differ from the PID reported in health JSON.

**Fix:** Upgrade to **scubiee 0.3.13+** and retry:

```bash
uv tool install --force scubiee==0.3.13 --index-url https://pypi.org/simple --refresh
scubiee dashboard --no-open
scubiee dashboard --status
```

If it still fails, run `scubiee doctor .` and check firewall/antivirus blocking localhost ports.

---

## Stop everything (before uninstall)

```bash
scubiee stop
```

Stops:

- Engine daemon
- Watchdog
- MCP-related processes using the uv tool Python (Windows)

Prefer **`scubiee stop`** over `scubiee engine stop` alone when preparing for wipe/uninstall.

---

## Autostart / supervisor (optional)

Advanced Windows/macOS scheduled-task integration:

```bash
scubiee engine autostart --off     # remove logon task
scubiee engine supervisor --logon  # standby / GPU cleanup path
```

Most users rely on MCP auto-start instead.

---

## Related

- [Daily use](./daily-use.md)
- [Cursor & MCP](./cursor-mcp.md)
- [Troubleshooting](./troubleshooting.md)

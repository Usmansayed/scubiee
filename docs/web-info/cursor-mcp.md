# Cursor & MCP

Scubiee integrates with Cursor through the **Model Context Protocol (MCP)**. The MCP server talks to a local Context Engine daemon on `http://127.0.0.1:8765` by default.

---

## First-time setup

1. Install Scubiee: `uv tool install scubiee==0.2.54 --index-url https://pypi.org/simple`
2. Run machine setup: `scubiee setup --repair`
3. Connect Cursor: `scubiee connect --cursor` (or `scubiee connect --all`)
4. Initialize your repo: `cd project && scubiee init . --fast`
5. **Reload MCP in Cursor:** Settings → MCP → refresh (or restart Cursor)

### `setup` vs `connect`

| Command | Writes |
|---------|--------|
| `scubiee setup --repair` | GPU profile, model cache, MCP entry, optional logon supervisor |
| `scubiee connect --cursor` | `~/.cursor/mcp.json` + `~/.cursor/rules/context-agent.mdc` |

Both use the **same Cursor rule file** (`context-agent.mdc`). Prefer **`connect`** when you only need tool wiring. Prefer **`setup --repair`** after upgrade, GPU change, or broken deps.

To remove Cursor wiring:

```bash
scubiee disconnect --cursor
```

Legacy installs may still have `~/.cursor/rules/context-engine.mdc` — `disconnect` and `wipe --all --yes` clean that up too.

---

## Registration modes

| Mode | Behavior |
|------|----------|
| **automatic** (default) | Opening a workspace registers it and keeps the index fresh |
| **mcp_cli** | First MCP tool use returns a consent prompt; you approve via MCP or `scubiee register` |

Check / change:

```bash
scubiee settings --show
scubiee settings --mode mcp_cli
scubiee settings --mode automatic
```

Register manually with no prompt next time:

```bash
scubiee register . --always-allow --fast
```

---

## MCP tools (phase surface)

After reload, the default **`phase`** surface exposes these tools to the agent:

| Tool | Use for |
|------|---------|
| `status` | Is the engine healthy? Which repo is bound? **Call once per session.** |
| `map` | Ranked overview of relevant chunks/symbols |
| `focus` | Deep context around a hit |
| `grep` | Text pattern search (supports `glob=`; reports truncation) |
| `glob` | Find files by path pattern |
| `workspace` | Session / workspace context |
| `register_project` | Register repo with explicit user consent |

**Important:** `grep`/`glob` only search **indexed** content and declared globs. An empty result with `truncated: false` means no match **in that scope** — not necessarily “file does not exist on disk.”

Other surfaces (`read`, `nav`, …) exist for advanced configs via `CTX_MCP_SURFACE`.

---

## Cursor rule (native tool ban)

`scubiee connect --cursor` and `setup` install `.cursor/rules/context-agent.mdc`, instructing the agent to:

1. Call `status()` once at session start
2. If `status.managed` and `status.ok` → use CE MCP for code discovery
3. If unmanaged or unhealthy → ignore the rule and use native tools

If the agent ignores MCP:

1. Confirm MCP server is green in Cursor Settings
2. Run `scubiee doctor .`
3. Reload MCP / restart Cursor

---

## MCP cannot start / ModuleNotFoundError

**Symptom:** Cursor MCP log shows `ModuleNotFoundError: pipeline` or wrong Python.

**Fix:**

```bash
scubiee setup --repair    # rewrites mcp.json
# or
scubiee connect --cursor  # refreshes MCP + rule
```

Verify `~/.cursor/mcp.json` uses the Python under your Scubiee install (on Windows: `%APPDATA%\uv\tools\scubiee\Scripts\python.exe`).

---

## Stale search after edits

**Symptom:** Agent search misses a change you just saved.

**Fix:**

```bash
scubiee sync .
```

The daemon keeps an in-memory engine — sync publishes a new generation when refreshed.

**Test tip:** Put a unique string in a **`.py`** file, save, sync, then search — `.txt` files may not be in the index.

---

## MCP locks files on Windows (uninstall)

While Cursor is open, MCP holds `python.exe` under the uv tool directory.

```bash
scubiee stop
# quit Cursor or disable MCP
scubiee wipe --all --yes --package
```

Check JSON `audit.remaining` if folders persist. See [Uninstall on Windows](./uninstall-windows.md).

---

## Related

- [Getting started](./getting-started.md)
- [Commands reference](./commands-reference.md)
- [Dashboard & engine](./dashboard-and-engine.md)
- [Troubleshooting](./troubleshooting.md)

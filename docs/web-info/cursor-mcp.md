# Cursor & MCP

Scubiee integrates with Cursor through the **Model Context Protocol (MCP)**. The MCP server talks to a local Context Engine daemon on `http://127.0.0.1:8765` by default.

---

## First-time setup

1. Install Scubiee: `uv tool install scubiee …`
2. Run machine setup: `scubiee setup --repair`
3. Initialize your repo: `cd project && scubiee init . --fast`
4. **Reload MCP in Cursor:** Settings → MCP → refresh (or restart Cursor)

Setup writes (or updates) `~/.cursor/mcp.json` with a `context-engine` entry pointing at the Scubiee MCP adapter.

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

## MCP tools (agent-facing)

After reload, the agent should use **Context Engine MCP** for code location (when your Cursor rule is enabled):

| Tool | Use for |
|------|---------|
| `status` | Is the engine healthy? Which repo is bound? |
| `grep` | Text pattern search (supports `glob=`; reports truncation) |
| `glob` | Find files by path pattern |
| `map` | Ranked overview of relevant chunks/symbols |
| `focus` | Deep context around a hit |
| `search` | Hybrid semantic + lexical retrieval |
| `sync_index` | Push disk changes into the index |
| `set_repo` / `register_project` | Bind workspace to a project root |

**Important:** `grep`/`glob` only search **indexed** content and declared globs. An empty result with `truncated: false` means no match **in that scope** — not necessarily “file does not exist on disk.”

---

## Cursor rule (native tool ban)

Many projects ship `.cursor/rules/context-agent.mdc` instructing the agent to **locate code only via CE MCP** (`map`, `focus`, `grep`, `glob`, `status`) and not native IDE search — except when `status()` is unhealthy.

If the agent ignores MCP:

1. Confirm MCP server is green in Cursor Settings
2. Run `scubiee doctor .`
3. Reload MCP / restart Cursor

---

## MCP cannot start / ModuleNotFoundError

**Symptom:** Cursor MCP log shows `ModuleNotFoundError: pipeline` or wrong Python.

**Cause:** MCP config points at a Python that is not the uv tool venv (symlink resolution on Mac was a common bug; fixed in recent releases).

**Fix:**

```bash
scubiee setup --repair    # rewrites mcp.json
```

Verify `~/.cursor/mcp.json` uses the Python under your Scubiee install (on Windows: `%APPDATA%\uv\tools\scubiee\Scripts\python.exe`).

---

## Stale search after edits

**Symptom:** Agent search misses a change you just saved.

**Fix:**

```bash
scubiee sync .
```

Or invoke MCP `sync_index`. The daemon keeps an in-memory engine — local CLI sync without daemon refresh was a historical bug; current releases publish to the daemon after sync.

**Test tip:** Put a unique string in a **`.py`** file, save, sync, then search — `.txt` files may not be in the index.

---

## MCP locks files on Windows (uninstall)

While Cursor is open, MCP holds `python.exe` under the uv tool directory. You **cannot** `uv tool uninstall` until processes stop.

```bash
scubiee stop
# quit Cursor or disable MCP
scubiee wipe --all --yes --package
```

See [Uninstall on Windows](./uninstall-windows.md).

---

## Related

- [Getting started](./getting-started.md)
- [Dashboard & engine](./dashboard-and-engine.md)
- [Troubleshooting](./troubleshooting.md)

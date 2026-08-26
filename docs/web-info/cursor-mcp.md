# Cursor & MCP

Scubiee integrates with AI coding tools through the **Model Context Protocol (MCP)**. The MCP server talks to a local Context Engine daemon (default `http://127.0.0.1:8765`).

**Docs assume scubiee 0.2.82.**

---

## First-time setup

```text
1. uv tool install --force scubiee==0.2.82 --index-url https://pypi.org/simple
2. scubiee setup --repair
3. cd your-project && scubiee init .
4. scubiee connect --cursor
5. Reload MCP in Cursor (Settings → MCP → refresh)
```

### `setup` vs `init` vs `connect`

| Command | Writes |
|---------|--------|
| `scubiee setup --repair` | Machine GPU/CPU/MLX profile, model cache, optional supervisor; may refresh MCP paths |
| `scubiee init .` | Repo enrollment + **index** (`.context-engine/id.json`, project store). **Not** MCP/rules |
| `scubiee connect --cursor` | `~/.cursor/mcp.json` + `~/.cursor/rules/context-agent.mdc` |

Prefer **`connect`** after every upgrade so rules stay current. Prefer **`setup --repair`** after GPU change or missing FastEmbed/ORT.

```bash
scubiee disconnect --cursor
```

---

## Special-4 hosts (per-repo connect)

These tools need a **workspace-local** MCP file in addition to (or instead of relying on) global MCP:

| Tool | Command (run inside the project) | Typical paths |
|------|----------------------------------|---------------|
| Kiro | `scubiee connect --kiro` | `.kiro/settings/mcp.json` |
| Copilot / VS Code | `scubiee connect --copilot` | `.vscode/mcp.json`, `.mcp.json` |
| Cline | `scubiee connect --cline` | `.cline/mcp.json` |
| Roo Code | `scubiee connect --roo-code` | `.roo/mcp.json` |

If connect runs outside a project folder, you may only get global wiring — the CLI warns you to run again inside the repo.

---

## What the agent should do (`status`)

At session start the agent calls **`status()` once**:

| Fields | Meaning |
|--------|---------|
| `managed: true` | This workspace is enrolled (after `init`) |
| `ok: true` | Daemon is healthy — use Scubiee tools |
| `warming: true` | Managed but daemon not ready yet — use tools; retry tool once if needed; **do not poll `status()` in a loop** |
| `managed: false` | Use native tools for now; retry `status()` after you run `init` / `connect` (event-driven — not every turn) |

When paused/stopped, follow **`scubiee resume`** (not `wake`).

---

## MCP tools (default `phase` surface)

| Tool | Use for |
|------|---------|
| `status` | Health + managed flag (once per session / after init) |
| `map` | Ranked overview of relevant chunks/symbols |
| `focus` | Deepen context around a hit |
| `grep` | Text pattern search (`glob=` supported; may set `truncated`) |
| `glob` | Find files by path pattern |
| `workspace` | Session / workspace context |

`grep`/`glob` search **indexed** content. Empty + `truncated: false` means no match in that scope — not “file missing on disk.”

---

## Cursor rule

`connect` / `setup` install `.cursor/rules/context-agent.mdc`:

1. Call `status()` at session start  
2. If managed + ok → use Scubiee MCP for discovery  
3. If warming → use tools; don’t busy-loop on `status()`  
4. If unmanaged → native tools; retry `status()` only after user runs init/connect  

If the agent ignores MCP: confirm MCP is green → `scubiee connect --cursor` → reload MCP.

---

## MCP cannot start / wrong Python

```bash
scubiee connect --cursor
# or
scubiee setup --repair
```

On Windows, `mcp.json` should point at `%APPDATA%\uv\tools\scubiee\Scripts\python.exe`.

---

## Stale search after edits

```bash
scubiee sync .
```

Put a unique string in a **`.py`** file in scope, sync, then search.

---

## Windows: MCP locks files

```bash
scubiee stop
# quit Cursor or disable MCP
scubiee wipe --all --yes --package
```

See [Uninstall on Windows](./uninstall-windows.md).

---

## Related

- [Getting started](./getting-started.md)
- [Troubleshooting](./troubleshooting.md)
- [Commands reference](./commands-reference.md)
- [FAQ](./faq.md)

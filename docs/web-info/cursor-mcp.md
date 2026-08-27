# Cursor & MCP

Scubiee integrates with AI coding tools through the **Model Context Protocol (MCP)**. The MCP server name is **`scubiee`**. It talks to the local Scubiee daemon (default `http://127.0.0.1:8765`).

**Docs assume [scubiee 0.2.88](https://pypi.org/project/scubiee/0.2.88/)** (published on PyPI). Install/debug: [Install & debug](./install-and-debug.md).

---

## First-time setup

```text
1. uv tool install --force scubiee==0.2.88 --index-url https://pypi.org/simple --refresh
2. scubiee setup --repair
3. cd your-project && scubiee init .
4. scubiee connect --cursor
5. Reload MCP in Cursor (Settings → MCP → refresh)
```

### `setup` vs `init` vs `connect`

| Command | Writes |
|---------|--------|
| `scubiee setup --repair` | Machine GPU/CPU/MLX profile, model cache, optional supervisor |
| `scubiee init .` | Repo enrollment + **index**. **Not** MCP/rules |
| `scubiee connect --cursor` | Global `~/.cursor/mcp.json` + rules **and** project `.cursor/mcp.json` (absolute `CTX_REPO`) |

Prefer **`connect`** after every upgrade so rules and project pins stay current. Prefer **`setup --repair`** after GPU change or missing FastEmbed/ORT.

```bash
scubiee disconnect --cursor
```

---

## Cursor workspace pin (important)

Cursor does **not** expand `${workspaceFolder}` in global `~/.cursor/mcp.json`. A literal token makes MCP resolve to your home folder → `managed: false`.

**0.2.87+ pin / 0.2.88+ sidebar bind:**

- Global MCP entry: **no** `CTX_REPO` / `CURSOR_*` workspace tokens
- Project `.cursor/mcp.json`: **absolute** `CTX_REPO` for the repo where you ran `connect`

Always run `scubiee connect --cursor` **from the project** you want managed, then reload MCP.

### Multiple repos in one Cursor app (sidebar)

One MCP process is shared across chats. A pin must not make an unindexed sidebar repo look managed.

- On `status()` (and later `map` / `grep` / …), pass `root` = that chat’s Workspace Path.
- Managed is true only if that folder (walking up) has `.scubiee/id.json` and is in the registry.
- Other chats: `managed: false` after one `status()` — use native tools; do not keep calling Scubiee.
- After a successful `status()`, you can pass `project_id` (`ce_…`) instead of the full path.

---

## Special-4 hosts (per-repo connect)

These tools need a **workspace-local** MCP file:

| Tool | Command (run inside the project) | Typical paths |
|------|----------------------------------|---------------|
| Kiro | `scubiee connect --kiro` | `.kiro/settings/mcp.json` |
| Copilot / VS Code | `scubiee connect --copilot` | `.vscode/mcp.json`, `.mcp.json` |
| Cline | `scubiee connect --cline` | `.cline/mcp.json` |
| Roo Code | `scubiee connect --roo-code` | `.roo/mcp.json` |

---

## What the agent should do (`status`)

At session start the agent calls **`status()` once**:

| Fields | Meaning |
|--------|---------|
| `managed: true` | This workspace is enrolled (after `init`) |
| `ok: true` | Daemon is healthy — use Scubiee tools |
| `warming: true` | Managed but daemon not ready yet — use tools; retry tool once; **do not poll `status()` in a loop** |
| `managed: false` | Use native tools for now; retry `status()` after you run `init` / `connect` |

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

`connect` / `setup` install `.cursor/rules/scubiee.mdc`:

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

On Windows, MCP should use `%APPDATA%\uv\tools\scubiee\Scripts\python.exe` (via the `scubiee-mcp` / `scubiee` shim).

---

## Stale search after edits

```bash
scubiee sync .
```

Put a unique string in a **`.py`** file in scope, sync, then search.

---

## Windows: MCP locks files (Access denied on reinstall)

```bash
scubiee unlock-tool
uv tool install --force scubiee==0.2.88 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
scubiee connect --cursor
```

Do **not** rely on Admin/reboot. See [Install & debug](./install-and-debug.md) and [Uninstall on Windows](./uninstall-windows.md).

---

## Related

- [Install & debug](./install-and-debug.md)
- [Getting started](./getting-started.md)
- [Troubleshooting](./troubleshooting.md)
- [Commands reference](./commands-reference.md)
- [FAQ](./faq.md)

# Scubiee — user guides

These docs are for **operators and end users**: install, daily use, troubleshooting, and uninstall. They are written so you can resolve most issues without reading engineering notes.

**Need more detail (why things break, every error code, every file path)?**  
See **[`web-info/` — detailed documentation hub](../../web-info/README.md)** (`how-everything-works`, `complete-fix-guide`, `error-codes-reference`, `data-and-files-reference`).

**Current release:** [`scubiee 0.3.15`](https://pypi.org/project/scubiee/0.3.15/) — **published on PyPI**.  
Pin this version in install commands until you intentionally upgrade.

**Upgrading from 0.2.x?** Read **[What's changed since 0.2.88](../whats-changed-since-0.2.88.md)** first.

**Product identity:** CLI + MCP server key = **`scubiee`**. On-disk data = **`~/.scubiee`** and **`<repo>/.scubiee`**. There is no legacy `context-engine` MCP key or `.context-engine` data path.

---

## Start here

| If you want to… | Read |
|-----------------|------|
| **Upgrade from 0.2.x — what changed?** | **[What's changed since 0.2.88](../whats-changed-since-0.2.88.md)** |
| **Install, upgrade, or debug package issues** | **[Install & debug](./install-and-debug.md)** ← full end-user playbook |
| Install and index your first repo | [Getting started](./getting-started.md) |
| Learn everyday commands and workflows | [Daily use](./daily-use.md) |
| **Unmanage a repo / delete its index data** | **[Repository lifecycle](./repo-lifecycle.md)** |
| Look up a specific command | [Commands reference](./commands-reference.md) |
| **All MCP tools — what they do** | **[MCP tools reference](./mcp-tools-reference.md)** |
| Fix something that broke | [Troubleshooting](./troubleshooting.md) · **[Detailed fix guide](../../web-info/complete-fix-guide.md)** |
| Understand indexing, confirm gates, fast mode | [Indexing & projects](./indexing-and-projects.md) |
| Use Scubiee inside Cursor (MCP) | [Cursor & MCP](./cursor-mcp.md) |
| Connect/disconnect AI tools from CLI | [Commands reference](./commands-reference.md#connect--disconnect) |
| Open the operator dashboard or manage the engine | [Dashboard & engine](./dashboard-and-engine.md) |
| Short Q&A | [FAQ](./faq.md) |

---

## By platform

| Platform | Doc |
|----------|-----|
| **Windows** (DirectML, CPU-only laptops, uv locks) | [Windows guide](./windows.md) |
| **Windows uninstall / repair** | [Uninstall on Windows](./uninstall-windows.md) |
| **macOS / Linux** | [Mac & Linux](./mac-and-linux.md) |
| **Uninstall (general)** | [Uninstall (Mac/Linux)](./uninstall-mac-linux.md) |

---

## Quick answers

| Question | Answer |
|----------|--------|
| What do I run on a new PC? | `uv tool install scubiee==0.3.15` → `scubiee setup --repair` → `cd your-repo` → `scubiee init .` → `scubiee connect --cursor` |
| Does `init` wire Cursor? | **No.** `init` indexes the repo. **`connect`** writes MCP + agent rules. |
| Agent says unmanaged? | Run `connect` in that project (and for Kiro/Copilot/Cline/Roo: run connect **inside each repo**). Cursor also needs project `.cursor/mcp.json` (written by connect). |
| Pause / stop — how do I continue? | **Per-repo pause:** `scubiee activate .` · **Global stop:** `scubiee resume` (not `engine start`). There is **no** `scubiee wake`. |
| `status` on a new folder? | `enrolled: false`, `state: "unmanaged"` until you run `scubiee init .` |
| Wipe one repo without prompt? | `scubiee wipe . --confirm` — see [Repository lifecycle](./repo-lifecycle.md) |
| Unmanage vs pause vs stop? | [Repository lifecycle](./repo-lifecycle.md) |
| `sync-now` while repo paused? | Blocked — run `scubiee activate .` first (0.3.13+) |
| `status` shows warming? | Daemon is starting. Use tools once; wait briefly and retry the **tool** — do not poll `status()` in a loop. |
| `init` says `machine_not_setup`? | Run `scubiee setup --repair` first. |
| Diagnose looks fine but `init` fails after reinstall? | Stale `accel.json` with missing packages — run `scubiee setup --repair`, then `scubiee diagnose --desktop`. |
| Why did init refuse my home folder? | Safety gate — run init **inside your project**, not `C:\Users\you` or `/`. |
| `uv tool install` Access denied (Windows)? | **`scubiee unlock-tool`**, then reinstall — **not** Admin/reboot. See [Install & debug](./install-and-debug.md). |
| `No module named 'pipeline'` after failed install? | Half-deleted uv tool dir — unlock/PS1 repair, then reinstall + `setup --repair`. |
| Setup worked before but preflight fails now? | `scubiee setup --repair`. |

---

## Canonical install sequence

```text
1. uv tool install --force scubiee==0.3.15 --index-url https://pypi.org/simple --refresh
2. scubiee setup --repair          # once per machine (GPU/CPU/MLX + model)
3. cd path\to\your\repo
4. scubiee init .                  # index this repo (does NOT write MCP)
5. scubiee connect --cursor        # MCP + rules (Special-4: inside each project)
6. Reload MCP in the IDE
```

Windows Access denied during step 1 → `scubiee unlock-tool` (or `scripts/uninstall-uv-scubiee.ps1` if the CLI is already broken), then retry.

---

## Where data lives

| Location | What |
|----------|------|
| `<repo>/.scubiee/id.json` | Stable project id for this repo (small; often gitignored) |
| `<repo>/.cursor/mcp.json` | Cursor **project** MCP pin (absolute `CTX_REPO`) from `connect --cursor` |
| `~/.scubiee/registry.json` | Which repos are managed |
| `~/.scubiee/projects/<id>/` | Index store (chunks, graph, vectors) |
| `~/.scubiee/accel.json` | GPU/CPU/MLX profile and calibrated batch size |
| `~/.cursor/mcp.json` | Cursor global MCP (from **`connect`**; no unexpanded `${workspaceFolder}` for CTX_REPO) |
| `~/.cursor/rules/scubiee.mdc` | Cursor agent rule (from **`connect`** / setup) |
| `%APPDATA%\uv\tools\scubiee\` (Windows) | uv tool env (CLI + MCP Python) |

---

## Engineering docs (not for end users)

- **Website / product writing:** [`../../web-info/product-guide-for-website.md`](../../web-info/product-guide-for-website.md)
- Architecture / internals: [`../engg/`](../engg/)
- Maintainer release notes: [`../session-info/`](../session-info/)
- **What's changed since 0.2.88:** [`../whats-changed-since-0.2.88.md`](../whats-changed-since-0.2.88.md)
- Publishing to PyPI: [`../publish-setup.md`](../publish-setup.md)
- Pre-production journey notes: [`../journey-audit-pre-production-2026-08-26.md`](../journey-audit-pre-production-2026-08-26.md)

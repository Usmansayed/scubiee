# Scubiee — user guides

These docs are for **operators and end users**: install, daily use, troubleshooting, and uninstall. They are written so you can resolve most issues without reading engineering notes.

**Current release:** `scubiee 0.2.82` on [PyPI](https://pypi.org/project/scubiee/).  
(Pin this version in install commands until you intentionally upgrade.)

---

## Start here

| If you want to… | Read |
|-----------------|------|
| Install and index your first repo | [Getting started](./getting-started.md) |
| Learn everyday commands and workflows | [Daily use](./daily-use.md) |
| Look up a specific command | [Commands reference](./commands-reference.md) |
| Fix something that broke | [Troubleshooting](./troubleshooting.md) |
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
| What do I run on a new PC? | `uv tool install scubiee==0.2.82` → `scubiee setup --repair` → `cd your-repo` → `scubiee init .` → `scubiee connect --cursor` |
| Does `init` wire Cursor? | **No.** `init` indexes the repo. **`connect`** writes MCP + agent rules. |
| Agent says unmanaged? | Run `connect` in that project (and for Kiro/Copilot/Cline/Roo: run connect **inside each repo**). |
| Pause / stop — how do I continue? | `scubiee resume` (global) or `scubiee resume .` (per-repo). There is **no** `scubiee wake`. |
| `status` shows warming? | Daemon is starting. Use tools once; wait briefly and retry the **tool** — do not poll `status()` in a loop. |
| `init` says `machine_not_setup`? | Run `scubiee setup --repair` first. |
| Diagnose looks fine but `init` fails after reinstall? | Stale `accel.json` with missing packages — run `scubiee setup --repair`, then `scubiee diagnose --desktop`. |
| Why did init refuse my home folder? | Safety gate — run init **inside your project**, not `C:\Users\you` or `/`. |
| `uv tool install` Access denied (Windows)? | Stop Scubiee / quit Cursor, remove the uv tool dir, reinstall. See [Windows](./windows.md) / [Uninstall](./uninstall-windows.md). |
| Setup worked before but preflight fails now? | `scubiee setup --repair`. |

---

## Canonical install sequence

```text
1. uv tool install --force scubiee==0.2.82 --index-url https://pypi.org/simple
2. scubiee setup --repair          # once per machine (GPU/CPU/MLX + model)
3. cd path\to\your\repo
4. scubiee init .                  # index this repo (does NOT write MCP)
5. scubiee connect --cursor        # MCP + rules (Special-4: inside each project)
6. Reload MCP in the IDE
```

---

## Where data lives

| Location | What |
|----------|------|
| `<repo>/.context-engine/id.json` | Stable project id for this repo (small; often gitignored) |
| `~/.context-engine/registry.json` | Which repos are managed |
| `~/.context-engine/projects/<id>/` | Index store (chunks, graph, vectors) |
| `~/.context-engine/accel.json` | GPU/CPU/MLX profile and calibrated batch size |
| `~/.cursor/mcp.json` | Cursor MCP wiring (from **`connect`**, also refreshed by setup) |
| `~/.cursor/rules/context-agent.mdc` | Cursor agent rule (from **`connect`** / setup) |

---

## Engineering docs (not for end users)

- Architecture / internals: [`../engg/`](../engg/)
- Maintainer release notes: [`../session-info/`](../session-info/)
- Publishing to PyPI: [`../publish-setup.md`](../publish-setup.md)
- Pre-production journey notes: [`../journey-audit-pre-production-2026-08-26.md`](../journey-audit-pre-production-2026-08-26.md)

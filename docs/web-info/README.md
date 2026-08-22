# Scubiee — user guides

These docs are for **operators and end users**: install, daily use, troubleshooting, and uninstall. They are written so you can resolve most issues without reading engineering notes.

**Current release:** `scubiee 0.2.50` on [PyPI](https://pypi.org/project/scubiee/0.2.50/).

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
| Open the operator dashboard or manage the engine | [Dashboard & engine](./dashboard-and-engine.md) |

---

## By platform

| Platform | Doc |
|----------|-----|
| **Windows** (DirectML, uv tool install) | [Windows guide](./windows.md) |
| **Windows uninstall / repair** | [Uninstall on Windows](./uninstall-windows.md) |
| **macOS / Linux** | [Mac & Linux](./mac-and-linux.md) |
| **Uninstall (general)** | [Uninstall (Mac/Linux)](./uninstall-mac-linux.md) |

---

## Quick answers

| Question | Answer |
|----------|--------|
| What do I run first on a new PC? | `uv tool install scubiee` → `scubiee setup --repair` → `cd your-repo` → `scubiee init . --fast` |
| Why did init refuse my home folder? | Safety gate — run init **inside your project directory**, not `C:\Users\you` or `/`. See [Indexing & projects](./indexing-and-projects.md). |
| Why does `uv tool uninstall` fail? | MCP/daemon locks Python on Windows. Run `scubiee stop` then `scubiee wipe --all --yes --package`. See [Uninstall on Windows](./uninstall-windows.md). |
| Setup worked before but preflight fails now? | Run `scubiee setup --repair`. |
| More short Q&A | [FAQ](./faq.md) |

---

## Where data lives

| Location | What |
|----------|------|
| `<repo>/.context-engine/id.json` | Stable project id for this repo (small; often gitignored) |
| `~/.context-engine/registry.json` | Which repos are managed |
| `~/.context-engine/projects/<id>/` | Index store (chunks, graph, vectors) |
| `~/.context-engine/accel.json` | GPU/CPU profile and calibrated batch size |
| `~/.cursor/mcp.json` | Cursor MCP wiring (written by setup) |

---

## Engineering docs (not for end users)

- Architecture / internals: [`../engg/`](../engg/)
- Maintainer release notes: [`../session-info/`](../session-info/)
- Publishing to PyPI: [`../publish-setup.md`](../publish-setup.md)

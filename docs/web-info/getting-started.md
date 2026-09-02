# Getting started

Scubiee is a **local** context engine for AI coding tools (Cursor, Claude Code, Kiro, Copilot, and more). It indexes your repository, embeds code with CodeRank (GPU when available), and exposes search/map/focus tools over MCP.

You need **Python 3.10+**. You do **not** need to clone the GitHub repo to use it.

**Current PyPI release:** [scubiee 0.3.13](https://pypi.org/project/scubiee/0.3.13/) (published). MCP key **`scubiee`**; data under **`~/.scubiee`**.

**Upgrading from 0.2.x?** [What's changed since 0.2.88](../whats-changed-since-0.2.88.md)

Full install + debug playbook: **[Install & debug](./install-and-debug.md)**.

---

## Canonical sequence (memorize this)

| Step | Command | What it does |
|------|---------|--------------|
| 1 | `uv tool install scubiee==0.3.13 …` | Install the CLI |
| 2 | `scubiee setup --repair` | One-time **machine** setup (GPU/CPU/MLX, model, `accel.json`) |
| 3 | `cd your-repo` → `scubiee init .` | Enroll + **index this repo** |
| 4 | `scubiee connect --cursor` | Write **MCP + agent rules** for your IDE |
| 5 | Reload MCP in the IDE | Agent can call `status()` → `managed: true` |

**Important:**

- **`init` does not write MCP or rules.** After init, you still need **`connect`**.
- **`setup` alone does not make a repo managed.** You still need **`init`** inside the project.
- For **Kiro, Copilot, Cline, and Roo Code**, run `connect` **inside each project** (workspace-local MCP).
- **Cursor:** `connect --cursor` also writes project `.cursor/mcp.json` with an absolute repo pin (global `${workspaceFolder}` is not expanded by Cursor).

---

## 1. Install the CLI

**Recommended — [uv](https://docs.astral.sh/uv/) tool install:**

```powershell
# Windows — pin PyPI + version
uv tool install --force scubiee==0.3.13 --index-url https://pypi.org/simple --refresh
```

```bash
# macOS / Linux
uv tool install --force scubiee==0.3.13 --index-url https://pypi.org/simple --refresh
```

Add uv’s bin directory to PATH once, then open a **new** terminal:

```bash
uv tool update-shell
```

On Windows, shims usually live in `%USERPROFILE%\.local\bin`.

**Alternative — pip:**

```bash
pip install -U scubiee==0.3.13
```

Verify:

```bash
scubiee --version
```

The output shows **which Python** runs Scubiee. Prefer the uv tool Python (`…\uv\tools\scubiee\Scripts\python.exe` on Windows).

---

## 2. One-time machine setup

Run **once per machine** (or again after GPU/driver changes, or a broken reinstall):

```bash
scubiee setup --repair
```

This:

1. Detects hardware (CUDA, DirectML for **discrete** AMD/NVIDIA on Windows, MLX on Apple Silicon, or CPU)
2. Installs the correct ONNX Runtime + FastEmbed stack (platform extras)
3. Downloads the CodeRank **FP16** embedding model (~270 MB, cached)
4. Calibrates embed batch size and saves `~/.scubiee/accel.json`
5. May register a session supervisor / refresh MCP paths

Check without changing anything:

```bash
scubiee setup --status
```

Shareable diagnose file (easy to find on Desktop):

```bash
scubiee diagnose --no-tests --desktop
# → ~/Desktop/scubiee-diagnose.json
```

**After a broken / forced reinstall:** always run `setup --repair` before `init`. Diagnose can still show an old `accel.json` throughput number while `fastembed` / `onnxruntime` are missing — repair fixes that.

Preflight:

```bash
scubiee preflight .
# lexical only (no semantic embed):
scubiee preflight . --lexical-only
```

---

## 3. Initialize your project

**Always `cd` into your project first.** Do not run init from your user home directory.

```bash
cd /path/to/your/project
scubiee init .
# optional first pass on large repos:
scubiee init . --fast
```

| Flag | Meaning |
|------|---------|
| `.` | Index **this directory** as the project root |
| `--fast` | Index `.py` under common code roots (`packages`, `src`, `lib`, …) |
| `--no-index` | Register without building an index yet |
| `--confirm` | Required when more than **400** indexable files would be touched |
| `--roots packages,src` | Limit fast indexing to specific subfolders |

If you see `"error": "machine_not_setup"`, run `scubiee setup --repair` first.

When init finishes on a TTY, Scubiee reminds you to run **`connect`** next (MCP is not automatic).

---

## 4. Connect your AI tools

```bash
scubiee connect --cursor
# or several:
scubiee connect --cursor --claude-code
# preview:
scubiee connect --cursor --dry-run
```

**Supported tools:** `--cursor`, `--claude-code`, `--codex`, `--kiro`, `--windsurf`, `--copilot`, `--cline`, `--roo-code`, `--continue`, `--zed`, `--opencode`, or `--all`.

### Special-4 (must connect inside each project)

These hosts do not resolve the open folder from user-global MCP alone:

| Tool | Flag | Typical local file |
|------|------|--------------------|
| Kiro | `--kiro` | `.kiro/settings/mcp.json` |
| Copilot / VS Code | `--copilot` | `.vscode/mcp.json` + `.mcp.json` |
| Cline | `--cline` | `.cline/mcp.json` |
| Roo Code | `--roo-code` | `.roo/mcp.json` |

```bash
cd path/to/that/project
scubiee connect --kiro    # example
```

Then **reload MCP** in the IDE (Settings → MCP → refresh, or restart).

To remove wiring:

```bash
scubiee disconnect --cursor
```

---

## 5. Sanity checks

```bash
scubiee status .
scubiee doctor .
scubiee search "your symbol name" .
scubiee diagnose --no-tests --desktop
scubiee dashboard --status
```

In the agent: call Scubiee **`status()`** once. Expect `managed: true` after init+connect. If `warming: true`, the daemon is still starting — use tools; do not spam `status()`.

---

## Upgrade path

```bash
scubiee upgrade
# or pin explicitly:
scubiee unlock-tool   # Windows: if Access denied / half-broken tool dir
uv tool install --force scubiee==0.3.13 --index-url https://pypi.org/simple --refresh

scubiee setup --repair
scubiee connect --cursor   # refresh MCP + rules after version bumps
```

If `uv tool install --force` fails with **Access denied** on Windows, run **`scubiee unlock-tool`** first (not Admin/reboot). See [Install & debug](./install-and-debug.md) and [Windows guide](./windows.md#access-denied-on-upgrade-or-reinstall).

Note: prefer `--force` with an explicit version over bare `uv tool upgrade`.

---

## Pause / stop / resume

| Goal | Command |
|------|---------|
| Stop engine / free GPU / unlock files | `scubiee stop` |
| Resume after global stop/pause | `scubiee resume` |
| Pause one repo’s indexing | `scubiee pause .` |
| Resume one repo | `scubiee resume .` |

There is **no** `scubiee wake` — if an old message said “wake”, run **`resume`**.

---

## Next steps

- [Daily use](./daily-use.md)
- [Cursor & MCP](./cursor-mcp.md)
- [Troubleshooting](./troubleshooting.md)
- [Windows guide](./windows.md) · [Mac & Linux](./mac-and-linux.md)
- [FAQ](./faq.md)

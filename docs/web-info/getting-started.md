# Getting started

Scubiee is a **local** Context Engine for Cursor: it indexes your codebase, embeds code with CodeRank (GPU when available), and exposes search/locate tools over MCP.

You need **Python 3.10+**. You do **not** need to clone the GitHub repo to use it.

---

## 1. Install the CLI

**Recommended — [uv](https://docs.astral.sh/uv/) tool install** (isolated, no venv juggling):

```powershell
# Windows — always pin PyPI and version on Windows
uv cache clean scubiee
uv tool install --force scubiee==0.2.54 --index-url https://pypi.org/simple --refresh
```

```bash
# macOS / Linux
uv tool install scubiee==0.2.54 --index-url https://pypi.org/simple
```

Add uv’s bin directory to PATH once (then restart the terminal):

```bash
uv tool update-shell
```

On Windows, uv usually installs shims to `%USERPROFILE%\.local\bin`. Ensure that folder is on PATH.

**Alternative — pip:**

```bash
pip install -U scubiee==0.2.54
```

Verify:

```bash
scubiee --version
```

The output shows **which Python** runs Scubiee. If you have Miniconda and a uv tool install, make sure `scubiee --version` points at the uv tool Python (`…\uv\tools\scubiee\Scripts\python.exe` on Windows).

---

## 2. One-time machine setup

Run **once per machine** (or again after GPU/driver changes):

```bash
scubiee setup --repair
```

This:

1. Detects hardware (CUDA, DirectML, MLX on Apple Silicon, or CPU)
2. Installs the correct ONNX Runtime + FastEmbed stack
3. Downloads the CodeRank **FP16** embedding model (~270 MB, cached)
4. Calibrates embed batch size and saves `~/.context-engine/accel.json`
5. Writes Cursor MCP config and optional logon supervisor

Check status without changing anything:

```bash
scubiee setup --status
```

**Important:** On Windows, `scubiee setup` alone can fail on a **brand-new** install if an old `accel.json` exists but FastEmbed is not installed yet. If you see `No module named 'fastembed'`, run:

```bash
scubiee setup --repair
```

Preflight should pass after setup:

```bash
scubiee preflight .
```

Use `--lexical-only` if you only need grep/glob (no semantic search):

```bash
scubiee preflight . --lexical-only
```

---

## 3. Initialize your project

**Always `cd` into your project first.** Do not run init from your user home directory.

```bash
cd /path/to/your/project
scubiee init . --fast
```

| Flag | Meaning |
|------|---------|
| `.` | Index **this directory** as the project root |
| `--fast` | Index `.py` files under common code roots only (`packages`, `src`, `lib`, …) — good first run |
| `--no-index` | Register the repo without building an index yet |
| `--confirm` | Required when more than **400** indexable files would be touched (safety gate) |
| `--roots packages,src` | Limit fast indexing to specific subfolders |

Example for a large monorepo:

```bash
scubiee init . --fast --roots packages
# or, if the tool reports >400 files:
scubiee init . --fast --confirm
```

Success prints JSON with `"ok": true`, a `project_id`, and chunk counts when indexed.

If you see `"error": "machine_not_setup"`, run `scubiee setup --repair` first — `init` requires a saved machine profile in `~/.context-engine/accel.json`.

---

## 4. Connect Cursor and other AI tools

**Recommended (0.2.54+):** use `connect` to install MCP config **and** the Cursor agent rule in one step:

```bash
scubiee connect --cursor
# or every supported tool:
scubiee connect --all
```

Preview without writing files:

```bash
scubiee connect --cursor --dry-run
```

This writes:

- `~/.cursor/mcp.json` — `context-engine` MCP server entry
- `~/.cursor/rules/context-agent.mdc` — one-shot `status()` rule (same template as `setup`)

`scubiee setup --repair` also writes MCP config; you can use **either** `setup` or `connect` for Cursor. Prefer **`connect`** when you only need tool wiring without re-running GPU calibration.

To remove wiring:

```bash
scubiee disconnect --cursor
```

Then **reload MCP in Cursor:** Settings → MCP → refresh (or restart Cursor).

---

## 5. Sanity checks

```bash
scubiee status .
scubiee doctor .
scubiee search "your symbol name" .
scubiee diagnose --no-tests
scubiee migrate --check-all
scubiee dashboard --no-open
scubiee dashboard --status
```

Optional release gate (maintainers / power users):

```bash
scubiee certify . --skip-daemon
```

---

## Upgrade path

When a new version is published:

```bash
uv tool install --force scubiee==0.2.54 --index-url https://pypi.org/simple --refresh
scubiee setup --repair
```

Note: `uv tool upgrade scubiee` refreshes dependencies but may **not** bump the Scubiee version — prefer `--force` with an explicit version.

---

## Next steps

- [Daily use](./daily-use.md) — sync, search, lifecycle commands
- [Indexing & projects](./indexing-and-projects.md) — confirm gates, home directory block, never-index
- [Troubleshooting](./troubleshooting.md) — faiss, ORT, MCP, stale registry
- [Windows guide](./windows.md) — DirectML, uv, repair scripts

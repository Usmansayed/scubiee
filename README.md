# Scubiee

Local Context Engine: Merkle sync → Graphify AST → **mix** compress → CodeRankEmbed (MLX FP16 on Apple Silicon, FastEmbed CUDA/DirectML elsewhere) → TurboQuant/FAISS → Conductor `R_plan`

## Install (no git clone)

Requires **Python 3.10+**. Two steps on a clean machine:

```bash
pip install -U scubiee
ctx setup
```

**npm** (optional wrapper — same pip install + `ctx setup`):

```bash
npm install -g scubiee
```

Then `ctx init <repo>` for each codebase, and reload MCP in Cursor (Settings → MCP → refresh).

`ctx setup` picks **CUDA** (NVIDIA), **DirectML** (Windows AMD/Intel), **MLX FP16** (Apple Silicon Metal), **CoreML** (Intel Mac), or **CPU**. On a MacBook, `pip install -U scubiee` already installs FastEmbed, ONNX Runtime, and **MLX** — no `[mlx]` / `[coreml]` extra required. Then `ctx setup` (or `ctx setup --repair` after an upgrade) writes the MLX FP16 profile. Opt out: `CTX_MLX=0` or `ctx setup --profile cpu`.

If PyPI is behind GitHub, install the tagged release:

```bash
pip install "scubiee @ git+https://github.com/Usmansayed/new-context-engine.git@v0.2.6"
ctx setup
```

From a git checkout (contributors only): `pip install -e .` then `ctx setup`. Maintainers: see `docs/publish-setup.md`.

## Use

Inside the engine process there are **three managers** only:

| Manager | Role |
|---------|------|
| **RuntimeManager** | Workspace lifecycle, publish search generation after sync, serve queries |
| **IndexManager** | Merkle probe, full index, incremental sync |
| **ResourceManager** | CPU/RAM admission and embed batching |

A tiny **watchdog** sidecar (not a manager) polls `/health` and restarts the daemon if it crashes. Disable: `CTX_WATCHDOG=0`.

**Install-and-forget check** (isolated port/home):

```powershell
.\.venv\Scripts\python.exe -u scripts\sim_install_forget.py
```

## Use

In Cursor: call MCP tools after reload.

CLI (optional):

```powershell
ctx index .
ctx search "login validate"
ctx sync .
ctx status .
```

Or: `python -m pipeline index .`

Default pre-embed compression is **`mix`** with a **512-char** cap (locked). Opt out: `CTX_COMPRESS=off`.

## Resource management

Indexing and embedding run at the calibrated batch. The resource manager **only pauses** if free RAM is near empty (default under 256 MB). CPU spikes and Windows “RAM % used” (file cache) do not stop work.

```powershell
ctx resources              # live pressure + hardware
ctx resources --refresh    # re-detect CPU/RAM/GPU/libs
ctx init                   # also writes hardware.json + picks fastest ORT backend
```

Disable entirely: `CTX_RM_DISABLE=1`. Emergency floor: `CTX_RM_MIN_FREE_RAM_MB`.

## Cursor MCP

After install, MCP tools talk to the local Context Engine service (`CTX_ENGINE_URL`, default `http://127.0.0.1:8765`). The MCP process auto-starts that service if needed.

Tools: `search_code`, `locate_capability`, `grep_code`, `file_outline`, `status`, `sync_index`, `set_repo`, `register_project`.

Dashboard (optional): http://127.0.0.1:8765/dashboard

Advanced (usually unnecessary):

```powershell
ctx engine status
ctx engine stop
ctx engine run .                   # foreground service
```

`ctx engine start` also starts the watchdog sidecar. Logs: `~/.context-engine/watchdog.log`.

**Registration modes** (dashboard or CLI):

| Mode | Trigger |
|------|---------|
| **Automatic** (default) | IDE/MCP open registers the project once, then incremental indexing |
| **MCP / CLI** | No auto-init; first tool call returns a consent prompt; use `register_project` (optional `always_allow`) or `ctx register` |

```powershell
ctx settings --mode automatic
ctx settings --mode mcp_cli
ctx register . --always-allow --fast
ctx serve .   # open http://127.0.0.1:8765/dashboard
```

On open (automatic): resolves a stable **project id**, indexes if needed (`CTX_AUTO_INDEX=1`), then keeps the index fresh every **5 minutes** (changed files only — graph patch + embed together).

## Project data

| Location | Role |
|----------|------|
| `<repo>/.context-engine/id.json` | Tiny identity (`project_id`). Prefer gitignore. |
| `~/.context-engine/prefs.json` | Registration mode + indexing prefs |
| `~/.context-engine/projects/<project_id>/` | Chunks, graph, merkle, embed cache |
| `~/.context-engine/registry.json` | Maps `project_id` ↔ paths, `registered`, `always_allow` |
| `~/.context-engine/vectordb/` | FAISS + TurboQuant collections |

Path moved → id file recovers the store. Id file deleted → registry path recovers. Both gone → new id + reindex.

## Layout

| Path | Role |
|------|------|
| `packages/pipeline/` | Index, embed, FAISS+TurboQuant, MCP, sync |
| `packages/conductor/` | Retrieval fusion (`R_plan`, etc.) |
| `packages/graphify/` | Bundled AST / graph |
| `packages/enrich/`, `metadata/`, `repo_ir/` | Chunk enrichment |
| `scripts/install*` | Setup + MCP install |
| `tests/` | Unit / integration tests |
| `docs/` | Design notes + ship notes |

See `VENDOR.md` and `docs/compress-mix-shipped.md`.

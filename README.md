# Context Engine

Merkle sync → Graphify AST → **mix** compress → CodeRankEmbed (FastEmbed) → TurboQuant/FAISS → Conductor `R_plan`

## Install (one command — full MCP)

Installs the package, picks GPU/CPU, starts the background service, and registers **context-engine** in Cursor MCP.

**Windows:**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

**macOS / Linux:**

```bash
bash scripts/install.sh
```

Then reload MCP in Cursor (Settings → MCP → refresh). Tools appear as `search_code`, `locate_capability`, etc.

Already have the package?

```powershell
ctx setup
# optional: also register/index this repo
ctx setup --register --repo .
```

Or: `pip install -e ".[mcp]"` then `python -m pipeline setup`.

Internally, MCP is a thin adapter and the Context Engine runs as a local service (`:8765`) so indexing/search stay out of the MCP process. You do not manage that separately — install/setup and MCP startup handle it.

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

Indexing and embedding go through a **Resource Manager** that samples CPU/RAM and adapts throughput:

| Pressure | Behavior |
|----------|----------|
| idle | Larger embed batches |
| normal | Baseline (from accel profile) |
| busy | Smaller batches + pauses |
| critical | Background sync deferred; embeds crawl |

```powershell
ctx resources              # live pressure + hardware
ctx resources --refresh    # re-detect CPU/RAM/GPU/libs
ctx init                   # also writes hardware.json + picks fastest ORT backend
```

Disable: `CTX_RM_DISABLE=1`. Tune: `CTX_RM_MAX_CPU`, `CTX_RM_CRITICAL_CPU`, `CTX_RM_MIN_FREE_RAM_MB`.

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

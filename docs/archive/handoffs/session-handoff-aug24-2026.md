# Session Handoff: Scubiee CLI Overhaul + MCP Workspace Resolution

**Date:** August 24, 2026
**Repo:** `C:\Users\usman\Downloads\context-engine` (GitHub: Usmansayed/new-context-engine)
**Package:** scubiee (PyPI), currently at v0.2.72
**Product:** Local AI code context engine — semantic search, graph retrieval, live re-indexing. MCP server for IDE integration.

---

## Summary of Work Done This Session

### 1. Verified Live Search Reindexing
- Confirmed that editing `web-info/website-content.md` and running `scubiee sync-now .` makes the content appear in normal `scubiee search` results (not just vector DB).
- Search correctly ranked the edited file #1 using `bm25+dense+graph` hybrid channel.

### 2. FP16/INT8 Model Precision Investigation
- Confirmed: Only macOS MLX uses FP16. Windows/Linux (CUDA, DirectML, CPU) all use the FP32 ONNX model.
- Generated FP16 (274 MB) and INT8 (139 MB) variants from the FP32 (548 MB) source using ORT tools.
- Created eval script at `scripts/eval_onnx_fp32_fp16_int8.py` for comparing retrieval quality across precisions.
- FP32 baseline on DirectML: hit@8=70%, MRR=0.54 on 50 hard NL queries over ~5k chunks.
- Full 3-way eval not completed due to timeout constraints but script is ready to run.

### 3. Wipe Command Fixes (v0.2.63+)
**Problems fixed:**
- `wipe --all` didn't clean `.kiro/settings/mcp.json` or `.kiro/steering/context-engine.md`
- MCP process stayed alive after wipe (Kiro respawned it because config wasn't removed first)
- `uv tool uninstall` failed because MCP process held file locks
- `--yes` vs `--confirm` confusion

**Fixes applied:**
- Added `_kiro_mcp_paths()` and `_kiro_steering_paths()` to `wipe.py`
- Reordered `wipe_all`: remove MCP configs FIRST, then stop processes, then delete data
- Removed `--yes` flag entirely, kept only `--confirm`
- Interactive Y/N prompt when running `scubiee wipe --all` without `--confirm`
- Files: `packages/pipeline/wipe.py`, `packages/pipeline/__main__.py`

### 4. Setup Auto-Repair (v0.2.63+)
- If `scubiee setup` fails due to ORT issues, it automatically retries with `force_install=True` (same as `--repair`)
- User no longer needs to manually run `--repair`
- Added numbered progress during model download ("Step 1/3: Downloading...")
- File: `packages/pipeline/__main__.py` (`_configure_machine`)

### 5. CLI Output Overhaul (v0.2.63 - v0.2.70)
**Goal:** Clean, minimal terminal output. No JSON dumps, no library noise, just progress bars and status lines.

**What was done:**
- `cli_ui.py`: Added `branded_header()`, `suppress_stderr_noise()`, `print_wipe_summary()`, `InitProgress` class, `SetupProgress` model bar
- `cmd_init`: Branded header, interactive Y/N for large repos (shows file count + est time), single progress bar
- `cmd_setup`: Suppresses fastembed/onnxruntime/huggingface noise in TTY mode, clean error messages
- `cmd_wipe`: Uses `print_wipe_summary()` for step-by-step output
- `cmd_stop`: Simplified to just "Stopped" / "Already stopped"
- `cmd_connect/disconnect`: Clean error for "no tools specified"
- `cmd_resume`: Simplified to just "Resumed"
- All commands: No JSON output in TTY mode (JSON only for piped/CI)

**Progress bar implementation (v0.2.68-0.2.70):**
- `InitProgress` shows single `[████░░░░] 40% Embedding 1,400/3,510` bar
- `SetupProgress` shows `[████░░░░] 30% Preparing model` during download
- Indexer sends `f"Embedding {done}/{total}"` in progress callback → parsed by InitProgress
- accel.py has pulse thread during model download that increments pct every 2s
- Bar appears immediately after user confirms ("Starting…") to prevent frozen terminal feel

**Stderr noise suppression (v0.2.69):**
- `sys.stderr` is redirected to devnull during init (kills ALL `[index]`, `[embed]`, `[graphify]` noise)
- Progress bar writes to saved `_real_stderr` reference (not affected by redirect)
- `GRAPHIFY_QUIET=1` and `CTX_QUIET=1` env vars also set for the indexer's internal quiet flag

**Remaining issue:** The single progress bar during init only works for full-index path. The incremental sync path (when repo is already indexed) doesn't call the progress callbacks. For small syncs this is fine (fast enough), but for the initial "first time after wipe" case it may not show the bar if `initialize_repo` takes the reconcile path instead of the full index path.

### 6. Search Auto-Fallback (v0.2.71)
- `scubiee search "query"` now silently falls back to local search when daemon is unreachable
- No `--local` flag needed
- User just types `scubiee search "something"` and it works regardless of daemon state
- File: `packages/pipeline/__main__.py` (`cmd_search`)

### 7. MCP Workspace Resolution (v0.2.72)
**Problem:** After wipe+reinstall, MCP reports `repo: C:\...\Programs\Kiro` instead of actual workspace. `managed: false`, tools don't work.

**Root cause:** `_default_repo()` in `mcp_locate.py` trusted `CTX_REPO` unconditionally. When that env var is stale/missing, it falls back to `cwd` which is the IDE install directory.

**Fix applied:** Reordered resolution priority:
1. IDE workspace env vars → enrolled project → use it
2. `CTX_REPO` → validated (must be enrolled or have .git) → use it
3. Walk up from cwd → enrolled → use it
4. IDE workspace with .git (not enrolled) → use it
5. Raw `CTX_REPO` fallback

**Problem still remaining:** Kiro doesn't set ANY workspace env var when spawning MCP. The process `cwd` is Kiro's install dir. So steps 1 and 3 find nothing. The ONLY thing that works is having a project-level `.kiro/settings/mcp.json` with explicit `CTX_REPO`.

---

## Current Open Problem: MCP Workspace Discovery for Kiro

### The Issue
See `docs/mcp-workspace-resolution-issue.md` for full details.

When Kiro spawns the Scubiee MCP server:
- It uses the user-level config (`~/.kiro/settings/mcp.json`) which has NO `CTX_REPO`
- The spawned process has `cwd` = Kiro install dir (not the workspace)
- No env var tells us which workspace the user has open
- Result: MCP can't find the repo → `managed: false`

### What Works Right Now
Running `scubiee connect --kiro` from the repo creates `<repo>/.kiro/settings/mcp.json` with `CTX_REPO`. This project-level config overrides the user-level one and Kiro's MCP works correctly.

### Research Needed
1. Does Kiro set any env var when spawning MCP? (check `process.env` in the MCP process)
2. Does the MCP protocol `initialize` message include `rootUri` or `workspaceFolders`?
3. Can `scubiee init` auto-write the project-level configs for Kiro/Copilot?
4. Is there a way to detect the workspace from the MCP server side without env vars?

### Options Being Considered
- **Option A:** `scubiee init` auto-writes `.kiro/settings/mcp.json` and `.vscode/mcp.json`
- **Option B:** MCP checks registry for managed projects and picks the right one
- **Option C:** Wait for Kiro to set a workspace env var (not in our control)
- **Option D:** Hybrid of A + B

---

## Files Modified This Session

| File | What Changed |
|------|-------------|
| `packages/pipeline/__main__.py` | cmd_init, cmd_setup, cmd_wipe, cmd_stop, cmd_connect, cmd_disconnect, cmd_resume, cmd_search rewritten for clean CLI output + auto-fallback |
| `packages/pipeline/cli_ui.py` | branded_header, suppress_stderr_noise, print_wipe_summary, InitProgress (single bar), SetupProgress (model bar + dedup) |
| `packages/pipeline/wipe.py` | .kiro cleanup, reordered wipe_all, --confirm only |
| `packages/pipeline/accel.py` | Model download pulse thread, numbered progress, removed old threading |
| `packages/pipeline/indexer.py` | All prints gated by `quiet` flag, emb_prog sends "Embedding done/total" |
| `packages/pipeline/mcp_locate.py` | `_default_repo()` reordered — IDE vars first, CTX_REPO validated |
| `pyproject.toml` | Version bumped from 0.2.62 → 0.2.72 |
| `web-info/website-content.md` | Added "Live search experience" section (test content) |
| `scripts/eval_onnx_fp32_fp16_int8.py` | New: FP32/FP16/INT8 retrieval comparison eval script |
| `docs/mcp-workspace-resolution-issue.md` | New: Documents the workspace discovery problem |

---

## Versions Published This Session

| Version | Key Change |
|---------|-----------|
| 0.2.63 | CLI overhaul start, --yes removed, wipe .kiro cleanup |
| 0.2.64 | Init: suppress stderr, better progress |
| 0.2.65 | Indexer emb_prog sends counts, accel pulse thread |
| 0.2.66 | InitProgress bar [████░░░░], SetupProgress model bar |
| 0.2.67 | All indexer prints gated by quiet, chunks count fallback |
| 0.2.68 | Single progress bar for init |
| 0.2.69 | Redirect stderr to devnull (kills ALL noise) |
| 0.2.70 | Show "Starting…" immediately after confirm |
| 0.2.71 | Search auto-fallback to local when daemon unreachable |
| 0.2.72 | MCP workspace: IDE enrolled repo priority over stale CTX_REPO |

---

## How to Test

```powershell
# Clean install
uv tool install scubiee==0.2.72 --force --no-cache

# Setup (one time)
scubiee setup

# Init a repo (writes index + project-level MCP for Kiro)
cd C:\Users\usman\Downloads\context-engine
scubiee init .
scubiee connect --kiro  # needed for Kiro project-level config

# Search (works with or without daemon)
scubiee search "embedding model loading"

# Wipe everything
scubiee wipe --all
```

---

## Architecture Quick Reference

```
User installs: uv tool install scubiee
                    |
                    v
scubiee setup    →  detect GPU, install ORT, download CodeRank, calibrate
                    |
                    v
scubiee init .   →  parse (graphify) → chunk → embed (FastEmbed+DML) → FAISS
                    |
                    v
scubiee connect  →  write MCP configs for each IDE tool
                    |
                    v
IDE spawns MCP   →  mcp_locate.py → _default_repo() → finds workspace → serves search
```

Key files:
- `packages/pipeline/mcp_locate.py` — MCP server entry point + workspace resolution
- `packages/pipeline/__main__.py` — All CLI commands
- `packages/pipeline/cli_ui.py` — Terminal UI (progress bars, status lines)
- `packages/pipeline/indexer.py` — Full index pipeline
- `packages/pipeline/accel.py` — Hardware detection + model management
- `packages/pipeline/wipe.py` — Cleanup logic
- `packages/pipeline/embedder.py` — Embedding (FastEmbed/MLX/ST)
- `packages/pipeline/searcher.py` — Search dispatch (daemon vs local)
- `packages/pipeline/tool_registry.py` — Definitions for all 13 supported tools

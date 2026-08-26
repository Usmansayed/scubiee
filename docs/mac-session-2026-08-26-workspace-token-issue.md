# Mac session notes — workspace token + related fixes (2026-08-26)

**Machine:** Apple Silicon, macOS 26.5.2  
**Repo:** `hidden-context-engine-` (tree ~0.2.82)  
**Scope:** Document what we changed this session, and the **open Cursor regression** found when live-testing `${workspaceFolder}`.

---

## 1. Open issue: Cursor does not expand `${workspaceFolder}` in global MCP env

### Symptom (live, after disconnect → connect)

1. `uv run scubiee disconnect --cursor` then `uv run scubiee connect --cursor` from this repo.
2. `~/.cursor/mcp.json` correctly contained:
   - `CTX_REPO=${workspaceFolder}`
   - `CURSOR_PROJECT_DIR=${workspaceFolder}`
   - `CURSOR_CWD=${workspaceFolder}`
3. Agent `status()` then reported:
   - `repo=/Users/<home>`
   - `managed=false`
   - `should_retry_status=true`

### Evidence from live MCP processes

Two `scubiee-mcp` children under Cursor’s `mcp-process`:

| PID (example) | `CTX_REPO` in process env | process `cwd` | Result |
|---------------|---------------------------|---------------|--------|
| A | literal `${workspaceFolder}` (**unexpanded**) | `$HOME` | falls through to home → unmanaged |
| B | `~/Downloads/hidden-context-engine-` (tilde form from another entry) | `$HOME` | would resolve if this process were the one attached |

Also observed:

- `PWD=/` on the MCP child
- Project file `.cursor/mcp.json` still had an **absolute** `CTX_REPO` + `CTX_PROJECT_ID` (from earlier emergency / setup), but the **agent chat was attached to the broken global spawn**

### Why this breaks Scubiee

Resolver order (`mcp_locate._default_repo`):

1. IDE env (skip unexpanded `${…}` placeholders)
2. `CTX_PROJECT_ID` registry
3. cwd walk for `.context-engine/id.json`
4. live `CTX_REPO` pin
5. else `Path.cwd()`

With unexpanded tokens + cwd=`$HOME`, step 5 wins → home → `managed=false`.

### What we believed vs what we measured

| Prior research assumption | Live Mac Cursor observation |
|---------------------------|-----------------------------|
| Cursor expands `${workspaceFolder}` in **global** `~/.cursor/mcp.json` (unlike VS Code user MCP) | **Not expanded** — left as literal string in process env |
| Global-only connect + token is enough for Cursor | **Insufficient** on this Cursor build / session |

Related docs (pre-discovery research):

- [`cursor-mcp-workspace-resolution-research.md`](./cursor-mcp-workspace-resolution-research.md)
- [`mcp-workspace-mismatch-all-hosts-research.md`](./mcp-workspace-mismatch-all-hosts-research.md)

### Likely next fix directions (not implemented yet)

1. **Treat Cursor like optional project MCP** — write `.cursor/mcp.json` with absolute `CTX_REPO` + `CTX_PROJECT_ID` when connect runs inside a repo (special-4 style), keep global entry token-based or drop duplicate.
2. **Find a Cursor-native var that actually expands** on this build (if any) and prefer it.
3. **Document Cursor as “token preferred, project pin fallback”** until expansion is verified across Cursor versions.

Special-4 remain unchanged by design: **kiro, copilot, cline, roo-code** (project absolute pins).

---

## 2. Code changes in this session

### A. MCP workspace resolution (`packages/pipeline/mcp_locate.py`)

- Extended `_IDE_WORKSPACE_ENV_KEYS`: `CURSOR_CWD`, `CLAUDE_PROJECT_DIR`, `CODEX_WORKSPACE_ROOT`, `OPENCODE_DEFAULT_PROJECT`, …
- Added `_is_unexpanded_placeholder()` — ignore literal `${workspaceFolder}` / `$(…)` / `%{…}`
- `_ide_workspace_candidates` / `_ctx_repo_raw`: skip `/`, unexpanded tokens, nonexistent paths

### B. Connect writers for non-special-4 (`packages/pipeline/rules_installer.py`)

- `_WORKSPACE_FOLDER_TOKEN = "${workspaceFolder}"`
- `_inject_global_workspace_hints()` for global connect when `pin_repo=False`:
  - all non-special-4: `CTX_REPO=${workspaceFolder}`
  - Cursor: also `CURSOR_PROJECT_DIR` / `CURSOR_CWD`
  - OpenCode: `OPENCODE_DEFAULT_PROJECT`
  - windsurf / continue / zed / amp / pi / claude-code / codex: `WORKSPACE_FOLDER` as needed
- Codex: `cwd = ${workspaceFolder}` written via `_write_mcp_toml`
- Leak guard: error only on **absolute** `CTX_REPO` in global entries (tokens allowed)

Special-4 global entries still **omit** absolute `CTX_REPO` (project files keep absolute pins).

### C. Mac accel / Core ML pytest fixes

- `packages/pipeline/accel.py` — Darwin host fallback must not override explicit Linux/Windows `detected.os`; `CTX_EMBED_BACKEND=mlx` overlay must not rewrite `accel.json`
- `packages/pipeline/coreml_mac.py` — topological sort after `bypass_empty_rotary_remainders` patch

### D. Wipe

- `packages/pipeline/wipe.py` — avoid recreating FastEmbed cache during audit; MLX under `CTX_HOME` listed in model targets
- `packages/pipeline/__main__.py` — `--yes` alias for wipe `--confirm`
- `tests/test_wipe.py` — coverage for wipe behavior

### E. Tests

- `tests/test_connect_formats.py` — global entries assert `${workspaceFolder}` for non-special-4; absolute pins forbidden; windsurf/continue/zed install smoke; Mac/Windows path cases retained
- `tests/test_mcp_repo_resolution.py` — ignore unexpanded tokens; prefer `CLAUDE_PROJECT_DIR` / `CODEX_WORKSPACE_ROOT`

### F. Docs (research + handoff)

- `docs/cursor-mcp-workspace-resolution-research.md` (new)
- `docs/mcp-workspace-mismatch-all-hosts-research.md` (new)
- Minor updates: `docs/mac-cursor-session-handoff-2026-08-26.md`, `docs/macos-deferred-verification.md`
- **This file** — issue write-up + change log

---

## 3. Verification already run

| Check | Result |
|-------|--------|
| `pytest` connect formats + mcp repo resolution | **41 passed** (via `uv run --with pytest`) |
| Live `disconnect --cursor` → `connect --cursor` | Config write OK; tokens present in `~/.cursor/mcp.json` |
| Live agent `status()` after reconnect | **FAIL** — home / unmanaged (issue §1) |
| Process env inspection | Confirms unexpanded `${workspaceFolder}` |

---

## 4. Intentionally not committed

Local IDE connect artifacts / junk (absolute pins, host-specific):

- `.cline/mcp.json`, `.kiro/…`, `.roo/mcp.json`, `.mcp.json`
- `:memory:.ses`
- Generated `.venv/` / optional `uv.lock` from local `uv run`

---

## 5. Push intent

Ship the resolver + connect-token work and Mac test fixes so others can reproduce the Cursor expansion failure and iterate on the fallback (§1).

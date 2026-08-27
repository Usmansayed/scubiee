# Mac session notes — workspace token + related fixes (2026-08-26)

**Machine:** Apple Silicon, macOS 26.5.2  
**Repo:** `hidden-context-engine-` (tree ~0.2.82)  
**Scope:** Document what we changed this session, and the **Cursor `${workspaceFolder}`** issue (now fixed).

---

## 1. Cursor does not expand `${workspaceFolder}` in global MCP env — **FIXED**

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

### Fix shipped (0.2.85+)

1. **Cursor is in `_GLOBAL_OMIT_CTX_REPO_SLUGS`** — global `~/.cursor/mcp.json` no longer gets `CTX_REPO` / `CURSOR_*` tokens (same pattern as special-4).
2. **Project pin remains** — `connect --cursor` writes `.cursor/mcp.json` with absolute `CTX_REPO` (+ project id) so the workspace-attached MCP resolves correctly.
3. Resolver still ignores unexpanded placeholders if an old global config remains.

**Acceptance:** after `scubiee connect --cursor` in a managed repo, agent `status()` reports that repo path and `managed=true` (attach to project MCP / reload MCP).

Special-4 unchanged: **kiro, copilot, cline, roo-code** (project absolute pins). Cursor joins them for **global omit** only.

---

## 2. Code changes in this session

### A. MCP workspace resolution (`packages/pipeline/mcp_locate.py`)

- Extended `_IDE_WORKSPACE_ENV_KEYS`: `CURSOR_CWD`, `CLAUDE_PROJECT_DIR`, `CODEX_WORKSPACE_ROOT`, `OPENCODE_DEFAULT_PROJECT`, …
- Added `_is_unexpanded_placeholder()` — ignore literal `${workspaceFolder}` / `$(…)` / `%{…}`
- `_ide_workspace_candidates` / `_ctx_repo_raw`: skip `/`, unexpanded tokens, nonexistent paths

### B. Connect writers (`packages/pipeline/rules_installer.py`)

- `_WORKSPACE_FOLDER_TOKEN = "${workspaceFolder}"`
- `_inject_global_workspace_hints()` for global connect when `pin_repo=False`
- **Cursor + special-4 omit** `CTX_REPO` from global; project files keep absolute pins
- OpenCode / windsurf / continue / zed / amp / pi / claude-code / codex still get workspace tokens where useful
- Codex: `cwd = ${workspaceFolder}` written via `_write_mcp_toml`
- Leak guard: error only on **absolute** `CTX_REPO` in global entries (tokens allowed)

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

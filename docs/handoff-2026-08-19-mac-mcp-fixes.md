# Handoff: Mac MCP + daemon + PyPI (19–20 Aug 2026)

For the agent on the other laptop. All of this is on GitHub branch **`feat/production-certification`** and PyPI **`scubiee 0.2.13`**. Local branch matches origin (`7f390e0`).

Do **not** commit `env` (PyPI/API secrets). Bench `docs/bench-*.err.log` and `:memory:.ses` are leftover junk.

---

## How to pick up on the other machine

```bash
git fetch origin
git checkout feat/production-certification
git pull

# Install / upgrade
pip install -U scubiee==0.2.13
# or: python -m pip install -U scubiee==0.2.13

# User Mac venv was ~/scubiee (NOT ~/.context-engine/venv)
# MCP command in .cursor/mcp.json must be that venv's python, not a resolved Homebrew Cellar path.

cd <repo>
ctx setup --repair    # writes MCP config + copies Cursor rule from package template
# Restart Context Engine MCP in Cursor (or reload window)
```

Cursor rule (always-apply, gitignored locally as `.cursor/`): packaged at `packages/pipeline/templates/context-agent.mdc`. `ctx setup` copies it to `.cursor/rules/context-agent.mdc`.

PyPI: https://pypi.org/project/scubiee/0.2.13/

---

## Product surface (phase) — current MCP tools

`CTX_MCP_SURFACE=phase` (default after setup):

| Tool | Use |
|------|-----|
| `map` | Cold / meaning locate (skinny cards, no bodies) |
| `focus` | outline / span / neighbors |
| `grep` | **Known exact literal only** (import line, error string) |
| `glob` | **Known filename/path only** (stack trace, @-ref) |
| `workspace` | show / pin / clear — session brain, no bodies |
| `status` | health — never to find code |

**Policy:** MCP-only retrieval. Native Grep/Glob/SemanticSearch/Task-explore banned unless MCP is actually down (`status()` unhealthy or connection failure). Then one native locate pass, then edit.

**Do not hard-cap** map/search/focus call counts. Duplicates get `usage_hint` (advisory), never `thrash_blocked`.

---

## Commits / versions (pushed)

| Version | Commit | What |
|---------|--------|------|
| **0.2.11** | `3d475d9` | Daemon publish-after-sync; MCP venv interpreter; Mac MLX stack; **remove hard tool-usage caps** |
| **0.2.12** | `a0e4cdb` | Phase **grep + glob**; Cursor rule via setup; **MLX per-thread embed** (daemon sync GPU stream) |
| **0.2.13** | `7f390e0` | Packaged **short strict Cursor rule** (no tool how-to in the rule — tools live in MCP instructions) |

---

## Bug 1: MCP `ModuleNotFoundError: pipeline`

**Cause:** `mcp_install.interpreter()` used `Path(sys.executable).resolve()`. On macOS the venv `bin/python` is a symlink into Homebrew Cellar → no venv `site-packages`.

**Fix:** `packages/pipeline/mcp_install.py` — prefer `CTX_PYTHON`, then `sys.prefix/bin/python`, **do not resolve away the venv shim**. Same idea in `__main__.py` MCP config write.

---

## Bug 2: Stale search after `ctx sync` (daemon “not loading” new vectors)

**Cause:** CLI `cmd_sync` ran local `incremental_sync` only. Running daemon kept the old in-memory engine (generation unchanged). Search looked like the vector DB did not update until engine restart.

**Fix:** `cmd_sync` prefers daemon `/v1/sync`. After local fallback sync, call `/v1/publish` via `RuntimeManager.publish()` / `EngineClient.publish()` / `server.py` route. `ce_service.sync()` publishes when `refreshed`.

**Verify:** edit a `.py` probe, `ctx sync`, `ctx search TOKEN` → hit that file at rank 1 without restarting the engine. `status` should bump `generation`.

**Note:** only **code extensions** are indexed (`DEFAULT_EXTENSIONS`). A `.txt` probe will never appear.

---

## Bug 3: MLX `There is no Stream(gpu, 0) in current thread`

**Cause:** MLX ≥0.31 GPU streams are thread-local. Model loaded on daemon main thread; sync/embed ran on a worker.

**Fix:**
- `packages/pipeline/mlx_mac.py` — `mlx_thread_stream()`, lock around embed eval; wrap weight `mx.eval` in that stream.
- `packages/pipeline/embedder.py` — per-thread MLX model in `threading.local()` (`_ensure_mlx`).

CLI incremental sync on the main thread could succeed while **daemon `/v1/sync` failed**. Test both.

---

## Bug 4: `embed_one` skipped MLX

**Cause:** `embed_one` only treated `coderank`/`fastembed`; MLX fell through to Ollama.

**Fix:** `packages/pipeline/embedder.py` — include `mlx` on the batch/embed path.

---

## Tool usage: no hardcoded caps

**Was:** `_NAV_SOFT_CAP = 4`, `_NAV_EXACT_CAP = 3`, `_nav_search_thrash_gate`, `_phase_focus_gate` **blocked** duplicate map/search/focus (`thrash_blocked`, “map budget 4/4”).

**Now:** `_record_locate_query` tracks queries; duplicate → `usage_hint` only. Same for hybrid `hybrid_cbm/semantic.py`. Focus already-in-session → advisory, not error.

Payload size limits (`max_chars`) stay. Search-only surface still disables `mode=exact` (product, not a session call cap).

Instructions: `SERVER_INSTRUCTIONS_PHASE` / `NAV` — “USAGE (guidance — tools are never hard-blocked)”.

---

## Phase grep/glob (MCP-only trajectory)

Native Grep/Glob mixed with MCP broke the sealed trajectory. Phase now exposes MCP `grep` + `glob` with **specific-only** instructions (not discovery). `glob_impl` wraps `files_impl`. `status()` tool list must include all six tools (`mcp_locate.py` `tool_lists`).

---

## Cursor rule

- **Local (gitignored):** `.cursor/rules/context-agent.mdc` — few lines: CE only for retrieval unless MCP unavailable.
- **Shipped:** `packages/pipeline/templates/context-agent.mdc` — same text.
- **Install:** `write_cursor_rule()` in `mcp_install.py`, called from `write_cursor_mcp()`.
- MCP server instructions still have the full trajectory (map/focus/grep/glob). **Do not duplicate that in the Cursor rule** (token waste).

---

## Mac embed stack (this user’s machine)

- Apple Silicon → default **MLX FP16** (`profile=mlx` in `~/.context-engine/accel.json`).
- DirectML is **Windows** (`onnxruntime-directml` + `DmlExecutionProvider`). Not used on this Mac.
- Resource manager: `packages/pipeline/resources.py` (`class ResourceManager` ~L81).

---

## Tests that matter

- `tests/test_mcp_locate.py` — phase tools, grep/glob instructions, no hard cap, cursor rule file if present
- `tests/test_mcp_lean.py` — `PHASE_EXPECTED` = `{map, focus, grep, glob, workspace, status}`
- `tests/test_session_store.py` — phase tool set
- `tests/test_hybrid_cbm.py` — duplicate search advises, does not block
- `tests/test_runtime_publish.py` — publish-after-sync

Live: `ctx sync` then `ctx search` after a unique comment in a `.py` file.

---

## Do not regress

1. Do not reintroduce hard map/search/focus session caps.
2. Do not `Path.resolve()` the MCP python interpreter on Darwin.
3. Do not skip daemon `/v1/publish` after out-of-process sync.
4. Do not embed MLX without a per-thread stream.
5. Do not tell agents to mix native Grep/Glob with phase MCP for discovery.
6. Do not put a long tool-usage table in the Cursor rule; keep it short.

---

## Open / known

- `status.sync_status` can still show `needs_full` after catchup chunked live reindex; locate can still work.
- `.cursor/` is gitignored; other machines get the rule via `ctx setup --repair` from the package template.
- Feature branch is **not** merged to `feat/live-reindexing` / default unless someone does that separately.

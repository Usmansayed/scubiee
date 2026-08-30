# Session Summary: Mac E2E, OpenCode v2, Moved-Folder Tracking

**Date:** August 31, 2026  
**Machine:** Apple Silicon MacBook (MLX ~111 t/s)  
**Repo:** `https://github.com/Usmansayed/new-context-engine.git`  
**Local package:** scubiee 0.3.5 (with uncommitted fixes from this session)  
**Prior handoff:** [session-handoff-aug30-2026-macbook.md](./session-handoff-aug30-2026-macbook.md)

---

## What we did

### 1. Full lifecycle E2E (real CLI)

Re-ran `tests/_e2e_run_cmds.sh` after the `wipe --all --keep-package` regression fix.

| Phase | Steps | Result |
|-------|-------|--------|
| Baseline | B1, B3, B5, B7, B8, B10 | OK |
| Global stop / halt | G1–G18, H1–H2 | OK (G3 blocked while stopped — expected) |
| Repo wipe | W1, W1b, W2 | OK |
| Full wipe keep-package | G16 (confirm required), G16b | OK — **`scubiee` stayed on PATH** |
| Post-wipe recovery | P1 setup, P2 init, P3 status | OK (was broken before fix) |
| Read-only | R1–R4 help/list | OK |
| Connect dry-run | C1, C2 | OK |

**Log:** `tests/_e2e_cmd_results.txt`  
**Runtime:** ~6.5 minutes on this Mac.

**E2E script hardening:** `tests/_e2e_run_cmds.sh` now checks `scubiee on PATH` after G16b and can `uv tool install --force .` if the shim was removed.

---

### 2. `wipe --all --keep-package` must not remove CLI (critical)

**Symptom:** After G16b, `scubiee: command not found`; P1–R4 failed with exit 127.

**Cause:** `remove_tool_shims()` ran unconditionally in `wipe_all()` even when `package=False`.

**Fix (`packages/pipeline/wipe.py`):**
- Call `remove_tool_shims()` only when `package=True`.
- `audit_scubiee_artifacts`: flag `tool_shim` leftovers only when `include_package=True`.

**Test:** `tests/test_wipe.py::test_wipe_all_keep_package_preserves_tool_shims`

---

### 3. OpenCode v2 MCP schema

Scubiee previously wrote OpenCode **v1** flat shape (`mcp.scubiee` with `enabled`). OpenCode **v2** uses `mcp.servers.{name}` with `disabled`.

**Fix (`packages/pipeline/rules_installer.py`):**
- `_write_mcp_opencode` — detect v1 vs v2; fresh files default to v2; migrate flat neighbors into `mcp.servers` when upgrading.
- `_remove_mcp_opencode` — remove from both v1 flat and v2 `servers` bucket.
- `write_mcp_config` / `remove_mcp_config` / `verify_mcp_configs` routed through opencode helpers.

**Tests:**
- `tests/test_mcp_config_merge.py` — v1 roundtrip, v2 roundtrip, fresh-file v2
- `tests/test_stop_all_tools.py` — v2 neighbor preservation on disconnect

**MCP merge experiment:** `python tests/_e2e_mcp_merge_experiment.py` → **13/13 passed** (all tools including opencode).

---

### 4. Multi-repo / moved folders (`hw_track`)

Registry stores `fs_id` (dev + inode on Darwin). Wipe and connect fan-out use `resolve_moved_path()` to find repos after rename/move when stale paths remain in `registry.json`.

**Integration tests (new):** `tests/test_managed_repos_hw_track.py`
- Fan-out finds hw-moved checkout via `fs_id`
- `_registered_repo_roots()` includes hw-moved path for wipe

---

### 5. Darwin `F_GETPATH` fix

**Symptom:** `resolve_moved_path()` always returned `None` on macOS; hw_track tests skipped or failed.

**Cause:** Raw `ctypes` `fcntl(fd, F_GETPATH, create_string_buffer(...))` returns -1 on Darwin. Python's **`fcntl` module** requires a **bytes buffer**:

```python
fcntl.fcntl(fd, fcntl.F_GETPATH, b"\x00" * 1024)
```

**Fix (`packages/pipeline/hw_track.py`):** Added `_darwin_getpath()` using the fcntl module; parse NUL-terminated path from returned bytes.

**Tests (all pass on this Mac):**
```
tests/test_hw_track.py::test_hardware_tracking_capture_and_resolve
tests/test_hw_track.py::test_hardware_tracking_shutil_move
tests/test_managed_repos_hw_track.py::test_fan_out_finds_hw_moved_checkout
tests/test_managed_repos_hw_track.py::test_wipe_registry_collects_hw_moved_path
```

---

### 6. Other fixes from session

| Fix | File |
|-----|------|
| Codex connect on Python 3.10 (`tomli` missing) | `pyproject.toml`, `rules_installer._loads_toml()` |
| Combination test JSON crash (bytes/Path) | `scripts/run_cli_combination_tests.py` |
| Windows-only `uv_tool_root` tests on Mac | `tests/test_process_control.py` (`skipif`) |
| Lazy TOML validation when `tomli` absent | `tests/_e2e_mcp_merge_experiment.py` |

---

## Pytest summary (focused runs)

```bash
uv run python -m pytest \
  tests/test_mcp_config_merge.py \
  tests/test_stop_all_tools.py \
  tests/test_hw_track.py \
  tests/test_managed_repos_hw_track.py \
  tests/test_wipe.py::test_wipe_all_keep_package_preserves_tool_shims \
  -q
# 33 passed (hw_track + managed_repos integration)
```

---

## How to verify on another Mac

```bash
git pull upstream main
uv tool install --force .
export PATH="$HOME/.local/bin:$PATH"

# Lifecycle E2E (~6–35 min depending on indexing)
bash tests/_e2e_run_cmds.sh

# MCP merge (13 tools, ~7s)
uv run python tests/_e2e_mcp_merge_experiment.py

# Unit/integration
uv run python -m pytest tests/test_hw_track.py tests/test_managed_repos_hw_track.py -v
```

---

## Files changed (this commit)

| Area | Files |
|------|-------|
| Wipe keep-package | `packages/pipeline/wipe.py`, `tests/test_wipe.py` |
| OpenCode v2 | `packages/pipeline/rules_installer.py`, `tests/test_mcp_config_merge.py`, `tests/test_stop_all_tools.py` |
| Darwin F_GETPATH | `packages/pipeline/hw_track.py`, `tests/test_hw_track.py` |
| Moved-folder integration | `tests/test_managed_repos_hw_track.py` |
| E2E script | `tests/_e2e_run_cmds.sh` |
| Deps / misc | `pyproject.toml`, `uv.lock`, `scripts/run_cli_combination_tests.py`, `tests/test_process_control.py`, `tests/_e2e_mcp_merge_experiment.py` |

---

## Known follow-ups

- **PyPI:** Fixes are in repo; not bumped/published unless requested.
- **E2E G16b exit code:** May be `1` when audit reports unrelated leftovers (`ok: false`) even though wipe succeeded and CLI survived.
- **Cursor `${workspaceFolder}`:** Global token may not expand; project `.cursor/mcp.json` absolute pin is the fix (0.3.83+).

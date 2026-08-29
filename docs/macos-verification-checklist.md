# macOS Testing & Verification Checklist (Scubiee 0.2.98+)

This document logs all cross-platform features and macOS-specific subsystems that must be verified when running on macOS / Darwin environments (Apple Silicon M1/M2/M3/M4 & Intel).

---

## 1. Hardware-Level Filesystem Tracking (`volfs` & `fcntl(F_GETPATH)`)
- **Module**: `packages/pipeline/hw_track.py`
- **Mechanism**:
  - `get_filesystem_id(path)` captures `(st_dev, st_ino)` via POSIX `stat()`.
  - `resolve_moved_path(fs_id)` opens `/.vol/{dev}/{ino}` and executes `fcntl(fd, F_GETPATH)` to translate the Inode back to the moved directory path in `< 0.2ms` with zero disk traversal.
- **Verification Target**:
  - Move/rename an enrolled repo directory to a different folder.
  - Run `resolve_moved_path` and verify it discovers the new path immediately.
  - Verify `scubiee wipe --all --confirm` cleans the moved repository's `.scubiee/` without scanning the hard drive.

---

## 2. Hardware Acceleration & Embeddings (MLX & CoreML & FastEmbed)
- **Module**: `packages/pipeline/accel.py`, `packages/pipeline/mlx_mac.py`
- **Mechanism**:
  - Apple Silicon (`arm64`): Native MLX embedding backend with FP16 weights (`mlx>=0.22`).
  - Intel Mac (`x86_64`): FastEmbed + ONNX Runtime CoreML / CPU EP.
- **Verification Target**:
  - Run `scubiee setup` on Apple Silicon: confirms MLX profile detection and speed calibration.
  - Run `scubiee setup` on Intel Mac: confirms CoreML / CPU fallback.

---

## 3. Strict MCP Workspace Isolation (`_is_repo_managed()`)
- **Module**: `packages/pipeline/mcp_locate.py`
- **Mechanism**:
  - `GATE 0` (unmanaged) returned when a workspace has no registered entry in `~/.scubiee/registry.json`.
  - MCP tools reject unmanaged repository calls with `requires_initialize` / `unmanaged`.
- **Verification Target**:
  - Run MCP tests against both enrolled and unenrolled repositories on macOS.
  - Confirm IDE tools (Cursor, Claude Code, Windsurf) receive `GATE 0` and stay on native tools when unmanaged.

---

## 4. Multi-Tool Connect & Disconnect on macOS
- **Module**: `packages/pipeline/tool_registry.py`, `packages/pipeline/rules_installer.py`
- **Target Paths**:
  - Cursor: `~/Library/Application Support/Cursor/User/globalStorage/state.vscdb`, `~/.cursor/mcp.json`
  - VS Code: `~/Library/Application Support/Code/User/globalStorage/state.vscdb`
  - Claude Code: `~/.claude/mcp.json`, `~/.claude/skills`
  - Windsurf: `~/.codeium/windsurf/mcp_config.json`
- **Verification Target**:
  - Run `scubiee connect <tool>` and verify correct configuration written without polluting repo folders.
  - Run `scubiee disconnect <tool>` and verify clean removal.

---

## 5. Comprehensive Wipe & File Cleanup
- **Module**: `packages/pipeline/wipe.py`
- **Verification Target**:
  - `scubiee wipe --all --confirm` removes:
    1. Global state (`~/.scubiee`)
    2. Model weights and caches (`~/.cache/huggingface`, `~/.scubiee/mlx`)
    3. In-repo `.scubiee` folders for all active and moved repositories (via `fs_id` hardware resolution)
    4. Tool MCP entries across Cursor, Claude Code, Windsurf, etc.
    5. Tool executable shim (`uv tool uninstall scubiee`)

---

## 6. How to Run macOS Tests
Run the production test suite on macOS:
```bash
uv tool install --editable ".[macos]"
python tests/mac_production_test.py
```
Or with pytest:
```bash
pytest -v tests/test_hw_track.py tests/test_mcp_locate.py tests/mac_production_test.py
```

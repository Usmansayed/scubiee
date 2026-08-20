# Cross-Platform Bug Analysis — scubiee 0.2.20

**Date:** 2026-08-20  
**Scope:** Code review of all OS/hardware-conditional paths  
**Platforms:** macOS ARM64 (tested), Windows AMD DirectML (tested), Windows NVIDIA CUDA (untested), Linux CUDA (untested)

---

## Confirmed Bugs (from code review)

### Bug 17 — MEDIUM: `os.killpg()` on Windows would crash

**File:** `packages/pipeline/daemon.py` line 357

**Code:**
```python
os.killpg(pid, signal.SIGKILL)
```

**Problem:** `os.killpg` does not exist on Windows. This line is inside the `else` branch of `if os.name == "nt"`, so it only runs on Unix. However, `signal.SIGKILL` is also undefined on Windows. The code is currently safe because the Windows path uses `taskkill`, but if the logic ever changes, this is fragile.

**Risk:** LOW (currently guarded by the `os.name == "nt"` branch). No action needed.

---

### Bug 18 — MEDIUM: `mlx_mac.py` imports `resource` unconditionally

**File:** `packages/pipeline/mlx_mac.py` line 147

**Code:**
```python
def _rss_bytes() -> dict[str, int]:
    import resource  # Unix-only!
```

**Problem:** If any code path on Windows somehow imports `mlx_mac.py` (e.g., via a stale import or wrong profile), it will crash with `ModuleNotFoundError: No module named 'resource'`.

**Current protection:** MLX is only used on Apple Silicon (guarded by `profile == "mlx"` and `_is_apple_silicon()`). But if a Windows user manually sets `--profile mlx` or `CTX_EMBED_BACKEND=mlx`, this crashes.

**Fix needed:** Add a guard: `if sys.platform != "win32": import resource` or use psutil only.

---

### Bug 19 — HIGH: CUDA profile on Linux without CUDA toolkit → silent CPU embedding

**Scenario:** Linux user has NVIDIA GPU (nvidia-smi works), installs scubiee, runs `ctx setup`. Profile is set to `cuda`. `onnxruntime-gpu` is installed. But CUDA toolkit libs aren't in LD_LIBRARY_PATH.

**What happens:** 
1. `ctx setup` → detects NVIDIA → profile=cuda → installs onnxruntime-gpu ✓
2. `ctx init` → loads FastEmbed → ORT session creation fails silently → falls back to CPU
3. User sees "Ready" but embeddings run at 1/10th speed on CPU
4. No warning printed (FastEmbed catches ORT errors internally)

**Our fix (this session):** Added `_refuse_cuda_cpu_fallback()` which checks providers after install. But this only runs during `ctx setup`, not during `ctx init` or daemon warm-up.

**Remaining gap:** If the user installs correctly but LD_LIBRARY_PATH changes (new shell session, cron, systemd service), the daemon warm-up will silently embed on CPU.

**Fix needed:** Check providers at daemon startup (in `run_server` or `ce_service._warm_registered`), not just at setup time.

---

### Bug 20 — MEDIUM: Windows file locking with `msvcrt.locking` uses 1-byte lock

**File:** `packages/pipeline/project_id.py` lines 52, 67

**Code:**
```python
msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # locks 1 byte
```

**Problem:** On Windows, `msvcrt.locking` locks a range of bytes. We lock just 1 byte at position 0. If two processes open the file and one seeks past byte 0 before locking, the lock doesn't protect them. Unix `flock` locks the entire file descriptor regardless of position.

**Impact:** Potential registry corruption under high concurrency on Windows. Low risk in practice (single-user product), but a correctness issue.

**Fix:** Lock a larger range (e.g., 1024 bytes) or use `win32file.LockFileEx` for whole-file locking.

---

### Bug 21 — MEDIUM: Dashboard port lock uses same 1-byte pattern

**File:** `packages/pipeline/dashboard_port.py` lines 102, 115

Same issue as Bug 20 but for the dashboard port allocation lock.

---

### Bug 22 — LOW: `_is_too_broad()` uses hardcoded Unix paths on Windows

**File:** `packages/pipeline/repo_lifecycle.py`

**Code:**
```python
_BROAD = {
    str(home / "Desktop"),
    str(home / "Documents"),
    str(home / "Downloads"),
    "/tmp", "/var", "/usr", "/etc", "/opt",
}
```

**Problem:** On Windows, paths like `/tmp` don't exist. The check works (these paths won't match Windows paths), but it's incomplete — doesn't block `C:\Users`, `C:\Windows`, `C:\Program Files`.

**Fix:** Add Windows broad paths: `C:\Users\{user}`, `C:\`, `C:\Windows`, `C:\Program Files`.

---

### Bug 23 — MEDIUM: Daemon spawn on Linux doesn't daemonize properly

**File:** `packages/pipeline/daemon.py` line ~274

On macOS/Linux, the daemon is spawned with `subprocess.Popen(..., stdin=DEVNULL)` but without `setsid` or double-fork. This means:
- If the parent terminal closes, the daemon may receive SIGHUP
- The daemon's process group is tied to the spawning shell

On macOS this is mitigated by the LaunchAgent supervisor. On Linux there's no equivalent — the daemon could die when the user closes their terminal.

**Fix:** Add `start_new_session=True` to the Popen call on Linux, or use `os.setsid` in `preexec_fn`.

---

### Bug 24 — HIGH: No Linux systemd/service integration

**Problem:** On macOS, `ctx setup` registers a LaunchAgent for auto-start. On Windows, it registers a logon supervisor task. On Linux: **nothing**. The daemon doesn't auto-start after reboot, and there's no watchdog equivalent.

**Impact:** Linux CUDA users must manually start the daemon every session.

**Fix:** Generate a systemd user service file (`~/.config/systemd/user/context-engine.service`) during `ctx setup` on Linux.

---

### Bug 25 — MEDIUM: Windows path normalization inconsistency

Multiple places compare paths using string comparison after `resolve()`. On Windows, paths can be `C:\Users\...` or `c:\users\...` (case-insensitive filesystem). `Path.resolve()` normalizes case on Windows, but `str(path)` comparisons elsewhere may not.

**Files:** `project_id.py` (`_norm_path`), `repo_lifecycle.py`, `git_family.py`

**Risk:** Registry may have duplicate entries for the same path with different casing.

---

### Bug 26 — LOW: MCP Python interpreter path on Windows with spaces

**File:** `packages/pipeline/mcp_install.py`

The MCP json uses the Python interpreter path as the `command`. On Windows, paths like `C:\Program Files\Python312\python.exe` have spaces. The MCP json format handles this correctly (it's an array), but if any shell-based launch path is used, spaces break the command.

**Current status:** The code uses `["python_path", "-u", "-m", ...]` format which handles spaces. Low risk.

---

## Platform Matrix — What's Tested vs What's Not

| Feature | macOS ARM64 | Win AMD/DML | Win NVIDIA/CUDA | Linux CUDA |
|---------|:-----------:|:-----------:|:---------------:|:----------:|
| `ctx setup` | ✓ Tested | ✓ Tested | ⚠️ Untested | ⚠️ Untested |
| `ctx init` (indexing) | ✓ Tested | ✓ Tested | ⚠️ Untested | ⚠️ Untested |
| Daemon lifecycle | ✓ Tested | ✓ Tested | ⚠️ Untested | ❌ No auto-start |
| MCP stdio | ✓ Tested | ✓ Tested | Probably OK | Probably OK |
| GPU embedding | ✓ MLX FP16 | ✓ DML | ⚠️ Silent CPU? | ⚠️ Silent CPU? |
| ORT wheel swap | ✓ N/A | ✓ Fixed 0.2.16 | ⚠️ Untested | ⚠️ Untested |
| File locking | ✓ flock | ⚠️ 1-byte lock | ⚠️ 1-byte lock | ✓ flock |
| Daemon auto-start | ✓ LaunchAgent | ✓ Logon task | ✓ Logon task | ❌ Missing |
| Process daemonize | ✓ OK | ✓ CREATE_NO_WINDOW | ✓ Same | ⚠️ No setsid |
| Path handling | ✓ | ⚠️ Case sensitivity | ⚠️ Case sensitivity | ✓ |

---

## Priority Fixes for CUDA Production

1. **Check CUDAExecutionProvider at daemon warm-up** (not just setup) — prevents silent CPU
2. **Linux systemd service generation** in `ctx setup` — auto-start + watchdog
3. **Linux daemon: `start_new_session=True`** — survives terminal close
4. **Windows broad-path guard** — refuse `C:\Users`, `C:\`
5. **Provider verification in FastEmbed model load** — loud failure vs silent CPU

---

## The macOS SIGSEGV Issue (separate from platform bugs)

The recurring crash is specific to **macOS ARM64 + tokenizers (Rust/Rayon) + CPython 3.12**. This is likely an upstream bug in the `tokenizers` library's interaction with CPython's memory allocator on Apple Silicon. The `gc.disable()` fix reduces frequency but doesn't eliminate it because the corruption happens in Rayon's thread pool, not in Python's GC.

**Long-term fix options:**
1. Pin `tokenizers` to a known-good version (test older versions)
2. Isolate tokenizers to a subprocess (embed in daemon only, never in MCP stdio)
3. Use `TOKENIZERS_PARALLELISM=false` to disable Rayon threading
4. Switch to a pure-Python tokenizer for the MCP process

**Immediate mitigation:** Set `TOKENIZERS_PARALLELISM=false` in the MCP process environment to disable Rayon worker threads. This may prevent the memory corruption at the cost of slightly slower tokenization.

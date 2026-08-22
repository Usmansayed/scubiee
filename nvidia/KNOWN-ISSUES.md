# Known Issues & Fixes — NVIDIA Windows

Issues discovered during testing and their resolutions in scubiee 0.2.25.

## Issue 1: `ctx init` crashes with NameError

**Symptom:**
```
NameError: name 'os' is not defined
```

**Root Cause:** `packages/pipeline/repo_lifecycle.py` used `os.environ` without importing `os`.

**Fix:** Added `import os` to module-level imports. Fixed in 0.2.25.

---

## Issue 2: CUDA reports healthy but runs on CPU

**Symptom:**
- `ctx setup` shows `profile=cuda` and `device=cuda`
- But calibration shows only 2-3 t/s (CPU speeds)
- ORT warning: "Failed to create CUDAExecutionProvider"
- Error about `cublasLt64_13.dll` missing

**Root Cause:** ONNX Runtime's `get_available_providers()` lists CUDAExecutionProvider
even when the DLLs required for session creation are missing. The old validation only
checked the provider list, not actual session creation.

**Fix (0.2.25):**
1. Added `_ensure_cuda_dll_paths()` that auto-discovers DLLs from:
   - `onnxruntime/capi/` directory (pip wheel)
   - `$CONDA_PREFIX/Library/bin/` (conda environment)
   - `CUDA_PATH/bin/` (system CUDA toolkit)
   - Registers them via `os.add_dll_directory()` + PATH prepend
2. Changed `_refuse_cuda_cpu_fallback()` to actually probe session creation:
   - Creates a real InferenceSession with CUDA provider
   - Checks if CUDA is in the active session providers
   - Only reports "cuda" if inference actually works
3. If probe fails: clearly reports CPU fallback with actionable fix hint

**If still failing after 0.2.25:**
The CUDA toolkit version must match the onnxruntime-gpu wheel:
- ORT 1.19+ needs CUDA 13 + cuDNN 9
- For CUDA 12.x systems: use the CUDA-12 specific wheel (see README.md Test 3)

---

## Issue 3: `ctx diagnose` shows test failures

**Symptom:**
```
Tests: FAIL
tests/test_source_integrity.py - FileNotFoundError
```

**Root Cause:** `ctx diagnose` tried to run pytest against relative test paths
(`tests/test_*.py`) which only exist in the source repository checkout, not in
a pip-installed package.

**Fix (0.2.25):** The test runner now checks if `tests/` directory exists before
attempting to run. When installed as a package, it gracefully reports:
```json
{"ok": true, "skipped": true, "reason": "test suite not available (installed package, not source checkout)"}
```

---

## Issue 4: `loguru` ModuleNotFoundError on fresh Windows install

**Symptom:**
```
ModuleNotFoundError: No module named 'loguru'
```

**Root Cause:** The MCP SDK (`mcp>=1.0`) depends on `loguru` but on some Windows
pip environments, transitive dependencies weren't resolved correctly.

**Fix (0.2.24+):** Added `loguru>=0.7` as an explicit dependency in pyproject.toml.

---

## Issue 5: ORT DLL path not found in conda environments

**Symptom:**
- CUDA toolkit is installed inside the conda env
- `nvidia-smi` works
- But ORT can't find `cublasLt64_xx.dll`

**Root Cause:** Conda installs CUDA libraries in `%CONDA_PREFIX%\Library\bin\` which
is not on the Windows DLL search path by default.

**Fix (0.2.25):** `_ensure_cuda_dll_paths()` now explicitly checks and registers
`%CONDA_PREFIX%\Library\bin\` via `os.add_dll_directory()` before ORT is imported.

**Manual workaround if still needed:**
```powershell
$env:PATH = "$env:CONDA_PREFIX\Library\bin;" + $env:PATH
ctx setup --repair
```

---

## Version History

| Version | Fixes |
|---------|-------|
| 0.2.24 | Added loguru as explicit dependency |
| 0.2.25 | Fixed all 4 issues above: os import, CUDA DLL discovery, session probe, diagnose paths |

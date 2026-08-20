# NVIDIA Windows Laptop — Scubiee Validation Guide

This document tells you exactly what to test on the NVIDIA-powered Windows laptop,
why each test matters, how to run it, and how to fix any issues found.

## Prerequisites

```powershell
pip install -U scubiee==0.2.25
```

---

## Test Plan

Run these commands **in order**. Each one validates a different layer of the stack.

### Test 1: Basic Installation Health

**Why:** Confirms scubiee installed correctly, all dependencies resolved (loguru, pydantic, mcp, faiss, tree-sitter etc.), and the CLI is reachable.

**How:**
```powershell
ctx --version
ctx preflight
```

**Expected:**
- Version shows `scubiee 0.2.25`
- Preflight reports `"ok": true` with all required capabilities available

**If it fails:**
- Missing module errors → `pip install -U scubiee==0.2.25` (force reinstall)
- If `faiss` fails: `pip install faiss-cpu`
- If `tree-sitter` fails: `pip install tree-sitter>=0.23`

---

### Test 2: Hardware Detection

**Why:** Confirms Scubiee sees the NVIDIA GPU and recommends the correct acceleration profile.

**How:**
```powershell
ctx resources
```

**Expected output should contain:**
- `"recommended_accel"` with `"profile": "cuda"`
- CPU count, RAM total visible
- No errors

**If it fails:**
- If GPU not detected: check `nvidia-smi` works from PowerShell
- If nvidia-smi not found: add NVIDIA driver path to system PATH

---

### Test 3: GPU Setup & CUDA Validation

**Why:** This is the critical test. It installs onnxruntime-gpu, discovers CUDA DLLs,
verifies the CUDA provider actually works (not just listed), calibrates batch size,
and saves the acceleration profile.

**How:**
```powershell
ctx setup --repair
```

**Expected:**
- Progress bar completes to 100%
- Profile reports `profile=cuda` (not `cpu`)
- Calibration shows > 10 t/s (texts per second)
- No "CUDAExecutionProvider" errors or DLL missing warnings

**If CUDA falls back to CPU (2-3 t/s):**

This means CUDA DLLs aren't loading. The fix depends on your CUDA toolkit version:

```powershell
# Check your CUDA version
nvidia-smi
```

Look at the "CUDA Version" in the top right of nvidia-smi output.

**If CUDA Version is 12.x:**
```powershell
pip uninstall onnxruntime-gpu onnxruntime -y
pip install onnxruntime-gpu --extra-index-url https://aiinfra.pkgs.visualstudio.com/PublicPackages/_packaging/onnxruntime-cuda-12/pypi/simple/
ctx setup --repair
```

**If CUDA Version is 11.x:**
```powershell
pip uninstall onnxruntime-gpu onnxruntime -y
pip install onnxruntime-gpu==1.17.0
ctx setup --repair
```

**If still failing after correct ORT version:**
```powershell
# Ensure CUDA Toolkit bin is on PATH
$env:PATH = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.x\bin;" + $env:PATH
# Or for conda environments:
$env:PATH = "$env:CONDA_PREFIX\Library\bin;" + $env:PATH
ctx setup --repair
```

---

### Test 4: Repository Initialization

**Why:** Tests that `ctx init` works without crashing (the `import os` bug fix).

**How:**
```powershell
# Create a test repo
mkdir C:\temp\test-repo
cd C:\temp\test-repo
echo "def hello(): return 'world'" > app.py
ctx init .
```

**Expected:**
- No `NameError: name 'os' is not defined`
- Output shows `"ok": true` with a project_id
- Index completes with chunk count > 0

**If it fails:**
- `NameError` on `os` → you're on < 0.2.25, run `pip install -U scubiee==0.2.25`
- Permission errors → run PowerShell as Administrator or use a different directory

---

### Test 5: Full Diagnostic Report

**Why:** Generates the complete shareable diagnostic log with all tech stack info,
acceleration status, daemon health, and saves it as a JSON file with clickable URL.

**How:**
```powershell
ctx diagnose
```

**Expected:**
- Progress bar completes
- Summary shows:
  - Acceleration: `cuda` (or `cpu` if CUDA fix pending)
  - Capabilities: `pass`
  - Tests: `pass` (will show "skipped" since not in source repo — that's correct)
- Log file saved with clickable `file:///` URL
- Open the folder, share the JSON file

**If it shows "Tests: FAIL":**
- On 0.2.25 this should show "skipped" when run outside the source repo
- If it still fails, you're on an older version

---

### Test 6: Search & Index Validation

**Why:** End-to-end test that indexing produces searchable vectors.

**How:**
```powershell
cd C:\temp\test-repo
ctx index . --force
ctx search "hello function"
```

**Expected:**
- Index completes with chunks > 0
- Search returns results mentioning `app.py`
- If CUDA is working: index should complete in seconds (not minutes)

---

### Test 7: Daemon & MCP Connectivity

**Why:** Validates the background engine daemon starts and Kiro/Cursor can connect to it.

**How:**
```powershell
ctx engine ensure .
ctx status
```

**Expected:**
- Daemon starts on `127.0.0.1:8765`
- Status shows `"sync_state": "ready"`
- No bind errors

**If port is busy:**
```powershell
ctx engine stop
ctx engine start .
```

---

### Test 8: Live Sync (Incremental Indexing)

**Why:** Validates that file changes are picked up automatically without re-indexing.

**How:**
```powershell
# With daemon running:
echo "def new_func(): pass" >> app.py
# Wait 3-5 seconds
ctx status
```

**Expected:**
- Status eventually shows `"sync_state": "ready"` (after brief "syncing")
- Search for "new_func" returns the new function

---

## Summary Checklist

| # | Test | Command | Pass Criteria |
|---|------|---------|--------------|
| 1 | Install | `ctx preflight` | `"ok": true` |
| 2 | Hardware | `ctx resources` | NVIDIA GPU detected |
| 3 | CUDA | `ctx setup --repair` | profile=cuda, >10 t/s |
| 4 | Init | `ctx init .` | No crash, project created |
| 5 | Diagnose | `ctx diagnose` | Capabilities pass, log saved |
| 6 | Index | `ctx index . --force` | Chunks indexed, search works |
| 7 | Daemon | `ctx engine ensure .` | Daemon healthy on :8765 |
| 8 | Live Sync | Edit file, wait, search | Changes reflected |

---

## Quick Fix Reference

| Symptom | Fix |
|---------|-----|
| `ModuleNotFoundError: loguru` | `pip install -U scubiee==0.2.25` |
| `NameError: os` on ctx init | `pip install -U scubiee==0.2.25` |
| CUDA falls back to CPU | See Test 3 fix steps above |
| `cublasLt64_13.dll` missing | Install matching CUDA ORT (see Test 3) |
| ctx diagnose shows test failures | Update to 0.2.25 (tests skipped outside source) |
| Profile shows cuda but runs on CPU | `ctx setup --repair` (0.2.25 validates properly) |
| Daemon won't start | `ctx engine stop` then `ctx engine start .` |

---

## After All Tests Pass

Once everything is green, open Kiro in this directory and the Context Engine
MCP will automatically connect to the running daemon. Kiro will have full
semantic code search, graph navigation, and live incremental indexing.

```powershell
# Final state should be:
ctx diagnose   # All pass, cuda acceleration, daemon running
# Then open Kiro/Cursor in the project directory
```

Share the `ctx diagnose` JSON log file if any issues remain.

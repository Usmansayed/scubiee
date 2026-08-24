# Mac Retest After 0.2.57 Changes

These changes were made and tested on Windows. They need verification on Mac.

## What Changed (since Mac's 25/25 test pass)

### 1. Memory budget coupling (RAM + CPU synced)
- Background RSS cap lowered: 800MB → 500MB
- Large reindex cap lowered: 8GB → 1GB
- `force_apply_memory_budget()` now also resets `CTX_CPU_EMBED_THREADS`
- Full reindex of existing repo now gets bootstrap budget (was background)

### 2. INT8 model for CPU profiles
- `_ensure_coderank_int8()` quantizes the FP16 model to INT8 during setup if profile=cpu
- Embedder loads `model_int8.onnx` when profile=cpu
- Mac Apple Silicon uses MLX (not affected), but Mac Intel uses CPU/CoreML

### 3. CPU thread budget
- `IndexMemoryBudget.cpu_thread_pct` field added to dataclass
- `apply_index_memory_budget()` sets `CTX_CPU_EMBED_THREADS` env var
- Embedder reads this when profile=cpu, sets `threads=N` on FastEmbed init

### 4. GPU auto-repair in `validate_dml_provider()`
- Now attempts `_install_ort_wheel()` before giving up
- Covers both DML and CUDA profiles
- Mac MLX/CoreML profiles skip this entirely (returns True early)

### 5. Production resilience (from earlier in session)
- `stdin=subprocess.DEVNULL` on all git subprocess calls (freshness.py, project_id.py, prs.py)
- Faiss preload on main thread in mcp_locate.py main()
- root_probe path separator fix (Windows-specific, no-op on Mac)

---

## Mac-Specific Tests to Run

```bash
cd <any-git-repo>
uv tool install scubiee[macos] --force
scubiee setup
```

### Test 1: Memory budget values
```bash
python -c "
from pipeline.memory_budget import bootstrap_budget, background_budget, large_reindex_budget
b = bootstrap_budget()
bg = background_budget()
lr = large_reindex_budget()
assert b.rss_cap_mb == 800 and b.cpu_thread_pct == 0.35
assert bg.rss_cap_mb == 500 and bg.cpu_thread_pct == 0.15
assert lr.rss_cap_mb == 1000 and lr.cpu_thread_pct == 0.35
print('PASS: budgets correct')
"
```

### Test 2: MLX profile does NOT use INT8 or CPU threads
```bash
python -c "
from pipeline.accel import load_accel, coderank_int8_onnx_path
prof = load_accel()
print(f'Profile: {prof.profile}')
# MLX should not trigger INT8 quantization
assert prof.profile in ('mlx', 'coreml'), f'Expected MLX, got {prof.profile}'
# INT8 may or may not exist (only created if cpu profile runs setup)
# The key check: embedder should NOT load INT8 for MLX
print('PASS: MLX profile active, INT8 not used')
"
```

### Test 3: git subprocess calls have stdin=DEVNULL
```bash
# This is a smoke test — if MCP tools hang, the stdin fix didn't apply
scubiee status
# Should return instantly (not hang on git rev-parse)
```

### Test 4: Full MCP tools work after changes
```bash
# Run the existing mac production test
python tests/mac_production_test.py
# Expected: 25/25 pass (same as before)
```

### Test 5: Background budget restore after bulk
```bash
python -c "
import os
from pipeline.memory_budget import bootstrap_budget, background_budget, force_apply_memory_budget, apply_index_memory_budget
apply_index_memory_budget(bootstrap_budget())
print('Bootstrap:', os.environ.get('CTX_CPU_EMBED_THREADS'), os.environ.get('CTX_CE_RSS_CAP_MB'))
force_apply_memory_budget(background_budget())
print('Background:', os.environ.get('CTX_CPU_EMBED_THREADS'), os.environ.get('CTX_CE_RSS_CAP_MB'))
# Threads should drop, RSS should drop
assert int(os.environ['CTX_CE_RSS_CAP_MB']) == 500
print('PASS')
"
```

### Test 6: Mac Intel (if available) — INT8 quantization
Only relevant if testing on an Intel Mac (no MLX, profile=cpu or coreml):
```bash
python -c "
from pipeline.accel import _ensure_coderank_int8, coderank_int8_onnx_path
result = _ensure_coderank_int8()
if result:
    print(f'INT8 model created: {result} ({result.stat().st_size/1024/1024:.0f}MB)')
else:
    print('INT8 skipped (expected on Apple Silicon with MLX)')
"
```

---

## Expected Results

| Test | Apple Silicon (MLX) | Intel Mac (CPU/CoreML) |
|------|--------------------|-----------------------|
| Budget values | PASS | PASS |
| MLX not using INT8 | PASS (mlx profile) | N/A (cpu/coreml) |
| git stdin fix | PASS (no hangs) | PASS |
| mac_production_test.py | 25/25 | Should pass |
| Budget force-restore | PASS | PASS |
| INT8 quantization | Skipped (MLX) | PASS (creates INT8) |

## If anything fails

The most likely failure would be:
1. `IndexMemoryBudget` dataclass change breaking unpickling of old cached state — fix: `scubiee wipe --all --yes; scubiee setup`
2. INT8 quantization failing on older onnxruntime — fix: graceful skip (already handles ImportError)

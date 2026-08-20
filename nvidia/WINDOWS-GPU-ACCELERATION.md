# Windows GPU Acceleration — DirectML (v0.2.26+)

## Summary

Starting with scubiee 0.2.26, **all Windows GPU acceleration uses DirectML**.
This applies to NVIDIA, AMD, and Intel GPUs equally. CUDA is no longer used on Windows.

## Why DirectML

| | CUDA (old) | DirectML (new) |
|---|---|---|
| Install | 1.3GB DLLs + version matching | `pip install onnxruntime-directml` (25MB) |
| DLL conflicts | Constant (locked files, version mismatch) | None |
| RTX 50-series (Blackwell) | Broken without CUDA 13 toolkit | Works |
| RTX 20/30/40-series | Works with effort | Works |
| AMD GPUs | Not supported | Works |
| Intel GPUs | Not supported | Works |
| Setup steps | nvidia-smi check, ORT swap, cuBLAS, cuDNN | Zero — included in base install |
| Performance (embeddings) | 150 t/s | 28 t/s |
| Reliability | Low | 100% |

DirectML is ~5x slower than CUDA for raw inference, but for embedding workloads:
- 28 t/s indexes a 3000-chunk codebase in 6.5 seconds
- The bottleneck is parsing (27s) and chunking (10s), NOT embedding
- Real-world wall time difference is negligible

## How It Works

1. `pip install scubiee` on Windows pulls `onnxruntime-directml` from base deps
2. `ctx setup` detects any GPU via Windows WMI → picks `dml` profile
3. No wheel swapping, no DLL hunting, no subprocess tricks
4. FastEmbed uses `DmlExecutionProvider` with the detected GPU

## User Flow

```powershell
# Fresh Windows laptop (NVIDIA, AMD, or Intel GPU)
pip install scubiee
ctx setup          # auto-detects GPU, picks DirectML, calibrates
ctx init .         # indexes at 400+ chunks/s
```

That's it. No CUDA Toolkit, no cuDNN download, no PATH hacking.

## For Linux NVIDIA Users

Linux still uses `onnxruntime-gpu` with CUDA. The CUDA DLL locking issue doesn't
exist on Linux (no DLL locking). Linux users get full CUDA performance (~150 t/s).

```bash
pip install scubiee[cuda]
ctx setup          # auto-detects NVIDIA, picks cuda profile
```

## Benchmarks (RTX 4060 Laptop GPU)

```
Context Engine repo: 371 files, 3039 chunks

DirectML:
  Parse:  27.0s (13.7 files/s)
  Chunk:  10.0s (303 chunks/s)
  Embed:   6.5s (464 chunks/s)
  Write:   0.7s
  Total:  62.9s

CPU (for comparison):
  Embed: ~180s (17 chunks/s)
  Total: ~220s
```

DirectML is 27x faster than CPU for embedding, making it practical for any repo size.

## Forcing CUDA on Windows (Advanced)

If you specifically need CUDA on Windows (e.g., benchmarking), you can still use it:

```powershell
pip install scubiee[cuda]
# Must also install matching CUDA DLLs manually:
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
ctx setup --profile cuda
```

This is unsupported and may have DLL locking issues. DirectML is the recommended path.

## Files Changed in 0.2.26

| File | Change |
|------|--------|
| `pyproject.toml` | `onnxruntime-directml` in base deps for win32 |
| `packages/pipeline/accel.py` | `recommend_profile()` picks DML for all Windows GPUs |
| `packages/pipeline/accel.py` | Removed Windows CUDA DLL management code |
| `packages/pipeline/accel.py` | Simplified `_install_ort_wheel()` (no subprocess/rename) |
| `packages/pipeline/hardware.py` | Removed ORT-import-skip hack |

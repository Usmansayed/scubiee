# CUDA DLL Resolution — RTX 4060 Laptop (August 2026)

## The Problem

After a clean install of scubiee 0.2.25 with `pip install -e ".[cuda]"`, the `ctx setup`
command completes but CUDA falls back to CPU at ~2.6 t/s instead of GPU speeds (>100 t/s).

The error in ORT logs:
```
Error loading "onnxruntime_providers_cuda.dll" which depends on "cublasLt64_13.dll"
which is missing. (Error 126)
Failed to create CUDAExecutionProvider. Require cuDNN 9.* and CUDA 13.*
```

## Root Cause Chain

1. **`pip install onnxruntime-gpu`** resolves to v1.29.0 (latest)
2. **ORT 1.29.0 requires CUDA 13 + cuDNN 9** (`cublasLt64_13.dll`)
3. **nvidia-smi reports "CUDA Version: 13.0"** — but this is the *driver capability*, not
   an installed toolkit. The driver can run CUDA 13 code, but the cuBLAS/cuDNN runtime DLLs
   aren't installed.
4. **The system has CUDA Toolkit 12.3** installed at `C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.3\`
   which provides `cublasLt64_12.dll` (CUDA 12 version)
5. **Mismatch**: ORT 1.29.0 wants `cublasLt64_13.dll`, system only has `cublasLt64_12.dll`

## The Fix (3 parts)

### Part 1: Pin ORT to CUDA-12 compatible version

```python
# In ort_packages_for("cuda"):
"onnxruntime-gpu>=1.17,<1.20"   # 1.19.x supports CUDA 12 + cuDNN 9
```

ORT 1.19.2 is the latest version that works with CUDA 12. ORT 1.20+ started requiring
CUDA 13 cuBLAS libraries.

### Part 2: Install CUDA runtime DLLs via pip

The NVIDIA pip packages bundle the required DLLs:
```powershell
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
```

This installs:
- `cublasLt64_12.dll` → `site-packages/nvidia/cublas/bin/`
- `cudnn64_9.dll` + friends → `site-packages/nvidia/cudnn/bin/`

Total: ~1.3GB (737MB cuDNN + 553MB cuBLAS)

### Part 3: Auto-discover DLL paths (code fix)

Updated `_ensure_cuda_dll_paths()` in `packages/pipeline/accel.py` to scan
`site-packages/nvidia/*/bin/` directories and register them via `os.add_dll_directory()`
before ORT is imported.

```python
# Check nvidia pip packages (nvidia-cublas-cu12, nvidia-cudnn-cu12)
site_packages = ort_dir.parent
nvidia_pkg_dir = site_packages / "nvidia"
if nvidia_pkg_dir.is_dir():
    for sub in ("cublas", "cudnn", "cuda_runtime", "cufft", "curand", "cusolver", "cusparse", "nccl"):
        bin_dir = nvidia_pkg_dir / sub / "bin"
        if bin_dir.is_dir():
            dll_dirs.append(bin_dir)
```

## Result

Before fix: 2.6 t/s (CPU fallback)
After fix: **146 t/s** (RTX 4060 GPU) — 56x speedup

## Why This Happens on Fresh Installs

The default `pip install onnxruntime-gpu` pulls the latest (1.29.0) which needs CUDA 13
cuBLAS. NVIDIA's driver reports CUDA 13.0 compatibility but that only means the GPU *can*
run CUDA 13 code — it doesn't mean the cuBLAS/cuDNN libraries are installed.

Most Windows machines with NVIDIA GPUs have:
- A recent driver (which reports CUDA 13.0 capability)
- Either no CUDA toolkit, or an older one (12.x)
- No cuDNN installed at all

The nvidia pip packages solve this portably — they bundle the exact DLLs needed.

## Timeline of Debugging Session

| Step | What we tried | Result |
|------|--------------|--------|
| 1 | `pip install -e ".[cuda]"` (ORT 1.29.0) | Installed but CUDA fails: missing cublasLt64_13 |
| 2 | Uninstall ORT, reinstall from CUDA-12 index | Same 1.29.0 wheel, still needs CUDA 13 |
| 3 | Downgrade to `onnxruntime-gpu==1.19.2` | CUDA still fails: missing cuDNN DLLs |
| 4 | Add CUDA 12.3 toolkit to PATH | Still fails: no cuDNN 9 on system |
| 5 | `pip install nvidia-cudnn-cu12 nvidia-cublas-cu12` | DLLs installed but not on PATH |
| 6 | Manually add nvidia DLL paths to PATH | **CUDA works! 153 t/s** |
| 7 | Code fix in `_ensure_cuda_dll_paths()` | Auto-discovers DLLs, no manual PATH needed |
| 8 | Test without PATH hack | **146 t/s — fully automatic** |

## Machines This Affects

Any Windows machine with:
- NVIDIA GPU (GeForce/RTX)
- No CUDA Toolkit fully installed OR only CUDA 12.x toolkit
- No cuDNN manually installed
- Fresh pip install of onnxruntime-gpu

This is **the majority of NVIDIA Windows laptops** — gamers, developers, students.
The fix makes scubiee work on all of them without any manual CUDA setup.

## Installer Requirements for Universal Compatibility

To ensure `ctx setup` works on ANY NVIDIA Windows machine:

1. Pin `onnxruntime-gpu` to a CUDA 12-compatible version (1.19.x)
2. Auto-install `nvidia-cublas-cu12` + `nvidia-cudnn-cu12` when profile=cuda
3. Auto-discover DLLs from `site-packages/nvidia/*/bin/` (already done in code fix)
4. Probe CUDA session creation, not just provider listing
5. If probe fails, give clear error with exact fix command

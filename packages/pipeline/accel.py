"""Hardware acceleration probe + install profile for CodeRank FastEmbed.

Profiles (mutually exclusive ORT wheels, plus Mac MLX):
  - cuda    → onnxruntime-gpu
  - dml     → onnxruntime-directml  (Windows AMD/Intel/NVIDIA without CUDA stack)
  - mlx     → Apple Silicon Metal (FP16 CodeRank; default on Darwin arm64)
  - coreml  → onnxruntime  (Intel Mac / explicit --profile coreml)
  - cpu     → onnxruntime

Persists choice to ``~/.context-engine/accel.json``.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

CODERANK_MODEL = "nomic-ai/CodeRankEmbed"
CODERANK_HF_ONNX = "jamie8johnson/CodeRankEmbed-onnx"
TARGET_TPS = float(os.environ.get("CTX_TARGET_TPS", "10"))
ACCEL_PATH = Path.home() / ".context-engine" / "accel.json"
# Install-time batch candidates. Prefer 16 unless 20 clearly wins ROI.
BATCH_CANDIDATES = (8, 16, 20)
BATCH_PREFER = 16
# Promote 16 → 20 only when throughput gain is clearly worth it.
BATCH_PROMOTE_MIN_RATIO = float(os.environ.get("CTX_BATCH_PROMOTE_RATIO", "0.10"))
BATCH_PROMOTE_MIN_TPS = float(os.environ.get("CTX_BATCH_PROMOTE_TPS", "3.0"))
# Prefer 16 over 8 unless 8 is meaningfully faster (pathological 16 case).
BATCH_DOWNGRADE_MIN_RATIO = float(os.environ.get("CTX_BATCH_DOWNGRADE_RATIO", "0.15"))
BATCH_CALIBRATE_N = int(os.environ.get("CTX_BATCH_CALIBRATE_N", "64"))


@dataclass
class AccelProfile:
    profile: str  # cuda | dml | mlx | coreml | cpu
    provider: str  # CUDAExecutionProvider | DmlExecutionProvider | CoreMLExecutionProvider | CPUExecutionProvider
    device_id: int = 0
    batch_size: int = 16
    backend: str = "fastembed"
    model: str = CODERANK_MODEL
    model_source: str = CODERANK_HF_ONNX
    texts_per_sec: float | None = None
    meets_target: bool | None = None
    reason: str = ""
    detected: dict[str, Any] = field(default_factory=dict)
    installed_at: str = ""
    batch_calibration: dict[str, Any] = field(default_factory=dict)
    envelope: dict[str, Any] = field(default_factory=dict)
    hardware_fingerprint: str = ""
    cuda_fallback_hint: str = ""

    def _coreml_options(self) -> dict[str, str]:
        from pipeline.coreml_mac import coreml_provider_options

        detected = self.detected if isinstance(self.detected, dict) else {}
        units = detected.get("coreml_compute_units")
        return coreml_provider_options(
            compute_units=str(units) if units else None
        )

    def providers(self) -> list:
        if self.profile == "mlx" or self.backend == "mlx":
            raise RuntimeError("MLX backend does not use ONNX Runtime providers")
        if self.profile == "cuda":
            return [("CUDAExecutionProvider", {"device_id": self.device_id}), "CPUExecutionProvider"]
        if self.profile == "dml":
            return [("DmlExecutionProvider", {"device_id": self.device_id}), "CPUExecutionProvider"]
        if self.profile == "coreml":
            from pipeline.coreml_mac import coreml_providers

            return coreml_providers(self)
        return ["CPUExecutionProvider"]


def load_accel(path: Path | None = None) -> AccelProfile | None:
    p = path or ACCEL_PATH
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return AccelProfile(**{k: v for k, v in raw.items() if k in AccelProfile.__dataclass_fields__})
    except Exception:  # noqa: BLE001
        return None


def save_accel(profile: AccelProfile, path: Path | None = None) -> Path:
    p = path or ACCEL_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone

    profile.installed_at = datetime.now(timezone.utc).isoformat()
    p.write_text(json.dumps(asdict(profile), indent=2) + "\n", encoding="utf-8")
    return p


def _has_nvidia() -> bool:
    """Detect NVIDIA GPU via multiple methods (nvidia-smi, ORT, torch, /proc)."""
    # Method 1: nvidia-smi (most reliable on both Windows and Linux)
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(
                ["nvidia-smi", "-L"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            if r.returncode == 0 and "GPU" in (r.stdout or ""):
                return True
        except Exception:  # noqa: BLE001
            pass

    # Method 2: Check if onnxruntime already has CUDA provider
    try:
        providers = ort_available_providers()
        if "CUDAExecutionProvider" in providers:
            return True
    except Exception:  # noqa: BLE001
        pass

    # Method 3: PyTorch (if installed)
    try:
        import torch

        if torch.cuda.is_available():
            return True
    except Exception:  # noqa: BLE001
        pass

    # Method 4: Linux /proc/driver/nvidia (driver loaded without toolkit in PATH)
    try:
        if Path("/proc/driver/nvidia/version").exists():
            return True
    except Exception:  # noqa: BLE001
        pass

    # Method 5: Windows — check WMI for NVIDIA adapters (nvidia-smi not in PATH)
    if platform.system() == "Windows":
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            if r.returncode == 0 and "nvidia" in (r.stdout or "").lower():
                return True
        except Exception:  # noqa: BLE001
            pass

    return False


def _is_apple_silicon(detected: dict[str, Any] | None = None) -> bool:
    d = detected or {}
    if d.get("apple_silicon"):
        return True
    os_name = str(d.get("os") or platform.system())
    machine = str(d.get("machine") or platform.machine()).lower()
    if os_name == "Darwin" and machine in {"arm64", "aarch64"}:
        return True
    names = " ".join(str(g.get("name") or "") for g in (d.get("gpus") or [])).lower()
    return os_name == "Darwin" and ("apple" in names or "m1" in names or "m2" in names or "m3" in names or "m4" in names or "m5" in names)


def _mlx_importable() -> bool:
    try:
        import mlx.core  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _env_disables_mlx() -> bool:
    raw = (os.environ.get("CTX_MLX") or os.environ.get("CTX_EMBED_BACKEND") or "").strip().lower()
    if raw in {"0", "false", "off", "no"}:
        return True
    return raw in {"fastembed", "cpu", "coreml", "st", "coderank", "sentence-transformers", "ollama"}


def _windows_d3d12_gpus() -> list[dict[str, Any]]:
    """Best-effort DXGI adapter list via PowerShell (no extra deps)."""
    if platform.system() != "Windows":
        return []
    ps = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name, AdapterRAM, DriverVersion | ConvertTo-Json -Compress"
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return []
        data = json.loads(r.stdout)
        if isinstance(data, dict):
            data = [data]
        out = []
        for row in data or []:
            name = str(row.get("Name") or "")
            ram = int(row.get("AdapterRAM") or 0)
            out.append({"name": name, "adapter_ram": ram, "driver": row.get("DriverVersion")})
        return out
    except Exception:  # noqa: BLE001
        return []


def detect_hardware() -> dict[str, Any]:
    gpus = _windows_d3d12_gpus()
    nvidia = _has_nvidia()
    # Prefer discrete-looking adapters for DML device_id (non-Microsoft Basic, larger RAM)
    dml_id = 0
    if gpus:
        scored = []
        for i, g in enumerate(gpus):
            name = g["name"].lower()
            score = g.get("adapter_ram") or 0
            if "microsoft" in name or "basic render" in name:
                score = -1
            if "radeon" in name or "geforce" in name or "rtx" in name or "arc" in name:
                score += 10**12
            scored.append((score, i, g))
        scored.sort(reverse=True)
        if scored and scored[0][0] >= 0:
            dml_id = scored[0][1]
    machine = platform.machine()
    apple_silicon = platform.system() == "Darwin" and machine.lower() in {"arm64", "aarch64"}
    if apple_silicon and not gpus:
        gpus = [{"name": "Apple Silicon GPU", "adapter_ram": 0, "backend": "metal"}]
    from pipeline.coreml_mac import requested_compute_units

    coreml_units = requested_compute_units()
    return {
        "os": platform.system(),
        "machine": machine,
        "python": sys.version.split()[0],
        "nvidia": nvidia,
        "gpus": gpus,
        "cpu_count": os.cpu_count() or 4,
        "suggested_dml_device_id": dml_id,
        "apple_silicon": apple_silicon,
        "coreml_compute_units": coreml_units if platform.system() == "Darwin" else None,
    }


def recommend_profile(detected: dict[str, Any] | None = None) -> AccelProfile:
    d = detected or detect_hardware()
    if d.get("nvidia"):
        return AccelProfile(
            profile="cuda",
            provider="CUDAExecutionProvider",
            device_id=0,
            batch_size=BATCH_PREFER,
            reason="NVIDIA GPU detected — use onnxruntime-gpu + FastEmbed",
            detected=d,
        )
    if d.get("os") == "Windows" and d.get("gpus"):
        # Any real adapter → DML (covers AMD/Intel/NVIDIA without CUDA toolkit)
        return AccelProfile(
            profile="dml",
            provider="DmlExecutionProvider",
            device_id=int(d.get("suggested_dml_device_id") or 0),
            batch_size=BATCH_PREFER,
            reason="Windows GPU via DirectML — use onnxruntime-directml + FastEmbed",
            detected=d,
        )
    if d.get("os") == "Darwin":
        apple_silicon = _is_apple_silicon(d)
        from pipeline.coreml_mac import requested_compute_units

        units = str(d.get("coreml_compute_units") or requested_compute_units())
        detected = {
            **d,
            "apple_silicon": apple_silicon,
            "coreml_compute_units": units,
        }
        if apple_silicon and not _env_disables_mlx():
            from pipeline.memory_budget import bootstrap_budget

            budget = bootstrap_budget()
            return AccelProfile(
                profile="mlx",
                provider="MLX",
                backend="mlx",
                device_id=0,
                batch_size=budget.mlx_batch,
                reason="Apple Silicon GPU via MLX FP16 — Metal, no CoreML/ORT for embed",
                detected=detected,
            )
        why = "macOS CoreML (Metal GPU"
        if apple_silicon or units == "ALL":
            why += " + Neural Engine"
        why += ") — onnxruntime CoreML EP + FastEmbed"
        return AccelProfile(
            profile="coreml",
            provider="CoreMLExecutionProvider",
            device_id=0,
            batch_size=BATCH_PREFER,
            reason=why,
            detected=detected,
        )
    return AccelProfile(
        profile="cpu",
        provider="CPUExecutionProvider",
        device_id=0,
        batch_size=BATCH_PREFER,
        reason="No usable GPU accelerator — FastEmbed CPU (multi-core)",
        detected=d,
    )


def ort_packages_for(profile: str) -> list[str]:
    if profile == "cuda":
        return ["onnxruntime-gpu>=1.17"]
    if profile == "dml":
        return ["onnxruntime-directml>=1.17"]
    if profile == "mlx":
        return ["onnxruntime>=1.17"]
    return ["onnxruntime>=1.17"]


def conflicting_ort_packages(profile: str) -> list[str]:
    """ORT wheels conflict — uninstall others before installing profile package."""
    all_ort = {"onnxruntime", "onnxruntime-gpu", "onnxruntime-directml"}
    keep = {
        "cuda": "onnxruntime-gpu",
        "dml": "onnxruntime-directml",
        "cpu": "onnxruntime",
        "coreml": "onnxruntime",
        "mlx": "onnxruntime",
    }[profile]
    return sorted(all_ort - {keep})


def _requirement_satisfied(spec: str) -> bool:
    """True if importlib.metadata reports a version matching the PEP 508 spec."""
    try:
        from packaging.requirements import Requirement
    except ImportError:
        name = spec.split(">", 1)[0].split("=", 1)[0].split("<", 1)[0].strip()
        try:
            importlib.metadata.version(name)
            return True
        except importlib.metadata.PackageNotFoundError:
            return False
    req = Requirement(spec)
    try:
        have = importlib.metadata.version(req.name)
    except importlib.metadata.PackageNotFoundError:
        return False
    if not req.specifier:
        return True
    return have in req.specifier


def _pip_fail_detail(out: str, rc: int) -> str:
    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    if not lines:
        return f"pip exited {rc}"
    return " | ".join(lines[-6:])


def _run_pip_captured(
    cmd: list[str],
    env: dict[str, str],
    *,
    on_tick: Callable[[], None] | None = None,
) -> tuple[int, str]:
    """Run pip and drain stdout.

    Windows deadlocks if we PIPE stdout and only ``poll()``: the OS pipe
    fills, pip blocks on write, we wait forever. Read in a thread.
    """
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    chunks: list[str] = []

    def drain() -> None:
        stdout = proc.stdout
        if stdout is None:
            return
        while True:
            block = stdout.read(4096)
            if not block:
                break
            chunks.append(block)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    while reader.is_alive() or proc.poll() is None:
        if on_tick is not None:
            on_tick()
        reader.join(timeout=0.2)
    reader.join(timeout=2.0)
    rc = proc.wait()
    return rc, "".join(chunks)


def pip_install(
    pkgs: list[str],
    *,
    upgrade: bool = False,
    progress: Any | None = None,
    start_pct: int = 0,
    end_pct: int = 0,
    phase: str = "Installing packages",
    force_reinstall: bool = False,
    no_deps: bool = False,
) -> None:
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--progress-bar",
        "off",
        "--disable-pip-version-check",
        "--no-input",
    ]
    if upgrade:
        cmd.append("-U")
    if force_reinstall:
        cmd.append("--force-reinstall")
    if no_deps:
        cmd.append("--no-deps")
    cmd.extend(pkgs)
    env = os.environ.copy()
    env["PIP_PROGRESS_BAR"] = "off"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INPUT"] = "1"
    if progress is not None:
        progress.set(start_pct, phase)
    else:
        print(f"[accel] {' '.join(cmd)}", file=sys.stderr, flush=True)
    until = max(start_pct, end_pct - 1) if end_pct else start_pct
    t0 = time.monotonic()

    def on_tick() -> None:
        if progress is None:
            return
        elapsed = int(time.monotonic() - t0)
        progress.pulse(f"{phase} ({elapsed}s)", until=until)

    rc, out = _run_pip_captured(cmd, env, on_tick=on_tick)
    if rc:
        last = _pip_fail_detail(out, rc)
        if progress is not None:
            progress.fail(f"{phase}: {last}")
        else:
            print((out or "").strip() or last, file=sys.stderr)
        raise subprocess.CalledProcessError(rc, cmd, output=out)
    if progress is not None and end_pct:
        progress.set(end_pct, phase)


def pip_uninstall(pkgs: list[str], *, progress: Any | None = None) -> None:
    cmd = [sys.executable, "-m", "pip", "uninstall", "-y", *pkgs]
    if progress is None:
        print(f"[accel] {' '.join(cmd)}", file=sys.stderr, flush=True)
    subprocess.run(
        cmd,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _purge_ort_modules() -> None:
    for name in list(sys.modules):
        if name == "onnxruntime" or name.startswith("onnxruntime."):
            del sys.modules[name]


def _ort_profile_ready(profile: str) -> bool:
    if profile == "mlx":
        return True
    providers = ort_available_providers()
    want = {
        "cuda": "CUDAExecutionProvider",
        "dml": "DmlExecutionProvider",
        "coreml": "CoreMLExecutionProvider",
        "cpu": "CPUExecutionProvider",
    }.get(profile)
    return bool(want and want in providers)


def _install_ort_wheel(profile: str, progress: Any | None = None) -> None:
    """Replace CPU/GPU/DML ORT wheels. They cannot coexist."""
    if profile == "mlx":
        return
    _purge_ort_modules()
    if _ort_profile_ready(profile):
        if progress is not None:
            progress.set(55, "GPU/CPU engine already installed")
        return
    all_ort = ["onnxruntime", "onnxruntime-gpu", "onnxruntime-directml"]
    pip_uninstall(all_ort, progress=progress)
    _purge_ort_modules()
    pip_install(
        ort_packages_for(profile),
        progress=progress,
        start_pct=32,
        end_pct=54,
        phase="Installing GPU/CPU engine",
        force_reinstall=True,
    )
    _purge_ort_modules()
    if _ort_profile_ready(profile):
        if progress is not None:
            progress.set(55, "GPU/CPU engine ready")
        return
    pip_install(
        ort_packages_for(profile),
        progress=progress,
        start_pct=54,
        end_pct=55,
        phase="Retrying GPU/CPU engine",
        force_reinstall=True,
        upgrade=True,
    )
    _purge_ort_modules()


def _align_profile_to_ort(profile: AccelProfile, progress: Any | None = None) -> None:
    """Do not warm FastEmbed on an EP this wheel does not provide."""
    if profile.profile in {"mlx", "cpu"}:
        return
    if _ort_profile_ready(profile.profile):
        return
    have = ort_available_providers()
    msg = (
        f"{profile.provider} is not in this onnxruntime wheel "
        f"(providers={have}). Using CPU. Close other Python/ctx processes "
        f"and re-run `ctx setup --repair` to retry GPU "
        f"({ort_packages_for(profile.profile)[0]})."
    )
    if progress is not None:
        progress.set(55, "GPU wheel missing — using CPU")
    else:
        print(f"[accel] {msg}", file=sys.stderr, flush=True)
    profile.profile = "cpu"
    profile.provider = "CPUExecutionProvider"
    profile.reason = msg


def install_profile_packages(profile: str, progress: Any | None = None) -> None:
    """Install FastEmbed + matching ORT wheel for profile (MLX on Apple Silicon)."""
    extras = ["fastembed>=0.4", "huggingface_hub>=0.20"]
    if profile in {"coreml", "mlx"}:
        extras.append("onnx>=1.16")
    if profile == "mlx":
        extras.append("mlx>=0.22")
    needed = [spec for spec in extras if not _requirement_satisfied(spec)]
    if needed:
        pip_install(
            needed,
            progress=progress,
            start_pct=18,
            end_pct=32,
            phase="Installing embedding runtime",
            # FastEmbed pulls CPU onnxruntime; GPU/DML wheel is installed next.
            no_deps=any(s.startswith("fastembed") for s in needed),
        )
    elif progress is not None:
        progress.set(32, "Embedding runtime already installed")
    _install_ort_wheel(profile, progress=progress)


def ort_available_providers() -> list[str]:
    try:
        import onnxruntime as ort  # type: ignore

        return list(ort.get_available_providers())
    except Exception:  # noqa: BLE001
        return []


def profile_packages_satisfied(profile: AccelProfile) -> bool:
    """True if saved accel matches target and the runtime already exposes it."""
    saved = load_accel()
    if saved is None or saved.profile != profile.profile:
        return False
    if profile.profile == "mlx" or profile.backend == "mlx":
        return _mlx_importable()
    providers = ort_available_providers()
    if not providers:
        return False
    want = profile.provider
    if want in providers:
        return True
    # CPU always ok if any ORT is importable
    if profile.profile == "cpu" and providers:
        return True
    return False


def _refuse_coreml_cpu_fallback(
    profile: AccelProfile, progress: Any | None = None
) -> None:
    """Hard-fail CoreML setup when the EP is missing instead of silent CPU."""
    if profile.profile != "coreml":
        return
    from pipeline.coreml_mac import mac_gpu_only

    available = ort_available_providers()
    if not available:
        return
    if "CoreMLExecutionProvider" in available:
        return
    msg = (
        "macOS GPU requested but CoreMLExecutionProvider is missing from this "
        f"onnxruntime wheel (providers={available})"
    )
    if mac_gpu_only():
        raise RuntimeError(msg + ". Refusing CPU fallback (CTX_MAC_GPU_ONLY=1).")
    if progress is None:
        print(f"[accel] {msg} — CPU fallback", file=sys.stderr, flush=True)
    else:
        progress.set(55, "CoreML unavailable — using CPU")
    profile.profile = "cpu"
    profile.provider = "CPUExecutionProvider"
    profile.reason = msg


def _refuse_cuda_cpu_fallback(
    profile: AccelProfile, progress: Any | None = None
) -> None:
    """Detect CUDA silent CPU fallback and warn/fix.

    After installing onnxruntime-gpu, verify CUDAExecutionProvider is actually
    available. If not (missing CUDA toolkit, wrong driver version, library path
    issues), warn clearly instead of silently running on CPU.
    """
    if profile.profile != "cuda":
        return
    available = ort_available_providers()
    if not available:
        return
    if "CUDAExecutionProvider" in available:
        return

    # CUDA EP missing — diagnose why
    hints: list[str] = []
    if platform.system() == "Linux":
        ld_path = os.environ.get("LD_LIBRARY_PATH", "")
        if "/usr/local/cuda" not in ld_path:
            hints.append(
                "LD_LIBRARY_PATH may need /usr/local/cuda/lib64. "
                "Try: export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH"
            )
        if not Path("/usr/local/cuda").exists():
            hints.append(
                "CUDA toolkit not found at /usr/local/cuda. "
                "Install from: https://developer.nvidia.com/cuda-downloads"
            )
    elif platform.system() == "Windows":
        cuda_path = os.environ.get("CUDA_PATH", "")
        if not cuda_path:
            hints.append(
                "CUDA_PATH environment variable not set. "
                "Install CUDA Toolkit from: https://developer.nvidia.com/cuda-downloads"
            )
        elif not Path(cuda_path).exists():
            hints.append(f"CUDA_PATH={cuda_path} does not exist.")

    hint_text = " ".join(hints) if hints else "Check CUDA toolkit installation."
    msg = (
        f"NVIDIA GPU detected but CUDAExecutionProvider is missing from onnxruntime-gpu "
        f"(providers={available}). {hint_text}"
    )

    # Check if user explicitly forced CUDA (don't silently fall back)
    force_gpu = (os.environ.get("CTX_REQUIRE_GPU") or "").strip().lower() in {
        "1", "true", "yes",
    }
    if force_gpu:
        raise RuntimeError(
            msg + " Refusing CPU fallback (CTX_REQUIRE_GPU=1). "
            "Fix CUDA installation or use --profile dml / --profile cpu."
        )

    if progress is None:
        print(f"[accel] WARNING: {msg}", file=sys.stderr, flush=True)
        print("[accel] Falling back to CPU. Run `ctx setup --repair` after fixing CUDA.",
              file=sys.stderr, flush=True)
    else:
        progress.set(55, "CUDA unavailable — using CPU (check CUDA toolkit)")

    profile.profile = "cpu"
    profile.provider = "CPUExecutionProvider"
    profile.reason = msg
    profile.cuda_fallback_hint = hint_text


def configure(
    *,
    force_profile: str | None = None,
    install_pkgs: bool = True,
    download_model: bool = True,
    bench: bool = True,
    force_install: bool = False,
    progress: Any | None = None,
) -> AccelProfile:
    detected = detect_hardware()
    hardware_snapshot: dict[str, Any] = detected
    if progress is not None:
        progress.set(12, "Detecting hardware")
    try:
        from pipeline.hardware import ensure_hardware_snapshot

        hardware_snapshot = ensure_hardware_snapshot(force=True)
    except Exception as exc:  # noqa: BLE001
        if progress is None:
            print(f"[accel] hardware snapshot skipped: {exc}", file=sys.stderr, flush=True)
    profile = recommend_profile(detected)
    if force_profile:
        fp = force_profile.lower().strip()
        if fp not in {"cuda", "dml", "cpu", "coreml", "mlx"}:
            raise ValueError(f"unknown profile {force_profile}")
        profile.profile = fp
        profile.provider = {
            "cuda": "CUDAExecutionProvider",
            "dml": "DmlExecutionProvider",
            "cpu": "CPUExecutionProvider",
            "coreml": "CoreMLExecutionProvider",
            "mlx": "MLX",
        }[fp]
        profile.reason = f"forced profile={fp}"
        profile.detected = detected
        if fp == "mlx":
            profile.backend = "mlx"
            from pipeline.memory_budget import bootstrap_budget

            profile.batch_size = bootstrap_budget().mlx_batch
        if fp == "dml":
            profile.device_id = int(detected.get("suggested_dml_device_id") or 0)
        if fp == "coreml":
            from pipeline.coreml_mac import requested_compute_units

            machine = str(detected.get("machine") or platform.machine()).lower()
            apple = machine in {"arm64", "aarch64"}
            detected = {
                **detected,
                "apple_silicon": apple,
                "coreml_compute_units": requested_compute_units(),
            }
            profile.detected = detected
        profile.batch_size = BATCH_PREFER

    if progress is not None:
        progress.set(16, f"Using {profile.profile} profile")
    else:
        print(f"[accel] profile={profile.profile} reason={profile.reason}", file=sys.stderr, flush=True)
    if install_pkgs:
        if not force_install and profile_packages_satisfied(profile):
            if progress is not None:
                progress.set(55, "Runtime already installed")
            else:
                print(
                    f"[accel] packages already satisfy profile={profile.profile} — skip ORT reinstall",
                    file=sys.stderr,
                    flush=True,
                )
        else:
            install_profile_packages(profile.profile, progress=progress)
        _align_profile_to_ort(profile, progress=progress)
        _refuse_coreml_cpu_fallback(profile, progress=progress)
        _refuse_cuda_cpu_fallback(profile, progress=progress)
    elif profile.profile == "coreml":
        _refuse_coreml_cpu_fallback(profile, progress=progress)
    elif profile.profile == "cuda":
        _refuse_cuda_cpu_fallback(profile, progress=progress)
    if download_model:
        if progress is not None:
            progress.set(56, "Downloading embedding model")
        if profile.profile == "coreml":
            from pipeline.coreml_mac import (
                COREML_STATIC_BATCH,
                COREML_STATIC_SEQ,
                assert_coreml_ep_active,
                coreml_model_name,
                register_coreml_coderank_model,
            )

            if progress is not None:
                progress.set(57, "Preparing CoreML-static CodeRank ONNX")
            patched = register_coreml_coderank_model(
                batch=COREML_STATIC_BATCH,
                seq=COREML_STATIC_SEQ,
            )
            if patched is None:
                raise RuntimeError(
                    "Failed to patch CodeRank ONNX for CoreML static shapes. "
                    "Refusing CPU fallback."
                )
            if progress is not None:
                progress.set(70, "Probing CoreML GPU session")
            else:
                print(
                    f"[accel] probing CoreML EP on {patched}",
                    file=sys.stderr,
                    flush=True,
                )
            used = assert_coreml_ep_active(patched, profile.providers())
            print(
                f"[accel] CoreML session providers={used}",
                file=sys.stderr,
                flush=True,
            )
            profile.model = coreml_model_name(profile.model)
        if profile.profile == "mlx":
            if progress is not None:
                progress.set(57, "Preparing MLX FP16 CodeRank weights")
            from pipeline.mlx_mac import apply_mlx_production_defaults

            apply_mlx_production_defaults()
            profile.backend = "mlx"
            profile.provider = "MLX"
        ensure_coderank_model(profile, progress=progress)
    if bench:
        if progress is not None:
            progress.set(86, "Calibrating speed")
        try:
            if profile.profile == "mlx":
                calibration = _calibrate_mlx(profile)
            else:
                calibration = calibrate_batch(profile)
            if profile.profile == "coreml" and not calibration.get("ok"):
                raise RuntimeError(
                    "CoreML calibration failed: "
                    f"{calibration.get('errors') or calibration.get('error') or calibration}"
                )
            profile.batch_size = int(calibration["winner"])
            profile.texts_per_sec = calibration.get("texts_per_sec")
            profile.meets_target = (
                profile.texts_per_sec is not None and profile.texts_per_sec >= TARGET_TPS
            )
            profile.batch_calibration = calibration
            if progress is None:
                print(
                    f"[accel] batch={profile.batch_size} "
                    f"{profile.texts_per_sec or 0:.2f} t/s "
                    f"(target {TARGET_TPS}+) meet={profile.meets_target} "
                    f"reason={calibration.get('reason')}",
                    file=sys.stderr,
                    flush=True,
                )
            if (
                profile.profile == "coreml"
                and (profile.texts_per_sec or 0) < TARGET_TPS
            ):
                coreml_tps = float(profile.texts_per_sec or 0)
                msg = (
                    f"CoreML Metal path is {coreml_tps:.2f} t/s (RoPE dim-0 splits "
                    "the graph into many CPU/GPU partitions). Switching to Apple "
                    "Silicon CPU FastEmbed, which is much faster on this model."
                )
                if progress is None:
                    print(f"[accel] {msg}", file=sys.stderr, flush=True)
                else:
                    progress.set(88, "CoreML too slow — using CPU")
                profile.profile = "cpu"
                profile.provider = "CPUExecutionProvider"
                profile.model = CODERANK_MODEL
                profile.reason = msg
                calibration = calibrate_batch(profile)
                profile.batch_size = int(calibration["winner"])
                profile.texts_per_sec = calibration.get("texts_per_sec")
                profile.meets_target = (
                    profile.texts_per_sec is not None
                    and profile.texts_per_sec >= TARGET_TPS
                )
                profile.batch_calibration = {
                    **calibration,
                    "coreml_rejected_tps": coreml_tps,
                }
                if progress is None:
                    print(
                        f"[accel] CPU batch={profile.batch_size} "
                        f"{profile.texts_per_sec or 0:.2f} t/s",
                        file=sys.stderr,
                        flush=True,
                    )
            if not profile.meets_target and progress is None:
                print(
                    "[accel] WARNING: below 10 t/s target — indexing will still work; "
                    "consider a stronger GPU or shorter embed recipe.",
                    file=sys.stderr,
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001
            from pipeline.coreml_mac import mac_gpu_only

            if profile.profile == "coreml" and mac_gpu_only():
                raise RuntimeError(
                    f"CoreML GPU calibration failed: {exc}. Refusing CPU fallback."
                ) from exc
            if progress is None:
                print(f"[accel] batch calibration failed: {exc}", file=sys.stderr, flush=True)
            profile.texts_per_sec = None
            profile.meets_target = None
            profile.batch_calibration = {"ok": False, "error": str(exc)}

    from pipeline.resource_envelope import derive_envelope

    mib = 1024 * 1024
    total_mb = float(hardware_snapshot.get("ram_total_bytes") or 0) / mib
    available_mb = float(hardware_snapshot.get("ram_available_bytes") or 0) / mib
    envelope = derive_envelope(
        total_mb,
        available_mb,
        calibrated_batch=profile.batch_size,
        cpu_count=int(
            hardware_snapshot.get("cpu_count_logical")
            or hardware_snapshot.get("cpu_count")
            or detected.get("cpu_count")
            or 1
        ),
    )
    profile.envelope = asdict(envelope)
    fingerprint_fields = {
        "os": hardware_snapshot.get("os") or detected.get("os"),
        "machine": hardware_snapshot.get("machine") or detected.get("machine"),
        "cpu_model": hardware_snapshot.get("cpu_model"),
        "cpu_count": hardware_snapshot.get("cpu_count_logical")
        or hardware_snapshot.get("cpu_count")
        or detected.get("cpu_count"),
        "ram_total_bytes": hardware_snapshot.get("ram_total_bytes"),
        "gpus": hardware_snapshot.get("gpus") or detected.get("gpus") or [],
    }
    profile.hardware_fingerprint = hashlib.sha256(
        json.dumps(fingerprint_fields, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    save_accel(profile)
    try:
        from pipeline.hardware import save_hardware

        hardware_snapshot = dict(hardware_snapshot)
        hardware_snapshot["recommended_accel"] = {
            "profile": profile.profile,
            "provider": profile.provider,
            "batch_size": profile.batch_size,
            "reason": profile.reason,
            "device_id": profile.device_id,
        }
        save_hardware(hardware_snapshot)
    except Exception as exc:  # noqa: BLE001
        if progress is None:
            print(f"[accel] hardware snapshot update skipped: {exc}", file=sys.stderr, flush=True)
    if progress is not None:
        progress.set(92, "Saving machine profile")
    else:
        print(f"[accel] wrote {ACCEL_PATH}", file=sys.stderr, flush=True)
    return profile


def register_coderank() -> None:
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    try:
        TextEmbedding.add_custom_model(
            model=CODERANK_MODEL,
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf=CODERANK_HF_ONNX),
            dim=768,
            model_file="onnx/model.onnx",
            description="CodeRankEmbed FP32 ONNX",
            license="mit",
            size_in_gb=0.5,
        )
    except ValueError as exc:
        if "already registered" not in str(exc).lower():
            raise


def ensure_coderank_model(
    profile: AccelProfile | None = None,
    progress: Any | None = None,
) -> None:
    """Download/warm CodeRank ONNX via FastEmbed."""
    import threading

    register_coderank()
    from fastembed import TextEmbedding

    prof = profile or load_accel() or recommend_profile()
    model_name = prof.model
    static_bs = 1
    if prof.profile == "coreml":
        from pipeline.coreml_mac import (
            coreml_model_name,
            pad_embed_batch,
            static_embed_batch_size,
        )

        model_name = coreml_model_name(prof.model)
        static_bs = static_embed_batch_size(prof, prof.batch_size)
    previous = {
        name: os.environ.get(name)
        for name in ("HF_HUB_DISABLE_PROGRESS_BARS", "TQDM_DISABLE")
    }
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["TQDM_DISABLE"] = "1"
    if progress is None:
        print(f"[accel] ensuring CodeRank model ({CODERANK_HF_ONNX}) ...", file=sys.stderr, flush=True)
    stop = threading.Event()

    def _pulse() -> None:
        while not stop.wait(0.2):
            if progress is not None:
                progress.pulse("Downloading embedding model", until=84)

    worker: threading.Thread | None = None
    if progress is not None:
        worker = threading.Thread(target=_pulse, daemon=True)
        worker.start()
    try:
        if prof.profile == "mlx" or prof.backend == "mlx":
            from pipeline.mlx_mac import (
                CodeRankMLX,
                apply_mlx_production_defaults,
                ensure_mlx_fp16_weights,
            )

            apply_mlx_production_defaults()
            # Download ONNX via CPU EP, then convert to isolated MLX FP16 weights.
            m = TextEmbedding(
                model_name=CODERANK_MODEL,
                threads=1,
                providers=["CPUExecutionProvider"],
                lazy_load=True,
            )
            list(m.embed(["warmup coderank embedding on accelerator"], batch_size=1, parallel=None))
            ensure_mlx_fp16_weights()
            CodeRankMLX(dtype="float16", require_gpu=True)
        else:
            m = TextEmbedding(
                model_name=model_name,
                threads=1,
                providers=prof.providers(),
                lazy_load=True,
            )
            warmup = ["warmup coderank embedding on accelerator"]
            if prof.profile == "coreml":
                from pipeline.coreml_mac import bind_coreml_tokenizer

                bind_coreml_tokenizer(m)
                warmup = pad_embed_batch(warmup, static_bs)
            list(m.embed(warmup, batch_size=static_bs, parallel=None))
    finally:
        stop.set()
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    if progress is not None:
        progress.set(85, "Embedding model ready")
    else:
        print("[accel] CodeRank model ready", file=sys.stderr, flush=True)


def _calibrate_mlx(profile: AccelProfile) -> dict[str, Any]:
    """Persist MLX production batch without an ORT microbench."""
    from pipeline.memory_budget import bootstrap_budget
    from pipeline.mlx_mac import CodeRankMLX, apply_mlx_production_defaults

    apply_mlx_production_defaults()
    budget = bootstrap_budget()
    winner = int(budget.mlx_batch)
    tps = None
    try:
        model = CodeRankMLX(dtype="float16", require_gpu=True)
        texts = _calibration_corpus(max(8, min(48, winner)))
        t0 = time.perf_counter()
        model.embed_texts(texts)
        wall = max(time.perf_counter() - t0, 1e-6)
        tps = round(len(texts) / wall, 3)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "winner": winner,
            "error": str(exc),
            "reason": "mlx warmup failed",
        }
    profile.batch_size = winner
    return {
        "ok": True,
        "winner": winner,
        "texts_per_sec": tps,
        "candidates": {str(winner): tps},
        "reason": "MLX FP16 production batch (bootstrap memory budget)",
        "dtype": "float16",
    }


def _calibration_corpus(n: int) -> list[str]:
    """CE-like enriched snippets (~700 chars) — matches real indexing inputs."""
    base = (
        "def authenticate(user, token):\n"
        "    \"\"\"Validate session token and return claims.\"\"\"\n"
        "    if not token:\n"
        "        raise ValueError('missing token')\n"
        "    return verify(user, token)\n"
        "# enriched: auth handler dispatch session claims validation\n"
    )
    text = (base * 4)[:700]
    return [f"{text}\n# id={i}\n" for i in range(max(1, n))]


def pick_batch_size(
    scores: dict[int, float],
    *,
    prefer: int = BATCH_PREFER,
    promote_ratio: float = BATCH_PROMOTE_MIN_RATIO,
    promote_min_tps: float = BATCH_PROMOTE_MIN_TPS,
    downgrade_ratio: float = BATCH_DOWNGRADE_MIN_RATIO,
) -> tuple[int, str]:
    """Choose among measured batch scores with a bias toward 16.

    Rules:
    - Prefer 16 when it ran successfully.
    - Take 20 only when it beats 16 by promote_ratio AND promote_min_tps.
    - Take 8 only when 16 is missing/failed, or 8 beats 16 by downgrade_ratio.
    """
    valid = {int(k): float(v) for k, v in scores.items() if v is not None and float(v) > 0}
    if not valid:
        return prefer, "no successful measurements; default prefer"

    def _tps(batch: int) -> float | None:
        return valid.get(batch)

    t16 = _tps(prefer)
    t20 = _tps(20)
    t8 = _tps(8)

    if t16 is not None:
        if t20 is not None:
            gain = t20 - t16
            ratio = (t20 / t16) - 1.0 if t16 > 0 else 0.0
            if ratio >= promote_ratio and gain >= promote_min_tps:
                return 20, (
                    f"20 beats 16 by {ratio * 100:.1f}% "
                    f"({t20:.2f} vs {t16:.2f} t/s)"
                )
            if t20 > t16:
                return prefer, (
                    f"keep 16; 20 only +{ratio * 100:.1f}% "
                    f"({t20:.2f} vs {t16:.2f} t/s) — poor ROI"
                )
        if t8 is not None and t8 > t16 * (1.0 + downgrade_ratio):
            return 8, (
                f"8 beats unstable/slow 16 by "
                f"{((t8 / t16) - 1.0) * 100:.1f}% ({t8:.2f} vs {t16:.2f} t/s)"
            )
        return prefer, f"prefer 16 at {t16:.2f} t/s"

    # 16 failed — pick best remaining with preference order 20 then 8
    if t20 is not None and (t8 is None or t20 >= t8):
        return 20, f"16 unavailable; use 20 at {t20:.2f} t/s"
    if t8 is not None:
        return 8, f"16 unavailable; use 8 at {t8:.2f} t/s"
    winner = max(valid.items(), key=lambda item: item[1])[0]
    return winner, f"fallback to best measured batch={winner}"


def calibrate_batch(
    profile: AccelProfile,
    *,
    n: int | None = None,
    candidates: tuple[int, ...] = BATCH_CANDIDATES,
    model: Any | None = None,
) -> dict[str, Any]:
    """Measure candidate batches once and persist a smart winner (usually 16)."""
    register_coderank()
    from fastembed import TextEmbedding

    count = int(n if n is not None else BATCH_CALIBRATE_N)
    model_name = profile.model
    static_bs = None
    batch_candidates = candidates
    if profile.profile == "coreml":
        from pipeline.coreml_mac import (
            COREML_STATIC_BATCH,
            coreml_model_name,
            pad_embed_batch,
            static_embed_batch_size,
        )

        model_name = coreml_model_name(profile.model)
        static_bs = static_embed_batch_size(profile, COREML_STATIC_BATCH)
        batch_candidates = (static_bs,)
        count = max(static_bs, ((count + static_bs - 1) // static_bs) * static_bs)
    else:
        lcm = math.lcm(*[int(b) for b in batch_candidates]) if batch_candidates else 1
        count = max(lcm, ((count + lcm - 1) // lcm) * lcm)
    texts = _calibration_corpus(count)

    if model is None:
        model = TextEmbedding(
            model_name=model_name,
            threads=1,
            providers=profile.providers(),
            lazy_load=True,
        )
        if static_bs:
            from pipeline.coreml_mac import bind_coreml_tokenizer

            bind_coreml_tokenizer(model)
            warm = pad_embed_batch(texts[:static_bs], static_bs)
            list(model.embed(warm, batch_size=static_bs, parallel=None))
        else:
            list(model.embed(texts[:1], batch_size=1, parallel=None))

    measured: dict[str, float] = {}
    errors: dict[str, str] = {}
    order = sorted(batch_candidates, key=lambda b: (0 if b == BATCH_PREFER else 1, abs(b - BATCH_PREFER)))
    t_start = time.perf_counter()
    for batch in order:
        try:
            t0 = time.perf_counter()
            payload = texts
            ort_bs = int(batch)
            if profile.profile == "coreml" and static_bs is not None:
                ort_bs = static_bs
                payload = pad_embed_batch(texts[:static_bs], static_bs)
            list(model.embed(payload, batch_size=ort_bs, parallel=None))
            wall = time.perf_counter() - t0
            used = static_bs if profile.profile == "coreml" else len(texts)
            tps = used / max(wall, 1e-6)
            measured[str(batch if profile.profile != "coreml" else static_bs)] = round(tps, 3)
            print(
                f"[accel] calibrate batch={batch} → {tps:.2f} t/s",
                file=sys.stderr,
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            errors[str(batch)] = str(exc)
            print(
                f"[accel] calibrate batch={batch} failed: {exc}",
                file=sys.stderr,
                flush=True,
            )

    scores = {int(k): v for k, v in measured.items()}
    winner, reason = pick_batch_size(scores)
    if profile.profile == "coreml" and static_bs is not None:
        winner = min(int(profile.batch_size or BATCH_PREFER), static_bs)
        reason = f"CoreML static ONNX batch={static_bs}; runtime batch={winner}"
    winner_tps = scores.get(winner)
    if winner_tps is None and static_bs is not None:
        winner_tps = scores.get(int(static_bs))
    elapsed = time.perf_counter() - t_start
    return {
        "ok": bool(scores),
        "winner": winner,
        "texts_per_sec": None if winner_tps is None else round(winner_tps, 3),
        "candidates": measured,
        "errors": errors,
        "n": count,
        "elapsed_s": round(elapsed, 3),
        "reason": reason,
        "prefer": BATCH_PREFER,
        "promote_ratio": BATCH_PROMOTE_MIN_RATIO,
        "promote_min_tps": BATCH_PROMOTE_MIN_TPS,
        "coreml_static_batch": static_bs,
    }


def microbench(profile: AccelProfile, n: int = 48) -> float:
    """Return texts/sec using the profile's configured batch (legacy helper)."""
    calibration = calibrate_batch(profile, n=n, candidates=(max(1, int(profile.batch_size)),))
    tps = calibration.get("texts_per_sec")
    if tps is None:
        raise RuntimeError(calibration.get("errors") or "microbench failed")
    return float(tps)


def resolve_runtime() -> AccelProfile:
    """Load the installed preference without detection or selection.

    Apple Silicon: ``ctx setup`` persists ``profile=mlx`` (FP16). A saved
    CoreML profile is overlaid with MLX when the ``mlx`` package is installed.
    ``accel.json`` is not rewritten here. Opt out with ``CTX_EMBED_BACKEND=fastembed``
    or ``CTX_MLX=0``. An explicit CPU profile is left unchanged.
    """
    profile = load_accel()
    if profile is None:
        raise RuntimeError("acceleration profile is not configured; run `ctx setup`")
    env = os.environ.get("CTX_EMBED_BACKEND", "").strip().lower()
    want_mlx = env == "mlx" or (profile.profile == "mlx" or profile.backend == "mlx")
    if profile.profile in {"dml", "cuda"} and env != "mlx":
        return profile
    if not want_mlx and not _env_disables_mlx() and _is_apple_silicon(profile.detected or {}):
        # Promote the old CoreML path only. An explicit CPU profile stays CPU.
        if profile.profile == "coreml" and _mlx_importable():
            want_mlx = True
    if not want_mlx:
        return profile
    from dataclasses import replace

    from pipeline.memory_budget import bootstrap_budget

    batch = int(profile.batch_size or bootstrap_budget().mlx_batch)
    if "CTX_EMBED_BATCH" in os.environ:
        batch = max(1, int(os.environ["CTX_EMBED_BATCH"]))
    elif profile.profile not in {"mlx"}:
        batch = bootstrap_budget().mlx_batch
    return replace(
        profile,
        profile="mlx",
        provider="MLX",
        backend="mlx",
        batch_size=batch,
        reason="MLX FP16 overlay (saved accel.json unchanged)",
    )

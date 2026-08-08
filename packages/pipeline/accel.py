"""Hardware acceleration probe + install profile for CodeRank FastEmbed.

Profiles (mutually exclusive ORT wheels):
  - cuda  → onnxruntime-gpu
  - dml   → onnxruntime-directml  (Windows AMD/Intel/NVIDIA without CUDA stack)
  - cpu   → onnxruntime

Persists choice to ``~/.context-engine/accel.json``.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CODERANK_MODEL = "nomic-ai/CodeRankEmbed"
CODERANK_HF_ONNX = "jamie8johnson/CodeRankEmbed-onnx"
TARGET_TPS = float(os.environ.get("CTX_TARGET_TPS", "10"))
ACCEL_PATH = Path.home() / ".context-engine" / "accel.json"


@dataclass
class AccelProfile:
    profile: str  # cuda | dml | cpu
    provider: str  # CUDAExecutionProvider | DmlExecutionProvider | CPUExecutionProvider
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

    def providers(self) -> list:
        if self.profile == "cuda":
            return [("CUDAExecutionProvider", {"device_id": self.device_id}), "CPUExecutionProvider"]
        if self.profile == "dml":
            return [("DmlExecutionProvider", {"device_id": self.device_id}), "CPUExecutionProvider"]
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
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(
                ["nvidia-smi", "-L"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            return r.returncode == 0 and "GPU" in (r.stdout or "")
        except Exception:  # noqa: BLE001
            return False
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:  # noqa: BLE001
        return False


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
    return {
        "os": platform.system(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "nvidia": nvidia,
        "gpus": gpus,
        "cpu_count": os.cpu_count() or 4,
        "suggested_dml_device_id": dml_id,
    }


def recommend_profile(detected: dict[str, Any] | None = None) -> AccelProfile:
    d = detected or detect_hardware()
    if d.get("nvidia"):
        return AccelProfile(
            profile="cuda",
            provider="CUDAExecutionProvider",
            device_id=0,
            batch_size=32,
            reason="NVIDIA GPU detected — use onnxruntime-gpu + FastEmbed",
            detected=d,
        )
    if d.get("os") == "Windows" and d.get("gpus"):
        # Any real adapter → DML (covers AMD/Intel/NVIDIA without CUDA toolkit)
        return AccelProfile(
            profile="dml",
            provider="DmlExecutionProvider",
            device_id=int(d.get("suggested_dml_device_id") or 0),
            batch_size=16,
            reason="Windows GPU via DirectML — use onnxruntime-directml + FastEmbed",
            detected=d,
        )
    return AccelProfile(
        profile="cpu",
        provider="CPUExecutionProvider",
        device_id=0,
        batch_size=8,
        reason="No usable GPU accelerator — FastEmbed CPU (multi-core)",
        detected=d,
    )


def ort_packages_for(profile: str) -> list[str]:
    if profile == "cuda":
        return ["onnxruntime-gpu>=1.17"]
    if profile == "dml":
        return ["onnxruntime-directml>=1.17"]
    return ["onnxruntime>=1.17"]


def conflicting_ort_packages(profile: str) -> list[str]:
    """ORT wheels conflict — uninstall others before installing profile package."""
    all_ort = {"onnxruntime", "onnxruntime-gpu", "onnxruntime-directml"}
    keep = {
        "cuda": "onnxruntime-gpu",
        "dml": "onnxruntime-directml",
        "cpu": "onnxruntime",
    }[profile]
    return sorted(all_ort - {keep})


def pip_install(pkgs: list[str], *, upgrade: bool = True) -> None:
    cmd = [sys.executable, "-m", "pip", "install"]
    if upgrade:
        cmd.append("-U")
    cmd.extend(pkgs)
    print(f"[accel] {' '.join(cmd)}", file=sys.stderr, flush=True)
    subprocess.check_call(cmd)


def pip_uninstall(pkgs: list[str]) -> None:
    cmd = [sys.executable, "-m", "pip", "uninstall", "-y", *pkgs]
    print(f"[accel] {' '.join(cmd)}", file=sys.stderr, flush=True)
    subprocess.run(cmd, check=False)


def install_profile_packages(profile: str) -> None:
    """Install FastEmbed + matching ORT wheel for profile.

    FastEmbed depends on ``onnxruntime`` (CPU). For cuda/dml we install FastEmbed
    first, then *replace* the ORT wheel with the accelerator build.
    """
    pip_install(["fastembed>=0.4", "huggingface_hub>=0.20"])
    # Drop whatever ORT FastEmbed pulled; install the profile-specific wheel.
    pip_uninstall(["onnxruntime", "onnxruntime-gpu", "onnxruntime-directml"])
    pip_install(ort_packages_for(profile))


def ort_available_providers() -> list[str]:
    try:
        import onnxruntime as ort  # type: ignore

        return list(ort.get_available_providers())
    except Exception:  # noqa: BLE001
        return []


def profile_packages_satisfied(profile: AccelProfile) -> bool:
    """True if saved accel matches target and ORT already exposes the provider."""
    saved = load_accel()
    if saved is None or saved.profile != profile.profile:
        return False
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


def configure(
    *,
    force_profile: str | None = None,
    install_pkgs: bool = True,
    download_model: bool = True,
    bench: bool = True,
    force_install: bool = False,
) -> AccelProfile:
    detected = detect_hardware()
    try:
        from pipeline.hardware import ensure_hardware_snapshot

        ensure_hardware_snapshot(force=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[accel] hardware snapshot skipped: {exc}", file=sys.stderr, flush=True)
    profile = recommend_profile(detected)
    if force_profile:
        fp = force_profile.lower().strip()
        if fp not in {"cuda", "dml", "cpu"}:
            raise ValueError(f"unknown profile {force_profile}")
        profile.profile = fp
        profile.provider = {
            "cuda": "CUDAExecutionProvider",
            "dml": "DmlExecutionProvider",
            "cpu": "CPUExecutionProvider",
        }[fp]
        profile.reason = f"forced profile={fp}"
        profile.detected = detected
        if fp == "dml":
            profile.device_id = int(detected.get("suggested_dml_device_id") or 0)
            profile.batch_size = 16
        elif fp == "cuda":
            profile.batch_size = 32
        else:
            profile.batch_size = 8

    print(f"[accel] profile={profile.profile} reason={profile.reason}", file=sys.stderr, flush=True)
    if install_pkgs:
        if not force_install and profile_packages_satisfied(profile):
            print(
                f"[accel] packages already satisfy profile={profile.profile} — skip ORT reinstall",
                file=sys.stderr,
                flush=True,
            )
        else:
            install_profile_packages(profile.profile)
    if download_model:
        ensure_coderank_model(profile)
    if bench:
        try:
            tps = microbench(profile)
            profile.texts_per_sec = round(tps, 3)
            profile.meets_target = tps >= TARGET_TPS
            print(
                f"[accel] microbench {tps:.2f} t/s "
                f"(target {TARGET_TPS}+) meet={profile.meets_target}",
                file=sys.stderr,
                flush=True,
            )
            if not profile.meets_target:
                print(
                    "[accel] WARNING: below 10 t/s target — indexing will still work; "
                    "consider a stronger GPU or shorter embed recipe.",
                    file=sys.stderr,
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001
            print(f"[accel] microbench failed: {exc}", file=sys.stderr, flush=True)
            profile.texts_per_sec = None
            profile.meets_target = None

    save_accel(profile)
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


def ensure_coderank_model(profile: AccelProfile | None = None) -> None:
    """Download/warm CodeRank ONNX via FastEmbed."""
    register_coderank()
    from fastembed import TextEmbedding

    prof = profile or load_accel() or recommend_profile()
    print(f"[accel] ensuring CodeRank model ({CODERANK_HF_ONNX}) ...", file=sys.stderr, flush=True)
    m = TextEmbedding(
        model_name=CODERANK_MODEL,
        threads=1,
        providers=prof.providers(),
        lazy_load=True,
    )
    list(m.embed(["warmup coderank"], batch_size=1, parallel=None))
    print("[accel] CodeRank model ready", file=sys.stderr, flush=True)


def microbench(profile: AccelProfile, n: int = 48) -> float:
    """Return texts/sec on synthetic ~800-char snippets."""
    register_coderank()
    from fastembed import TextEmbedding

    text = ("def foo(x):\n    return x * 2\n\n" * 20)[:800]
    texts = [f"{text}\n# {i}" for i in range(n)]
    m = TextEmbedding(
        model_name=CODERANK_MODEL,
        threads=1,
        providers=profile.providers(),
        lazy_load=True,
    )
    list(m.embed(texts[:1], batch_size=1, parallel=None))
    t0 = time.perf_counter()
    list(m.embed(texts, batch_size=profile.batch_size, parallel=None))
    wall = time.perf_counter() - t0
    return len(texts) / max(wall, 1e-6)


def resolve_runtime() -> AccelProfile:
    """Load saved profile or recommend without installing."""
    env = os.environ.get("CTX_ACCEL", "").strip().lower()
    if env in {"cuda", "dml", "cpu"}:
        p = recommend_profile()
        p.profile = env
        p.provider = {
            "cuda": "CUDAExecutionProvider",
            "dml": "DmlExecutionProvider",
            "cpu": "CPUExecutionProvider",
        }[env]
        p.reason = f"CTX_ACCEL={env}"
        return p
    return load_accel() or recommend_profile()

"""Hardware acceleration probe + install profile for CodeRank FastEmbed.

Profiles (mutually exclusive ORT wheels, plus Mac MLX):
  - cuda    → onnxruntime-gpu
  - dml     → onnxruntime-directml  (Windows AMD/Intel/NVIDIA without CUDA stack)
  - mlx     → Apple Silicon Metal (FP16 CodeRank only; default on Darwin arm64)
  - coreml  → onnxruntime  (Intel Mac / explicit --profile coreml)
  - cpu     → onnxruntime

Persists choice to ``~/.scubiee/accel.json``.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable
from pipeline.project_id import context_engine_home

CODERANK_MODEL = "nomic-ai/CodeRankEmbed"
CODERANK_HF_ONNX = "jamie8johnson/CodeRankEmbed-onnx"
# Production weights: FP16 ONNX only (Windows/Linux FastEmbed + Mac convert source).
CODERANK_ONNX_FILE = "onnx/model_fp16.onnx"
# HF hosts FP32 source weights under this name; setup converts to model_fp16.onnx locally.
CODERANK_FP32_ONNX_FILE = "onnx/model.onnx"
CODERANK_FP16_MIN_BYTES = 180_000_000
# Installed alongside fastembed (--no-deps) so CPU onnxruntime is not pulled back in.
FASTEMBED_RUNTIME_DEPS = [
    "huggingface_hub>=0.20",
    "loguru>=0.7.2",
    "mmh3>=4.1.0",
    "onnx>=1.16",
    "Pillow>=10.0",
    "py-rust-stemmers>=0.1.0",
    "tokenizers>=0.15",
    "tqdm>=4.66",
]
TARGET_TPS = float(os.environ.get("CTX_TARGET_TPS", "10"))


def accel_path() -> Path:
    """Resolved accel.json path.

    Honors an explicit ``ACCEL_PATH`` monkeypatch (tests), then ``CTX_HOME``,
    then ``~/.scubiee/accel.json``.
    """
    # Tests commonly ``monkeypatch.setattr(accel, "ACCEL_PATH", tmp/...)``.
    current = globals().get("ACCEL_PATH")
    default = context_engine_home() / "accel.json"
    if isinstance(current, Path) and current != default:
        return current
    override = (os.environ.get("CTX_HOME") or "").strip()
    if override:
        return Path(override) / "accel.json"
    return default


ACCEL_PATH = context_engine_home() / "accel.json"
# Install-time batch candidates. Prefer 16 unless 20 clearly wins ROI.
BATCH_CANDIDATES = (8, 16, 20)
BATCH_PREFER = 16
# CPU is much slower — one preferred batch + smaller corpus keeps setup usable.
CPU_BATCH_CANDIDATES = (16,)
CPU_BATCH_CALIBRATE_N = int(os.environ.get("CTX_CPU_BATCH_CALIBRATE_N", "16"))
# Promote 16 → 20 only when throughput gain is clearly worth it.
BATCH_PROMOTE_MIN_RATIO = float(os.environ.get("CTX_BATCH_PROMOTE_RATIO", "0.10"))
BATCH_PROMOTE_MIN_TPS = float(os.environ.get("CTX_BATCH_PROMOTE_TPS", "3.0"))
# Prefer 16 over 8 unless 8 is meaningfully faster (pathological 16 case).
BATCH_DOWNGRADE_MIN_RATIO = float(os.environ.get("CTX_BATCH_DOWNGRADE_RATIO", "0.15"))
BATCH_CALIBRATE_N = int(os.environ.get("CTX_BATCH_CALIBRATE_N", "64"))
# Never hang forever on DirectML/CUDA calibrate (user's CPU-only laptop hang).
CALIBRATE_TIMEOUT_S = float(os.environ.get("CTX_CALIBRATE_TIMEOUT_S", "90"))
CPU_CALIBRATE_TIMEOUT_S = float(os.environ.get("CTX_CPU_CALIBRATE_TIMEOUT_S", "120"))
GPU_PROBE_TIMEOUT_S = float(os.environ.get("CTX_GPU_PROBE_TIMEOUT_S", "45"))


@dataclass
class AccelProfile:
    profile: str  # cuda | dml | mlx | coreml | cpu
    provider: str  # CUDAExecutionProvider | DmlExecutionProvider | CoreMLExecutionProvider | CPUExecutionProvider
    device_id: int = 0
    batch_size: int = 16
    backend: str = "fastembed"
    model: str = CODERANK_MODEL
    model_source: str = CODERANK_HF_ONNX
    onnx_file: str = CODERANK_ONNX_FILE
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
    p = path or accel_path()
    if not p.exists():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        profile = AccelProfile(
            **{k: v for k, v in raw.items() if k in AccelProfile.__dataclass_fields__}
        )
        # Force FP16 ONNX even if an older accel.json still lists model.onnx.
        if profile.onnx_file != CODERANK_ONNX_FILE:
            profile.onnx_file = CODERANK_ONNX_FILE
        return profile
    except Exception:  # noqa: BLE001
        return None


def save_accel(profile: AccelProfile, path: Path | None = None) -> Path:
    p = path or accel_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone

    profile.onnx_file = CODERANK_ONNX_FILE
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


def _windows_gpu_name(gpu: dict[str, Any] | str) -> str:
    if isinstance(gpu, dict):
        return str(gpu.get("name") or "").strip().lower()
    return str(gpu or "").strip().lower()


def _windows_gpu_pnp(gpu: dict[str, Any] | str) -> str:
    if isinstance(gpu, dict):
        return str(gpu.get("pnp_device_id") or gpu.get("PNPDeviceID") or "").strip().upper()
    return ""


def _windows_gpu_compat(gpu: dict[str, Any] | str) -> str:
    if isinstance(gpu, dict):
        return str(
            gpu.get("adapter_compatibility") or gpu.get("AdapterCompatibility") or ""
        ).strip().lower()
    return ""


def _windows_pci_vendor(gpu: dict[str, Any] | str) -> str | None:
    """Return nvidia | amd | intel from PNPDeviceID / AdapterCompatibility when known."""
    pnp = _windows_gpu_pnp(gpu)
    # PCI\VEN_10DE&DEV_...  (NVIDIA), VEN_1002 (AMD), VEN_8086 (Intel)
    if "VEN_10DE" in pnp:
        return "nvidia"
    if "VEN_1002" in pnp:
        return "amd"
    if "VEN_8086" in pnp:
        return "intel"
    compat = _windows_gpu_compat(gpu)
    if "nvidia" in compat:
        return "nvidia"
    if "advanced micro devices" in compat or compat == "amd":
        return "amd"
    if "intel" in compat:
        return "intel"
    return None


def _windows_pci_device_id(gpu: dict[str, Any] | str) -> str | None:
    """Return lowercase 4-hex PCI device id from PNPDeviceID (DEV_XXXX), if present."""
    pnp = _windows_gpu_pnp(gpu)
    m = re.search(r"DEV_([0-9A-F]{4})", pnp)
    if m:
        return m.group(1).lower()
    if isinstance(gpu, dict):
        raw = gpu.get("device_id") or gpu.get("DeviceId")
        if raw is not None:
            try:
                return f"{int(raw):04x}"
            except (TypeError, ValueError):
                text = str(raw).strip().lower().removeprefix("0x")
                if len(text) == 4 and all(c in "0123456789abcdef" for c in text):
                    return text
    return None


# ---------------------------------------------------------------------------
# Structural PCI ID tables (industry approach — names alone can never be 100%).
# Microsoft DXGI has NO discrete/integrated flag (only SOFTWARE). Vulkan has
# PHYSICAL_DEVICE_TYPE_*; on Windows without Vulkan we use PCI device IDs.
# Sources: AMD/Linux pci tables, rusty-stack INTEGRATED_PCI_DEVICE_IDS +
# DISCRETE_PCI_ID_TO_GFX, public APU reports (Rembrandt 1638, Strix 150e, …).
# Conservative: APU denylist only IDs that are definitively integrated.
# ---------------------------------------------------------------------------

# AMD APU / iGPU PCI device IDs — NEVER select DirectML for these.
_AMD_APU_PCI_DEVICE_IDS: frozenset[str] = frozenset(
    {
        # Raven Ridge / Picasso
        "15d8",
        "15dd",
        "15d9",
        # Renoir
        "15e7",
        "1636",
        "1638",  # also Rembrandt overlap in some tables; Rembrandt confirmed 1638
        "164c",
        "15e0",
        "1506",
        # Cezanne / Barcelo
        "1638",
        "1640",
        "15e7",
        # Rembrandt / Yellow Carp (Ryzen 6000 / 7x35)
        "164d",
        "1681",
        # Raphael desktop iGPU
        "164e",
        # Phoenix / Hawk Point
        "15bf",
        "15c8",
        "15d0",
        "1900",
        "1901",
        # Mendocino
        "150e",  # also reported for Strix 880M/890M APU iGPU
        "150f",
        # Van Gogh (Steam Deck APU)
        "163f",
        # Older Llano/Trinity/Kaveri/Carrizo/Bristol/Stoney APU ranges (common)
        "9802",
        "9803",
        "9804",
        "9805",
        "9806",
        "9807",
        "9808",
        "9809",
        "980a",
        "9640",
        "9641",
        "9642",
        "9643",
        "9644",
        "9645",
        "9647",
        "9648",
        "9649",
        "964a",
        "9900",
        "9901",
        "9902",
        "9903",
        "9904",
        "9905",
        "9906",
        "9907",
        "9908",
        "9909",
        "990a",
        "990b",
        "990c",
        "990d",
        "990e",
        "990f",
        "1304",
        "1305",
        "1306",
        "1307",
        "1309",
        "130a",
        "130b",
        "130c",
        "130d",
        "130e",
        "130f",
        "1310",
        "1311",
        "1312",
        "1313",
        "1315",
        "1316",
        "1317",
        "1318",
        "131b",
        "131c",
        "131d",
        "9870",
        "9874",
        "9875",
        "9876",
        "9877",
        "98e4",
    }
)

# Known AMD *discrete* PCI device IDs (RDNA2/3/4 + common Navi). Weird OEM
# marketing names still classify as discrete when the silicon ID is known.
_AMD_DISCRETE_PCI_DEVICE_IDS: frozenset[str] = frozenset(
    {
        # RDNA4
        "7550",
        "7551",
        "7590",
        # RDNA3 Navi31/32/33
        "744c",
        "7448",
        "7449",
        "744a",
        "744b",
        "745e",
        "747e",
        "7470",
        "7460",
        "7461",
        "7480",
        "7483",
        "7489",
        "749f",
        "73f0",
        # RDNA2 Navi21/22/23/24 (incl. RX 6500M = 743f)
        "73bf",
        "73af",
        "73a5",
        "73a1",
        "73a2",
        "73a3",
        "73df",
        "73c3",
        "73ff",
        "73ef",
        "73e0",
        "73e1",
        "73e3",
        "743f",
        "7424",
        "7421",
        "7422",
        "7423",
        # RDNA1 / older discrete common
        "731f",
        "7340",
        "73a0",
        "67df",  # Polaris RX 470/480/570/580
        "67ff",
        "6fdf",
        "687f",
        "6867",
    }
)


def _is_windows_software_adapter(gpu: dict[str, Any] | str) -> bool:
    name = _windows_gpu_name(gpu)
    return (
        "microsoft" in name
        or "basic render" in name
        or "basic display" in name
        or "remote desktop" in name
        or "virtual" in name
        or "hyper-v" in name
        or "parsec" in name
        or "citrix" in name
        or "vmware" in name
    )


def _is_windows_intel_or_igpu_denied(gpu: dict[str, Any] | str) -> bool:
    """Adapters that must never select DirectML (hang / crawl risk)."""
    if _is_windows_software_adapter(gpu):
        return True
    vendor = _windows_pci_vendor(gpu)
    if vendor == "intel":
        return True
    # Structural: known AMD APU PCI device IDs are never DML-eligible.
    dev = _windows_pci_device_id(gpu)
    if dev and (vendor in {None, "amd"}) and dev in _AMD_APU_PCI_DEVICE_IDS:
        return True
    name = _windows_gpu_name(gpu)
    if not name:
        return True

    intel_markers = (
        "intel",
        "uhd graphics",
        "hd graphics",
        "iris",
        "arc a",  # Intel Arc — not on our DML allowlist by policy
        "xe graphics",
    )
    if any(m in name for m in intel_markers):
        return True

    # AMD APU / integrated — plain "Radeon Graphics", Vega Graphics, RDNA iGPU M parts.
    amd_igpu = (
        "radeon(tm) graphics",
        "radeon graphics",
        "amd radeon graphics",
        "radeon vega graphics",
        "vega graphics",
        "graphics (radeon",
        "radeon(tm) rx vega 3",
        "radeon(tm) rx vega 6",
        "radeon(tm) rx vega 8",
        "radeon(tm) rx vega 10",
        "radeon(tm) rx vega 11",
        "radeon rx vega 3",
        "radeon rx vega 6",
        "radeon rx vega 8",
        "radeon rx vega 10",
        "radeon rx vega 11",
        # RDNA2/3/4 laptop APU iGPUs (not discrete RX cards)
        "radeon 610m",
        "radeon 660m",
        "radeon 680m",
        "radeon 740m",
        "radeon 760m",
        "radeon 780m",
        "radeon 880m",
        "radeon 890m",
        "radeon 8050s",
        "radeon 8060s",
    )
    if any(m in name for m in amd_igpu):
        return True
    # "… Vega N Graphics" APU wording (without discrete RX Vega 56/64)
    if "vega" in name and "graphics" in name and "rx vega 5" not in name and "rx vega 6" not in name:
        # rx vega 56/64 are discrete; rx vega 3/8/11 graphics already denied above
        if not any(x in name for x in ("rx vega 56", "rx vega 64", "vega 56", "vega 64")):
            return True
    return False


def _is_windows_nvidia_discrete(gpu: dict[str, Any] | str) -> bool:
    if _is_windows_intel_or_igpu_denied(gpu):
        return False
    name = _windows_gpu_name(gpu)
    vendor = _windows_pci_vendor(gpu)
    nvidia_markers = (
        "nvidia",
        "geforce",
        "rtx ",
        "rtx-",
        "rtx a",  # RTX A2000 workstation
        "gtx ",
        "gtx-",
        "quadro",
        "tesla",
        "titan",
        "nvs ",
        "rtx 20",
        "rtx 30",
        "rtx 40",
        "rtx 50",
    )
    if vendor == "nvidia":
        return True
    return any(m in name for m in nvidia_markers)


def _is_windows_amd_discrete(gpu: dict[str, Any] | str) -> bool:
    """True only for discrete AMD GPUs. Ambiguous AMD names → False (CPU-safe)."""
    if _is_windows_intel_or_igpu_denied(gpu):
        return False
    name = _windows_gpu_name(gpu)
    vendor = _windows_pci_vendor(gpu)
    if vendor not in {None, "amd"} and "radeon" not in name and "amd" not in name:
        return False
    # Structural: known discrete silicon IDs win even with weird OEM names.
    dev = _windows_pci_device_id(gpu)
    if dev and dev in _AMD_DISCRETE_PCI_DEVICE_IDS:
        return True
    if not name:
        return False

    # Discrete allowlist — prefer explicit product lines over bare "AMD".
    amd_discrete = (
        "radeon rx",
        "rx 460",
        "rx 470",
        "rx 480",
        "rx 550",
        "rx 560",
        "rx 570",
        "rx 580",
        "rx 590",
        "rx 5500",
        "rx 5600",
        "rx 5700",
        "rx 6400",
        "rx 6500",
        "rx 6600",
        "rx 6650",
        "rx 6700",
        "rx 6750",
        "rx 6800",
        "rx 6900",
        "rx 6950",
        "rx 7600",
        "rx 7700",
        "rx 7800",
        "rx 7900",
        "rx 9060",
        "rx 9070",
        "radeon pro",
        "radeon vii",
        "firepro",
        "radeon instinct",
        "instinct mi",
        "radeon hd 5",
        "radeon hd 6",
        "radeon hd 7",
        "radeon hd 8",
        "radeon r5 2",
        "radeon r7 2",
        "radeon r7 3",
        "radeon r9 2",
        "radeon r9 3",
        "radeon r9 m",
        "radeon r7 m",
        "radeon hd 77",
        "radeon hd 78",
        "radeon hd 79",
        "rx vega 56",
        "rx vega 64",
        "vega 56",
        "vega 64",
    )
    if any(m in name for m in amd_discrete):
        return True
    # PCI says AMD but name is not an allowlisted discrete product → treat as CPU-safe.
    return False


def _is_windows_discrete_amd_or_nvidia(gpu: dict[str, Any] | str) -> bool:
    """True only for discrete NVIDIA / AMD GPUs (not Intel iGPU / APU graphics).

    Multi-signal (closest to 100% without a living silicon DB update loop):
    1. PCI device-ID denylist for known AMD APUs (structural)
    2. PCI device-ID allowlist for known AMD discrete chips
    3. NVIDIA VEN_10DE / name markers
    4. Marketing-name allow/deny (OEM strings)
    Ambiguous / unknown → False (CPU path). Prefer a rare CPU miss over a DML hang.
    Escape hatch: ``scubiee setup --profile dml``.
    """
    if _is_windows_intel_or_igpu_denied(gpu):
        return False
    if _is_windows_nvidia_discrete(gpu):
        return True
    if _is_windows_amd_discrete(gpu):
        return True
    return False


def _windows_discrete_gpu_candidates(gpus: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    return [
        (i, g)
        for i, g in enumerate(gpus or [])
        if isinstance(g, dict) and _is_windows_discrete_amd_or_nvidia(g)
    ]


def _windows_d3d12_gpus() -> list[dict[str, Any]]:
    """Best-effort Win32_VideoController list via PowerShell (no extra deps)."""
    if platform.system() != "Windows":
        return []
    ps = (
        "Get-CimInstance Win32_VideoController | "
        "Select-Object Name, AdapterRAM, DriverVersion, PNPDeviceID, AdapterCompatibility | "
        "ConvertTo-Json -Compress"
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
            out.append(
                {
                    "name": name,
                    "adapter_ram": ram,
                    "driver": row.get("DriverVersion"),
                    "pnp_device_id": str(row.get("PNPDeviceID") or ""),
                    "adapter_compatibility": str(row.get("AdapterCompatibility") or ""),
                }
            )
        return out
    except Exception:  # noqa: BLE001
        return []


def detect_hardware() -> dict[str, Any]:
    gpus = _windows_d3d12_gpus()
    nvidia = _has_nvidia()
    # Prefer discrete AMD/NVIDIA adapters for DML device_id
    dml_id = 0
    discrete = _windows_discrete_gpu_candidates(gpus)
    if discrete:
        scored: list[tuple[int, int]] = []
        for i, g in discrete:
            score = int(g.get("adapter_ram") or 0)
            name = _windows_gpu_name(g)
            if "rtx" in name or "rx 7" in name or "rx 8" in name or "rx 9" in name:
                score += 10**12
            scored.append((score, i))
        scored.sort(reverse=True)
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
        # Only true when an allowlisted discrete adapter was found — never bare nvidia-smi.
        "windows_discrete_amd_nvidia": bool(discrete),
    }


def recommend_profile(detected: dict[str, Any] | None = None) -> AccelProfile:
    d = detected or detect_hardware()
    # Windows: DirectML only when a discrete AMD/NVIDIA adapter is identified.
    # Never select DML from a bare nvidia-smi / ORT hint alone (device_id may be iGPU).
    if d.get("os") == "Windows":
        gpus = [g for g in (d.get("gpus") or []) if isinstance(g, dict)]
        discrete = _windows_discrete_gpu_candidates(gpus)
        if discrete:
            device_id = int(d.get("suggested_dml_device_id") or 0)
            best = max(
                discrete,
                key=lambda item: int(item[1].get("adapter_ram") or 0),
            )
            device_id = best[0]
            vendor = "NVIDIA/AMD"
            names = " ".join(_windows_gpu_name(g) for _, g in discrete)
            if any(
                m in names
                for m in ("nvidia", "geforce", "rtx", "gtx", "quadro", "tesla", "titan")
            ):
                vendor = "NVIDIA"
            elif "radeon" in names or "amd" in names or "firepro" in names:
                vendor = "AMD"
            return AccelProfile(
                profile="dml",
                provider="DmlExecutionProvider",
                device_id=device_id,
                batch_size=BATCH_PREFER,
                reason=(
                    f"Windows discrete {vendor} GPU via DirectML "
                    "(Intel iGPU / APU graphics use CPU instead)"
                ),
                detected=d,
            )
    # Linux NVIDIA: use CUDA (DLL locking is not an issue on Linux)
    if d.get("nvidia") and d.get("os") == "Linux":
        return AccelProfile(
            profile="cuda",
            provider="CUDAExecutionProvider",
            device_id=0,
            batch_size=BATCH_PREFER,
            reason="Linux NVIDIA GPU detected — use onnxruntime-gpu + FastEmbed",
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
    # Final fallback — but never allow CPU-only on Apple Silicon (has Metal GPU).
    # Only use the host Darwin safety net when `detected` omitted os or said Darwin.
    # Explicit Linux/Windows mocks must not flip to MLX just because the host is an M-series Mac.
    import platform as _platform

    detected_os = str(d.get("os") or "").strip()
    if detected_os in {"", "Darwin"}:
        if _platform.system() == "Darwin" and _platform.machine() in ("arm64", "aarch64"):
            # Force MLX even if earlier detection failed (Apple Silicon always has Metal)
            return AccelProfile(
                profile="mlx",
                provider="MLX",
                backend="mlx",
                device_id=0,
                batch_size=24,
                reason="Apple Silicon GPU via MLX FP16 (fallback — detection may have failed)",
                detected=d,
            )
    return AccelProfile(
        profile="cpu",
        provider="CPUExecutionProvider",
        device_id=0,
        batch_size=BATCH_PREFER,
        reason=(
            "No discrete AMD/NVIDIA GPU — FastEmbed CPU (multi-core). "
            "On Windows, Intel iGPU / APU graphics are ignored for DirectML."
            if d.get("os") == "Windows"
            else "No usable GPU accelerator — FastEmbed CPU (multi-core)"
        ),
        detected=d,
    )


def ort_packages_for(profile: str) -> list[str]:
    if profile == "cuda":
        return ["onnxruntime-gpu>=1.17,<1.25"]
    if profile == "dml":
        return ["onnxruntime-directml>=1.17,<1.25"]
    if profile == "mlx":
        return ["onnxruntime>=1.17,<1.25"]
    return ["onnxruntime>=1.17,<1.25"]


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
    uv = shutil.which("uv")
    if uv:
        cmd = [
            uv,
            "pip",
            "install",
            "--python",
            sys.executable,
            "--quiet",
        ]
    else:
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
    if rc and uv:
        # uv can fail on Windows when DLLs are locked (e.g. indexing still running).
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
    uv = shutil.which("uv")
    if uv:
        cmd = [uv, "pip", "uninstall", "--python", sys.executable, "-y", *pkgs]
    else:
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


def _site_package_roots() -> list[Path]:
    roots: list[Path] = []
    try:
        import site

        for item in list(site.getsitepackages() or []) + [site.getusersitepackages()]:
            if item:
                roots.append(Path(item))
    except Exception:  # noqa: BLE001
        pass
    for item in sys.path:
        if item and str(item).replace("\\", "/").rstrip("/").endswith("site-packages"):
            roots.append(Path(item))
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def remove_stale_ort_tree() -> list[str]:
    """Delete leftover onnxruntime dirs after pip uninstall of conflicting wheels.

    Windows often leaves a namespace folder (``capi/`` without ``__init__.py``)
    so ``import onnxruntime`` succeeds but ``SessionOptions`` is missing.
    """
    _purge_ort_modules()
    removed: list[str] = []
    for root in _site_package_roots():
        leftover = root / "onnxruntime"
        if leftover.exists():
            shutil.rmtree(leftover, ignore_errors=True)
            if not leftover.exists():
                removed.append(str(leftover))
    return removed


def _ort_session_ok() -> bool:
    _purge_ort_modules()
    try:
        import onnxruntime as ort  # type: ignore
    except Exception:  # noqa: BLE001
        return False
    return hasattr(ort, "SessionOptions") and hasattr(ort, "get_available_providers")


def _ort_profile_ready(profile: str) -> bool:
    if profile == "mlx":
        return True
    if not _ort_session_ok():
        return False
    providers = ort_available_providers()
    want = {
        "cuda": "CUDAExecutionProvider",
        "dml": "DmlExecutionProvider",
        "coreml": "CoreMLExecutionProvider",
        "cpu": "CPUExecutionProvider",
    }.get(profile)
    return bool(want and want in providers)


def _install_ort_wheel(profile: str, progress: Any | None = None) -> None:
    """Install the correct ORT wheel for the detected profile.

    ORT wheels conflict — only one can be installed at a time:
    - onnxruntime (CPU + CoreML on Mac)
    - onnxruntime-directml (Windows GPU — NVIDIA, AMD, Intel)
    - onnxruntime-gpu (Linux NVIDIA CUDA)

    On Windows with DirectML, the wheel is already installed from base deps
    (pyproject.toml includes onnxruntime-directml for win32). This function
    mainly handles Linux CUDA and edge cases.
    """
    if profile == "mlx":
        return
    _purge_ort_modules()
    if _ort_profile_ready(profile):
        if progress is not None:
            progress.set(55, "GPU/CPU engine already installed")
        return
    all_ort = ["onnxruntime", "onnxruntime-gpu", "onnxruntime-directml"]
    pip_uninstall(all_ort, progress=progress)
    if platform.system() == "Windows":
        import site
        import shutil

        for sp in site.getsitepackages():
            sp_path = Path(sp)
            if sp_path.is_dir():
                for broken in sp_path.glob("~*"):
                    try:
                        if broken.is_dir():
                            shutil.rmtree(broken, ignore_errors=True)
                        else:
                            broken.unlink(missing_ok=True)
                    except Exception:  # noqa: BLE001
                        pass
    remove_stale_ort_tree()
    spec = ort_packages_for(profile)[0]
    try:
        pip_install(
            [spec],
            progress=progress,
            start_pct=32,
            end_pct=54,
            phase="Installing GPU/CPU engine",
            force_reinstall=False,
        )
    except subprocess.CalledProcessError:
        _purge_ort_modules()
        pip_install(
            [spec],
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
    remove_stale_ort_tree()
    pip_install(
        [spec],
        progress=progress,
        start_pct=54,
        end_pct=55,
        phase="Retrying GPU/CPU engine",
        force_reinstall=True,
        upgrade=True,
    )
    _purge_ort_modules()
    if not _ort_session_ok():
        raise RuntimeError(
            "onnxruntime imported without SessionOptions (broken leftover install). "
            "Close other Python processes and re-run `scubiee setup --repair`."
        )
    if profile in {"cuda", "dml", "coreml"} and not _ort_profile_ready(profile):
        have = ort_available_providers()
        raise RuntimeError(
            f"{ort_packages_for(profile)[0]} is installed but "
            f"{profile} EP is missing (providers={have}). "
            "Close other Python/ctx processes and re-run `scubiee setup --repair`."
        )


def _align_profile_to_ort(profile: AccelProfile, progress: Any | None = None) -> None:
    """Ensure the saved profile matches an EP this ORT wheel exposes."""
    if profile.profile in {"mlx", "cpu"}:
        return
    if _ort_profile_ready(profile.profile):
        return
    have = ort_available_providers()
    # On Windows, if we just swapped ORT wheels in this session, the new
    # provider won't be visible until next process. Save the GPU profile
    # WITHOUT calibrating — next run will calibrate at full GPU speed.
    if platform.system() == "Windows" and profile.profile == "dml":
        if progress is not None:
            progress.set(55, "DirectML installed — will calibrate on next run")
        else:
            print(
                "[accel] DirectML wheel installed but not visible in this session. "
                "Profile saved as dml — next ctx command will use GPU.",
                file=sys.stderr,
                flush=True,
            )
        # Mark that calibration is pending but keep the dml profile
        profile._dml_pending = True  # type: ignore[attr-defined]
        return
    msg = (
        f"{profile.provider} is not in this onnxruntime wheel "
        f"(providers={have}). "
        f"Re-run `scubiee setup --repair` to install "
        f"{ort_packages_for(profile.profile)[0]}."
    )
    if profile.profile == "cuda":
        raise RuntimeError(msg)
    if profile.profile == "dml":
        # Non-Windows only (Windows keeps dml + _dml_pending above).
        if progress is not None:
            progress.set(55, "DirectML unavailable — using CPU")
        else:
            print(f"[accel] {msg} — CPU fallback", file=sys.stderr, flush=True)
        profile.profile = "cpu"
        profile.provider = "CPUExecutionProvider"
        profile.reason = msg
        return
    if progress is not None:
        progress.set(55, "GPU wheel missing — using CPU")
    else:
        print(f"[accel] {msg} — CPU fallback", file=sys.stderr, flush=True)
    profile.profile = "cpu"
    profile.provider = "CPUExecutionProvider"
    profile.reason = msg


def install_profile_packages(profile: str, progress: Any | None = None) -> None:
    """Install matching ORT wheel first, then FastEmbed (avoids CPU ORT shadowing DML)."""
    if profile != "mlx":
        _install_ort_wheel(profile, progress=progress)
    runtime = list(FASTEMBED_RUNTIME_DEPS)
    if profile == "mlx":
        runtime.append("mlx>=0.22")
    needed_runtime = [spec for spec in runtime if not _requirement_satisfied(spec)]
    if needed_runtime:
        pip_install(
            needed_runtime,
            progress=progress,
            start_pct=18,
            end_pct=28,
            phase="Installing embedding runtime",
        )
    if not _requirement_satisfied("fastembed>=0.4"):
        pip_install(
            ["fastembed>=0.4"],
            progress=progress,
            start_pct=28,
            end_pct=32,
            phase="Installing FastEmbed",
            no_deps=True,
        )
    elif progress is not None:
        progress.set(32, "Embedding runtime already installed")
    if profile == "mlx":
        _install_ort_wheel(profile, progress=progress)


def _ensure_cuda_dll_paths() -> None:
    """Auto-discover CUDA/cuDNN DLLs for Linux CUDA setups.

    On Linux with onnxruntime-gpu, CUDA DLLs may be in non-standard locations
    (conda env, pip nvidia packages, etc.). This adds them to LD_LIBRARY_PATH.
    On Windows, DirectML is used instead of CUDA so this is a no-op.
    """
    if platform.system() == "Windows":
        return  # Windows uses DirectML, no CUDA DLL hunting needed
    try:
        import importlib.util

        spec = importlib.util.find_spec("onnxruntime")
        if spec is None or spec.origin is None:
            return
        ort_dir = Path(spec.origin).parent
        # Check nvidia pip packages (nvidia-cublas-cu12, nvidia-cudnn-cu12)
        site_packages = ort_dir.parent
        nvidia_pkg_dir = site_packages / "nvidia"
        if nvidia_pkg_dir.is_dir():
            lib_dirs: list[str] = []
            for sub in ("cublas", "cudnn", "cuda_runtime", "cufft", "curand", "cusolver", "cusparse"):
                lib_dir = nvidia_pkg_dir / sub / "lib"
                if lib_dir.is_dir():
                    lib_dirs.append(str(lib_dir.resolve()))
            if lib_dirs:
                existing = os.environ.get("LD_LIBRARY_PATH", "")
                additions = [d for d in lib_dirs if d not in existing]
                if additions:
                    os.environ["LD_LIBRARY_PATH"] = ":".join(additions) + ":" + existing
    except Exception:  # noqa: BLE001
        pass


def ort_available_providers() -> list[str]:
    _ensure_cuda_dll_paths()
    try:
        import onnxruntime as ort  # type: ignore

        if not hasattr(ort, "SessionOptions") or not hasattr(ort, "get_available_providers"):
            return []
        return list(ort.get_available_providers())
    except Exception:  # noqa: BLE001
        return []


def validate_dml_provider() -> bool:
    """Runtime guard: verify GPU provider is available; auto-repair if not.

    Called at daemon/engine startup when the saved profile is "dml" or "cuda".
    If the expected GPU execution provider is missing (e.g. onnxruntime got
    upgraded to a version without DML), attempts automatic repair by
    reinstalling the correct ORT wheel. Only falls back to CPU as a last
    resort after repair fails.

    Returns True if GPU provider is available (or was successfully repaired).
    """
    saved = load_accel()
    if saved is None or saved.profile in {"cpu", "mlx", "coreml"}:
        return True
    if saved.profile not in {"dml", "cuda"}:
        return True

    want_provider = {
        "dml": "DmlExecutionProvider",
        "cuda": "CUDAExecutionProvider",
    }[saved.profile]

    providers = ort_available_providers()
    if want_provider in providers:
        return True

    # GPU provider missing. Attempt auto-repair before giving up.
    # Common cause: fastembed pulled a newer onnxruntime that shadows
    # onnxruntime-directml. Fix: reinstall the correct ORT wheel.
    print(
        f"[scubiee] {want_provider} missing (have: {providers}). "
        f"Attempting auto-repair for {saved.profile} profile...",
        file=sys.stderr,
        flush=True,
    )
    try:
        _install_ort_wheel(saved.profile)
        _purge_ort_modules()
        providers = ort_available_providers()
        if want_provider in providers:
            print(
                f"[scubiee] Auto-repair successful: {want_provider} restored.",
                file=sys.stderr,
                flush=True,
            )
            return True
    except Exception as exc:  # noqa: BLE001
        print(
            f"[scubiee] Auto-repair failed: {exc}",
            file=sys.stderr,
            flush=True,
        )

    # Repair failed. Emit clear error, do NOT silently fall back to CPU.
    print(
        f"[scubiee] ERROR: {saved.profile} profile but {want_provider} "
        f"still missing after repair. GPU acceleration is broken.",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"  Fix: scubiee setup --repair",
        file=sys.stderr,
        flush=True,
    )
    return False


def profile_packages_satisfied(profile: AccelProfile) -> bool:
    """True if saved accel matches target and the runtime already exposes it."""
    if not _requirement_satisfied("fastembed>=0.4"):
        return False
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


def saved_accel_needs_reconfigure(existing: AccelProfile) -> bool:
    """True when accel.json must not skip ``setup`` / ``configure``."""
    if not _requirement_satisfied("fastembed>=0.4"):
        return True
    if not coderank_fp16_onnx_ready():
        return True
    detected = existing.detected if isinstance(existing.detected, dict) else detect_hardware()
    recommended = recommend_profile(detected)
    if existing.profile == "cpu" and recommended.profile != "cpu":
        return True
    if existing.profile != recommended.profile and recommended.profile != "cpu":
        return True
    if existing.profile in {"dml", "cuda", "coreml"}:
        return not _ort_profile_ready(existing.profile)
    if existing.profile == "mlx" or existing.backend == "mlx":
        return not _mlx_importable()
    return False


def setup_finish_message(*, reused_runtime: bool = False) -> str:
    """Honest one-line setup outcome (never claim GPU when profile is CPU)."""
    prof = load_accel()
    if prof is None:
        return "Ready. Next: scubiee init ."
    detected = prof.detected if isinstance(prof.detected, dict) else {}
    recommended = recommend_profile(detected)
    tps = prof.texts_per_sec
    if prof.profile == "cpu" and recommended.profile != "cpu":
        gpu = recommended.profile.upper()
        speed = f" (~{tps:.1f} t/s)" if tps is not None else ""
        return (
            f"Setup finished on CPU{speed}, not {gpu}. "
            "Run: scubiee setup --repair"
        )
    if reused_runtime:
        return f"Ready (reused {prof.profile} runtime + model cache). Next: scubiee init ."
    if prof.profile != "cpu":
        speed = f", ~{tps:.1f} t/s" if tps is not None else ""
        return f"Ready ({prof.profile}{speed}). Next: scubiee init ."
    speed = f" (~{tps:.1f} t/s)" if tps is not None else ""
    return f"Ready (CPU{speed}). Next: scubiee init ."


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
    available AND can create a working session. ORT may list the provider but
    fail at session time if DLLs are missing. We do a real inference probe.
    """
    if profile.profile != "cuda":
        return
    _ensure_cuda_dll_paths()
    available = ort_available_providers()
    if not available:
        return

    cuda_listed = "CUDAExecutionProvider" in available

    # Even if CUDA EP is listed, probe actual session creation
    cuda_works = False
    if cuda_listed:
        try:
            import numpy as np
            import onnxruntime as ort

            # Create a trivial ONNX model in-memory to test CUDA session
            # Use ORT's own session with CUDA provider to verify DLL loading
            sess_options = ort.SessionOptions()
            sess_options.log_severity_level = 4  # suppress warnings during probe
            # Try creating a session with a known model to verify CUDA actually works
            from huggingface_hub import try_to_load_from_cache

            model_path = try_to_load_from_cache(
                CODERANK_HF_ONNX, "model_optimized.onnx"
            )
            if model_path and Path(model_path).is_file():
                sess = ort.InferenceSession(
                    str(model_path),
                    sess_options=sess_options,
                    providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
                )
                active = sess.get_providers()
                cuda_works = "CUDAExecutionProvider" in active
                del sess
            else:
                # No cached model yet — trust provider list for now,
                # calibration will catch it later
                cuda_works = True
        except Exception:  # noqa: BLE001
            cuda_works = False

    if cuda_listed and cuda_works:
        return

    # CUDA EP missing or non-functional — diagnose why
    hints: list[str] = []
    if not cuda_listed:
        reason_prefix = "CUDAExecutionProvider not listed"
    else:
        reason_prefix = "CUDAExecutionProvider listed but session creation failed (DLL load error)"

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
        hints.append(
            "For CUDA 12.x try: pip install onnxruntime-gpu "
            "--extra-index-url https://aiinfra.pkgs.visualstudio.com/PublicPackages/"
            "_packaging/onnxruntime-cuda-12/pypi/simple/"
        )

    hint_text = " ".join(hints) if hints else "Check CUDA toolkit installation."
    msg = (
        f"NVIDIA GPU detected but {reason_prefix} "
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
        print("[accel] Falling back to CPU. Run `scubiee setup --repair` after fixing CUDA.",
              file=sys.stderr, flush=True)
    else:
        progress.set(55, "CUDA unavailable — using CPU (check CUDA toolkit)")

    profile.profile = "cpu"
    profile.provider = "CPUExecutionProvider"
    profile.reason = msg
    profile.cuda_fallback_hint = hint_text


def _do_calibration(profile: AccelProfile, progress: Any | None = None) -> None:
    """Run batch-size calibration; DML/CUDA failures time out into CPU."""
    if profile.profile == "mlx":
        calibration = _calibrate_mlx(profile)
        _apply_calibration_result(profile, calibration, progress=progress)
        return

    if profile.profile in {"dml", "cuda"}:
        try:
            _probe_gpu_embed(profile, timeout_s=GPU_PROBE_TIMEOUT_S)
            calibration = _calibrate_with_timeout(
                profile, timeout_s=CALIBRATE_TIMEOUT_S
            )
            if not calibration.get("ok"):
                raise RuntimeError(
                    calibration.get("errors")
                    or calibration.get("error")
                    or "calibration produced no scores"
                )
            _apply_calibration_result(profile, calibration, progress=progress)
            return
        except Exception as exc:  # noqa: BLE001
            _fallback_to_cpu_profile(
                profile,
                f"{profile.profile} calibration failed ({exc})",
                progress=progress,
            )

    # CPU path (native or after GPU fallback)
    try:
        calibration = _calibrate_with_timeout(
            profile, timeout_s=CPU_CALIBRATE_TIMEOUT_S
        )
        if not calibration.get("ok"):
            raise RuntimeError(
                calibration.get("errors")
                or calibration.get("error")
                or "CPU calibration produced no scores"
            )
        _apply_calibration_result(profile, calibration, progress=progress)
    except Exception as exc:  # noqa: BLE001
        from pipeline.coreml_mac import mac_gpu_only

        if profile.profile == "coreml" and mac_gpu_only():
            raise RuntimeError(
                f"CoreML GPU calibration failed: {exc}. Refusing CPU fallback."
            ) from exc
        # Last resort: keep going with safe defaults so setup/init can continue.
        if progress is not None:
            progress.set(88, "Calibration skipped — using safe CPU defaults")
        else:
            print(
                f"[accel] calibration failed ({exc}); using safe defaults",
                file=sys.stderr,
                flush=True,
            )
        if profile.profile != "cpu":
            _fallback_to_cpu_profile(profile, str(exc), progress=None)
        profile.batch_size = BATCH_PREFER
        profile.texts_per_sec = None
        profile.meets_target = None
        profile.batch_calibration = {
            "ok": False,
            "winner": BATCH_PREFER,
            "error": str(exc),
            "reason": "safe defaults after calibration failure",
        }

    if (
        profile.profile == "coreml"
        and (profile.texts_per_sec or 0) < TARGET_TPS
        and profile.batch_calibration.get("ok")
    ):
        # Existing CoreML→CPU slow-path (unchanged behaviour)
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
        _fallback_to_cpu_profile(profile, msg, progress=None)
        calibration = _calibrate_with_timeout(
            profile, timeout_s=CPU_CALIBRATE_TIMEOUT_S
        )
        _apply_calibration_result(profile, calibration, progress=progress)
        profile.batch_calibration = {
            **(profile.batch_calibration or {}),
            "coreml_rejected_tps": coreml_tps,
        }

    if not profile.meets_target and progress is None and profile.texts_per_sec is not None:
        print(
            "[accel] WARNING: below 10 t/s target — indexing will still work; "
            "consider a stronger GPU or shorter embed recipe.",
            file=sys.stderr,
            flush=True,
        )


def _apply_calibration_result(
    profile: AccelProfile,
    calibration: dict[str, Any],
    *,
    progress: Any | None = None,
) -> None:
    profile.batch_size = int(calibration.get("winner") or BATCH_PREFER)
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


def _run_with_timeout(fn: Callable[[], Any], timeout_s: float, *, label: str) -> Any:
    """Run ``fn`` in a daemon thread; raise TimeoutError if it exceeds ``timeout_s``."""
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FuturesTimeout

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(fn)
        try:
            return fut.result(timeout=max(1.0, float(timeout_s)))
        except FuturesTimeout as exc:
            raise TimeoutError(
                f"{label} exceeded {timeout_s:.0f}s — falling back"
            ) from exc


def _probe_gpu_embed(profile: AccelProfile, *, timeout_s: float) -> None:
    """Fail fast if DML/CUDA cannot embed a single string."""
    if profile.profile not in {"dml", "cuda"}:
        return

    def _once() -> None:
        register_coderank()
        from fastembed import TextEmbedding

        model = TextEmbedding(
            model_name=profile.model,
            threads=1,
            providers=profile.providers(),
            lazy_load=True,
        )
        list(model.embed(["scubiee gpu probe"], batch_size=1, parallel=None))

    _run_with_timeout(_once, timeout_s, label=f"{profile.profile} probe")


def _calibrate_with_timeout(
    profile: AccelProfile, *, timeout_s: float
) -> dict[str, Any]:
    return _run_with_timeout(
        lambda: calibrate_batch(profile),
        timeout_s,
        label=f"{profile.profile} calibration",
    )


def _fallback_to_cpu_profile(
    profile: AccelProfile,
    reason: str,
    *,
    progress: Any | None = None,
) -> None:
    """Mutate profile in-place to CPU so setup/init can continue.

    Never demotes Apple Silicon MacBooks to CPU-only — they have a Metal GPU.
    Prefer MLX when available; otherwise leave the existing Mac GPU profile.
    """
    # MLX is already the correct Mac GPU path — do not overwrite.
    if profile.profile == "mlx" or profile.backend == "mlx":
        return

    detected = profile.detected if isinstance(profile.detected, dict) else {}
    apple = _is_apple_silicon(detected) or (
        platform.system() == "Darwin"
        and platform.machine().lower() in {"arm64", "aarch64"}
    )
    if apple and not _env_disables_mlx():
        if _mlx_importable():
            from pipeline.memory_budget import bootstrap_budget

            if progress is not None:
                progress.set(87, "Keeping Apple Silicon GPU (MLX)")
            else:
                print(
                    f"[accel] {reason} — Apple Silicon keeps MLX Metal GPU (not CPU)",
                    file=sys.stderr,
                    flush=True,
                )
            profile.profile = "mlx"
            profile.provider = "MLX"
            profile.backend = "mlx"
            profile.device_id = 0
            profile.batch_size = int(profile.batch_size or bootstrap_budget().mlx_batch)
            profile.reason = (
                f"Apple Silicon Metal GPU (MLX) — refused CPU demotion ({reason})"
            )
            return
        # mlx package missing: keep CoreML Metal rather than FastEmbed CPU
        if profile.profile == "coreml":
            if progress is not None:
                progress.set(87, "Keeping CoreML Metal GPU")
            profile.reason = (
                f"Apple Silicon CoreML Metal — refused CPU demotion ({reason})"
            )
            return

    if progress is not None:
        progress.set(87, "GPU path failed — switching to CPU")
    else:
        print(f"[accel] {reason} — using CPU", file=sys.stderr, flush=True)
    profile.profile = "cpu"
    profile.provider = "CPUExecutionProvider"
    profile.backend = "fastembed"
    profile.device_id = 0
    profile.model = CODERANK_MODEL
    profile.reason = reason
    profile.meets_target = None


def _saved_dml_still_has_discrete_gpu(profile: AccelProfile) -> bool:
    """True when a saved DML profile still looks like discrete AMD/NVIDIA."""
    detected = profile.detected if isinstance(profile.detected, dict) else {}
    if detected.get("nvidia") or detected.get("windows_discrete_amd_nvidia"):
        return True
    gpus = [g for g in (detected.get("gpus") or []) if isinstance(g, dict)]
    return bool(_windows_discrete_gpu_candidates(gpus))


def _demote_stale_dml_profile(profile: AccelProfile) -> AccelProfile:
    """Rewrite leftover DML accel.json from older installs (Intel iGPU hang)."""
    from dataclasses import replace

    demoted = replace(
        profile,
        profile="cpu",
        provider="CPUExecutionProvider",
        backend="fastembed",
        device_id=0,
        reason=(
            "Saved DirectML profile demoted to CPU — no discrete AMD/NVIDIA GPU "
            "in accel.json (re-run scubiee setup --repair to re-detect)."
        ),
        batch_calibration={
            **(profile.batch_calibration or {}),
            "demoted_from": "dml",
            "ok": True,
            "winner": int(profile.batch_size or BATCH_PREFER),
            "reason": "stale_dml_demoted",
        },
    )
    try:
        save_accel(demoted)
    except Exception:  # noqa: BLE001
        pass
    return demoted


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
        # If DML was just installed but not visible, download model with CPU provider
        if getattr(profile, "_dml_pending", False):
            from dataclasses import replace

            cpu_profile = replace(profile, profile="cpu", provider="CPUExecutionProvider")
            ensure_coderank_model(cpu_profile, progress=progress)
        else:
            ensure_coderank_model(profile, progress=progress)
    if bench:
        # Skip calibration if DML was just installed but not yet visible
        # (will calibrate on next run when DirectML is properly loaded)
        if getattr(profile, "_dml_pending", False):
            if progress is not None:
                progress.set(92, "Skipping calibration — DirectML ready on next run")
            profile.batch_size = BATCH_PREFER
            profile.texts_per_sec = None
            profile.meets_target = False
            profile.batch_calibration = {
                "ok": True,
                "winner": BATCH_PREFER,
                "texts_per_sec": None,
                "reason": "deferred — DirectML not yet visible in this process",
            }
        else:
            if progress is not None:
                progress.set(86, "Calibrating speed")
            try:
                _do_calibration(profile, progress=progress)
            except Exception as exc:  # noqa: BLE001
                from pipeline.coreml_mac import mac_gpu_only

                if profile.profile == "coreml" and mac_gpu_only():
                    raise RuntimeError(
                        f"CoreML GPU calibration failed: {exc}. Refusing CPU fallback."
                    ) from exc
                if profile.profile in {"dml", "cuda"}:
                    _fallback_to_cpu_profile(
                        profile,
                        f"{profile.profile} calibration crashed ({exc})",
                        progress=progress,
                    )
                    try:
                        _do_calibration(profile, progress=progress)
                    except Exception as cpu_exc:  # noqa: BLE001
                        if progress is None:
                            print(
                                f"[accel] CPU calibration also failed: {cpu_exc}",
                                file=sys.stderr,
                                flush=True,
                            )
                        profile.batch_size = BATCH_PREFER
                        profile.texts_per_sec = None
                        profile.meets_target = None
                        profile.batch_calibration = {
                            "ok": False,
                            "winner": BATCH_PREFER,
                            "error": str(cpu_exc),
                            "reason": "safe defaults after GPU+CPU calibration failure",
                        }
                else:
                    if progress is None:
                        print(
                            f"[accel] batch calibration failed: {exc}",
                            file=sys.stderr,
                            flush=True,
                        )
                    profile.texts_per_sec = None
                    profile.meets_target = None
                    profile.batch_calibration = {"ok": False, "error": str(exc)}
                    if profile.profile != "cpu":
                        profile.batch_size = int(profile.batch_size or BATCH_PREFER)
                    else:
                        profile.batch_size = BATCH_PREFER


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
        print(f"[accel] wrote {accel_path()}", file=sys.stderr, flush=True)
    return profile


def default_fastembed_cache_root() -> Path:
    """FastEmbed model cache without importing fastembed (safe during first ``setup``)."""
    for key in ("FASTEMBED_CACHE", "FASTEMBED_CACHE_PATH"):
        raw = os.environ.get(key)
        if raw:
            return Path(raw)
    return Path.home() / ".cache" / "fastembed"


def fastembed_cache_root() -> Path:
    try:
        from fastembed.common.utils import define_cache_dir

        return Path(define_cache_dir())
    except ImportError:
        return default_fastembed_cache_root()


def _coderank_hf_cache_name() -> str:
    return f"models--{CODERANK_HF_ONNX.replace('/', '--')}"


def list_coderank_snapshot_dirs(cache_root: Path | None = None) -> list[Path]:
    root = cache_root or fastembed_cache_root()
    snaps = root / _coderank_hf_cache_name() / "snapshots"
    if not snaps.is_dir():
        return []
    out = [p for p in snaps.iterdir() if p.is_dir()]
    out.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return out


def coderank_fp16_onnx_ready(cache_root: Path | None = None) -> bool:
    from pipeline.coreml_mac import find_coderank_onnx

    root = cache_root or fastembed_cache_root()
    found = find_coderank_onnx(root)
    if found is None or not found.is_file():
        return False
    return found.stat().st_size >= CODERANK_FP16_MIN_BYTES


def _setup_download_env() -> dict[str, str | None]:
    names = (
        "HF_HUB_DISABLE_PROGRESS_BARS",
        "HF_HUB_DISABLE_SYMLINKS_WARNING",
        "HF_HUB_DISABLE_TELEMETRY",
        "TQDM_DISABLE",
    )
    prev = {name: os.environ.get(name) for name in names}
    os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    os.environ["TQDM_DISABLE"] = "1"
    # Silence the huggingface_hub "unauthenticated requests" warning
    import logging
    logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
    return prev


def _restore_env(prev: dict[str, str | None]) -> None:
    for name, value in prev.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _download_coderank_source_onnx(cache_root: Path) -> Path:
    from huggingface_hub import snapshot_download
    from huggingface_hub.utils import disable_progress_bars, enable_progress_bars

    prev = _setup_download_env()
    disable_progress_bars()
    try:
        snapshot_download(
            repo_id=CODERANK_HF_ONNX,
            cache_dir=str(cache_root),
            allow_patterns=[
                "config.json",
                "tokenizer.json",
                "tokenizer_config.json",
                "special_tokens_map.json",
                "vocab.txt",
                CODERANK_FP32_ONNX_FILE,
            ],
        )
    finally:
        enable_progress_bars()
        _restore_env(prev)
    for snap in list_coderank_snapshot_dirs(cache_root):
        fp32 = snap / CODERANK_FP32_ONNX_FILE
        if fp32.is_file() and fp32.stat().st_size > 100_000_000:
            return fp32
    raise RuntimeError(
        "CodeRank weights (onnx/model.onnx) did not download completely. "
        "Check disk space and network, then run: scubiee setup --repair"
    )


def _convert_coderank_fp32_onnx_to_fp16(src: Path, dest: Path) -> None:
    import warnings

    try:
        import onnx  # noqa: F401
    except ImportError:
        pip_install(["onnx>=1.16"], phase="Installing ONNX for FP16 conversion")
    import onnx

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".onnx.part")
    model = onnx.load(str(src), load_external_data=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            from onnxruntime.transformers import float16 as ort_fp16

            converted = ort_fp16.convert_float_to_float16(model, keep_io_types=True)
        except Exception:
            from onnxconverter_common import float16 as common_fp16

            converted = common_fp16.convert_float_to_float16(model, keep_io_types=True)
    onnx.save(converted, str(tmp))
    tmp.replace(dest)


def ensure_coderank_fp16_onnx(progress: Any | None = None) -> Path:
    """Ensure FP16 ONNX exists in the FastEmbed cache (convert from HF FP32 if needed)."""
    cache_root = fastembed_cache_root()
    if coderank_fp16_onnx_ready(cache_root):
        from pipeline.coreml_mac import find_coderank_onnx

        found = find_coderank_onnx(cache_root)
        assert found is not None
        if progress is not None:
            progress.set(70, "Embedding model ready (cached)")
        return found

    import threading as _thr
    _dl_stop = _thr.Event()
    def _dl_pulse():
        i = 0
        while not _dl_stop.wait(2.0):
            i += 1
            if progress is not None:
                # Increment pct from 58 toward 63 so the progress bar fills up.
                # Each tick adds 1 to pct (capped at 63 to leave room for convert step).
                pct = 58 + min(i, 5)
                progress.set(pct, f"Downloading model\u2026 ({int(i*2)}s)")
    if progress is not None:
        progress.set(58, "Downloading model\u2026")
        _dl_thread = _thr.Thread(target=_dl_pulse, daemon=True)
        _dl_thread.start()
    else:
        print("[accel] Downloading CodeRank weights (~500 MB)...", file=sys.stderr, flush=True)
    fp32 = _download_coderank_source_onnx(cache_root)
    _dl_stop.set()
    if progress is not None:
        progress.set(64, "Converting to FP16\u2026")
    else:
        print("[accel] Converting to FP16...", file=sys.stderr, flush=True)
    fp16 = fp32.parent / "model_fp16.onnx"
    if fp16.is_file() and fp16.stat().st_size >= CODERANK_FP16_MIN_BYTES:
        if progress is not None:
            progress.set(70, "Step 3/3: FP16 model ready")
        return fp16
    _convert_coderank_fp32_onnx_to_fp16(fp32, fp16)
    if fp16.stat().st_size < CODERANK_FP16_MIN_BYTES:
        fp16.unlink(missing_ok=True)
        raise RuntimeError("CodeRank FP16 conversion produced an incomplete file.")
    if progress is not None:
        progress.set(70, "Step 3/3: FP16 model ready")
    else:
        print("[accel] Step 3/3: FP16 model ready", file=sys.stderr, flush=True)
    return fp16


CODERANK_INT8_ONNX_FILE = "onnx/model_int8.onnx"


def _ensure_coderank_int8(progress: Any | None = None) -> Path | None:
    """Create INT8 quantized model from the FP16/FP32 source for CPU-only profiles.

    INT8 dynamic quantization gives ~1.5x speedup on CPU with VNNI/AMX
    instructions (Intel 10th gen+, AMD Zen3+) and 4x smaller model size.
    Accuracy loss is negligible for code search retrieval.
    """
    # Apple Silicon uses MLX Metal GPU — never degrade to INT8 CPU
    import platform as _plat
    if _plat.system() == "Darwin" and _plat.machine() in ("arm64", "aarch64"):
        return None
    cache_root = fastembed_cache_root()
    snap_dirs = list_coderank_snapshot_dirs(cache_root)
    if not snap_dirs:
        return None
    onnx_dir = snap_dirs[0] / "onnx"
    int8_path = onnx_dir / "model_int8.onnx"
    if int8_path.is_file() and int8_path.stat().st_size > 50_000_000:
        # Already exists and is a reasonable size (>50MB for 137M-param model)
        return int8_path

    # Find the source model (FP16 preferred, FP32 fallback)
    fp16_path = onnx_dir / "model_fp16.onnx"
    fp32_path = onnx_dir / "model.onnx"
    source = fp16_path if fp16_path.is_file() else fp32_path
    if not source.is_file():
        return None

    if progress is not None:
        progress.set(82, "Quantizing model to INT8 for CPU speed")
    else:
        print("[accel] Quantizing CodeRank to INT8 for CPU inference...", file=sys.stderr, flush=True)

    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic

        quantize_dynamic(
            str(source),
            str(int8_path),
            weight_type=QuantType.QInt8,
        )
        size_mb = int8_path.stat().st_size / 1024 / 1024
        if progress is None:
            print(f"[accel] INT8 model ready ({size_mb:.0f} MB)", file=sys.stderr, flush=True)
        return int8_path
    except ImportError:
        # onnxruntime.quantization not available — skip, FP16 still works
        if progress is None:
            print("[accel] INT8 quantization skipped (onnxruntime.quantization not available)", file=sys.stderr, flush=True)
        return None
    except Exception as exc:  # noqa: BLE001
        if progress is None:
            print(f"[accel] INT8 quantization failed: {exc}", file=sys.stderr, flush=True)
        return None


def coderank_int8_onnx_path() -> Path | None:
    """Return the INT8 model path if it exists, else None."""
    cache_root = fastembed_cache_root()
    snap_dirs = list_coderank_snapshot_dirs(cache_root)
    if not snap_dirs:
        return None
    int8_path = snap_dirs[0] / "onnx" / "model_int8.onnx"
    return int8_path if int8_path.is_file() else None


def format_setup_error(exc: BaseException) -> str:
    msg = str(exc).strip()
    if "model_fp16.onnx" in msg and ("NO_SUCHFILE" in msg or "does not exist" in msg.lower()):
        return (
            "CodeRank FP16 weights are missing from the model cache. "
            "Run: scubiee wipe --all --yes  then  scubiee setup --repair"
        )
    if "did not download completely" in msg or "FP16 conversion" in msg:
        return msg
    if "No module named 'fastembed'" in msg or "No module named \"fastembed\"" in msg:
        return (
            "FastEmbed is not installed yet (normal on Windows after `uv tool install`). "
            "Setup will install it automatically — if this persists, run: scubiee setup --repair"
        )
    if "No module named 'PIL'" in msg or "Pillow" in msg:
        return (
            "Missing FastEmbed dependency (Pillow). "
            "Run: uv tool install --force scubiee  then  scubiee setup --repair"
        )
    if "loguru" in msg or "mmh3" in msg or "py_rust_stemmers" in msg:
        return (
            "Missing FastEmbed dependencies. "
            "Run: uv tool install --force scubiee  then  scubiee setup --repair"
        )
    if len(msg) > 240:
        return msg[:237] + "..."
    return msg or exc.__class__.__name__


def _coderank_fp16_description():
    from fastembed.common.model_description import DenseModelDescription, ModelSource

    return DenseModelDescription(
        model=CODERANK_MODEL,
        sources=ModelSource(hf=CODERANK_HF_ONNX),
        dim=768,
        model_file=CODERANK_ONNX_FILE,
        description="CodeRankEmbed FP16 ONNX",
        license="mit",
        size_in_GB=0.27,
        additional_files=[],
    )


def _patch_registered_coderank_to_fp16() -> bool:
    """Replace an in-process FP32 CodeRank registration with FP16 (same model name)."""
    from fastembed import TextEmbedding
    from fastembed.text.custom_text_embedding import CustomTextEmbedding

    desired = _coderank_fp16_description()
    patched = False
    registries: list[list[Any]] = []
    custom = getattr(CustomTextEmbedding, "SUPPORTED_MODELS", None)
    if isinstance(custom, list):
        registries.append(custom)
    for emb_type in getattr(TextEmbedding, "EMBEDDINGS_REGISTRY", ()) or ():
        models = getattr(emb_type, "SUPPORTED_MODELS", None)
        if isinstance(models, list) and models not in registries:
            registries.append(models)
    for models in registries:
        for i, desc in enumerate(models):
            if str(getattr(desc, "model", "")).lower() != CODERANK_MODEL.lower():
                continue
            if getattr(desc, "model_file", None) != CODERANK_ONNX_FILE:
                models[i] = desired
                patched = True
            else:
                patched = True  # already FP16
    return patched


def register_coderank() -> None:
    """Register CodeRank as FP16 ONNX; upgrade any stale FP32 in-process entry."""
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    if _patch_registered_coderank_to_fp16():
        return
    try:
        TextEmbedding.add_custom_model(
            model=CODERANK_MODEL,
            pooling=PoolingType.MEAN,
            normalization=True,
            sources=ModelSource(hf=CODERANK_HF_ONNX),
            dim=768,
            model_file=CODERANK_ONNX_FILE,
            description="CodeRankEmbed FP16 ONNX",
            license="mit",
            size_in_gb=0.27,
        )
    except ValueError as exc:
        if "already registered" not in str(exc).lower():
            raise
        _patch_registered_coderank_to_fp16()


def _ensure_fastembed_import_deps(*, progress: Any | None = None) -> None:
    """FastEmbed needs these at import time; install without pulling CPU onnxruntime."""
    checks: list[tuple[str, str]] = [
        ("PIL", "Pillow>=10.0"),
        ("loguru", "loguru>=0.7.2"),
        ("mmh3", "mmh3>=4.1.0"),
        ("py_rust_stemmers", "py-rust-stemmers>=0.1.0"),
        ("tokenizers", "tokenizers>=0.15"),
    ]
    missing = [spec for mod, spec in checks if not _module_available(mod)]
    if not missing:
        return
    pip_install(
        missing,
        progress=progress,
        start_pct=52,
        end_pct=55,
        phase="Installing FastEmbed dependencies",
    )


def _module_available(name: str) -> bool:
    import importlib.util

    return importlib.util.find_spec(name) is not None


def ensure_coderank_model(
    profile: AccelProfile | None = None,
    progress: Any | None = None,
) -> None:
    """Download/warm CodeRank FP16 ONNX via FastEmbed.

    For CPU-only profiles: also creates an INT8 quantized model (4x smaller,
    ~1.5x faster) if it doesn't already exist. The embedder uses INT8
    automatically when profile=cpu.
    """

    register_coderank()
    _ensure_fastembed_import_deps(progress=progress)
    from fastembed import TextEmbedding

    prof = profile or load_accel() or recommend_profile()
    if getattr(prof, "onnx_file", None) != CODERANK_ONNX_FILE:
        prof.onnx_file = CODERANK_ONNX_FILE
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
    previous = _setup_download_env()
    if progress is None:
        print(
            f"[accel] ensuring CodeRank FP16 model ({CODERANK_HF_ONNX} / {CODERANK_ONNX_FILE}) ...",
            file=sys.stderr,
            flush=True,
        )
    ensure_coderank_fp16_onnx(progress=progress)
    if progress is not None:
        progress.set(72, "Warming up embedding model on accelerator")
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
        _restore_env(previous)
    # For CPU-only profiles: create INT8 quantized model if missing.
    # INT8 is ~4x smaller and ~1.5x faster on CPU (uses VNNI/AMX instructions).
    if prof.profile == "cpu":
        _ensure_coderank_int8(progress=progress)
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
    candidates: tuple[int, ...] | None = None,
    model: Any | None = None,
) -> dict[str, Any]:
    """Measure candidate batches once and persist a smart winner (usually 16).

    CPU profiles use a lighter probe (one batch size, fewer texts) so setup
    does not spend minutes calibrating on slow machines.
    """
    register_coderank()
    from fastembed import TextEmbedding

    if candidates is None:
        if profile.profile == "cpu":
            batch_candidates = CPU_BATCH_CANDIDATES
        else:
            batch_candidates = BATCH_CANDIDATES
    else:
        batch_candidates = candidates

    if n is not None:
        count = int(n)
    elif profile.profile == "cpu":
        count = CPU_BATCH_CALIBRATE_N
    else:
        count = BATCH_CALIBRATE_N
    model_name = profile.model
    static_bs = None
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
    if profile.profile == "cpu" and not scores:
        winner, reason = BATCH_PREFER, "CPU default batch (calibration empty)"
    if profile.profile == "cpu" and len(batch_candidates) == 1 and scores:
        only = int(batch_candidates[0])
        winner, reason = only, f"CPU light calibrate (single candidate batch={only})"
    if profile.profile == "coreml" and static_bs is not None:
        winner = min(int(profile.batch_size or BATCH_PREFER), static_bs)
        reason = f"CoreML static ONNX batch={static_bs}; runtime batch={winner}"
    winner_tps = scores.get(winner)
    if winner_tps is None and static_bs is not None:
        winner_tps = scores.get(int(static_bs))
    elapsed = time.perf_counter() - t_start
    return {
        "ok": bool(scores) or profile.profile == "cpu",
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
        "light_cpu": profile.profile == "cpu",
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

    Apple Silicon: ``scubiee setup`` persists ``profile=mlx`` (FP16). A saved
    CoreML profile is overlaid with MLX when the ``mlx`` package is installed.
    Opt out with ``CTX_EMBED_BACKEND=fastembed`` or ``CTX_MLX=0``.

    Safeguards:
    - Stale DirectML (Intel iGPU) accel.json → demote to CPU (Windows only).
    - Accidental CPU profile on Apple Silicon → promote back to MLX Metal GPU.
    """
    profile = load_accel()
    if profile is None:
        raise RuntimeError("acceleration profile is not configured; run `scubiee setup`")
    if (
        profile.profile == "dml"
        and not (os.environ.get("CTX_FORCE_DML") or "").strip()
        and not _saved_dml_still_has_discrete_gpu(profile)
    ):
        return _demote_stale_dml_profile(profile)

    env = os.environ.get("CTX_EMBED_BACKEND", "").strip().lower()
    # Never leave M-series MacBooks on a CPU-only profile when MLX is available.
    # Explicit CTX_EMBED_BACKEND=mlx is an in-memory overlay only (do not rewrite accel.json).
    if (
        profile.profile == "cpu"
        and env not in {"cpu", "fastembed", "st", "coderank", "mlx"}
        and not _env_disables_mlx()
        and _is_apple_silicon(profile.detected or {})
        and _mlx_importable()
    ):
        from dataclasses import replace

        from pipeline.memory_budget import bootstrap_budget

        promoted = replace(
            profile,
            profile="mlx",
            provider="MLX",
            backend="mlx",
            batch_size=bootstrap_budget().mlx_batch,
            reason=(
                "Apple Silicon Metal GPU (MLX) — restored from accidental CPU profile"
            ),
        )
        try:
            save_accel(promoted)
        except Exception:  # noqa: BLE001
            pass
        return promoted

    want_mlx = env == "mlx" or (profile.profile == "mlx" or profile.backend == "mlx")
    if profile.profile in {"dml", "cuda"} and env != "mlx":
        return profile
    if not want_mlx and not _env_disables_mlx() and _is_apple_silicon(profile.detected or {}):
        # Promote the old CoreML path only. An explicit CPU profile stays CPU
        # only when MLX is disabled/unavailable (handled above).
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

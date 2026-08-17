"""Hardware acceleration probe + install profile for CodeRank FastEmbed.

Profiles (mutually exclusive ORT wheels):
  - cuda  → onnxruntime-gpu
  - dml   → onnxruntime-directml  (Windows AMD/Intel/NVIDIA without CUDA stack)
  - cpu   → onnxruntime

Persists choice to ``~/.context-engine/accel.json``.
"""

from __future__ import annotations

import hashlib
import json
import math
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
    batch_calibration: dict[str, Any] = field(default_factory=dict)
    envelope: dict[str, Any] = field(default_factory=dict)
    hardware_fingerprint: str = ""

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
    hardware_snapshot: dict[str, Any] = detected
    try:
        from pipeline.hardware import ensure_hardware_snapshot

        hardware_snapshot = ensure_hardware_snapshot(force=True)
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
        profile.batch_size = BATCH_PREFER

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
            calibration = calibrate_batch(profile)
            profile.batch_size = int(calibration["winner"])
            profile.texts_per_sec = calibration.get("texts_per_sec")
            profile.meets_target = (
                profile.texts_per_sec is not None and profile.texts_per_sec >= TARGET_TPS
            )
            profile.batch_calibration = calibration
            print(
                f"[accel] batch={profile.batch_size} "
                f"{profile.texts_per_sec or 0:.2f} t/s "
                f"(target {TARGET_TPS}+) meet={profile.meets_target} "
                f"reason={calibration.get('reason')}",
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
        print(f"[accel] hardware snapshot update skipped: {exc}", file=sys.stderr, flush=True)
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
    # Keep divisible by all candidates for clean last-batch sizing.
    lcm = math.lcm(*[int(b) for b in candidates]) if candidates else 1
    count = max(lcm, ((count + lcm - 1) // lcm) * lcm)
    texts = _calibration_corpus(count)

    if model is None:
        model = TextEmbedding(
            model_name=CODERANK_MODEL,
            threads=1,
            providers=profile.providers(),
            lazy_load=True,
        )
        list(model.embed(texts[:1], batch_size=1, parallel=None))

    measured: dict[str, float] = {}
    errors: dict[str, str] = {}
    # Prefer mid-size first so we fail fast if the device is unhealthy, then
    # measure 8 and 20 around the preferred 16.
    order = sorted(candidates, key=lambda b: (0 if b == BATCH_PREFER else 1, abs(b - BATCH_PREFER)))
    t_start = time.perf_counter()
    for batch in order:
        try:
            t0 = time.perf_counter()
            list(model.embed(texts, batch_size=int(batch), parallel=None))
            wall = time.perf_counter() - t0
            tps = len(texts) / max(wall, 1e-6)
            measured[str(batch)] = round(tps, 3)
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
    winner_tps = scores.get(winner)
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
    }


def microbench(profile: AccelProfile, n: int = 48) -> float:
    """Return texts/sec using the profile's configured batch (legacy helper)."""
    calibration = calibrate_batch(profile, n=n, candidates=(max(1, int(profile.batch_size)),))
    tps = calibration.get("texts_per_sec")
    if tps is None:
        raise RuntimeError(calibration.get("errors") or "microbench failed")
    return float(tps)


def resolve_runtime() -> AccelProfile:
    """Load the installed preference without detection or selection."""
    profile = load_accel()
    if profile is None:
        raise RuntimeError("acceleration profile is not configured; run `ctx init`")
    return profile

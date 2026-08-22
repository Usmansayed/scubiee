"""Explicit runtime capability checks for Context Engine.

No caller may interpret a missing parser or semantic backend as a successful,
empty search/index. Accel inspection reads the saved profile, checks the exact
provider, and warms the already-cached model offline. It never selects a
profile, installs packages, downloads a model, or calibrates hardware.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from pipeline.accel import AccelProfile


Finder = Callable[[str], object | None]
ProviderGetter = Callable[[], list[str]]
ModelWarmup = Callable[[AccelProfile], bool]


@dataclass(frozen=True)
class ProviderValidation:
    """Read-only proof that a saved provider can warm its saved model."""

    ok: bool
    profile: str | None
    provider: str | None
    available_providers: tuple[str, ...]
    provider_available: bool
    model_warm: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _available_providers() -> list[str]:
    import onnxruntime as ort  # type: ignore

    return list(ort.get_available_providers())


def _warm_saved_model(profile: AccelProfile) -> bool:
    """Warm only an already-cached model on the exact saved provider."""

    from fastembed import TextEmbedding  # type: ignore
    from pipeline.accel import register_coderank

    register_coderank()
    model_name = profile.model
    warm = ["scubiee provider validation"]
    warm_bs = 1
    if profile.profile == "coreml":
        from pipeline.coreml_mac import (
            bind_coreml_tokenizer,
            coreml_model_name,
            pad_embed_batch,
            static_embed_batch_size,
        )

        model_name = coreml_model_name(profile.model)
        warm_bs = static_embed_batch_size(profile, max(1, int(profile.batch_size or 1)))
        warm = pad_embed_batch(warm, warm_bs)
    model = TextEmbedding(
        model_name=model_name,
        threads=1,
        providers=profile.providers(),
        lazy_load=True,
        local_files_only=True,
    )
    if profile.profile == "coreml":
        bind_coreml_tokenizer(model)
    warmed = list(model.embed(warm, batch_size=warm_bs, parallel=None))
    return bool(warmed)


def validate_provider(
    profile: AccelProfile | None,
    *,
    finder: Finder = importlib.util.find_spec,
    provider_getter: ProviderGetter = _available_providers,
    warmup: ModelWarmup = _warm_saved_model,
) -> ProviderValidation:
    """Validate a saved profile without selecting, installing, or calibrating."""

    if profile is None:
        return ProviderValidation(
            False,
            None,
            None,
            (),
            False,
            False,
            "no saved profile; run `python -m pipeline setup`",
        )
    if profile.profile == "mlx" or profile.backend == "mlx":
        mlx_ok = finder("mlx") is not None
        return ProviderValidation(
            mlx_ok,
            profile.profile,
            profile.provider,
            ("MLX",),
            mlx_ok,
            mlx_ok,
            "MLX package available" if mlx_ok else "mlx is not installed",
        )
    missing = [
        module for module in ("fastembed", "onnxruntime") if finder(module) is None
    ]
    if missing:
        return ProviderValidation(
            False,
            profile.profile,
            profile.provider,
            (),
            False,
            False,
            "missing installed package(s): " + ", ".join(missing),
        )
    try:
        providers = tuple(provider_getter())
    except Exception as exc:  # noqa: BLE001
        return ProviderValidation(
            False,
            profile.profile,
            profile.provider,
            (),
            False,
            False,
            f"provider query failed: {exc}",
        )
    provider_available = profile.provider in providers
    if not provider_available:
        return ProviderValidation(
            False,
            profile.profile,
            profile.provider,
            providers,
            False,
            False,
            f"saved provider {profile.provider} is unavailable",
        )
    try:
        model_warm = bool(warmup(profile))
        detail = (
            f"{profile.provider} warmed cached model {profile.model}"
            if model_warm
            else f"cached model {profile.model} did not produce an embedding"
        )
    except Exception as exc:  # noqa: BLE001
        model_warm = False
        detail = f"model warm-up failed: {exc}"
    return ProviderValidation(
        provider_available and model_warm,
        profile.profile,
        profile.provider,
        providers,
        provider_available,
        model_warm,
        detail,
    )


def recommended_server_command(profile: AccelProfile | None) -> str:
    """Return startup guidance derived only from persisted profile presence."""

    return "python -m pipeline serve" if profile is not None else "python -m pipeline setup"


class CapabilityError(RuntimeError):
    """A required local CE capability is unavailable."""


_CAPABILITIES = (
    (
        "faiss",
        "faiss",
        True,
        "Install the CE vector dependencies, then rerun `scubiee preflight`.",
    ),
    (
        "rapidfuzz",
        "rapidfuzz",
        True,
        "Install `rapidfuzz`; graph deduplication cannot run without it.",
    ),
    (
        "typescript_parser",
        "tree_sitter_typescript",
        True,
        "Install the TypeScript tree-sitter parser; CE refuses partial TS/TSX indexing.",
    ),
    (
        "json_parser",
        "tree_sitter_json",
        True,
        "Install the JSON tree-sitter parser; CE refuses partial JSON indexing.",
    ),
)


def inspect_accel(*, finder: Finder = importlib.util.find_spec) -> dict[str, Any]:
    """Report hardware accel plan vs what this Python can actually run."""
    saved_profile: AccelProfile | None = None
    profile_name: str | None = None
    provider: str | None = None
    batch_size: int | None = None
    backend = "fastembed"
    texts_per_sec = None
    reason = "acceleration profile is not configured"
    configured = False
    try:
        from pipeline.accel import resolve_runtime

        prof = resolve_runtime()
        saved_profile = prof
        configured = True
        profile_name = prof.profile
        provider = prof.provider
        batch_size = int(prof.batch_size or 8)
        backend = str(prof.backend or "fastembed")
        texts_per_sec = prof.texts_per_sec
        reason = prof.reason or reason
    except Exception as exc:  # noqa: BLE001
        reason = f"accel resolve failed: {exc}"

    fastembed_ok = finder("fastembed") is not None
    # onnxruntime-directml / onnxruntime-gpu install as top-level `onnxruntime`
    ort_ok = finder("onnxruntime") is not None
    validation = validate_provider(saved_profile, finder=finder)
    providers = list(validation.available_providers)
    provider_ok = validation.provider_available

    explicit_st = False
    try:
        import os

        explicit_st = os.environ.get("CTX_EMBED_BACKEND", "").strip().lower() in {
            "st",
            "sentence-transformers",
            "coderank",
        }
    except Exception:  # noqa: BLE001
        explicit_st = False

    st_ok = finder("sentence_transformers") is not None
    if not configured:
        semantic_ok = False
        missing = ["not_configured"]
        hint = "Run `scubiee setup` to configure and persist an acceleration profile."
    elif backend == "mlx":
        mlx_ok = finder("mlx") is not None
        semantic_ok = mlx_ok
        missing = [] if mlx_ok else ["mlx"]
        hint = (
            "Install MLX (`pip install mlx`) on Apple Silicon, then set "
            "CTX_EMBED_BACKEND=mlx. GPU initialization is required; CPU fallback is refused."
        )
    elif backend == "fastembed" and not explicit_st:
        semantic_ok = fastembed_ok and ort_ok and validation.ok
        missing: list[str] = []
        if not fastembed_ok:
            missing.append("fastembed")
        if not ort_ok:
            missing.append("onnxruntime")
        if ort_ok and not provider_ok:
            missing.append(f"provider:{provider}")
        if provider_ok and not validation.model_warm:
            missing.append("model_warmup")
        hint = (
            f"Run `python -m pipeline setup` (or `pip install -e \".[{profile_name}]\"`) "
            f"so FastEmbed uses {provider} at batch={batch_size}."
        )
    else:
        semantic_ok = st_ok
        missing = [] if st_ok else ["sentence_transformers"]
        hint = "Install sentence-transformers or switch back to FastEmbed via `scubiee setup`."

    return {
        "ok": semantic_ok,
        "profile": profile_name,
        "provider": provider,
        "batch_size": batch_size,
        "backend": backend if not explicit_st else "coderank",
        "texts_per_sec": texts_per_sec,
        "reason": reason,
        "fastembed": fastembed_ok,
        "onnxruntime": ort_ok,
        "providers": providers,
        "provider_ok": provider_ok,
        "model_warm": validation.model_warm,
        "provider_validation": validation.to_dict(),
        "sentence_transformers": st_ok,
        "missing": missing,
        "hint": hint,
    }


def inspect_capabilities(
    *,
    require_semantic: bool = True,
    finder: Finder = importlib.util.find_spec,
) -> dict[str, Any]:
    """Return an install-safe capability report without importing heavy deps."""
    capabilities: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for label, module, always_required, hint in _CAPABILITIES:
        required = always_required
        available = finder(module) is not None
        capabilities[label] = {
            "module": module,
            "available": available,
            "required": required,
            "hint": hint,
        }
        if required and not available:
            missing.append(module)

    accel = inspect_accel(finder=finder)
    capabilities["embed_accel"] = {
        "module": "fastembed+onnxruntime",
        "available": bool(accel.get("ok")),
        "required": require_semantic,
        "hint": accel.get("hint") or "",
        "detail": {
            "profile": accel.get("profile"),
            "provider": accel.get("provider"),
            "batch_size": accel.get("batch_size"),
            "backend": accel.get("backend"),
            "texts_per_sec": accel.get("texts_per_sec"),
            "providers": accel.get("providers"),
        },
    }
    if require_semantic and not accel.get("ok"):
        missing.extend(str(x) for x in (accel.get("missing") or []))

    # Keep ST visible but not required unless explicitly selected.
    capabilities["semantic_search_st"] = {
        "module": "sentence_transformers",
        "available": finder("sentence_transformers") is not None,
        "required": False,
        "hint": "Optional PyTorch fallback only — production path is FastEmbed+ORT.",
    }

    return {
        "ok": not missing,
        "require_semantic": require_semantic,
        "capabilities": capabilities,
        "missing_required": sorted(set(missing)),
        "accel": accel,
    }


def require_capabilities(
    *,
    require_semantic: bool = True,
    finder: Finder = importlib.util.find_spec,
) -> dict[str, Any]:
    """Return the report or fail closed with concrete recovery instructions."""
    report = inspect_capabilities(require_semantic=require_semantic, finder=finder)
    if report["ok"]:
        return report
    caps = report["capabilities"]
    hints = [
        caps[name]["hint"]
        for name in caps
        if caps[name].get("required") and not caps[name].get("available")
    ]
    accel = report.get("accel") or {}
    if accel.get("hint"):
        hints.append(str(accel["hint"]))
    raise CapabilityError(
        "Context Engine required dependencies unavailable: "
        + ", ".join(report["missing_required"])
        + ". "
        + " ".join(hints)
    )

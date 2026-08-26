"""Dependency preflight must make degraded CE operation explicit."""

from __future__ import annotations

import sys
from importlib.machinery import ModuleSpec
from types import SimpleNamespace

import pytest


def _finder(available: set[str]):
    def find_spec(name: str):
        return ModuleSpec(name, loader=None) if name in available else None

    return find_spec


def test_preflight_reports_required_parser_and_accel_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipeline import accel
    from pipeline.accel import AccelProfile
    from pipeline.preflight import ProviderValidation, inspect_capabilities

    monkeypatch.delenv("CTX_EMBED_BACKEND", raising=False)
    monkeypatch.delenv("CTX_MLX", raising=False)
    # Without a persisted profile, missing packages collapse to ``not_configured``.
    # Stub an installed CPU plan so the finder-driven package gaps are asserted.
    monkeypatch.setattr(
        accel,
        "load_accel",
        lambda: AccelProfile(
            profile="cpu",
            provider="CPUExecutionProvider",
            backend="fastembed",
            batch_size=16,
            reason="pytest stub",
        ),
    )
    monkeypatch.setattr(
        "pipeline.preflight.validate_provider",
        lambda *_a, **_k: ProviderValidation(
            True,
            "cpu",
            "CPUExecutionProvider",
            ("CPUExecutionProvider",),
            True,
            True,
            "ok",
        ),
    )

    report = inspect_capabilities(
        require_semantic=True,
        finder=_finder({"faiss", "rapidfuzz"}),
    )

    assert report["ok"] is False
    assert "tree_sitter_json" in report["missing_required"]
    assert "tree_sitter_typescript" in report["missing_required"]
    assert "fastembed" in report["missing_required"]
    assert report["capabilities"]["typescript_parser"]["available"] is False
    assert report["capabilities"]["embed_accel"]["available"] is False
    assert report["accel"]["backend"] in {"fastembed", "coderank"}


def test_preflight_allows_lexical_only_without_semantic_backend() -> None:
    from pipeline.preflight import inspect_capabilities

    report = inspect_capabilities(
        require_semantic=False,
        finder=_finder(
            {
                "faiss",
                "rapidfuzz",
                "tree_sitter_json",
                "tree_sitter_typescript",
            }
        ),
    )

    assert report["ok"] is True
    assert report["missing_required"] == []
    assert report["capabilities"]["embed_accel"]["required"] is False


def test_preflight_ok_when_fastembed_stack_present() -> None:
    from pipeline.preflight import inspect_capabilities

    report = inspect_capabilities(
        require_semantic=True,
        finder=_finder(
            {
                "faiss",
                "rapidfuzz",
                "tree_sitter_json",
                "tree_sitter_typescript",
                "fastembed",
                "onnxruntime",
            }
        ),
    )
    # Provider check may still fail if real ORT lacks Dml — that's OK for this unit;
    # package presence must clear the import side of missing_required.
    assert "fastembed" not in report["missing_required"]
    assert "tree_sitter_typescript" not in report["missing_required"]


def test_missing_installed_profile_cannot_report_valid_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipeline import accel
    from pipeline.preflight import inspect_capabilities

    monkeypatch.setattr(accel, "load_accel", lambda: None)
    monkeypatch.setattr(
        accel,
        "recommend_profile",
        lambda *args, **kwargs: pytest.fail("preflight must not recommend"),
    )
    monkeypatch.setattr(
        accel,
        "configure",
        lambda *args, **kwargs: pytest.fail("preflight must not configure"),
    )
    monkeypatch.setattr(
        accel,
        "calibrate_batch",
        lambda *args, **kwargs: pytest.fail("preflight must not calibrate"),
    )
    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(get_available_providers=lambda: ["CPUExecutionProvider"]),
    )

    report = inspect_capabilities(
        require_semantic=True,
        finder=_finder(
            {
                "faiss",
                "rapidfuzz",
                "tree_sitter_json",
                "tree_sitter_typescript",
                "fastembed",
                "onnxruntime",
            }
        ),
    )

    assert report["ok"] is False
    assert report["accel"]["ok"] is False
    assert report["accel"]["profile"] is None
    assert "not_configured" in report["accel"]["missing"]
    assert "scubiee setup" in report["accel"]["hint"]


def test_explicit_installed_cpu_profile_remains_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pipeline import accel
    from pipeline.accel import AccelProfile
    from pipeline.preflight import ProviderValidation, inspect_capabilities

    installed = AccelProfile(
        profile="cpu",
        provider="CPUExecutionProvider",
        batch_size=16,
        reason="explicit installed CPU profile",
    )
    monkeypatch.setattr(accel, "load_accel", lambda: installed)
    monkeypatch.delenv("CTX_EMBED_BACKEND", raising=False)
    monkeypatch.delenv("CTX_MLX", raising=False)
    monkeypatch.setattr(
        "pipeline.preflight.validate_provider",
        lambda *_a, **_k: ProviderValidation(
            True,
            "cpu",
            "CPUExecutionProvider",
            ("CPUExecutionProvider",),
            True,
            True,
            "ok",
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(get_available_providers=lambda: ["CPUExecutionProvider"]),
    )

    report = inspect_capabilities(
        require_semantic=True,
        finder=_finder(
            {
                "faiss",
                "rapidfuzz",
                "tree_sitter_json",
                "tree_sitter_typescript",
                "fastembed",
                "onnxruntime",
            }
        ),
    )

    assert report["ok"] is True
    assert report["accel"]["ok"] is True
    assert report["accel"]["profile"] == "cpu"
    assert report["accel"]["provider_ok"] is True


def test_require_capabilities_raises_with_actionable_missing_names() -> None:
    from pipeline.preflight import CapabilityError, require_capabilities

    with pytest.raises(CapabilityError, match="rapidfuzz"):
        require_capabilities(
            require_semantic=True,
            finder=_finder(set()),
        )


def test_full_index_fails_closed_when_preflight_rejects(monkeypatch, tmp_path) -> None:
    import pytest

    from pipeline.indexer import index_repo
    from pipeline.preflight import CapabilityError

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    monkeypatch.setattr(
        "pipeline.indexer.require_capabilities",
        lambda **_kwargs: (_ for _ in ()).throw(CapabilityError("missing test dep")),
    )

    with pytest.raises(CapabilityError, match="missing test dep"):
        index_repo(repo)

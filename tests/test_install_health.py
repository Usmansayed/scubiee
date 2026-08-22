from __future__ import annotations

from pathlib import Path

from pipeline import install_health


def test_faiss_class_wrappers_present_false_when_missing(tmp_path: Path, monkeypatch) -> None:
    site = tmp_path / "site-packages"
    (site / "faiss").mkdir(parents=True)
    (site / "faiss" / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(install_health.sys, "path", [str(site)])
    assert install_health.faiss_class_wrappers_present() is False


def test_faiss_class_wrappers_present_true_when_file_exists(tmp_path: Path, monkeypatch) -> None:
    site = tmp_path / "site-packages"
    (site / "faiss").mkdir(parents=True)
    (site / "faiss" / "class_wrappers.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(install_health.sys, "path", [str(site)])
    assert install_health.faiss_class_wrappers_present() is True


def test_version_only_accepts_common_aliases() -> None:
    from pipeline.__main__ import _version_only

    assert _version_only(["--version"])
    assert _version_only(["version"])
    assert _version_only(["-version"])
    assert _version_only(["-V"])
    assert not _version_only(["index"])


def test_requires_faiss_guard_skips_setup_and_wipe() -> None:
    from pipeline.__main__ import _requires_faiss_guard

    assert not _requires_faiss_guard(["setup", "--repair"])
    assert not _requires_faiss_guard(["wipe", "--all"])
    assert not _requires_faiss_guard(["connect", "--cursor", "--dry-run"])
    assert not _requires_faiss_guard(["disconnect", "--all", "--dry-run"])
    assert not _requires_faiss_guard(["migrate", "--check-all"])
    assert not _requires_faiss_guard(["diagnose", "--no-tests"])
    assert _requires_faiss_guard(["init"])
    assert _requires_faiss_guard(["index"])

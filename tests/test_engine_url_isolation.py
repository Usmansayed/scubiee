"""Engine URL isolation for pytest vs production daemon port."""

from __future__ import annotations

import pytest


def test_engine_url_defaults_to_8765(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CTX_ENGINE_URL", raising=False)
    monkeypatch.delenv("CTX_SEARCH_URL", raising=False)
    monkeypatch.delenv("CTX_ALLOW_TEST_HOME", raising=False)
    monkeypatch.delenv("CTX_ENGINE_PORT", raising=False)
    from pipeline.client import engine_url

    assert engine_url() == "http://127.0.0.1:8765"


def test_engine_url_uses_test_port_under_allow_test_home(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CTX_ENGINE_URL", raising=False)
    monkeypatch.delenv("CTX_SEARCH_URL", raising=False)
    monkeypatch.setenv("CTX_ALLOW_TEST_HOME", "1")
    monkeypatch.delenv("CTX_ENGINE_PORT", raising=False)
    from pipeline.client import engine_url

    assert engine_url() == "http://127.0.0.1:18765"


def test_engine_url_explicit_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_ALLOW_TEST_HOME", "1")
    monkeypatch.setenv("CTX_ENGINE_URL", "http://127.0.0.1:9999")
    from pipeline.client import engine_url

    assert engine_url() == "http://127.0.0.1:9999"

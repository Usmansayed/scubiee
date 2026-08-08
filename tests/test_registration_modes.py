"""Registration modes: automatic vs mcp_cli + always_allow."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))


@pytest.fixture
def ce_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    return home


def test_prefs_default_automatic(ce_home: Path):
    from pipeline.settings import get_registration_mode, load_prefs

    prefs = load_prefs()
    assert prefs["registration_mode"] == "automatic"
    assert get_registration_mode() == "automatic"


def test_set_registration_mode(ce_home: Path):
    from pipeline.settings import get_registration_mode, set_registration_mode

    set_registration_mode("mcp_cli")
    assert get_registration_mode() == "mcp_cli"
    set_registration_mode("automatic")
    assert get_registration_mode() == "automatic"


def test_env_overrides_mode(ce_home: Path, monkeypatch: pytest.MonkeyPatch):
    from pipeline.settings import get_registration_mode, set_registration_mode

    set_registration_mode("automatic")
    monkeypatch.setenv("CTX_REGISTRATION_MODE", "mcp_cli")
    assert get_registration_mode() == "mcp_cli"


def test_needs_consent_mcp_cli(ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from pipeline.registration import needs_registration_consent, register_project
    from pipeline.settings import set_registration_mode

    monkeypatch.setenv("CTX_REGISTRATION_MODE", "mcp_cli")
    set_registration_mode("mcp_cli")
    repo = tmp_path / "app"
    repo.mkdir()
    assert needs_registration_consent(repo) is True

    with patch("pipeline.registration.index_is_usable", return_value=True):
        r = register_project(repo, always_allow=False, index=False)
    assert r.ok
    assert needs_registration_consent(repo) is False


def test_always_allow_skips_consent(ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from pipeline.registration import (
        is_always_allowed,
        needs_registration_consent,
        register_project,
    )
    from pipeline.settings import set_registration_mode

    set_registration_mode("mcp_cli")
    monkeypatch.setenv("CTX_REGISTRATION_MODE", "mcp_cli")
    repo = tmp_path / "app2"
    repo.mkdir()

    with patch("pipeline.registration.index_is_usable", return_value=True):
        register_project(repo, always_allow=True, index=False)

    assert is_always_allowed(repo) is True
    # Wipe registered flag but keep always_allow — still no consent needed
    from pipeline.project_id import load_registry, read_id_file, save_registry

    pid = read_id_file(repo)
    reg = load_registry()
    reg["projects"][pid]["registered"] = False
    # leave always_allow True; also clear usable-index path by not having chunks
    save_registry(reg)
    with patch("pipeline.registration.index_is_usable", return_value=False):
        assert needs_registration_consent(repo) is False


def test_automatic_no_consent(ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from pipeline.registration import needs_registration_consent
    from pipeline.settings import set_registration_mode

    set_registration_mode("automatic")
    monkeypatch.delenv("CTX_REGISTRATION_MODE", raising=False)
    repo = tmp_path / "x"
    repo.mkdir()
    assert needs_registration_consent(repo) is False


def test_prompt_payload(ce_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from pipeline.registration import registration_prompt_payload
    from pipeline.settings import set_registration_mode

    set_registration_mode("mcp_cli")
    monkeypatch.setenv("CTX_REGISTRATION_MODE", "mcp_cli")
    repo = tmp_path / "p"
    repo.mkdir()
    payload = registration_prompt_payload(repo)
    assert payload["status"] == "needs_registration"
    assert any(a.get("always_allow") for a in payload["actions"])


def test_dashboard_html_has_modes():
    from pipeline.dashboard import DASHBOARD_HTML

    assert "automatic" in DASHBOARD_HTML
    assert "mcp_cli" in DASHBOARD_HTML
    assert "/api/settings" in DASHBOARD_HTML

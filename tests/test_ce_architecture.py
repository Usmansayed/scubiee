"""Context Engine service + client (architecture) tests."""

from __future__ import annotations

import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))


@pytest.fixture
def ce_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "ce-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    return home


def test_context_engine_status_unregistered(ce_home: Path, tmp_path: Path, monkeypatch):
    from pipeline.ce_service import ContextEngine
    from pipeline.settings import set_registration_mode

    set_registration_mode("mcp_cli")
    monkeypatch.setenv("CTX_REGISTRATION_MODE", "mcp_cli")
    repo = tmp_path / "proj"
    repo.mkdir()
    ce = ContextEngine()
    ce.repo = repo
    st = ce.status(repo)
    assert st.get("registration_mode") == "mcp_cli"
    assert "needs_registration" in st or st.get("registered") is False


def test_client_unreachable():
    from pipeline.client import EngineClient

    c = EngineClient("http://127.0.0.1:59999", timeout=1.0)
    r = c.get("/health")
    assert r.get("ok") is False
    assert "unreachable" in str(r.get("error") or "").lower() or "hint" in r


def test_http_v1_health(ce_home: Path, tmp_path: Path):
    from pipeline.server import Handler

    repo = tmp_path / "r"
    repo.mkdir()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        from pipeline.client import EngineClient

        c = EngineClient(f"http://127.0.0.1:{port}", timeout=5.0)
        h = c.get("/health")
        assert h.get("ok") is True
        assert h.get("service") == "scubiee"
        settings = c.get("/api/settings")
        assert "registration_mode" in settings
    finally:
        httpd.shutdown()

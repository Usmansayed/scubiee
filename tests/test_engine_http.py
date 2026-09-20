"""Tests for cross-platform engine HTTP transport."""

from __future__ import annotations

import httpx


def test_get_json_retries_connect_error():
    from pipeline.engine_http import EngineHttp

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"ok": True, "embedder_loaded": True})

    http = EngineHttp(
        base_url="http://127.0.0.1:8765",
        transport=httpx.MockTransport(handler),
        retries=3,
    )
    out = http.get_json("/health")
    assert out["ok"] is True
    assert calls["n"] == 3


def test_post_json_does_not_retry_by_default():
    from pipeline.engine_http import EngineHttp

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("boom", request=request)

    http = EngineHttp(
        base_url="http://127.0.0.1:8765",
        transport=httpx.MockTransport(handler),
        retries=3,
    )
    out = http.post_json("/v1/embed/prewarm", {"wait": False})
    assert out.get("ok") is False
    assert calls["n"] == 1
    assert out.get("should_retry") is True


def test_post_json_retry_true_does_not_shadow_tenacity():
    """Param name ``retry`` must not break the tenacity decorator (0.3.81 footgun)."""
    from pipeline.engine_http import EngineHttp

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json={"ok": True})

    http = EngineHttp(
        base_url="http://127.0.0.1:8765",
        transport=httpx.MockTransport(handler),
        retries=3,
    )
    out = http.post_json("/v1/status", {"path": "."}, retry=True)
    assert out.get("ok") is True
    assert calls["n"] == 2


def test_get_json_soft_never_raises():
    from pipeline.engine_http import EngineHttp

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    http = EngineHttp(
        base_url="http://127.0.0.1:8765",
        transport=httpx.MockTransport(handler),
        retries=2,
    )
    out = http.get_json_soft("/health")
    assert out.get("ok") is False
    assert "unreachable" in str(out.get("error") or "").lower()

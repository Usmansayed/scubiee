"""Cross-platform engine HTTP transport (Windows / macOS / Linux).

Uses sync ``httpx.Client`` + ``tenacity`` so MCP/IDE hosts stay on the existing
sync tool path. Pure-Python stack — no OS-specific sockets beyond httpx.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from tenacity import (
    retry as tenacity_retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)


def engine_http_retries() -> int:
    raw = (os.environ.get("CTX_ENGINE_HTTP_RETRIES") or "3").strip()
    try:
        return max(1, min(8, int(raw)))
    except ValueError:
        return 3


def _default_timeout(read_s: float) -> httpx.Timeout:
    # Split timeouts: fail fast on dead connect; allow slower read on warm/prewarm.
    # Pool wait must stay short — a 2s+ pool stall stacked on retrieve blew the 1s map SLA.
    connect = min(2.0, max(0.5, read_s / 4.0))
    pool = min(0.75, max(0.25, connect))
    return httpx.Timeout(connect=connect, read=read_s, write=read_s, pool=pool)


class EngineHttp:
    """Shared sync HTTP client for the local Scubiee engine."""

    def __init__(
        self,
        base_url: str,
        *,
        retries: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.retries = int(retries if retries is not None else engine_http_retries())
        if isinstance(timeout, httpx.Timeout):
            to = timeout
        elif timeout is None:
            to = _default_timeout(8.0)
        else:
            to = _default_timeout(float(timeout))
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=to,
            transport=transport,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
            headers={"Accept": "application/json", "User-Agent": "scubiee-engine-http/1"},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> EngineHttp:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get_json(self, path: str) -> dict[str, Any]:
        """GET with retries on connect/timeout (idempotent). Raises on hard failure."""

        @tenacity_retry(
            retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
            stop=stop_after_attempt(self.retries),
            wait=wait_exponential_jitter(initial=0.05, max=0.5),
            reraise=True,
        )
        def _once() -> dict[str, Any]:
            r = self._client.get(path)
            if r.status_code in {502, 503, 504}:
                # Treat as transient for retry policy via raise.
                raise httpx.TimeoutException(f"upstream {r.status_code}", request=r.request)
            r.raise_for_status()
            data = r.json() if r.content else {}
            return data if isinstance(data, dict) else {"ok": False, "data": data}

        return _once()

    def post_json(self, path: str, body: dict[str, Any] | None = None, *, retry: bool = False) -> dict[str, Any]:
        """POST JSON. Retries only when ``retry=True`` (explicit idempotent calls)."""
        payload = body or {}

        def _once() -> dict[str, Any]:
            r = self._client.post(path, json=payload)
            if r.status_code >= 400:
                try:
                    data = r.json() if r.content else {}
                except Exception:  # noqa: BLE001
                    data = {"error": r.text[:500]}
                if not isinstance(data, dict):
                    data = {"error": str(data)}
                data.setdefault("ok", False)
                data.setdefault("http_status", r.status_code)
                return data
            data = r.json() if r.content else {}
            return data if isinstance(data, dict) else {"ok": True, "data": data}

        if not retry:
            try:
                return _once()
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                return {
                    "ok": False,
                    "error": f"Scubiee unreachable at {self.base_url}: {exc}",
                    "hint": "Run: scubiee setup   or   scubiee engine start",
                    "should_retry": True,
                }

        # NOTE: param name ``retry`` shadows tenacity.retry — use tenacity_retry.
        @tenacity_retry(
            retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
            stop=stop_after_attempt(self.retries),
            wait=wait_exponential_jitter(initial=0.05, max=0.5),
            reraise=True,
        )
        def _retrying() -> dict[str, Any]:
            return _once()

        try:
            return _retrying()
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            return {
                "ok": False,
                "error": f"Scubiee unreachable at {self.base_url}: {exc}",
                "hint": "Run: scubiee setup   or   scubiee engine start",
                "should_retry": True,
            }

    def get_json_soft(self, path: str) -> dict[str, Any]:
        """GET that never raises — matches legacy EngineClient error dicts."""
        try:
            return self.get_json(path)
        except httpx.HTTPStatusError as exc:
            try:
                data = exc.response.json() if exc.response.content else {}
            except Exception:  # noqa: BLE001
                data = {"error": str(exc)}
            if not isinstance(data, dict):
                data = {"error": str(data)}
            data.setdefault("ok", False)
            data.setdefault("http_status", exc.response.status_code)
            return data
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPError, OSError) as exc:
            return {
                "ok": False,
                "error": f"Scubiee unreachable at {self.base_url}: {exc}",
                "hint": "Run: scubiee setup   or   scubiee engine start",
                "should_retry": True,
            }


_POOL_LOCK = __import__("threading").Lock()
_POOL: dict[tuple[str, float, int], EngineHttp] = {}


def shared_engine_http(
    base_url: str,
    *,
    timeout: float = 8.0,
    retries: int | None = None,
) -> EngineHttp:
    """Process-local pooled client — avoid TCP/TLS setup on every map/search."""
    key = (base_url.rstrip("/"), float(timeout), int(retries if retries is not None else engine_http_retries()))
    with _POOL_LOCK:
        hit = _POOL.get(key)
        if hit is not None:
            return hit
        hit = EngineHttp(base_url, timeout=timeout, retries=retries)
        _POOL[key] = hit
        return hit

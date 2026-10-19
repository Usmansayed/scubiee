"""A crashed or stopped engine is recovered instead of failing the next map call."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error

import pytest


@pytest.mark.skipif(os.name == "nt", reason="POSIX zombie semantics")
def test_unreaped_dead_child_is_not_alive() -> None:
    from pipeline.daemon import _pid_alive
    from pipeline.lifecycle_runtime import _pid_alive as life_alive
    from pipeline.watchdog import _pid_alive as wd_alive

    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    deadline = time.time() + 5
    import psutil

    while time.time() < deadline and psutil.Process(proc.pid).status() != psutil.STATUS_ZOMBIE:
        time.sleep(0.05)
    try:
        assert _pid_alive(proc.pid) is False
        assert wd_alive(proc.pid) is False
        assert life_alive(proc.pid) is False
    finally:
        proc.wait()


def _refused(*_a, **_k):
    raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))


class _Resp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a) -> None:
        return None


def test_map_request_starts_a_stopped_engine_then_retries(monkeypatch) -> None:
    import pipeline.map_v3_helpers as mv2

    calls = {"n": 0, "ensure": 0}

    class _Opener:
        def open(self, req, timeout=None):
            calls["n"] += 1
            if calls["ensure"] == 0:
                _refused()
            return _Resp(b'{"hits": [{"path": "a.py"}]}')

    monkeypatch.setattr(mv2, "_opener", lambda: _Opener())
    monkeypatch.setattr("pipeline.client.EngineClient.healthy", lambda self: False)

    def _ensure(repo, **kw):
        calls["ensure"] += 1
        return {"ok": True}

    monkeypatch.setattr("pipeline.daemon.ensure_daemon", _ensure)
    assert mv2._http("/v1/search", {"query": "x"}) == {"hits": [{"path": "a.py"}]}
    assert calls["ensure"] == 1


def test_health_pulse_never_starts_the_engine(monkeypatch) -> None:
    import pipeline.map_v3_helpers as mv2

    class _Opener:
        def open(self, req, timeout=None):
            _refused()

    monkeypatch.setattr(mv2, "_opener", lambda: _Opener())
    started: list[bool] = []
    monkeypatch.setattr("pipeline.daemon.ensure_daemon", lambda *a, **k: started.append(True))
    monkeypatch.setattr(mv2.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        mv2._http("/health", None, 1)
    assert started == []


def test_unstartable_engine_reports_why(monkeypatch) -> None:
    import pipeline.map_v3_helpers as mv2

    class _Opener:
        def open(self, req, timeout=None):
            _refused()

    monkeypatch.setattr(mv2, "_opener", lambda: _Opener())
    monkeypatch.setattr("pipeline.client.EngineClient.healthy", lambda self: False)
    monkeypatch.setattr(
        "pipeline.daemon.ensure_daemon",
        lambda *a, **k: {"ok": False, "reason": "globally_paused", "hint": "run scubiee resume"},
    )
    with pytest.raises(RuntimeError, match="globally_paused.*scubiee resume"):
        mv2._http("/v1/search", {"query": "x"})

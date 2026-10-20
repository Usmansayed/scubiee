"""CTX_ENGINE_URL on another port while the machine's engine runs elsewhere."""

from __future__ import annotations

import argparse
import json
import os

import pytest

from pipeline import daemon


def _write_lock(url: str, pid: int | None = None) -> None:
    path = daemon.lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": pid or os.getpid(), "url": url}), encoding="utf-8")


def test_live_engine_on_other_port_is_reported(monkeypatch):
    _write_lock("http://127.0.0.1:8765")
    monkeypatch.setenv("CTX_ENGINE_URL", "http://127.0.0.1:8799")
    out = daemon.engine_running_elsewhere()
    assert out is not None and out["reason"] == "engine_on_other_url"
    assert out["running_url"] == "http://127.0.0.1:8765"
    assert daemon.start_daemon(wait_s=0)["reason"] == "engine_on_other_url"
    assert daemon.ensure_daemon(wait_s=0)["reason"] == "engine_on_other_url"


@pytest.mark.parametrize(
    "recorded, wanted",
    [("http://127.0.0.1:8799", "http://127.0.0.1:8799"), ("http://localhost:8799", "http://127.0.0.1:8799/")],
)
def test_same_endpoint_is_not_elsewhere(monkeypatch, recorded, wanted):
    _write_lock(recorded)
    monkeypatch.setenv("CTX_ENGINE_URL", wanted)
    assert daemon.engine_running_elsewhere() is None


def test_dead_lock_pid_is_not_elsewhere(monkeypatch):
    _write_lock("http://127.0.0.1:8765", pid=2**22 + 12345)
    monkeypatch.setenv("CTX_ENGINE_URL", "http://127.0.0.1:8799")
    assert daemon.engine_running_elsewhere() is None


def test_engine_start_on_other_port_exits_nonzero(monkeypatch, capsys):
    import pipeline.__main__ as cli

    _write_lock("http://127.0.0.1:8765")
    monkeypatch.setenv("CTX_ENGINE_URL", "http://127.0.0.1:8799")
    assert cli.main(["engine", "start", "--wait", "0"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False and out["reason"] == "engine_on_other_url"


def test_map_reports_other_port_without_waiting(monkeypatch, tmp_path, capsys):
    import pipeline.__main__ as cli
    from pipeline.client import EngineClient

    _write_lock("http://127.0.0.1:8765")
    monkeypatch.setenv("CTX_ENGINE_URL", "http://127.0.0.1:8799")
    monkeypatch.setattr(EngineClient, "healthy", lambda self: False)
    monkeypatch.setattr(cli, "_engine_process_alive", lambda: True)

    def _no_wait(_s):
        raise AssertionError("map waited for an engine that runs on another port")

    monkeypatch.setattr(cli, "_wait_engine_healthy", _no_wait)
    args = argparse.Namespace(config="find", query="anything", names=None, path=str(tmp_path))
    assert cli.cmd_map(args) == 1
    err = capsys.readouterr().err
    assert "already running at http://127.0.0.1:8765" in err

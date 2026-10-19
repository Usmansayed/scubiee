"""A map call that lands while the worker's background _warm is still running must
not redo or fight the warm's work: the repo walk is shared, the warm pauses while a
call runs, and find skips the whole-repo callers grep until the warm has finished."""
from __future__ import annotations

import threading
import time

import pytest

import pipeline.map_v3_helpers as mv


@pytest.fixture
def warm_state(monkeypatch):
    monkeypatch.setattr(mv, "_WARM_STARTED", threading.Event())
    monkeypatch.setattr(mv, "_WARM_DONE", threading.Event())
    monkeypatch.setattr(mv, "_CALL_IDLE", threading.Event())
    mv._CALL_IDLE.set()
    monkeypatch.setattr(mv, "_FILES", None)
    yield


def test_repo_walk_runs_once_when_warm_and_call_race(warm_state, monkeypatch):
    walks = []

    def slow_walk():
        walks.append(1)
        time.sleep(0.2)
        return ["a.py"]

    monkeypatch.setattr(mv, "_walk_repo", slow_walk)
    results = []
    threads = [threading.Thread(target=lambda: results.append(mv._repo_files())) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert walks == [1]
    assert results == [["a.py"], ["a.py"]]


def test_warm_pauses_while_a_call_is_running(warm_state, monkeypatch):
    read = []
    monkeypatch.setattr(mv, "_http", lambda *a, **k: {})
    monkeypatch.setattr(mv, "_repo_files", lambda: [f"f{i}.py" for i in range(5)])
    monkeypatch.setattr(mv, "_kind_of", lambda f: "code")
    monkeypatch.setattr(mv, "_lines", lambda f: read.append(f) or [])

    with mv.call_active():
        t = threading.Thread(target=mv._warm, daemon=True)
        t.start()
        time.sleep(0.2)
        assert read == []
        assert not mv._WARM_DONE.is_set()
    t.join(2)
    assert len(read) == 5
    assert mv._WARM_DONE.is_set()


def test_engine_opener_skips_https_and_proxy_setup(monkeypatch):
    import urllib.request

    monkeypatch.setattr(mv, "_OPENER", None)
    handlers = mv._opener().handlers
    assert not any(isinstance(h, urllib.request.HTTPSHandler) for h in handlers)
    assert not any(isinstance(h, urllib.request.ProxyHandler) for h in handlers)
    assert any(isinstance(h, urllib.request.HTTPHandler) for h in handlers)
    assert any(isinstance(h, urllib.request.HTTPErrorProcessor) for h in handlers)


def _connections(monkeypatch):
    greps = []
    monkeypatch.setattr(mv, "_grep", lambda *a, **k: greps.append(a) or ([], False))
    monkeypatch.setattr(mv, "_code_text", lambda *a, **k: "")
    monkeypatch.setattr(mv, "_outline", lambda rel: [])
    mv._append_connections(mv.Out(4000), {"file": "x.py", "symbol": "f", "start": 1, "end": 2})
    return greps


def test_find_skips_callers_grep_while_warm_pending(warm_state, monkeypatch):
    mv._WARM_STARTED.set()
    assert _connections(monkeypatch) == []


def test_find_runs_callers_grep_once_warm_done(warm_state, monkeypatch):
    mv._WARM_STARTED.set()
    mv._WARM_DONE.set()
    assert len(_connections(monkeypatch)) == 1


def test_find_runs_callers_grep_when_no_warm_thread(warm_state, monkeypatch):
    assert len(_connections(monkeypatch)) == 1

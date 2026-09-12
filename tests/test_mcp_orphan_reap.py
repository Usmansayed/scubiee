"""Orphan MCP workers after Cursor close must die; engine/supervisor must not."""

from __future__ import annotations

import os

from pipeline.process_control import reap_orphaned_mcp_processes


def test_reap_orphaned_mcp_kills_worker_with_dead_parent(monkeypatch) -> None:
    procs = [
        {
            "pid": 101,
            "ppid": 99,  # dead Cursor utility
            "exe": r"C:\Users\x\.local\bin\scubiee-mcp.EXE",
            "cmdline": r'"C:\uv\tools\scubiee\Scripts\python.exe" scubiee-mcp.EXE',
        },
        {
            "pid": 202,
            "ppid": 1,
            "exe": "",
            "cmdline": r"python.exe -u -m pipeline engine run C:\repo --host 127.0.0.1 --port 8765",
        },
        {
            "pid": 303,
            "ppid": 50,  # live Cursor
            "exe": r"C:\Users\x\.local\bin\scubiee-mcp-bridge.EXE",
            "cmdline": "scubiee-mcp-bridge.EXE",
        },
    ]
    monkeypatch.setattr(
        "pipeline.process_control.enumerate_scubiee_processes",
        lambda **_k: procs,
    )
    monkeypatch.setattr(
        "pipeline.process_control._pid_alive",
        lambda pid: int(pid) in {50, 1, 202, 303, os.getpid()},
    )

    killed: list[int] = []

    def _term(pid, **_k):
        killed.append(int(pid))
        return {"pid": pid, "ok": True, "terminated": True}

    monkeypatch.setattr("pipeline.process_control.safe_terminate_pid", _term)
    monkeypatch.setattr("pipeline.process_control._pid_is_protected", lambda *_a, **_k: False)

    out = reap_orphaned_mcp_processes(keep_pids={os.getpid()})
    assert 101 in out["killed"]
    assert 202 not in out["killed"]  # engine
    assert 303 not in out["killed"]  # live parent


def test_reap_orphaned_mcp_skips_supervisor(monkeypatch) -> None:
    procs = [
        {
            "pid": 404,
            "ppid": 5512,
            "exe": "",
            "cmdline": r"python.exe -u -m pipeline engine supervisor --logon",
        }
    ]
    monkeypatch.setattr(
        "pipeline.process_control.enumerate_scubiee_processes",
        lambda **_k: procs,
    )
    monkeypatch.setattr("pipeline.process_control._pid_alive", lambda pid: False)
    monkeypatch.setattr(
        "pipeline.process_control.safe_terminate_pid",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not kill supervisor")),
    )
    out = reap_orphaned_mcp_processes()
    assert out["killed"] == []
    assert 404 in out["skipped"]

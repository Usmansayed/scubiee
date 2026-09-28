"""Issue 2 follow-up: a healthy engine was force-restarted as a "hung prewarm".

On Windows, deleting or renaming over a file another process holds open fails
(WinError 32/5). Both prewarm markers swallowed that error, so a reader holding
the file at the wrong moment left "prewarm" on disk while the embedder was
loaded, and the watchdog killed the engine once the grace window ran out.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows share-mode semantics")


@windows_only
def test_clearing_the_busy_stamp_while_a_reader_holds_it(tmp_path: Path, monkeypatch) -> None:
    from pipeline import engine as eng
    from pipeline import warm_autoload as wa

    stamp = tmp_path / "embed_prewarm.busy"
    monkeypatch.setattr(eng, "_prewarm_busy_path", lambda: stamp)
    stamp.write_text(f"{time.time() - 600} {os.getpid()}", encoding="utf-8")
    with open(stamp, encoding="utf-8"):  # the watchdog mid-read
        eng._mark_prewarm_busy(False)
        assert wa.hung_prewarm_should_abort(max_age_s=45.0) is False, (
            "a cleared stamp must not read as a live, hung prewarm"
        )
    assert eng.prewarm_busy_stamp_active() is False


@windows_only
def test_phase_reaches_disk_while_a_reader_holds_the_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import engine as eng
    from pipeline import warm_autoload as wa

    monkeypatch.setattr(eng, "_prewarm_busy_path", lambda: tmp_path / "embed_prewarm.busy")
    wa.set_phase(wa.PHASE_PREWARM)
    with open(wa.phase_path(), encoding="utf-8"):  # a bridge/watchdog read in progress
        wa.set_phase(wa.PHASE_DENSE)
    disk = json.loads(wa.phase_path().read_text(encoding="utf-8"))
    assert disk["phase"] == wa.PHASE_DENSE, "other processes read the disk copy"
    assert not list(tmp_path.glob("warm_phase.*.tmp")), "no temp files left behind"


def test_neutralised_stamp_is_not_a_live_writer(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import engine as eng
    from pipeline import warm_autoload as wa

    stamp = tmp_path / "embed_prewarm.busy"
    monkeypatch.setattr(eng, "_prewarm_busy_path", lambda: stamp)
    wa._PHASE = wa.PHASE_DOWN
    wa._UPDATED_AT = 0.0
    wa.mark_down()
    stamp.write_text("0 0", encoding="utf-8")
    assert wa.hung_prewarm_should_abort(max_age_s=45.0) is False


def test_watchdog_does_not_restart_when_the_engine_reports_the_embedder_loaded(
    monkeypatch, tmp_path: Path
) -> None:
    """Belt and braces: whatever the marker files say, a loaded embedder is not hung."""
    monkeypatch.setenv("CTX_HOME", str(tmp_path))
    from pipeline import watchdog as wd

    monkeypatch.setattr(wd, "_health_ok", lambda: True)
    monkeypatch.setattr("pipeline.warm_autoload.hung_prewarm_should_abort", lambda **_k: True)
    monkeypatch.setattr(wd, "prewarm_still_progressing", lambda **_k: (False, 0.0))

    class _Client:
        def __init__(self, *_a, **_k):
            pass

        def get(self, _path):
            return {"warm_state": "ready", "chunks": 7000, "embedder_loaded": True}

    monkeypatch.setattr("pipeline.client.EngineClient", _Client)
    restarts: list[str] = []
    monkeypatch.setattr(
        "pipeline.daemon.force_restart_daemon", lambda *a, **k: restarts.append("restart") or {"ok": True}
    )
    logs: list[str] = []
    monkeypatch.setattr(wd, "_log", logs.append)

    wd.watchdog_loop(stop_after=1.2)

    assert restarts == []
    assert any("embedder_loaded=True" in line for line in logs), logs
    assert not any("hung prewarm" in line for line in logs), logs

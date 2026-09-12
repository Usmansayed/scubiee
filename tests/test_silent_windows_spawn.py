"""Silent Windows spawn/kill helpers — no console flash."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.mark.skipif(os.name != "nt", reason="Windows-only flash contract")
def test_hidden_run_sets_create_no_window() -> None:
    from pipeline.process_job import CREATE_NO_WINDOW, hidden_run

    with patch("pipeline.process_job.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess(["x"], 0)
        hidden_run(["taskkill", "/PID", "1", "/F"], capture_output=True, check=False)
    kwargs = run.call_args.kwargs
    assert kwargs.get("creationflags", 0) & CREATE_NO_WINDOW


@pytest.mark.skipif(os.name != "nt", reason="Windows-only flash contract")
def test_taskkill_silent_uses_hidden_run() -> None:
    from pipeline.process_job import taskkill_silent

    with patch("pipeline.process_job.hidden_run") as hr:
        hr.return_value = subprocess.CompletedProcess(["taskkill"], 0)
        taskkill_silent(4242, tree=True)
    args = hr.call_args.args[0]
    assert args[:2] == ["taskkill", "/PID"]
    assert "4242" in args
    assert "/T" in args
    assert "/F" in args


def test_no_raw_taskkill_subprocess_in_hot_paths() -> None:
    """Guard against regressions that reintroduce flashing taskkill Popen/run."""
    root = Path(__file__).resolve().parents[1] / "packages" / "pipeline"
    offenders: list[str] = []
    for name in ("daemon.py", "watchdog.py", "process_control.py", "mcp_bridge.py"):
        text = (root / name).read_text(encoding="utf-8")
        # Allow comments / powershell scripts mentioning taskkill; ban direct argv lists.
        if '["taskkill"' in text or "['taskkill'" in text:
            offenders.append(name)
    assert offenders == [], f"raw taskkill argv still in: {offenders}"

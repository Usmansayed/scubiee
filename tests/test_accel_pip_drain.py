"""pip install must drain stdout or Windows deadlocks."""

from __future__ import annotations

import os
import sys

from pipeline.accel import _run_pip_captured


def test_run_pip_captured_drains_large_stdout():
    rc, out = _run_pip_captured(
        [sys.executable, "-c", "print('x' * 80000, end='')"],
        os.environ.copy(),
    )
    assert rc == 0
    assert len(out) >= 80000

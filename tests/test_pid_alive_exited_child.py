"""A killed child its parent has not waited on must count as dead on every OS.

POSIX keeps it as a zombie; Windows keeps the process object alive while any
handle (here the Popen) is open, so OpenProcess alone still succeeds."""
from __future__ import annotations

import subprocess
import sys
import time

import pytest


@pytest.fixture
def killed_unwaited_child():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    proc.kill()
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            import psutil

            if not psutil.pid_exists(proc.pid) or psutil.Process(proc.pid).status() == psutil.STATUS_ZOMBIE:
                break
        except Exception:  # noqa: BLE001
            break
        time.sleep(0.05)
    time.sleep(0.2)
    yield proc
    proc.wait()


def test_daemon_pid_alive_false_for_killed_child(killed_unwaited_child) -> None:
    from pipeline import daemon as d

    assert d._pid_alive(killed_unwaited_child.pid) is False
    assert d._pid_running(killed_unwaited_child.pid) is False
    assert d.pid_is_zombie(killed_unwaited_child.pid) is True


def test_watchdog_and_lifecycle_pid_checks_agree(killed_unwaited_child) -> None:
    from pipeline import lifecycle_runtime, watchdog

    assert watchdog._pid_alive(killed_unwaited_child.pid) is False
    assert lifecycle_runtime._pid_alive(killed_unwaited_child.pid) is False


def test_live_process_is_alive() -> None:
    import os

    from pipeline import daemon as d

    assert d._pid_alive(os.getpid()) is True
    assert d.pid_is_zombie(os.getpid()) is False

from __future__ import annotations

import json
import threading
from pathlib import Path

from pipeline.dashboard_port import (
    DashboardLock,
    allocate_dashboard_port,
    preferred_dashboard_port,
)


def test_preferred_port_stable_and_private() -> None:
    a = preferred_dashboard_port("ce-install-1")
    b = preferred_dashboard_port("ce-install-1")

    assert a == b
    assert 49152 <= a <= 65535


def test_allocate_skips_busy_port(monkeypatch) -> None:
    preferred = preferred_dashboard_port("seed")
    busy = {preferred}

    def fake_bind(port: int) -> bool:
        return port not in busy

    monkeypatch.setattr("pipeline.dashboard_port._port_free", fake_bind)

    got = allocate_dashboard_port("seed", preferred=preferred)

    assert got == preferred + 1
    assert 49152 <= got <= 65535


def test_allocate_wraps_at_top_of_private_range(monkeypatch) -> None:
    monkeypatch.setattr(
        "pipeline.dashboard_port._port_free",
        lambda port: port == 49152,
    )

    assert allocate_dashboard_port("seed", preferred=65535) == 49152


def test_dashboard_lock_acquire_writes_state_atomically(tmp_path: Path) -> None:
    state_path = tmp_path / "home" / ".context-engine" / "dashboard.json"
    lock = DashboardLock(path=state_path)

    state = lock.acquire("http://127.0.0.1:54321/ce-dashboard", 1234)

    assert state == lock.read()
    assert state["host"] == "127.0.0.1"
    assert state["port"] == 54321
    assert state["url"] == "http://127.0.0.1:54321/ce-dashboard"
    assert state["pid"] == 1234
    assert isinstance(state["started_at"], float)
    assert json.loads(state_path.read_text(encoding="utf-8")) == state
    assert {path.name for path in state_path.parent.iterdir()} == {
        "dashboard.json",
        "dashboard.json.lock",
    }


def test_dashboard_lock_releases_only_for_owner(tmp_path: Path) -> None:
    state_path = tmp_path / "dashboard.json"
    lock = DashboardLock(path=state_path)
    lock.acquire("http://127.0.0.1:54321/ce-dashboard", 1234)

    assert lock.release_if_owner(9999) is False
    assert state_path.is_file()
    assert lock.release_if_owner(1234) is True
    assert not state_path.exists()
    assert lock.read() is None


def test_release_does_not_delete_replacement_between_read_and_unlink(
    tmp_path: Path, monkeypatch
) -> None:
    state_path = tmp_path / "dashboard.json"
    owner = DashboardLock(path=state_path)
    replacement = DashboardLock(path=state_path)
    owner.acquire("http://127.0.0.1:54321/ce-dashboard", 1234)

    replacement_started = threading.Event()
    replacement_done = threading.Event()
    replacement_thread: list[threading.Thread] = []
    real_unlink = Path.unlink

    def publish_replacement() -> None:
        replacement_started.set()
        replacement.acquire("http://127.0.0.1:54322/ce-dashboard", 5678)
        replacement_done.set()

    def unlink_after_replacement_attempt(
        path: Path, *args, **kwargs
    ) -> None:
        if path == state_path:
            thread = threading.Thread(target=publish_replacement)
            replacement_thread.append(thread)
            thread.start()
            assert replacement_started.wait(timeout=1)
            replacement_done.wait(timeout=0.2)
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink_after_replacement_attempt)

    assert owner.release_if_owner(1234) is True
    assert replacement_done.wait(timeout=2)
    replacement_thread[0].join(timeout=2)
    assert replacement.read()["pid"] == 5678

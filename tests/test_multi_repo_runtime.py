from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from conftest import enroll_test_repo


def _wait_until(predicate, timeout_s: float = 1.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition did not become true")


def test_same_repo_sessions_share_one_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    from pipeline.repo_runtime import RepoHub

    repo = tmp_path / "repo"
    repo.mkdir()
    enroll_test_repo(repo, home=home, project_id="ce_multi_same1234567890abcdef")
    hub = RepoHub()

    first = hub.ensure(repo, session_id="session-a")
    second = hub.ensure(repo, session_id="session-b")

    assert first is second
    assert first.sessions == {"session-a", "session-b"}


def test_different_repositories_keep_independent_engines_and_keepers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    from pipeline.repo_runtime import RepoHub

    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    enroll_test_repo(left, home=home, project_id="ce_multi_left1234567890abcdef")
    enroll_test_repo(right, home=home, project_id="ce_multi_right1234567890abcdef")
    hub = RepoHub()
    left_runtime = hub.ensure(left)
    right_runtime = hub.ensure(right)
    left_runtime.engine = object()
    left_runtime.keeper = object()

    assert left_runtime is not right_runtime
    assert right_runtime.engine is None
    assert right_runtime.keeper is None
    assert hub.get(left_runtime.project_id) is left_runtime
    assert hub.get(right_runtime.project_id) is right_runtime


def test_runtime_manager_preserves_active_facade_per_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    from pipeline.ce_service import RuntimeManager

    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    enroll_test_repo(first, home=home, project_id="ce_multi_first1234567890abcdef")
    enroll_test_repo(second, home=home, project_id="ce_multi_second1234567890abcdef")
    manager = RuntimeManager()
    manager._activate_runtime(first)
    first_engine = object()
    manager.engine = first_engine
    manager.generation = 7

    manager._activate_runtime(second)
    assert manager.engine is None
    manager.engine = object()

    manager._activate_runtime(first)
    assert manager.engine is first_engine
    assert manager.generation == 7


def test_active_work_outranks_idle_work() -> None:
    from pipeline.fair_schedule import FairEmbedScheduler

    scheduler = FairEmbedScheduler()
    assert scheduler.acquire("holder", "recent", timeout_s=0.1)
    order: list[str] = []

    def queued(project_id: str, priority: str) -> None:
        assert scheduler.acquire(project_id, priority, timeout_s=1)
        order.append(project_id)
        scheduler.release(project_id)

    idle = threading.Thread(target=queued, args=("idle", "idle"))
    active = threading.Thread(target=queued, args=("active", "active"))
    idle.start()
    _wait_until(lambda: scheduler.status()["queued"] == 1)
    active.start()
    _wait_until(lambda: scheduler.status()["queued"] == 2)
    scheduler.release("holder")
    idle.join(1)
    active.join(1)

    assert order == ["active", "idle"]


def test_equal_priority_requests_are_fifo() -> None:
    from pipeline.fair_schedule import FairEmbedScheduler

    scheduler = FairEmbedScheduler()
    assert scheduler.acquire("holder", "recent", timeout_s=0.1)
    order: list[str] = []

    def queued(project_id: str) -> None:
        assert scheduler.acquire(project_id, "recent", timeout_s=1)
        order.append(project_id)
        scheduler.release(project_id)

    first = threading.Thread(target=queued, args=("first",))
    second = threading.Thread(target=queued, args=("second",))
    first.start()
    _wait_until(lambda: scheduler.status()["queued"] == 1)
    second.start()
    _wait_until(lambda: scheduler.status()["queued"] == 2)
    scheduler.release("holder")
    first.join(1)
    second.join(1)

    assert order == ["first", "second"]


def test_aging_prevents_idle_starvation() -> None:
    from pipeline.fair_schedule import FairEmbedScheduler

    scheduler = FairEmbedScheduler(aging_s=0.01)
    assert scheduler.acquire("holder", "active", timeout_s=0.1)
    order: list[str] = []

    def queued(project_id: str, priority: str) -> None:
        assert scheduler.acquire(project_id, priority, timeout_s=1)
        order.append(project_id)
        scheduler.release(project_id)

    idle = threading.Thread(target=queued, args=("idle", "idle"))
    idle.start()
    _wait_until(lambda: scheduler.status()["queued"] == 1)
    time.sleep(0.04)
    active = threading.Thread(target=queued, args=("active", "active"))
    active.start()
    _wait_until(lambda: scheduler.status()["queued"] == 2)
    scheduler.release("holder")
    idle.join(1)
    active.join(1)

    assert order == ["idle", "active"]


def test_resource_manager_uses_process_wide_scheduler_for_embed_jobs() -> None:
    from pipeline.fair_schedule import reset_embed_scheduler_for_tests
    from pipeline.resources import get_resource_manager, reset_resource_manager_for_tests

    reset_embed_scheduler_for_tests()
    reset_resource_manager_for_tests()
    manager = get_resource_manager()

    assert manager.run_job("embed", lambda: "embedded", project_id="project-a") == "embedded"
    assert manager.status()["embed_scheduler"]["holder"] is None


def test_drop_engine_preserves_other_repository_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from pipeline.engine import _ENGINES, clear_engines, drop_engine

    clear_engines()
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    _ENGINES[f"{left.resolve()}::"] = object()
    _ENGINES[f"{right.resolve()}::"] = object()

    assert drop_engine(left) is True
    assert f"{left.resolve()}::" not in _ENGINES
    assert f"{right.resolve()}::" in _ENGINES
    clear_engines()


def test_failure_is_isolated_to_its_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "ce-home"
    monkeypatch.setenv("CTX_HOME", str(home))
    from pipeline.repo_runtime import RepoHub

    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    enroll_test_repo(left, home=home, project_id="ce_multi_fail1234567890abcdef")
    enroll_test_repo(right, home=home, project_id="ce_multi_ok1234567890abcdef")
    hub = RepoHub()
    failed = hub.ensure(left)
    healthy = hub.ensure(right)

    hub.isolate_failure(failed.project_id, RuntimeError("broken index"))

    assert failed.error == "broken index"
    assert failed.warm_state == "error"
    assert healthy.error is None
    assert healthy.warm_state == "idle"

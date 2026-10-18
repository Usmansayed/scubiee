"""wipe --all speed: bounded repo scan, no idle sleeps, background delete (journey #10)."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from pipeline import process_control, wipe


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "users" / "me"
    home.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setenv("CTX_HOME", str(home / ".scubiee"))
    return home


def test_discover_refuses_home_and_its_ancestors_without_walking(fake_home: Path, monkeypatch) -> None:
    (fake_home / ".scubiee").mkdir()
    (fake_home / "proj" / ".scubiee").mkdir(parents=True)

    def boom(*_a, **_k):
        raise AssertionError("must not walk a broad root")

    monkeypatch.setattr(wipe.os, "walk", boom)
    assert wipe._discover_repo_id_dirs(fake_home) == []
    assert wipe._discover_repo_id_dirs(fake_home.parent) == []
    assert wipe._discover_repo_id_dirs(Path(fake_home.anchor)) == []


def test_discover_skips_dependency_trees_and_finds_nested_checkouts(fake_home: Path) -> None:
    repo = fake_home / "work" / "app"
    (repo / ".scubiee").mkdir(parents=True)
    (repo / "packages" / "sub" / ".scubiee").mkdir(parents=True)
    (repo / "node_modules" / "dep" / ".scubiee").mkdir(parents=True)
    (repo / ".venv" / "lib" / ".scubiee").mkdir(parents=True)

    found = {p.relative_to(repo).as_posix() for p in wipe._discover_repo_id_dirs(repo)}

    assert found == {".scubiee", "packages/sub/.scubiee"}


def test_discover_depth_is_capped(fake_home: Path) -> None:
    repo = fake_home / "work" / "app"
    shallow = repo / "a" / "b" / "c" / ".scubiee"
    deep = repo / "a" / "b" / "c" / "d" / "e" / ".scubiee"
    shallow.mkdir(parents=True)
    deep.mkdir(parents=True)

    found = wipe._discover_repo_id_dirs(repo)

    assert shallow in found and deep not in found


def test_discover_never_returns_the_machine_home(fake_home: Path, monkeypatch) -> None:
    repo = fake_home / "work" / "app"
    repo.mkdir(parents=True)
    machine = repo / "nested-home" / ".scubiee"
    machine.mkdir(parents=True)
    monkeypatch.setenv("CTX_HOME", str(machine))

    assert machine not in wipe._discover_repo_id_dirs(repo)


def test_only_real_repos_are_added_as_wipe_targets(fake_home: Path) -> None:
    plain = fake_home / "Downloads"
    plain.mkdir()
    git_repo = fake_home / "code" / "a"
    (git_repo / ".git").mkdir(parents=True)
    enrolled = fake_home / "code" / "b"
    (enrolled / ".scubiee").mkdir(parents=True)

    assert not wipe._looks_like_repo(fake_home)
    assert not wipe._looks_like_repo(fake_home.parent)
    assert not wipe._looks_like_repo(plain)
    assert wipe._looks_like_repo(git_repo)
    assert wipe._looks_like_repo(enrolled)


def test_rm_tree_background_renames_aside_instantly(tmp_path: Path) -> None:
    target = tmp_path / ".scubiee"
    (target / "indexes").mkdir(parents=True)
    (target / "indexes" / "a.bin").write_bytes(b"x" * 1024)
    trash: list[Path] = []

    out = wipe._rm_tree_background(target, trash)

    assert out["removed"] and not target.exists()
    assert len(trash) == 1 and trash[0].is_dir()
    assert wipe._rm_tree_background(target, trash)["missing"]


def test_scheduled_delete_runs_after_the_waited_process_exits(tmp_path: Path) -> None:
    a = tmp_path / "a.trash-1"
    b = tmp_path / "b with space.trash-1"
    for d in (a, b):
        (d / "x").mkdir(parents=True)
        (d / "x" / "f.txt").write_text("data", encoding="utf-8")
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.0)"])

    out = process_control.schedule_delete_paths_after_exit([a, b], holder.pid)
    assert out["scheduled"]
    assert a.exists()
    holder.wait()
    deadline = time.time() + 30
    while time.time() < deadline and (a.exists() or b.exists()):
        time.sleep(0.2)

    assert not a.exists() and not b.exists()


def test_kill_all_fast_path_skips_stop_passes_when_nothing_runs(fake_home: Path, monkeypatch) -> None:
    monkeypatch.setattr(process_control, "_anything_scubiee_running", lambda **_k: False)

    def boom(*_a, **_k):
        raise AssertionError("stop pass must be skipped")

    monkeypatch.setattr(process_control, "stop_all_context_engine_processes", boom)
    monkeypatch.setattr(process_control, "stop_engine_worker_processes", boom)

    out = process_control.kill_all_scubiee_processes(rounds=5)

    assert out["ok"] and out["fast_path"] == "nothing_running" and out["remaining_pids"] == []


def test_kill_all_still_runs_full_pass_when_something_runs(fake_home: Path, monkeypatch) -> None:
    monkeypatch.setattr(process_control, "_anything_scubiee_running", lambda **_k: True)
    calls: list[str] = []
    monkeypatch.setattr(
        process_control, "stop_engine_worker_processes", lambda: calls.append("workers") or {}
    )
    monkeypatch.setattr(
        process_control,
        "stop_all_context_engine_processes",
        lambda **_k: calls.append("stop_all") or {},
    )
    monkeypatch.setattr(process_control, "enumerate_scubiee_processes", lambda **_k: [])
    monkeypatch.setattr(process_control, "uv_tool_root", lambda *_a: None)

    out = process_control.kill_all_scubiee_processes(rounds=1)

    assert calls == ["workers", "stop_all"] and out["ok"] and "fast_path" not in out


def test_stop_processes_under_does_not_sleep_when_nothing_to_kill(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(process_control, "processes_under", lambda _root: [])
    slept: list[float] = []
    monkeypatch.setattr(process_control.time, "sleep", lambda s: slept.append(s))

    out = process_control.stop_processes_under(tmp_path, grace_s=1.0)

    assert out["killed"] == [] and slept == []


def test_settle_sleep_skipped_when_no_scubiee_process(fake_home: Path, monkeypatch) -> None:
    monkeypatch.setattr(process_control, "stub_mcp_commands_to_noop", lambda **_k: {"stubbed": ["x"]})
    monkeypatch.setattr(process_control, "enumerate_scubiee_processes", lambda **_k: [])
    monkeypatch.setattr(
        process_control,
        "kill_all_scubiee_processes",
        lambda **_k: {"ok": True, "remaining_pids": []},
    )
    monkeypatch.setattr(process_control, "disable_mcp_to_prevent_respawn", lambda **_k: {"ok": True})
    slept: list[float] = []
    monkeypatch.setattr(process_control.time, "sleep", lambda s: slept.append(s))

    out = process_control.release_scubiee_process_locks()

    assert out["settle_skipped"] == "no_scubiee_processes" and slept == []

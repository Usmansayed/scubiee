"""Shared pytest fixtures.

Unit tests must be deterministic regardless of how the process was launched. The
SDK trial harness runs the workspace's baseline pytest with ``CTX_MCP_SURFACE``
set in the environment (to A/B the ``read`` vs ``graph`` MCP surfaces), which
would otherwise leak into and flip surface-specific assertions. Neutralise it by
default; tests that want a specific surface opt in via ``monkeypatch.setenv``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Env keys written by ``apply_index_memory_budget`` / similar without always
# going through monkeypatch — clear between tests so ResourceManager ceilings
# and refuse logic stay deterministic in the full suite.
_LEAKY_CTX_KEYS = (
    "CTX_CE_MEMORY_MODE",
    "CTX_CE_RSS_CAP_MB",
    "CTX_SCUBIEE_TOTAL_RSS_MB",
    "CTX_CE_EMB_BATCH_CEILING",
    "CTX_CE_AGGRESSIVE_UNLOAD",
    "CTX_MLX_DTYPE",
    "CTX_MLX_FAST_ATTN",
    "CTX_MLX_FAST_LN",
    "CTX_MLX_EVAL",
    "CTX_MLX_CACHE_MB",
    "CTX_CPU_EMBED_THREADS",
    "CTX_EMBED_BATCH",
    "CTX_RM_DISABLE",
)


@pytest.fixture(autouse=True)
def _restore_repo_local_state():
    """Keep the checkout's own enrollment/MCP files pristine across tests.

    Several suites hand the real repo root to product code while ``CTX_HOME`` is
    isolated. The repo is unknown to that empty registry, so it gets re-enrolled
    and ``.scubiee/id.json`` is rewritten with a fresh project id (and MCP pins
    follow). Left in place that leaks into later tests — and into the developer's
    IDE — so snapshot these two files and put them back.
    """
    root = Path(__file__).resolve().parents[1]
    watched = (root / ".scubiee" / "id.json", root / ".cursor" / "mcp.json")
    before = {path: (path.read_bytes() if path.is_file() else None) for path in watched}
    yield
    for path, original in before.items():
        try:
            current = path.read_bytes() if path.is_file() else None
            if current == original:
                continue
            if original is None:
                path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(original)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def _guard_real_scubiee_home(request):
    """Fail loudly if a test destroys the operator's real ``~/.scubiee``.

    ``wipe_all`` sweeps the ``Path.home()`` defaults on top of ``CTX_HOME``
    (see ``_context_engine_homes``), so the autouse ``CTX_HOME`` isolation alone
    does not sandbox destructive paths — those tests must fake ``Path.home()``
    too. Without this guard a plain ``pytest`` run silently wipes the machine's
    accel profile, index, and IDE MCP config while still reporting green.
    """
    real = Path.home() / ".scubiee"
    existed = real.is_dir()
    yield
    if existed and not real.is_dir():
        pytest.fail(
            f"{request.node.nodeid} deleted the real Scubiee home {real}. "
            "Destructive tests must monkeypatch Path.home() as well as CTX_HOME.",
            pytrace=False,
        )


@pytest.fixture(autouse=True)
def _neutral_mcp_surface(monkeypatch):
    monkeypatch.delenv("CTX_MCP_SURFACE", raising=False)
    yield


@pytest.fixture(autouse=True)
def _clear_leaky_ctx_env():
    previous = {key: os.environ.get(key) for key in _LEAKY_CTX_KEYS}
    for key in _LEAKY_CTX_KEYS:
        os.environ.pop(key, None)
    yield
    for key, value in previous.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.fixture(autouse=True)
def _isolate_scubiee_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Each test gets a fresh ``~/.scubiee`` — no leaked global pause state."""
    home = tmp_path / "scubiee-test-home"
    home.mkdir()
    monkeypatch.setenv("CTX_HOME", str(home))
    monkeypatch.setenv("CTX_ALLOW_TEST_HOME", "1")
    # Unit tests never WMI-create a real engine (tests that need it opt in).
    monkeypatch.setenv("CTX_ENGINE_ORPHAN_SPAWN", "0")
    # Keeper tests fake _sync_paths; the child-process graph merge opts in.
    monkeypatch.setenv("CTX_GRAPH_CATCHUP_ASYNC", "0")
    # ce_service._start_keeper sets this in os.environ for the engine process.
    # Tests that start a keeper leaked it into every later test, where it made
    # the ledger defer batches as "embedder_cold". monkeypatch's undo removes
    # it again after each test.
    monkeypatch.delenv("CTX_SYNC_WAIT_FOR_EMBEDDER", raising=False)
    yield home


def _pytest_owns(pid: int) -> bool:
    """True for this pytest process and anything it spawned."""
    me = os.getpid()
    if int(pid) == me:
        return True
    try:
        import psutil

        return any(c.pid == int(pid) for c in psutil.Process(me).children(recursive=True))
    except Exception:  # noqa: BLE001
        return False


_REAL_REPO = Path(__file__).resolve().parents[1]
_GUARDED_MCP_CONFIGS = [
    _REAL_REPO / ".cursor" / "mcp.json",
    _REAL_REPO / ".kiro" / "settings" / "mcp.json",
    _REAL_REPO / ".vscode" / "mcp.json",
    _REAL_REPO / ".mcp.json",
    Path.home() / ".cursor" / "mcp.json",
    Path.home() / ".kiro" / "settings" / "mcp.json",
]


@pytest.fixture(autouse=True)
def _never_touch_the_developers_mcp_configs(request: pytest.FixtureRequest):
    """Restore real MCP configs a test rewrote.

    ``stub_mcp_commands_to_noop`` walks ``Path.cwd()`` (the checkout under
    pytest) and the home-level legacy paths. A full-suite run pointed this
    repo's ``.cursor/mcp.json`` at ``cmd /c exit 0``, so every MCP session
    afterwards died on initialize ("Not connected", issue 7).
    """
    before: dict[Path, bytes | None] = {}
    for p in _GUARDED_MCP_CONFIGS:
        try:
            before[p] = p.read_bytes()
        except OSError:
            before[p] = None
    yield
    for p, data in before.items():
        try:
            now = p.read_bytes()
        except OSError:
            now = None
        if now == data:
            continue
        try:
            if data is None:
                p.unlink(missing_ok=True)
            else:
                p.write_bytes(data)
        except OSError:
            continue
        msg = f"[conftest] restored {p} rewritten by {request.node.nodeid}\n"
        sys.__stderr__.write(msg)
        try:
            log = Path(os.environ.get("TEMP") or "/tmp") / "conftest_mcp_restores.log"
            with log.open("a", encoding="utf-8") as fh:
                fh.write(msg)
        except OSError:
            pass


@pytest.fixture(autouse=True)
def _never_kill_the_developers_processes(monkeypatch: pytest.MonkeyPatch):
    """Unit tests may only kill processes they started.

    ``test_wipe_repo_halts_before_removal`` ran the real post-wipe restart and
    killed the live engine plus every uv-tool Scubiee process (MCP bridges,
    watchdog) on the developer's machine: the silent "engine died" and "Not
    connected" reports behind issues 2 and 7. Tests that exercise the kill
    helpers monkeypatch them (or psutil) themselves, which overrides this.
    """
    import psutil

    blocked: list[tuple[str, int]] = []
    real_kill, real_terminate = psutil.Process.kill, psutil.Process.terminate
    real_os_kill = os.kill

    def _guard(name, real):
        def _wrapped(self, *a, **k):
            if not _pytest_owns(self.pid):
                blocked.append((name, self.pid))
                return None
            return real(self, *a, **k)

        return _wrapped

    def _os_kill(pid, sig):
        if sig != 0 and not _pytest_owns(pid):
            blocked.append(("os.kill", int(pid)))
            return None
        return real_os_kill(pid, sig)

    monkeypatch.setattr(psutil.Process, "kill", _guard("psutil.kill", real_kill))
    monkeypatch.setattr(psutil.Process, "terminate", _guard("psutil.terminate", real_terminate))
    monkeypatch.setattr(os, "kill", _os_kill)
    try:
        import pipeline.process_job as pj

        real_taskkill = pj.taskkill_silent

        def _taskkill(pid, *a, **k):
            if not _pytest_owns(pid):
                blocked.append(("taskkill", int(pid)))
                return None
            return real_taskkill(pid, *a, **k)

        _taskkill.__wrapped__ = real_taskkill  # type: ignore[attr-defined]
        monkeypatch.setattr(pj, "taskkill_silent", _taskkill)
    except Exception:  # noqa: BLE001
        pass
    yield blocked


def write_machine_setup(home: Path) -> Path:
    """Minimal ``accel.json`` so ``require_machine_setup()`` passes in tests."""
    home.mkdir(parents=True, exist_ok=True)
    accel = home / "accel.json"
    if not accel.is_file():
        accel.write_text("{}\n", encoding="utf-8")
    return home


def enroll_test_repo(
    repo: Path,
    *,
    home: Path,
    project_id: str = "ce_test1234567890abcdef12345678",
) -> str:
    """Register *repo* as managed without implicit bind side effects."""
    import json

    from pipeline.project_id import mutate_registry

    write_machine_setup(home)
    ce = repo / ".scubiee"
    ce.mkdir(parents=True, exist_ok=True)
    (ce / "id.json").write_text(
        json.dumps({"project_id": project_id}), encoding="utf-8"
    )
    root = str(repo.resolve())

    def _add(reg: dict) -> str:
        projects = reg.setdefault("projects", {})
        projects[project_id] = {
            "managed": True,
            "root": root,
            "paths": [root],
        }
        return project_id

    mutate_registry(_add)
    return project_id


@pytest.fixture
def cpu_accel_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Persist a CPU accel.json under an isolated ``CTX_HOME`` for semantic tests."""
    home = tmp_path / "ce-home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("CTX_HOME", str(home))
    from pipeline import accel
    from pipeline.accel import AccelProfile, save_accel

    path = home / "accel.json"
    monkeypatch.setattr(accel, "ACCEL_PATH", path)
    profile = AccelProfile(
        profile="cpu",
        provider="CPUExecutionProvider",
        backend="fastembed",
        batch_size=16,
        texts_per_sec=2.0,
        reason="pytest fixture",
    )
    save_accel(profile, path=path)

    def _fake_inspect_accel(**kwargs):
        validation = {
            "ok": True,
            "profile": profile.profile,
            "provider": profile.provider,
            "available_providers": [profile.provider],
            "provider_available": True,
            "model_warm": True,
            "detail": "pytest fixture",
        }
        return {
            "ok": True,
            "profile": profile.profile,
            "provider": profile.provider,
            "batch_size": profile.batch_size,
            "backend": profile.backend,
            "texts_per_sec": profile.texts_per_sec,
            "reason": profile.reason,
            "fastembed": True,
            "onnxruntime": True,
            "providers": [profile.provider],
            "provider_ok": True,
            "model_warm": True,
            "provider_validation": validation,
            "missing": [],
            "hint": "",
        }

    monkeypatch.setattr("pipeline.preflight.inspect_accel", _fake_inspect_accel)
    return path

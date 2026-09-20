"""Shared pytest fixtures.

Unit tests must be deterministic regardless of how the process was launched. The
SDK trial harness runs the workspace's baseline pytest with ``CTX_MCP_SURFACE``
set in the environment (to A/B the ``read`` vs ``graph`` MCP surfaces), which
would otherwise leak into and flip surface-specific assertions. Neutralise it by
default; tests that want a specific surface opt in via ``monkeypatch.setenv``.
"""

from __future__ import annotations

import os
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
    yield home


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

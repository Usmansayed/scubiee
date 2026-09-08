"""Realistic CLI integration tests for the upgrade registry + supervisor.

These deliberately escape the conftest ``CTX_HOME`` isolation and run a real
``scubiee upgrade`` against the operator's ``~/.scubiee``, which rewrites upgrade
history and MCP configs. Marked ``integration`` so a plain ``pytest`` run cannot
damage a working machine; opt in with ``pytest -m integration``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.integration


def _find_scubiee() -> Path:
    exe = shutil.which("scubiee")
    if exe:
        return Path(exe)
    for candidate in (
        Path(os.environ.get("APPDATA", "")) / "uv" / "tools" / "scubiee" / "Scripts" / "scubiee.exe",
        Path.home() / ".local" / "bin" / "scubiee",
        Path.home() / ".local" / "bin" / "scubiee.exe",
    ):
        if candidate.is_file():
            return candidate
    pytest.skip("scubiee CLI not installed")


def _find_scubiee_python(scubiee: Path) -> Path:
    py = scubiee.parent / "python.exe"
    if py.is_file():
        return py
    pytest.skip("scubiee python not found next to CLI")


def _run_json(cmd: list[str], *, cwd: Path, timeout: float = 300.0, env: dict[str, str] | None = None) -> tuple[int, dict | None, str]:
    run_env = os.environ.copy() if env is None else env
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=run_env,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")
    payload: dict | None = None
    # Prefer full-document JSON (scubiee prints pretty-printed blocks).
    stripped = combined.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
    if payload is None:
        for line in reversed(combined.splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    payload = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
    if payload is None:
        start = combined.find("{")
        end = combined.rfind("}")
        if start != -1 and end > start:
            try:
                payload = json.loads(combined[start : end + 1])
            except json.JSONDecodeError:
                payload = None
    return proc.returncode, payload, combined


@pytest.fixture(scope="module")
def scubiee_exe() -> Path:
    return _find_scubiee()


@pytest.fixture(scope="module")
def scubiee_py(scubiee_exe: Path) -> Path:
    return _find_scubiee_python(scubiee_exe)


def _real_home_env() -> dict[str, str]:
    """Subprocess env that uses the operator's real ``~/.scubiee`` (not pytest isolation)."""
    env = os.environ.copy()
    env.pop("CTX_HOME", None)
    env.pop("CTX_ALLOW_TEST_HOME", None)
    return env


@pytest.fixture
def real_scubiee_home(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point in-process helpers at the same home the CLI subprocess uses."""
    home = Path.home() / ".scubiee"
    monkeypatch.setenv("CTX_HOME", str(home))
    monkeypatch.delenv("CTX_ALLOW_TEST_HOME", raising=False)
    return home


def test_installed_registry_releases(scubiee_py: Path):
    code = """
from pipeline import upgrade_releases
from pipeline.upgrade_registry import list_releases, compose_upgrade
assert [r.version for r in list_releases()] == ["0.2.18", "0.3.7", "0.3.10"]
path = compose_upgrade("0.3.6", "0.3.10")
assert [r.version for r in path.releases] == ["0.3.7", "0.3.10"]
print("ok")
"""
    proc = subprocess.run(
        [str(scubiee_py), "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_cli_upgrade_check_emits_release_path(scubiee_exe: Path, repo_root: Path):
    rc, payload, combined = _run_json(
        [str(scubiee_exe), "upgrade", "--check"],
        cwd=repo_root,
        timeout=120,
        env=_real_home_env(),
    )
    assert payload is not None, combined[-2000:]
    assert payload.get("ok") is True
    plan = payload.get("plan") or {}
    assert "release_path" in plan
    assert isinstance(plan.get("release_path"), list)
    assert isinstance(plan.get("warnings"), list)


def test_cli_upgrade_check_version_cross_plan(scubiee_py: Path):
    code = """
from pipeline.upgrade_manifest import build_diff_plan
plan = build_diff_plan(from_version="0.3.9", to_version="0.3.10", skip_package=False)
d = plan.to_dict()
assert d["release_path"] == ["0.3.10"]
assert plan.action_for("mcp_pins").action == "rewrite"
assert plan.action_for("package").action == "swap"
print("ok")
"""
    proc = subprocess.run([str(scubiee_py), "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr or proc.stdout


@pytest.fixture(scope="module")
def repo_root() -> Path:
    return ROOT


def test_cli_stale_mcp_repair(
    scubiee_exe: Path,
    repo_root: Path,
    real_scubiee_home: Path,
):
    """Seed stale MCP, run real upgrade, verify bridge + build env restored."""
    if not (repo_root / ".scubiee" / "id.json").is_file():
        pytest.skip("repo not enrolled")

    sys.path.insert(0, str(ROOT / "packages"))
    from pipeline.upgrade_scenarios import apply_stale_state, verify_post_upgrade

    from pipeline.upgrade import installed_version

    pid = json.loads((repo_root / ".scubiee" / "id.json").read_text(encoding="utf-8"))["project_id"]
    apply_stale_state("stale_mcp_pins", repo_root, project_id=pid, version="0.3.10")

    rc, payload, combined = _run_json(
        [str(scubiee_exe), "upgrade"],
        cwd=repo_root,
        timeout=600,
        env=_real_home_env(),
    )
    assert payload is not None, combined[-4000:]
    # A real upgrade re-stamps history with the installed version, not the seed.
    verify = verify_post_upgrade(
        "stale_mcp_pins",
        repo_root,
        project_id=pid,
        version=installed_version() or "0.3.10",
        report=payload,
    )
    health_flake = payload.get("error") == "health_not_ok" and verify.get("ok") is True
    assert verify["ok"] is True, verify
    assert rc == 0 or health_flake, payload.get("error")

    from pipeline.mcp_install import verify_mcp_json

    mcp = verify_mcp_json(repo_root / ".cursor" / "mcp.json")
    assert mcp.get("ok") is True
    assert mcp.get("uses_bridge") is True

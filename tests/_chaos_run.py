"""One-off chaos harness — writes JSON lines to stdout for report compilation."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT
PYTHON = sys.executable


def run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None, timeout: float = 120) -> dict:
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd or REPO,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "cmd": cmd,
            "cwd": str(cwd or REPO),
            "exit": proc.returncode,
            "stdout": proc.stdout[-4000:] if proc.stdout else "",
            "stderr": proc.stderr[-2000:] if proc.stderr else "",
            "ms": round((time.perf_counter() - t0) * 1000, 1),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "cmd": cmd,
            "cwd": str(cwd or REPO),
            "exit": -1,
            "stdout": (exc.stdout or b"").decode("utf-8", errors="replace")[-2000:],
            "stderr": (exc.stderr or b"").decode("utf-8", errors="replace")[-2000:],
            "ms": round((time.perf_counter() - t0) * 1000, 1),
            "timeout": True,
        }


def http_get(url: str, timeout: float = 3) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return {"ok": True, "status": resp.status, "body": body[:1500]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def emit(phase: str, name: str, result: dict) -> None:
    row = {"phase": phase, "test": name, **result}
    print(json.dumps(row, default=str), flush=True)


def main() -> int:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO / "packages") + os.pathsep + env.get("PYTHONPATH", "")

    # --- Phase 1: CLI surface ---
    emit("cli", "pipeline_help", run([PYTHON, "-m", "pipeline", "--help"]))
    emit("cli", "ctx_no_args", run(["ctx"]))
    emit("cli", "ctx_version_flag", run(["ctx", "--version"]))
    emit("cli", "pip_show", run([PYTHON, "-m", "pip", "show", "scubiee"]))
    emit("cli", "preflight", run([PYTHON, "-m", "pipeline", "preflight", "."], env=env))
    emit("cli", "doctor", run([PYTHON, "-m", "pipeline", "doctor", "."], env=env, timeout=180))
    emit("cli", "list", run([PYTHON, "-m", "pipeline", "list"], env=env))

    # --- Phase 2: engine lifecycle ---
    emit("engine", "stop_clean", run([PYTHON, "-m", "pipeline", "engine", "stop"], env=env))
    emit("engine", "health_down", http_get("http://127.0.0.1:8765/health"))
    emit("engine", "search_while_down", run([PYTHON, "-m", "pipeline", "search", ".", "test query", "--top-k", "3"], env=env, timeout=30))
    emit("engine", "ensure", run([PYTHON, "-m", "pipeline", "engine", "ensure", "."], env=env, timeout=60))
    emit("engine", "health_up", http_get("http://127.0.0.1:8765/health"))
    emit("engine", "status", run([PYTHON, "-m", "pipeline", "engine", "status", "."], env=env, timeout=30))
    emit("engine", "sync_now", run([PYTHON, "-m", "pipeline", "sync-now", "."], env=env, timeout=120))
    emit("engine", "status_repo", run([PYTHON, "-m", "pipeline", "status", "."], env=env, timeout=30))

    # --- Phase 3: temp repo init + fast index ---
    tmp = Path(tempfile.mkdtemp(prefix="ce-chaos-"))
    try:
        (tmp / "src").mkdir()
        (tmp / "src" / "hello.py").write_text(
            'def chaos_beacon_x991():\n    return "chaos991"\n',
            encoding="utf-8",
        )
        emit("temp_repo", "init", run([PYTHON, "-m", "pipeline", "init", str(tmp), "--fast", "--roots", "src"], env=env, timeout=600))
        emit("temp_repo", "sync_now", run([PYTHON, "-m", "pipeline", "sync-now", str(tmp)], env=env, timeout=120))
        emit("temp_repo", "search", run([PYTHON, "-m", "pipeline", "search", str(tmp), "chaos_beacon_x991", "--top-k", "3"], env=env, timeout=60))
        (tmp / "src" / "newfile.py").write_text("NEW=1\n", encoding="utf-8")
        emit("temp_repo", "sync_after_newfile", run([PYTHON, "-m", "pipeline", "sync-now", str(tmp)], env=env, timeout=120))
        emit("temp_repo", "pause", run([PYTHON, "-m", "pipeline", "pause", str(tmp)], env=env))
        emit("temp_repo", "sync_while_paused", run([PYTHON, "-m", "pipeline", "sync-now", str(tmp)], env=env, timeout=60))
        emit("temp_repo", "resume", run([PYTHON, "-m", "pipeline", "resume", str(tmp)], env=env))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # --- Phase 4: stop engine mid ensure + double start ---
    emit("engine", "stop_before_chaos", run([PYTHON, "-m", "pipeline", "engine", "stop"], env=env))
    emit("engine", "double_ensure_1", run([PYTHON, "-m", "pipeline", "engine", "ensure", "."], env=env, timeout=60))
    emit("engine", "double_ensure_2", run([PYTHON, "-m", "pipeline", "engine", "ensure", "."], env=env, timeout=60))
    emit("engine", "start_when_running", run([PYTHON, "-m", "pipeline", "engine", "start", "."], env=env, timeout=30))

    # --- Phase 5: uninstall / reinstall ---
    emit("install", "pip_uninstall", run([PYTHON, "-m", "pip", "uninstall", "scubiee", "-y"], timeout=60))
    emit("install", "pipeline_after_uninstall", run([PYTHON, "-m", "pipeline", "engine", "status", "."], env=env, timeout=15))
    emit("install", "pip_reinstall_editable", run([PYTHON, "-m", "pip", "install", "-e", str(REPO)], timeout=180))
    emit("install", "pipeline_after_reinstall", run([PYTHON, "-m", "pipeline", "preflight", "."], env=env, timeout=30))
    emit("install", "ensure_after_reinstall", run([PYTHON, "-m", "pipeline", "engine", "ensure", "."], env=env, timeout=60))

    # --- Phase 6: setup skip-install (non-destructive) ---
    emit("setup", "setup_skip_install", run([PYTHON, "-m", "pipeline", "setup", "--skip-install"], env=env, timeout=120))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

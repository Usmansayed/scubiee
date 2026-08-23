"""Preflight gate for dev_mcp_vs_nomcp — all checks must pass before mcp arm."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = (ROOT / "testdata" / "frontend-mcp").resolve()
PACKAGES = ROOT / "packages"
CE_PY = Path.home() / "AppData" / "Roaming" / "uv" / "tools" / "scubiee" / "Scripts" / "python.exe"
if not CE_PY.is_file():
    CE_PY = Path(sys.executable)

_OPENCODE_EXE = (
    Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
)
OPENCODE = (
    str(_OPENCODE_EXE)
    if _OPENCODE_EXE.is_file()
    else (shutil.which("opencode") or shutil.which("opencode.cmd") or "opencode")
)


def _ce_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PACKAGES)
    env.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")
    env["CTX_ENGINE_IDLE_S"] = "0"
    env["CTX_WATCHDOG"] = "0"
    return env


def _search_ok(proc: subprocess.CompletedProcess[str]) -> bool:
    if proc.returncode != 0:
        return False
    text = (proc.stdout or "").strip()
    if not text:
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    if data.get("ok") is False or "error" in data:
        return False
    return "latency_ms" in data


def _run(cmd: list[str], *, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=str(ROOT), env=_ce_env(), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )


def main() -> int:
    checks: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append((name, ok, detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    # 1. Lifecycle: RUN mode + no stale idle anchor + register experiment client
    prep = _run([str(CE_PY), "-c", """
from pipeline.lifecycle_runtime import (
    DESIRED_RUN, load_policy, note_activity, register_client, save_policy, set_desired_mode,
)
set_desired_mode(DESIRED_RUN)
note_activity()
p = load_policy()
p["last_client_left_at"] = None
save_policy(p)
register_client("dev_mcp_vs_nomcp", kind="experiment")
print("ok")
"""], timeout=30)
    record("lifecycle_run", prep.returncode == 0, (prep.stdout or prep.stderr).strip()[-120:])

    # 2. Engine start
    start = _run(["scubiee", "engine", "start", str(REPO), "--wait", "300"], timeout=360)
    start_ok = False
    if start.returncode == 0:
        try:
            start_ok = json.loads(start.stdout or "{}").get("ok", False)
        except json.JSONDecodeError:
            pass
    record("engine_start", start_ok, (start.stdout or start.stderr)[-200:])

    # 3. Search smoke (poll up to 2 min)
    search_ok = False
    last_search = ""
    for i in range(24):
        s = _run(["scubiee", "search", "session evidence recall perception", str(REPO)], timeout=120)
        last_search = (s.stdout or s.stderr)[-200:]
        if _search_ok(s):
            search_ok = True
            record("search_smoke", True, f"attempt={i} latency_ok")
            break
        time.sleep(5)
    if not search_ok:
        record("search_smoke", False, last_search or "no response")

    # 4. Engine survives idle window (70s)
    time.sleep(70)
    alive = _run(["scubiee", "search", "test", str(REPO)], timeout=60)
    survive = _search_ok(alive)
    record("engine_survives_idle", survive, "still searchable after 70s")

    # 5. Index chunks
    st = _run(["scubiee", "status", str(REPO)], timeout=60)
    chunks_ok = False
    if st.returncode == 0:
        try:
            data = json.loads(st.stdout or "{}")
            chunks = data.get("chunks") or (data.get("meta") or {}).get("chunks")
            chunks_ok = int(chunks or 0) >= 3000
            record("indexed_chunks", chunks_ok, f"chunks={chunks}")
        except (json.JSONDecodeError, TypeError, ValueError):
            record("indexed_chunks", False, "parse error")
    else:
        record("indexed_chunks", False, st.stderr[-120:])

    # 6. OpenCode + MCP config
    oc = _run([OPENCODE, "--version"], timeout=30)
    record("opencode_cli", oc.returncode == 0, (oc.stdout or oc.stderr or "").strip()[:80])

    models = _run([OPENCODE, "models"], timeout=60)
    record("opencode_model", "x-preview-f-free" in (models.stdout or ""), "opencode/x-preview-f-free")

    cfg_path = Path.home() / ".config" / "opencode" / "config.json"
    mcp_ok = False
    if cfg_path.is_file():
        block = json.loads(cfg_path.read_text(encoding="utf-8")).get("mcp", {}).get("context-engine", {})
        mcp_ok = (
            isinstance(block, dict)
            and block.get("type") == "local"
            and block.get("enabled") is True
            and bool(block.get("command"))
        )
    record("opencode_mcp_schema", mcp_ok, str(cfg_path))

    conn = _run(["scubiee", "connect", "--opencode", "--repo", str(REPO)], timeout=60)
    record("scubiee_connect", conn.returncode == 0, (conn.stdout or "")[-120:])

    pf = _run(["scubiee", "preflight"], timeout=120)
    record("scubiee_preflight", pf.returncode == 0, (pf.stdout or pf.stderr)[-120:])

    # 7. nomcp artifact present
    nomcp = ROOT / "out" / "experiments" / "dev_mcp_vs_nomcp" / "nomcp_20260822T140106Z.json"
    record("nomcp_logged", nomcp.is_file(), str(nomcp))

    failed = [n for n, ok, _ in checks if not ok]
    print("\n=== SUMMARY ===")
    print(json.dumps({"passed": len(checks) - len(failed), "failed": failed}, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())

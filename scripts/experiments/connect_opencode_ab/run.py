"""OpenCode connect A/B with mandatory preflight before any OpenCode run."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "out" / "experiments" / "connect_opencode_ab"
MISSION = HERE / "mission.json"
INDEXED_REPO = (ROOT / "testdata" / "frontend-mcp").resolve()
PACKAGES = (ROOT / "packages").resolve()

_UV_PY = Path.home() / "AppData" / "Roaming" / "uv" / "tools" / "scubiee" / "Scripts" / "python.exe"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
CE_PY = _UV_PY if _UV_PY.is_file() else (VENV_PY if VENV_PY.is_file() else Path(sys.executable))

_OPENCODE_EXE = (
    Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
)
OPENCODE = (
    str(_OPENCODE_EXE)
    if _OPENCODE_EXE.is_file()
    else (shutil.which("opencode") or shutil.which("opencode.cmd") or "opencode")
)

COPY_EXCLUDED = {
    ".git", ".venv", ".context-engine", ".pytest_cache", "__pycache__",
    "out", ".env", "research", "testdata", "scripts", "vendor", "node_modules",
}


def _load_helper(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = mod  # type: ignore[union-attr]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


opencode_ab = _load_helper("_opencode_mcp_ab_helper", ROOT / "scripts/experiments/opencode_mcp_ab/run.py")
parse_jsonl = opencode_ab._parse_jsonl
sum_tokens = opencode_ab._sum_tokens
extract_assistant_text = opencode_ab._extract_assistant_text
provider_block = opencode_ab._provider_block


def _ce_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PACKAGES)
    env.setdefault("CTX_ENGINE_URL", "http://127.0.0.1:8765")
    if extra:
        env.update(extra)
    return env


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: float = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        env=env or os.environ.copy(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _cursor_entry_to_opencode(entry: dict[str, Any], *, repo: Path) -> dict[str, Any]:
    if entry.get("type") == "local" and entry.get("enabled") is not None:
        oc = dict(entry)
        env = dict(oc.get("environment") or oc.get("env") or {})
    else:
        cmd = [str(entry.get("command", ""))]
        cmd.extend(str(a) for a in entry.get("args") or [])
        env = {str(k): str(v) for k, v in (entry.get("env") or {}).items()}
        oc = {"type": "local", "enabled": True, "command": cmd, "environment": env, "timeout": 120000}
    env = dict(oc.get("environment") or {})
    env["CTX_REPO"] = str(repo.resolve()).replace("\\", "/")
    env["CTX_AUTO_INDEX"] = "0"
    env["CTX_ENGINE_URL"] = "http://127.0.0.1:8765"
    oc["environment"] = env
    oc["enabled"] = True
    oc["type"] = "local"
    oc.setdefault("timeout", 120000)
    return oc


def _validate_opencode_mcp_config(path: Path) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return ["missing config"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"invalid json: {exc}"]
    block = (data.get("mcp") or {}).get("context-engine")
    if not isinstance(block, dict):
        return ["missing mcp.context-engine"]
    if block.get("type") != "local":
        errors.append("mcp.context-engine.type must be local")
    if block.get("enabled") is not True:
        errors.append("mcp.context-engine.enabled must be true")
    if not isinstance(block.get("command"), list) or not block["command"]:
        errors.append("mcp.context-engine.command must be non-empty list")
    if not isinstance(block.get("environment"), dict):
        errors.append("mcp.context-engine.environment must be object")
    return errors


def _ensure_engine_ready(repo: Path, *, timeout_s: float = 900) -> dict[str, Any]:
    script = f"""
import json, time
from pathlib import Path
from pipeline.client import EngineClient
from pipeline.daemon import ensure_daemon

repo = Path(r"{repo}")
ensure_daemon(repo)
client = EngineClient(timeout=30.0)
opened = client.open_repo(str(repo), wait=True)
deadline = time.time() + {int(timeout_s)}
last = {{}}
while time.time() < deadline:
    st = client.status(str(repo))
    last = st
    warm = st.get("warm_state")
    eng = st.get("engine") or {{}}
    chunks = eng.get("chunks") or st.get("meta", {{}}).get("chunks")
    if warm == "ready" and eng and chunks:
        print(json.dumps({{"ok": True, "warm_state": warm, "chunks": chunks, "opened": opened}}))
        raise SystemExit(0)
    if warm in {{"error", "failed"}}:
        print(json.dumps({{"ok": False, "warm_state": warm, "error": st.get("warm_error"), "opened": opened}}))
        raise SystemExit(1)
    time.sleep(3)
print(json.dumps({{"ok": False, "timeout": True, "last": last, "opened": opened}}))
raise SystemExit(1)
"""
    proc = _run([str(CE_PY), "-c", script], env=_ce_env(), timeout=timeout_s + 60)
    line = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else "{}"
    try:
        out = json.loads(line)
    except json.JSONDecodeError:
        out = {"ok": False, "error": proc.stderr or proc.stdout or "engine script failed"}
    out["exit_code"] = proc.returncode
    return out


def _preflight(repo: Path, *, skip_connect: bool = False) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: Any) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})
        status = "PASS" if ok else "FAIL"
        print(f"[preflight] {status} {name}: {detail}", flush=True)
        if not ok:
            raise RuntimeError(f"preflight failed: {name}: {detail}")

    record("repo_exists", repo.is_dir(), str(repo))

    pf = _run(["scubiee", "preflight"], timeout=120)
    record("scubiee_preflight", pf.returncode == 0, (pf.stdout or pf.stderr)[-400:])

    init_script = f"""
from pathlib import Path
from pipeline.repo_lifecycle import initialize_repo
repo = Path(r"{repo}")
out = initialize_repo(repo, index=True, confirm=True)
import json; print(json.dumps(out))
"""
    init = _run([str(CE_PY), "-c", init_script], env=_ce_env(), timeout=900)
    try:
        init_data = json.loads((init.stdout or "").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        init_data = {"ok": False, "stdout": init.stdout, "stderr": init.stderr}
    record("initialize_repo", init.returncode == 0 and init_data.get("ok", True), init_data)

    warm = _ensure_engine_ready(repo)
    record("engine_ready", bool(warm.get("ok")), warm)

    search = _run(["scubiee", "search", "agent guidance session stale", str(repo)], timeout=120)
    record("search_smoke", search.returncode == 0 and "agent_guidance" in (search.stdout or "").lower(),
           (search.stdout or search.stderr)[-300:])

    cfg_path = Path.home() / ".config/opencode/config.json"
    if not skip_connect:
        conn = _run(["scubiee", "connect", "--opencode", "--repo", str(repo)], timeout=60)
        record("scubiee_connect", conn.returncode == 0, (conn.stdout or conn.stderr)[-300:])
        if cfg_path.is_file():
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
            raw = (data.get("mcp") or {}).get("context-engine")
            if isinstance(raw, dict):
                data.setdefault("mcp", {})["context-engine"] = _cursor_entry_to_opencode(raw, repo=repo)
                cfg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    errs = _validate_opencode_mcp_config(cfg_path)
    record("opencode_mcp_schema", not errs, errs or "valid")

    oc_ver = _run([OPENCODE, "--version"], timeout=30)
    record("opencode_cli", oc_ver.returncode == 0, (oc_ver.stdout or oc_ver.stderr).strip())

    models = _run([OPENCODE, "models"], timeout=60)
    mission = json.loads(MISSION.read_text(encoding="utf-8"))
    model = mission.get("model", "opencode/x-preview-f-free")
    record("opencode_model", model in (models.stdout or ""), model)

    return {"ok": True, "checks": checks}


def _connect_opencode(repo: Path) -> dict[str, Any]:
    proc = _run(["scubiee", "connect", "--opencode", "--repo", str(repo.resolve())], timeout=60)
    cfg_path = Path.home() / ".config/opencode/config.json"
    entry: dict[str, Any] | None = None
    if cfg_path.is_file():
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        raw = (data.get("mcp") or {}).get("context-engine")
        if isinstance(raw, dict):
            data.setdefault("mcp", {})["context-engine"] = _cursor_entry_to_opencode(raw, repo=repo)
            cfg_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            entry = raw
    return {"ok": proc.returncode == 0, "stdout": proc.stdout, "stderr": proc.stderr, "config_path": str(cfg_path), "entry": entry}


def _arm_config(*, arm: str, repo: Path, connect_entry: dict[str, Any] | None) -> dict[str, Any]:
    disabled = {"frontend-mcp": {"type": "local", "enabled": False, "command": ["echo", "disabled"]}}
    cfg: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        **provider_block(),
        "permission": {
            "edit": "allow" if arm == "mcp" else "deny",
            "bash": "allow" if arm == "mcp" else "deny",
            "webfetch": "deny",
            "read": "allow", "grep": "allow", "glob": "allow", "list": "allow",
        },
        "mcp": {**disabled},
    }
    if arm == "nomcp":
        return cfg
    mcp_block = dict(disabled)
    if connect_entry:
        mcp_block["context-engine"] = _cursor_entry_to_opencode(connect_entry, repo=INDEXED_REPO)
    else:
        py = str(CE_PY.resolve()).replace("\\", "/")
        repo_s = str(INDEXED_REPO).replace("\\", "/")
        mcp_block["context-engine"] = {
            "type": "local", "enabled": True,
            "command": [py, "-u", "-m", "pipeline.mcp_locate"],
            "environment": {
                "CTX_REPO": repo_s, "CTX_ENGINE_URL": "http://127.0.0.1:8765",
                "CTX_MCP_SURFACE": "phase", "CTX_AUTO_INDEX": "0",
                "PYTHONPATH": str(PACKAGES).replace("\\", "/"),
            },
            "timeout": 120000,
        }
    cfg["mcp"] = mcp_block
    return cfg


def _copy_workspace(source: Path, target: Path) -> str:
    def _ignore(_d: str, names: list[str]) -> set[str]:
        return {n for n in names if n in COPY_EXCLUDED}

    shutil.copytree(source, target, ignore=_ignore)
    for cmd in (
        ["git", "init"],
        ["git", "-c", "user.name=Connect AB", "-c", "user.email=ab@local", "add", "-A"],
        ["git", "-c", "user.name=Connect AB", "-c", "user.email=ab@local", "commit", "-m", "baseline", "--no-gpg-sign"],
    ):
        proc = subprocess.run(cmd, cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if proc.returncode != 0 and cmd[1] != "init":
            raise RuntimeError(proc.stderr)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=target, capture_output=True, text=True)
    return head.stdout.strip()


def _git_diff_stat(workspace: Path) -> dict[str, Any]:
    stat = subprocess.run(["git", "diff", "--no-ext-diff", "--stat", "HEAD"], cwd=workspace, capture_output=True, text=True)
    files = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=workspace, capture_output=True, text=True)
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], cwd=workspace, capture_output=True, text=True)
    changed = sorted({f for f in (files.stdout or "").splitlines() if f} | {f for f in (untracked.stdout or "").splitlines() if f})
    return {"stat": (stat.stdout or "").strip(), "changed_files": changed,
            "added_test_files": [f for f in changed if f.startswith("tests/test_") and f.endswith(".py")]}


def _system_hint(arm: str) -> str:
    if arm == "nomcp":
        return "NO MCP servers. Use only built-in read, grep, glob, list. Read-only — do not edit files."
    return (
        "Context Engine MCP (context-engine) is connected via scubiee connect. "
        "Prefer CE locate/search tools for unfamiliar code, then read/grep to verify. "
        "You may edit files, run tests, and implement the requested change."
    )


def run_task(*, arm: str, task: dict[str, Any], workspace: Path, cfg: dict[str, Any],
             model: str, variant: str, timeout_s: float, dry_run: bool) -> dict[str, Any]:
    cfg_path = workspace / "opencode.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    errs = _validate_opencode_mcp_config(cfg_path) if arm == "mcp" else []
    if errs:
        raise RuntimeError(f"workspace opencode.json invalid: {errs}")

    prompt = " | ".join([f"ARM={arm}", _system_hint(arm), task["prompt"], "Repo root is the working directory."])
    cmd = [OPENCODE, "run", "--format", "json", "--auto", "--pure", "--dir", str(workspace),
           "--title", f"connect-ab-{arm}-{task['id']}-{int(time.time())}",
           "--model", model, "--variant", variant, prompt]
    (workspace / f"{task['id']}_cmd.txt").write_text(" ".join(cmd), encoding="utf-8")
    if dry_run:
        return {"task": task["id"], "arm": arm, "dry_run": True, "cmd": cmd, "config": str(cfg_path)}

    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(cfg_path)
    env["CTX_ENGINE_URL"] = "http://127.0.0.1:8765"
    env["CTX_REPO"] = str(INDEXED_REPO).replace("\\", "/")

    print(f"\n=== {task['id']} / {arm} (model={model}, variant={variant}) ===", flush=True)
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=str(workspace), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    lines: list[str] = []
    err_lines: list[str] = []

    def _pump(pipe: Any, sink: list[str]) -> None:
        try:
            for ln in pipe:
                sink.append(ln)
        except Exception:  # noqa: BLE001
            pass

    out_t = threading.Thread(target=_pump, args=(proc.stdout, lines), daemon=True)
    err_t = threading.Thread(target=_pump, args=(proc.stderr, err_lines), daemon=True)
    out_t.start(); err_t.start()
    timed_out = False
    last_beat = t0
    while True:
        now = time.perf_counter()
        if proc.poll() is not None:
            break
        if now - t0 > timeout_s:
            proc.kill(); timed_out = True; break
        if now - last_beat >= 20:
            tok = sum_tokens(parse_jsonl("".join(lines[-400:])))
            print(f"  [beat {now - t0:.0f}s] events={len(lines)} tools={tok.get('tool_calls')} mcp={tok.get('mcp_tool_calls')} tokens={tok.get('tokens_total')}", flush=True)
            last_beat = now
        time.sleep(0.25)
    out_t.join(timeout=10); err_t.join(timeout=10); proc.wait()
    ms = (time.perf_counter() - t0) * 1000
    raw = "".join(lines); stderr_text = "".join(err_lines)
    (workspace / f"{task['id']}_stdout.txt").write_text(raw, encoding="utf-8")
    (workspace / f"{task['id']}_stderr.txt").write_text(stderr_text, encoding="utf-8")
    events = parse_jsonl(raw); tok = sum_tokens(events); text = extract_assistant_text(events)
    row: dict[str, Any] = {
        "task": task["id"], "arm": arm, "ok": proc.returncode == 0 and not timed_out,
        "exit_code": proc.returncode, "timed_out": timed_out, "ms": round(ms, 1),
        "text_excerpt": text[:2000], "events": len(events), **tok,
    }
    if arm == "mcp":
        row["diff"] = _git_diff_stat(workspace)
    print(f"  exit={proc.returncode} tokens={tok.get('tokens_total')} tools={tok.get('tool_calls')} mcp={tok.get('mcp_tool_calls')} ms={ms:.0f}", flush=True)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenCode connect A/B on frontend-mcp")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-preflight", action="store_true")
    ap.add_argument("--timeout", type=float, default=3600.0)
    ap.add_argument("--model", default=None)
    ap.add_argument("--variant", default=None)
    ap.add_argument("--tasks", nargs="+", default=None)
    args = ap.parse_args()

    mission = json.loads(MISSION.read_text(encoding="utf-8"))
    repo = (ROOT / mission["repo"]).resolve()
    if not repo.is_dir():
        print(f"ERROR: repo missing: {repo}", file=sys.stderr)
        return 2

    if not args.dry_run and not args.skip_preflight:
        print("\n=== PREFLIGHT ===", flush=True)
        _preflight(repo)

    model = args.model or mission.get("model") or "opencode/x-preview-f-free"
    variant = args.variant or mission.get("variant") or "max"
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ws_root = Path(tempfile.gettempdir()) / "connect_opencode_ab" / stamp
    ws_root.mkdir(parents=True, exist_ok=True)

    connect_info: dict[str, Any] | None = None
    results: list[dict[str, Any]] = []
    for task in mission["tasks"]:
        if args.tasks and task["id"] not in args.tasks:
            continue
        arm = task["arm"]
        ws = ws_root / f"{task['id']}_{arm}"
        print(f"[{task['id']}] copying workspace -> {ws}", flush=True)
        baseline = _copy_workspace(repo, ws)
        if arm == "mcp" and connect_info is None and not args.dry_run:
            connect_info = _connect_opencode(repo)
        cfg = _arm_config(arm=arm, repo=ws, connect_entry=(connect_info or {}).get("entry") if arm == "mcp" else None)
        row = run_task(arm=arm, task=task, workspace=ws, cfg=cfg, model=model, variant=variant,
                       timeout_s=args.timeout, dry_run=args.dry_run)
        row["workspace"] = str(ws); row["baseline_commit"] = baseline
        results.append(row)
        (OUT / f"{task['id']}_{stamp}.json").write_text(json.dumps(row, indent=2, default=str), encoding="utf-8")

    report = {"title": mission["title"], "repo": str(repo), "model": model, "variant": variant,
              "connect": connect_info, "results": results, "workspace_root": str(ws_root)}
    out = OUT / f"report_{stamp}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (OUT / "report_latest.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("\n=== SUMMARY ===")
    print(json.dumps(results, indent=2, default=str))
    print(f"\nReport: {out}")
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

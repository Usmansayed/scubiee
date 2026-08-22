"""Same complex vague dev task on both arms: CE MCP vs native tools only.

Mandatory preflight before any OpenCode run. Tokens from step_finish JSONL events.

Usage:
  python -u scripts/experiments/dev_mcp_vs_nomcp.py
  python -u scripts/experiments/dev_mcp_vs_nomcp.py --arms nomcp,mcp --timeout 3600
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REPO = (ROOT / "testdata" / "frontend-mcp").resolve()
PACKAGES = (ROOT / "packages").resolve()
OUT = ROOT / "out" / "experiments" / "dev_mcp_vs_nomcp"

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

COPY_EXCLUDED_NAMES = {
    ".git", ".venv", ".context-engine", ".pytest_cache", "__pycache__",
    "out", ".env", ".superpowers", "research", "testdata", "scripts",
    "graphify-out", "vendor", "node_modules",
}

# Vague but specific — no filenames/functions (same prompt both arms).
DEV_TASK = (
    "Agents using our perception stack keep thrashing: they repeat costly observation "
    "and verification steps even when that evidence was already collected earlier in the "
    "same session. When a tool comes back degraded, they often plow ahead instead of "
    "adapting. Separately, codebase intelligence / code-graph style lookup still is not "
    "a first-class perception capability wired like the other perception tools.\n\n"
    "Implement one coherent change set that fixes all of this: session evidence recall "
    "so agents can ask what was already observed or verified (with a clear empty answer "
    "when nothing exists), guidance text that steers agents toward recall instead of "
    "redoing browser work, graceful degraded envelopes when toggles are off, and a "
    "toggleable code-graph perception tool registered and dispatched like the others. "
    "Discover every integration point yourself — schemas, handlers, dispatch, envelopes, "
    "session store, coordinator guidance. Add regression tests, update any contract counts "
    "the repo already guards, and leave a brief docs note. Make it work across multiple "
    "layers, not stubs."
)


def _load_helper(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = mod  # type: ignore[union-attr]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


opencode_ab = _load_helper("_opencode_mcp_ab_helper", Path(__file__).parent / "opencode_mcp_ab" / "run.py")
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


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, timeout: float = 600):
    return subprocess.run(
        cmd, cwd=str(cwd or ROOT), env=env or os.environ.copy(),
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
    )


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
while time.time() < deadline:
    st = client.status(str(repo))
    warm = st.get("warm_state")
    eng = st.get("engine") or {{}}
    chunks = eng.get("chunks") or (st.get("meta") or {{}}).get("chunks")
    if warm == "ready" and eng and chunks:
        print(json.dumps({{"ok": True, "warm_state": warm, "chunks": chunks}}))
        raise SystemExit(0)
    time.sleep(3)
print(json.dumps({{"ok": False, "warm_state": st.get("warm_state"), "error": st.get("warm_error")}}))
raise SystemExit(1)
"""
    proc = _run([str(CE_PY), "-c", script], env=_ce_env(), timeout=timeout_s + 60)
    line = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else "{}"
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {"ok": False, "error": proc.stderr or proc.stdout}


def _validate_opencode_mcp(path: Path) -> list[str]:
    if not path.is_file():
        return ["missing"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [str(exc)]
    block = (data.get("mcp") or {}).get("context-engine")
    if not isinstance(block, dict):
        return ["missing context-engine"]
    errs = []
    if block.get("type") != "local":
        errs.append("type must be local")
    if block.get("enabled") is not True:
        errs.append("enabled must be true")
    if not block.get("command"):
        errs.append("command required")
    return errs


def _preflight(repo: Path, *, model: str) -> None:
    checks: list[tuple[str, bool, Any]] = []

    def record(name: str, ok: bool, detail: Any) -> None:
        checks.append((name, ok, detail))
        print(f"[preflight] {'PASS' if ok else 'FAIL'} {name}: {detail}", flush=True)
        if not ok:
            raise RuntimeError(f"preflight failed: {name}")

    record("repo_exists", repo.is_dir(), str(repo))
    pf = _run(["scubiee", "preflight"], timeout=120)
    record("scubiee_preflight", pf.returncode == 0, (pf.stdout or pf.stderr)[-300:])

    init_script = f"""
from pathlib import Path
from pipeline.repo_lifecycle import initialize_repo
import json
out = initialize_repo(Path(r"{repo}"), index=True, confirm=True)
print(json.dumps(out))
"""
    init = _run([str(CE_PY), "-c", init_script], env=_ce_env(), timeout=900)
    try:
        init_data = json.loads((init.stdout or "").strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        init_data = {"ok": False, "stderr": init.stderr}
    record("initialize_repo", init.returncode == 0 and init_data.get("ok", True), init_data)

    warm = _ensure_engine_ready(repo)
    record("engine_ready", bool(warm.get("ok")), warm)

    search = _run(["scubiee", "search", "session evidence recall perception", str(repo)], timeout=120)
    record("search_smoke", search.returncode == 0, (search.stdout or "")[-200:])

    conn = _run(["scubiee", "connect", "--opencode", "--repo", str(repo)], timeout=60)
    record("scubiee_connect", conn.returncode == 0, (conn.stdout or "")[-200:])
    cfg = Path.home() / ".config" / "opencode" / "config.json"
    if cfg.is_file():
        data = json.loads(cfg.read_text(encoding="utf-8"))
        raw = (data.get("mcp") or {}).get("context-engine")
        if isinstance(raw, dict) and raw.get("type") != "local":
            py = str(CE_PY).replace("\\", "/")
            repo_s = str(repo).replace("\\", "/")
            data.setdefault("mcp", {})["context-engine"] = {
                "type": "local", "enabled": True,
                "command": [py, "-u", "-m", "pipeline.mcp_locate"],
                "environment": {
                    "CTX_REPO": repo_s, "CTX_ENGINE_URL": "http://127.0.0.1:8765",
                    "CTX_MCP_SURFACE": "phase", "CTX_AUTO_INDEX": "0",
                    "PYTHONPATH": str(PACKAGES).replace("\\", "/"),
                },
                "timeout": 120000,
            }
            cfg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    record("opencode_mcp_schema", not _validate_opencode_mcp(cfg), _validate_opencode_mcp(cfg) or "valid")

    oc = _run([OPENCODE, "--version"], timeout=30)
    record("opencode_cli", oc.returncode == 0, (oc.stdout or "").strip())
    models = _run([OPENCODE, "models"], timeout=60)
    record("opencode_model", model in (models.stdout or ""), model)


def _arm_configs(*, indexed_repo: Path) -> dict[str, dict[str, Any]]:
    py = str(CE_PY.resolve()).replace("\\", "/")
    packages = str(PACKAGES).replace("\\", "/")
    repo_s = str(indexed_repo.resolve()).replace("\\", "/")
    disabled = {"frontend-mcp": {"type": "local", "enabled": False, "command": ["echo", "disabled"]}}
    perms = {
        "edit": "allow", "bash": "allow", "webfetch": "deny",
        "read": "allow", "grep": "allow", "glob": "allow", "list": "allow",
    }
    base: dict[str, Any] = {"$schema": "https://opencode.ai/config.json", **provider_block(), "permission": perms}
    mcp_env = {
        "PYTHONPATH": packages,
        "CTX_REPO": repo_s,
        "CTX_ENGINE_URL": "http://127.0.0.1:8765",
        "CTX_MCP_SURFACE": "phase",
        "CTX_AUTO_INDEX": "0",
        "CTX_RETRIEVE": "R_plan",
    }
    return {
        "nomcp": {**base, "mcp": {**disabled}},
        "mcp": {
            **base,
            "mcp": {
                **disabled,
                "context-engine": {
                    "type": "local", "enabled": True,
                    "command": [py, "-u", "-m", "pipeline.mcp_locate"],
                    "environment": mcp_env,
                    "timeout": 120000,
                },
            },
        },
    }


def _copy_workspace(source: Path, target: Path) -> str:
    def _ignore(_d: str, names: list[str]) -> set[str]:
        return {n for n in names if n in COPY_EXCLUDED_NAMES or n.startswith(".sim-ce-home")}

    shutil.copytree(source, target, ignore=_ignore)
    for cmd in (
        ["git", "init"],
        ["git", "-c", "user.name=Dev AB Trial", "-c", "user.email=trial@local.invalid", "add", "-A"],
        ["git", "-c", "user.name=Dev AB Trial", "-c", "user.email=trial@local.invalid", "commit", "-m", "baseline", "--no-gpg-sign"],
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
    return {
        "stat": (stat.stdout or "").strip(),
        "changed_files": changed,
        "added_test_files": [f for f in changed if re.match(r"^tests/test_.*\.py$", f)],
    }


def _arm_hint(arm: str) -> str:
    if arm == "nomcp":
        return "ARM=nomcp | NO MCP. Native read/grep/glob/bash only. Same task as MCP arm."
    return "ARM=mcp | Context Engine MCP enabled. Prefer CE search/map/focus for locate, then read/grep to implement."


def run_arm(arm: str, cfg: dict[str, Any], workspace: Path, *, model: str, variant: str, timeout_s: float) -> dict[str, Any]:
    cfg_path = workspace / "opencode.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    if arm == "mcp":
        warm = _ensure_engine_ready(REPO)
        if not warm.get("ok"):
            raise RuntimeError(f"engine not ready before {arm}: {warm}")

    prompt = f"{_arm_hint(arm)} | {DEV_TASK} | Repo root is the working directory."
    cmd = [OPENCODE, "run", "--format", "json", "--auto", "--pure", "--dir", str(workspace),
           "--title", f"dev-ab-{arm}-{int(time.time())}", "--model", model, "--variant", variant, prompt]
    (workspace / f"{arm}_cmd.txt").write_text(" ".join(cmd), encoding="utf-8")

    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(cfg_path)
    env["CTX_ENGINE_URL"] = "http://127.0.0.1:8765"
    env["CTX_REPO"] = str(REPO).replace("\\", "/")

    print(f"\n=== {arm} (model={model}, variant={variant}, timeout={timeout_s:g}s) ===", flush=True)
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=str(workspace), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")
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
            print(f"  [beat {now - t0:.0f}s] tools={tok.get('tool_calls')} mcp={tok.get('mcp_tool_calls')} tokens={tok.get('tokens_total')}", flush=True)
            last_beat = now
        time.sleep(0.25)
    out_t.join(timeout=10); err_t.join(timeout=10); proc.wait()
    ms = (time.perf_counter() - t0) * 1000
    raw = "".join(lines); stderr_text = "".join(err_lines)
    (workspace / f"{arm}_stdout.txt").write_text(raw, encoding="utf-8")
    (workspace / f"{arm}_stderr.txt").write_text(stderr_text, encoding="utf-8")
    events = parse_jsonl(raw); tok = sum_tokens(events); text = extract_assistant_text(events)
    row: dict[str, Any] = {
        "arm": arm, "ok": proc.returncode == 0 and not timed_out,
        "exit_code": proc.returncode, "timed_out": timed_out, "ms": round(ms, 1),
        "text_excerpt": text[:1500], "events": len(events), **tok,
        "diff": _git_diff_stat(workspace),
    }
    print(f"  done exit={proc.returncode} tokens={tok.get('tokens_total')} mcp_tools={tok.get('mcp_tool_calls')} ms={ms:.0f}", flush=True)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="Same-task token A/B: CE MCP vs no MCP")
    ap.add_argument("--arms", nargs="+", default=["nomcp", "mcp"], choices=["mcp", "nomcp"])
    ap.add_argument("--model", default="opencode/x-preview-f-free")
    ap.add_argument("--variant", default="max")
    ap.add_argument("--timeout", type=float, default=3600.0)
    ap.add_argument("--skip-preflight", action="store_true")
    args = ap.parse_args()

    if not REPO.is_dir():
        print(f"ERROR: missing {REPO}", file=sys.stderr)
        return 2

    if not args.skip_preflight:
        print("\n=== PREFLIGHT ===", flush=True)
        _preflight(REPO, model=args.model)

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ws_root = Path(tempfile.gettempdir()) / "ce_dev_mcp_ab" / stamp
    ws_root.mkdir(parents=True, exist_ok=True)
    configs = _arm_configs(indexed_repo=REPO)
    results: list[dict[str, Any]] = []

    for arm in args.arms:
        ws = ws_root / f"{arm}_workspace"
        print(f"[{arm}] workspace -> {ws}", flush=True)
        baseline = _copy_workspace(REPO, ws)
        row = run_arm(arm, configs[arm], ws, model=args.model, variant=args.variant, timeout_s=args.timeout)
        row["workspace"] = str(ws); row["baseline_commit"] = baseline
        results.append(row)
        (OUT / f"{arm}_{stamp}.json").write_text(json.dumps(row, indent=2, default=str), encoding="utf-8")

    by_tokens = sorted(results, key=lambda r: int(r.get("tokens_total") or 10**12))
    t_nomcp = next((r for r in results if r["arm"] == "nomcp"), None)
    t_mcp = next((r for r in results if r["arm"] == "mcp"), None)
    savings = None
    if t_nomcp and t_mcp and t_nomcp.get("tokens_total") and t_mcp.get("tokens_total"):
        nt = int(t_nomcp["tokens_total"]); mt = int(t_mcp["tokens_total"])
        if nt > 0:
            savings = round((1 - mt / nt) * 100, 1)

    report = {
        "title": "Same-task token A/B: context-engine MCP vs no MCP",
        "task": DEV_TASK,
        "repo": str(REPO),
        "model": args.model,
        "variant": args.variant,
        "workspace_root": str(ws_root),
        "arms": results,
        "token_savings_pct_mcp_vs_nomcp": savings,
        "ranking_by_tokens": [
            {
                "arm": r["arm"],
                "tokens_total": r.get("tokens_total"),
                "tokens_input": r.get("tokens_input"),
                "tokens_output": r.get("tokens_output"),
                "tokens_reasoning": r.get("tokens_reasoning"),
                "tokens_cache_read": r.get("tokens_cache_read"),
                "tool_calls": r.get("tool_calls"),
                "mcp_tool_calls": r.get("mcp_tool_calls"),
                "wall_ms": r.get("ms"),
                "changed_files": len(r.get("diff", {}).get("changed_files", [])),
                "added_test_files": r.get("diff", {}).get("added_test_files"),
                "timed_out": r.get("timed_out"),
                "ok": r.get("ok"),
            }
            for r in by_tokens
        ],
    }
    out = OUT / f"report_{stamp}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (OUT / "report_latest.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("\n=== TOKEN COMPARISON (same prompt, both arms) ===")
    print(json.dumps(report["ranking_by_tokens"], indent=2))
    if savings is not None:
        print(f"\nMCP vs no-MCP token delta: {savings}% ({'MCP used fewer' if savings > 0 else 'no-MCP used fewer'})")
    print(f"\nReport: {out}")
    return 0 if all(r.get("ok") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

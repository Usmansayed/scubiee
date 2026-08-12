"""Isolated 2-arm dev-task token A/B: context-engine MCP vs no MCP (native tools).

Each arm gets a fresh copy of testdata/frontend-mcp (git-baselined), then runs
the SAME complex multi-file dev task via `opencode run`:

  - mcp   : context-engine MCP enabled (D_channel_best surface)
  - nomcp : zero MCP servers, native read/grep/glob/bash only

Tokens are summed from opencode `step_finish` events. Report written to
out/experiments/dev_mcp_vs_nomcp/.

Usage:
  .\\.venv\\Scripts\\python.exe -u scripts\\experiments\\dev_mcp_vs_nomcp.py
  .\\.venv\\Scripts\\python.exe -u scripts\\experiments\\dev_mcp_vs_nomcp.py --model google/gemini-3.1-pro-preview --arms mcp,nomcp
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import queue
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
REPO = ROOT / "testdata" / "frontend-mcp"
OUT = ROOT / "out" / "experiments" / "dev_mcp_vs_nomcp"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not VENV_PY.is_file():
    VENV_PY = Path(sys.executable)

_OPENCODE_EXE = (
    Path.home()
    / "AppData"
    / "Roaming"
    / "npm"
    / "node_modules"
    / "opencode-ai"
    / "bin"
    / "opencode.exe"
)
OPENCODE = (
    str(_OPENCODE_EXE)
    if _OPENCODE_EXE.is_file()
    else (shutil.which("opencode") or shutil.which("opencode.cmd") or "opencode")
)

COPY_EXCLUDED_NAMES = {
    ".git",
    ".venv",
    ".context-engine",
    ".pytest_cache",
    "__pycache__",
    "out",
    ".env",
    ".superpowers",
    "research",
    "testdata",
    "scripts",
    "graphify-out",
    "vendor",
    "node_modules",
}

# Same complex multi-file feature task the SDK dev trial uses on frontend-mcp.
DEV_TASK = (
    "Hey — agents using our perception MCP keep thrashing. They re-run the same "
    "expensive observation / verify steps even when that evidence was already "
    "collected earlier in the session, and when a tool comes back degraded they "
    "often just plow ahead instead of noticing. Also the codebase-intelligence / "
    "code-graph side still isn't reachable as its own first-class perception "
    "tool the way the other perception tools are.\n\n"
    "I need you to fix both of these, as one coherent change:\n"
    "1) Add a first-class perception tool that queries the pure-Python codebase "
    "intelligence / code graph (search / related files / neighbors style), wired "
    "the same way other perception tools are — schema, handler, and runtime "
    "dispatch by name. Gate it behind an env toggle (default on) with a graceful "
    "degraded envelope when it's off.\n"
    "2) Add a small session-evidence recall path so an agent can ask what was "
    "already observed / verified this session (or get a clear empty answer), and "
    "make sure agent-guidance / coordinator-facing text actually points agents at "
    "that instead of redoing the same browser work. Also env-gated if that fits "
    "the project's toggle patterns.\n\n"
    "I don't know the layout at all — you'll need to poke around and find where "
    "tool schemas live, where handlers live, how dispatch works, where envelopes "
    "are built, where session/store state lives, and where agent guidance / "
    "coordinator briefing text is authored. Touch the real integration points, "
    "not stubs. Add tests so this doesn't regress, bump any tool-count / contract "
    "expectations the repo already guards, and leave a short docs note. Make it "
    "actually work across multiple sides of the codebase."
)


def _load_helper(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[name] = mod  # type: ignore[union-attr]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


opencode_ab = _load_helper(
    "_opencode_mcp_ab_helper", Path(__file__).parent / "opencode_mcp_ab" / "run.py"
)
parse_jsonl = opencode_ab._parse_jsonl
sum_tokens = opencode_ab._sum_tokens
extract_assistant_text = opencode_ab._extract_assistant_text
ensure_daemon = opencode_ab._ensure_daemon


def _google_provider_block() -> dict[str, Any]:
    auth = Path.home() / ".local" / "share" / "opencode" / "auth.json"
    key = ""
    if auth.is_file():
        try:
            key = str((json.loads(auth.read_text(encoding="utf-8")) or {}).get("google", {}).get("key", ""))
        except (OSError, json.JSONDecodeError):
            key = ""
    if not key:
        env_f = ROOT / ".env"
        if env_f.is_file():
            for line in env_f.read_text(encoding="utf-8").splitlines():
                m = re.match(r"^\s*GOOGLE1\s*=\s*(.+?)\s*$", line)
                if m:
                    key = m.group(1).strip().strip('"').strip("'")
                    break
    if not key:
        return {}
    return {
        "provider": {
            "google": {
                "npm": "@ai-sdk/google",
                "name": "Google AI Studio",
                "options": {"apiKey": key},
                "models": {
                    "gemini-3.1-pro-preview": {"name": "Gemini 3.1 Pro Preview"},
                    "gemini-2.5-pro": {"name": "Gemini 2.5 Pro"},
                    "gemini-2.5-flash": {"name": "Gemini 2.5 Flash"},
                },
            }
        }
    }


def _arm_configs(workspace: Path) -> dict[str, dict[str, Any]]:
    py = str(VENV_PY.resolve()).replace("\\", "/")
    packages = str((ROOT / "packages").resolve()).replace("\\", "/")
    ws = str(workspace.resolve()).replace("\\", "/")
    base: dict[str, Any] = {"$schema": "https://opencode.ai/config.json"}
    base.update(_google_provider_block())
    disabled_global = {
        "frontend-mcp": {
            "type": "local",
            "enabled": False,
            "command": ["echo", "disabled"],
        }
    }
    return {
        "mcp": {
            **base,
            "mcp": {
                **disabled_global,
                "ce-d-channel-best": {
                    "type": "local",
                    "enabled": True,
                    "command": [py, "-m", "pipeline.mcp_d_channel_best"],
                    "environment": {
                        "PYTHONPATH": packages,
                        "CTX_REPO": ws,
                        "CTX_RETRIEVE": "D_channel_best",
                        "CTX_ENGINE_URL": "http://127.0.0.1:8765",
                    },
                    "timeout": 120000,
                },
            },
        },
        "nomcp": {
            **base,
            "mcp": disabled_global,
        },
    }


def _copy_workspace(source: Path, target: Path) -> str:
    def _ignore(directory: str, names: list[str]) -> set[str]:
        return {
            n
            for n in names
            if n in COPY_EXCLUDED_NAMES or n.startswith(".sim-ce-home")
        }

    shutil.copytree(source, target, ignore=_ignore)
    for cmd in (
        ["git", "init"],
        ["git", "-c", "user.name=Dev AB Trial", "-c", "user.email=trial@local.invalid", "add", "-A"],
        ["git", "-c", "user.name=Dev AB Trial", "-c", "user.email=trial@local.invalid", "commit", "-m", "trial baseline", "--no-gpg-sign"],
    ):
        proc = subprocess.run(
            cmd, cwd=target, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if proc.returncode != 0 and cmd[1] != "init":
            raise RuntimeError(f"git {' '.join(cmd[1:])} failed: {proc.stderr}")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=target, capture_output=True, text=True
    )
    return head.stdout.strip()


def _git_diff_stat(workspace: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--stat", "HEAD"],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    stat_text = proc.stdout
    files = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    changed = sorted(
        {f for f in (files.stdout or "").splitlines() if f}
        | {f for f in (untracked.stdout or "").splitlines() if f}
    )
    added_tests = [f for f in changed if re.match(r"^tests/test_.*\.py$", f)]
    return {
        "stat": stat_text.strip(),
        "changed_files": changed,
        "added_test_files": added_tests,
    }


def run_arm(
    arm: str,
    cfg: dict[str, Any],
    workspace: Path,
    *,
    model: str,
    variant: str,
    timeout_s: float,
) -> dict[str, Any]:
    cfg_path = workspace / "opencode.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    if arm == "mcp":
        print(f"[{arm}] ensuring CE daemon on workspace (CTX_RETRIEVE=D_channel_best)…", flush=True)
        ensure_daemon(workspace, retrieve_mode="D_channel_best")

    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(cfg_path)
    env.pop("CTX_HOME", None)
    env.pop("CTX_ENGINE_URL", None)
    env["CTX_ENGINE_URL"] = "http://127.0.0.1:8765"
    if arm == "mcp":
        env["CTX_RETRIEVE"] = "D_channel_best"

    session_title = f"dev-mcp-vs-nomcp-{arm}-{int(time.time())}"
    cmd = [
        OPENCODE,
        "run",
        "--format",
        "json",
        "--auto",
        "--pure",
        "--dir",
        str(workspace),
        "--title",
        session_title,
    ]
    if model:
        cmd.extend(["--model", model])
    if variant:
        cmd.extend(["--variant", variant])
    cmd.append(DEV_TASK)
    (workspace / f"{arm}_cmd.txt").write_text(" ".join(cmd), encoding="utf-8")

    print(
        f"\n=== {arm} run started (model={model or 'default'}, variant={variant or 'default'}, timeout={timeout_s:g}s) ===",
        flush=True,
    )
    t0 = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        cwd=str(workspace),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    def _pump(pipe: Any, sink: list[str]) -> None:
        try:
            for ln in pipe:
                sink.append(ln)
        except Exception:  # noqa: BLE001
            pass

    lines: list[str] = []
    err_lines: list[str] = []
    done = threading.Event()
    out_t = threading.Thread(target=_pump, args=(proc.stdout, lines), daemon=True)
    err_t = threading.Thread(target=_pump, args=(proc.stderr, err_lines), daemon=True)
    out_t.start()
    err_t.start()
    timed_out = False
    last_beat = time.perf_counter()
    while True:
        now = time.perf_counter()
        if proc.poll() is not None:
            break
        if now - t0 > timeout_s:
            proc.kill()
            timed_out = True
            break
        if now - last_beat >= 20.0:
            events = parse_jsonl("".join(lines[-400:]))
            tok = sum_tokens(events)
            print(
                f"  [beat {now - t0:.0f}s] events={len(events)} "
                f"steps={tok.get('steps')} tools={tok.get('tool_calls')} "
                f"tokens={tok.get('tokens_total')}",
                flush=True,
            )
            last_beat = now
        time.sleep(0.25)
    out_t.join(timeout=10)
    err_t.join(timeout=10)
    proc.wait()
    stderr_text = "".join(err_lines)
    raw = "".join(lines)
    ms = (time.perf_counter() - t0) * 1000

    events = parse_jsonl(raw)
    tok = sum_tokens(events)
    text = extract_assistant_text(events)
    if timed_out:
        (workspace / f"{arm}_timeout_stdout.txt").write_text(raw, encoding="utf-8")
        row: dict[str, Any] = {
            "arm": arm,
            "ok": False,
            "error": "timeout",
            "ms": ms,
            "exit_code": None,
            "text_excerpt": text[:1500],
            "events": len(events),
            "timed_out": True,
            **tok,
        }
        print(f"  TIMEOUT tools={tok.get('tool_calls')} tokens={tok.get('tokens_total')}", flush=True)
        row["diff"] = _git_diff_stat(workspace)
        return row

    (workspace / f"{arm}_stdout.txt").write_text(raw, encoding="utf-8")
    (workspace / f"{arm}_stderr.txt").write_text(stderr_text, encoding="utf-8")
    row = {
        "arm": arm,
        "ok": proc.returncode == 0,
        "error": "" if proc.returncode == 0 else stderr_text[:500],
        "ms": round(ms, 1),
        "exit_code": proc.returncode,
        "text_excerpt": text[:1500],
        "events": len(events),
        "timed_out": False,
        **tok,
    }
    row["diff"] = _git_diff_stat(workspace)
    print(
        f"  done exit={proc.returncode} tokens={tok.get('tokens_total')} "
        f"exchanged={tok.get('tokens_exchanged')} tools={tok.get('tool_calls')} "
        f"ms={ms:.0f} changed_files={len(row['diff']['changed_files'])} "
        f"new_tests={len(row['diff']['added_test_files'])}",
        flush=True,
    )
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenCode dev-task token A/B: CE MCP vs no MCP")
    ap.add_argument("--arms", nargs="+", default=["mcp", "nomcp"], choices=["mcp", "nomcp"])
    ap.add_argument("--model", default="opencode/deepseek-v4-flash-free")
    ap.add_argument("--variant", default="max", help="reasoning effort variant (e.g. max, high, minimal)")
    ap.add_argument("--timeout", type=float, default=2400.0)
    ap.add_argument("--keep-workspaces", action="store_true")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ws_root = Path(tempfile.gettempdir()) / "ce_dev_mcp_ab" / stamp
    ws_root.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for arm in args.arms:
        ws = ws_root / f"{arm}_workspace"
        print(f"[{arm}] copying workspace -> {ws}", flush=True)
        baseline = _copy_workspace(REPO, ws)
        row = run_arm(
            arm,
            _arm_configs(ws)[arm],
            ws,
            model=args.model,
            variant=args.variant,
            timeout_s=args.timeout,
        )
        row["workspace"] = str(ws)
        row["baseline_commit"] = baseline
        results.append(row)
        per = OUT / f"{arm}_{stamp}.json"
        per.write_text(json.dumps(row, indent=2, default=str), encoding="utf-8")
        print(f"[{arm}] per-arm result -> {per}", flush=True)

    # Best-effort: point the daemon back at the original repo after the MCP arm.
    try:
        ensure_daemon(REPO, retrieve_mode="D_channel_best")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] daemon restore failed: {exc}", flush=True)

    by_tokens = sorted(results, key=lambda r: int(r.get("tokens_total") or 10**12))
    report = {
        "title": "Dev task token A/B: context-engine MCP vs no MCP (native tools)",
        "task": DEV_TASK[:300],
        "repo": str(REPO),
        "model": args.model,
        "workspace_root": str(ws_root),
        "arms": results,
        "ranking_by_tokens": [
            {
                "arm": r["arm"],
                "tokens_total": r.get("tokens_total"),
                "tokens_exchanged": r.get("tokens_exchanged"),
                "tokens_input": r.get("tokens_input"),
                "tokens_output": r.get("tokens_output"),
                "tokens_cache_read": r.get("tokens_cache_read"),
                "tool_calls": r.get("tool_calls"),
                "steps": r.get("steps"),
                "wall_ms": r.get("ms"),
                "changed_files": len(r.get("diff", {}).get("changed_files", [])),
                "added_test_files": r.get("diff", {}).get("added_test_files"),
                "timed_out": r.get("timed_out"),
            }
            for r in by_tokens
        ],
        "comparison": {
            (by_tokens[0]["arm"] if by_tokens else None): "FEWER tokens",
            (by_tokens[-1]["arm"] if by_tokens else None): "MORE tokens",
        },
    }
    out = OUT / f"report_{stamp}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    latest = OUT / "report_latest.json"
    latest.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("\n=== TOKEN COMPARISON ===")
    print(json.dumps(report["ranking_by_tokens"], indent=2))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

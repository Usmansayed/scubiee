#!/usr/bin/env python3
"""Isolated Kiro credit A/B: three dev tasks, with Scubiee MCP vs without.

Preflight (no task spend until it passes):
  Kiro CLI, API key from env/.env, auto model, MCP wait settings, rules,
  agent surface, deterministic map/pack, then a live Kiro chat that must
  call every ship Scubiee tool. A failed tool aborts before the benchmark.

Both arms start from the same snapshot commit for every task.
Raw logs stay under .ab_workspaces/kiro_credit_harness/<run_id>/.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import kiro_mcp_ab_dev_eval as ab  # noqa: E402

SUITE = ("weak_start", "engine_visibility", "session_isolation")
_FILE_READ = re.compile(
    r"(?:Reading file:|fs_read|path[\"']?\s*[:=]\s*[\"'])\s*([^\s\"']+)",
    re.I,
)


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n", encoding="utf-8")


def _baseline_sha(ws: Path) -> str:
    log = ab._run(["git", "log", "--reverse", "--format=%H%x09%s"], cwd=ws)
    for ln in (log.stdout or "").splitlines():
        if "\t" not in ln:
            continue
        sha, subj = ln.split("\t", 1)
        if "ab-dev baseline" in subj:
            return sha.strip()
    rev = ab._run(["git", "rev-parse", "HEAD"], cwd=ws)
    return (rev.stdout or "").strip()


def _reset(ws: Path, sha: str) -> None:
    ab._run(["git", "reset", "--hard", sha], cwd=ws, check=True)
    ab._run(["git", "clean", "-fd"], cwd=ws, check=True)


def _key_present() -> dict[str, Any]:
    ab._load_dotenv_key()
    key = os.environ.get("KIRO_API_KEY") or ""
    return {
        "ok": bool(key),
        "source": "env",
        "length": len(key),
        "note": "value not recorded",
    }


def _cli_settings() -> dict[str, Any]:
    path = Path.home() / ".kiro" / "settings" / "cli.json"
    cfg: dict[str, Any] = {}
    if path.is_file():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
        except json.JSONDecodeError:
            cfg = {}
    loaded = cfg.get("mcp.loadedBefore")
    init_ms = int(cfg.get("mcp.initTimeout") or 0)
    nonint_ms = int(cfg.get("mcp.noInteractiveTimeout") or 0)
    return {
        "ok": loaded in (True, "true") and init_ms >= 120_000 and nonint_ms >= 120_000,
        "path": str(path),
        "mcp.loadedBefore": loaded,
        "mcp.initTimeout": init_ms,
        "mcp.noInteractiveTimeout": nonint_ms,
    }


def _engine_health() -> dict[str, Any]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=5) as resp:
            body = json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": type(exc).__name__}
    return {
        "ok": bool(body.get("ok") and body.get("dense_ready") and body.get("warm_ready")),
        "version": body.get("version"),
        "warm_state": body.get("warm_state"),
        "dense_ready": body.get("dense_ready"),
        "embedder_loaded": body.get("embedder_loaded"),
        "chunks": body.get("chunks"),
    }


def _repo_state() -> dict[str, Any]:
    branch = ab._run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT)
    dirty = ab._run(["git", "status", "--porcelain"], cwd=ROOT)
    lines = [ln for ln in (dirty.stdout or "").splitlines() if ln.strip()]
    return {
        "ok": True,
        "branch": (branch.stdout or "").strip(),
        "dirty_entries": len(lines),
        "note": "snapshots copy this worktree; arms get their own git init",
    }


def oracle_disk_callers(ws: Path) -> dict[str, Any]:
    """Hidden check: same-file callers of a symbol that is not a graph node."""
    code = r"""
import json, sys
from pathlib import Path
from pipeline.context_trace import _expand_disk_delta
from trace_lab.types import TraceNode

root = Path(sys.argv[1])
pkg = root / "pkg"
pkg.mkdir(parents=True, exist_ok=True)
(pkg / "mod.py").write_text(
    "def helper():\n    return target()\n\n"
    "def target():\n    return 1\n\n"
    "def other():\n    return 2\n",
    encoding="utf-8",
)
(pkg / "quiet.py").write_text(
    "def lonely():\n    return 1\n\n"
    "def bystander():\n    return 2\n",
    encoding="utf-8",
)
helper = TraceNode(id="pkg/mod.py::helper", file="pkg/mod.py", symbol="helper", kind="function", start_line=1, end_line=2, text="pass")
other = TraceNode(id="pkg/mod.py::other", file="pkg/mod.py", symbol="other", kind="function", start_line=7, end_line=8, text="pass")
nodes = {helper.id: helper, other.id: other}
called = _expand_disk_delta(root, nodes, "pkg/mod.py::target", direction="callers", k=8)
quiet = _expand_disk_delta(root, {}, "pkg/quiet.py::lonely", direction="callers", k=8)
syms = [str(c.get("symbol") or "") for c in ((called or {}).get("delta") or [])]
quiet_delta = (quiet or {}).get("delta") or []
ok = bool(
    called and called.get("ok") is True
    and "helper" in syms
    and "other" not in syms
    and quiet and quiet.get("ok") is True
    and quiet_delta == []
)
print(json.dumps({"ok": ok, "symbols": syms, "quiet_n": len(quiet_delta)}))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ws / "packages")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, "-c", code, str(ws / "_oracle_disk")],
        cwd=str(ws),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
    )
    parsed: dict[str, Any] = {}
    for line in reversed((proc.stdout or "").splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                parsed = {}
            break
    return {
        "ok": bool(parsed.get("ok")),
        "symbols": parsed.get("symbols"),
        "quiet_n": parsed.get("quiet_n"),
        "exit_code": proc.returncode,
        "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-8:]),
    }


def _files_explored(log_path: Path) -> dict[str, Any]:
    if not log_path.is_file():
        return {"n": 0, "paths": []}
    text = log_path.read_text(encoding="utf-8", errors="replace")
    paths = []
    seen: set[str] = set()
    for m in _FILE_READ.finditer(text):
        p = m.group(1).replace("\\", "/").strip()
        if not p or p in seen:
            continue
        seen.add(p)
        paths.append(p)
    return {"n": len(paths), "paths": paths[:80]}


def _activate(task_id: str) -> None:
    task = ab.TASKS[task_id]
    ab.ACTIVE_TASK_ID = task_id
    ab.ACTIVE_TASK = task
    ab.DEV_PROMPT = task["prompt"]
    ab.ACTIVE_TEST_KEYWORDS = task["test_keywords"]
    ab.ACTIVE_TEST_FILES = tuple(task.get("test_files") or ())


def _slim(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {}
    tools = row.get("tools") or {}
    diff = row.get("diff") or {}
    tests = row.get("tests") or {}
    return {
        "success": row.get("success"),
        "arm_status": row.get("arm_status"),
        "credits": row.get("credits"),
        "out_tokens_est": row.get("out_tokens_est"),
        "wall_ms": row.get("wall_ms"),
        "exit_code": row.get("exit_code"),
        "timed_out": row.get("timed_out"),
        "scubiee_count": tools.get("scubiee_count"),
        "native_count": tools.get("native_count"),
        "mcp_tools": tools.get("mcp_scubiee_tools"),
        "files_changed": diff.get("files") or diff.get("stat"),
        "diff_changed": diff.get("changed"),
        "tests_ok": tests.get("ok"),
        "tests_summary": tests.get("summary") or tests.get("reason"),
        "oracle_ok": (row.get("oracle") or {}).get("ok"),
        "isolation": row.get("isolation"),
        "error": row.get("error"),
        "log": row.get("log"),
    }


def static_preflight() -> dict[str, Any]:
    ab.ensure_kiro_mcp_wait_settings()
    key = _key_present()
    cli = _cli_settings()
    credit_ok = ab._CREDIT.search("Credits: 1.25") is not None
    log_dir = ab.BASE.parent / "kiro_credit_harness" / "_preflight_writecheck"
    log_dir.mkdir(parents=True, exist_ok=True)
    probe = log_dir / "write_ok.txt"
    probe.write_text("ok\n", encoding="utf-8")
    checks = {
        "kiro_cli": {"ok": ab.KIRO.is_file(), "path": str(ab.KIRO)},
        "api_key": key,
        "model": {"ok": True, "value": "auto", "effort": "medium"},
        "mcp_wait": cli,
        "bridge": {"ok": ab.BRIDGE.is_file(), "path": str(ab.BRIDGE)},
        "ship_tools": {
            "ok": set(ab.MCP_PREFLIGHT_REQUIRED)
            == {
                "gate",
                "status",
                "map",
                "pack_context",
                "expand_context",
                "collect_hot_context",
                "workspace",
                "expand",
            },
            "tools": list(ab.MCP_PREFLIGHT_REQUIRED),
        },
        "credit_parser": {"ok": credit_ok, "pattern": "Credits: <number>"},
        "log_dir_writable": {"ok": probe.is_file(), "path": str(log_dir)},
        "engine": _engine_health(),
        "repo": _repo_state(),
        "project_id": ab.assert_project_id_binding(ROOT),
    }
    checks["ok"] = all(
        bool(v.get("ok"))
        for v in checks.values()
        if isinstance(v, dict) and "ok" in v
    )
    return checks


def _compare(tasks: dict[str, Any]) -> dict[str, Any]:
    rows = []
    sum_c = {"with": 0.0, "without": 0.0}
    known = {"with": True, "without": True}
    wins = {"with": 0, "without": 0, "tie": 0}
    for task_id, arms in tasks.items():
        w = (arms.get("with") or {})
        n = (arms.get("without") or {})
        wc, nc = w.get("credits"), n.get("credits")
        if wc is None:
            known["with"] = False
        else:
            sum_c["with"] += float(wc)
        if nc is None:
            known["without"] = False
        else:
            sum_c["without"] += float(nc)
        if wc is not None and nc is not None:
            if wc < nc:
                wins["with"] += 1
            elif nc < wc:
                wins["without"] += 1
            else:
                wins["tie"] += 1
        rows.append(
            {
                "task": task_id,
                "with_credits": wc,
                "without_credits": nc,
                "with_success": w.get("success"),
                "without_success": n.get("success"),
                "with_tokens_est": w.get("out_tokens_est"),
                "without_tokens_est": n.get("out_tokens_est"),
                "with_native": w.get("native_count"),
                "without_native": n.get("native_count"),
                "with_scubiee": w.get("scubiee_count"),
                "files_with": (arms.get("_files") or {}).get("with"),
                "files_without": (arms.get("_files") or {}).get("without"),
            }
        )
    saved = None
    if known["with"] and known["without"] and sum_c["without"]:
        saved = round(sum_c["without"] - sum_c["with"], 4)
    both_correct = all(
        (arms.get("with") or {}).get("success") and (arms.get("without") or {}).get("success")
        for arms in tasks.values()
    )
    treatment_not_worse = all(
        bool((arms.get("with") or {}).get("success"))
        or not bool((arms.get("without") or {}).get("success"))
        for arms in tasks.values()
    )
    return {
        "per_task": rows,
        "credits_with": round(sum_c["with"], 4) if known["with"] else None,
        "credits_without": round(sum_c["without"], 4) if known["without"] else None,
        "credits_saved_by_scubiee": saved,
        "credit_wins": wins,
        "both_arms_correct_on_every_task": both_correct,
        "treatment_not_worse": treatment_not_worse,
        "scubiee_reduced_credits_without_hurting_results": bool(
            saved is not None and saved > 0 and treatment_not_worse
        ),
    }


def _write_md(path: Path, report: dict[str, Any]) -> None:
    cmp = report.get("comparison") or {}
    lines = [
        "# Kiro credit harness",
        "",
        f"Run `{report.get('run_id')}` · model `{report.get('model')}` · effort `{report.get('effort')}`",
        "",
        "## Verdict",
        "",
        f"Scubiee reduced credits without hurting results: **{cmp.get('scubiee_reduced_credits_without_hurting_results')}**",
        "",
        f"- Control credits: {cmp.get('credits_without')}",
        f"- Treatment credits: {cmp.get('credits_with')}",
        f"- Saved by Scubiee (control − treatment): {cmp.get('credits_saved_by_scubiee')}",
        f"- Treatment not worse on correctness: {cmp.get('treatment_not_worse')}",
        "",
        "## Tasks",
        "",
        "| task | with credits | without credits | with ok | without ok | with ~tok | without ~tok |",
        "|---|---:|---:|---|---|---:|---:|",
    ]
    for row in cmp.get("per_task") or []:
        lines.append(
            f"| {row['task']} | {row['with_credits']} | {row['without_credits']} | "
            f"{row['with_success']} | {row['without_success']} | "
            f"{row['with_tokens_est']} | {row['without_tokens_est']} |"
        )
    lines += ["", "Raw logs live next to this file.", ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timeout-s", type=int, default=600)
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--task", default="disk_callers", choices=sorted(ab.TASKS))
    ap.add_argument(
        "--skip-rules",
        action="store_true",
        help="Skip the extra rules-quote chat. Tool preflight still checks GATE visibility.",
    )
    ap.add_argument(
        "--preflight-only",
        action="store_true",
        help="Stop after static checks plus the live Kiro tool proof.",
    )
    args = ap.parse_args()

    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + "_credit"
    run_dir = (ROOT / ".ab_workspaces" / "kiro_credit_harness" / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    static = static_preflight()
    _write(run_dir / "preflight_static.json", static)
    print(json.dumps({"event": "preflight_static", "ok": static.get("ok")}, indent=2), flush=True)
    if not static.get("ok"):
        _write(run_dir / "report.json", {"ok": False, "aborted": "static_preflight", "preflight_static": static})
        print("ERROR: static preflight failed — not starting Kiro", file=sys.stderr)
        return 2

    print(json.dumps({"event": "snapshot_start", "run_id": run_id}), flush=True)
    with_ws = run_dir / "with"
    without_ws = run_dir / "without"
    try:
        ab.snapshot_workspace(with_ws)
        paired = ab.snapshot_without_from_with_baseline(with_ws, without_ws)
    except Exception as exc:
        import traceback

        (run_dir / "snapshot_error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        print(json.dumps({"event": "snapshot_error", "error": str(exc)[:800]}), flush=True)
        return 2
    if not paired.get("ok"):
        _write(run_dir / "snapshot_error.json", paired)
        print(json.dumps({"event": "snapshot_error", "error": paired.get("error")}), flush=True)
        return 2
    base_with = _baseline_sha(with_ws)
    base_without = _baseline_sha(without_ws)
    print(json.dumps({"event": "snapshot_done", "with": base_with, "without": base_without}), flush=True)

    print(json.dumps({"event": "warm_proof_start"}), flush=True)
    warm = ab.deterministic_warm_proof(with_ws, timeout_s=120.0)
    _write(run_dir / "warm_proof.json", warm)
    if not warm.get("ok"):
        _write(run_dir / "report.json", {"ok": False, "aborted": "warm_proof", "warm": warm, "preflight_static": static})
        print("ERROR: warm proof failed — not asking Kiro", file=sys.stderr)
        return 3

    log_dir = run_dir / "logs"
    print(json.dumps({"event": "kiro_tool_preflight_start", "tools": list(ab.MCP_PREFLIGHT_REQUIRED)}), flush=True)
    with ab.McpNeutralizer():
        pf = ab.run_kiro_mcp_preflight(
            ws=with_ws,
            model=args.model,
            effort=args.effort,
            timeout_s=min(args.timeout_s, 900),
            log_dir=log_dir,
        )
        if not pf.get("ok") and "not visible" in str(pf.get("error") or "").lower():
            print(json.dumps({"event": "kiro_tool_preflight_retry", "reason": "mcp_not_loaded"}), flush=True)
            ab._kill_hung_mcp_bridges()
            import time as _time
            _time.sleep(3)
            pf = ab.run_kiro_mcp_preflight(
                ws=with_ws,
                model=args.model,
                effort=args.effort,
                timeout_s=min(args.timeout_s, 900),
                log_dir=log_dir,
            )
        _write(run_dir / "preflight_kiro.json", pf)
        print(json.dumps({"event": "kiro_tool_preflight", "ok": pf.get("ok"), "error": pf.get("error")}, indent=2), flush=True)
        if not pf.get("ok"):
            _write(
                run_dir / "report.json",
                {
                    "ok": False,
                    "aborted": "kiro_tools",
                    "preflight_static": static,
                    "preflight_kiro": pf,
                    "run_dir": str(run_dir),
                },
            )
            print("ERROR: Kiro could not use every Scubiee tool — benchmark not started", file=sys.stderr)
            return 3

        rules = {"ok": True, "skipped": True}
        if not args.skip_rules:
            rules = ab.run_kiro_rules_probe(
                ws=with_ws,
                model=args.model,
                effort=args.effort,
                timeout_s=min(args.timeout_s, 600),
                log_dir=log_dir,
            )
            _write(run_dir / "rules_probe.json", rules)
            print(json.dumps({"event": "rules_probe", "ok": rules.get("ok"), "error": rules.get("error")}), flush=True)
            if not rules.get("ok"):
                _write(
                    run_dir / "report.json",
                    {"ok": False, "aborted": "rules", "rules_probe": rules, "run_dir": str(run_dir)},
                )
                print("ERROR: rules probe failed — benchmark not started", file=sys.stderr)
                return 3

        if args.preflight_only:
            _write(run_dir / "report.json", {"ok": True, "aborted": None, "preflight_only": True, "run_dir": str(run_dir)})
            print(json.dumps({"event": "preflight_only_done", "run_dir": str(run_dir)}), flush=True)
            return 0

        _reset(with_ws, base_with)
        tasks: dict[str, Any] = {}
        suite = (args.task,)
        for task_id in suite:
            _activate(task_id)
            print(json.dumps({"event": "task_start", "task": task_id}), flush=True)
            _reset(with_ws, base_with)
            _reset(without_ws, base_without)
            task_logs = log_dir / task_id
            row: dict[str, Any] = {}
            for arm, ws in (("without", without_ws), ("with", with_ws)):
                print(json.dumps({"event": "arm_start", "task": task_id, "arm": arm}), flush=True)
                result = ab.run_arm(
                    arm=arm,
                    ws=ws,
                    model=args.model,
                    effort=args.effort,
                    timeout_s=args.timeout_s,
                    log_dir=task_logs / arm,
                )
                explored = _files_explored(task_logs / arm / f"{arm}.log")
                result["files_explored"] = explored
                if task_id == "disk_callers":
                    result["oracle"] = oracle_disk_callers(ws)
                    result["success"] = bool(
                        result.get("success") and result["oracle"].get("ok")
                    )
                _write(task_logs / arm / "result.json", result)
                slim = _slim(result)
                slim["files_explored_n"] = explored["n"]
                row[arm] = slim
                row.setdefault("_files", {})[arm] = explored["n"]
                print(
                    json.dumps(
                        {
                            "event": "arm_done",
                            "task": task_id,
                            "arm": arm,
                            "credits": slim.get("credits"),
                            "success": slim.get("success"),
                            "oracle_ok": slim.get("oracle_ok"),
                            "wall_ms": slim.get("wall_ms"),
                        }
                    ),
                    flush=True,
                )
            tasks[task_id] = row
            _write(run_dir / "tasks_partial.json", tasks)

        comparison = _compare(tasks)
        report = {
            "ok": True,
            "run_id": run_id,
            "run_dir": str(run_dir),
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "model": args.model,
            "effort": args.effort,
            "timeout_s": args.timeout_s,
            "tasks": list(suite),
            "same_start_each_task": True,
            "preflight_static": static,
            "preflight_kiro_ok": True,
            "rules_ok": True,
            "comparison": comparison,
            "runs": tasks,
        }
        _write(run_dir / "report.json", report)
        _write_md(run_dir / "REPORT.md", report)
        print(json.dumps({"event": "done", "comparison": comparison, "run_dir": str(run_dir)}, indent=2), flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

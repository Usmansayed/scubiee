"""Soft OpenCode A/B: graphify+grep vs CE R_plan vs CE D_rerank.

Agent may use built-in read/grep/glob. MCP search is encouraged when needed,
not forced. Measures OpenCode step_finish tokens.

Usage:
  .\\.venv\\Scripts\\python.exe -u scripts\\experiments\\opencode_soft_ab\\run.py
  .\\.venv\\Scripts\\python.exe -u scripts\\experiments\\opencode_soft_ab\\run.py --model opencode/deepseek-v4-flash-free
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "out" / "experiments" / "opencode_soft_ab"
LEGACY_OUT = ROOT / "out" / "experiments" / "opencode_mcp_ab"
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

GRAPH_JSON = (
    Path.home()
    / ".context-engine"
    / "projects"
    / "ce_312fe25bcf4127b33feb5275c4b918ec"
    / "graph.json"
)

ARMS = ("graphify", "ce_r_plan", "ce_d_rerank")


def _load_mission() -> dict[str, Any]:
    return json.loads((HERE / "mission.json").read_text(encoding="utf-8"))


def _provider_block() -> dict[str, Any]:
    for base in (OUT, LEGACY_OUT):
        for name in ("opencode_bedrock.json", "opencode_google.json"):
            cfg_path = base / name
            if not cfg_path.is_file():
                continue
            try:
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            prov = data.get("provider")
            if isinstance(prov, dict) and prov:
                return {"provider": prov}
    cfg = Path.home() / ".config" / "opencode" / "opencode.jsonc"
    if not cfg.is_file():
        cfg = Path.home() / ".config" / "opencode" / "opencode.json"
    if not cfg.is_file():
        return {}
    raw = re.sub(r"^\s*//.*$", "", cfg.read_text(encoding="utf-8"), flags=re.M)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    out: dict[str, Any] = {}
    if "provider" in data:
        prov = dict(data["provider"])
        prov.pop("google-vertex", None)
        prov.pop("google-vertex-anthropic", None)
        out["provider"] = prov
    if "model" in data:
        out["model"] = data["model"]
    return out


def _active_google_key() -> str | None:
    for base in (OUT, LEGACY_OUT):
        ring = base / ".google_keys.json"
        if not ring.is_file():
            continue
        try:
            data = json.loads(ring.read_text(encoding="utf-8"))
            keys = data.get("keys") or []
            i = int(data.get("i") or 0)
            if keys:
                return str(keys[i % len(keys)])
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            pass
    return os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY") or os.environ.get("GEMINI_API_KEY")


def _inject_model_env(env: dict[str, str]) -> None:
    for base in (OUT, LEGACY_OUT):
        bedrock = base / ".bedrock.json"
        if bedrock.is_file():
            try:
                data = json.loads(bedrock.read_text(encoding="utf-8"))
                if data.get("key"):
                    env["AWS_BEARER_TOKEN_BEDROCK"] = str(data["key"])
                if data.get("region"):
                    env["AWS_REGION"] = str(data["region"])
                    env["AWS_DEFAULT_REGION"] = str(data["region"])
            except (OSError, json.JSONDecodeError, TypeError):
                pass
            break
    gkey = _active_google_key()
    if gkey:
        env["GOOGLE_GENERATIVE_AI_API_KEY"] = gkey
        env["GEMINI_API_KEY"] = gkey
        env["GOOGLE_API_KEY"] = gkey


def _soft_permissions() -> dict[str, str]:
    """Normal agent tools allowed — MCP not the only path."""
    return {
        "edit": "deny",
        "bash": "deny",
        "webfetch": "deny",
        "read": "allow",
        "grep": "allow",
        "glob": "allow",
        "list": "allow",
        "skill": "deny",
        "task": "deny",
        "todowrite": "deny",
        "todoread": "deny",
    }


def _arm_configs(repo: Path) -> dict[str, dict[str, Any]]:
    py = str(VENV_PY.resolve()).replace("\\", "/")
    packages = str((ROOT / "packages").resolve()).replace("\\", "/")
    repo_s = str(repo.resolve()).replace("\\", "/")
    graph = str(GRAPH_JSON.resolve()).replace("\\", "/") if GRAPH_JSON.is_file() else ""

    base = {
        "$schema": "https://opencode.ai/config.json",
        **_provider_block(),
        "permission": _soft_permissions(),
    }
    disabled_global = {
        "frontend-mcp": {
            "type": "local",
            "enabled": False,
            "command": ["echo", "disabled"],
        }
    }

    def ce_mcp(mode: str, name: str) -> dict[str, Any]:
        return {
            name: {
                "type": "local",
                "enabled": True,
                "command": [py, "-m", "pipeline.mcp_search_only"],
                "environment": {
                    "PYTHONPATH": packages,
                    "CTX_REPO": repo_s,
                    "CTX_RETRIEVE": mode,
                    "CTX_ENGINE_URL": "http://127.0.0.1:8765",
                },
                "timeout": 120000,
            }
        }

    return {
        "graphify": {
            **base,
            "mcp": {
                **disabled_global,
                "graphify": {
                    "type": "local",
                    "enabled": True,
                    "command": [py, "-m", "graphify.serve", graph],
                    "environment": {"PYTHONPATH": packages},
                    "timeout": 120000,
                },
            },
        },
        "ce_r_plan": {
            **base,
            "mcp": {**disabled_global, **ce_mcp("R_plan", "context-engine")},
        },
        "ce_d_rerank": {
            **base,
            "mcp": {**disabled_global, **ce_mcp("D", "context-engine")},
        },
    }


def _system_hint(arm: str, *, encourage: str = "soft") -> str:
    common = (
        "Index/graph already warm when applicable — do not reindex. "
        "Answer with exact repo-relative paths. Be concise."
    )
    if encourage == "high":
        # Strong nudge to MCP first; builtins only after MCP points the way.
        if arm == "graphify":
            return (
                "CRITICAL: Start EVERY locate step with graphify MCP "
                "(query_graph / get_neighbors / get_node / graph_stats). "
                "Call MCP first before read/grep. Use built-in read/grep ONLY "
                "to open a path MCP already returned. Do not wander with blind "
                f"grep as your primary search. {common}"
            )
        label = "R_plan" if arm == "ce_r_plan" else "D_rerank"
        return (
            f"CRITICAL: Start EVERY locate step with Context Engine search_code "
            f"({label} hybrid). Call search_code first before read/grep. "
            "Use built-in read/grep ONLY to open paths search_code already "
            "returned. Do not use blind grep/glob as your primary finder. "
            f"{common}"
        )

    soft = (
        "You may freely use built-in read, grep, and glob. "
    )
    if arm == "graphify":
        return (
            "You have graphify MCP (query_graph, get_neighbors, get_node, …) "
            "plus normal read/grep. Prefer graphify when locating by structure/"
            f"relationships; use grep for exact symbols. {soft}{common}"
        )
    if arm == "ce_r_plan":
        return (
            "You have Context Engine search_code (R_plan hybrid) plus normal "
            "read/grep. Do NOT force MCP on every step — but when you need to "
            "find unfamiliar code by meaning, prefer search_code first, then "
            f"open files with read/grep. {soft}{common}"
        )
    return (
        "You have Context Engine search_code (D_rerank hybrid) plus normal "
        "read/grep. Do NOT force MCP on every step — but when you need to "
        "find unfamiliar code by meaning, prefer search_code first, then "
        f"open files with read/grep. {soft}{common}"
    )


def _score(text: str, turn: dict[str, Any]) -> dict[str, Any]:
    low = text.lower().replace("\\", "/")
    touch_ok = all(need.lower() in low for need in (turn.get("must_touch") or []))
    avoid_hit = []
    for a in turn.get("must_avoid") or []:
        al = a.lower()
        if (
            f"/{al}/" in low
            or f"/{al}." in low
            or f"{al}_" in low
            or f"{al}/" in low
            or f"\\{al}\\" in text.lower()
        ):
            avoid_hit.append(a)
    return {
        "touch_ok": touch_ok,
        "avoid_ok": not avoid_hit,
        "ok": touch_ok and not avoid_hit,
        "avoid_hit": avoid_hit,
    }


def _extract_assistant_text(events: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for ev in events:
        typ = ev.get("type") or ev.get("event") or ""
        part = ev.get("part") if isinstance(ev.get("part"), dict) else {}
        if typ == "text" or part.get("type") == "text":
            t = part.get("text") or ev.get("text")
            if t:
                chunks.append(str(t))
            continue
        if typ in {"message", "assistant"}:
            if part.get("text"):
                chunks.append(str(part["text"]))
            elif ev.get("text"):
                chunks.append(str(ev["text"]))
            elif isinstance(ev.get("message"), dict):
                content = ev["message"].get("content")
                if isinstance(content, str):
                    chunks.append(content)
                elif isinstance(content, list):
                    for c in content:
                        if isinstance(c, dict) and c.get("text"):
                            chunks.append(str(c["text"]))
    nonempty = [c.strip() for c in chunks if c and c.strip()]
    if not nonempty:
        return ""
    return nonempty[0] if len(nonempty) == 1 else "\n".join(nonempty[-3:])


def _parse_jsonl(raw: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _sum_tokens(events: list[dict[str, Any]]) -> dict[str, Any]:
    total = input_t = output_t = reasoning = cache_read = cache_write = 0
    cost = 0.0
    steps = 0
    tools = 0
    mcp_tools = 0
    builtin_tools = 0
    for ev in events:
        part = ev.get("part") if isinstance(ev.get("part"), dict) else {}
        typ = ev.get("type") or ""
        if typ == "tool_use" or part.get("type") == "tool":
            tools += 1
            name = str(part.get("tool") or part.get("name") or ev.get("tool") or "").lower()
            if any(
                k in name
                for k in (
                    "search_code",
                    "graphify",
                    "query_graph",
                    "get_node",
                    "get_neighbors",
                    "status",
                )
            ):
                mcp_tools += 1
            elif name:
                builtin_tools += 1
        if typ != "step_finish" and part.get("type") != "step-finish":
            continue
        steps += 1
        tok = part.get("tokens") or ev.get("tokens") or {}
        if isinstance(tok, dict):
            total += int(tok.get("total") or 0)
            input_t += int(tok.get("input") or 0)
            output_t += int(tok.get("output") or 0)
            reasoning += int(tok.get("reasoning") or 0)
            cache = tok.get("cache") or {}
            if isinstance(cache, dict):
                cache_read += int(cache.get("read") or 0)
                cache_write += int(cache.get("write") or 0)
        try:
            cost += float(part.get("cost") or ev.get("cost") or 0.0)
        except (TypeError, ValueError):
            pass
    return {
        "steps": steps,
        "tool_calls": tools,
        "mcp_tool_calls": mcp_tools,
        "builtin_tool_calls": builtin_tools,
        "tokens_total": total,
        "tokens_input": input_t,
        "tokens_output": output_t,
        "tokens_reasoning": reasoning,
        "tokens_cache_read": cache_read,
        "tokens_cache_write": cache_write,
        "cost": round(cost, 6),
    }


def _ensure_daemon(repo: Path, *, retrieve_mode: str) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "packages")
    env.pop("CTX_HOME", None)
    env.pop("CTX_ENGINE_URL", None)
    env.pop("CTX_SEARCH_URL", None)
    mode = retrieve_mode.strip()
    env["CTX_RETRIEVE"] = mode
    script = f"""
from pathlib import Path
import os
from pipeline.daemon import force_restart_daemon
from pipeline.client import EngineClient
repo = Path(r'{repo}')
mode = {mode!r}
os.environ['CTX_RETRIEVE'] = mode
os.environ.pop('CTX_HOME', None)
force_restart_daemon(repo)
c = EngineClient()
opened = c.open_repo(str(repo), wait=True)
st = c.status(str(repo))
eng = st.get('engine') or {{}}
# verify retrieve mode with a tiny search
r = c.search('agent guidance vanished', top_k=2, path=str(repo))
tm = (r.get('timings') or {{}}).get('retrieve_mode')
print({{'want': mode, 'got': tm, 'open': opened.get('ok'), 'warm': st.get('warm_state'),
       'chunks': eng.get('chunks'), 'url': c.base}})
"""
    subprocess.run(
        [str(VENV_PY), "-c", script],
        cwd=str(ROOT),
        env=env,
        check=False,
    )


def run_arm(
    arm: str,
    cfg: dict[str, Any],
    repo: Path,
    mission: dict[str, Any],
    *,
    model: str | None,
    dry_run: bool,
    encourage: str = "soft",
) -> dict[str, Any]:
    work = OUT / "runs" / f"{arm}_{int(time.time())}"
    work.mkdir(parents=True, exist_ok=True)
    cfg_path = work / "opencode.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    project_cfg = repo / "opencode.json"
    backup = work / "opencode.json.project_backup"
    had_project_cfg = project_cfg.is_file()
    if had_project_cfg:
        shutil.copy2(project_cfg, backup)
    shutil.copy2(cfg_path, project_cfg)

    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(cfg_path)
    env.pop("CTX_HOME", None)
    env["CTX_ENGINE_URL"] = "http://127.0.0.1:8765"
    _inject_model_env(env)
    if arm == "ce_d_rerank":
        env["CTX_RETRIEVE"] = "D"
    elif arm == "ce_r_plan":
        env["CTX_RETRIEVE"] = "R_plan"

    turns_out: list[dict[str, Any]] = []
    session_title = f"soft-ab-{arm}-{int(time.time())}"

    try:
        for i, turn in enumerate(mission["turns"]):
            nudge = (
                "REMINDER: use your MCP search/graph tools first this turn."
                if encourage == "high"
                else ""
            )
            prompt = " | ".join(
                x
                for x in [
                    f"ARM={arm}",
                    _system_hint(arm, encourage=encourage).replace("\n", " "),
                    nudge,
                    f"Task {turn['id']}: {turn['prompt']}",
                    "Repo root is the working directory.",
                ]
                if x
            )
            cmd = [
                OPENCODE,
                "run",
                "--format",
                "json",
                "--auto",
                "--pure",
                "--dir",
                str(repo),
                "--title",
                session_title,
            ]
            if i > 0:
                cmd.append("--continue")
            if model:
                cmd.extend(["--model", model])
            cmd.append(prompt)

            (work / f"{turn['id']}_cmd.txt").write_text(" ".join(cmd), encoding="utf-8")
            if dry_run:
                turns_out.append({"turn": turn["id"], "dry_run": True, "cmd": cmd})
                continue

            print(f"\n=== {arm} / {turn['id']} ===", flush=True)
            t0 = time.perf_counter()
            try:
                proc = subprocess.run(
                    cmd,
                    cwd=str(repo),
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=480,
                )
            except subprocess.TimeoutExpired:
                turns_out.append(
                    {
                        "turn": turn["id"],
                        "ok": False,
                        "error": "timeout",
                        "ms": 480000,
                        "tokens_total": 0,
                    }
                )
                print("  TIMEOUT", flush=True)
                continue
            ms = (time.perf_counter() - t0) * 1000
            (work / f"{turn['id']}_stdout.txt").write_text(proc.stdout or "", encoding="utf-8")
            (work / f"{turn['id']}_stderr.txt").write_text(proc.stderr or "", encoding="utf-8")
            events = _parse_jsonl(proc.stdout or "")
            text = _extract_assistant_text(events)
            tok = _sum_tokens(events)
            rub = _score(text, turn)
            row = {
                "turn": turn["id"],
                "ok": rub["ok"],
                "touch_ok": rub["touch_ok"],
                "avoid_ok": rub["avoid_ok"],
                "avoid_hit": rub.get("avoid_hit"),
                "ms": round(ms, 1),
                "exit_code": proc.returncode,
                "text_excerpt": text[:1500],
                "events": len(events),
                **tok,
            }
            turns_out.append(row)
            print(
                f"  {'PASS' if rub['ok'] else 'FAIL'} touch={rub['touch_ok']} "
                f"avoid={rub['avoid_ok']} tokens={tok['tokens_total']} "
                f"tools={tok['tool_calls']} mcp={tok['mcp_tool_calls']} "
                f"builtin={tok['builtin_tool_calls']} ms={ms:.0f}",
                flush=True,
            )
    finally:
        if had_project_cfg:
            shutil.copy2(backup, project_cfg)
        elif project_cfg.is_file():
            project_cfg.unlink()

    passed = sum(1 for t in turns_out if t.get("ok"))
    total = max(len(turns_out), 1)
    return {
        "arm": arm,
        "work": str(work),
        "rubric_pass": passed,
        "rubric_total": len(turns_out),
        "rubric_rate": round(passed / total, 4),
        "tokens_total": sum(int(t.get("tokens_total") or 0) for t in turns_out),
        "tokens_input": sum(int(t.get("tokens_input") or 0) for t in turns_out),
        "tokens_output": sum(int(t.get("tokens_output") or 0) for t in turns_out),
        "tool_calls": sum(int(t.get("tool_calls") or 0) for t in turns_out),
        "mcp_tool_calls": sum(int(t.get("mcp_tool_calls") or 0) for t in turns_out),
        "builtin_tool_calls": sum(int(t.get("builtin_tool_calls") or 0) for t in turns_out),
        "wall_ms": round(sum(float(t.get("ms") or 0) for t in turns_out), 1),
        "turns": turns_out,
        "config": str(cfg_path),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Soft OpenCode A/B (graphify vs CE R_plan vs CE D)")
    ap.add_argument("--arms", nargs="+", default=list(ARMS), choices=list(ARMS))
    ap.add_argument(
        "--model",
        default="opencode/deepseek-v4-flash-free",
        help="Default: free DeepSeek (Nova/Bedrock flaky with MCP). Override as needed.",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-daemon", action="store_true")
    ap.add_argument(
        "--encourage",
        choices=["soft", "high"],
        default="soft",
        help="soft=MCP when needed; high=strongly prefer MCP first every locate",
    )
    args = ap.parse_args()

    mission = _load_mission()
    repo = (ROOT / mission["repo"]).resolve()
    if not repo.is_dir():
        print(f"repo missing: {repo}", file=sys.stderr)
        return 2
    if "graphify" in args.arms and not GRAPH_JSON.is_file():
        print(f"graph.json missing: {GRAPH_JSON}", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    os.environ.pop("CTX_HOME", None)
    os.environ.pop("CTX_ENGINE_URL", None)

    configs = _arm_configs(repo)
    results: list[dict[str, Any]] = []
    t_all = time.perf_counter()
    for arm in args.arms:
        if not args.skip_daemon and not args.dry_run and arm.startswith("ce_"):
            mode = "D" if arm == "ce_d_rerank" else "R_plan"
            print(f"\nensuring CE daemon CTX_RETRIEVE={mode}…", flush=True)
            _ensure_daemon(repo, retrieve_mode=mode)
        results.append(
            run_arm(
                arm,
                configs[arm],
                repo,
                mission,
                model=args.model,
                dry_run=args.dry_run,
                encourage=args.encourage,
            )
        )
    wall_s = time.perf_counter() - t_all

    def quality(r: dict[str, Any]) -> bool:
        if args.dry_run:
            return True
        return float(r.get("rubric_rate") or 0) >= 0.5 or int(r.get("rubric_pass") or 0) >= 2

    qualifiers = [r for r in results if quality(r)]
    pool = qualifiers or results
    ranked = sorted(
        pool,
        key=lambda r: (
            int(r.get("tokens_total") or 10**12),
            -float(r.get("rubric_rate") or 0),
        ),
    )
    by_tokens = sorted(results, key=lambda r: int(r.get("tokens_total") or 10**12))

    table = []
    for r in results:
        table.append(
            {
                "arm": r["arm"],
                "tokens_total": r.get("tokens_total"),
                "tokens_input": r.get("tokens_input"),
                "tokens_output": r.get("tokens_output"),
                "rubric_pass": r.get("rubric_pass"),
                "rubric_total": r.get("rubric_total"),
                "tool_calls": r.get("tool_calls"),
                "mcp_tool_calls": r.get("mcp_tool_calls"),
                "builtin_tool_calls": r.get("builtin_tool_calls"),
                "wall_ms": r.get("wall_ms"),
            }
        )

    report = {
        "mission": mission["title"],
        "repo": str(repo),
        "model": args.model,
        "wall_s": round(wall_s, 1),
        "policy": (
            "high — MCP first every locate; read/grep only after MCP paths"
            if args.encourage == "high"
            else "soft — read/grep allowed; MCP encouraged when semantic locate needed"
        ),
        "encourage": args.encourage,
        "primary_metric": "tokens_total (lower better among quality>=0.5)",
        "arms": results,
        "table": table,
        "winner_tokens": ranked[0]["arm"] if ranked else None,
        "ranking_by_tokens": [
            {
                "arm": r["arm"],
                "tokens_total": r.get("tokens_total"),
                "rubric_rate": r.get("rubric_rate"),
                "tool_calls": r.get("tool_calls"),
            }
            for r in by_tokens
        ],
    }
    out = OUT / f"report_{int(time.time())}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "report_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n=== TOKEN WINNER: {report['winner_tokens']} ===", flush=True)
    print(f"wall_s={wall_s:.0f}", flush=True)
    print(json.dumps(table, indent=2), flush=True)
    print(f"wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

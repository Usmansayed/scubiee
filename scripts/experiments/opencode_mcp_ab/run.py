"""Real OpenCode MCP A/B: graphify vs D_rerank-only vs CE context-nav.

Runs `opencode run` three times with isolated MCP configs against the same
mission prompts, then scores must_touch / must_avoid and rough token usage.

Usage:
  .\\.venv\\Scripts\\python.exe -u scripts\\experiments\\opencode_mcp_ab\\run.py
  .\\.venv\\Scripts\\python.exe -u scripts\\experiments\\opencode_mcp_ab\\run.py --arms ce_nav
  .\\.venv\\Scripts\\python.exe -u scripts\\experiments\\opencode_mcp_ab\\run.py --dry-run
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
OUT = ROOT / "out" / "experiments" / "opencode_mcp_ab"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
if not VENV_PY.is_file():
    VENV_PY = Path(sys.executable)

# Prefer the real .exe — Windows .cmd wrappers truncate multi-line argv.
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


def _load_mission() -> dict[str, Any]:
    return json.loads((HERE / "mission.json").read_text(encoding="utf-8"))


def _provider_block() -> dict[str, Any]:
    """Merge Bedrock + Google AI Studio bootstrap configs over user Vertex config."""
    merged: dict[str, Any] = {}
    for name in ("opencode_bedrock.json", "opencode_google.json"):
        cfg_path = OUT / name
        if not cfg_path.is_file():
            continue
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        prov = data.get("provider")
        if isinstance(prov, dict) and prov:
            merged.update(prov)
    if merged:
        return {"provider": merged}

    cfg = Path.home() / ".config" / "opencode" / "opencode.jsonc"
    if not cfg.is_file():
        cfg = Path.home() / ".config" / "opencode" / "opencode.json"
    if not cfg.is_file():
        return {}
    raw = cfg.read_text(encoding="utf-8")
    raw = re.sub(r"^\s*//.*$", "", raw, flags=re.M)
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
    ring = OUT / ".google_keys.json"
    if not ring.is_file():
        return os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY") or os.environ.get(
            "GEMINI_API_KEY"
        )
    try:
        data = json.loads(ring.read_text(encoding="utf-8"))
        keys = data.get("keys") or []
        i = int(data.get("i") or 0)
        if keys:
            return str(keys[i % len(keys)])
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        pass
    return os.environ.get("GOOGLE_GENERATIVE_AI_API_KEY")


def _inject_model_env(env: dict[str, str]) -> None:
    """Load Bedrock bearer token / Google AI Studio key into process env."""
    bedrock = OUT / ".bedrock.json"
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
    gkey = _active_google_key()
    if gkey:
        env["GOOGLE_GENERATIVE_AI_API_KEY"] = gkey
        env["GEMINI_API_KEY"] = gkey
        env["GOOGLE_API_KEY"] = gkey


def _arm_configs(repo: Path) -> dict[str, dict[str, Any]]:
    py = str(VENV_PY.resolve()).replace("\\", "/")
    packages = str((ROOT / "packages").resolve()).replace("\\", "/")
    repo_s = str(repo.resolve()).replace("\\", "/")
    graph = str(GRAPH_JSON.resolve()).replace("\\", "/") if GRAPH_JSON.is_file() else ""

    base = {
        "$schema": "https://opencode.ai/config.json",
        **_provider_block(),
        "permission": {
            "edit": "deny",
            "bash": "deny",
            "webfetch": "deny",
            "read": "deny",
            "grep": "deny",
            "glob": "deny",
            "list": "deny",
            "skill": "deny",
            "task": "deny",
            "todowrite": "deny",
            "todoread": "deny",
        },
    }

    # Disable broken global frontend-mcp from ~/.config/opencode so arms are clean.
    disabled_global = {
        "frontend-mcp": {
            "type": "local",
            "enabled": False,
            "command": ["echo", "disabled"],
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
                    "command": [
                        py,
                        "-m",
                        "graphify.serve",
                        graph,
                    ],
                    "environment": {
                        "PYTHONPATH": packages,
                    },
                    "timeout": 120000,
                },
            },
        },
        "d_rerank": {
            **base,
            "mcp": {
                **disabled_global,
                "ce-d-rerank": {
                    "type": "local",
                    "enabled": True,
                    "command": [
                        py,
                        "-m",
                        "pipeline.mcp_d_rerank_only",
                    ],
                    "environment": {
                        "PYTHONPATH": packages,
                        "CTX_REPO": repo_s,
                        "CTX_RETRIEVE": "D",
                        "CTX_ENGINE_URL": "http://127.0.0.1:8765",
                    },
                    "timeout": 120000,
                },
            },
        },
        "ce_nav": {
            **base,
            "mcp": {
                **disabled_global,
                "context-engine": {
                    "type": "local",
                    "enabled": True,
                    "command": [
                        py,
                        "-m",
                        "pipeline.mcp_server",
                    ],
                    "environment": {
                        "PYTHONPATH": packages,
                        "CTX_REPO": repo_s,
                        "CTX_RETRIEVE": "R_plan",
                        "CTX_ENGINE_URL": "http://127.0.0.1:8765",
                    },
                    "timeout": 120000,
                },
            },
        },
        "d_channel_best": {
            **base,
            "mcp": {
                **disabled_global,
                "ce-d-channel-best": {
                    "type": "local",
                    "enabled": True,
                    "command": [
                        py,
                        "-m",
                        "pipeline.mcp_d_channel_best",
                    ],
                    "environment": {
                        "PYTHONPATH": packages,
                        "CTX_REPO": repo_s,
                        "CTX_RETRIEVE": "D_channel_best",
                        "CTX_ENGINE_URL": "http://127.0.0.1:8765",
                    },
                    "timeout": 120000,
                },
            },
        },
    }


def _system_hint(arm: str) -> str:
    common = (
        "Index is already warm — do NOT call set_repo, register_project, or reindex. "
        "Answer with exact repo-relative file paths. "
        "You MUST call MCP tools before answering — do not invent paths from memory."
    )
    if arm == "graphify":
        return (
            "You have ONLY the graphify MCP (query_graph, get_neighbors, get_node, "
            "graph_stats, etc). Use those tools to find code locations. Do not use "
            f"unrelated MCPs. {common}"
        )
    if arm == "d_rerank":
        return (
            "You have ONLY context-engine D_rerank search_code MCP. Call search_code "
            "to locate files, then reason from the returned previews/paths. Do not "
            "expect follow_imports/read_span — they are unavailable on this arm. "
            f"{common}"
        )
    if arm == "d_channel_best":
        return (
            "You have Context Engine MCP with D_channel_best search_code PLUS "
            "query_graph, grep_code, grep_ident, read_span, graph_neighbors. "
            "Workflow: search_code (seeds) → query_graph and/or grep_* → read_span. "
            f"Prefer small spans over whole files. {common}"
        )
    return (
        "You have Context Engine MCP with search_code PLUS navigation tools: "
        "query_graph, read_span, follow_imports, graph_neighbors, grep_ident. "
        "Workflow: search_code (arrow) → query_graph / follow_imports / grep_ident / "
        f"graph_neighbors → read_span for small spans. Prefer spans over whole files. {common}"
    )


def _score(text: str, turn: dict[str, Any]) -> dict[str, Any]:
    """Score final answer text only (not tool dumps)."""
    low = text.lower().replace("\\", "/")
    touch_ok = all(need.lower() in low for need in (turn.get("must_touch") or []))
    # Fail avoid only if a distractor looks like a cited path in the answer.
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
    avoid_ok = not avoid_hit
    return {
        "touch_ok": touch_ok,
        "avoid_ok": avoid_ok,
        "ok": touch_ok and avoid_ok,
        "avoid_hit": avoid_hit,
    }


def _extract_assistant_text(events: list[dict[str, Any]]) -> str:
    """Final natural-language answer only — never tool payloads (they poison avoid)."""
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
    # Prefer the last substantial answer blob.
    nonempty = [c.strip() for c in chunks if c and c.strip()]
    if not nonempty:
        return ""
    if len(nonempty) == 1:
        return nonempty[0]
    # Concatenate late texts (model often narrates then answers).
    return "\n".join(nonempty[-3:])


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
    """Sum OpenCode step_finish token counters across a turn.

    ``tokens_total`` prefers provider ``total`` when present; else
    input+output+cache_read+cache_write (tokens exchanged with the model).
    """
    total = input_t = output_t = reasoning = cache_read = cache_write = 0
    cost = 0.0
    steps = 0
    tools = 0
    for ev in events:
        part = ev.get("part") if isinstance(ev.get("part"), dict) else {}
        typ = ev.get("type") or ""
        if typ == "tool_use" or part.get("type") == "tool":
            tools += 1
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
    exchanged = input_t + output_t + cache_read + cache_write
    if total <= 0:
        total = exchanged
    return {
        "steps": steps,
        "tool_calls": tools,
        "tokens_total": total,
        "tokens_exchanged": exchanged,
        "tokens_input": input_t,
        "tokens_output": output_t,
        "tokens_reasoning": reasoning,
        "tokens_cache_read": cache_read,
        "tokens_cache_write": cache_write,
        "cost": round(cost, 6),
    }


def _ensure_daemon(repo: Path, *, retrieve_mode: str | None = None) -> None:
    """Ensure daemon is up on :8765, warm on repo, optionally force CTX_RETRIEVE."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "packages")
    env.pop("CTX_HOME", None)
    env.pop("CTX_ENGINE_URL", None)
    env.pop("CTX_SEARCH_URL", None)
    mode = (retrieve_mode or "R_plan").strip()
    env["CTX_RETRIEVE"] = mode
    script = f"""
from pathlib import Path
import os
from pipeline.daemon import ensure_daemon, force_restart_daemon, stop_daemon
from pipeline.client import EngineClient
repo = Path(r'{repo}')
mode = {mode!r}
os.environ['CTX_RETRIEVE'] = mode
os.environ.pop('CTX_HOME', None)
# Always restart when switching retrieve mode so engine.py sees CTX_RETRIEVE.
force_restart_daemon(repo)
c = EngineClient()
opened = c.open_repo(str(repo), wait=True)
st = c.status(str(repo))
eng = st.get('engine') or {{}}
print({{'mode': mode, 'open': opened.get('ok'), 'warm': st.get('warm_state'),
       'chunks': eng.get('chunks'), 'root': eng.get('root'), 'url': c.base}})
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
) -> dict[str, Any]:
    work = OUT / "runs" / f"{arm}_{int(time.time())}"
    work.mkdir(parents=True, exist_ok=True)
    cfg_path = work / "opencode.json"
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # OpenCode loads project opencode.json from --dir; swap in arm config safely.
    project_cfg = repo / "opencode.json"
    backup = work / "opencode.json.project_backup"
    had_project_cfg = project_cfg.is_file()
    if had_project_cfg:
        shutil.copy2(project_cfg, backup)
    shutil.copy2(cfg_path, project_cfg)

    env = os.environ.copy()
    env["OPENCODE_CONFIG"] = str(cfg_path)
    env.pop("CTX_HOME", None)
    env.pop("CTX_ENGINE_URL", None)
    env.pop("CTX_SEARCH_URL", None)
    env["CTX_ENGINE_URL"] = "http://127.0.0.1:8765"
    _inject_model_env(env)
    if arm == "d_rerank":
        env["CTX_RETRIEVE"] = "D"
    elif arm == "ce_nav":
        env["CTX_RETRIEVE"] = "R_plan"
    elif arm == "d_channel_best":
        env["CTX_RETRIEVE"] = "D_channel_best"

    turns_out: list[dict[str, Any]] = []
    session_title = f"mcp-tok-{arm}-{int(time.time())}"

    try:
        for i, turn in enumerate(mission["turns"]):
            prompt = " | ".join(
                [
                    f"ARM={arm}",
                    _system_hint(arm).replace("\n", " "),
                    f"Task {turn['id']}: {turn['prompt']}",
                    "Repo root is the working directory. Prefer MCP tools. Be concise.",
                ]
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
            # Continue the same agent session across turns (real agentic work).
            if i > 0:
                cmd.append("--continue")
            if model:
                cmd.extend(["--model", model])
            cmd.append(prompt)

            (work / f"{turn['id']}_cmd.txt").write_text(
                " ".join(cmd), encoding="utf-8"
            )
            if dry_run:
                turns_out.append({"turn": turn["id"], "dry_run": True, "cmd": cmd})
                continue

            print(f"\n=== {arm} / {turn['id']} ===")
            best_row: dict[str, Any] | None = None
            # Retry once if the model answers with zero MCP tool calls (invalid A/B).
            for attempt in range(2):
                t0 = time.perf_counter()
                attempt_cmd = list(cmd)
                if attempt > 0:
                    # Fresh session title so continue-state does not poison retry.
                    session_title = f"mcp-tok-{arm}-{int(time.time())}-r{attempt}"
                    attempt_cmd = [
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
                    if model:
                        attempt_cmd.extend(["--model", model])
                    attempt_cmd.append(
                        prompt
                        + " | RETRY: previous attempt used ZERO tools — you MUST "
                        "call MCP tools now before answering."
                    )
                    print(f"  retry {attempt} (zero tools on prior attempt)…")
                try:
                    proc = subprocess.run(
                        attempt_cmd,
                        cwd=str(repo),
                        env=env,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=420,
                    )
                except subprocess.TimeoutExpired as exc:
                    partial = (exc.stdout or "") if isinstance(exc.stdout, str) else (
                        exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
                    )
                    (work / f"{turn['id']}_timeout_stdout.txt").write_text(
                        partial, encoding="utf-8"
                    )
                    events = _parse_jsonl(partial)
                    tok = _sum_tokens(events)
                    best_row = {
                        "turn": turn["id"],
                        "ok": False,
                        "error": "timeout",
                        "ms": 420000,
                        "invalid_no_tools": int(tok.get("tool_calls") or 0) == 0,
                        **tok,
                    }
                    print(
                        f"  TIMEOUT tools={tok.get('tool_calls')} "
                        f"tokens={tok.get('tokens_total')}"
                    )
                    break
                ms = (time.perf_counter() - t0) * 1000
                suffix = "" if attempt == 0 else f"_retry{attempt}"
                (work / f"{turn['id']}{suffix}_stdout.txt").write_text(
                    proc.stdout or "", encoding="utf-8"
                )
                (work / f"{turn['id']}{suffix}_stderr.txt").write_text(
                    proc.stderr or "", encoding="utf-8"
                )
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
                    "attempt": attempt,
                    "invalid_no_tools": int(tok.get("tool_calls") or 0) == 0,
                    **tok,
                }
                best_row = row
                print(
                    f"  {'PASS' if rub['ok'] else 'FAIL'} touch={rub['touch_ok']} "
                    f"avoid={rub['avoid_ok']} tokens={tok['tokens_total']} "
                    f"exchanged={tok['tokens_exchanged']} tools={tok['tool_calls']} "
                    f"ms={ms:.0f}"
                )
                if int(tok.get("tool_calls") or 0) > 0:
                    break
            if best_row is not None:
                turns_out.append(best_row)
    finally:
        if had_project_cfg:
            shutil.copy2(backup, project_cfg)
        elif project_cfg.is_file():
            project_cfg.unlink()

    passed = sum(1 for t in turns_out if t.get("ok"))
    total = max(len(turns_out), 1)
    tokens_total = sum(int(t.get("tokens_total") or 0) for t in turns_out)
    tokens_exchanged = sum(int(t.get("tokens_exchanged") or 0) for t in turns_out)
    tokens_in = sum(int(t.get("tokens_input") or 0) for t in turns_out)
    tokens_out = sum(int(t.get("tokens_output") or 0) for t in turns_out)
    tool_calls = sum(int(t.get("tool_calls") or 0) for t in turns_out)
    wall_ms = sum(float(t.get("ms") or 0) for t in turns_out)
    invalid = any(t.get("invalid_no_tools") for t in turns_out) or tool_calls == 0
    return {
        "arm": arm,
        "work": str(work),
        "rubric_pass": passed,
        "rubric_total": len(turns_out),
        "rubric_rate": round(passed / total, 4),
        "tokens_total": tokens_total,
        "tokens_exchanged": tokens_exchanged,
        "tokens_input": tokens_in,
        "tokens_output": tokens_out,
        "tool_calls": tool_calls,
        "wall_ms": round(wall_ms, 1),
        "invalid_no_tools": invalid,
        "turns": turns_out,
        "config": str(cfg_path),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="OpenCode MCP real A/B (token-savings)")
    ap.add_argument(
        "--arms",
        nargs="+",
        default=["graphify", "d_channel_best"],
        choices=["graphify", "d_rerank", "ce_nav", "d_channel_best"],
    )
    ap.add_argument(
        "--model",
        default="amazon-bedrock/eu.amazon.nova-pro-v1:0",
        help="provider/model (default: Bedrock Nova Pro EU)",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-daemon", action="store_true")
    args = ap.parse_args()

    mission = _load_mission()
    repo = (ROOT / mission["repo"]).resolve()
    if not repo.is_dir():
        print(f"repo missing: {repo}", file=sys.stderr)
        return 2

    if "graphify" in args.arms and not GRAPH_JSON.is_file():
        print(f"graph.json missing for graphify arm: {GRAPH_JSON}", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    os.environ.pop("CTX_HOME", None)
    os.environ.pop("CTX_ENGINE_URL", None)

    configs = _arm_configs(repo)
    results: list[dict[str, Any]] = []
    t_all = time.perf_counter()
    ce_modes = {
        "d_rerank": "D",
        "ce_nav": "R_plan",
        "d_channel_best": "D_channel_best",
    }
    for arm in args.arms:
        if not args.skip_daemon and not args.dry_run and arm in ce_modes:
            mode = ce_modes[arm]
            print(f"\nensuring CE daemon with CTX_RETRIEVE={mode}…")
            _ensure_daemon(repo, retrieve_mode=mode)
        results.append(
            run_arm(
                arm,
                configs[arm],
                repo,
                mission,
                model=args.model,
                dry_run=args.dry_run,
            )
        )
    wall_s = time.perf_counter() - t_all

    # Primary ranking: among quality-passing arms with real tool use, lowest tokens win.
    def quality(r: dict[str, Any]) -> bool:
        if args.dry_run:
            return True
        if r.get("invalid_no_tools"):
            return False
        return float(r.get("rubric_rate") or 0) >= 0.5 or int(r.get("rubric_pass") or 0) >= 2

    qualifiers = [r for r in results if quality(r)]
    pool = qualifiers or [r for r in results if not r.get("invalid_no_tools")] or results
    ranked = sorted(
        pool,
        key=lambda r: (
            int(r.get("tokens_total") or 10**12),
            -float(r.get("rubric_rate") or 0),
            int(r.get("tool_calls") or 10**9),
        ),
    )
    by_tokens = sorted(
        results,
        key=lambda r: int(r.get("tokens_total") or 10**12),
    )
    baseline = next((r for r in results if r["arm"] == "graphify"), None)
    if baseline is None:
        baseline = next((r for r in results if r["arm"] == "d_rerank"), None)
    savings = []
    for r in results:
        base_tok = int((baseline or {}).get("tokens_total") or 0)
        tok = int(r.get("tokens_total") or 0)
        saved = (base_tok - tok) if base_tok and tok else None
        pct = round(100.0 * saved / base_tok, 1) if base_tok and saved is not None else None
        savings.append(
            {
                "arm": r["arm"],
                "tokens_total": tok,
                "tokens_exchanged": r.get("tokens_exchanged"),
                "tokens_vs_baseline": saved,
                "pct_saved_vs_baseline": pct,
                "baseline": (baseline or {}).get("arm"),
                "rubric_pass": r.get("rubric_pass"),
                "rubric_total": r.get("rubric_total"),
                "tool_calls": r.get("tool_calls"),
                "invalid_no_tools": r.get("invalid_no_tools"),
                "wall_ms": r.get("wall_ms"),
            }
        )

    report = {
        "mission": mission["title"],
        "repo": str(repo),
        "model": args.model,
        "wall_s": round(wall_s, 1),
        "primary_metric": "tokens_total (lower better among quality>=0.5)",
        "arms": results,
        "token_savings": savings,
        "winner_tokens": ranked[0]["arm"] if ranked else None,
        "ranking_by_tokens": [
            {
                "arm": r["arm"],
                "tokens_total": r.get("tokens_total"),
                "tokens_exchanged": r.get("tokens_exchanged"),
                "rubric_rate": r.get("rubric_rate"),
                "tool_calls": r.get("tool_calls"),
                "invalid_no_tools": r.get("invalid_no_tools"),
            }
            for r in by_tokens
        ],
    }
    out = OUT / f"report_{int(time.time())}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest = OUT / "report_latest.json"
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n=== TOKEN WINNER: {report['winner_tokens']} ===")
    print(f"wall_s={wall_s:.0f}")
    print(json.dumps(report["token_savings"], indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

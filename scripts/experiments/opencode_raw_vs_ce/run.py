"""Isolated A/B: raw (grep/read/glob only) vs ce_search (CE search MCP + grep/read/glob).

Measures who finishes with fewer tokens on vague soft queries.

Usage:
  .\.venv\Scripts\python.exe -u scripts\experiments\opencode_raw_vs_ce\run.py
  .\.venv\Scripts\python.exe -u scripts\experiments\opencode_raw_vs_ce\run.py --arms ce_search
  .\.venv\Scripts\python.exe -u scripts\experiments\opencode_raw_vs_ce\run.py --dry-run
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
OUT = ROOT / "out" / "experiments" / "opencode_raw_vs_ce"
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

ARMS = ("raw", "ce_search")


# ---------------------------------------------------------------------------
# Provider / API key helpers (reuse pattern from soft_ab)
# ---------------------------------------------------------------------------

def _provider_block() -> dict[str, Any]:
    """Load provider config from bootstrap files or user opencode config."""
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
            return {"provider": prov}
    # Fallback: read user's global opencode config
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


# ---------------------------------------------------------------------------
# Arm configs
# ---------------------------------------------------------------------------

def _arm_configs(repo: Path) -> dict[str, dict[str, Any]]:
    py = str(VENV_PY.resolve()).replace("\\", "/")
    packages = str((ROOT / "packages").resolve()).replace("\\", "/")
    repo_s = str(repo.resolve()).replace("\\", "/")

    # Both arms get read/grep/glob — the only difference is MCP availability.
    soft_perms = {
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

    base = {
        "$schema": "https://opencode.ai/config.json",
        **_provider_block(),
        "permission": soft_perms,
    }

    # Disable any global MCP that might leak in
    disabled_global = {
        "frontend-mcp": {
            "type": "local",
            "enabled": False,
            "command": ["echo", "disabled"],
        }
    }

    return {
        # RAW: no MCP at all — agent must use native grep/read/glob only
        "raw": {
            **base,
            "mcp": {**disabled_global},
        },
        # CE_SEARCH: Context Engine search MCP + native read/grep/glob
        "ce_search": {
            **base,
            "mcp": {
                **disabled_global,
                "context-engine": {
                    "type": "local",
                    "enabled": True,
                    "command": [py, "-m", "pipeline.mcp_search_only"],
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
    }


def _system_hint(arm: str) -> str:
    common = (
        "Answer with exact repo-relative file paths. Be concise. "
        "Do not edit files — read-only discovery."
    )
    if arm == "raw":
        return (
            "You have ONLY built-in read, grep, and glob tools. No MCP. "
            "Use grep to search by pattern, glob to find files, "
            f"read to open them. {common}"
        )
    return (
        "You have Context Engine search_code (semantic search MCP) plus "
        "built-in read/grep/glob. When you need to locate unfamiliar code "
        "by meaning (not an exact string), prefer search_code first — "
        f"then open files with read. {common}"
    )


# ---------------------------------------------------------------------------
# JSONL parsing + scoring (same as soft_ab)
# ---------------------------------------------------------------------------

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
            name = str(
                part.get("tool") or part.get("name") or ev.get("tool") or ""
            ).lower()
            if any(k in name for k in ("search_code", "ce_search", "context")):
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
    exchanged = input_t + output_t + cache_read + cache_write
    if total <= 0:
        total = exchanged
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


def _score(text: str, turn: dict[str, Any]) -> dict[str, Any]:
    low = text.lower().replace("\\", "/")
    touch_ok = all(need.lower() in low for need in (turn.get("must_touch") or []))
    avoid_hit: list[str] = []
    for a in turn.get("must_avoid") or []:
        al = a.lower()
        if (
            f"/{al}" in low
            or f"{al}" in low
            or f"\\{al}" in text.lower()
        ):
            avoid_hit.append(a)
    return {
        "touch_ok": touch_ok,
        "avoid_ok": not avoid_hit,
        "ok": touch_ok and not avoid_hit,
        "avoid_hit": avoid_hit,
    }


# ---------------------------------------------------------------------------
# Run a single arm
# ---------------------------------------------------------------------------

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

    # OpenCode loads opencode.json from --dir; swap in arm config
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
    env["CTX_RETRIEVE"] = "R_plan"
    _inject_model_env(env)

    turns_out: list[dict[str, Any]] = []
    session_title = f"raw-vs-ce-{arm}-{int(time.time())}"

    try:
        for i, turn in enumerate(mission["turns"]):
            prompt = " | ".join([
                f"ARM={arm}",
                _system_hint(arm).replace("\n", " "),
                f"Task {turn['id']}: {turn['prompt']}",
                "Repo root is the working directory.",
            ])
            cmd = [
                OPENCODE,
                "run",
                "--format", "json",
                "--auto",
                "--pure",
                "--dir", str(repo),
                "--title", session_title,
            ]
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
                turns_out.append({
                    "turn": turn["id"],
                    "ok": False,
                    "error": "timeout",
                    "ms": 480000,
                    "tokens_total": 0,
                })
                print("  TIMEOUT", flush=True)
                # Reset session title so next turn doesn't --continue a dead session
                session_title = f"raw-vs-ce-{arm}-{int(time.time())}"
                continue
            ms = (time.perf_counter() - t0) * 1000

            (work / f"{turn['id']}_stdout.txt").write_text(
                proc.stdout or "", encoding="utf-8"
            )
            (work / f"{turn['id']}_stderr.txt").write_text(
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
                "text_len": len(text),
                "events_count": len(events),
                **tok,
            }
            turns_out.append(row)
            print(
                f"  {'PASS' if rub['ok'] else 'FAIL'} "
                f"touch={rub['touch_ok']} avoid={rub['avoid_ok']} "
                f"tokens={tok['tokens_total']} tools={tok['tool_calls']} "
                f"mcp={tok['mcp_tool_calls']} builtin={tok['builtin_tool_calls']} "
                f"ms={ms:.0f}",
                flush=True,
            )
    finally:
        # Restore original opencode.json
        if had_project_cfg:
            shutil.copy2(backup, project_cfg)
        elif project_cfg.is_file():
            project_cfg.unlink()

    passed = sum(1 for t in turns_out if t.get("ok"))
    total_turns = max(len(turns_out), 1)
    return {
        "arm": arm,
        "work": str(work),
        "rubric_pass": passed,
        "rubric_total": len(turns_out),
        "rubric_rate": round(passed / total_turns, 4),
        "tokens_total": sum(int(t.get("tokens_total") or 0) for t in turns_out),
        "tokens_input": sum(int(t.get("tokens_input") or 0) for t in turns_out),
        "tokens_output": sum(int(t.get("tokens_output") or 0) for t in turns_out),
        "tool_calls": sum(int(t.get("tool_calls") or 0) for t in turns_out),
        "mcp_tool_calls": sum(int(t.get("mcp_tool_calls") or 0) for t in turns_out),
        "builtin_tool_calls": sum(int(t.get("builtin_tool_calls") or 0) for t in turns_out),
        "wall_ms": round(sum(float(t.get("ms") or 0) for t in turns_out), 1),
        "cost": round(sum(float(t.get("cost") or 0) for t in turns_out), 6),
        "turns": turns_out,
        "config": str(cfg_path),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Isolated A/B: raw (grep/read only) vs ce_search (CE MCP + grep/read)"
    )
    ap.add_argument("--arms", nargs="+", default=list(ARMS), choices=list(ARMS))
    ap.add_argument(
        "--model",
        default=None,
        help="Model override (defaults to user opencode config or free model)",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mission = json.loads((HERE / "mission.json").read_text(encoding="utf-8"))
    repo = (ROOT / mission["repo"]).resolve()
    if not repo.is_dir():
        print(f"ERROR: repo missing: {repo}", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    os.environ.pop("CTX_HOME", None)
    os.environ.pop("CTX_ENGINE_URL", None)

    configs = _arm_configs(repo)
    results: list[dict[str, Any]] = []
    t_all = time.perf_counter()

    for arm in args.arms:
        print(f"\n{'='*60}\n  ARM: {arm}\n{'='*60}", flush=True)
        results.append(
            run_arm(arm, configs[arm], repo, mission, model=args.model, dry_run=args.dry_run)
        )

    wall_s = time.perf_counter() - t_all

    # Rank by tokens (lower = better) among arms that pass >= 50% rubric
    def quality(r: dict[str, Any]) -> bool:
        if args.dry_run:
            return True
        return float(r.get("rubric_rate") or 0) >= 0.5

    qualifiers = [r for r in results if quality(r)]
    pool = qualifiers or results
    ranked = sorted(pool, key=lambda r: int(r.get("tokens_total") or 10**12))

    table = []
    for r in results:
        table.append({
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
            "cost": r.get("cost"),
        })

    winner = ranked[0]["arm"] if ranked else "unknown"
    # Calculate token savings
    savings_pct = None
    if len(results) == 2 and not args.dry_run:
        t_raw = next((r["tokens_total"] for r in results if r["arm"] == "raw"), 0)
        t_ce = next((r["tokens_total"] for r in results if r["arm"] == "ce_search"), 0)
        if t_raw > 0:
            savings_pct = round((1 - t_ce / t_raw) * 100, 1)

    report = {
        "experiment": "raw_vs_ce_search",
        "mission": mission["title"],
        "repo": str(repo),
        "model": args.model or "(config default)",
        "wall_s": round(wall_s, 1),
        "primary_metric": "tokens_total (lower = better, among rubric >= 50%)",
        "winner": winner,
        "ce_token_savings_pct": savings_pct,
        "table": table,
        "arms": results,
    }

    out_file = OUT / f"report_{int(time.time())}.json"
    out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (OUT / "report_latest.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    # Print summary
    print(f"\n{'='*60}", flush=True)
    print(f"  WINNER (by tokens): {winner}", flush=True)
    if savings_pct is not None:
        direction = "CE saves" if savings_pct > 0 else "Raw saves"
        print(f"  Token delta: {direction} {abs(savings_pct)}%", flush=True)
    print(f"  Wall time: {wall_s:.0f}s", flush=True)
    print(f"{'='*60}", flush=True)
    print(json.dumps(table, indent=2), flush=True)
    print(f"\nReport: {out_file}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

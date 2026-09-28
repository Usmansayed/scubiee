#!/usr/bin/env python3
"""Phase C live compliance A/B — baseline GATE vs calibrated Prefer/Forbid.

Both arms HAVE Scubiee MCP. Diff is instruction policy only:

* baseline   — current mandatory map→pack ladder (SCUBIEE_PROMPT_EXTRA)
* calibrated — Prefer/Forbid from locate-force framework §6 (needles → Grep)

Usage:
  PYTHONPATH=packages python scripts/locate_calibration_phase_c_live.py --smoke
  PYTHONPATH=packages python scripts/locate_calibration_phase_c_live.py --tasks C02_pack_expand_ladder,C09_auth_jwt_trap,C01_connect_permissions_gate
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

_SPEC = importlib.util.spec_from_file_location(
    "kiro_mcp_ab_eval", ROOT / "scripts" / "kiro_mcp_ab_eval.py"
)
assert _SPEC and _SPEC.loader
_k = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_k)

OUT_JSON = ROOT / "docs" / "superpowers" / "plans" / "locate-calibration-phase-c-live-results.json"
OUT_MD = ROOT / "docs" / "superpowers" / "plans" / "2026-09-07-locate-calibration-phase-c-live.md"
LOG_ROOT = ROOT / "out" / "kiro_phase_c_live"
AGENTS_DIR = ROOT / ".kiro" / "agents"

CALIBRATED_PROMPT_EXTRA = """
You HAVE the scubiee MCP server. BAN shell `scubiee map|pack|expand` — use MCP tools only.

LOCATE PRIORITY (calibrated Prefer/Forbid — research draft):
- Soft / structural / multi-hop locate → PREFER map → pack_context(mode=lean, same query) → Native-Read top heatmap locs. expand_context only if thin.
- Exact edit with a good suggested_seed → PREFER map then pack (forbid empty/_/test seeds).
- Exact literals / imports / error strings / JWT-like needles → REQUIRE-FIRST host Grep/rg (do NOT open with map/pack).
- Filename / path pattern → Prefer Glob/fileSearch first.
- Known path:lines → Prefer span Read; do not rematerialize via soft map.
- After a Scubiee heatmap, guided native Grep/Read on card locs is encouraged.
- If Scubiee errors/unavailable → native tools; do not deadlock.
- Do not run parallel explore thrash alongside Scubiee on the same question.
- Do NOT BAN native forever — Grep/Glob/Read stay first-class for exception classes.

Finish with the requested JSON block.
"""

# 3-task compliance slice: soft ladder, needle trap, multi-hop connect
LIVE_TASK_IDS = [
    "C02_pack_expand_ladder",  # soft / structural
    "C09_auth_jwt_trap",  # literal needle — Forbid-first map
    "C01_connect_permissions_gate",  # multi-hop exact-ish
]


def write_policy_agents(*, model: str) -> dict[str, Path]:
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    common = {
        "includeMcpJson": False,
        "includePowers": False,
        "model": model,
        "permissions": {
            "rules": [
                {
                    "capability": "shell",
                    "match": [
                        "rg *",
                        "findstr *",
                        "dir *",
                        "ls *",
                        "type *",
                        "Get-ChildItem *",
                        "Select-String *",
                    ],
                    "effect": "allow",
                },
            ]
        },
        "mcpServers": {"scubiee": _k._scubiee_mcp_entry()},
        "tools": _k.BUILTIN_TOOLS + _k.SCUBIEE_TOOLS,
        "allowedTools": _k.BUILTIN_TOOLS + _k.SCUBIEE_TOOLS,
        "resources": [
            "file://AGENTS.md",
            "file://.kiro/steering/scubiee.md",
        ],
    }
    baseline = {
        **common,
        "name": "ab_policy_baseline",
        "description": "Phase C live — baseline mandatory map→pack GATE",
        "prompt": _k.SHARED_PROMPT + _k.SCUBIEE_PROMPT_EXTRA,
    }
    calibrated = {
        **common,
        "name": "ab_policy_calibrated",
        "description": "Phase C live — calibrated Prefer/Forbid (needles→Grep)",
        "prompt": _k.SHARED_PROMPT + CALIBRATED_PROMPT_EXTRA,
    }
    # Avoid AGENTS.md GATE overpowering calibrated: drop steering for calibrated arm
    calibrated["resources"] = ["file://AGENTS.md"]
    b_path = AGENTS_DIR / "ab_policy_baseline.json"
    c_path = AGENTS_DIR / "ab_policy_calibrated.json"
    _k._write_json(b_path, baseline)
    _k._write_json(c_path, calibrated)
    return {"baseline": b_path, "calibrated": c_path}


def _classify_task(task_id: str) -> str:
    if "jwt" in task_id or "auth" in task_id:
        return "literal_needle"
    if "connect" in task_id:
        return "exact_edit"
    return "soft_understand"


def _compliance(row: dict[str, Any], taxonomy: str) -> dict[str, Any]:
    tools = row.get("tools") or {}
    scubiee = list(tools.get("scubiee_tools") or [])
    native = list(tools.get("native_tools") or [])
    used_map = any(t in {"map", "map_context"} for t in scubiee)
    used_pack = "pack_context" in scubiee
    used_grepish = any(
        t in {"execute_bash", "shell", "fs_read", "fileread", "grep", "filesearch"}
        or "bash" in t
        or "read" in t
        for t in native
    )
    over_use = False
    under_use = False
    if taxonomy == "literal_needle":
        # over_use: opened with map/pack
        over_use = used_map or used_pack
    if taxonomy in {"soft_understand", "exact_edit"}:
        under_use = not used_map and not used_pack
    return {
        "taxonomy": taxonomy,
        "used_map": used_map,
        "used_pack": used_pack,
        "used_native": bool(native) or used_grepish,
        "over_use": over_use,
        "under_use": under_use,
        "scubiee_count": tools.get("scubiee_count"),
        "native_count": tools.get("native_count"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="auto")
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--timeout-s", type=int, default=420)
    ap.add_argument("--tasks", default="", help="Comma task ids (default: LIVE_TASK_IDS)")
    ap.add_argument("--smoke", action="store_true", help="One soft task both arms")
    args = ap.parse_args()

    _k._load_dotenv_key()
    if not os.environ.get("KIRO_API_KEY"):
        print("ERROR: KIRO_API_KEY missing", file=sys.stderr)
        return 2
    if not _k.KIRO.is_file():
        print(f"ERROR: kiro-cli missing: {_k.KIRO}", file=sys.stderr)
        return 2

    by_id = {t["id"]: t for t in _k.TASKS}
    if args.smoke:
        task_ids = ["C02_pack_expand_ladder"]
    elif args.tasks.strip():
        task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()]
    else:
        task_ids = list(LIVE_TASK_IDS)
    tasks = [by_id[i] for i in task_ids if i in by_id]
    if not tasks:
        print("ERROR: no matching tasks", file=sys.stderr)
        return 2

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_dir = LOG_ROOT / run_id
    paths = write_policy_agents(model=args.model)
    _k._validate_agent(paths["baseline"])
    _k._validate_agent(paths["calibrated"])

    protocol = {
        "kind": "phase_c_live_policy_ab",
        "model": args.model,
        "effort": args.effort,
        "timeout_s": args.timeout_s,
        "n_tasks": len(tasks),
        "arms": ["baseline", "calibrated"],
        "both_have_scubiee": True,
        "run_id": run_id,
        "engine_health": _k._engine_health(),
    }
    print(json.dumps({"event": "protocol", **protocol}, indent=2), flush=True)

    runs: list[dict[str, Any]] = []
    order = [
        ("baseline", "ab_policy_baseline"),
        ("calibrated", "ab_policy_calibrated"),
    ]
    t0 = time.perf_counter()
    with _k.McpNeutralizer():
        for task in tasks:
            tax = _classify_task(task["id"])
            for arm, agent in order:
                print(f"RUN {task['id']} arm={arm} tax={tax} ...", flush=True)
                row = _k.run_one(
                    arm=arm,
                    agent=agent,
                    task=task,
                    model=args.model,
                    effort=args.effort,
                    log_dir=log_dir,
                    require_mcp=True,
                    timeout_s=args.timeout_s,
                )
                row["taxonomy"] = tax
                row["compliance"] = _compliance(row, tax)
                runs.append(row)
                print(
                    json.dumps(
                        {
                            "event": "result",
                            "task": row["task_id"],
                            "arm": row["arm"],
                            "file_rec": (row.get("gold") or {}).get("file_rec"),
                            "symbol_rec": (row.get("gold") or {}).get("symbol_rec"),
                            "scubiee": (row.get("tools") or {}).get("scubiee_count"),
                            "native": (row.get("tools") or {}).get("native_count"),
                            "over_use": row["compliance"]["over_use"],
                            "under_use": row["compliance"]["under_use"],
                            "tokens": row.get("out_tokens_est"),
                            "exit": row.get("exit_code"),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )

    # Scoreboard
    def agg(arm: str) -> dict[str, Any]:
        subset = [r for r in runs if r.get("arm") == arm]
        if not subset:
            return {"arm": arm, "n": 0}

        def mean(xs: list[float | None]) -> float | None:
            ys = [x for x in xs if x is not None]
            return round(sum(ys) / len(ys), 3) if ys else None

        return {
            "arm": arm,
            "n": len(subset),
            "mean_file_rec": mean([(r.get("gold") or {}).get("file_rec") for r in subset]),
            "mean_symbol_rec": mean([(r.get("gold") or {}).get("symbol_rec") for r in subset]),
            "mean_tokens": mean([r.get("out_tokens_est") for r in subset]),
            "mean_scubiee": mean([(r.get("tools") or {}).get("scubiee_count") for r in subset]),
            "mean_native": mean([(r.get("tools") or {}).get("native_count") for r in subset]),
            "over_use_rate": round(
                sum(1 for r in subset if (r.get("compliance") or {}).get("over_use")) / len(subset),
                3,
            ),
            "under_use_rate": round(
                sum(1 for r in subset if (r.get("compliance") or {}).get("under_use")) / len(subset),
                3,
            ),
        }

    board = {"baseline": agg("baseline"), "calibrated": agg("calibrated")}
    needle_rows = [r for r in runs if r.get("taxonomy") == "literal_needle"]
    soft_rows = [r for r in runs if r.get("taxonomy") in {"soft_understand", "exact_edit"}]
    over_cal = (
        round(
            sum(
                1
                for r in needle_rows
                if r.get("arm") == "calibrated" and (r.get("compliance") or {}).get("over_use")
            )
            / max(1, sum(1 for r in needle_rows if r.get("arm") == "calibrated")),
            3,
        )
        if needle_rows
        else None
    )
    under_cal = (
        round(
            sum(
                1
                for r in soft_rows
                if r.get("arm") == "calibrated" and (r.get("compliance") or {}).get("under_use")
            )
            / max(1, sum(1 for r in soft_rows if r.get("arm") == "calibrated")),
            3,
        )
        if soft_rows
        else None
    )

    findings = [
        f"Live arms both have Scubiee; policy text differs (baseline mandatory ladder vs calibrated Prefer/Forbid).",
        f"Scoreboard baseline file_rec={board['baseline'].get('mean_file_rec')} "
        f"calibrated={board['calibrated'].get('mean_file_rec')}.",
        f"Needle over_use calibrated={over_cal}; soft/exact under_use calibrated={under_cal}.",
        f"mean scubiee_calls baseline={board['baseline'].get('mean_scubiee')} "
        f"calibrated={board['calibrated'].get('mean_scubiee')}.",
    ]

    report = {
        "protocol": protocol,
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "scoreboard": board,
        "over_use_rate_calibrated_needles": over_cal,
        "under_use_rate_calibrated_soft": under_cal,
        "findings_draft": findings,
        "runs": runs,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    md = [
        "# Locate calibration — Phase C live (Kiro policy A/B)",
        "",
        f"**Run:** `{run_id}` · **Tasks:** {len(tasks)} · **Elapsed:** {report['elapsed_s']}s",
        "**Both arms have Scubiee** — only Prefer/Forbid instruction text differs.",
        "",
        "## Scoreboard",
        "",
        "| Arm | n | file_rec | sym_rec | tokens | scubiee | native | over_use | under_use |",
        "|-----|--:|---------:|--------:|-------:|--------:|-------:|---------:|----------:|",
    ]
    for name in ("baseline", "calibrated"):
        s = board[name]
        md.append(
            f"| `{name}` | {s.get('n')} | {s.get('mean_file_rec')} | {s.get('mean_symbol_rec')} | "
            f"{s.get('mean_tokens')} | {s.get('mean_scubiee')} | {s.get('mean_native')} | "
            f"{s.get('over_use_rate')} | {s.get('under_use_rate')} |"
        )
    md += [
        "",
        f"**Needle over_use (calibrated):** {over_cal}",
        f"**Soft/exact under_use (calibrated):** {under_cal}",
        "",
        "## Findings",
        "",
    ]
    for f in findings:
        md.append(f"- {f}")
    md += [
        "",
        f"Logs: `out/kiro_phase_c_live/{run_id}/`",
        f"Raw: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
        "",
    ]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"ok": True, "scoreboard": board, "findings": findings}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

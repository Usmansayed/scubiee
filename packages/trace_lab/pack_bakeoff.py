"""Bakeoff: guide vs guide+collect vs pack_context (few-call full context)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pipeline.context_trace import (
    _CACHE,
    run_collect_hot,
    run_map_context,
    run_pack_context,
)


def _chars(obj: Any) -> int:
    return len(json.dumps(obj, separators=(",", ":"), default=str))


def _tok(chars: int) -> int:
    return max(1, chars // 4)


AUTH_GOLD = {
    "fixtures/trace-lab/app/middleware/auth.py::authenticate",
    "fixtures/trace-lab/app/middleware/auth.py::extract_bearer",
    "fixtures/trace-lab/app/services/jwt_service.py::JwtService.verify",
    "fixtures/trace-lab/app/utils/token.py::decode",
    "fixtures/trace-lab/app/repositories/user_repo.py::UserRepository.resolve",
}

CASES: list[dict[str, Any]] = [
    {
        "id": "auth",
        "query": (
            "Login fails invalid token — authenticate extract_bearer JwtService.verify "
            "decode UserRepository.resolve connect User.lookup credential path"
        ),
        "seed_file": "fixtures/trace-lab/app/middleware/auth.py",
        "seed_symbol": "authenticate",
        "gold": AUTH_GOLD,
    },
    {
        "id": "connect",
        "query": (
            "scubiee connect writes Cursor mcp.json autoApprove permissions.json "
            "mcpAllowlist via install_tool write_project_tool_surface "
            "apply_permissions_to_repo_tool_surface write_project_gate_rules AGENTS.md"
        ),
        "seed_file": "packages/pipeline/__main__.py",
        "seed_symbol": "cmd_connect",
        "gold": {
            "packages/pipeline/__main__.py::cmd_connect",
            "packages/pipeline/rules_installer.py::install_tools",
            "packages/pipeline/rules_installer.py::install_tool",
            "packages/pipeline/rules_installer.py::write_project_tool_surface",
            "packages/pipeline/rules_installer.py::write_project_gate_rules",
        },
        "useful_substr": (
            "rules_installer",
            "mcp_permissions",
            "__main__",
            "tool_registry",
            "connect_state",
        ),
    },
]


def _arm_a(root: Path, case: dict[str, Any], k: int) -> dict[str, Any]:
    t0 = time.perf_counter()
    out = run_map_context(
        root,
        case["query"],
        seed_file=case["seed_file"],
        seed_symbol=case.get("seed_symbol", ""),
        k=k,
    )
    ms = (time.perf_counter() - t0) * 1000
    cards = out.get("heatmap") or []
    # Simulate native Reads of every card span (~40 chars/line)
    read_chars = 0
    for c in cards:
        lines = max(1, int(c.get("end_line") or 0) - int(c.get("start_line") or 0) + 1)
        read_chars += lines * 40
    tool_chars = _chars({k: v for k, v in out.items() if k != "_persist"})
    return {
        "arm": "A_guide_plus_simulated_reads",
        "tool_calls": 1 + len(cards),
        "map_calls": 1,
        "read_calls_sim": len(cards),
        "response_chars": tool_chars,
        "read_chars_sim": read_chars,
        "total_chars": tool_chars + read_chars,
        "total_tok_est": _tok(tool_chars + read_chars),
        "cards": len(cards),
        "ms": round(ms, 1),
        "ids": [c.get("id") for c in cards],
        "graphify": out.get("graphify"),
    }


def _arm_b(root: Path, case: dict[str, Any], k: int, budget: int) -> dict[str, Any]:
    t0 = time.perf_counter()
    mapped = run_map_context(
        root,
        case["query"],
        seed_file=case["seed_file"],
        seed_symbol=case.get("seed_symbol", ""),
        k=k,
    )
    cards = list(mapped.get("heatmap") or [])
    collected = run_collect_hot(root, cards, threshold=0.65, max_chars=budget)
    ms = (time.perf_counter() - t0) * 1000
    payload = {
        "map": {k: v for k, v in mapped.items() if k != "_persist"},
        "collect": collected,
    }
    ch = _chars(payload)
    return {
        "arm": "B_guide_plus_collect",
        "tool_calls": 2,
        "map_calls": 1,
        "collect_calls": 1,
        "response_chars": ch,
        "total_chars": ch,
        "total_tok_est": _tok(ch),
        "cards": len(cards),
        "packed": collected.get("count") or 0,
        "pack_chars": collected.get("chars") or 0,
        "ms": round(ms, 1),
        "ids": [c.get("id") for c in cards],
        "packed_ids": [b.get("id") for b in (collected.get("bodies") or [])],
        "graphify": mapped.get("graphify"),
    }


def _arm_c(root: Path, case: dict[str, Any], k: int, budget: int) -> dict[str, Any]:
    t0 = time.perf_counter()
    out = run_pack_context(
        root,
        case["query"],
        seed_file=case["seed_file"],
        seed_symbol=case.get("seed_symbol", ""),
        k=k,
        hot_threshold=0.65,
        budget_chars=budget,
        drop_noise=True,
    )
    ms = (time.perf_counter() - t0) * 1000
    payload = {k: v for k, v in out.items() if k != "_persist"}
    ch = _chars(payload)
    return {
        "arm": "C_pack_context",
        "tool_calls": 1,
        "map_calls": 0,
        "pack_calls": 1,
        "response_chars": ch,
        "total_chars": ch,
        "total_tok_est": _tok(ch),
        "cards": out.get("count") or 0,
        "packed": out.get("packed") or 0,
        "pack_chars": out.get("chars") or 0,
        "ms": round(ms, 1),
        "ids": [c.get("id") for c in (out.get("heatmap") or [])],
        "packed_ids": [b.get("id") for b in (out.get("pack") or [])],
        "graphify": out.get("graphify"),
        "noise_dropped": True,
    }


def _score(arm: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    gold: set[str] = set(case.get("gold") or [])
    ids = set(arm.get("packed_ids") or arm.get("ids") or [])
    hit = ids & gold if gold else set()
    useful_sub = case.get("useful_substr")
    useful = 0
    total = len(arm.get("ids") or []) or 1
    if useful_sub:
        for i in arm.get("ids") or []:
            if any(s in (i or "") for s in useful_sub):
                useful += 1
    return {
        "gold_hit": len(hit),
        "gold_n": len(gold),
        "gold_rec": round(len(hit) / len(gold), 3) if gold else None,
        "useful_frac": round(useful / total, 3) if useful_sub else None,
    }


def run_bakeoff(
    root: Path,
    *,
    k: int = 12,
    budget_chars: int = 12_000,
) -> dict[str, Any]:
    _CACHE.clear()
    rows: list[dict[str, Any]] = []
    for case in CASES:
        for runner in (_arm_a, _arm_b, _arm_c):
            if runner is _arm_a:
                arm = runner(root, case, k)
            else:
                arm = runner(root, case, k, budget_chars)
            arm["case"] = case["id"]
            arm["score"] = _score(arm, case)
            rows.append(arm)
    return {
        "ok": True,
        "root": str(root),
        "k": k,
        "budget_chars": budget_chars,
        "rows": rows,
    }


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--k", type=int, default=12)
    p.add_argument("--budget", type=int, default=12_000)
    p.add_argument(
        "--out",
        type=Path,
        default=Path("docs/superpowers/plans/pack-bakeoff-results.json"),
    )
    args = p.parse_args()
    report = run_bakeoff(args.root.resolve(), k=args.k, budget_chars=args.budget)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(args.out), "n": len(report["rows"])}, indent=2))
    for row in report["rows"]:
        s = row["score"]
        print(
            f"{row['case']:8} {row['arm']:28} calls={row['tool_calls']:2} "
            f"tok~{row['total_tok_est']:5} packed={row.get('packed', '-')} "
            f"gold_rec={s.get('gold_rec')} useful={s.get('useful_frac')}"
        )


if __name__ == "__main__":
    main()

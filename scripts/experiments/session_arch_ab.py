"""Session traversal architecture A/B.

Default arms for hard eval:
  D_rerank_fullfile | D_rerank_spans | SeedSpan | GraphHop | Planner

Planner: import-follow + ident BM25/grep + graph (no LSP).
Classic D_rerank baselines included for quality vs token comparison.

Usage:
  .\\.venv\\Scripts\\python.exe -u scripts\\experiments\\session_arch_ab.py --mission brutal_v1
  .\\.venv\\Scripts\\python.exe -u scripts\\experiments\\session_arch_ab.py --ladder
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))
sys.path.insert(0, str(ROOT / "scripts" / "experiments"))

from pipeline.engine import load_engine  # noqa: E402

from session_arch.core import pack_session  # noqa: E402
from session_arch.d_rerank_arms import run_d_rerank_fullfile, run_d_rerank_spans  # noqa: E402
from session_arch.graph_hop import run_graph_hop  # noqa: E402
from session_arch.mission import DIFFICULTY_LADDER, MISSIONS  # noqa: E402
from session_arch.outline_hop import run_outline_hop  # noqa: E402
from session_arch.planner import run_planner  # noqa: E402
from session_arch.seed_span import run_seed_span  # noqa: E402

REPO_DEFAULT = ROOT / "testdata" / "frontend-mcp"
OUT_DIR = ROOT / "out" / "experiments"

DEFAULT_ARMS = [
    "D_rerank_fullfile",
    "D_rerank_spans",
    "SeedSpan",
    "GraphHop",
    "Planner",
]

ARMS: dict[str, Callable[..., Any]] = {
    "D_rerank_fullfile": run_d_rerank_fullfile,
    "D_rerank_spans": run_d_rerank_spans,
    "SeedSpan": run_seed_span,
    "GraphHop": run_graph_hop,
    "Planner": run_planner,
    "OutlineHop": run_outline_hop,
}


def _maybe_register_lsp() -> None:
    try:
        from session_arch.lsp_hop import run_lsp_hop  # noqa: WPS433

        ARMS["LspHop"] = run_lsp_hop
    except Exception:  # noqa: BLE001
        pass


_maybe_register_lsp()


def _efficiency(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Token efficiency vs classic D fullfile + quality-adjusted cost."""
    by = {r["arm"]: r for r in results}
    base = by.get("D_rerank_fullfile")
    base_tok = int(base["tokens_total"]) if base else None
    rows = []
    for r in results:
        passed = int(r["rubric_pass_turns"])
        total = max(int(r["rubric_total_turns"]), 1)
        tok = int(r["tokens_total"])
        rows.append(
            {
                "arm": r["arm"],
                "rubric_rate": r["rubric_rate"],
                "tokens_total": tok,
                "tokens_per_pass": round(tok / max(passed, 1), 1),
                "tokens_per_turn": round(tok / total, 1),
                "savings_vs_D_fullfile": (
                    None
                    if base_tok is None
                    else round(1.0 - (tok / max(base_tok, 1)), 4)
                ),
                "ops": r.get("ops"),
            }
        )
    # Best: high rubric, then low tokens
    best = sorted(
        results,
        key=lambda r: (-float(r["rubric_rate"]), int(r["tokens_total"])),
    )[0]
    return {"baseline": "D_rerank_fullfile", "rows": rows, "quality_token_winner": best["arm"]}


def _pick_winner(results: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(
        results,
        key=lambda r: (-float(r["rubric_rate"]), int(r["tokens_total"])),
    )
    win = ranked[0]
    return {
        "arm": win["arm"],
        "rubric_rate": win["rubric_rate"],
        "tokens_total": win["tokens_total"],
        "memory_hit_rate": win["memory_hit_rate"],
        "memory_no_cold_rate": win.get("memory_no_cold_rate"),
        "ranking": [
            {
                "arm": r["arm"],
                "rubric_rate": r["rubric_rate"],
                "rubric_pass_turns": r["rubric_pass_turns"],
                "rubric_total_turns": r["rubric_total_turns"],
                "tokens_total": r["tokens_total"],
                "ops": r.get("ops"),
            }
            for r in ranked
        ],
    }


def _arms_separated(results: list[dict[str, Any]]) -> bool:
    rates = {round(float(r["rubric_rate"]), 4) for r in results}
    return len(rates) > 1


def _hop_beats_seed(results: list[dict[str, Any]]) -> bool:
    by = {r["arm"]: float(r["rubric_rate"]) for r in results}
    seed = by.get("SeedSpan")
    if seed is None:
        return _arms_separated(results)
    return any(
        by.get(a, -1.0) > seed
        for a in ("GraphHop", "Planner", "OutlineHop", "LspHop")
        if a in by
    )


def _failing_turns(results: list[dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in results:
        fails = [
            t["turn"]
            for t in r.get("turns") or []
            if t.get("turn") and not str(t["turn"]).startswith("_") and not t.get("ok")
        ]
        out[r["arm"]] = fails
    return out


def run_mission(
    engine: Any,
    mission: dict[str, Any],
    *,
    arms: list[str],
    top_k: int | None,
    max_chars: int,
) -> dict[str, Any]:
    k = int(top_k if top_k is not None else mission.get("default_top_k") or 8)
    hop_keep = 6 if k <= 4 else 4
    results: list[dict[str, Any]] = []
    print(f"\n######## mission={mission.get('id')} top_k={k} ########")
    print(mission.get("title") or "")
    for name in arms:
        fn = ARMS[name]
        print(f"\n=== {name} ===")
        kwargs: dict[str, Any] = {"top_k": k, "max_chars_span": max_chars}
        if name == "GraphHop":
            kwargs["hop_keep"] = hop_keep
            kwargs["expand_cap"] = 16
        if name == "Planner":
            kwargs["hop_keep"] = hop_keep
            kwargs["expand_cap"] = 16
            kwargs["max_rounds"] = 2
        if name == "D_rerank_fullfile":
            kwargs["max_chars_file"] = 12000
        st = fn(engine, mission, **kwargs)
        packed = pack_session(st)
        results.append(packed)
        print(
            f"  rubric {packed['rubric_pass_turns']}/{packed['rubric_total_turns']} "
            f"({packed['rubric_rate']:.0%})  tokens={packed['tokens_total']}  "
            f"ms={packed['retrieve_ms']:.0f}  ops={packed['ops']}"
        )
        for t in packed["turns"]:
            mark = "PASS" if t.get("ok") else "FAIL"
            print(
                f"    {t['turn']}: {mark} open={t.get('open_ok')} "
                f"tok+={t.get('tokens_delta')} search={t.get('used_full_search')}"
            )
            if not t.get("ok"):
                print(
                    f"      opened={[Path(x).name for x in (t.get('opened') or [])]}"
                )

    winner = _pick_winner(results)
    eff = _efficiency(results)
    print("\n--- efficiency vs D_rerank_fullfile ---")
    for row in eff["rows"]:
        sav = row["savings_vs_D_fullfile"]
        sav_s = f"{sav:.0%}" if sav is not None else "n/a"
        print(
            f"  {row['arm']}: rubric={row['rubric_rate']:.0%} "
            f"tok={row['tokens_total']} tok/pass={row['tokens_per_pass']} "
            f"save={sav_s}"
        )

    return {
        "mission_id": mission.get("id"),
        "mission": mission.get("title"),
        "top_k": k,
        "max_chars_span": max_chars,
        "separated": _arms_separated(results),
        "hop_beats_seed": _hop_beats_seed(results),
        "failing_turns": _failing_turns(results),
        "efficiency": eff,
        "winner": winner,
        "arms": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Session arch A/B incl. classic D_rerank baselines"
    )
    ap.add_argument("--repo", type=Path, default=REPO_DEFAULT)
    ap.add_argument("--top-k", type=int, default=None)
    ap.add_argument("--max-chars", type=int, default=700)
    ap.add_argument(
        "--arms",
        nargs="+",
        default=DEFAULT_ARMS,
        choices=list(ARMS.keys()),
    )
    ap.add_argument("--mission", default=None, choices=list(MISSIONS.keys()))
    ap.add_argument("--ladder", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    os.environ.pop("CTX_HOME", None)

    repo = args.repo.resolve()
    if not repo.is_dir():
        print(f"repo missing: {repo}", file=sys.stderr)
        return 2

    print(f"loading engine: {repo}")
    t0 = time.perf_counter()
    engine = load_engine(repo)
    print(
        f"loaded chunks={len(engine.chunks)} in {(time.perf_counter() - t0) * 1000:.0f}ms"
    )

    if args.ladder:
        mission_ids = list(DIFFICULTY_LADDER)
    elif args.mission:
        mission_ids = [args.mission]
    else:
        mission_ids = ["brutal_v1"]

    ladder_reports: list[dict[str, Any]] = []
    for mid in mission_ids:
        mission = MISSIONS[mid]
        report = run_mission(
            engine,
            mission,
            arms=list(args.arms),
            top_k=args.top_k,
            max_chars=args.max_chars,
        )
        ladder_reports.append(report)
        print(
            f"\n>>> {mid}: winner={report['winner']['arm']} "
            f"rates={[(r['arm'], r['rubric_rate']) for r in report['winner']['ranking']]}"
        )
        print(f"    failing={report['failing_turns']}")
        if not args.ladder:
            break
        # On ladder: stop after brutal if Planner clearly wins quality
        if mid == "brutal_v1" and report["winner"]["arm"] == "Planner":
            print("\n*** brutal done — continuing ladder for more signal ***")

    focus = ladder_reports[0]
    # Prefer mission where Planner has best relative quality if multi
    for rep in ladder_reports:
        if rep["winner"]["arm"] == "Planner":
            focus = rep
            break

    payload = {
        "repo": str(repo),
        "mode": "ladder" if args.ladder else "single",
        "arms": list(args.arms),
        "planner_tools": "import_follow + ident_bm25_grep + graph (no LSP)",
        "verdict": {
            "mission_id": focus.get("mission_id"),
            "winner": focus["winner"],
            "failing_turns": focus["failing_turns"],
            "efficiency": focus.get("efficiency"),
            "note": (
                "Winner by rubric then tokens; efficiency vs D_rerank_fullfile included."
            ),
        },
        "missions": ladder_reports,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = args.out or (OUT_DIR / f"session_arch_{int(time.time())}.json")
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    latest = OUT_DIR / "session_arch_latest.json"
    latest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")
    print(f"wrote {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

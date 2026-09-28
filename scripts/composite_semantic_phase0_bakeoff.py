"""Focused Phase 0 bakeoff: composite_v1 vs semantic add/gate only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trace_lab.cases import default_fixture_root
from trace_lab.metrics import evaluate
from trace_lab.prod_eval import _case_with_query_seed, _correct, _merge_heatmaps
from trace_lab.sim import HOT_THRESHOLD
from trace_lab.strategies import compile_bundle
from trace_lab.types import GoldRef
from trace_lab.vague_eval import hot_set, prompt_to_case
from trace_lab.verify_board import _must_at_k


def run_focused(hot_threshold: float = HOT_THRESHOLD) -> dict[str, Any]:
    root = default_fixture_root().resolve()
    board_name = "verify_prod.json"
    board = json.loads((root / board_name).read_text(encoding="utf-8"))
    cases = board["cases"]

    nodes, graph, lex, tracers = compile_bundle(
        root,
        with_graphify=True,
        with_embed_power=True,
        require_real_embeds=False,
    )
    arm_names = [
        "composite_v1",
        "composite_semantic_add",
        "composite_semantic_gate",
    ]
    for name in arm_names:
        if name not in tracers:
            raise SystemExit(f"missing arm {name}")

    rows: list[dict[str, Any]] = []
    for raw in cases:
        gold = prompt_to_case(raw)
        chunks = list(raw.get("seed_chunks") or [])
        if not chunks:
            chunks = [
                {
                    "file": gold.seed.file,
                    "symbol": gold.seed.symbol,
                    "text": nodes[gold.seed.id].text if gold.seed.id in nodes else "",
                }
            ]
        seeds = [GoldRef(file=ch["file"], symbol=ch["symbol"]) for ch in chunks]
        seen: set[str] = set()
        uniq: list[GoldRef] = []
        for s in seeds:
            if s.id in seen or s.id not in nodes:
                continue
            seen.add(s.id)
            uniq.append(s)
        if not uniq:
            uniq = [gold.seed]
        user_prompt = str(raw.get("prompt") or gold.query)
        arm_out: dict[str, Any] = {}
        for name in arm_names:
            maps = []
            for s in uniq:
                sub = _case_with_query_seed(gold, user_prompt, s)
                maps.append(tracers[name](sub, nodes, graph, lex))
            hm = _merge_heatmaps(maps, strategy=f"{name}+prod")
            met = evaluate(hm, gold, nodes, hot_threshold=hot_threshold)
            hot = hot_set(hm, hot_threshold)
            ver = _correct(hot, gold)
            ranked = hm.ranked_ids()
            arm_out[name] = {
                **ver,
                "f1": met.f1,
                "recall_must": met.recall_must,
                "precision_hot": met.precision_hot,
                "must_at_5": round(_must_at_k(ranked, gold.must_ids, 5), 4),
                "must_at_10": round(_must_at_k(ranked, gold.must_ids, 10), 4),
                "backend": (hm.extra or {}).get("embed_backend"),
            }
        rows.append({"id": gold.id, "arms": arm_out})

    summary: dict[str, Any] = {}
    soft_keys = ("f1", "recall_must", "precision_hot", "must_at_5", "must_at_10")
    for name in arm_names:
        n_ok = sum(1 for r in rows if r["arms"][name]["correct"])
        soft = {
            k: round(sum(r["arms"][name].get(k, 0) for r in rows) / max(len(rows), 1), 4)
            for k in soft_keys
        }
        summary[name] = {
            "correct": n_ok,
            "n": len(rows),
            "accuracy": round(n_ok / max(len(rows), 1), 4),
            "mean_f1": soft["f1"],
            "mean_recall_must": soft["recall_must"],
            "mean_precision_hot": soft["precision_hot"],
            "mean_must_at_5": soft["must_at_5"],
            "mean_must_at_10": soft["must_at_10"],
            "failed_ids": [r["id"] for r in rows if not r["arms"][name]["correct"]],
        }
    return {"board": board_name, "n_cases": len(rows), "summary": summary, "cases": rows}


def main() -> None:
    report = run_focused()
    summary = report["summary"]
    base = summary["composite_v1"]
    rec: dict = {}
    for a in ("composite_semantic_add", "composite_semantic_gate"):
        s = summary[a]
        hard_up = s["accuracy"] > base["accuracy"]
        must_up = s["mean_recall_must"] > base["mean_recall_must"]
        f1_drop = base["mean_f1"] - s["mean_f1"]
        prec_drop = base["mean_precision_hot"] - s["mean_precision_hot"]
        keep = (hard_up or must_up) and f1_drop <= 0.02 and prec_drop <= 0.03
        rec[a] = {
            "keep": keep,
            "hard_up": hard_up,
            "must_up": must_up,
            "f1_drop": round(f1_drop, 4),
            "prec_drop": round(prec_drop, 4),
        }
    keeps = [a for a, v in rec.items() if v.get("keep")]
    if keeps:
        recommendation = (
            "Keep as opt-in bakeoff arms: "
            + ", ".join(keeps)
            + ". Do not flip MCP default."
        )
    else:
        recommendation = (
            "Kill Phase 0 sensor for default use; neither add nor gate met "
            "keep/kill gate vs composite_v1. Keep code as experimental opt-in "
            "scaffolding for Phase 1."
        )
    out = {
        "board": report["board"],
        "n_cases": report["n_cases"],
        "base": {
            "accuracy": base["accuracy"],
            "mean_f1": base["mean_f1"],
            "mean_recall_must": base["mean_recall_must"],
            "mean_precision_hot": base["mean_precision_hot"],
        },
        "summary": summary,
        "keep_kill": rec,
        "recommendation": recommendation,
    }
    path = Path("docs/superpowers/plans/2026-09-06-composite-semantic-phase0-bakeoff.json")
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    md = Path("docs/superpowers/plans/2026-09-06-composite-semantic-phase0-bakeoff.md")
    lines = [
        "# Composite semantic Phase 0 bakeoff",
        "",
        f"Board: `{out['board']}` ({out['n_cases']} cases)",
        "",
        "## Summary",
        "",
        "| Arm | Acc | F1 | Must-rec | Prec |",
        "|-----|-----|----|----------|------|",
    ]
    for name, s in summary.items():
        lines.append(
            f"| `{name}` | {s.get('accuracy')} | {s.get('mean_f1')} | "
            f"{s.get('mean_recall_must')} | {s.get('mean_precision_hot')} |"
        )
    lines.extend(
        [
            "",
            "## Keep / kill",
            "",
            "```json",
            json.dumps(rec, indent=2),
            "```",
            "",
            "## Recommendation",
            "",
            recommendation,
            "",
        ]
    )
    md.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(out, indent=2))
    print("wrote", path)
    print("wrote", md)


if __name__ == "__main__":
    main()

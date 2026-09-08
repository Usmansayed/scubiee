"""Seeded head-to-head: PolyTrace (no embed) vs EmbedPower (CodeRank).

Both arms receive the same gold seed + prompt. Gold context is loaded from
fixtures/trace-lab/seeded_prompts.json (collected from the fixture, not from
tracer output).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trace_lab.cases import default_fixture_root
from trace_lab.metrics import evaluate
from trace_lab.sim import HOT_THRESHOLD
from trace_lab.strategies import compile_bundle
from trace_lab.types import GoldCase, GoldRef, Heatmap
from trace_lab.vague_eval import hot_set, jaccard, prompt_to_case


def load_seeded_prompts(path: Path | None = None) -> dict[str, Any]:
    root = default_fixture_root()
    path = path or (root / "seeded_prompts.json")
    return json.loads(path.read_text(encoding="utf-8"))


def run_seeded_compare(
    fixture: Path | None = None,
    *,
    hot_threshold: float = HOT_THRESHOLD,
    require_real_embeds: bool = False,
) -> dict[str, Any]:
    root = (fixture or default_fixture_root()).resolve()
    data = load_seeded_prompts(root / "seeded_prompts.json")
    prompts = data["prompts"]
    nodes, graph, lex, tracers = compile_bundle(
        root,
        with_graphify=False,
        with_embed_power=True,
        require_real_embeds=require_real_embeds,
    )
    poly = tracers["polytrace"]
    embed = tracers["embed_power_oracle"]  # gold seed + embed gates

    rows: list[dict[str, Any]] = []
    for raw in prompts:
        gold = prompt_to_case(raw)
        # prompt_to_case expects "prompt" key — seeded file uses "prompt"
        if not hasattr(gold, "query") or not gold.query:
            gold.query = str(raw["prompt"])

        arms: dict[str, Any] = {}
        hots: dict[str, set[str]] = {}
        for name, fn in (("polytrace", poly), ("embed_power", embed)):
            hm: Heatmap = fn(gold, nodes, graph, lex)
            met = evaluate(hm, gold, nodes, hot_threshold=hot_threshold)
            hot = hot_set(hm, hot_threshold)
            hots[name] = hot
            arms[name] = {
                "f1": met.f1,
                "recall_must": met.recall_must,
                "precision_hot": met.precision_hot,
                "false_negatives": met.false_negatives,
                "false_positives_forbidden": met.false_positives_forbidden,
                "extra_hot": met.extra_hot,
                "hot": sorted(hot),
                "heatmap": [
                    {
                        "id": c.node_id,
                        "score": c.score,
                        "why": c.why,
                    }
                    for c in hm.cells
                    if c.score >= hot_threshold
                ],
            }

        rows.append(
            {
                "id": gold.id,
                "title": str(raw.get("title") or gold.id),
                "prompt": gold.query,
                "seed": gold.seed.id,
                "context_notes": str(raw.get("context_notes") or ""),
                "gold_must": sorted(gold.must_ids),
                "gold_should": sorted(gold.should_ids),
                "gold_must_not": sorted(gold.must_not_ids),
                "arms": arms,
                "heatmap_jaccard": round(jaccard(hots["polytrace"], hots["embed_power"]), 4),
                "winner": _winner(arms),
            }
        )

    summary = _summarize(rows)
    return {
        "fixture": str(root),
        "n_prompts": len(rows),
        "hot_threshold": hot_threshold,
        "note": "Both arms receive the same gold seed + prompt.",
        "summary": summary,
        "prompts": rows,
    }


def _winner(arms: dict[str, Any]) -> str:
    p, e = arms["polytrace"], arms["embed_power"]
    if abs(p["f1"] - e["f1"]) < 1e-6:
        if len(p["false_positives_forbidden"]) != len(e["false_positives_forbidden"]):
            return (
                "polytrace"
                if len(p["false_positives_forbidden"]) < len(e["false_positives_forbidden"])
                else "embed_power"
            )
        return "tie"
    return "polytrace" if p["f1"] > e["f1"] else "embed_power"


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in ("polytrace", "embed_power"):
        f1s = [r["arms"][name]["f1"] for r in rows]
        recs = [r["arms"][name]["recall_must"] for r in rows]
        out[name] = {
            "mean_f1": round(sum(f1s) / max(len(f1s), 1), 4),
            "mean_recall_must": round(sum(recs) / max(len(recs), 1), 4),
            "sum_fn": sum(len(r["arms"][name]["false_negatives"]) for r in rows),
            "sum_forbidden_fp": sum(
                len(r["arms"][name]["false_positives_forbidden"]) for r in rows
            ),
            "wins": sum(1 for r in rows if r["winner"] == name),
        }
    out["ties"] = sum(1 for r in rows if r["winner"] == "tie")
    out["mean_heatmap_jaccard"] = round(
        sum(r["heatmap_jaccard"] for r in rows) / max(len(rows), 1), 4
    )
    return out


def format_seeded_table(report: dict[str, Any]) -> str:
    lines = [
        f"seeded-compare  prompts={report['n_prompts']}  (same seed+prompt both arms)",
        f"{'arm':14} {'F1':>7} {'recall':>7} {'FN':>4} {'FP!':>4} {'wins':>5}",
        "-" * 48,
    ]
    for name in ("polytrace", "embed_power"):
        row = report["summary"][name]
        lines.append(
            f"{name:14} {row['mean_f1']:7.3f} {row['mean_recall_must']:7.3f} "
            f"{row['sum_fn']:4d} {row['sum_forbidden_fp']:4d} {row['wins']:5d}"
        )
    lines.append(
        f"ties={report['summary']['ties']}  "
        f"mean heatmap Jaccard(poly vs embed)={report['summary']['mean_heatmap_jaccard']:.3f}"
    )
    lines.append("")
    lines.append(f"{'id':4} {'win':12} {'polyF1':>7} {'embF1':>7} {'jacc':>6}  prompt")
    lines.append("-" * 72)
    for r in report["prompts"]:
        lines.append(
            f"{r['id']:4} {r['winner']:12} {r['arms']['polytrace']['f1']:7.3f} "
            f"{r['arms']['embed_power']['f1']:7.3f} {r['heatmap_jaccard']:6.3f}  "
            f"{r['prompt'][:42]}"
        )
    return "\n".join(lines)


def dump_seeded_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")

"""Bakeoff novel semantic strategies on NEW OOD board only (verify_ood_v2)."""

from __future__ import annotations

import json
import time
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


def run_ood(*, hot: float = HOT_THRESHOLD) -> dict[str, Any]:
    root = default_fixture_root().resolve()
    board_name = "verify_ood_v2.json"
    board = json.loads((root / board_name).read_text(encoding="utf-8"))
    cases = board["cases"]
    t0 = time.time()
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=True, with_embed_power=True, require_real_embeds=False
    )
    arm_names = [
        "composite_v1",
        "semantic_tracer_v1",
        "semantic_tracer_fuse",
        "semantic_waypoint",
        "semantic_meet",
        "semantic_dual",
        "semantic_ensemble",
        "poly_embed",
        "hybrid_teleport",
    ]
    arm_names = [a for a in arm_names if a in tracers]
    rows: list[dict[str, Any]] = []

    for raw in cases:
        gold = prompt_to_case(raw)
        uniq = [gold.seed] if gold.seed.id in nodes else []
        if not uniq:
            # try resolve
            continue
        user_prompt = str(raw.get("prompt") or gold.query)
        arm_out: dict[str, Any] = {}
        for name in arm_names:
            maps = []
            for s in uniq:
                sub = _case_with_query_seed(gold, user_prompt, s)
                try:
                    maps.append(tracers[name](sub, nodes, graph, lex))
                except Exception as exc:  # noqa: BLE001
                    arm_out[name] = {
                        "correct": False,
                        "f1": 0.0,
                        "recall_must": 0.0,
                        "precision_hot": 0.0,
                        "must_at_10": 0.0,
                        "error": str(exc)[:120],
                    }
                    maps = []
                    break
            if name in arm_out:
                continue
            hm = _merge_heatmaps(maps, strategy=f"{name}+ood")
            met = evaluate(hm, gold, nodes, hot_threshold=hot)
            hot_ids = hot_set(hm, hot)
            ver = _correct(hot_ids, gold)
            arm_out[name] = {
                **ver,
                "f1": met.f1,
                "recall_must": met.recall_must,
                "precision_hot": met.precision_hot,
                "must_at_10": round(_must_at_k(hm.ranked_ids(), gold.must_ids, 10), 4),
                "n_hot": len(hot_ids),
            }
        rows.append({"id": gold.id, "family": raw.get("family"), "arms": arm_out})

    summary: dict[str, Any] = {}
    for name in arm_names:
        present = [r for r in rows if name in r["arms"] and "error" not in r["arms"][name]]
        if not present:
            continue
        n_ok = sum(1 for r in present if r["arms"][name]["correct"])
        soft_keys = ("f1", "recall_must", "precision_hot", "must_at_10")
        soft = {
            k: round(sum(r["arms"][name][k] for r in present) / max(len(present), 1), 4)
            for k in soft_keys
        }
        summary[name] = {
            "correct": n_ok,
            "n": len(present),
            "accuracy": round(n_ok / max(len(present), 1), 4),
            "mean_f1": soft["f1"],
            "mean_recall_must": soft["recall_must"],
            "mean_precision_hot": soft["precision_hot"],
            "mean_must_at_10": soft["must_at_10"],
            "failed_ids": [r["id"] for r in present if not r["arms"][name]["correct"]],
        }

    base = summary.get("composite_v1", {})
    ranked = sorted(
        summary.keys(),
        key=lambda n: (
            summary[n]["mean_recall_must"],
            summary[n]["mean_f1"],
            summary[n]["accuracy"],
        ),
        reverse=True,
    )

    def ship(name: str) -> bool:
        if name not in summary or not base:
            return False
        st = summary[name]
        return (
            st["mean_recall_must"] > base["mean_recall_must"]
            and (base["mean_f1"] - st["mean_f1"]) <= 0.02
            and (base["mean_precision_hot"] - st["mean_precision_hot"]) <= 0.03
            and (base["accuracy"] - st["accuracy"]) <= 0.05
        )

    winners = [n for n in summary if n != "composite_v1" and ship(n)]
    best = ranked[0] if ranked else ""
    return {
        "board": board_name,
        "n_cases": len(rows),
        "elapsed_s": round(time.time() - t0, 2),
        "summary": summary,
        "ranked": ranked,
        "best": best,
        "ship_winners": winners,
        "note": "OOD board verify_ood_v2 — not verify_hard/verify_prod",
    }


def main() -> None:
    out = run_ood()
    plans = Path("docs/superpowers/plans")
    plans.mkdir(parents=True, exist_ok=True)
    stem = "2026-09-06-semantic-ood-v2-bakeoff"
    (plans / f"{stem}.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    s = out["summary"]
    lines = [
        "# Semantic novel strategies — OOD hard board v2",
        "",
        f"Board: `{out['board']}` ({out['n_cases']} NEW cases) · {out['elapsed_s']}s",
        "",
        "**Not** verify_hard / verify_prod.",
        "",
        "| Arm | Acc | F1 | Must | Prec | Must@10 |",
        "|-----|-----|----|------|------|---------|",
    ]
    for name in out["ranked"]:
        row = s[name]
        lines.append(
            f"| `{name}` | {row['accuracy']} | {row['mean_f1']} | "
            f"{row['mean_recall_must']} | {row['mean_precision_hot']} | "
            f"{row['mean_must_at_10']} |"
        )
    lines.extend(
        [
            "",
            f"**Best (must→F1→acc):** `{out['best']}`",
            f"**Ship-gate winners vs composite_v1:** {out['ship_winners'] or '(none)'}",
            "",
            "### Strategies under test",
            "",
            "- `semantic_waypoint` — ANN targets + heat shortest seed→target paths",
            "- `semantic_meet` — forward BFS ∩ backward from semantic targets",
            "- `semantic_dual` — second embed seed + merge structural expands",
            "- baselines: composite_v1, semantic_tracer_v1/fuse, poly_embed, hybrid_teleport",
            "",
        ]
    )
    (plans / f"{stem}.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("board", "n_cases", "best", "ship_winners", "ranked")}, indent=2))
    for name in out["ranked"]:
        r = s[name]
        print(name, r["accuracy"], r["mean_f1"], r["mean_recall_must"], r["mean_must_at_10"])
    print("wrote", plans / f"{stem}.md")


if __name__ == "__main__":
    main()

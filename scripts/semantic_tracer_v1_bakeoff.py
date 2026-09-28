"""Focused bakeoff: composite_v1 vs semantic_tracer_v1 (+ controls)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from trace_lab.cases import default_fixture_root
from trace_lab.metrics import evaluate
from trace_lab.prod_eval import _case_with_query_seed, _correct, _merge_heatmaps
from trace_lab.semantic_sensor import apply_vector_only, node_sem_scores
from trace_lab.semantic_index import from_embed_field
from trace_lab.sim import HOT_THRESHOLD
from trace_lab.strategies import compile_bundle
from trace_lab.types import GoldRef
from trace_lab.vague_eval import hot_set, prompt_to_case
from trace_lab.verify_board import _must_at_k


def run_board(board_name: str, *, hot: float = HOT_THRESHOLD) -> dict[str, Any]:
    root = default_fixture_root().resolve()
    board = json.loads((root / board_name).read_text(encoding="utf-8"))
    cases = board["cases"]
    t0 = time.time()
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=True, with_embed_power=True, require_real_embeds=False
    )
    from trace_lab.embed_field import EmbedField

    field = EmbedField(
        nodes,
        cache_path=root / ".embed_cache" / "coderank.jsonl",
        require_real=False,
        quiet=True,
    )
    index = from_embed_field(field)

    arm_names = [
        "composite_v1",
        "semantic_tracer_v1",
        "poly_embed",
        "hybrid_teleport",
    ]
    arm_names = [a for a in arm_names if a in tracers]
    rows: list[dict[str, Any]] = []

    for raw in cases:
        gold = prompt_to_case(raw)
        chunks = list(raw.get("seed_chunks") or [])
        if not chunks:
            chunks = [
                {
                    "file": gold.seed.file,
                    "symbol": gold.seed.symbol,
                    "text": "",
                }
            ]
        seeds = [GoldRef(file=ch["file"], symbol=ch["symbol"]) for ch in chunks]
        uniq: list[GoldRef] = []
        seen: set[str] = set()
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
            met = evaluate(hm, gold, nodes, hot_threshold=hot)
            hot_ids = hot_set(hm, hot)
            ver = _correct(hot_ids, gold)
            ranked = hm.ranked_ids()
            arm_out[name] = {
                **ver,
                "f1": met.f1,
                "recall_must": met.recall_must,
                "precision_hot": met.precision_hot,
                "must_at_10": round(_must_at_k(ranked, gold.must_ids, 10), 4),
                "n_hot": len(hot_ids),
                "n_cells": len(hm.cells),
            }
        # vector_only control
        seed_id = uniq[0].id
        q_aff = index.query_affinities(user_prompt)
        s_aff = index.seed_affinities(seed_id)
        sem = node_sem_scores(
            list(nodes.keys()), q_aff=q_aff, seed_id=seed_id, seed_aff=s_aff
        )
        vom = apply_vector_only(seed_id=seed_id, sem=sem, k=24)
        met = evaluate(vom, gold, nodes, hot_threshold=hot)
        hot_ids = hot_set(vom, hot)
        ver = _correct(hot_ids, gold)
        arm_out["vector_only"] = {
            **ver,
            "f1": met.f1,
            "recall_must": met.recall_must,
            "precision_hot": met.precision_hot,
            "must_at_10": round(_must_at_k(vom.ranked_ids(), gold.must_ids, 10), 4),
            "n_hot": len(hot_ids),
            "n_cells": len(vom.cells),
        }
        rows.append({"id": gold.id, "arms": arm_out})

    all_arms = arm_names + ["vector_only"]
    summary: dict[str, Any] = {}
    for name in all_arms:
        n_ok = sum(1 for r in rows if r["arms"][name]["correct"])
        soft_keys = ("f1", "recall_must", "precision_hot", "must_at_10", "n_hot")
        soft = {
            k: round(sum(r["arms"][name][k] for r in rows) / max(len(rows), 1), 4)
            for k in soft_keys
        }
        summary[name] = {
            "correct": n_ok,
            "n": len(rows),
            "accuracy": round(n_ok / max(len(rows), 1), 4),
            "mean_f1": soft["f1"],
            "mean_recall_must": soft["recall_must"],
            "mean_precision_hot": soft["precision_hot"],
            "mean_must_at_10": soft["must_at_10"],
            "mean_hot": soft["n_hot"],
            "failed_ids": [r["id"] for r in rows if not r["arms"][name]["correct"]],
        }

    base = summary["composite_v1"]
    st = summary["semantic_tracer_v1"]
    must_up = st["mean_recall_must"] > base["mean_recall_must"]
    f1_drop = base["mean_f1"] - st["mean_f1"]
    prec_drop = base["mean_precision_hot"] - st["mean_precision_hot"]
    acc_drop = base["accuracy"] - st["accuracy"]
    ship = (
        must_up
        and f1_drop <= 0.02
        and prec_drop <= 0.03
        and acc_drop <= 0.05
    )
    must10_up = st["mean_must_at_10"] > base["mean_must_at_10"]
    return {
        "board": board_name,
        "n_cases": len(rows),
        "elapsed_s": round(time.time() - t0, 2),
        "embed_backend": index.backend,
        "summary": summary,
        "vs_composite_v1": {
            "must_delta": round(st["mean_recall_must"] - base["mean_recall_must"], 4),
            "f1_delta": round(st["mean_f1"] - base["mean_f1"], 4),
            "prec_delta": round(st["mean_precision_hot"] - base["mean_precision_hot"], 4),
            "acc_delta": round(st["accuracy"] - base["accuracy"], 4),
            "must_at_10_delta": round(
                st["mean_must_at_10"] - base["mean_must_at_10"], 4
            ),
            "must10_up": must10_up,
            "ship_gate": ship,
        },
        "cycle2_recommendation": (
            "Cycle 1 comparator helped ranking/must@10 — proceed to Cycle 2 "
            "(trace centroid + strict teleport)."
            if (must10_up or must_up) and f1_drop <= 0.05
            else "Cycle 1 did not clearly beat composite_v1 on balanced metrics — "
            "tune edge_sem weights / beta before Cycle 2 teleport, or ablate path polish."
        ),
    }


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default="verify_hard.json")
    ap.add_argument("--stem", default="2026-09-06-semantic-tracer-v1-hard")
    args = ap.parse_args()
    out = run_board(args.board)
    plans = Path("docs/superpowers/plans")
    plans.mkdir(parents=True, exist_ok=True)
    jp = plans / f"{args.stem}.json"
    mp = plans / f"{args.stem}.md"
    jp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    s = out["summary"]
    lines = [
        f"# Semantic tracer v1 bakeoff — `{out['board']}`",
        "",
        f"Cases: {out['n_cases']} · {out['elapsed_s']}s · `{out['embed_backend']}`",
        "",
        "| Arm | Acc | F1 | Must | Prec | Must@10 |",
        "|-----|-----|----|------|------|---------|",
    ]
    for name, row in s.items():
        lines.append(
            f"| `{name}` | {row['accuracy']} | {row['mean_f1']} | "
            f"{row['mean_recall_must']} | {row['mean_precision_hot']} | "
            f"{row['mean_must_at_10']} |"
        )
    v = out["vs_composite_v1"]
    lines.extend(
        [
            "",
            "## vs composite_v1",
            "",
            f"- must Δ {v['must_delta']} · F1 Δ {v['f1_delta']} · prec Δ {v['prec_delta']} · "
            f"acc Δ {v['acc_delta']} · must@10 Δ {v['must_at_10_delta']}",
            f"- ship_gate: **{v['ship_gate']}**",
            "",
            "## Cycle 2 recommendation",
            "",
            out["cycle2_recommendation"],
            "",
        ]
    )
    mp.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: out[k] for k in (
        "board", "n_cases", "elapsed_s", "embed_backend", "vs_composite_v1",
        "cycle2_recommendation",
    )}, indent=2))
    print("summary keys", list(s.keys()))
    for name, row in s.items():
        print(
            name,
            row["accuracy"],
            row["mean_f1"],
            row["mean_recall_must"],
            row["mean_precision_hot"],
        )
    print("wrote", jp)
    print("wrote", mp)


if __name__ == "__main__":
    main()

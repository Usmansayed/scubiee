"""Bakeoff: composite_v1 vs semantic_tracer_v1 vs fuse (+ controls)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from trace_lab.cases import default_fixture_root
from trace_lab.metrics import evaluate
from trace_lab.prod_eval import _case_with_query_seed, _correct, _merge_heatmaps
from trace_lab.semantic_index import from_embed_field
from trace_lab.semantic_sensor import apply_vector_only, node_sem_scores
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
        "semantic_tracer_fuse",
        "semantic_tracer_fuse_teleport",
        "poly_embed",
        "hybrid_teleport",
    ]
    arm_names = [a for a in arm_names if a in tracers]
    rows: list[dict[str, Any]] = []

    for raw in cases:
        gold = prompt_to_case(raw)
        chunks = list(raw.get("seed_chunks") or [])
        if not chunks:
            chunks = [{"file": gold.seed.file, "symbol": gold.seed.symbol, "text": ""}]
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
            }
        seed_id = uniq[0].id
        q_aff = index.query_affinities(user_prompt)
        s_aff = index.seed_affinities(seed_id)
        sem = node_sem_scores(list(nodes.keys()), q_aff=q_aff, seed_id=seed_id, seed_aff=s_aff)
        vom = apply_vector_only(seed_id=seed_id, sem=sem, k=24)
        met = evaluate(vom, gold, nodes, hot_threshold=hot)
        hot_ids = hot_set(vom, hot)
        arm_out["vector_only"] = {
            **_correct(hot_ids, gold),
            "f1": met.f1,
            "recall_must": met.recall_must,
            "precision_hot": met.precision_hot,
            "must_at_10": round(_must_at_k(vom.ranked_ids(), gold.must_ids, 10), 4),
            "n_hot": len(hot_ids),
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

    def vs(name: str) -> dict[str, Any]:
        st = summary[name]
        must_up = st["mean_recall_must"] > base["mean_recall_must"]
        f1_drop = base["mean_f1"] - st["mean_f1"]
        prec_drop = base["mean_precision_hot"] - st["mean_precision_hot"]
        acc_drop = base["accuracy"] - st["accuracy"]
        return {
            "must_delta": round(st["mean_recall_must"] - base["mean_recall_must"], 4),
            "f1_delta": round(st["mean_f1"] - base["mean_f1"], 4),
            "prec_delta": round(st["mean_precision_hot"] - base["mean_precision_hot"], 4),
            "acc_delta": round(st["accuracy"] - base["accuracy"], 4),
            "must_at_10_delta": round(st["mean_must_at_10"] - base["mean_must_at_10"], 4),
            "ship_gate": must_up
            and f1_drop <= 0.02
            and prec_drop <= 0.03
            and acc_drop <= 0.05,
        }

    fuse_vs = vs("semantic_tracer_fuse")
    winners = [
        n
        for n in all_arms
        if n != "composite_v1" and vs(n).get("ship_gate")
    ]
    # Best balanced: max F1 among arms with acc >= base-0.05 and must >= base-0.01
    cands = [
        n
        for n, s in summary.items()
        if s["accuracy"] >= base["accuracy"] - 0.05
        and s["mean_recall_must"] >= base["mean_recall_must"] - 0.01
    ]
    best = max(cands, key=lambda n: (summary[n]["mean_f1"], summary[n]["mean_must_at_10"]))

    if fuse_vs["ship_gate"]:
        rec = "KEEP semantic_tracer_fuse as opt-in research default candidate; still do not flip MCP until second board confirms."
    elif (
        summary["semantic_tracer_fuse"]["mean_must_at_10"] > base["mean_must_at_10"]
        and fuse_vs["f1_delta"] >= -0.02
    ):
        rec = "Fuse improves ranking (must@10) without big F1 loss — keep as research arm; tighten teleport before ship."
    else:
        rec = "Fuse did not beat composite_v1 on balanced metrics — keep composite_v1; retain fuse for ablation research."

    return {
        "board": board_name,
        "n_cases": len(rows),
        "elapsed_s": round(time.time() - t0, 2),
        "embed_backend": index.backend,
        "summary": summary,
        "vs_composite": {n: vs(n) for n in all_arms if n != "composite_v1"},
        "ship_winners": winners,
        "best_balanced": best,
        "recommendation": rec,
    }


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default="verify_hard.json")
    ap.add_argument("--stem", default="2026-09-06-semantic-tracer-fuse-hard")
    args = ap.parse_args()
    out = run_board(args.board)
    plans = Path("docs/superpowers/plans")
    plans.mkdir(parents=True, exist_ok=True)
    jp = plans / f"{args.stem}.json"
    mp = plans / f"{args.stem}.md"
    jp.write_text(json.dumps(out, indent=2), encoding="utf-8")
    s = out["summary"]
    lines = [
        f"# Semantic tracer fuse bakeoff — `{out['board']}`",
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
    lines.extend(
        [
            "",
            f"**Best balanced:** `{out['best_balanced']}`",
            f"**Ship-gate winners:** {out['ship_winners'] or '(none)'}",
            "",
            "## vs composite_v1 (fuse)",
            "",
            "```json",
            json.dumps(out["vs_composite"].get("semantic_tracer_fuse", {}), indent=2),
            "```",
            "",
            "## Recommendation",
            "",
            out["recommendation"],
            "",
            "### Fusion contents",
            "",
            "- Cycle 1: edge/node comparator best-first + path polish",
            "- Cycle 2: live trace centroid + strict verified teleport",
            "- Cycle 3 lite: hub penalty + info-gain skip",
            "- Spine: composite membership + DFG/sink rank",
            "",
        ]
    )
    mp.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: out[k] for k in (
        "board", "n_cases", "elapsed_s", "best_balanced", "ship_winners", "recommendation",
    )}, indent=2))
    for name, row in s.items():
        print(name, row["accuracy"], row["mean_f1"], row["mean_recall_must"], row["mean_must_at_10"])
    print("wrote", jp)
    print("wrote", mp)


if __name__ == "__main__":
    main()

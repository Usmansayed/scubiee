"""Combo matrix bakeoff: structural vs semantic sensors vs verified teleport.

Shares one composite_v1 heatmap per case, then applies many post variants.
Boards: verify_hard (primary) and optionally verify_prod.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from trace_lab.cases import default_fixture_root
from trace_lab.metrics import evaluate
from trace_lab.prod_eval import _case_with_query_seed, _correct, _merge_heatmaps
from trace_lab.semantic_index import from_embed_field
from trace_lab.semantic_sensor import (
    apply_add_then_gate,
    apply_additive,
    apply_gate,
    apply_vector_only,
    node_sem_scores,
)
from trace_lab.semantic_teleport import apply_bm25_teleport, apply_embed_teleport
from trace_lab.sim import HOT_THRESHOLD
from trace_lab.strategies import compile_bundle
from trace_lab.types import GoldRef, Heatmap
from trace_lab.vague_eval import hot_set, prompt_to_case
from trace_lab.verify_board import _must_at_k


def _keep_vs_base(base: dict[str, Any], arm: dict[str, Any]) -> dict[str, Any]:
    hard_up = arm.get("accuracy", 0) > base.get("accuracy", 0)
    must_up = arm.get("mean_recall_must", 0) > base.get("mean_recall_must", 0)
    f1_drop = base.get("mean_f1", 0) - arm.get("mean_f1", 0)
    prec_drop = base.get("mean_precision_hot", 0) - arm.get("mean_precision_hot", 0)
    keep = (hard_up or must_up) and f1_drop <= 0.02 and prec_drop <= 0.03
    return {
        "keep": keep,
        "hard_up": hard_up,
        "must_up": must_up,
        "f1_drop": round(f1_drop, 4),
        "prec_drop": round(prec_drop, 4),
        "f1_delta": round(arm.get("mean_f1", 0) - base.get("mean_f1", 0), 4),
        "must_delta": round(
            arm.get("mean_recall_must", 0) - base.get("mean_recall_must", 0), 4
        ),
        "acc_delta": round(arm.get("accuracy", 0) - base.get("accuracy", 0), 4),
    }


def run_combo_board(
    board_name: str = "verify_hard.json",
    *,
    hot_threshold: float = HOT_THRESHOLD,
    max_cases: int | None = None,
) -> dict[str, Any]:
    root = default_fixture_root().resolve()
    board = json.loads((root / board_name).read_text(encoding="utf-8"))
    cases = board["cases"]
    if max_cases is not None:
        cases = cases[: max_cases]

    t0 = time.time()
    nodes, graph, lex, tracers = compile_bundle(
        root,
        with_graphify=True,
        with_embed_power=True,
        require_real_embeds=False,
    )
    struct_fn = tracers["composite_v1"]
    # Optional existing semantic-ish baselines
    extra_arms = {
        k: tracers[k]
        for k in ("hybrid_teleport", "poly_embed", "recall_belt")
        if k in tracers
    }

    from trace_lab.embed_field import EmbedField
    from trace_lab.graphify_layer import build_graphify_graph
    from trace_lab.lsp_index import build_lsp_index

    lsp = build_lsp_index(root, nodes, graph)
    field = EmbedField(
        nodes,
        cache_path=root / ".embed_cache" / "coderank.jsonl",
        require_real=False,
        quiet=True,
    )
    index = from_embed_field(field)
    try:
        gfy = build_graphify_graph(root, nodes)
    except Exception:  # noqa: BLE001
        gfy = None

    # Precompute nothing global — query/seed affinities are per case.
    # Variant builders close over struct_hm + sem maps.
    def build_variants(
        struct_hm: Heatmap,
        seed_id: str,
        query: str,
        q_aff: dict[str, float],
        s_aff: dict[str, float],
    ) -> dict[str, Heatmap]:
        island = [c.node_id for c in struct_hm.cells]
        out: dict[str, Heatmap] = {"composite_v1": struct_hm}

        # Weight / alpha / tau sweeps on island
        for wq, ws, tag in (
            (0.6, 0.4, "q60s40"),
            (1.0, 0.0, "q_only"),
            (0.0, 1.0, "s_only"),
            (0.5, 0.5, "q50s50"),
            (0.3, 0.7, "q30s70"),
        ):
            sem = node_sem_scores(
                island, q_aff=q_aff, seed_id=seed_id, seed_aff=s_aff, w_query=wq, w_seed=ws
            )
            for alpha in (0.10, 0.15, 0.25, 0.40):
                name = f"add_{tag}_a{int(alpha * 100)}"
                out[name] = apply_additive(
                    struct_hm, sem, alpha=alpha, strategy=name
                )
            for tau in (0.15, 0.25, 0.40):
                name = f"gate_{tag}_t{int(tau * 100)}"
                out[name] = apply_gate(
                    struct_hm, sem, tau=tau, seed_id=seed_id, strategy=name
                )
            name = f"add_gate_{tag}"
            out[name] = apply_add_then_gate(
                struct_hm, sem, alpha=0.25, tau=0.25, seed_id=seed_id, strategy=name
            )

        # Full-corpus semantic for vector_only + teleport
        all_ids = list(nodes.keys())
        sem_all = node_sem_scores(
            all_ids, q_aff=q_aff, seed_id=seed_id, seed_aff=s_aff, w_query=0.6, w_seed=0.4
        )
        sem_q = node_sem_scores(
            all_ids, q_aff=q_aff, seed_id=seed_id, seed_aff=s_aff, w_query=1.0, w_seed=0.0
        )
        out["vector_only"] = apply_vector_only(seed_id=seed_id, sem=sem_all, k=24)
        out["vector_only_q"] = apply_vector_only(
            seed_id=seed_id, sem=sem_q, k=24, strategy="vector_only_q"
        )

        for min_sem, top_k, tag in (
            (0.25, 12, "m25k12"),
            (0.35, 12, "m35k12"),
            (0.45, 8, "m45k8"),
            (0.30, 20, "m30k20"),
        ):
            name = f"embed_teleport_{tag}"
            out[name] = apply_embed_teleport(
                struct_hm,
                seed_id=seed_id,
                query=query,
                nodes=nodes,
                graph=graph,
                lsp=lsp,
                sem_all=sem_all,
                extra_graph=gfy,
                top_k=top_k,
                min_sem=min_sem,
                strategy=name,
            )
            # teleport then additive rescore on expanded island
            tele = out[name]
            sem_tele = node_sem_scores(
                [c.node_id for c in tele.cells],
                q_aff=q_aff,
                seed_id=seed_id,
                seed_aff=s_aff,
            )
            name2 = f"embed_teleport_add_{tag}"
            out[name2] = apply_additive(tele, sem_tele, alpha=0.20, strategy=name2)

        out["bm25_teleport"] = apply_bm25_teleport(
            struct_hm,
            seed_id=seed_id,
            query=query,
            nodes=nodes,
            graph=graph,
            lsp=lsp,
            lex=lex,
            extra_graph=gfy,
        )
        # Full stack: bm25 teleport + embed teleport + add
        stacked = apply_embed_teleport(
            out["bm25_teleport"],
            seed_id=seed_id,
            query=query,
            nodes=nodes,
            graph=graph,
            lsp=lsp,
            sem_all=sem_all,
            extra_graph=gfy,
            top_k=12,
            min_sem=0.30,
            strategy="stack_bm25_embed",
        )
        sem_s = node_sem_scores(
            [c.node_id for c in stacked.cells],
            q_aff=q_aff,
            seed_id=seed_id,
            seed_aff=s_aff,
        )
        out["stack_bm25_embed_add"] = apply_additive(
            stacked, sem_s, alpha=0.20, strategy="stack_bm25_embed_add"
        )
        return out

    arm_names: list[str] | None = None
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

        # Merge multi-seed structural heatmaps once
        struct_maps = []
        for s in uniq:
            sub = _case_with_query_seed(gold, user_prompt, s)
            struct_maps.append(struct_fn(sub, nodes, graph, lex))
        struct_hm = _merge_heatmaps(struct_maps, strategy="composite_v1+prod")
        seed_id = uniq[0].id

        q_aff = index.query_affinities(user_prompt)
        # seed affinities: use first seed; for multi-seed take max later if needed
        s_aff = index.seed_affinities(seed_id)
        if len(uniq) > 1:
            for s in uniq[1:]:
                other = index.seed_affinities(s.id)
                for nid, v in other.items():
                    s_aff[nid] = max(float(s_aff.get(nid, 0.0)), float(v))

        variants = build_variants(struct_hm, seed_id, user_prompt, q_aff, s_aff)

        # Extra live arms (re-run; not shared)
        for name, fn in extra_arms.items():
            maps = []
            for s in uniq:
                sub = _case_with_query_seed(gold, user_prompt, s)
                maps.append(fn(sub, nodes, graph, lex))
            variants[name] = _merge_heatmaps(maps, strategy=f"{name}+prod")

        if arm_names is None:
            arm_names = sorted(variants.keys())

        arm_out: dict[str, Any] = {}
        for name in arm_names:
            hm = variants[name]
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
                "n_hot": len(hot),
                "n_cells": len(hm.cells),
            }
        rows.append({"id": gold.id, "arms": arm_out})

    assert arm_names is not None
    summary: dict[str, Any] = {}
    soft_keys = ("f1", "recall_must", "precision_hot", "must_at_5", "must_at_10", "n_hot")
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
            "mean_hot": soft["n_hot"],
            "failed_ids": [r["id"] for r in rows if not r["arms"][name]["correct"]],
        }

    base = summary["composite_v1"]
    keep_kill = {
        name: _keep_vs_base(base, summary[name])
        for name in arm_names
        if name != "composite_v1"
    }
    # Rank by composite score: must-rec then F1 then accuracy
    ranked_arms = sorted(
        arm_names,
        key=lambda n: (
            summary[n]["mean_recall_must"],
            summary[n]["mean_f1"],
            summary[n]["accuracy"],
            -summary[n]["mean_hot"],
        ),
        reverse=True,
    )
    winners = [a for a, v in keep_kill.items() if v.get("keep")]
    best = ranked_arms[0]
    return {
        "board": board_name,
        "n_cases": len(rows),
        "elapsed_s": round(time.time() - t0, 2),
        "embed_backend": index.backend,
        "n_variants": len(arm_names),
        "base": {
            "accuracy": base["accuracy"],
            "mean_f1": base["mean_f1"],
            "mean_recall_must": base["mean_recall_must"],
            "mean_precision_hot": base["mean_precision_hot"],
        },
        "ranked_top15": [
            {
                "arm": n,
                **{k: summary[n][k] for k in (
                    "accuracy",
                    "mean_f1",
                    "mean_recall_must",
                    "mean_precision_hot",
                    "mean_must_at_10",
                )},
                "keep": keep_kill.get(n, {}).get("keep") if n != "composite_v1" else None,
            }
            for n in ranked_arms[:15]
        ],
        "winners_keep_gate": winners,
        "best_by_must_f1": best,
        "summary": summary,
        "keep_kill": keep_kill,
    }


def write_report(out: dict[str, Any], stem: str) -> tuple[Path, Path]:
    plans = Path("docs/superpowers/plans")
    plans.mkdir(parents=True, exist_ok=True)
    jp = plans / f"{stem}.json"
    mp = plans / f"{stem}.md"
    # Slim JSON for readability (drop full keep_kill noise in md; keep in json)
    slim = {k: v for k, v in out.items() if k not in {"summary", "keep_kill"}}
    slim["summary_top"] = {
        r["arm"]: out["summary"][r["arm"]] for r in out["ranked_top15"]
    }
    slim["keep_winners_detail"] = {
        a: out["keep_kill"][a] for a in out.get("winners_keep_gate", [])
    }
    jp.write_text(json.dumps(out, indent=2), encoding="utf-8")

    lines = [
        f"# Semantic combo bakeoff — `{out['board']}`",
        "",
        f"Cases: {out['n_cases']} · Variants: {out['n_variants']} · "
        f"Backend: `{out.get('embed_backend')}` · {out.get('elapsed_s')}s",
        "",
        "## Baseline (`composite_v1`)",
        "",
        f"- Acc {out['base']['accuracy']} · F1 {out['base']['mean_f1']} · "
        f"Must-rec {out['base']['mean_recall_must']} · Prec {out['base']['mean_precision_hot']}",
        "",
        "## Top 15 by must-rec → F1 → acc",
        "",
        "| Arm | Acc | F1 | Must | Prec | Keep? |",
        "|-----|-----|----|------|------|-------|",
    ]
    for r in out["ranked_top15"]:
        keep = r.get("keep")
        keep_s = "—" if keep is None else ("YES" if keep else "no")
        lines.append(
            f"| `{r['arm']}` | {r['accuracy']} | {r['mean_f1']} | "
            f"{r['mean_recall_must']} | {r['mean_precision_hot']} | {keep_s} |"
        )
    lines.extend(
        [
            "",
            f"**Best by ranking:** `{out['best_by_must_f1']}`",
            "",
            f"**Keep-gate winners:** {out['winners_keep_gate'] or '(none)'}",
            "",
            "## Verdict",
            "",
        ]
    )
    if out["winners_keep_gate"]:
        lines.append(
            "At least one semantic/hybrid variant beat `composite_v1` on hard↑ or "
            "must↑ without collapsing F1/precision — see winners above."
        )
    else:
        lines.append(
            "No variant met the keep gate (must↑ or hard↑ with F1 drop ≤0.02 and "
            "prec drop ≤0.03). Rank-only and teleport combos did not earn a default flip."
        )
    if out["best_by_must_f1"] != "composite_v1":
        lines.append(
            f"Note: raw best by must/F1 is `{out['best_by_must_f1']}` "
            "(may fail keep gate on precision)."
        )
    lines.append("")
    mp.write_text("\n".join(lines), encoding="utf-8")
    # also write slim companion
    (plans / f"{stem}.slim.json").write_text(json.dumps(slim, indent=2), encoding="utf-8")
    return jp, mp


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--board", default="verify_hard.json")
    ap.add_argument("--max-cases", type=int, default=None)
    ap.add_argument("--stem", default="2026-09-06-semantic-combo-hard")
    args = ap.parse_args()
    out = run_combo_board(args.board, max_cases=args.max_cases)
    jp, mp = write_report(out, args.stem)
    print(json.dumps({k: out[k] for k in (
        "board", "n_cases", "n_variants", "elapsed_s", "embed_backend",
        "base", "ranked_top15", "winners_keep_gate", "best_by_must_f1",
    )}, indent=2))
    print("wrote", jp)
    print("wrote", mp)


if __name__ == "__main__":
    main()

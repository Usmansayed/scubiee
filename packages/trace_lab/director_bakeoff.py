"""Bakeoff Trace Director arms A/B/C vs polytrace on verify_hard."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from trace_lab.cases import default_fixture_root
from trace_lab.metrics import evaluate
from trace_lab.ollama_client import ollama_generate
from trace_lab.sim import HOT_THRESHOLD
from trace_lab.strategies import compile_bundle
from trace_lab.trace_director import Arm, parse_plan_selftest, run_director
from trace_lab.vague_eval import hot_set, prompt_to_case
from trace_lab.verify_board import _correct, _must_at_k, load_verify_board


def _warm(model: str) -> None:
    ollama_generate(
        "ready",
        model=model,
        num_predict=4,
        keep_alive="60m",
        num_ctx=2048,
    )


def run_director_bakeoff(
    fixture: Path | None = None,
    *,
    board_name: str = "verify_hard.json",
    hot_threshold: float = HOT_THRESHOLD,
    model: str = "qwen3.5-0.8b-q4",
    arms: tuple[Arm, ...] = ("A", "B", "C"),
    limit: int | None = None,
    with_baseline: bool = True,
    with_dense: bool = True,
) -> dict[str, Any]:
    parse_plan_selftest()
    root = (fixture or default_fixture_root()).resolve()
    board = load_verify_board(root / board_name)
    cases = board["cases"]
    if limit is not None:
        cases = cases[:limit]

    nodes, graph, lex, tracers = compile_bundle(
        root,
        with_graphify=True,
        with_embed_power=with_dense,
        require_real_embeds=False,
    )
    gfy = None
    # recover graphify graph used inside polytrace binder via rebuild (cheap-ish)
    from trace_lab.graphify_layer import build_graphify_graph

    gfy = build_graphify_graph(root, nodes)

    field = None
    if with_dense and "poly_embed" in tracers:
        # EmbedField lives inside binders; rebuild lightweight
        from trace_lab.embed_field import EmbedField

        field = EmbedField(
            nodes,
            cache_path=root / ".embed_cache" / "coderank.jsonl",
            require_real=False,
            quiet=True,
        )

    print(f"warming {model}...", flush=True)
    _warm(model)

    arm_names = [f"director_{a}" for a in arms]
    if with_baseline:
        arm_names = ["polytrace", *arm_names]

    rows: list[dict[str, Any]] = []
    for raw in cases:
        gold = prompt_to_case(raw)
        arm_out: dict[str, Any] = {}

        if with_baseline:
            t0 = time.perf_counter()
            hm = tracers["polytrace"](gold, nodes, graph, lex)
            wall = time.perf_counter() - t0
            met = evaluate(hm, gold, nodes, hot_threshold=hot_threshold)
            hot = hot_set(hm, hot_threshold)
            ver = _correct(hot, gold)
            ranked = hm.ranked_ids()
            arm_out["polytrace"] = {
                **ver,
                "f1": met.f1,
                "recall_must": met.recall_must,
                "precision_hot": met.precision_hot,
                "ndcg": met.ndcg,
                "must_at_10": round(_must_at_k(ranked, gold.must_ids, 10), 4),
                "wall_s": round(wall, 3),
                "llm_wall_s": 0.0,
                "eval_tok_s": 0.0,
                "prompt_tok_s": 0.0,
            }

        dense = field.affinities(gold.query) if field is not None else None
        for arm in arms:
            t0 = time.perf_counter()
            try:
                hm, plan, oll, pack = run_director(
                    arm,
                    gold,
                    nodes,
                    graph,
                    lex,
                    gfy,
                    dense=dense,
                    model=model,
                )
                err = None
            except Exception as e:  # noqa: BLE001 — bakeoff continues
                err = str(e)
                hm = None
                plan = None
                oll = None
                pack = None
            wall = time.perf_counter() - t0
            name = f"director_{arm}"
            if hm is None:
                arm_out[name] = {
                    "correct": False,
                    "error": err,
                    "wall_s": round(wall, 3),
                }
                continue
            met = evaluate(hm, gold, nodes, hot_threshold=hot_threshold)
            hot = hot_set(hm, hot_threshold)
            ver = _correct(hot, gold)
            ranked = hm.ranked_ids()
            arm_out[name] = {
                **ver,
                "f1": met.f1,
                "recall_must": met.recall_must,
                "precision_hot": met.precision_hot,
                "ndcg": met.ndcg,
                "must_at_10": round(_must_at_k(ranked, gold.must_ids, 10), 4),
                "wall_s": round(wall, 3),
                "llm_wall_s": round(oll.wall_s, 3),
                "eval_tok_s": round(oll.eval_tok_s, 1),
                "prompt_tok_s": round(oll.prompt_tok_s, 1),
                "eval_count": oll.eval_count,
                "prompt_tokens": oll.prompt_eval_count,
                "n_pack": len(pack.numbered),
                "plan_intent": plan.intent,
                "plan_note": plan.note,
                "keep_n": len(plan.keep),
                "drop_n": len(plan.drop),
                "raw_plan": (plan.raw or "")[:500],
                "prompt_preview": pack.prompt[:1200],
            }
            print(
                f"  {gold.id} {name}: correct={ver['correct']} "
                f"rec={met.recall_must:.2f} prec={met.precision_hot:.2f} "
                f"wall={wall:.2f}s llm={oll.wall_s:.2f}s",
                flush=True,
            )

        rows.append({"id": gold.id, "title": gold.title, "arms": arm_out})

    summary: dict[str, Any] = {}
    for name in arm_names:
        subset = [r["arms"][name] for r in rows if name in r["arms"] and "error" not in r["arms"][name]]
        if not subset:
            summary[name] = {"n": 0}
            continue
        n = len(subset)
        summary[name] = {
            "n": n,
            "hard": sum(1 for x in subset if x.get("correct")),
            "acc": round(sum(1 for x in subset if x.get("correct")) / n, 4),
            "must_rec": round(sum(x.get("recall_must", 0) for x in subset) / n, 4),
            "prec": round(sum(x.get("precision_hot", 0) for x in subset) / n, 4),
            "f1": round(sum(x.get("f1", 0) for x in subset) / n, 4),
            "ndcg": round(sum(x.get("ndcg", 0) for x in subset) / n, 4),
            "must_at_10": round(sum(x.get("must_at_10", 0) for x in subset) / n, 4),
            "wall_s_mean": round(sum(x.get("wall_s", 0) for x in subset) / n, 3),
            "llm_wall_s_mean": round(sum(x.get("llm_wall_s", 0) for x in subset) / n, 3),
            "eval_tok_s_mean": round(sum(x.get("eval_tok_s", 0) for x in subset) / n, 1),
            "under_5s": sum(1 for x in subset if x.get("wall_s", 99) < 5.0),
        }

    return {
        "board": board_name,
        "model": model,
        "hot_threshold": hot_threshold,
        "n_cases": len(rows),
        "summary": summary,
        "cases": rows,
    }


def format_director_table(report: dict[str, Any]) -> str:
    lines = [
        f"director bakeoff  n={report['n_cases']}  model={report['model']}",
        f"{'arm':18} {'hard':>7} {'acc':>6} {'rec':>6} {'prec':>6} {'f1':>6} "
        f"{'ndcg':>6} {'@10':>5} {'wall':>6} {'llm':>6} {'<5s':>5}",
    ]
    for name, s in report["summary"].items():
        if not s.get("n"):
            continue
        lines.append(
            f"{name:18} {s['hard']:>3}/{s['n']:<3} {s['acc']:6.2f} {s['must_rec']:6.2f} "
            f"{s['prec']:6.2f} {s['f1']:6.2f} {s['ndcg']:6.2f} {s['must_at_10']:5.2f} "
            f"{s['wall_s_mean']:6.2f} {s['llm_wall_s_mean']:6.2f} {s['under_5s']:>5}"
        )
    return "\n".join(lines)


def dump_director_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")

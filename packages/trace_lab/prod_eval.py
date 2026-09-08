"""Production-like verify: detailed paragraph + 2 seed code chunks.

Mirrors how an agent would ask: write what you want, paste two code anchors.
Runs non-LLM arms with (a) enriched query text and (b) multi-seed heatmap merge.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trace_lab.cases import default_fixture_root
from trace_lab.metrics import evaluate
from trace_lab.sim import HOT_THRESHOLD
from trace_lab.strategies import compile_bundle
from trace_lab.types import GoldCase, GoldRef, HeatCell, Heatmap
from trace_lab.vague_eval import hot_set, prompt_to_case
from trace_lab.verify_board import _correct, _must_at_k, dump_verify_report, format_verify_table


def _enrich_query(paragraph: str, chunks: list[dict[str, Any]]) -> str:
    parts = [paragraph.strip(), "", "## Seed code anchors"]
    for i, ch in enumerate(chunks, start=1):
        parts.append(f"### Seed {i}: {ch['file']}::{ch['symbol']}")
        parts.append("```")
        parts.append((ch.get("text") or "").strip())
        parts.append("```")
    return "\n".join(parts)


def _merge_heatmaps(maps: list[Heatmap], strategy: str) -> Heatmap:
    by: dict[str, HeatCell] = {}
    for hm in maps:
        for c in hm.cells:
            prev = by.get(c.node_id)
            if prev is None or c.score > prev.score:
                by[c.node_id] = HeatCell(
                    node_id=c.node_id,
                    score=c.score,
                    why=c.why,
                    path=c.path,
                )
    cells = sorted(by.values(), key=lambda c: -c.score)
    return Heatmap(strategy=strategy, cells=cells, extra={"merged_from": len(maps)})


def _case_with_query_seed(gold: GoldCase, query: str, seed: GoldRef) -> GoldCase:
    return GoldCase(
        id=gold.id,
        title=gold.title,
        query=query,
        seed=seed,
        must=list(gold.must),
        should=list(gold.should),
        must_not=list(gold.must_not),
        gold_rank=list(gold.gold_rank),
        notes=gold.notes,
    )


def run_prod_verify(
    fixture: Path | None = None,
    *,
    board_name: str = "verify_prod.json",
    hot_threshold: float = HOT_THRESHOLD,
) -> dict[str, Any]:
    root = (fixture or default_fixture_root()).resolve()
    board = json.loads((root / board_name).read_text(encoding="utf-8"))
    cases = board["cases"]

    nodes, graph, lex, tracers = compile_bundle(
        root,
        with_graphify=True,
        with_embed_power=True,
        require_real_embeds=False,
    )
    from trace_lab.embed_field import EmbedField
    from trace_lab.graphify_layer import build_graphify_graph
    from trace_lab.lsp_index import build_lsp_index
    from trace_lab.recall_belt import bind_recall_belt, bind_recall_fuse
    from trace_lab.semantic_trace import bind_semantic_trace

    lsp = build_lsp_index(root, nodes, graph)
    field = EmbedField(
        nodes,
        cache_path=root / ".embed_cache" / "coderank.jsonl",
        require_real=False,
        quiet=True,
    )
    try:
        gfy = build_graphify_graph(root, nodes)
    except Exception:  # noqa: BLE001
        gfy = None
    tracers.setdefault("semantic_trace", bind_semantic_trace(lsp, field))
    tracers["recall_belt"] = bind_recall_belt(lsp, field, gfy)
    tracers["recall_fuse"] = bind_recall_fuse(lsp, field, tracers["polytrace"], gfy)
    from trace_lab.ultimate_trace import bind_ultimate_trace

    tracers["ultimate_trace"] = bind_ultimate_trace(lsp, extra_graph=gfy)
    from trace_lab.arms import register_composite_semantic_arms, register_system_arms

    register_system_arms(root, lsp, gfy, tracers)
    register_composite_semantic_arms(root, lsp, field, gfy, tracers)

    arm_names = [
        "polytrace",
        "callgraph_jedi",
        "composite_v1",
        "semantic_tracer_v1",
        "semantic_tracer_fuse",
        "composite_semantic_add",
        "composite_semantic_gate",
        "dfg_slice",
        "pdg_prio",
        "hybrid_teleport",
        "rank_default",
        "rank_strict",
        "ultimate_trace",
        "semantic_trace",
        "recall_belt",
        "recall_fuse",
    ]
    # Keep only arms that exist
    arm_names = [a for a in arm_names if a in tracers]
    rows: list[dict[str, Any]] = []

    for raw in cases:
        gold = prompt_to_case(raw)
        chunks = list(raw.get("seed_chunks") or [])
        if len(chunks) < 2:
            # fallback: seed + first must
            chunks = [
                {
                    "file": gold.seed.file,
                    "symbol": gold.seed.symbol,
                    "text": nodes[gold.seed.id].text if gold.seed.id in nodes else "",
                }
            ]
            if gold.must:
                m = gold.must[min(1, len(gold.must) - 1)]
                chunks.append(
                    {
                        "file": m.file,
                        "symbol": m.symbol,
                        "text": nodes[m.id].text if m.id in nodes else "",
                    }
                )
        query = _enrich_query(raw["prompt"], chunks)
        # System arms use user paragraph only for intent; pass both:
        # - enriched query for legacy arms (polytrace)
        # - prompt-only stored on case.notes for diagnostics
        seeds = [GoldRef(file=ch["file"], symbol=ch["symbol"]) for ch in chunks]
        # dedupe seeds
        seen: set[str] = set()
        uniq_seeds: list[GoldRef] = []
        for s in seeds:
            if s.id in seen or s.id not in nodes:
                continue
            seen.add(s.id)
            uniq_seeds.append(s)
        if not uniq_seeds:
            uniq_seeds = [gold.seed]

        user_prompt = str(raw.get("prompt") or gold.query)
        arm_out: dict[str, Any] = {}
        from trace_lab.failure_report import build_failure_report

        for name in arm_names:
            fn = tracers[name]
            maps: list[Heatmap] = []
            # Layered system arms: query = user paragraph only (anti intent_poison)
            q_for_arm = user_prompt if name in {
                "callgraph_jedi",
                "composite_v1",
                "semantic_tracer_v1",
                "semantic_tracer_fuse",
                "composite_semantic_add",
                "composite_semantic_gate",
                "dfg_slice",
                "pdg_prio",
                "hybrid_teleport",
                "rank_default",
                "rank_strict",
            } else query
            for s in uniq_seeds:
                sub = _case_with_query_seed(gold, q_for_arm, s)
                maps.append(fn(sub, nodes, graph, lex))
            hm = _merge_heatmaps(maps, strategy=f"{name}+prod")
            met = evaluate(hm, gold, nodes, hot_threshold=hot_threshold)
            hot = hot_set(hm, hot_threshold)
            ver = _correct(hot, gold)
            ranked = hm.ranked_ids()
            fail = build_failure_report(gold, hm, nodes, hot_threshold=hot_threshold)
            arm_out[name] = {
                **ver,
                "f1": met.f1,
                "recall_must": met.recall_must,
                "precision_hot": met.precision_hot,
                "ndcg": met.ndcg,
                "inversions": met.inversions,
                "must_at_5": round(_must_at_k(ranked, gold.must_ids, 5), 4),
                "must_at_10": round(_must_at_k(ranked, gold.must_ids, 10), 4),
                "n_seeds": len(uniq_seeds),
                "prompt_chars": len(q_for_arm),
                "explored_nodes": fail["explored_nodes"],
                "hot_count": fail["hot_count"],
                "failure_report": fail,
            }
        rows.append(
            {
                "id": gold.id,
                "family": str(raw.get("family") or ""),
                "prompt": raw["prompt"],
                "seed": gold.seed.id,
                "seed_chunks": [f"{c['file']}::{c['symbol']}" for c in chunks],
                "arms": arm_out,
            }
        )

    summary: dict[str, Any] = {}
    soft_keys = ("f1", "recall_must", "precision_hot", "ndcg", "must_at_5", "must_at_10", "explored_nodes", "hot_count")
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
            "mean_ndcg": soft["ndcg"],
            "mean_must_at_5": soft["must_at_5"],
            "mean_must_at_10": soft["must_at_10"],
            "mean_explored_nodes": soft["explored_nodes"],
            "mean_hot_count": soft["hot_count"],
            "total_inversions": sum(r["arms"][name]["inversions"] for r in rows),
            "failed_ids": [r["id"] for r in rows if not r["arms"][name]["correct"]],
        }

    return {
        "fixture": str(root),
        "board": board_name,
        "n_cases": len(rows),
        "definition": "correct <=> all must are hot AND no must_not is hot",
        "mode": "production-like paragraph + 2 seed chunks; multi-seed merge; enriched query",
        "summary": summary,
        "cases": rows,
    }


def main_prod_cli(out: Path | None = None, fixture: Path | None = None, hot: float = HOT_THRESHOLD) -> dict[str, Any]:
    report = run_prod_verify(fixture, hot_threshold=hot)
    print(format_verify_table(report))
    print(f"mode: {report.get('mode')}")
    path = out or Path("docs/superpowers/plans/verify-prod-results.json")
    dump_verify_report(report, path)
    print(f"wrote {path}")
    return report

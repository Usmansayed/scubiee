"""Vague-prompt eval: map (BM25+vector) → PolyTrace → heatmap vs gold.

This is the honesty check the crisp gold cases skip: humans ask vaguely,
and the seed is not handed to the tracer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from conductor.bm25_index import tokenize
from trace_lab.cases import default_fixture_root
from trace_lab.metrics import evaluate
from trace_lab.retrieve import LexicalIndex, query_intent
from trace_lab.sim import HOT_THRESHOLD
from trace_lab.strategies import compile_bundle
from trace_lab.types import GoldCase, GoldRef, HeatCell, Heatmap, TraceNode
from trace_lab.vector_index import VectorIndex, hybrid_map_scores, pick_seed


def load_vague_prompts(path: Path | None = None) -> dict[str, Any]:
    root = default_fixture_root()
    path = path or (root / "vague_prompts.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _ref(raw: dict) -> GoldRef:
    return GoldRef(file=str(raw["file"]).replace("\\", "/"), symbol=str(raw["symbol"]))


def prompt_to_case(raw: dict) -> GoldCase:
    seed = _ref(raw["seed"])
    return GoldCase(
        id=str(raw["id"]),
        title=str(raw.get("family") or raw["id"]),
        query=str(raw["prompt"]),
        seed=seed,
        must=[_ref(x) for x in raw.get("must") or []],
        should=[_ref(x) for x in raw.get("should") or []],
        must_not=[_ref(x) for x in raw.get("must_not") or []],
        gold_rank=[],
        notes=str(raw.get("notes") or ""),
    )


def hot_set(hm: Heatmap, threshold: float = HOT_THRESHOLD) -> set[str]:
    return {c.node_id for c in hm.cells if c.score >= threshold}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    u = a | b
    return len(a & b) / max(len(u), 1)


def run_vague_eval(
    fixture: Path | None = None,
    *,
    hot_threshold: float = HOT_THRESHOLD,
    with_graphify: bool = False,
    with_embed_power: bool = True,
    require_real_embeds: bool = False,
) -> dict[str, Any]:
    root = (fixture or default_fixture_root()).resolve()
    bundle = load_vague_prompts(root / "vague_prompts.json")
    prompts = bundle["prompts"]
    nodes, graph, lex, tracers = compile_bundle(
        root,
        with_graphify=with_graphify,
        with_embed_power=with_embed_power,
        require_real_embeds=require_real_embeds,
    )
    map_lex = LexicalIndex(nodes, include_path=True)
    from trace_lab.vector_index import VectorIndex

    vec = VectorIndex(nodes)
    poly = tracers["polytrace"]
    embed_fn = tracers.get("embed_power")
    embed_ora = tracers.get("embed_power_oracle")

    rows: list[dict[str, Any]] = []
    family_hots: dict[str, list[set[str]]] = {}
    oracle_family_hots: dict[str, list[set[str]]] = {}

    for raw in prompts:
        gold = prompt_to_case(raw)
        family = str(raw.get("family") or gold.id)
        intent = query_intent(gold.query)

        bm_scores = hybrid_map_scores(gold.query, map_lex, vec, bm25_weight=1.0)
        vec_scores = hybrid_map_scores(gold.query, map_lex, vec, bm25_weight=0.0)
        hyb_scores = hybrid_map_scores(gold.query, map_lex, vec, bm25_weight=0.45)

        seeds = {
            "oracle": gold.seed.id,
            "bm25": pick_seed(gold.query, nodes, bm_scores, intent=intent),
            "vector": pick_seed(gold.query, nodes, vec_scores, intent=intent),
            "hybrid": pick_seed(gold.query, nodes, hyb_scores, intent=intent),
        }

        arm: dict[str, Any] = {}
        for mode, sid in seeds.items():
            if sid is None or sid not in nodes:
                arm[mode] = {
                    "seed": None,
                    "seed_ok": False,
                    "recall_must": 0.0,
                    "precision_hot": 0.0,
                    "f1": 0.0,
                    "false_negatives": sorted(gold.must_ids),
                    "false_positives_forbidden": [],
                    "hot": [],
                }
                continue
            n = nodes[sid]
            case = GoldCase(
                id=gold.id,
                title=gold.title,
                query=gold.query,
                seed=GoldRef(n.file, n.symbol),
                must=gold.must,
                should=gold.should,
                must_not=gold.must_not,
                gold_rank=[],
                notes=gold.notes,
            )
            hm = poly(case, nodes, graph, lex)
            met = evaluate(hm, gold, nodes, hot_threshold=hot_threshold)
            hot = hot_set(hm, hot_threshold)
            arm[mode] = {
                "seed": sid,
                "seed_ok": sid == gold.seed.id or sid in gold.must_ids or sid in gold.should_ids,
                "seed_exact": sid == gold.seed.id,
                "recall_must": met.recall_must,
                "precision_hot": met.precision_hot,
                "f1": met.f1,
                "false_negatives": met.false_negatives,
                "false_positives_forbidden": met.false_positives_forbidden,
                "hot": sorted(hot),
                "intent": intent,
            }
            if mode == "hybrid":
                family_hots.setdefault(family, []).append(hot)
            if mode == "oracle":
                oracle_family_hots.setdefault(family, []).append(hot)

        # mapfuse: BM25+vector map → top-k seeds → merge PolyTrace heatmaps
        hm_m, seed_m, seeds_m = map_then_polytrace(
            gold.query, nodes, graph, lex, poly, vec, map_lex=map_lex, top_k=4
        )
        met_m = evaluate(hm_m, gold, nodes, hot_threshold=hot_threshold)
        hot_m = hot_set(hm_m, hot_threshold)
        arm["mapfuse"] = {
            "seed": seed_m,
            "seeds": seeds_m,
            "seed_ok": bool(
                seed_m
                and (
                    seed_m == gold.seed.id
                    or seed_m in gold.must_ids
                    or seed_m in gold.should_ids
                    or any(
                        s == gold.seed.id or s in gold.must_ids or s in gold.should_ids
                        for s in seeds_m
                    )
                )
            ),
            "seed_exact": seed_m == gold.seed.id,
            "recall_must": met_m.recall_must,
            "precision_hot": met_m.precision_hot,
            "f1": met_m.f1,
            "false_negatives": met_m.false_negatives,
            "false_positives_forbidden": met_m.false_positives_forbidden,
            "hot": sorted(hot_m),
            "intent": intent,
        }
        family_hots.setdefault(f"mapfuse:{family}", []).append(hot_m)

        if embed_fn is not None:
            # Seed is ignored by embed_power except as unused GoldCase field;
            # affinities pick soft seeds. Still pass gold.seed for schema.
            hm_e = embed_fn(gold, nodes, graph, lex)
            met_e = evaluate(hm_e, gold, nodes, hot_threshold=hot_threshold)
            hot_e = hot_set(hm_e, hot_threshold)
            # Approximate "seed" as highest affinity hot node for reporting
            top_e = hm_e.ranked_ids()[0] if hm_e.cells else None
            arm["embed_power"] = {
                "seed": top_e,
                "seed_ok": bool(hot_e & (gold.must_ids | gold.should_ids | {gold.seed.id})),
                "seed_exact": top_e == gold.seed.id,
                "recall_must": met_e.recall_must,
                "precision_hot": met_e.precision_hot,
                "f1": met_e.f1,
                "false_negatives": met_e.false_negatives,
                "false_positives_forbidden": met_e.false_positives_forbidden,
                "hot": sorted(hot_e),
                "intent": intent,
            }
            family_hots.setdefault(f"embed:{family}", []).append(hot_e)
        if embed_ora is not None:
            hm_o = embed_ora(gold, nodes, graph, lex)
            met_o = evaluate(hm_o, gold, nodes, hot_threshold=hot_threshold)
            hot_o = hot_set(hm_o, hot_threshold)
            arm["embed_power_oracle"] = {
                "seed": gold.seed.id,
                "seed_ok": True,
                "seed_exact": True,
                "recall_must": met_o.recall_must,
                "precision_hot": met_o.precision_hot,
                "f1": met_o.f1,
                "false_negatives": met_o.false_negatives,
                "false_positives_forbidden": met_o.false_positives_forbidden,
                "hot": sorted(hot_o),
                "intent": intent,
            }

        rows.append(
            {
                "id": gold.id,
                "family": family,
                "prompt": gold.query,
                "gold_seed": gold.seed.id,
                "intent": intent,
                "arms": arm,
            }
        )

    family_agree = _family_agreement(
        {k: v for k, v in family_hots.items() if ":" not in k}
    )
    mapfuse_agree = _family_agreement(
        {
            k.split(":", 1)[1]: v
            for k, v in family_hots.items()
            if k.startswith("mapfuse:")
        }
    )
    embed_agree = _family_agreement(
        {
            k.split(":", 1)[1]: v
            for k, v in family_hots.items()
            if k.startswith("embed:")
        }
    )
    oracle_agree = _family_agreement(oracle_family_hots)
    summary = _summarize(rows, family_agree, oracle_agree)
    summary["mapfuse_mean_family_jaccard"] = round(
        sum(v["mean_pairwise_jaccard"] for v in mapfuse_agree.values() if v["n"] >= 2)
        / max(sum(1 for v in mapfuse_agree.values() if v["n"] >= 2), 1),
        4,
    )
    summary["mapfuse_families_identical"] = sum(
        1 for v in mapfuse_agree.values() if v["n"] >= 2 and v["identical"]
    )
    summary["embed_mean_family_jaccard"] = round(
        sum(v["mean_pairwise_jaccard"] for v in embed_agree.values() if v["n"] >= 2)
        / max(sum(1 for v in embed_agree.values() if v["n"] >= 2), 1),
        4,
    )
    summary["embed_families_identical"] = sum(
        1 for v in embed_agree.values() if v["n"] >= 2 and v["identical"]
    )
    return {
        "fixture": str(root),
        "n_prompts": len(rows),
        "hot_threshold": hot_threshold,
        "summary": summary,
        "family_agreement": family_agree,
        "mapfuse_family_agreement": mapfuse_agree,
        "embed_family_agreement": embed_agree,
        "oracle_family_agreement": oracle_agree,
        "prompts": rows,
    }


def _family_agreement(family_hots: dict[str, list[set[str]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for fam, hots in family_hots.items():
        if len(hots) < 2:
            out[fam] = {"n": len(hots), "mean_pairwise_jaccard": 1.0, "identical": True}
            continue
        pairs = []
        identical = True
        for i in range(len(hots)):
            for j in range(i + 1, len(hots)):
                jacc = jaccard(hots[i], hots[j])
                pairs.append(jacc)
                if hots[i] != hots[j]:
                    identical = False
        out[fam] = {
            "n": len(hots),
            "mean_pairwise_jaccard": round(sum(pairs) / max(len(pairs), 1), 4),
            "identical": identical,
        }
    return out


def _summarize(
    rows: list[dict[str, Any]],
    family_agree: dict[str, Any],
    oracle_agree: dict[str, Any] | None = None,
) -> dict[str, Any]:
    modes = ("oracle", "bm25", "vector", "hybrid", "mapfuse", "embed_power", "embed_power_oracle")
    by_mode: dict[str, Any] = {}
    for mode in modes:
        present = [r for r in rows if mode in r["arms"]]
        if not present:
            continue
        f1s = [r["arms"][mode]["f1"] for r in present]
        recs = [r["arms"][mode]["recall_must"] for r in present]
        seed_ok = sum(1 for r in present if r["arms"][mode].get("seed_ok"))
        seed_exact = sum(1 for r in present if r["arms"][mode].get("seed_exact"))
        fn = sum(len(r["arms"][mode]["false_negatives"]) for r in present)
        fp = sum(len(r["arms"][mode]["false_positives_forbidden"]) for r in present)
        by_mode[mode] = {
            "mean_f1": round(sum(f1s) / max(len(f1s), 1), 4),
            "mean_recall_must": round(sum(recs) / max(len(recs), 1), 4),
            "seed_ok": seed_ok,
            "seed_exact": seed_exact,
            "n": len(present),
            "sum_fn": fn,
            "sum_forbidden_fp": fp,
        }
    mean_fam = [
        v["mean_pairwise_jaccard"]
        for v in family_agree.values()
        if v["n"] >= 2
    ]
    oracle_mean = [
        v["mean_pairwise_jaccard"]
        for v in (oracle_agree or {}).values()
        if v["n"] >= 2
    ]
    return {
        "arms": by_mode,
        "mean_family_jaccard": round(sum(mean_fam) / max(len(mean_fam), 1), 4),
        "families_identical": sum(
            1 for v in family_agree.values() if v["n"] >= 2 and v["identical"]
        ),
        "families_compared": sum(1 for v in family_agree.values() if v["n"] >= 2),
        "oracle_mean_family_jaccard": round(sum(oracle_mean) / max(len(oracle_mean), 1), 4),
        "oracle_families_identical": sum(
            1 for v in (oracle_agree or {}).values() if v["n"] >= 2 and v["identical"]
        ),
    }


def format_vague_table(report: dict[str, Any]) -> str:
    lines = [
        f"vague-eval  prompts={report['n_prompts']}",
        f"{'arm':10} {'F1':>7} {'recall':>7} {'seedOK':>7} {'exact':>6} {'FN':>4} {'FP!':>4}",
        "-" * 52,
    ]
    for mode, row in report["summary"]["arms"].items():
        lines.append(
            f"{mode:10} {row['mean_f1']:7.3f} {row['mean_recall_must']:7.3f} "
            f"{row['seed_ok']:7d} {row['seed_exact']:6d} {row['sum_fn']:4d} {row['sum_forbidden_fp']:4d}"
        )
    lines.append(
        f"family Jaccard hybrid={report['summary']['mean_family_jaccard']:.3f} "
        f"| mapfuse={report['summary'].get('mapfuse_mean_family_jaccard', 0):.3f} "
        f"| embed_power={report['summary'].get('embed_mean_family_jaccard', 0):.3f} "
        f"| oracle={report['summary'].get('oracle_mean_family_jaccard', 0):.3f}"
    )
    return "\n".join(lines)


def dump_vague_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def map_then_polytrace(
    query: str,
    nodes: dict[str, TraceNode],
    graph,
    lex,
    poly,
    vec: VectorIndex,
    *,
    map_lex: LexicalIndex | None = None,
    top_k: int = 4,
) -> tuple[Heatmap, str | None, list[str]]:
    """Product-shaped path: hybrid map → try top seeds → merge PolyTrace heat."""
    from trace_lab.polytrace import faction_of, is_foreign

    intent = query_intent(query)
    mlex = map_lex or lex
    scores = hybrid_map_scores(query, mlex, vec, bm25_weight=0.45)
    primary = pick_seed(query, nodes, scores, intent=intent)
    candidates: list[str] = []
    if primary:
        candidates.append(primary)
    ql = query.lower()
    qtoks = set(tokenize(query.lower()))
    allow_logger = bool(qtoks & {"log", "logger", "logging", "printing", "print"}) or "print" in ql
    allow_http = bool(qtoks & {"pay", "payment", "bill", "billing", "cents", "http"})
    for nid, sc in sorted(scores.items(), key=lambda kv: -kv[1]):
        if sc <= 0 or nid in candidates:
            continue
        n = nodes.get(nid)
        if n is None or n.kind not in {"function", "method", "const"}:
            continue
        p = "/" + n.file.replace("\\", "/")
        if "/logger.py" in p and not allow_logger:
            continue
        if "/http/" in p and not allow_http:
            continue
        candidates.append(nid)
        if len(candidates) >= top_k:
            break

    merged: dict[str, float] = {}
    why: dict[str, str] = {}
    paths: dict[str, tuple[str, ...]] = {}
    used_seeds: list[str] = []
    primary_fac = faction_of(nodes[candidates[0]].file) if candidates else "auth"
    from trace_lab.polytrace import _ALLIES

    allies = _ALLIES.get(primary_fac, frozenset({primary_fac}))
    for sid in candidates:
        n = nodes[sid]
        if faction_of(n.file) not in allies and sid != candidates[0]:
            # Allow a second-chance seed if it is a gold-ish topic hit in allies only
            continue
        case = GoldCase(
            id="map",
            title="map",
            query=query,
            seed=GoldRef(n.file, n.symbol),
            must=[],
            should=[],
            must_not=[],
            gold_rank=[],
        )
        hm = poly(case, nodes, graph, lex)
        used_seeds.append(sid)
        for c in hm.cells:
            dst = nodes.get(c.node_id)
            if dst is None:
                continue
            if is_foreign(dst, query, n.file) and c.node_id != sid:
                continue
            if c.score > merged.get(c.node_id, 0.0):
                merged[c.node_id] = c.score
                why[c.node_id] = f"map[{n.symbol}]/{c.why}"
                paths[c.node_id] = c.path

    cells = [
        HeatCell(
            node_id=nid,
            score=round(sc, 4),
            why=why.get(nid, "map"),
            path=paths.get(nid, (nid,)),
        )
        for nid, sc in sorted(merged.items(), key=lambda kv: -kv[1])
        if sc > 0
    ]
    return Heatmap(strategy="polytrace_map", cells=cells), (
        used_seeds[0] if used_seeds else None
    ), used_seeds

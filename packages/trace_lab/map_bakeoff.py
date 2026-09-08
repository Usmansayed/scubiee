"""Map-algorithm bakeoff: BM25 / graph+BM25 / dense / hybrid → PolyTrace.

Question: can graph+BM25 beat CodeRank embeddings for *seed finding*,
when expansion is always structure-only PolyTrace?
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.cases import default_fixture_root
from trace_lab.embed_field import EmbedField
from trace_lab.metrics import evaluate
from trace_lab.retrieve import LexicalIndex, expand_query, normalize, query_intent
from trace_lab.sim import HOT_THRESHOLD
from trace_lab.strategies import compile_bundle
from trace_lab.types import GoldCase, GoldRef, TraceNode
from trace_lab.vague_eval import hot_set, load_vague_prompts, prompt_to_case
from trace_lab.vector_index import pick_seed


def bm25_map_scores(query: str, lex: LexicalIndex) -> dict[str, float]:
    return normalize(lex.bm25_scores(expand_query(query)))


def graph_boost_bm25(
    query: str,
    lex: LexicalIndex,
    graph: AstTraceGraph,
    *,
    hops: int = 1,
    boost: float = 0.35,
) -> dict[str, float]:
    """BM25 + reinforce nodes that sit next to other strong BM25 hits.

    Idea: if both `authenticate` and `verify` score, and they are linked,
    both get a bump. Isolated lexical traps (billing mentioning auth) do not
    get reinforced by a neighbor hit, so they stay lower.
    """
    base = bm25_map_scores(query, lex)
    if not base:
        return {}
    # Top lexical islands
    top = {nid for nid, sc in base.items() if sc >= 0.35}
    if len(top) < 2:
        top = {nid for nid, _ in sorted(base.items(), key=lambda kv: -kv[1])[:5]}

    neighbor_hits: dict[str, float] = {nid: 0.0 for nid in base}
    for nid in top:
        frontier = {nid}
        seen = {nid}
        for _ in range(hops):
            nxt: set[str] = set()
            for u in frontier:
                for v, _rel, w in graph.neighbors(u, directed=False):
                    if v in seen:
                        continue
                    seen.add(v)
                    nxt.add(v)
                    if v in top and v != nid:
                        # mutual support between lexical islands
                        neighbor_hits[nid] += w * base.get(v, 0.0)
                        neighbor_hits[v] += w * base.get(nid, 0.0)
            frontier = nxt
            if not frontier:
                break

    out: dict[str, float] = {}
    for nid, sc in base.items():
        out[nid] = sc + boost * neighbor_hits.get(nid, 0.0)
    return normalize(out)


def graph_ppr_bm25(
    query: str,
    lex: LexicalIndex,
    graph: AstTraceGraph,
    *,
    alpha: float = 0.55,
    iters: int = 25,
) -> dict[str, float]:
    """Personalized PageRank seeded by BM25 mass — classic graph+lexical map."""
    base = bm25_map_scores(query, lex)
    ids = list(graph.nodes.keys())
    if not ids:
        return base
    idx = {n: i for i, n in enumerate(ids)}
    n = len(ids)
    # row-stochastic transition on undirected view of calls/uses
    w = np.zeros((n, n), dtype=np.float64)
    for src, edges in graph.out.items():
        i = idx.get(src)
        if i is None:
            continue
        for e in edges:
            if e.relation not in {"calls", "uses", "contains", "called_by"}:
                continue
            j = idx.get(e.target)
            if j is None:
                continue
            w[i, j] += float(e.weight)
            w[j, i] += float(e.weight) * 0.5
    row = w.sum(axis=1, keepdims=True)
    dangling = row[:, 0] <= 0
    row[dangling] = 1.0
    p = w / row
    if dangling.any():
        p[dangling] = 1.0 / n

    pers = np.zeros(n, dtype=np.float64)
    for nid, sc in base.items():
        i = idx.get(nid)
        if i is not None and sc > 0:
            pers[i] = sc
    if pers.sum() <= 0:
        pers[:] = 1.0 / n
    else:
        pers = pers / pers.sum()

    v = pers.copy()
    for _ in range(iters):
        v = (1.0 - alpha) * pers + alpha * (v @ p)
    mx = float(v.max()) or 1.0
    return {ids[i]: float(v[i] / mx) for i in range(n) if v[i] > 1e-8}


def multi_seed_poly(
    query: str,
    scores: dict[str, float],
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex: LexicalIndex,
    poly,
    *,
    top_k: int = 3,
):
    """Map top-k → PolyTrace each → max-merge heatmap."""
    from trace_lab.types import HeatCell, Heatmap

    intent = query_intent(query)
    seeds: list[str] = []
    # reuse pick_seed iteratively by zeroing chosen
    work = dict(scores)
    for _ in range(top_k):
        sid = pick_seed(query, nodes, work, intent=intent)
        if sid is None:
            break
        seeds.append(sid)
        work[sid] = -1.0
    if not seeds:
        return Heatmap(strategy="multi", cells=[]), None, []

    merged: dict[str, float] = {}
    why: dict[str, str] = {}
    for sid in seeds:
        n = nodes[sid]
        case = GoldCase(
            id="m",
            title="m",
            query=query,
            seed=GoldRef(n.file, n.symbol),
            must=[],
            should=[],
            must_not=[],
            gold_rank=[],
        )
        hm = poly(case, nodes, graph, lex)
        for c in hm.cells:
            if c.score > merged.get(c.node_id, 0.0):
                merged[c.node_id] = c.score
                why[c.node_id] = f"map[{n.symbol}]/{c.why}"
    cells = [
        HeatCell(node_id=nid, score=round(sc, 4), why=why.get(nid, "multi"), path=(nid,))
        for nid, sc in sorted(merged.items(), key=lambda kv: -kv[1])
        if sc > 0
    ]
    return Heatmap(strategy="multi", cells=cells), seeds[0], seeds


def run_map_bakeoff(
    fixture: Path | None = None,
    *,
    hot_threshold: float = HOT_THRESHOLD,
    with_real_embeds: bool = True,
) -> dict[str, Any]:
    root = (fixture or default_fixture_root()).resolve()
    prompts = load_vague_prompts(root / "vague_prompts.json")["prompts"]
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=False, with_embed_power=False
    )
    map_lex = LexicalIndex(nodes, include_path=True)
    poly = tracers["polytrace"]

    # Dense field (CodeRank if available)
    field: EmbedField | None = None
    try:
        field = EmbedField(
            nodes,
            cache_path=root / ".embed_cache" / "coderank.jsonl",
            require_real=with_real_embeds,
            quiet=True,
        )
    except Exception as exc:  # noqa: BLE001
        field = None
        dense_err = str(exc)
    else:
        dense_err = None

    arms_spec = [
        "bm25",
        "graph_boost",
        "graph_ppr",
        "bm25_multiseed",
        "graph_ppr_multiseed",
    ]
    if field is not None:
        arms_spec += ["dense", "hybrid", "dense_multiseed"]

    rows: list[dict[str, Any]] = []
    for raw in prompts:
        gold = prompt_to_case(raw)
        intent = query_intent(gold.query)
        score_maps: dict[str, dict[str, float]] = {
            "bm25": bm25_map_scores(gold.query, map_lex),
            "graph_boost": graph_boost_bm25(gold.query, map_lex, graph),
            "graph_ppr": graph_ppr_bm25(gold.query, map_lex, graph),
        }
        if field is not None:
            dn = normalize(field.affinities(gold.query))
            bm = score_maps["bm25"]
            score_maps["dense"] = dn
            score_maps["hybrid"] = {
                nid: 0.45 * bm.get(nid, 0.0) + 0.55 * dn.get(nid, 0.0)
                for nid in set(bm) | set(dn)
            }

        arm_out: dict[str, Any] = {}
        for name in arms_spec:
            if name.endswith("_multiseed"):
                base = name.replace("_multiseed", "")
                sm = score_maps.get(base) or score_maps["bm25"]
                if base == "dense" and field is None:
                    continue
                if base == "graph_ppr":
                    sm = score_maps["graph_ppr"]
                hm, seed, seeds = multi_seed_poly(
                    gold.query, sm, nodes, graph, lex, poly, top_k=3
                )
            else:
                sm = score_maps[name]
                seed = pick_seed(gold.query, nodes, sm, intent=intent)
                seeds = [seed] if seed else []
                if seed is None or seed not in nodes:
                    arm_out[name] = _empty(gold)
                    continue
                n = nodes[seed]
                case = GoldCase(
                    id=gold.id,
                    title=gold.title,
                    query=gold.query,
                    seed=GoldRef(n.file, n.symbol),
                    must=gold.must,
                    should=gold.should,
                    must_not=gold.must_not,
                    gold_rank=[],
                )
                hm = poly(case, nodes, graph, lex)

            met = evaluate(hm, gold, nodes, hot_threshold=hot_threshold)
            arm_out[name] = {
                "seed": seed,
                "seeds": seeds,
                "seed_ok": bool(
                    seed
                    and (
                        seed == gold.seed.id
                        or seed in gold.must_ids
                        or seed in gold.should_ids
                    )
                ),
                "seed_exact": seed == gold.seed.id,
                "f1": met.f1,
                "recall_must": met.recall_must,
                "precision_hot": met.precision_hot,
                "false_negatives": met.false_negatives,
                "false_positives_forbidden": met.false_positives_forbidden,
                "hot": sorted(hot_set(hm, hot_threshold)),
            }

        rows.append(
            {
                "id": gold.id,
                "family": str(raw.get("family") or ""),
                "prompt": gold.query,
                "gold_seed": gold.seed.id,
                "arms": arm_out,
            }
        )

    summary = _summarize(rows, arms_spec)
    return {
        "fixture": str(root),
        "n_prompts": len(rows),
        "dense_backend": None if field is None else field.backend,
        "dense_error": dense_err,
        "summary": summary,
        "prompts": rows,
    }


def _empty(gold: GoldCase) -> dict[str, Any]:
    return {
        "seed": None,
        "seeds": [],
        "seed_ok": False,
        "seed_exact": False,
        "f1": 0.0,
        "recall_must": 0.0,
        "precision_hot": 0.0,
        "false_negatives": sorted(gold.must_ids),
        "false_positives_forbidden": [],
        "hot": [],
    }


def _summarize(rows: list[dict[str, Any]], arms: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name in arms:
        present = [r for r in rows if name in r["arms"]]
        if not present:
            continue
        f1s = [r["arms"][name]["f1"] for r in present]
        recs = [r["arms"][name]["recall_must"] for r in present]
        out.append(
            {
                "arm": name,
                "mean_f1": round(sum(f1s) / len(f1s), 4),
                "mean_recall_must": round(sum(recs) / len(recs), 4),
                "seed_ok": sum(1 for r in present if r["arms"][name].get("seed_ok")),
                "seed_exact": sum(1 for r in present if r["arms"][name].get("seed_exact")),
                "n": len(present),
                "sum_fn": sum(len(r["arms"][name]["false_negatives"]) for r in present),
                "sum_forbidden_fp": sum(
                    len(r["arms"][name]["false_positives_forbidden"]) for r in present
                ),
            }
        )
    out.sort(key=lambda r: (-r["mean_f1"], -r["mean_recall_must"]))
    return out


def format_map_table(report: dict[str, Any]) -> str:
    lines = [
        f"map-bakeoff  prompts={report['n_prompts']}  dense={report.get('dense_backend')}",
        f"{'arm':22} {'F1':>7} {'recall':>7} {'seedOK':>7} {'exact':>6} {'FN':>4} {'FP!':>4}",
        "-" * 62,
    ]
    for row in report["summary"]:
        lines.append(
            f"{row['arm']:22} {row['mean_f1']:7.3f} {row['mean_recall_must']:7.3f} "
            f"{row['seed_ok']:7d} {row['seed_exact']:6d} {row['sum_fn']:4d} {row['sum_forbidden_fp']:4d}"
        )
    return "\n".join(lines)


def dump_map_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")

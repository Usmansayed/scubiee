"""Run gold cases × tracing strategies and emit a comparison report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trace_lab.cases import default_fixture_root, load_cases
from trace_lab.metrics import evaluate
from trace_lab.strategies import compile_bundle
from trace_lab.types import GoldCase, Heatmap, TraceNode

HOT_THRESHOLD = 0.45


def run_case(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph,
    lex,
    tracers,
    *,
    hot_threshold: float = HOT_THRESHOLD,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    heatmaps: dict[str, list[dict[str, Any]]] = {}
    for name, fn in tracers.items():
        hm: Heatmap = fn(case, nodes, graph, lex)
        met = evaluate(hm, case, nodes, hot_threshold=hot_threshold)
        rows.append(met.as_dict())
        heatmaps[name] = [
            {
                "id": c.node_id,
                "score": c.score,
                "why": c.why,
                "path": list(c.path),
            }
            for c in hm.cells[:16]
        ]
    return {
        "case": case.id,
        "title": case.title,
        "query": case.query,
        "seed": case.seed.id,
        "metrics": rows,
        "heatmaps": heatmaps,
    }


def run_sim(
    fixture: Path | None = None,
    *,
    cache_root: Path | None = None,
    with_graphify: bool = True,
    hot_threshold: float = HOT_THRESHOLD,
) -> dict[str, Any]:
    root = (fixture or default_fixture_root()).resolve()
    cases = load_cases(root / "cases")
    nodes, graph, lex, tracers = compile_bundle(
        root, cache_root=cache_root, with_graphify=with_graphify
    )
    results = [
        run_case(c, nodes, graph, lex, tracers, hot_threshold=hot_threshold)
        for c in cases
    ]
    summary = _summarize(results)
    return {
        "fixture": str(root),
        "n_nodes": len(nodes),
        "n_edges": len(graph.edges),
        "strategies": list(tracers),
        "hot_threshold": hot_threshold,
        "summary": summary,
        "cases": results,
    }


def _summarize(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[str, list[dict[str, Any]]] = {}
    for case in results:
        for row in case["metrics"]:
            by.setdefault(row["strategy"], []).append(row)
    out: list[dict[str, Any]] = []
    for name, rows in by.items():
        n = max(len(rows), 1)
        out.append(
            {
                "strategy": name,
                "mean_recall_must": round(sum(r["recall_must"] for r in rows) / n, 4),
                "mean_precision_hot": round(sum(r["precision_hot"] for r in rows) / n, 4),
                "mean_f1": round(sum(r["f1"] for r in rows) / n, 4),
                "mean_ndcg": round(sum(r["ndcg"] for r in rows) / n, 4),
                "mean_token_precision": round(sum(r["token_precision"] for r in rows) / n, 4),
                "sum_inversions": sum(r["inversions"] for r in rows),
                "sum_forbidden_fp": sum(len(r["false_positives_forbidden"]) for r in rows),
                "sum_fn": sum(len(r["false_negatives"]) for r in rows),
            }
        )
    out.sort(key=lambda r: (-r["mean_f1"], -r["mean_recall_must"]))
    return out


def format_table(report: dict[str, Any]) -> str:
    lines = [
        f"trace-lab  nodes={report['n_nodes']}  edges={report['n_edges']}",
        f"{'strategy':22} {'F1':>7} {'recall':>7} {'prec':>7} {'nDCG':>7} {'tokP':>7} {'inv':>5} {'FP!':>4} {'FN':>4}",
        "-" * 78,
    ]
    for row in report["summary"]:
        lines.append(
            f"{row['strategy']:22} {row['mean_f1']:7.3f} {row['mean_recall_must']:7.3f} "
            f"{row['mean_precision_hot']:7.3f} {row['mean_ndcg']:7.3f} {row['mean_token_precision']:7.3f} "
            f"{row['sum_inversions']:5d} {row['sum_forbidden_fp']:4d} {row['sum_fn']:4d}"
        )
    return "\n".join(lines)


def dump_report(report: dict[str, Any], path: Path) -> None:
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")

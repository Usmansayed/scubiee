"""Hard correctness verification + ranking scoreboard.

Compares PolyTrace / PolyEmbed / SemanticTrace / EmbedPower on a board.
Reports hard-correct AND soft metrics (recall, precision, F1, nDCG, inversions).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trace_lab.cases import default_fixture_root
from trace_lab.metrics import evaluate
from trace_lab.sim import HOT_THRESHOLD
from trace_lab.strategies import compile_bundle
from trace_lab.vague_eval import hot_set, prompt_to_case


def load_verify_board(path: Path | None = None) -> dict[str, Any]:
    root = default_fixture_root()
    path = path or (root / "verify_board.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _correct(hot: set[str], gold) -> dict[str, Any]:
    missing = sorted(gold.must_ids - hot)
    forbidden = sorted(hot & gold.must_not_ids)
    return {
        "correct": not missing and not forbidden,
        "missing_must": missing,
        "forbidden_hot": forbidden,
        "extra_hot": sorted(hot - gold.relevant_ids - gold.must_not_ids),
    }


def _must_at_k(ranked: list[str], must: set[str], k: int) -> float:
    if not must:
        return 1.0
    hit = set(ranked[:k]) & must
    return len(hit) / len(must)


def run_verify(
    fixture: Path | None = None,
    *,
    board_name: str = "verify_board.json",
    hot_threshold: float = HOT_THRESHOLD,
    require_real_embeds: bool = False,
) -> dict[str, Any]:
    root = (fixture or default_fixture_root()).resolve()
    board = load_verify_board(root / board_name)
    cases = board["cases"]
    nodes, graph, lex, tracers = compile_bundle(
        root,
        with_graphify=True,
        with_embed_power=True,
        require_real_embeds=require_real_embeds,
    )
    from trace_lab.embed_field import EmbedField
    from trace_lab.graphify_layer import build_graphify_graph
    from trace_lab.lsp_index import build_lsp_index
    from trace_lab.poly_embed import bind_poly_embed
    from trace_lab.recall_belt import bind_recall_belt, bind_recall_fuse
    from trace_lab.semantic_trace import bind_semantic_trace

    lsp = build_lsp_index(root, nodes, graph)
    field = EmbedField(
        nodes,
        cache_path=root / ".embed_cache" / "coderank.jsonl",
        require_real=require_real_embeds,
        quiet=True,
    )
    tracers.setdefault("poly_embed", bind_poly_embed(lsp, field))
    tracers.setdefault("semantic_trace", bind_semantic_trace(lsp, field))
    try:
        gfy = build_graphify_graph(root, nodes)
    except Exception:  # noqa: BLE001
        gfy = None
    tracers["recall_belt"] = bind_recall_belt(lsp, field, gfy)
    tracers["recall_fuse"] = bind_recall_fuse(lsp, field, tracers["polytrace"], gfy)

    arm_names = ["polytrace", "poly_embed", "semantic_trace", "recall_belt", "recall_fuse"]
    if "embed_power_oracle" in tracers:
        arm_names.append("embed_power_oracle")

    rows: list[dict[str, Any]] = []
    for raw in cases:
        gold = prompt_to_case(raw)
        arm_out: dict[str, Any] = {}
        for name in arm_names:
            fn = tracers[name]
            hm = fn(gold, nodes, graph, lex)
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
                "inversions": met.inversions,
                "must_at_5": round(_must_at_k(ranked, gold.must_ids, 5), 4),
                "must_at_10": round(_must_at_k(ranked, gold.must_ids, 10), 4),
                "hot": sorted(hot),
                "heatmap": [
                    {"id": c.node_id, "score": c.score, "why": c.why}
                    for c in hm.cells
                    if c.score >= hot_threshold
                ],
            }
        rows.append(
            {
                "id": gold.id,
                "family": str(raw.get("family") or ""),
                "prompt": gold.query,
                "seed": gold.seed.id,
                "arms": arm_out,
            }
        )

    summary: dict[str, Any] = {}
    soft_keys = (
        "f1",
        "recall_must",
        "precision_hot",
        "ndcg",
        "must_at_5",
        "must_at_10",
    )
    for name in arm_names:
        n_ok = sum(1 for r in rows if r["arms"][name]["correct"])
        soft = {
            k: round(sum(r["arms"][name][k] for r in rows) / max(len(rows), 1), 4)
            for k in soft_keys
        }
        inv = sum(r["arms"][name]["inversions"] for r in rows)
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
            "total_inversions": inv,
            "failed_ids": [r["id"] for r in rows if not r["arms"][name]["correct"]],
        }

    return {
        "fixture": str(root),
        "board": board_name,
        "n_cases": len(rows),
        "definition": "correct <=> all must are hot AND no must_not is hot",
        "summary": summary,
        "cases": rows,
    }


def format_verify_table(report: dict[str, Any]) -> str:
    lines = [
        f"verify-board  cases={report['n_cases']}  board={report.get('board', '?')}",
        f"hard: {report['definition']}",
        (
            f"{'arm':22} {'hard':>8} {'acc':>6} {'rec':>6} {'prec':>6} "
            f"{'F1':>6} {'nDCG':>6} {'@5':>5} {'@10':>5}  inv"
        ),
        "-" * 88,
    ]
    for name, row in report["summary"].items():
        lines.append(
            f"{name:22} {row['correct']:3d}/{row['n']:<3d} {row['accuracy']:6.3f} "
            f"{row['mean_recall_must']:6.3f} {row['mean_precision_hot']:6.3f} "
            f"{row['mean_f1']:6.3f} {row['mean_ndcg']:6.3f} "
            f"{row['mean_must_at_5']:5.3f} {row['mean_must_at_10']:5.3f}  "
            f"{row['total_inversions']}"
        )
    lines.append("")
    arms = list(report["summary"].keys())
    hdr = f"{'id':4} {'family':14} " + " ".join(f"{a[:4]:>5}" for a in arms) + "  prompt"
    lines.append(hdr)
    lines.append("-" * 88)
    for r in report["cases"]:
        marks = []
        for name in arms:
            if name not in r["arms"]:
                marks.append("  -  ")
            else:
                marks.append(" OK " if r["arms"][name]["correct"] else " FAIL")
        lines.append(
            f"{r['id']:4} {r['family'][:14]:14} "
            + " ".join(marks)
            + f"  {r['prompt'][:36]}"
        )
    return "\n".join(lines)


def dump_verify_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")


"""Rich-context OOD board: queries that need long chains / more heatmap context."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from trace_lab.cases import default_fixture_root
from trace_lab.metrics import evaluate
from trace_lab.prod_eval import _case_with_query_seed, _correct
from trace_lab.sim import HOT_THRESHOLD
from trace_lab.strategies import compile_bundle
from trace_lab.vague_eval import hot_set, prompt_to_case
from trace_lab.verify_board import _must_at_k

BOARD = "verify_ood_v8_rich.json"
ARMS = (
    "composite_v1",
    "semantic_tracer_fuse",
    "poly_embed",
    "hyb_fuse_demote_noise_plus",
    "hyb_fuse_demote_strict",
    "hyb_comp_demote_noise_plus",
)
CANDIDATE = "hyb_fuse_demote_noise_plus"


def run(*, hot: float = HOT_THRESHOLD) -> dict[str, Any]:
    t0 = time.time()
    root = default_fixture_root().resolve()
    board = json.loads((root / BOARD).read_text(encoding="utf-8"))
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=True, with_embed_power=True, require_real_embeds=False
    )
    rows = []
    for raw in board["cases"]:
        gold = prompt_to_case(raw)
        if gold.seed.id not in nodes:
            continue
        user_prompt = str(raw.get("prompt") or gold.query)
        n_must = len(gold.must_ids)
        arm_out: dict[str, Any] = {}
        for name in ARMS:
            if name not in tracers:
                continue
            try:
                hm = tracers[name](
                    _case_with_query_seed(gold, user_prompt, gold.seed),
                    nodes,
                    graph,
                    lex,
                )
            except Exception as exc:  # noqa: BLE001
                arm_out[name] = {
                    "correct": False,
                    "f1": 0.0,
                    "recall_must": 0.0,
                    "precision_hot": 0.0,
                    "must_at_10": 0.0,
                    "n_hot": 0,
                    "error": str(exc)[:140],
                }
                continue
            met = evaluate(hm, gold, nodes, hot_threshold=hot)
            ids = hot_set(hm, hot)
            ver = _correct(ids, gold)
            arm_out[name] = {
                **ver,
                "f1": met.f1,
                "recall_must": met.recall_must,
                "precision_hot": met.precision_hot,
                "must_at_10": round(_must_at_k(hm.ranked_ids(), gold.must_ids, 10), 4),
                "n_hot": len(ids),
                "n_must": n_must,
            }
        rows.append({
            "id": gold.id,
            "family": raw.get("family"),
            "n_must": n_must,
            "arms": arm_out,
        })

    summary = {}
    for name in ARMS:
        present = [r for r in rows if name in r["arms"] and "error" not in r["arms"][name]]
        if not present:
            continue
        n_ok = sum(1 for r in present if r["arms"][name]["correct"])
        soft = {
            k: round(sum(r["arms"][name][k] for r in present) / max(len(present), 1), 4)
            for k in ("f1", "recall_must", "precision_hot", "must_at_10", "n_hot")
        }
        # rich-context stress: cases with >=5 must nodes
        rich = [r for r in present if r["n_must"] >= 5]
        rich_ok = sum(1 for r in rich if r["arms"][name]["correct"])
        rich_must = (
            round(sum(r["arms"][name]["recall_must"] for r in rich) / max(len(rich), 1), 4)
            if rich else None
        )
        summary[name] = {
            "correct": n_ok,
            "n": len(present),
            "accuracy": round(n_ok / max(len(present), 1), 4),
            "mean_f1": soft["f1"],
            "mean_recall_must": soft["recall_must"],
            "mean_precision_hot": soft["precision_hot"],
            "mean_must_at_10": soft["must_at_10"],
            "mean_n_hot": soft["n_hot"],
            "rich_n": len(rich),
            "rich_accuracy": round(rich_ok / max(len(rich), 1), 4) if rich else None,
            "rich_must": rich_must,
            "failed_ids": [r["id"] for r in present if not r["arms"][name]["correct"]],
            "failed_rich": [r["id"] for r in rich if not r["arms"][name]["correct"]],
        }

    base = summary.get("composite_v1", {})
    cand = summary.get(CANDIDATE, {})
    ok_rich = (
        cand
        and base
        and cand["mean_recall_must"] >= base["mean_recall_must"] - 0.02
        and cand.get("rich_must", 0) is not None
        and cand["rich_must"] >= (base.get("rich_must") or 0) - 0.02
        and cand["accuracy"] >= base["accuracy"] - 0.05
    )
    return {
        "elapsed_s": round(time.time() - t0, 2),
        "board": BOARD,
        "candidate": CANDIDATE,
        "summary": summary,
        "rows": rows,
        "rich_context_ok": ok_rich,
        "delta_vs_composite": {
            "accuracy": round(cand.get("accuracy", 0) - base.get("accuracy", 0), 4),
            "f1": round(cand.get("mean_f1", 0) - base.get("mean_f1", 0), 4),
            "must": round(cand.get("mean_recall_must", 0) - base.get("mean_recall_must", 0), 4),
            "rich_acc": round(
                (cand.get("rich_accuracy") or 0) - (base.get("rich_accuracy") or 0), 4
            ),
            "rich_must": round((cand.get("rich_must") or 0) - (base.get("rich_must") or 0), 4),
        },
    }


def write_report(result: dict[str, Any]) -> Path:
    docs = Path("docs/superpowers/plans")
    docs.mkdir(parents=True, exist_ok=True)
    jp = docs / "2026-09-06-rich-context-v8.json"
    mp = docs / "2026-09-06-rich-context-v8.md"
    slim = {k: v for k, v in result.items() if k != "rows"}
    # keep failed case detail without full rows
    jp.write_text(json.dumps({**slim, "case_fails": {
        name: result["summary"][name]["failed_ids"]
        for name in result["summary"]
    }}, indent=2), encoding="utf-8")

    lines = [
        "# Rich-context OOD board v8",
        "",
        "Queries that **need more context**: long E2E must chains, vague prompts, deep cross-module hops.",
        "",
        f"Candidate: `{CANDIDATE}` · elapsed {result['elapsed_s']}s · **rich_context_ok:** `{result['rich_context_ok']}`",
        "",
        f"Delta vs composite: {result['delta_vs_composite']}",
        "",
        "| Arm | Acc | F1 | Must | Must@10 | n_hot | Rich Acc | Rich Must | Failed |",
        "|-----|-----|----|------|---------|-------|----------|-----------|--------|",
    ]
    ranked = sorted(
        result["summary"].keys(),
        key=lambda n: (
            result["summary"][n]["mean_recall_must"],
            result["summary"][n]["accuracy"],
            result["summary"][n]["mean_f1"],
        ),
        reverse=True,
    )
    for name in ranked:
        st = result["summary"][name]
        fails = ",".join(st["failed_ids"][:8]) or "—"
        lines.append(
            f"| `{name}` | {st['accuracy']:.4f} | {st['mean_f1']:.4f} | {st['mean_recall_must']:.4f} | "
            f"{st['mean_must_at_10']:.4f} | {st['mean_n_hot']:.1f} | {st['rich_accuracy']} | "
            f"{st['rich_must']} | {fails} |"
        )
    lines += ["", "## Per-case must recall (candidate vs composite)", ""]
    lines.append("| Case | n_must | composite must | candidate must | cand correct |")
    lines.append("|------|--------|----------------|----------------|--------------|")
    for r in result["rows"]:
        b = r["arms"].get("composite_v1", {})
        c = r["arms"].get(CANDIDATE, {})
        lines.append(
            f"| `{r['id']}` | {r['n_must']} | {b.get('recall_must', 0):.2f} | "
            f"{c.get('recall_must', 0):.2f} | {c.get('correct', False)} |"
        )
    mp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mp


if __name__ == "__main__":
    result = run()
    path = write_report(result)
    print(json.dumps({
        "rich_context_ok": result["rich_context_ok"],
        "delta": result["delta_vs_composite"],
        "candidate": result["summary"].get(CANDIDATE),
        "composite_v1": result["summary"].get("composite_v1"),
        "report": str(path),
    }, indent=2))

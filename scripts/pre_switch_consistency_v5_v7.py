"""Pre-switch consistency: candidate vs composite on 3 NEW hard boards (v5/v6/v7)."""

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

BOARDS = ("verify_ood_v5.json", "verify_ood_v6.json", "verify_ood_v7.json")
ARMS = (
    "composite_v1",
    "semantic_tracer_fuse",
    "poly_embed",
    "hyb_fuse_demote_noise_plus",
    "hyb_comp_demote_noise_plus",
)
CANDIDATE = "hyb_fuse_demote_noise_plus"


def _eval_board(board_name: str, nodes, graph, lex, tracers, *, hot: float) -> dict[str, Any]:
    root = default_fixture_root().resolve()
    board = json.loads((root / board_name).read_text(encoding="utf-8"))
    rows = []
    for raw in board["cases"]:
        gold = prompt_to_case(raw)
        if gold.seed.id not in nodes:
            continue
        user_prompt = str(raw.get("prompt") or gold.query)
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
                arm_out[name] = {"correct": False, "f1": 0.0, "recall_must": 0.0,
                                 "precision_hot": 0.0, "must_at_10": 0.0, "error": str(exc)[:120]}
                continue
            met = evaluate(hm, gold, nodes, hot_threshold=hot)
            hot_ids = hot_set(hm, hot)
            ver = _correct(hot_ids, gold)
            arm_out[name] = {
                **ver,
                "f1": met.f1,
                "recall_must": met.recall_must,
                "precision_hot": met.precision_hot,
                "must_at_10": round(_must_at_k(hm.ranked_ids(), gold.must_ids, 10), 4),
            }
        rows.append({"id": gold.id, "family": raw.get("family"), "arms": arm_out})

    summary = {}
    for name in ARMS:
        present = [r for r in rows if name in r["arms"] and "error" not in r["arms"][name]]
        if not present:
            continue
        n_ok = sum(1 for r in present if r["arms"][name]["correct"])
        soft = {
            k: round(sum(r["arms"][name][k] for r in present) / max(len(present), 1), 4)
            for k in ("f1", "recall_must", "precision_hot", "must_at_10")
        }
        summary[name] = {
            "correct": n_ok,
            "n": len(present),
            "accuracy": round(n_ok / max(len(present), 1), 4),
            "mean_f1": soft["f1"],
            "mean_recall_must": soft["recall_must"],
            "mean_precision_hot": soft["precision_hot"],
            "mean_must_at_10": soft["must_at_10"],
            "failed_ids": [r["id"] for r in present if not r["arms"][name]["correct"]],
        }
    return {"board": board_name, "n_cases": len(rows), "summary": summary, "rows": rows}


def run(*, hot: float = HOT_THRESHOLD) -> dict[str, Any]:
    t0 = time.time()
    root = default_fixture_root().resolve()
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=True, with_embed_power=True, require_real_embeds=False
    )
    per = [_eval_board(b, nodes, graph, lex, tracers, hot=hot) for b in BOARDS]

    agg: dict[str, dict[str, float]] = {}
    for name in ARMS:
        vals = [pb["summary"][name] for pb in per if name in pb["summary"]]
        if not vals:
            continue
        n = len(vals)
        agg[name] = {
            "mean_accuracy": round(sum(v["accuracy"] for v in vals) / n, 4),
            "mean_f1": round(sum(v["mean_f1"] for v in vals) / n, 4),
            "mean_must": round(sum(v["mean_recall_must"] for v in vals) / n, 4),
            "mean_prec": round(sum(v["mean_precision_hot"] for v in vals) / n, 4),
            "min_accuracy": round(min(v["accuracy"] for v in vals), 4),
            "min_f1": round(min(v["mean_f1"] for v in vals), 4),
            "boards": n,
        }

    base = agg["composite_v1"]
    cand = agg[CANDIDATE]
    board_wins = 0
    regressions = []
    for pb in per:
        b = pb["summary"]["composite_v1"]
        c = pb["summary"][CANDIDATE]
        better = (
            (c["accuracy"] > b["accuracy"] + 0.01)
            or (c["accuracy"] >= b["accuracy"] and c["mean_f1"] > b["mean_f1"] + 0.005)
        )
        if better:
            board_wins += 1
        # consistency: no hard collapse
        if c["accuracy"] < b["accuracy"] - 0.05 or c["mean_recall_must"] < b["mean_recall_must"] - 0.05:
            regressions.append(pb["board"])

    consistent = (
        board_wins >= 2
        and not regressions
        and cand["mean_must"] >= base["mean_must"] - 0.03
        and cand["mean_accuracy"] >= base["mean_accuracy"] - 0.01
        and (
            cand["mean_accuracy"] >= base["mean_accuracy"] + 0.02
            or cand["mean_f1"] >= base["mean_f1"] + 0.02
        )
    )
    return {
        "elapsed_s": round(time.time() - t0, 2),
        "boards": BOARDS,
        "candidate": CANDIDATE,
        "aggregate": agg,
        "per_board": [{k: v for k, v in pb.items() if k != "rows"} for pb in per],
        "board_wins": board_wins,
        "regressions": regressions,
        "consistent": consistent,
        "go_switch": consistent,
    }


def write_report(result: dict[str, Any]) -> Path:
    docs = Path("docs/superpowers/plans")
    docs.mkdir(parents=True, exist_ok=True)
    jp = docs / "2026-09-06-pre-switch-consistency-v5-v7.json"
    mp = docs / "2026-09-06-pre-switch-consistency-v5-v7.md"
    jp.write_text(json.dumps(result, indent=2), encoding="utf-8")
    base = result["aggregate"]["composite_v1"]
    cand = result["aggregate"][CANDIDATE]
    lines = [
        "# Pre-switch consistency (NEW boards v5/v6/v7)",
        "",
        f"Candidate: `{CANDIDATE}` · elapsed {result['elapsed_s']}s",
        "",
        f"**Consistent / go_switch:** `{result['consistent']}` · board wins {result['board_wins']}/3 · regressions {result['regressions'] or 'none'}",
        "",
        "## Aggregate",
        "",
        "| Arm | Acc | F1 | Must | Prec | min Acc |",
        "|-----|-----|----|------|------|---------|",
    ]
    for name, st in sorted(result["aggregate"].items(), key=lambda kv: (-kv[1]["mean_accuracy"], -kv[1]["mean_f1"])):
        lines.append(
            f"| `{name}` | {st['mean_accuracy']:.4f} | {st['mean_f1']:.4f} | {st['mean_must']:.4f} | "
            f"{st['mean_prec']:.4f} | {st['min_accuracy']:.4f} |"
        )
    lines += [
        "",
        f"Delta vs composite: acc {cand['mean_accuracy'] - base['mean_accuracy']:+.4f}, "
        f"F1 {cand['mean_f1'] - base['mean_f1']:+.4f}, must {cand['mean_must'] - base['mean_must']:+.4f}",
        "",
        "## Per board",
        "",
    ]
    for pb in result["per_board"]:
        lines.append(f"### {pb['board']} (n={pb['n_cases']})")
        lines.append("")
        lines.append("| Arm | Acc | F1 | Must | Failed |")
        lines.append("|-----|-----|----|------|--------|")
        for name in ARMS:
            st = pb["summary"].get(name)
            if not st:
                continue
            fails = ",".join(st["failed_ids"][:6]) or "—"
            lines.append(
                f"| `{name}` | {st['accuracy']:.4f} | {st['mean_f1']:.4f} | "
                f"{st['mean_recall_must']:.4f} | {fails} |"
            )
        lines.append("")
    mp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mp


if __name__ == "__main__":
    result = run()
    path = write_report(result)
    print(json.dumps({
        "go_switch": result["go_switch"],
        "consistent": result["consistent"],
        "board_wins": result["board_wins"],
        "regressions": result["regressions"],
        "candidate": result["aggregate"][CANDIDATE],
        "composite_v1": result["aggregate"]["composite_v1"],
        "report": str(path),
    }, indent=2))

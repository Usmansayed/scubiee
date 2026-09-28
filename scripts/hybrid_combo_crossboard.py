"""Cross-board hybrid combo sweep — anti-overfit (v2 train-ish, v3+v4 holdout).

Winner must improve mean(acc,F1) vs composite_v1 on ≥2 boards and not crash
must recall on the mean.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from trace_lab.cases import default_fixture_root
from trace_lab.metrics import evaluate
from trace_lab.prod_eval import _case_with_query_seed, _correct
from trace_lab.semantic_hybrid import HYBRID_SPECS
from trace_lab.sim import HOT_THRESHOLD
from trace_lab.strategies import compile_bundle
from trace_lab.vague_eval import hot_set, prompt_to_case
from trace_lab.verify_board import _must_at_k

BOARDS = ("verify_ood_v2.json", "verify_ood_v3.json", "verify_ood_v4.json")
BASELINES = (
    "composite_v1",
    "semantic_tracer_fuse",
    "semantic_tracer_v1",
    "poly_embed",
)


def _eval_board(
    board_name: str,
    nodes,
    graph,
    lex,
    tracers,
    arm_names: list[str],
    *,
    hot: float,
) -> dict[str, Any]:
    root = default_fixture_root().resolve()
    board = json.loads((root / board_name).read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    for raw in board["cases"]:
        gold = prompt_to_case(raw)
        if gold.seed.id not in nodes:
            continue
        user_prompt = str(raw.get("prompt") or gold.query)
        arm_out: dict[str, Any] = {}
        for name in arm_names:
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
                    "error": str(exc)[:160],
                }
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
                "n_hot": len(hot_ids),
            }
        rows.append({"id": gold.id, "family": raw.get("family"), "arms": arm_out})

    summary: dict[str, Any] = {}
    for name in arm_names:
        present = [r for r in rows if name in r["arms"] and "error" not in r["arms"][name]]
        if not present:
            continue
        n_ok = sum(1 for r in present if r["arms"][name]["correct"])
        soft_keys = ("f1", "recall_must", "precision_hot", "must_at_10")
        soft = {
            k: round(sum(r["arms"][name][k] for r in present) / max(len(present), 1), 4)
            for k in soft_keys
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
    return {"board": board_name, "summary": summary, "n_cases": len(rows)}


def run_sweep(*, hot: float = HOT_THRESHOLD) -> dict[str, Any]:
    t0 = time.time()
    root = default_fixture_root().resolve()
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=True, with_embed_power=True, require_real_embeds=False
    )
    hybrid_names = [s[0] for s in HYBRID_SPECS if s[0] in tracers]
    arm_names = [a for a in BASELINES if a in tracers] + hybrid_names

    per_board = []
    for b in BOARDS:
        per_board.append(_eval_board(b, nodes, graph, lex, tracers, arm_names, hot=hot))

    # Aggregate across boards
    agg: dict[str, dict[str, float]] = {}
    for name in arm_names:
        accs, f1s, musts, precs = [], [], [], []
        for pb in per_board:
            st = pb["summary"].get(name)
            if not st:
                continue
            accs.append(st["accuracy"])
            f1s.append(st["mean_f1"])
            musts.append(st["mean_recall_must"])
            precs.append(st["mean_precision_hot"])
        if not accs:
            continue
        n = len(accs)
        agg[name] = {
            "mean_accuracy": round(sum(accs) / n, 4),
            "mean_f1": round(sum(f1s) / n, 4),
            "mean_must": round(sum(musts) / n, 4),
            "mean_prec": round(sum(precs) / n, 4),
            "boards": n,
            "min_accuracy": round(min(accs), 4),
            "min_f1": round(min(f1s), 4),
        }

    base = agg.get("composite_v1", {})

    def beats_composite(name: str) -> bool:
        if name == "composite_v1" or not base or name not in agg:
            return False
        st = agg[name]
        # Acc win with flat F1, or F1 win with near-flat acc; must stable.
        f1_win = st["mean_f1"] >= base["mean_f1"] + 0.03 and st["mean_accuracy"] >= base["mean_accuracy"] - 0.03
        acc_win = st["mean_accuracy"] >= base["mean_accuracy"] + 0.03 and st["mean_f1"] >= base["mean_f1"] - 0.01
        return (f1_win or acc_win) and st["mean_must"] >= base["mean_must"] - 0.03

    def boards_win(name: str) -> int:
        """How many boards beat composite on (acc and F1)."""
        wins = 0
        for pb in per_board:
            b = pb["summary"].get("composite_v1")
            s = pb["summary"].get(name)
            if not b or not s:
                continue
            if s["accuracy"] >= b["accuracy"] and s["mean_f1"] > b["mean_f1"] + 0.005:
                wins += 1
            elif s["accuracy"] > b["accuracy"] + 0.02:
                wins += 1
        return wins

    ranked = sorted(
        agg.keys(),
        key=lambda n: (
            boards_win(n),
            agg[n]["mean_f1"],
            agg[n]["mean_accuracy"],
            agg[n]["mean_must"],
        ),
        reverse=True,
    )

    generalizers = [
        n
        for n in ranked
        if n != "composite_v1" and boards_win(n) >= 2 and beats_composite(n)
    ]
    # Soft generalizers: win ≥2 boards even if mean delta smaller
    soft = [
        n for n in ranked if n != "composite_v1" and boards_win(n) >= 2 and n not in generalizers
    ]

    return {
        "elapsed_s": round(time.time() - t0, 2),
        "boards": BOARDS,
        "arms": arm_names,
        "per_board": per_board,
        "aggregate": agg,
        "ranked": ranked,
        "board_wins": {n: boards_win(n) for n in ranked},
        "generalizers": generalizers,
        "soft_generalizers": soft,
        "best": ranked[0] if ranked else None,
    }


def write_report(result: dict[str, Any]) -> tuple[Path, Path]:
    docs = Path("docs/superpowers/plans")
    docs.mkdir(parents=True, exist_ok=True)
    json_path = docs / "2026-09-06-hybrid-combo-crossboard.json"
    md_path = docs / "2026-09-06-hybrid-combo-crossboard.md"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    lines = [
        "# Hybrid combo cross-board sweep",
        "",
        f"Elapsed: {result['elapsed_s']}s · boards: {', '.join(result['boards'])}",
        "",
        "**Anti-overfit rule:** win on ≥2 of v2/v3/v4; do not crown v2-only winners.",
        "",
        "## Aggregate (mean across boards)",
        "",
        "| Arm | Acc | F1 | Must | Prec | Board wins |",
        "|-----|-----|----|------|------|------------|",
    ]
    agg = result["aggregate"]
    wins = result["board_wins"]
    for name in result["ranked"]:
        st = agg[name]
        lines.append(
            f"| `{name}` | {st['mean_accuracy']:.4f} | {st['mean_f1']:.4f} | "
            f"{st['mean_must']:.4f} | {st['mean_prec']:.4f} | {wins.get(name, 0)} |"
        )
    lines += [
        "",
        f"**Hard generalizers:** {result['generalizers'] or '(none)'}",
        f"**Soft (≥2 board wins):** {result['soft_generalizers'] or '(none)'}",
        f"**Best by rank key:** `{result['best']}`",
        "",
        "## Per board",
        "",
    ]
    for pb in result["per_board"]:
        lines.append(f"### {pb['board']} (n={pb['n_cases']})")
        lines.append("")
        lines.append("| Arm | Acc | F1 | Must |")
        lines.append("|-----|-----|----|------|")
        ranked_b = sorted(
            pb["summary"].keys(),
            key=lambda n: (
                pb["summary"][n]["accuracy"],
                pb["summary"][n]["mean_f1"],
                pb["summary"][n]["mean_recall_must"],
            ),
            reverse=True,
        )
        for name in ranked_b[:12]:
            st = pb["summary"][name]
            lines.append(
                f"| `{name}` | {st['accuracy']:.4f} | {st['mean_f1']:.4f} | "
                f"{st['mean_recall_must']:.4f} |"
            )
        lines.append("")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


if __name__ == "__main__":
    result = run_sweep()
    jp, mp = write_report(result)
    print(json.dumps({
        "best": result["best"],
        "generalizers": result["generalizers"],
        "soft_generalizers": result["soft_generalizers"],
        "board_wins": {k: result["board_wins"][k] for k in result["ranked"][:8]},
        "top_agg": {k: result["aggregate"][k] for k in result["ranked"][:8]},
        "report": str(mp),
    }, indent=2))

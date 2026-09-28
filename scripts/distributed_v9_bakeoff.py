"""4 hard distributed multi-file expansion tests (verify_ood_v9_distributed)."""

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

BOARD = "verify_ood_v9_distributed.json"
ARMS = (
    "composite_v1",
    "semantic_tracer_fuse",
    "poly_embed",
    "hyb_fuse_demote_noise_plus",
)
CANDIDATE = "hyb_fuse_demote_noise_plus"


def _n_files(ids: set[str]) -> int:
    return len({i.split("::", 1)[0] for i in ids})


def run(*, hot: float = HOT_THRESHOLD) -> dict[str, Any]:
    t0 = time.time()
    root = default_fixture_root().resolve()
    board = json.loads((root / BOARD).read_text(encoding="utf-8"))
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=True, with_embed_power=True, require_real_embeds=False
    )
    tests: list[dict[str, Any]] = []

    for raw in board["cases"]:
        gold = prompt_to_case(raw)
        if gold.seed.id not in nodes:
            continue
        user_prompt = str(raw.get("prompt") or gold.query)
        must_files = _n_files(gold.must_ids)
        arm_out: dict[str, Any] = {}
        for name in ARMS:
            if name not in tracers:
                continue
            hm = tracers[name](
                _case_with_query_seed(gold, user_prompt, gold.seed),
                nodes,
                graph,
                lex,
            )
            met = evaluate(hm, gold, nodes, hot_threshold=hot)
            ids = hot_set(hm, hot)
            ver = _correct(ids, gold)
            missing = sorted(gold.must_ids - ids)
            arm_out[name] = {
                **ver,
                "f1": met.f1,
                "recall_must": met.recall_must,
                "precision_hot": met.precision_hot,
                "must_at_10": round(_must_at_k(hm.ranked_ids(), gold.must_ids, 10), 4),
                "n_hot": len(ids),
                "n_hot_files": _n_files(ids),
                "missing_must": [m.rsplit("::", 1)[-1] for m in missing],
            }
        tests.append(
            {
                "id": gold.id,
                "family": raw.get("family"),
                "n_must": len(gold.must_ids),
                "n_must_files": must_files,
                "arms": arm_out,
            }
        )

    summary: dict[str, Any] = {}
    for name in ARMS:
        rows = [t for t in tests if name in t["arms"]]
        n_ok = sum(1 for t in rows if t["arms"][name]["correct"])
        soft = {
            k: round(sum(t["arms"][name][k] for t in rows) / max(len(rows), 1), 4)
            for k in ("f1", "recall_must", "precision_hot", "must_at_10", "n_hot", "n_hot_files")
        }
        summary[name] = {
            "correct": n_ok,
            "n": len(rows),
            "accuracy": round(n_ok / max(len(rows), 1), 4),
            **{f"mean_{k}" if not k.startswith("n_") else f"mean_{k}": soft[k] for k in soft},
            "failed": [t["id"] for t in rows if not t["arms"][name]["correct"]],
        }

    return {
        "elapsed_s": round(time.time() - t0, 2),
        "board": BOARD,
        "n_tests": len(tests),
        "tests": tests,
        "summary": summary,
        "candidate_vs_composite": {
            "acc_delta": round(
                summary[CANDIDATE]["accuracy"] - summary["composite_v1"]["accuracy"], 4
            ),
            "must_delta": round(
                summary[CANDIDATE]["mean_recall_must"]
                - summary["composite_v1"]["mean_recall_must"],
                4,
            ),
            "f1_delta": round(
                summary[CANDIDATE]["mean_f1"] - summary["composite_v1"]["mean_f1"], 4
            ),
        },
    }


def write_report(result: dict[str, Any]) -> Path:
    docs = Path("docs/superpowers/plans")
    docs.mkdir(parents=True, exist_ok=True)
    jp = docs / "2026-09-06-distributed-v9.json"
    mp = docs / "2026-09-06-distributed-v9.md"
    jp.write_text(json.dumps(result, indent=2), encoding="utf-8")
    lines = [
        "# 4 hard distributed multi-file expansion tests (v9)",
        "",
        f"Elapsed {result['elapsed_s']}s · each test spans many files (network expansion).",
        "",
        "## Summary",
        "",
        "| Arm | Acc | F1 | Must | Hot files | Failed |",
        "|-----|-----|----|------|-----------|--------|",
    ]
    for name, st in sorted(
        result["summary"].items(),
        key=lambda kv: (-kv[1]["mean_recall_must"], -kv[1]["accuracy"], -kv[1]["mean_f1"]),
    ):
        fails = ",".join(st["failed"]) or "—"
        lines.append(
            f"| `{name}` | {st['accuracy']:.4f} | {st['mean_f1']:.4f} | "
            f"{st['mean_recall_must']:.4f} | {st['mean_n_hot_files']:.1f} | {fails} |"
        )
    lines += ["", f"Delta candidate vs composite: {result['candidate_vs_composite']}", "", "## Per test", ""]
    for t in result["tests"]:
        lines.append(
            f"### `{t['id']}` — {t['family']} (must={t['n_must']} across **{t['n_must_files']} files**)"
        )
        lines.append("")
        lines.append("| Arm | OK | Must | F1 | Hot files | Missing |")
        lines.append("|-----|----|------|----|-----------|---------|")
        for name in ARMS:
            a = t["arms"][name]
            miss = ",".join(a["missing_must"][:8]) or "—"
            lines.append(
                f"| `{name}` | {a['correct']} | {a['recall_must']:.2f} | {a['f1']:.3f} | "
                f"{a['n_hot_files']} | {miss} |"
            )
        lines.append("")
    mp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return mp


if __name__ == "__main__":
    result = run()
    path = write_report(result)
    print(
        json.dumps(
            {
                "n_tests": result["n_tests"],
                "summary": result["summary"],
                "delta": result["candidate_vs_composite"],
                "per_test": {
                    t["id"]: {
                        "files": t["n_must_files"],
                        "cand": t["arms"][CANDIDATE]["correct"],
                        "comp": t["arms"]["composite_v1"]["correct"],
                        "cand_must": t["arms"][CANDIDATE]["recall_must"],
                        "comp_must": t["arms"]["composite_v1"]["recall_must"],
                    }
                    for t in result["tests"]
                },
                "report": str(path),
            },
            indent=2,
        )
    )

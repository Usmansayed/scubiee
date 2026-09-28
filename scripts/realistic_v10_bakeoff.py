"""Realistic agent-input bakeoff: enriched paragraph + seed code chunks + multi-seed merge."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from trace_lab.cases import default_fixture_root
from trace_lab.metrics import evaluate
from trace_lab.prod_eval import _case_with_query_seed, _enrich_query, _merge_heatmaps
from trace_lab.sim import HOT_THRESHOLD
from trace_lab.strategies import compile_bundle
from trace_lab.types import GoldRef
from trace_lab.vague_eval import hot_set, prompt_to_case
from trace_lab.verify_board import _correct, _must_at_k

BOARD = "verify_ood_v10_realistic.json"
ARMS = (
    "composite_v1",
    "semantic_tracer_fuse",
    "poly_embed",
    "hyb_fuse_demote_noise_plus",
)
CANDIDATE = "hyb_fuse_demote_noise_plus"


def _fill_chunks(raw: dict, gold, nodes) -> list[dict[str, Any]]:
    chunks = []
    for ch in list(raw.get("seed_chunks") or []):
        ref = GoldRef(file=ch["file"], symbol=ch["symbol"])
        text = ch.get("text") or (nodes[ref.id].text if ref.id in nodes else "")
        chunks.append({"file": ch["file"], "symbol": ch["symbol"], "text": text})
    if not chunks:
        chunks = [
            {
                "file": gold.seed.file,
                "symbol": gold.seed.symbol,
                "text": nodes[gold.seed.id].text if gold.seed.id in nodes else "",
            }
        ]
    return chunks


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
        chunks = _fill_chunks(raw, gold, nodes)
        enriched = _enrich_query(str(raw["prompt"]), chunks)
        seeds: list[GoldRef] = []
        seen: set[str] = set()
        for ch in chunks:
            s = GoldRef(file=ch["file"], symbol=ch["symbol"])
            if s.id in seen or s.id not in nodes:
                continue
            seen.add(s.id)
            seeds.append(s)
        if not seeds:
            seeds = [gold.seed]

        arm_out: dict[str, Any] = {}
        for name in ARMS:
            if name not in tracers:
                continue
            maps = []
            for s in seeds:
                # Realistic: pass enriched query (paragraph + code anchors).
                # Intent parsers strip anchors via _user_query; embeds keep them.
                sub = _case_with_query_seed(gold, enriched, s)
                maps.append(tracers[name](sub, nodes, graph, lex))
            hm = _merge_heatmaps(maps, strategy=f"{name}+realistic")
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
                "n_seeds": len(seeds),
                "prompt_chars": len(enriched),
                "missing_must": [m.rsplit("::", 1)[-1] for m in sorted(gold.must_ids - ids)],
                "forbidden_hot": [
                    m.rsplit("::", 1)[-1] for m in sorted(ids & gold.must_not_ids)
                ],
            }
        rows.append(
            {
                "id": gold.id,
                "family": raw.get("family"),
                "n_chunks": len(chunks),
                "chunk_ids": [f"{c['file']}::{c['symbol']}" for c in chunks],
                "arms": arm_out,
            }
        )

    summary = {}
    for name in ARMS:
        present = [r for r in rows if name in r["arms"]]
        n_ok = sum(1 for r in present if r["arms"][name]["correct"])
        soft = {
            k: round(sum(r["arms"][name][k] for r in present) / max(len(present), 1), 4)
            for k in ("f1", "recall_must", "precision_hot", "must_at_10", "n_hot")
        }
        summary[name] = {
            "correct": n_ok,
            "n": len(present),
            "accuracy": round(n_ok / max(len(present), 1), 4),
            "mean_f1": soft["f1"],
            "mean_recall_must": soft["recall_must"],
            "mean_precision_hot": soft["precision_hot"],
            "mean_must_at_10": soft["must_at_10"],
            "mean_n_hot": soft["n_hot"],
            "failed": [r["id"] for r in present if not r["arms"][name]["correct"]],
        }

    return {
        "elapsed_s": round(time.time() - t0, 2),
        "board": BOARD,
        "input_style": "enriched_paragraph + seed_code_chunks + multi_seed_merge",
        "summary": summary,
        "rows": rows,
        "delta_vs_composite": {
            "accuracy": round(
                summary[CANDIDATE]["accuracy"] - summary["composite_v1"]["accuracy"], 4
            ),
            "f1": round(
                summary[CANDIDATE]["mean_f1"] - summary["composite_v1"]["mean_f1"], 4
            ),
            "must": round(
                summary[CANDIDATE]["mean_recall_must"]
                - summary["composite_v1"]["mean_recall_must"],
                4,
            ),
        },
    }


def write_report(result: dict[str, Any]) -> Path:
    docs = Path("docs/superpowers/plans")
    docs.mkdir(parents=True, exist_ok=True)
    jp = docs / "2026-09-06-realistic-v10.json"
    mp = docs / "2026-09-06-realistic-v10.md"
    slim = {k: v for k, v in result.items() if k != "rows"}
    jp.write_text(
        json.dumps({**slim, "per_case": [
            {
                "id": r["id"],
                "chunks": r["chunk_ids"],
                "arms": {
                    n: {
                        "correct": a["correct"],
                        "must": a["recall_must"],
                        "f1": a["f1"],
                        "missing": a["missing_must"],
                        "forbidden": a["forbidden_hot"],
                    }
                    for n, a in r["arms"].items()
                },
            }
            for r in result["rows"]
        ]}, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# Realistic agent-input bakeoff (v10)",
        "",
        f"Input: **{result['input_style']}** · elapsed {result['elapsed_s']}s",
        "",
        "Each case = enriched flow paragraph + 1–3 pasted seed bodies; multi-seed heatmaps merged.",
        "",
        f"Delta candidate vs composite: {result['delta_vs_composite']}",
        "",
        "| Arm | Acc | F1 | Must | Prec | Failed |",
        "|-----|-----|----|------|------|--------|",
    ]
    for name, st in sorted(
        result["summary"].items(),
        key=lambda kv: (-kv[1]["accuracy"], -kv[1]["mean_f1"], -kv[1]["mean_recall_must"]),
    ):
        fails = ",".join(st["failed"]) or "—"
        lines.append(
            f"| `{name}` | {st['accuracy']:.4f} | {st['mean_f1']:.4f} | "
            f"{st['mean_recall_must']:.4f} | {st['mean_precision_hot']:.4f} | {fails} |"
        )
    lines += ["", "## Per case", ""]
    for r in result["rows"]:
        lines.append(f"### `{r['id']}` — {r['family']} (chunks: {', '.join(x.split('::')[-1] for x in r['chunk_ids'])})")
        lines.append("")
        lines.append("| Arm | OK | Must | F1 | Missing | Forbidden |")
        lines.append("|-----|----|------|----|---------|-----------|")
        for name in ARMS:
            a = r["arms"][name]
            lines.append(
                f"| `{name}` | {a['correct']} | {a['recall_must']:.2f} | {a['f1']:.3f} | "
                f"{','.join(a['missing_must']) or '—'} | {','.join(a['forbidden_hot']) or '—'} |"
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
                "input": result["input_style"],
                "summary": result["summary"],
                "delta": result["delta_vs_composite"],
                "report": str(path),
            },
            indent=2,
        )
    )

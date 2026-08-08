"""Chunk-unit × text-style matrix for SEIR (experiment only).

Axes:
  chunk_unit: function | class | file
  text style: baseline (mix) | ast_tree | mix_rels

Usage:
  .\\.venv\\Scripts\\python.exe -u scripts\\seir_matrix_bench.py
  .\\.venv\\Scripts\\python.exe -u scripts\\seir_matrix_bench.py --limit-spans 80
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))


def _load_ab():
    path = ROOT / "scripts" / "seir_ab_bench.py"
    spec = importlib.util.spec_from_file_location("seir_ab_bench", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ab = _load_ab()

from conductor.hard_v2_gold import HARD_V2  # noqa: E402
from pipeline.embedder import Embedder  # noqa: E402
from seir.render import MATRIX_ARMS, render  # noqa: E402
from seir.spans import CHUNK_UNITS, iter_python_spans  # noqa: E402

REPO_DEFAULT = ROOT / "testdata" / "frontend-mcp"
OUT_DIR = ROOT / "out" / "seir_matrix"


def main() -> int:
    ap = argparse.ArgumentParser(description="SEIR chunk×text matrix bench")
    ap.add_argument("--repo", default=str(REPO_DEFAULT))
    ap.add_argument("--units", default=",".join(CHUNK_UNITS))
    ap.add_argument("--arms", default=",".join(MATRIX_ARMS))
    ap.add_argument("--max-chars", type=int, default=512)
    ap.add_argument("--limit-spans", type=int, default=0)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--batch", type=int, default=int(os.environ.get("CTX_EMBED_BATCH", "16")))
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"ERROR: missing repo {repo}", flush=True)
        return 2

    units = [u.strip() for u in args.units.split(",") if u.strip()]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    for u in units:
        if u not in CHUNK_UNITS:
            print(f"ERROR: unknown unit {u!r}", flush=True)
            return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    limit = args.limit_spans if args.limit_spans > 0 else None
    graph = ab._load_graph(repo)

    print("[seir-matrix] loading embedder…", flush=True)
    embedder = Embedder(
        model="nomic-ai/CodeRankEmbed",
        cache_path=None,
        batch_size=int(args.batch),
        max_seq_length=512,
    )
    embedder.embed_one("warmup", is_query=True)

    report: dict[str, Any] = {
        "repo": str(repo),
        "config": {
            "max_chars": args.max_chars,
            "units": units,
            "arms": arms,
            "limit_spans": limit,
            "gold": "HARD_V2",
            "gold_n": len(HARD_V2),
            "eval": "dense-only FAISS IP",
        },
        "cells": {},
    }

    for unit in units:
        spans = iter_python_spans(repo, limit=limit, chunk_unit=unit)
        print(f"\n######## CHUNK UNIT={unit} spans={len(spans)} ########", flush=True)
        if not spans:
            report["cells"][unit] = {"error": "no spans"}
            continue
        files = [s.file for s in spans]
        report["cells"][unit] = {"spans": len(spans), "arms": {}}

        for arm in arms:
            key = f"{unit}/{arm}"
            print(f"\n=== CELL {key} ===", flush=True)
            t_render = time.perf_counter()
            texts = [
                render(arm, s, max_chars=args.max_chars, graph=graph) for s in spans
            ]
            render_sec = time.perf_counter() - t_render
            print(
                f"[seir-matrix] rendered avg_chars="
                f"{statistics.mean(len(t) for t in texts):.0f} in {render_sec:.2f}s",
                flush=True,
            )
            ab.OUT_DIR = OUT_DIR / unit
            col, stats = ab._build_collection(arm, texts, files, embedder)
            stats["render_sec"] = round(render_sec, 3)
            quality = ab._eval_dense(col, files, embedder, HARD_V2, top_k=args.top_k)
            print(
                json.dumps(
                    {
                        "stats": {
                            k: stats[k]
                            for k in (
                                "n",
                                "avg_chars",
                                "embed_sec",
                                "collection_bytes",
                            )
                        },
                        "quality": {
                            k: quality[k]
                            for k in (
                                "recall_at_1",
                                "recall_at_5",
                                "recall_at_10",
                                "mrr",
                                "ndcg_at_10",
                                "avg_query_ms",
                                "failure_count",
                            )
                        },
                    },
                    indent=2,
                ),
                flush=True,
            )
            report["cells"][unit]["arms"][arm] = {"stats": stats, "quality": quality}

    flat: list[tuple[str, float, float, float]] = []
    for unit, cell in report["cells"].items():
        for arm, data in (cell.get("arms") or {}).items():
            q = data["quality"]
            s = data["stats"]
            flat.append((f"{unit}/{arm}", q["recall_at_5"], q["mrr"], -s["avg_chars"]))
    flat.sort(key=lambda t: (-t[1], -t[2], -t[3]))
    report["ranked_cells"] = [
        {"cell": c, "recall_at_5": r5, "mrr": mrr, "neg_chars": nc}
        for c, r5, mrr, nc in flat
    ]

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_json = ROOT / "out" / f"seir_matrix_{ts}.json"
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n[seir-matrix] wrote {out_json}", flush=True)
    if flat:
        print(
            f"[seir-matrix] best={flat[0][0]} R@5={flat[0][1]} MRR={flat[0][2]}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""SEIR A/B: same spans, different post-AST embed texts, dense retrieval eval.

Does not change production indexer defaults. Imports CE Embedder + FAISS + HARD_V2.

Usage:
  .\\.venv\\Scripts\\python.exe -u scripts\\seir_ab_bench.py
  .\\.venv\\Scripts\\python.exe -u scripts\\seir_ab_bench.py --limit-spans 80 --arms baseline,ast_tree
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

from conductor.hard_v2_gold import HARD_V2  # noqa: E402
from pipeline.embedder import Embedder  # noqa: E402
from pipeline.vectordb import FaissCollection, CollectionMeta  # noqa: E402
from seir.caps import estimate_tokens  # noqa: E402
from seir.render import ARMS, render  # noqa: E402
from seir.spans import iter_python_spans  # noqa: E402

REPO_DEFAULT = ROOT / "testdata" / "frontend-mcp"
OUT_DIR = ROOT / "out" / "seir_ab"


def _hit(files: list[str], needles: list[str]) -> bool:
    blob = " ".join(f.replace("\\", "/").lower() for f in files)
    return any(n.lower().replace("\\", "/") in blob for n in needles)


def _rank(files: list[str], needles: list[str]) -> int | None:
    for i, f in enumerate(files, 1):
        fl = f.replace("\\", "/").lower()
        if any(n.lower().replace("\\", "/") in fl for n in needles):
            return i
    return None


def _dcg(rels: list[float]) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


def _ndcg(gains: list[float], k: int = 10) -> float:
    g = gains[:k]
    ideal = sorted(gains, reverse=True)[:k]
    idcg = _dcg(ideal)
    return 0.0 if idcg <= 0 else _dcg(g) / idcg


def _load_graph(repo: Path) -> Any:
    candidates = [
        repo / "graphify-out" / "graph.json",
        ROOT / "out" / "seir_ab" / "graph.json",
    ]
    # Optional: existing CE store graph (may be empty if not indexed)
    try:
        from pipeline.store import PipelineStore

        store = PipelineStore(repo, resolve=True)
        candidates.insert(0, store.base / "graph.json")
    except Exception:  # noqa: BLE001
        pass
    for path in candidates:
        if path.is_file():
            try:
                from graphify.serve import _load_graph

                print(f"[seir] graph={path}", flush=True)
                return _load_graph(str(path))
            except Exception as exc:  # noqa: BLE001
                print(f"[seir] graph load failed {path}: {exc}", flush=True)
    print("[seir] no graph.json — rels arm uses AST-local edges only", flush=True)
    return None


def _eval_dense(
    col: FaissCollection,
    files: list[str],
    embedder: Embedder,
    suite: list[dict[str, Any]],
    *,
    top_k: int = 10,
) -> dict[str, Any]:
    r1 = r5 = r10 = 0
    rr = 0.0
    ndcgs: list[float] = []
    qms: list[float] = []
    fails: list[str] = []
    for item in suite:
        q = item["query"]
        rel = item["files_substr"]
        t0 = time.perf_counter()
        qv = embedder.embed_one(q, is_query=True)
        hits = col.search(qv, top_k=top_k)
        qms.append((time.perf_counter() - t0) * 1000)
        hit_files: list[str] = []
        for vid, _score, payload in hits:
            f = str(payload.get("file") or "")
            if not f and 0 <= int(vid) < len(files):
                f = files[int(vid)]
            if f:
                hit_files.append(f)
        ok1 = _hit(hit_files[:1], rel)
        ok5 = _hit(hit_files[:5], rel)
        ok10 = _hit(hit_files[:10], rel)
        r1 += int(ok1)
        r5 += int(ok5)
        r10 += int(ok10)
        if not ok10:
            fails.append(item.get("id", q))
        rank = _rank(hit_files, rel)
        if rank:
            rr += 1.0 / rank
        gains = [1.0 if _hit([f], rel) else 0.0 for f in hit_files[:10]]
        ndcgs.append(_ndcg(gains, 10))
    n = max(len(suite), 1)
    return {
        "n": n,
        "recall_at_1": round(r1 / n, 4),
        "recall_at_5": round(r5 / n, 4),
        "recall_at_10": round(r10 / n, 4),
        "mrr": round(rr / n, 4),
        "ndcg_at_10": round(statistics.mean(ndcgs) if ndcgs else 0.0, 4),
        "avg_query_ms": round(statistics.mean(qms) if qms else 0.0, 1),
        "failures": fails[:20],
        "failure_count": len(fails),
    }


def _build_collection(
    arm: str,
    texts: list[str],
    files: list[str],
    embedder: Embedder,
) -> tuple[FaissCollection, dict[str, Any]]:
    out = OUT_DIR / arm
    if out.exists():
        import shutil

        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    matrix = embedder.embed_many(texts)
    embed_sec = time.perf_counter() - t0
    dim = int(matrix.shape[1])

    meta = CollectionMeta(
        name=f"seir_{arm}",
        cwd=str(OUT_DIR),
        dim=dim,
        metric="ip",
        bits=4,
    )
    col = FaissCollection(out, meta)
    ids = list(range(len(texts)))
    payloads = [
        {"id": int(i), "file": files[i], "text": texts[i][:200]}
        for i in range(len(texts))
    ]
    col.add(matrix, ids, payloads)
    col.save()

    chars = [len(t) for t in texts]
    toks = [estimate_tokens(t) for t in texts]
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    stats = {
        "n": len(texts),
        "embed_sec": round(embed_sec, 3),
        "embed_ms_per_chunk": round(1000 * embed_sec / max(len(texts), 1), 2),
        "avg_chars": round(statistics.mean(chars), 1),
        "avg_tokens_est": round(statistics.mean(toks), 1),
        "total_chars": int(sum(chars)),
        "collection_bytes": int(size),
        "dim": dim,
    }
    return col, stats


def main() -> int:
    ap = argparse.ArgumentParser(description="SEIR representation A/B bench")
    ap.add_argument("--repo", default=str(REPO_DEFAULT))
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--max-chars", type=int, default=512)
    ap.add_argument("--limit-spans", type=int, default=0)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--batch", type=int, default=int(os.environ.get("CTX_EMBED_BATCH", "16")))
    args = ap.parse_args()

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"ERROR: missing repo {repo}", flush=True)
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    for a in arms:
        if a not in ARMS:
            print(f"ERROR: unknown arm {a!r}; choose from {ARMS}", flush=True)
            return 2

    limit = args.limit_spans if args.limit_spans > 0 else None
    print(f"[seir] spans from {repo} limit={limit}", flush=True)
    spans = iter_python_spans(repo, limit=limit)
    if not spans:
        print("ERROR: no python spans found", flush=True)
        return 2
    print(f"[seir] spans={len(spans)}", flush=True)

    graph = _load_graph(repo)
    files = [s.file for s in spans]

    print("[seir] loading embedder…", flush=True)
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
            "arms": arms,
            "spans": len(spans),
            "top_k": args.top_k,
            "gold": "HARD_V2",
            "gold_n": len(HARD_V2),
            "baseline_recipe": "pipeline.chunk_compress mix via prepare_enriched_from_parts(source)",
            "eval": "dense-only FAISS IP (isolates representation)",
        },
        "arms": {},
    }

    for arm in arms:
        print(f"\n=== ARM {arm} ===", flush=True)
        t_render = time.perf_counter()
        texts = [
            render(arm, s, max_chars=args.max_chars, graph=graph)
            for s in spans
        ]
        render_sec = time.perf_counter() - t_render
        print(
            f"[seir] rendered {len(texts)} in {render_sec:.2f}s "
            f"avg_chars={statistics.mean(len(t) for t in texts):.0f}",
            flush=True,
        )
        col, stats = _build_collection(arm, texts, files, embedder)
        stats["render_sec"] = round(render_sec, 3)
        print(json.dumps(stats, indent=2), flush=True)
        quality = _eval_dense(col, files, embedder, HARD_V2, top_k=args.top_k)
        print(
            json.dumps(
                {k: quality[k] for k in (
                    "recall_at_1", "recall_at_5", "recall_at_10",
                    "mrr", "ndcg_at_10", "avg_query_ms", "failure_count",
                )},
                indent=2,
            ),
            flush=True,
        )
        report["arms"][arm] = {"stats": stats, "quality": quality}

    # ranking
    ranked = sorted(
        arms,
        key=lambda a: (
            -report["arms"][a]["quality"]["recall_at_5"],
            -report["arms"][a]["quality"]["mrr"],
            report["arms"][a]["stats"]["avg_chars"],
        ),
    )
    report["ranked_by_r5_mrr_then_fewer_chars"] = ranked
    baseline_q = report["arms"].get("baseline", {}).get("quality", {})
    winners = []
    for a in arms:
        if a == "baseline":
            continue
        q = report["arms"][a]["quality"]
        s = report["arms"][a]["stats"]
        b_s = report["arms"].get("baseline", {}).get("stats", {})
        better_quality = (
            q.get("recall_at_5", 0) > baseline_q.get("recall_at_5", 0)
            or q.get("mrr", 0) > baseline_q.get("mrr", 0)
            or q.get("ndcg_at_10", 0) > baseline_q.get("ndcg_at_10", 0)
        )
        denser = s.get("avg_chars", 1e9) < b_s.get("avg_chars", 0) * 0.95 if b_s else False
        if better_quality or (
            denser
            and q.get("recall_at_5", 0) >= baseline_q.get("recall_at_5", 0) - 0.02
        ):
            winners.append(a)
    report["beats_or_matches_baseline_denser"] = winners

    ts = time.strftime("%Y%m%d_%H%M%S")
    out_json = ROOT / "out" / f"seir_ab_{ts}.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n[seir] wrote {out_json}", flush=True)
    print(f"[seir] ranked={ranked} winners={winners}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

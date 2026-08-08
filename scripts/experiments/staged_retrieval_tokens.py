"""Experiment: staged retrieval token savings (does not change production).

Architecture under test:
  Query
    → parallel BM25 ⊕ dense ⊕ graph (via D_rerank / A pool)
    → D lexical/path rerank
    → optional 1-hop graph neighbor expand (capped)
    → read only chunk spans (not whole files)
    → optional light grep confirm snippets

Arms compared (same HARD_V2 queries):
  1. naive_dense_fullfile — dense top files → full-file reads
  2. ce_d_spans          — D_rerank hits → chunk span text only
  3. staged_expand_spans — D_rerank seeds → graph expand → span reads + grep peek

Usage:
  .\\.venv\\Scripts\\python.exe -u scripts\\experiments\\staged_retrieval_tokens.py
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))

from conductor.hard_v2_gold import HARD_V2  # noqa: E402
from pipeline.engine import WarmSearchEngine, load_engine  # noqa: E402
from pipeline.token_meter import estimate_tokens  # noqa: E402

REPO_DEFAULT = ROOT / "testdata" / "frontend-mcp"
OUT_DIR = ROOT / "out" / "experiments"


@dataclass
class ArmOut:
    name: str
    query: str
    tokens: int
    chars: int
    ms: float
    files: list[str]
    hit_gold: bool
    gold_rank: int | None
    detail: dict[str, Any] = field(default_factory=dict)


def _hit_gold(files: list[str], needles: list[str]) -> tuple[bool, int | None]:
    for i, f in enumerate(files, 1):
        fl = f.replace("\\", "/").lower()
        if any(n.lower().replace("\\", "/") in fl for n in needles):
            return True, i
    return False, None


def _read_span(
    root: Path,
    rel: str,
    start: int,
    end: int,
    *,
    max_chars: int,
) -> str:
    path = root / rel
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    s = max(1, int(start)) - 1
    e = min(len(lines), max(int(end), s + 1))
    body = "\n".join(lines[s:e])
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    return f"# {rel}:{start}-{end}\n{body}"


def _read_file_capped(root: Path, rel: str, *, max_chars: int) -> str:
    try:
        body = (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    return f"# {rel} (full-ish)\n{body}"


def _chunk_by_id(engine: WarmSearchEngine) -> dict[int, Any]:
    return {int(c.id): c for c in engine.chunks}


def _grep_peek(root: Path, rel: str, query: str, *, max_chars: int = 240) -> str:
    terms = [t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query) if len(t) > 3][:6]
    if not terms:
        return ""
    try:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = text.splitlines()
    hits: list[str] = []
    low_terms = [t.lower() for t in terms]
    for i, line in enumerate(lines, 1):
        low = line.lower()
        if any(t in low for t in low_terms):
            hits.append(f"{i}:{line.strip()[:160]}")
            if len(hits) >= 3:
                break
    if not hits:
        return ""
    blob = "\n".join(hits)
    if len(blob) > max_chars:
        blob = blob[: max_chars - 1] + "…"
    return f"# grep {rel}\n{blob}"


def arm_naive_dense_fullfile(
    engine: WarmSearchEngine,
    query: str,
    qvec: Any,
    gold: list[str],
    *,
    top_k: int,
    max_chars_per_file: int,
) -> ArmOut:
    t0 = time.perf_counter()
    dense_hits = engine.conductor.dense.search(qvec, top_k=top_k * 4)
    files: list[str] = []
    seen: set[str] = set()
    for cid, _score in dense_hits:
        if cid < 0 or cid >= len(engine.files):
            continue
        f = engine.files[cid].replace("\\", "/")
        if f in seen:
            continue
        seen.add(f)
        files.append(f)
        if len(files) >= top_k:
            break
    parts = [_read_file_capped(engine.root, f, max_chars=max_chars_per_file) for f in files]
    payload = "\n\n".join(p for p in parts if p)
    ok, rank = _hit_gold(files, gold)
    return ArmOut(
        name="naive_dense_fullfile",
        query=query,
        tokens=estimate_tokens(payload),
        chars=len(payload),
        ms=(time.perf_counter() - t0) * 1000,
        files=files,
        hit_gold=ok,
        gold_rank=rank,
        detail={"n_files": len(files)},
    )


def arm_ce_d_spans(
    engine: WarmSearchEngine,
    query: str,
    qvec: Any,
    gold: list[str],
    *,
    top_k: int,
    max_chars_per_span: int,
) -> ArmOut:
    t0 = time.perf_counter()
    hits = engine.conductor.retrieve_D_rerank(query, qvec, top_k=top_k)
    by_id = _chunk_by_id(engine)
    files: list[str] = []
    parts: list[str] = []
    for h in hits:
        f = h.file.replace("\\", "/")
        files.append(f)
        c = by_id.get(int(h.chunk_id))
        if c is None:
            continue
        parts.append(
            _read_span(
                engine.root,
                f,
                c.start_line,
                c.end_line,
                max_chars=max_chars_per_span,
            )
        )
    payload = "\n\n".join(p for p in parts if p)
    ok, rank = _hit_gold(files, gold)
    return ArmOut(
        name="ce_d_spans",
        query=query,
        tokens=estimate_tokens(payload),
        chars=len(payload),
        ms=(time.perf_counter() - t0) * 1000,
        files=files,
        hit_gold=ok,
        gold_rank=rank,
        detail={"n_hits": len(hits)},
    )


def arm_staged(
    engine: WarmSearchEngine,
    query: str,
    qvec: Any,
    gold: list[str],
    *,
    seed_k: int,
    expand_cap: int,
    max_files: int,
    max_chars_per_span: int,
    grep_peek: bool,
) -> ArmOut:
    """Staged: D_rerank seeds → graph neighbor expand → span reads (+ optional grep)."""
    t0 = time.perf_counter()
    seeds = engine.conductor.retrieve_D_rerank(query, qvec, top_k=seed_k)
    seed_files = [h.file.replace("\\", "/") for h in seeds]
    expanded = list(seed_files)
    seen = set(expanded)
    # 1-hop neighbors
    for nf in engine.conductor.graph.neighbor_files(seed_files, cap=expand_cap):
        n = nf.replace("\\", "/")
        if n not in seen:
            seen.add(n)
            expanded.append(n)
        if len(expanded) >= max_files:
            break
    expanded = expanded[:max_files]

    by_id = _chunk_by_id(engine)
    # Best chunk per seed hit; for expanded-only files, pick first chunk in that file
    file_to_chunk: dict[str, Any] = {}
    for h in seeds:
        f = h.file.replace("\\", "/")
        c = by_id.get(int(h.chunk_id))
        if c is not None and f not in file_to_chunk:
            file_to_chunk[f] = c
    for f in expanded:
        if f in file_to_chunk:
            continue
        for c in engine.chunks:
            if c.file.replace("\\", "/") == f:
                file_to_chunk[f] = c
                break

    parts: list[str] = []
    for f in expanded:
        c = file_to_chunk.get(f)
        if c is None:
            continue
        parts.append(
            _read_span(
                engine.root,
                f,
                c.start_line,
                c.end_line,
                max_chars=max_chars_per_span,
            )
        )
        if grep_peek:
            g = _grep_peek(engine.root, f, query, max_chars=200)
            if g:
                parts.append(g)

    payload = "\n\n".join(p for p in parts if p)
    ok, rank = _hit_gold(expanded, gold)
    return ArmOut(
        name="staged_expand_spans",
        query=query,
        tokens=estimate_tokens(payload),
        chars=len(payload),
        ms=(time.perf_counter() - t0) * 1000,
        files=expanded,
        hit_gold=ok,
        gold_rank=rank,
        detail={
            "seed_files": seed_files,
            "n_expanded": len(expanded),
            "grep_peek": grep_peek,
        },
    )


def _summarize(arm_name: str, rows: list[ArmOut]) -> dict[str, Any]:
    toks = [r.tokens for r in rows]
    ms = [r.ms for r in rows]
    hits = sum(1 for r in rows if r.hit_gold)
    ranks = [r.gold_rank for r in rows if r.gold_rank]
    mrr = statistics.mean(1.0 / r for r in ranks) if ranks else 0.0
    n = max(len(rows), 1)
    return {
        "arm": arm_name,
        "n": len(rows),
        "tokens_total": int(sum(toks)),
        "tokens_mean": round(statistics.mean(toks), 1),
        "tokens_p50": int(sorted(toks)[len(toks) // 2]),
        "ms_mean": round(statistics.mean(ms), 1),
        "recall_at_list": round(hits / n, 4),
        "mrr": round(mrr, 4),
        "gold_hits": hits,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Staged retrieval token-savings experiment")
    ap.add_argument("--repo", default=str(REPO_DEFAULT))
    ap.add_argument("--top-k", type=int, default=8)
    ap.add_argument("--seed-k", type=int, default=5)
    ap.add_argument("--expand-cap", type=int, default=12)
    ap.add_argument("--max-files-staged", type=int, default=8)
    ap.add_argument("--max-chars-file", type=int, default=8000)
    ap.add_argument("--max-chars-span", type=int, default=700)
    ap.add_argument("--no-grep-peek", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="Limit gold queries (0=all)")
    args = ap.parse_args()

    os.environ.pop("CTX_HOME", None)
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"ERROR: missing repo {repo}", flush=True)
        return 2

    print(f"[staged-exp] loading engine {repo}", flush=True)
    engine = load_engine(repo)
    print(
        f"[staged-exp] chunks={len(engine.chunks)} load_ms={engine.load_ms:.0f}",
        flush=True,
    )

    suite = HARD_V2
    if args.limit > 0:
        suite = HARD_V2[: args.limit]

    by_arm: dict[str, list[ArmOut]] = {
        "naive_dense_fullfile": [],
        "ce_d_spans": [],
        "staged_expand_spans": [],
    }

    for i, item in enumerate(suite, 1):
        q = item["query"]
        gold = item["files_substr"]
        print(f"[{i}/{len(suite)}] {item['id']}", flush=True)
        qvec = engine.embedder.embed_one(q, is_query=True)

        a = arm_naive_dense_fullfile(
            engine,
            q,
            qvec,
            gold,
            top_k=args.top_k,
            max_chars_per_file=args.max_chars_file,
        )
        b = arm_ce_d_spans(
            engine,
            q,
            qvec,
            gold,
            top_k=args.top_k,
            max_chars_per_span=args.max_chars_span,
        )
        c = arm_staged(
            engine,
            q,
            qvec,
            gold,
            seed_k=args.seed_k,
            expand_cap=args.expand_cap,
            max_files=args.max_files_staged,
            max_chars_per_span=args.max_chars_span,
            grep_peek=not args.no_grep_peek,
        )
        by_arm["naive_dense_fullfile"].append(a)
        by_arm["ce_d_spans"].append(b)
        by_arm["staged_expand_spans"].append(c)
        print(
            f"  naive={a.tokens} tok hit={a.hit_gold} | "
            f"ce={b.tokens} hit={b.hit_gold} | "
            f"staged={c.tokens} hit={c.hit_gold}",
            flush=True,
        )

    summaries = {name: _summarize(name, rows) for name, rows in by_arm.items()}
    naive_tok = summaries["naive_dense_fullfile"]["tokens_total"]
    savings = {}
    for name, s in summaries.items():
        if name == "naive_dense_fullfile":
            continue
        saved = max(0, naive_tok - s["tokens_total"])
        savings[name] = {
            "tokens_saved_vs_naive": saved,
            "pct_saved_vs_naive": round(100.0 * saved / naive_tok, 1) if naive_tok else 0.0,
            "recall_delta_vs_naive": round(
                s["recall_at_list"] - summaries["naive_dense_fullfile"]["recall_at_list"],
                4,
            ),
        }

    report = {
        "repo": str(repo),
        "config": {
            "top_k": args.top_k,
            "seed_k": args.seed_k,
            "expand_cap": args.expand_cap,
            "max_files_staged": args.max_files_staged,
            "max_chars_file": args.max_chars_file,
            "max_chars_span": args.max_chars_span,
            "grep_peek": not args.no_grep_peek,
            "gold": "HARD_V2",
            "n": len(suite),
            "note": "experiment only — production defaults unchanged",
        },
        "summaries": summaries,
        "savings_vs_naive_fullfile": savings,
        "rows": {
            name: [asdict(r) for r in rows] for name, rows in by_arm.items()
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = OUT_DIR / f"staged_retrieval_tokens_{ts}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("\n=== STAGED RETRIEVAL TOKEN EXPERIMENT ===", flush=True)
    for name, s in summaries.items():
        print(json.dumps(s, indent=2), flush=True)
    print("\nSavings vs naive_dense_fullfile:", flush=True)
    print(json.dumps(savings, indent=2), flush=True)
    print(f"\n[staged-exp] wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

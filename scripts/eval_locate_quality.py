"""Retrieval-quality gate for the locate toolkit (map/focus/expand).

Runs natural-language queries with known ground-truth files against the live
engine and reports hit@k plus rank. Exits non-zero when hit rate drops below
--min-hit-rate so it can be used as a gate.

    python scripts/eval_locate_quality.py --repo . --json out.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "packages") not in sys.path:
    sys.path.insert(0, str(ROOT / "packages"))

# (query, any-of expected path substrings). Ground truth is deliberately stated
# as suffixes so the eval survives file moves within a package.
CASES: list[tuple[str, tuple[str, ...]]] = [
    (
        "how do we decide token budgets when savings mode is on",
        ("pipeline/session_store.py",),
    ),
    (
        "track which files are hot in the current working session",
        ("pipeline/work_session.py",),
    ),
    (
        "start the background service and recover when it is hung",
        ("pipeline/daemon.py",),
    ),
    (
        "combine dense vectors, keyword search and graph neighbours into one ranking",
        (
            "conductor/architectures.py",
            "conductor/conductor.py",
            "pipeline/searcher.py",
        ),
    ),
    (
        "talk to the running service over http and check whether it is healthy",
        ("pipeline/client.py",),
    ),
    (
        "detect which files changed since the last index using hashes",
        (
            "pipeline/merkle.py",
            "pipeline/root_probe.py",
            "pipeline/incremental.py",
            "pipeline/freshness.py",
        ),
    ),
    (
        "split source files into chunks and embed them",
        ("pipeline/chunk_compress.py", "pipeline/indexer.py", "pipeline/embedder.py"),
    ),
    (
        "walk the call and import graph between symbols",
        (
            "pipeline/graphify_mcp_tools.py",
            "pipeline/context_nav.py",
            "graphify/symbol_resolution.py",
        ),
    ),
    (
        "compress vectors so the index fits in memory",
        ("pipeline/turbo_quant.py", "pipeline/faiss_store.py", "pipeline/vectordb.py"),
    ),
]


def _norm(path: str) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def _targets(card: object) -> list[dict]:
    if isinstance(card, str):
        try:
            card = json.loads(card)
        except json.JSONDecodeError:
            return []
    if not isinstance(card, dict):
        return []
    out = []
    for t in card.get("targets") or []:
        if isinstance(t, dict):
            out.append(t)
    return out


def run_case(map_fn, query: str, expected: tuple[str, ...], top_k: int) -> dict:
    t0 = time.perf_counter()
    try:
        raw = map_fn(query=query)
        error = ""
    except Exception as exc:  # noqa: BLE001
        raw, error = "", f"{type(exc).__name__}: {exc}"
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

    targets = _targets(raw)
    files = [_norm(t.get("file") or t.get("path") or "") for t in targets]
    rank = None
    for i, f in enumerate(files[:top_k], start=1):
        if any(f.endswith(e) for e in expected):
            rank = i
            break
    return {
        "query": query,
        "expected_any_of": list(expected),
        "hit": rank is not None,
        "rank": rank,
        "n_targets": len(targets),
        "returned": files[:top_k],
        "elapsed_ms": elapsed_ms,
        "error": error,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--top-k", type=int, default=8)
    ap.add_argument("--min-hit-rate", type=float, default=0.75)
    ap.add_argument("--json", default="")
    args = ap.parse_args(argv)

    repo = Path(args.repo).resolve()
    os.environ["CTX_REPO"] = str(repo)
    os.environ.setdefault("CTX_RETRIEVE", "D_channel_best")
    os.environ.setdefault("CTX_TOKEN_MODE", "savings")

    from pipeline.mcp_locate import create_mcp

    mcp = create_mcp(name="eval-locate")
    tools = mcp._tool_manager._tools
    map_fn = tools["map"].fn
    expand_fn = tools["expand"].fn

    results = [run_case(map_fn, q, exp, args.top_k) for q, exp in CASES]
    hits = sum(1 for r in results if r["hit"])
    hit_rate = hits / len(results) if results else 0.0
    ranks = [r["rank"] for r in results if r["rank"]]
    mrr = sum(1 / r for r in ranks) / len(results) if results else 0.0

    # expand() must materialise a handle produced by map().
    expand_check = {"ok": False, "detail": "no handle produced by map"}
    for r, (q, _exp) in zip(results, CASES):
        if r["error"] or not r["n_targets"]:
            continue
        card = _targets(map_fn(query=q))
        handle = (card[0].get("handle") or "") if card else ""
        if not handle:
            continue
        try:
            body = json.loads(expand_fn(handle=handle))
            expand_check = {
                "ok": bool(body.get("ok")) and bool(body.get("text")),
                "handle": handle,
                "chars": len(str(body.get("text") or "")),
            }
        except Exception as exc:  # noqa: BLE001
            expand_check = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}
        break

    report = {
        "repo": str(repo),
        "n_cases": len(results),
        "hits": hits,
        "hit_rate": round(hit_rate, 3),
        "mrr": round(mrr, 3),
        "median_ms": sorted(r["elapsed_ms"] for r in results)[len(results) // 2],
        "expand": expand_check,
        "cases": results,
    }
    print(json.dumps(report, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")

    ok = hit_rate >= args.min_hit_rate and expand_check.get("ok")
    print(
        f"\nhit@{args.top_k}={hits}/{len(results)} ({hit_rate:.0%})  "
        f"mrr={mrr:.3f}  expand_ok={expand_check.get('ok')}  "
        f"=> {'PASS' if ok else 'FAIL'}",
        file=sys.stderr,
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

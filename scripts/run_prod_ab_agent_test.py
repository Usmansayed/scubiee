"""Production A/B: Graphify vs D_rerank via local API (no Cursor semantic search)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from conductor.diverse_bank import (
    D1_SEO,
    D2_FIGMA,
    D3_CONSISTENCY,
    D4_DESIGN_EXEC,
    D5_ERRORISH,
)
from conductor.suite_bank import (
    S1_SYMBOL,
    S2_PARAPHRASE,
    S3_CONFUSABLE,
    S4_MULTIHOP,
    S5_TERSE,
)

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / "testdata" / "frontend-mcp"
API = "http://127.0.0.1:8765"
TOP_K = 5
OUT = ROOT / "out" / "conductor_prod_ab_agent_run.json"

BANKS = {
    "S1_symbol": S1_SYMBOL[:6],
    "S2_paraphrase": S2_PARAPHRASE[:6],
    "S3_confusion": S3_CONFUSABLE[:6],
    "S4_multihop": S4_MULTIHOP[:4],
    "S5_terse": S5_TERSE[:4],
    "D1_seo": D1_SEO[:4],
    "D2_figma": D2_FIGMA[:4],
    "D3_consistency": D3_CONSISTENCY[:4],
    "D4_design": D4_DESIGN_EXEC[:4],
    "D5_errorish": D5_ERRORISH[:4],
}

_size_cache: dict[str, int] = {}


def file_chars(rel: str) -> int:
    if rel in _size_cache:
        return _size_cache[rel]
    p = REPO / rel
    if not p.exists():
        hits = list(REPO.rglob(Path(rel).name))
        p = hits[0] if hits else None  # type: ignore[assignment]
    n = len(p.read_text(encoding="utf-8", errors="ignore")) if p and p.exists() else 0
    _size_cache[rel] = n
    return n


def tok(chars: int) -> int:
    return max(1, (chars + 3) // 4) if chars else 0


def gold_hit(files: list[str], substrs: list[str]) -> tuple[bool, int | None]:
    for i, f in enumerate(files):
        fl = f.replace("\\", "/").lower()
        for s in substrs:
            if s.replace("\\", "/").lower() in fl:
                return True, i + 1
    return False, None


def tokens_to_gold(files: list[str], substrs: list[str]) -> dict:
    """Tokens if agent opens files in rank order until gold (early stop)."""
    total = 0
    found = False
    opened = 0
    for f in files:
        total += file_chars(f)
        opened += 1
        ok, _ = gold_hit([f], substrs)
        if ok:
            found = True
            break
    return {
        "found": found,
        "files_opened": opened,
        "chars": total,
        "tokens_est": tok(total),
        "tokens_top_k_all": tok(sum(file_chars(f) for f in files)),
    }


def run_compare(query: str, top_k: int = TOP_K) -> dict:
    r = requests.post(f"{API}/compare", json={"query": query, "top_k": top_k}, timeout=120)
    r.raise_for_status()
    return r.json()


def main() -> None:
    rows: list[dict] = []
    t0 = time.perf_counter()
    for bank, items in BANKS.items():
        for item in items:
            q = item["query"]
            gold = item["files_substr"]
            data = run_compare(q)
            g_hits = [h["file"] for h in data["modes"]["graphify"]["hits"]]
            d_hits = [h["file"] for h in data["modes"]["d_rerank"]["hits"]]
            g_ok, g_rank = gold_hit(g_hits, gold)
            d_ok, d_rank = gold_hit(d_hits, gold)
            g_tok = tokens_to_gold(g_hits, gold)
            d_tok = tokens_to_gold(d_hits, gold)

            if g_ok and not d_ok:
                winner = "graphify"
            elif d_ok and not g_ok:
                winner = "d_rerank"
            elif g_ok and d_ok:
                if (g_rank or 99) < (d_rank or 99):
                    winner = "graphify_better_rank"
                elif (d_rank or 99) < (g_rank or 99):
                    winner = "d_rerank_better_rank"
                else:
                    winner = "tie"
            else:
                winner = "miss_both"

            if g_tok["found"] and d_tok["found"]:
                if g_tok["tokens_est"] < d_tok["tokens_est"]:
                    tok_winner = "graphify"
                elif d_tok["tokens_est"] < g_tok["tokens_est"]:
                    tok_winner = "d_rerank"
                else:
                    tok_winner = "tie"
            elif g_tok["found"]:
                tok_winner = "graphify"
            elif d_tok["found"]:
                tok_winner = "d_rerank"
            else:
                tok_winner = "miss_both"

            rows.append(
                {
                    "bank": bank,
                    "id": item["id"],
                    "query": q,
                    "gold": gold,
                    "same_top1": data["agreement"]["same_top1"],
                    "jaccard": data["agreement"]["jaccard_top_k"],
                    "latency_ms": data["total_latency_ms"],
                    "g_r_at_k": g_ok,
                    "d_r_at_k": d_ok,
                    "g_rank": g_rank,
                    "d_rank": d_rank,
                    "g_files": g_hits,
                    "d_files": d_hits,
                    "g_tokens_to_gold": g_tok,
                    "d_tokens_to_gold": d_tok,
                    "quality_winner": winner,
                    "token_winner": tok_winner,
                    "g_lat": data["modes"]["graphify"]["latency_ms"],
                    "d_lat": data["modes"]["d_rerank"]["latency_ms"],
                }
            )
            print(
                f"{item['id']:28} g@{g_rank or '-'} d@{d_rank or '-'} "
                f"q={winner:22} tok={tok_winner}",
                flush=True,
            )

    elapsed = time.perf_counter() - t0
    n = len(rows)
    g_hit = sum(1 for r in rows if r["g_r_at_k"])
    d_hit = sum(1 for r in rows if r["d_r_at_k"])
    both = sum(1 for r in rows if r["g_r_at_k"] and r["d_r_at_k"])
    only_g = sum(1 for r in rows if r["g_r_at_k"] and not r["d_r_at_k"])
    only_d = sum(1 for r in rows if r["d_r_at_k"] and not r["g_r_at_k"])
    miss = sum(1 for r in rows if not r["g_r_at_k"] and not r["d_r_at_k"])

    def mrr(key_rank: str) -> float:
        s = 0.0
        for r in rows:
            rk = r[key_rank]
            s += (1.0 / rk) if rk else 0.0
        return s / n

    g_found = [r for r in rows if r["g_tokens_to_gold"]["found"]]
    d_found = [r for r in rows if r["d_tokens_to_gold"]["found"]]
    both_rows = [
        r
        for r in rows
        if r["g_tokens_to_gold"]["found"] and r["d_tokens_to_gold"]["found"]
    ]
    g_tok_both = sum(r["g_tokens_to_gold"]["tokens_est"] for r in both_rows) / max(
        1, len(both_rows)
    )
    d_tok_both = sum(r["d_tokens_to_gold"]["tokens_est"] for r in both_rows) / max(
        1, len(both_rows)
    )
    g_topk_tok = sum(r["g_tokens_to_gold"]["tokens_top_k_all"] for r in rows) / n
    d_topk_tok = sum(r["d_tokens_to_gold"]["tokens_top_k_all"] for r in rows) / n

    qw: dict[str, int] = {}
    tw: dict[str, int] = {}
    for r in rows:
        qw[r["quality_winner"]] = qw.get(r["quality_winner"], 0) + 1
        tw[r["token_winner"]] = tw.get(r["token_winner"], 0) + 1

    by_bank: dict[str, dict] = {}
    for r in rows:
        b = r["bank"]
        by_bank.setdefault(b, {"n": 0, "g": 0, "d": 0})
        by_bank[b]["n"] += 1
        by_bank[b]["g"] += int(r["g_r_at_k"])
        by_bank[b]["d"] += int(r["d_r_at_k"])

    summary = {
        "n_queries": n,
        "top_k": TOP_K,
        "elapsed_s": round(elapsed, 2),
        "channel": "conductor_api_/compare",
        "no_cursor_semantic_search": True,
        "recall_at_5": {
            "graphify": round(g_hit / n, 4),
            "d_rerank": round(d_hit / n, 4),
            "both_hit": both,
            "graphify_only": only_g,
            "d_rerank_only": only_d,
            "miss_both": miss,
        },
        "mrr": {"graphify": round(mrr("g_rank"), 4), "d_rerank": round(mrr("d_rank"), 4)},
        "latency_ms_mean": {
            "graphify": round(sum(r["g_lat"] for r in rows) / n, 2),
            "d_rerank": round(sum(r["d_lat"] for r in rows) / n, 2),
            "compare_total": round(sum(r["latency_ms"] for r in rows) / n, 2),
        },
        "agreement": {
            "same_top1_rate": round(sum(1 for r in rows if r["same_top1"]) / n, 4),
            "jaccard_mean": round(sum(r["jaccard"] for r in rows) / n, 4),
        },
        "tokens_to_gold_mean_when_found": {
            "graphify": round(
                sum(r["g_tokens_to_gold"]["tokens_est"] for r in g_found) / max(1, len(g_found)),
                1,
            ),
            "d_rerank": round(
                sum(r["d_tokens_to_gold"]["tokens_est"] for r in d_found) / max(1, len(d_found)),
                1,
            ),
            "note": "chars/4 if agent opens ranked files until gold hit",
        },
        "tokens_to_gold_mean_on_both_hit": {
            "n": len(both_rows),
            "graphify": round(g_tok_both, 1),
            "d_rerank": round(d_tok_both, 1),
            "delta_d_minus_g": round(d_tok_both - g_tok_both, 1),
            "cheaper": (
                "graphify"
                if g_tok_both < d_tok_both
                else ("d_rerank" if d_tok_both < g_tok_both else "tie")
            ),
        },
        "tokens_if_open_all_top5_mean": {
            "graphify": round(g_topk_tok, 1),
            "d_rerank": round(d_topk_tok, 1),
        },
        "quality_winner_counts": qw,
        "token_winner_counts": tw,
        "by_bank_recall": {
            k: {
                "graphify": round(v["g"] / v["n"], 3),
                "d_rerank": round(v["d"] / v["n"], 3),
                "n": v["n"],
            }
            for k, v in by_bank.items()
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2), encoding="utf-8")
    print("\n=== SUMMARY ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    print(f"\nWrote {OUT}", flush=True)


if __name__ == "__main__":
    main()

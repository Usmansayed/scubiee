"""Real-repo ladder soak: map → pack(lean) → expand(+bodies) vs pack-only.

Measures whether follow-up tools recover recall that lean packs miss.
Uses composite_v1 by default (CTX_TRACE_ENGINE).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

ROOT = Path(r"C:/Users/usman/Downloads/context-engine")
OUT = Path("docs/superpowers/plans/2026-09-05-ladder-followup-real-eval.json")

# Reuse the 10 real problems from the map/pack eval.
from ten_problem_map_pack_eval import PROBLEMS, _pick_seed, _score_pack, _soft_map  # noqa: E402


def _union_score(parts: list[dict[str, Any]], gold_files: list[str], gold_symbols: list[str]) -> dict[str, Any]:
    files: set[str] = set()
    syms: set[str] = set()
    chars = 0
    packed = 0
    for p in parts:
        if not p or not p.get("ok"):
            continue
        for b in (p.get("pack") or []) + (p.get("heatmap") or []) + (p.get("delta") or []) + (p.get("cold") or []):
            if b.get("file"):
                files.add(str(b["file"]).replace("\\", "/"))
            if b.get("symbol"):
                syms.add(str(b["symbol"]))
        for b in p.get("pack") or []:
            packed += 1
            chars += len(b.get("text") or "")
    fake = {
        "ok": True,
        "pack": [{"file": f, "symbol": s, "text": ""} for f in files for s in (list(syms) or [""])],
        "heatmap": [{"file": f, "symbol": s} for f, s in zip(files, list(syms) + [""] * len(files))],
        "packed": packed,
        "chars": chars,
        "count": len(files),
    }
    # score on accumulated file/symbol sets
    file_hits = []
    for g in gold_files:
        ok = any(f.endswith(g) or g in f for f in files)
        file_hits.append({"gold": g, "hit": ok})
    sym_hits = []
    for g in gold_symbols:
        ok = g in syms or any(s.endswith(g) or g in s for s in syms)
        sym_hits.append({"gold": g, "hit": ok})
    fh = sum(1 for x in file_hits if x["hit"])
    sh = sum(1 for x in sym_hits if x["hit"])
    return {
        "file_rec": round(fh / len(gold_files), 3) if gold_files else None,
        "symbol_rec": round(sh / len(gold_symbols), 3) if gold_symbols else None,
        "file_hits": file_hits,
        "symbol_hits": sym_hits,
        "packed": packed,
        "pack_chars": chars,
        "heatmap_n": len(files),
        "_fake": fake,
    }


def run() -> dict[str, Any]:
    os.environ.setdefault("CTX_TRACE_ENGINE", "composite_v1")
    from pipeline.context_trace import _CACHE, run_expand_context, run_pack_context

    _CACHE.clear()
    rows: list[dict[str, Any]] = []
    t_all = time.perf_counter()

    for prob in PROBLEMS:
        t0 = time.perf_counter()
        try:
            map_out = _soft_map(ROOT, prob["map_query"], k=10)
        except Exception as exc:  # noqa: BLE001
            map_out = {"ok": False, "error": str(exc), "cards": []}
        cards = list(map_out.get("cards") or [])
        seed_card = _pick_seed(cards, prob["gold_files"])
        if not seed_card.get("file"):
            seed_file = prob["gold_files"][0]
            seed_symbol = (prob.get("gold_symbols") or [""])[0]
            seed_line = 0
            seed_source = "gold_fallback"
        else:
            seed_file = seed_card["file"]
            seed_symbol = seed_card.get("symbol") or ""
            seed_line = int(seed_card.get("start_line") or 0)
            seed_source = "map_card"

        pack_kwargs: dict[str, Any] = {
            "seed_file": seed_file,
            "k": 16,
            "mode": "lean",
            "policy": "strict",
            "hot_threshold": 0.65,
            "drop_noise": True,
        }
        if seed_symbol and "(" not in seed_symbol:
            pack_kwargs["seed_symbol"] = seed_symbol
        elif seed_line:
            pack_kwargs["seed_line"] = seed_line

        pack = run_pack_context(ROOT, prob["pack_query"], **pack_kwargs)
        if not pack.get("ok"):
            pack = run_pack_context(
                ROOT,
                prob["pack_query"],
                seed_file=prob["gold_files"][0],
                seed_symbol=(prob.get("gold_symbols") or [""])[0],
                mode="lean",
            )
            seed_source = "gold_retry"
            seed_file = prob["gold_files"][0]

        seed_id = (pack.get("seed") or {}).get("id") or ""
        if not seed_id and pack.get("heatmap"):
            seed_id = pack["heatmap"][0].get("id") or ""

        prior_ids = {c.get("id") for c in (pack.get("heatmap") or []) if c.get("id")}
        prior_packed = {b.get("id") for b in (pack.get("pack") or []) if b.get("id")}

        expand = {"ok": False}
        if seed_id:
            expand = run_expand_context(
                ROOT,
                seed_id,
                query=prob["pack_query"],
                direction="callees",
                k=12,
                prior_ids=prior_ids,
                with_bodies=True,
                budget_chars=4000,
                max_bodies=3,
                prior_packed_ids=prior_packed,
            )
            # If still thin on callers-ish problems, one effects/broad beat
            if (expand.get("count") or 0) < 2:
                expand2 = run_expand_context(
                    ROOT,
                    seed_id,
                    query=prob["pack_query"],
                    direction="broad",
                    k=12,
                    prior_ids=prior_ids | {c.get("id") for c in (expand.get("delta") or []) if c.get("id")},
                    with_bodies=True,
                    budget_chars=3000,
                    max_bodies=2,
                    prior_packed_ids=prior_packed
                    | {b.get("id") for b in (expand.get("pack") or []) if b.get("id")},
                )
                if expand2.get("ok"):
                    expand = {
                        "ok": True,
                        "delta": list(expand.get("delta") or []) + list(expand2.get("delta") or []),
                        "pack": list(expand.get("pack") or []) + list(expand2.get("pack") or []),
                        "count": (expand.get("count") or 0) + (expand2.get("count") or 0),
                        "direction": "callees+broad",
                    }

        lean_only = _score_pack(pack, prob["gold_files"], prob["gold_symbols"]) if pack.get("ok") else {
            "file_rec": 0.0,
            "symbol_rec": 0.0,
        }
        ladder = _union_score([pack, expand], prob["gold_files"], prob.get("gold_symbols") or [])

        rows.append(
            {
                "id": prob["id"],
                "seed": {"source": seed_source, "file": seed_file, "symbol": seed_symbol, "id": seed_id},
                "pack_ok": pack.get("ok"),
                "pack_engine": pack.get("engine"),
                "pack_policy": pack.get("policy"),
                "lean": lean_only,
                "ladder": {
                    "file_rec": ladder["file_rec"],
                    "symbol_rec": ladder["symbol_rec"],
                    "packed": ladder["packed"],
                    "pack_chars": ladder["pack_chars"],
                    "expand_count": expand.get("count"),
                    "expand_direction": expand.get("direction"),
                },
                "delta_file": round((ladder["file_rec"] or 0) - (lean_only.get("file_rec") or 0), 3),
                "delta_sym": round((ladder["symbol_rec"] or 0) - (lean_only.get("symbol_rec") or 0), 3),
                "ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        )
        print(
            f"{prob['id']}: lean_file={lean_only.get('file_rec')} "
            f"ladder_file={ladder['file_rec']} "
            f"lean_sym={lean_only.get('symbol_rec')} "
            f"ladder_sym={ladder['symbol_rec']} "
            f"Δf={rows[-1]['delta_file']} Δs={rows[-1]['delta_sym']} "
            f"expand={expand.get('count')}"
        )

    lean_f = [r["lean"].get("file_rec") or 0 for r in rows]
    lad_f = [r["ladder"].get("file_rec") or 0 for r in rows]
    lean_s = [r["lean"].get("symbol_rec") or 0 for r in rows]
    lad_s = [r["ladder"].get("symbol_rec") or 0 for r in rows]
    report = {
        "ok": True,
        "engine": os.environ.get("CTX_TRACE_ENGINE", "composite_v1"),
        "protocol": "map → pack(lean,strict) → expand(callees|broad, with_bodies)",
        "n": len(rows),
        "mean_lean_file_rec": round(sum(lean_f) / len(lean_f), 3),
        "mean_ladder_file_rec": round(sum(lad_f) / len(lad_f), 3),
        "mean_lean_symbol_rec": round(sum(lean_s) / len(lean_s), 3),
        "mean_ladder_symbol_rec": round(sum(lad_s) / len(lad_s), 3),
        "mean_delta_file": round(sum(r["delta_file"] for r in rows) / len(rows), 3),
        "mean_delta_sym": round(sum(r["delta_sym"] for r in rows) / len(rows), 3),
        "elapsed_ms": round((time.perf_counter() - t_all) * 1000, 1),
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "rows"}, indent=2))
    print("wrote", OUT)
    return report


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "packages"))
    run()

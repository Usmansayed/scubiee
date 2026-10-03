#!/usr/bin/env python3
"""Real bakeoff: pack_context(composite_v1) vs other pack engines.

Same query + same seed per case. Heatmap-only (include_bodies=False) = MCP default.
Reports wall time + top-id overlap vs composite baseline.

  python scripts/pack_vs_composite_bakeoff.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-blind20-triple-pack-queries.json"
OUT_JSON = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-pack-vs-composite-bakeoff.json"
OUT_MD = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-pack-vs-composite-bakeoff.md"

# Primary comparison: product default vs escape hatch.
# Heavy embed engines (poly_embed / semantic) are optional — they often crash DML mid-suite.
ARMS: list[tuple[str, str]] = [
    ("pack_context", "composite_v1"),
    ("pack_context_broad", "polytrace"),
]

N_CASES = 8
EXTRA_HEAVY_ARMS = os.environ.get("PACK_BAKEOFF_HEAVY", "").strip() in {"1", "true", "yes"}
if EXTRA_HEAVY_ARMS:
    ARMS.extend(
        [
            ("pack_poly_embed", "poly_embed"),
            ("pack_semantic", "semantic_tracer_fuse"),
        ]
    )


def _ids(payload: dict[str, Any], *, top: int = 10) -> list[str]:
    heat = payload.get("heatmap") or payload.get("pack") or payload.get("chain") or []
    out: list[str] = []
    for c in heat:
        if not isinstance(c, dict):
            continue
        i = str(c.get("id") or "")
        if not i:
            f = str(c.get("file") or "")
            s = str(c.get("symbol") or "")
            i = f"{f}::{s}" if f else ""
        if i:
            out.append(i)
        if len(out) >= top:
            break
    return out


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _pick_seed(cards: list[dict[str, Any]]) -> tuple[str, str]:
    from pipeline.context_trace import pick_suggested_seed

    sug = pick_suggested_seed(cards) if cards else None
    if isinstance(sug, dict) and sug.get("file"):
        return str(sug["file"]), str(sug.get("symbol") or "")
    for c in cards:
        f = str(c.get("file") or "")
        if f.startswith("packages/") and "/test" not in f:
            return f, str(c.get("symbol") or "")
    if cards:
        return str(cards[0].get("file") or ""), str(cards[0].get("symbol") or "")
    return "packages/pipeline/context_trace.py", "run_pack_context"


def _soft_map(query: str, *, k: int = 10) -> dict[str, Any]:
    """Soft map via warm search (same idea as MCP map) — no seed required."""
    from pipeline.context_trace import pick_suggested_seed
    from pipeline.searcher import search_repo

    t0 = time.perf_counter()
    hits = search_repo(ROOT, query, top_k=k, use_server=True) or []
    cards: list[dict[str, Any]] = []
    for i, h in enumerate(hits, 1):
        f = str(getattr(h, "file", None) or "").replace("\\", "/")
        cards.append(
            {
                "rank": i,
                "file": f,
                "symbol": getattr(h, "symbol", None) or "",
                "score": float(getattr(h, "score", 0) or 0),
                "loc": getattr(h, "loc", None) or f"{f}:1-1",
                "why": (getattr(h, "snippet", None) or getattr(h, "text", None) or "")[:240],
            }
        )
    return {
        "ok": bool(cards),
        "cards": cards,
        "suggested_seed": pick_suggested_seed(cards) if cards else None,
        "elapsed_s": round(time.perf_counter() - t0, 3),
    }


def main() -> int:
    sys.path.insert(0, str(ROOT / "packages"))
    os.environ.setdefault("CTX_TRACE_ENGINE", "composite_v1")
    os.environ.setdefault("PYTHONUTF8", "1")

    from pipeline.context_trace import _CACHE, run_pack_context

    raw = json.loads(QUERIES.read_text(encoding="utf-8"))
    cases = list(raw.get("cases") or [])[:N_CASES]
    rows: list[dict[str, Any]] = []

    for case in cases:
        cid = case["id"]
        q = str(case.get("enrich_prompt") or case.get("task") or "")
        print(f"\n=== {cid} ===", flush=True)
        _CACHE.clear()
        mapped = _soft_map(q, k=10)
        cards = list(mapped.get("cards") or [])
        seed_file, seed_symbol = _pick_seed(cards)
        print(f"  seed={seed_file}::{seed_symbol or '(empty)'}", flush=True)

        arm_out: dict[str, Any] = {}
        baseline_ids: list[str] = []
        for tool, eng in ARMS:
            policy = "broad" if tool == "pack_context_broad" else "strict"
            engine = None if tool == "pack_context_broad" else eng
            # broad uses polytrace via policy; still pass tool_name pack_context
            t0 = time.perf_counter()
            try:
                out = run_pack_context(
                    ROOT,
                    q,
                    seed_file=seed_file,
                    seed_symbol=seed_symbol,
                    mode="lean",
                    policy=policy,
                    engine=engine if tool != "pack_context_broad" else None,
                    tool_name="pack_context" if "pack_context" in tool else tool,
                    include_bodies=False,
                )
                err = out.get("error")
            except Exception as exc:  # noqa: BLE001
                out = {"ok": False, "error": str(exc)}
                err = str(exc)
            ms = (time.perf_counter() - t0) * 1000
            ids = _ids(out)
            if eng == "composite_v1" and tool == "pack_context":
                baseline_ids = ids
            row = {
                "case": cid,
                "family": case.get("family"),
                "tool": tool,
                "engine_req": eng,
                "engine_got": out.get("engine"),
                "ok": bool(out.get("ok")) and not err,
                "wall_ms": round(ms, 1),
                "heatmap_n": len(out.get("heatmap") or out.get("pack") or []),
                "top_ids": ids[:8],
                "jaccard_vs_composite": round(_jaccard(ids, baseline_ids), 3)
                if baseline_ids
                else None,
                "error": err,
            }
            arm_out[tool] = row
            print(
                f"  {tool:22s} ok={row['ok']} {row['wall_ms']:8.1f}ms "
                f"heat={row['heatmap_n']} j={row['jaccard_vs_composite']}",
                flush=True,
            )
        # recompute jaccard now that baseline exists
        base = arm_out.get("pack_context", {}).get("top_ids") or []
        for tool, row in arm_out.items():
            row["jaccard_vs_composite"] = round(_jaccard(row.get("top_ids") or [], base), 3)
        rows.append(
            {
                "case": cid,
                "family": case.get("family"),
                "query": q,
                "seed_file": seed_file,
                "seed_symbol": seed_symbol,
                "arms": arm_out,
            }
        )

    # aggregates
    summary: dict[str, Any] = {}
    for tool, eng in ARMS:
        xs = [c["arms"][tool] for c in rows if tool in c["arms"]]
        ok_n = sum(1 for x in xs if x.get("ok"))
        times = [float(x["wall_ms"]) for x in xs if x.get("ok")]
        jacs = [
            float(x["jaccard_vs_composite"])
            for x in xs
            if x.get("jaccard_vs_composite") is not None and tool != "pack_context"
        ]
        summary[tool] = {
            "engine": eng,
            "ok": f"{ok_n}/{len(xs)}",
            "mean_wall_ms": round(sum(times) / len(times), 1) if times else None,
            "median_wall_ms": round(sorted(times)[len(times) // 2], 1) if times else None,
            "mean_jaccard_vs_composite": round(sum(jacs) / len(jacs), 3) if jacs else (1.0 if tool == "pack_context" else None),
            "speedup_vs_slowest": None,
        }

    ok_means = {
        k: v["mean_wall_ms"]
        for k, v in summary.items()
        if v.get("mean_wall_ms") is not None
    }
    if ok_means:
        slowest = max(ok_means.values())
        fastest = min(ok_means.values())
        for k, v in summary.items():
            m = v.get("mean_wall_ms")
            if m:
                v["ratio_vs_composite"] = round(m / summary["pack_context"]["mean_wall_ms"], 2) if summary["pack_context"].get("mean_wall_ms") else None
                v["vs_slowest_speedup"] = round(slowest / m, 2)

    report = {
        "protocol": "pack_vs_composite_bakeoff_v1",
        "n_cases": len(rows),
        "include_bodies": False,
        "note": "pack_context tool with engine=composite_v1 is the product default; other arms are alternate engines behind the same pack API",
        "summary": summary,
        "cases": rows,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Pack engines bakeoff: composite vs others",
        "",
        f"**Cases:** {len(rows)} (from blind20 triple-pack queries)",
        "**Mode:** lean heatmap-only (`include_bodies=False`) — MCP default",
        "**Same seed** per case from map → `pick_suggested_seed`",
        "",
        "## Summary",
        "",
        "| arm | engine | ok | mean ms | median ms | × vs composite | Jaccard vs composite |",
        "|-----|--------|----|--------:|---------:|---------------:|---------------------:|",
    ]
    for tool, eng in ARMS:
        s = summary[tool]
        lines.append(
            f"| `{tool}` | {eng} | {s['ok']} | {s['mean_wall_ms']} | {s['median_wall_ms']} | "
            f"{s.get('ratio_vs_composite')} | {s.get('mean_jaccard_vs_composite')} |"
        )
    lines += [
        "",
        "## Verdict hints",
        "",
        "- If Jaccard vs composite is high and other arms are slower → ship **pack_context + composite_v1** only.",
        "- `pack_context_broad` is the polytrace escape hatch (policy=broad), not a second default.",
        "",
        f"Raw: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("\n" + "\n".join(lines), flush=True)
    print(f"\nWrote {OUT_JSON}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

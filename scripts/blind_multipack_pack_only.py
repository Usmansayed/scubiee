"""Pack-only continuation: frozen maps → 4-arm pack/trace (no remap)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

MAPS = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-blind-multipack-20-maps.json"
QUERIES = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-blind-multipack-20-queries.json"
OUT_DIR = ROOT / "docs" / "superpowers" / "plans" / "blind_multipack_20_runs"
OUT_JSON = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-blind-multipack-20-results.json"
OUT_MD = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-blind-multipack-20-results.md"

ARMS = (
    "composite_v1",
    "semantic_tracer_fuse",
    "hyb_fuse_demote_noise_plus",
    "poly_embed",
)


def _resolve_seed(
    file: str, symbol: str, nodes: dict, *, query: str = ""
) -> tuple[str, str, str]:
    from trace_lab.types import GoldRef

    file = (file or "").replace("\\", "/")
    symbol = (symbol or "").strip()
    q_toks = {t.lower() for t in (query or "").replace("/", " ").replace(".", " ").split() if len(t) > 2}
    if not file:
        return "", "", "no_file"
    if symbol:
        rid = GoldRef(file=file, symbol=symbol).id
        if rid in nodes:
            return file, symbol, "exact"
        for n in nodes.values():
            if n.file.replace("\\", "/") != file:
                continue
            if n.symbol == symbol or n.symbol.endswith("." + symbol):
                return n.file.replace("\\", "/"), n.symbol, "fuzzy_symbol"
    cands = [
        n
        for n in nodes.values()
        if n.file.replace("\\", "/") == file and n.kind in {"function", "method", "class"}
    ]
    if not cands:
        cands = [n for n in nodes.values() if n.file.replace("\\", "/") == file]
    if not cands:
        return file, "", "file_missing_in_nodes"

    def pref(n):
        k = 0 if n.kind in {"function", "method"} else (1 if n.kind == "class" else 2)
        name = n.symbol.rsplit(".", 1)[-1].lower()
        # Prefer symbols whose names appear in the enrich query (cmd_doctor, unlock, …)
        qhit = -sum(3 for t in q_toks if t in name or name in t)
        bonus = 0
        for hint in (
            "cmd_",
            "run_",
            "bind_",
            "build_",
            "apply_",
            "load",
            "compress",
            "schedule",
            "disconnect",
            "doctor",
            "certify",
            "dashboard",
            "serve",
            "wipe",
            "halt",
            "upgrade",
            "unlock",
            "expand",
            "fingerprint",
        ):
            if name.startswith(hint) or hint in name:
                bonus -= 2
        # Avoid generic cmd_init when query is about something else
        if name in {"cmd_init", "main", "cli"} and qhit == 0:
            bonus += 5
        return (k, qhit, bonus, -len(n.text or ""), n.symbol)

    best = sorted(cands, key=pref)[0]
    return best.file.replace("\\", "/"), best.symbol, "best_in_file"


def main() -> int:
    from trace_lab.prod_eval import _case_with_query_seed
    from trace_lab.sim import HOT_THRESHOLD
    from trace_lab.strategies import compile_bundle
    from trace_lab.types import GoldCase, GoldRef
    from trace_lab.vague_eval import hot_set

    maps = json.loads(MAPS.read_text(encoding="utf-8"))
    q_by = {c["id"]: c for c in json.loads(QUERIES.read_text(encoding="utf-8"))["cases"]}
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"compile_bundle on {ROOT} (REAL CodeRank embeds) …", flush=True)
    t_bundle = time.time()
    nodes, graph, lex, tracers = compile_bundle(
        ROOT,
        with_graphify=True,
        with_embed_power=True,
        require_real_embeds=True,
    )
    print(
        f"bundle ready in {time.time() - t_bundle:.1f}s; nodes={len(nodes)}; "
        f"arms={[a for a in ARMS if a in tracers]}",
        flush=True,
    )

    rows: list[dict[str, Any]] = []
    t0 = time.time()
    for i, mrow in enumerate(maps["rows"], 1):
        cid = mrow["id"]
        case = q_by[cid]
        q = case["enrich_map_query"]
        seed_raw = mrow.get("suggested_seed") or {}
        rf, rs, how = _resolve_seed(
            seed_raw.get("file", ""), seed_raw.get("symbol", ""), nodes, query=q
        )
        print(f"[{i}/20] {cid} seed {rf}::{rs} ({how})", flush=True)

        arm_out: dict[str, Any] = {}
        if rf and rs and GoldRef(file=rf, symbol=rs).id in nodes:
            gold = GoldCase(
                id=cid,
                title=case.get("task") or cid,
                query=q,
                seed=GoldRef(file=rf, symbol=rs),
                must=[],
                should=[],
                must_not=[],
                gold_rank=[],
            )
            seed_text = nodes[gold.seed.id].text or ""
            rich_q = (
                f"{q}\n\n## Seed code anchors\n### Seed 1: {rf}::{rs}\n```\n"
                f"{seed_text.strip()[:2500]}\n```"
            )
            sub = _case_with_query_seed(gold, rich_q, gold.seed)
            for name in ARMS:
                if name not in tracers:
                    arm_out[name] = {"ok": False, "error": "arm_missing"}
                    continue
                t_arm = time.time()
                try:
                    hm = tracers[name](sub, nodes, graph, lex)
                    ranked = hm.ranked_ids()
                    hot = sorted(hot_set(hm, HOT_THRESHOLD))
                    top15 = ranked[:15]
                    pack_like = []
                    for nid in top15:
                        n = nodes.get(nid)
                        if not n:
                            continue
                        pack_like.append(
                            {
                                "id": nid,
                                "file": n.file.replace("\\", "/"),
                                "symbol": n.symbol,
                                "kind": n.kind,
                                "score": next(
                                    (c.score for c in hm.cells if c.node_id == nid),
                                    None,
                                ),
                                "body_chars": len(n.text or ""),
                            }
                        )
                    arm_out[name] = {
                        "ok": True,
                        "elapsed_s": round(time.time() - t_arm, 3),
                        "n_hot": len(hot),
                        "n_ranked": len(ranked),
                        "hot_ids": hot[:40],
                        "top15_ids": top15,
                        "pack_like": pack_like,
                    }
                    print(f"  {name}: hot={len(hot)} ({arm_out[name]['elapsed_s']}s)", flush=True)
                except Exception as e:  # noqa: BLE001
                    arm_out[name] = {
                        "ok": False,
                        "error": f"{type(e).__name__}: {e}",
                        "elapsed_s": round(time.time() - t_arm, 3),
                    }
                    print(f"  {name}: FAIL {arm_out[name]['error']}", flush=True)
        else:
            for name in ARMS:
                arm_out[name] = {"ok": False, "error": "seed_unresolved"}

        row = {
            "id": cid,
            "family": case.get("family"),
            "task": case.get("task"),
            "enrich_map_query": q,
            "map_ok": mrow.get("map_ok"),
            "suggested_seed": seed_raw,
            "resolved_seed": {"file": rf, "symbol": rs, "how": how},
            "map_top_cards": mrow.get("map_top_cards") or [],
            "arms": arm_out,
        }
        rows.append(row)
        (OUT_DIR / f"{cid}_row.json").write_text(json.dumps(row, indent=2)[:400_000], encoding="utf-8")

    result = {
        "protocol": "blind_map_multipack_v2",
        "created": "2026-09-06",
        "elapsed_s": round(time.time() - t0, 2),
        "root": str(ROOT),
        "arms": list(ARMS),
        "n_nodes": len(nodes),
        "queries_file": str(QUERIES),
        "maps_file": str(MAPS),
        "note": "NEW u01–u20; frozen maps; 4-arm pack; REAL CodeRank embeds; phase1",
        "embed_backend": "real:coderank",
        "rows": rows,
    }
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")

    lines = [
        "# Blind map → multi-arm pack (v2, NEW 20 queries)",
        "",
        f"Queries: `{QUERIES.name}` · arms: {', '.join(f'`{a}`' for a in ARMS)}",
        f"Elapsed pack: {result['elapsed_s']}s · nodes: {result['n_nodes']}",
        "",
        "Phase 1 — no ground truth. Same enrich query + map seed for every arm.",
        "",
        "| ID | Family | Seed | " + " | ".join(ARMS) + " |",
        "|----|--------|------|" + "|".join(["------"] * len(ARMS)) + "|",
    ]
    for r in rows:
        seed = r["resolved_seed"]
        seed_s = f"{seed.get('file','')}::{seed.get('symbol','')}"[-52:]
        cells = []
        for a in ARMS:
            arm = r["arms"].get(a) or {}
            cells.append(f"hot={arm.get('n_hot')}" if arm.get("ok") else "FAIL")
        lines.append(f"| `{r['id']}` | {r.get('family')} | `{seed_s}` | " + " | ".join(cells) + " |")
    lines += ["", "## Per case top-5", ""]
    for r in rows:
        lines.append(f"### `{r['id']}` — {r.get('family')}")
        rs = r["resolved_seed"]
        lines.append(f"- seed: `{rs.get('file')}::{rs.get('symbol')}` ({rs.get('how')})")
        for a in ARMS:
            arm = r["arms"].get(a) or {}
            if not arm.get("ok"):
                lines.append(f"- `{a}`: FAIL {arm.get('error')}")
                continue
            tops = [x.split("::")[-1] for x in (arm.get("top15_ids") or [])[:5]]
            lines.append(f"- `{a}`: hot={arm.get('n_hot')} top5={tops}")
        lines.append("")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT_JSON}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

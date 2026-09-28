"""Blind map → multi-arm pack on 20 NEW queries (u01–u20).

Phase 1: map once per case → freeze seed → run 4 pack/trace arms.
No ground-truth scoring in this script.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages"))

SCUBIEE = ROOT / ".venv" / "Scripts" / "scubiee.exe"
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


def _run_cli(args: list[str], timeout: int = 180) -> dict[str, Any]:
    t0 = time.time()
    try:
        proc = subprocess.run(
            args,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "PYTHONPATH": str(ROOT / "packages")},
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        parsed = None
        if out:
            try:
                parsed = json.loads(out)
            except json.JSONDecodeError:
                start = out.find("{")
                end = out.rfind("}")
                if start >= 0 and end > start:
                    try:
                        parsed = json.loads(out[start : end + 1])
                    except json.JSONDecodeError:
                        parsed = None
        return {
            "ok": proc.returncode == 0 and parsed is not None,
            "returncode": proc.returncode,
            "elapsed_s": round(time.time() - t0, 3),
            "stderr_tail": err[-800:] if err else "",
            "json": parsed,
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": -1,
            "elapsed_s": round(time.time() - t0, 3),
            "stderr_tail": "TIMEOUT",
            "json": None,
        }


def _pick_seed(map_json: dict[str, Any] | None) -> dict[str, Any]:
    if not map_json:
        return {"file": "", "symbol": "", "source": "missing"}
    sug = map_json.get("suggested_seed") or {}
    if isinstance(sug, dict) and sug.get("file"):
        return {
            "file": str(sug.get("file") or "").replace("\\", "/"),
            "symbol": str(sug.get("symbol") or ""),
            "source": "suggested_seed",
        }
    cards = map_json.get("cards") or map_json.get("results") or []
    if cards and isinstance(cards[0], dict):
        c0 = cards[0]
        return {
            "file": str(c0.get("file") or "").replace("\\", "/"),
            "symbol": str(c0.get("symbol") or ""),
            "source": "cards[0]",
        }
    return {"file": "", "symbol": "", "source": "none"}


def _map_top_cards(map_json: dict[str, Any] | None, k: int = 8) -> list[dict[str, Any]]:
    if not map_json:
        return []
    cards = map_json.get("cards") or map_json.get("results") or []
    out = []
    for c in cards[:k]:
        if not isinstance(c, dict):
            continue
        out.append(
            {
                "file": str(c.get("file") or "").replace("\\", "/"),
                "symbol": str(c.get("symbol") or ""),
                "loc": c.get("loc")
                or f"{c.get('file')}:{c.get('start_line')}-{c.get('end_line')}",
                "score": c.get("score"),
                "heat": c.get("heat"),
            }
        )
    return out


def _resolve_seed(file: str, symbol: str, nodes: dict) -> tuple[str, str, str]:
    """Return (file, symbol, how) that exists in nodes, or empty."""
    from trace_lab.types import GoldRef

    file = (file or "").replace("\\", "/")
    symbol = (symbol or "").strip()
    if not file:
        return "", "", "no_file"
    if symbol:
        rid = GoldRef(file=file, symbol=symbol).id
        if rid in nodes:
            return file, symbol, "exact"
        # fuzzy: symbol suffix match in same file
        for nid, n in nodes.items():
            if n.file.replace("\\", "/") != file:
                continue
            if n.symbol == symbol or n.symbol.endswith("." + symbol) or symbol.endswith("." + n.symbol):
                return n.file.replace("\\", "/"), n.symbol, "fuzzy_symbol"

    # Prefer function/method in file; skip ROOT / module-level junk
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
        # prefer names that look like entrypoints
        name = n.symbol.rsplit(".", 1)[-1].lower()
        bonus = 0
        for hint in ("cmd_", "run_", "main", "bind_", "build_", "apply_", "load"):
            if name.startswith(hint) or hint in name:
                bonus -= 1
        return (k, bonus, -len(n.text or ""), n.symbol)

    best = sorted(cands, key=pref)[0]
    return best.file.replace("\\", "/"), best.symbol, "best_in_file"


def main() -> int:
    from trace_lab.sim import HOT_THRESHOLD
    from trace_lab.strategies import compile_bundle
    from trace_lab.types import GoldCase, GoldRef
    from trace_lab.vague_eval import hot_set

    spec = json.loads(QUERIES.read_text(encoding="utf-8"))
    cases = spec["cases"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"compile_bundle on {ROOT} …", flush=True)
    t_bundle = time.time()
    nodes, graph, lex, tracers = compile_bundle(
        ROOT,
        with_graphify=True,
        with_embed_power=True,
        require_real_embeds=False,
    )
    missing_arms = [a for a in ARMS if a not in tracers]
    print(
        f"bundle ready in {time.time() - t_bundle:.1f}s; "
        f"nodes={len(nodes)} arms_ok={ [a for a in ARMS if a in tracers] } missing={missing_arms}",
        flush=True,
    )

    rows: list[dict[str, Any]] = []
    t0 = time.time()

    for i, case in enumerate(cases, 1):
        cid = case["id"]
        q = case["enrich_map_query"]
        print(f"\n[{i}/{len(cases)}] {cid} map…", flush=True)
        map_res = _run_cli([str(SCUBIEE), "map", q, "--k", "10"], timeout=240)
        (OUT_DIR / f"{cid}_map.json").write_text(
            json.dumps(map_res, indent=2)[:500_000], encoding="utf-8"
        )
        seed_raw = _pick_seed(map_res.get("json"))
        rf, rs, how = _resolve_seed(seed_raw["file"], seed_raw["symbol"], nodes)
        print(
            f"  seed map={seed_raw['file']}::{seed_raw['symbol']} → "
            f"resolved={rf}::{rs} ({how})",
            flush=True,
        )

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
            # Attach seed body as lean pack would (code vocab + anchor)
            seed_text = nodes[gold.seed.id].text or ""
            rich_q = (
                f"{q}\n\n## Seed code anchors\n### Seed 1: {rf}::{rs}\n```\n"
                f"{seed_text.strip()[:2500]}\n```"
            )
            from trace_lab.prod_eval import _case_with_query_seed

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
                        "strategy": getattr(hm, "strategy", name),
                    }
                    print(
                        f"  {name}: hot={len(hot)} top={top15[:3]} "
                        f"({arm_out[name]['elapsed_s']}s)",
                        flush=True,
                    )
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
            "map_ok": bool(map_res.get("ok")),
            "map_elapsed_s": map_res.get("elapsed_s"),
            "suggested_seed": seed_raw,
            "resolved_seed": {"file": rf, "symbol": rs, "how": how},
            "map_top_cards": _map_top_cards(map_res.get("json")),
            "arms": arm_out,
        }
        rows.append(row)
        (OUT_DIR / f"{cid}_row.json").write_text(
            json.dumps(row, indent=2)[:400_000], encoding="utf-8"
        )

    result = {
        "protocol": "blind_map_multipack_v2",
        "created": "2026-09-06",
        "elapsed_s": round(time.time() - t0, 2),
        "root": str(ROOT),
        "arms": list(ARMS),
        "n_nodes": len(nodes),
        "queries_file": str(QUERIES),
        "note": "NEW u01–u20 queries; multi-arm pack after map; no GT in phase 1",
        "rows": rows,
    }
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")

    lines = [
        "# Blind map → multi-arm pack (v2, NEW 20 queries)",
        "",
        f"Queries: `{QUERIES.name}` · arms: {', '.join(f'`{a}`' for a in ARMS)}",
        f"Elapsed: {result['elapsed_s']}s · nodes: {result['n_nodes']}",
        "",
        "Phase 1 only — no ground truth. Same enrich query + map seed for every arm.",
        "",
        "| ID | Family | Seed | " + " | ".join(ARMS) + " |",
        "|----|--------|------|" + "|".join(["------"] * len(ARMS)) + "|",
    ]
    for r in rows:
        seed = r["resolved_seed"]
        seed_s = f"{seed.get('file','')}::{seed.get('symbol','')}"[-48:]
        cells = []
        for a in ARMS:
            arm = r["arms"].get(a) or {}
            if arm.get("ok"):
                cells.append(f"hot={arm.get('n_hot')}")
            else:
                cells.append("FAIL")
        lines.append(
            f"| `{r['id']}` | {r.get('family')} | `{seed_s}` | " + " | ".join(cells) + " |"
        )
    lines += ["", "## Per case top-5 (composite vs candidate)", ""]
    for r in rows:
        lines.append(f"### `{r['id']}` — {r.get('family')}")
        lines.append(f"- task: {r.get('task')}")
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
    print(f"\nWrote {OUT_JSON} and {OUT_MD}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

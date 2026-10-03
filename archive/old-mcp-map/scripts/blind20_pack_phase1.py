"""Blind-20 Phase 1: enrich map → seed chunks → all pack arms → freeze (NO GT).

Queries authored without codebase inspection. Do not score until Phase 2.

Usage:
  python scripts/blind20_pack_phase1.py
  python scripts/blind20_pack_phase1.py --ids r01 r02
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QUERIES = ROOT / "docs/superpowers/plans/2026-09-06-blind20-pack-queries.json"
OUT_DIR = ROOT / "docs/superpowers/plans/blind20_pack_runs"
MAPS_JSON = ROOT / "docs/superpowers/plans/2026-09-06-blind20-pack-maps.json"
RESULTS = ROOT / "docs/superpowers/plans/2026-09-06-blind20-pack-results.json"
RESULTS_MD = ROOT / "docs/superpowers/plans/2026-09-06-blind20-pack-results.md"
SCUBIEE = ROOT / ".venv" / "Scripts" / "scubiee.exe"


def _require_phase0() -> dict[str, Any]:
    import importlib.util

    sys.path.insert(0, str(ROOT / "packages"))
    spec = importlib.util.spec_from_file_location(
        "venture_preflight", ROOT / "scripts" / "venture_preflight.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from trace_lab.cases import default_fixture_root

    rep = mod.preflight(fixture_root=default_fixture_root().resolve(), require_faiss=True)
    if not rep.get("ok"):
        raise SystemExit(f"PHASE0 FAIL: {rep.get('blockers')}")
    return rep


def _run_json(cmd: list[str]) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "packages")
    env["CTX_TRUST_ID_FILE"] = "1"
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    raw = (proc.stdout or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(
            f"rc={proc.returncode} cmd={' '.join(cmd)}\n"
            f"stderr={(proc.stderr or '')[-1500:]}\nstdout={raw[-1500:]}"
        )
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError(f"no JSON from {' '.join(cmd)}: {raw[:400]}")
    return json.loads(raw[start : end + 1])


def _resolve_seed(file: str, symbol: str, nodes: dict, *, query: str = "") -> tuple[str, str, str]:
    from trace_lab.types import GoldRef

    file = (file or "").replace("\\", "/")
    symbol = (symbol or "").strip()
    q_toks = {
        t.lower()
        for t in (query or "").replace("/", " ").replace(".", " ").split()
        if len(t) > 2
    }
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
        qhit = -sum(3 for t in q_toks if t in name or name in t)
        return (k, qhit, -len(n.text or ""), n.symbol)

    best = sorted(cands, key=pref)[0]
    return best.file.replace("\\", "/"), best.symbol, "best_in_file"


def _cards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return list(payload.get("cards") or payload.get("results") or [])


def map_all(cases: list[dict[str, Any]]) -> dict[str, Any]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, case in enumerate(cases, 1):
        cid = case["id"]
        q = case["enrich_prompt"]
        print(f"[map {i}/{len(cases)}] {cid}", flush=True)
        t0 = time.time()
        try:
            payload = _run_json(
                [str(SCUBIEE), "map", q, str(ROOT), "--k", "10", "--local"]
            )
            cards = _cards(payload)
            seed = payload.get("suggested_seed") or {}
            if not seed and cards:
                c0 = cards[0]
                seed = {
                    "file": c0.get("file"),
                    "symbol": c0.get("symbol"),
                    "line": c0.get("start_line"),
                }
            chunks = [
                {
                    "file": c.get("file"),
                    "symbol": c.get("symbol"),
                    "loc": c.get("loc"),
                    "score": c.get("score"),
                    "start_line": c.get("start_line"),
                    "end_line": c.get("end_line"),
                }
                for c in cards[:10]
            ]
            row = {
                "id": cid,
                "map_ok": True,
                "elapsed_s": round(time.time() - t0, 2),
                "suggested_seed": seed,
                "chunks": chunks,
                "map_top_cards": chunks,
                "n_cards": len(cards),
            }
            (OUT_DIR / f"{cid}_map.json").write_text(
                json.dumps(payload, indent=2)[:500_000], encoding="utf-8"
            )
            (OUT_DIR / f"{cid}_chunks.json").write_text(
                json.dumps(
                    {"id": cid, "enrich_prompt": q, "suggested_seed": seed, "chunks": chunks},
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            row = {
                "id": cid,
                "map_ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_s": round(time.time() - t0, 2),
                "suggested_seed": {},
                "chunks": [],
                "map_top_cards": [],
                "n_cards": 0,
            }
            print(f"  MAP FAIL {row['error']}", flush=True)
        rows.append(row)
    out = {
        "protocol": "blind20_pack_compare_v1_maps",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rows": rows,
    }
    MAPS_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def pack_all(
    cases: list[dict[str, Any]],
    maps: dict[str, Any],
    arms: list[str],
) -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "packages"))
    from trace_lab.prod_eval import _case_with_query_seed
    from trace_lab.sim import HOT_THRESHOLD
    from trace_lab.strategies import compile_bundle
    from trace_lab.types import GoldCase, GoldRef
    from trace_lab.vague_eval import hot_set

    print(f"compile_bundle on {ROOT} (real embeds) …", flush=True)
    t_bundle = time.time()
    nodes, graph, lex, tracers = compile_bundle(
        ROOT,
        with_graphify=True,
        with_embed_power=True,
        require_real_embeds=True,
    )
    print(
        f"bundle {time.time() - t_bundle:.1f}s nodes={len(nodes)} "
        f"arms_present={[a for a in arms if a in tracers]}",
        flush=True,
    )

    map_by = {r["id"]: r for r in maps["rows"]}
    q_by = {c["id"]: c for c in cases}
    rows: list[dict[str, Any]] = []
    t0 = time.time()

    for i, cid in enumerate([c["id"] for c in cases], 1):
        case = q_by[cid]
        mrow = map_by.get(cid) or {}
        q = case["enrich_prompt"]
        seed_raw = mrow.get("suggested_seed") or {}
        rf, rs, how = _resolve_seed(
            str(seed_raw.get("file") or ""),
            str(seed_raw.get("symbol") or ""),
            nodes,
            query=q,
        )
        print(f"[pack {i}/{len(cases)}] {cid} seed={rf}::{rs} ({how})", flush=True)

        # Also run production CLI pack (composite) for parity with agent ladder
        cli_pack: dict[str, Any] = {"ok": False}
        if rf and mrow.get("map_ok"):
            t_cli = time.time()
            try:
                cmd = [
                    str(SCUBIEE),
                    "pack",
                    q,
                    str(ROOT),
                    "--seed-file",
                    rf,
                    "--mode",
                    "lean",
                ]
                if rs:
                    cmd.extend(["--seed-symbol", rs])
                payload = _run_json(cmd)
                pack_items = payload.get("pack") or []
                cli_pack = {
                    "ok": True,
                    "elapsed_s": round(time.time() - t_cli, 3),
                    "n_pack": len(pack_items),
                    "pack": [
                        {
                            "file": (x.get("file") or "").replace("\\", "/"),
                            "symbol": x.get("symbol"),
                            "score": x.get("score"),
                        }
                        for x in pack_items[:20]
                    ],
                }
                (OUT_DIR / f"{cid}_pack_cli_composite_v1.json").write_text(
                    json.dumps(payload, indent=2)[:500_000], encoding="utf-8"
                )
            except Exception as exc:  # noqa: BLE001
                cli_pack = {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_s": round(time.time() - t_cli, 3),
                }

        arm_out: dict[str, Any] = {"cli_composite_v1": cli_pack}
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
            # Enrich with map chunk bodies (seed + top cards present in nodes)
            anchors = [f"### Seed: {rf}::{rs}\n```\n{(nodes[gold.seed.id].text or '')[:2500]}\n```"]
            for ch in (mrow.get("chunks") or [])[:5]:
                cf = str(ch.get("file") or "").replace("\\", "/")
                cs = str(ch.get("symbol") or "")
                if not cf:
                    continue
                rid = GoldRef(file=cf, symbol=cs).id if cs else ""
                n = nodes.get(rid) if rid else None
                if n is None:
                    for cand in nodes.values():
                        if cand.file.replace("\\", "/") == cf and (
                            not cs or cand.symbol.endswith(cs)
                        ):
                            n = cand
                            break
                if n:
                    anchors.append(
                        f"### Map chunk: {n.file}::{n.symbol}\n```\n{(n.text or '')[:1200]}\n```"
                    )
            rich_q = f"{q}\n\n## Seed code anchors\n" + "\n".join(anchors)
            sub = _case_with_query_seed(gold, rich_q, gold.seed)
            for name in arms:
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
                    print(
                        f"  {name}: hot={len(hot)} ({arm_out[name]['elapsed_s']}s)",
                        flush=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    arm_out[name] = {
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "elapsed_s": round(time.time() - t_arm, 3),
                    }
                    print(f"  {name}: FAIL {arm_out[name]['error']}", flush=True)
        else:
            for name in arms:
                arm_out[name] = {"ok": False, "error": "seed_unresolved"}

        row = {
            "id": cid,
            "family": case.get("family"),
            "task": case.get("task"),
            "enrich_prompt": q,
            "map_ok": mrow.get("map_ok"),
            "suggested_seed": seed_raw,
            "resolved_seed": {"file": rf, "symbol": rs, "how": how},
            "map_chunks": mrow.get("chunks") or [],
            "arms": arm_out,
        }
        rows.append(row)
        (OUT_DIR / f"{cid}_row.json").write_text(
            json.dumps(row, indent=2)[:600_000], encoding="utf-8"
        )

    result = {
        "protocol": "blind20_pack_compare_v1_phase1",
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scored": False,
        "elapsed_s": round(time.time() - t0, 2),
        "root": str(ROOT),
        "arms": arms,
        "also_cli_pack": "cli_composite_v1",
        "n_nodes": len(nodes),
        "queries_file": str(QUERIES.relative_to(ROOT)).replace("\\", "/"),
        "maps_file": str(MAPS_JSON.relative_to(ROOT)).replace("\\", "/"),
        "note": "FROZEN — no GT yet. Author GT only after this file exists.",
        "rows": rows,
    }
    RESULTS.write_text(json.dumps(result, indent=2), encoding="utf-8")

    lines = [
        "# Blind-20 map → multi-arm pack (Phase 1 freeze)",
        "",
        f"Arms: {', '.join(f'`{a}`' for a in arms)} + `cli_composite_v1`",
        f"Elapsed pack loop: {result['elapsed_s']}s · AST nodes: {result['n_nodes']}",
        "",
        "**No ground truth yet.**",
        "",
    ]
    for r in rows:
        rs = r["resolved_seed"]
        lines.append(f"### `{r['id']}` — {r.get('family')}")
        lines.append(f"- seed: `{rs.get('file')}::{rs.get('symbol')}` ({rs.get('how')})")
        for a, arm in r["arms"].items():
            if not arm.get("ok"):
                lines.append(f"- `{a}`: FAIL {arm.get('error')}")
            elif "n_hot" in arm:
                tops = [x.split("::")[-1] for x in (arm.get("top15_ids") or [])[:5]]
                lines.append(f"- `{a}`: hot={arm.get('n_hot')} top5={tops}")
            else:
                lines.append(f"- `{a}`: n_pack={arm.get('n_pack')}")
        lines.append("")
    RESULTS_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {RESULTS}", flush=True)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", default=None)
    ap.add_argument("--skip-phase0", action="store_true")
    ap.add_argument("--maps-only", action="store_true")
    ap.add_argument("--pack-only", action="store_true", help="Reuse frozen maps JSON")
    args = ap.parse_args()

    if not SCUBIEE.is_file():
        print(f"missing {SCUBIEE}", file=sys.stderr)
        return 2

    bundle = json.loads(QUERIES.read_text(encoding="utf-8"))
    cases = bundle["cases"]
    arms = list(bundle.get("arms") or [])
    if args.ids:
        want = set(args.ids)
        cases = [c for c in cases if c["id"] in want]

    if not args.skip_phase0 and not args.pack_only:
        print("Phase0 gate…", flush=True)
        p0 = _require_phase0()
        print(
            "Phase0 OK",
            p0.get("faiss_product_repo", {}).get("n_hits"),
            "hits meta=",
            p0.get("faiss_product_repo", {}).get("meta_root"),
            flush=True,
        )

    if args.pack_only:
        maps = json.loads(MAPS_JSON.read_text(encoding="utf-8"))
    else:
        maps = map_all(cases)
        if args.maps_only:
            print(f"Maps frozen → {MAPS_JSON}")
            return 0

    pack_all(cases, maps, arms)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

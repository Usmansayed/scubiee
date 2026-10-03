"""Blind map→pack runner: NO correctness scoring.

For each case: enrich map query → suggested_seed → pack(same query, lean).
Writes raw artifacts only.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCUBIEE = ROOT / ".venv" / "Scripts" / "scubiee.exe"
QUERIES = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-blind-map-pack-20-queries.json"
OUT_DIR = ROOT / "docs" / "superpowers" / "plans" / "blind_map_pack_20_runs"
OUT_JSON = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-blind-map-pack-20-results.json"
OUT_MD = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-blind-map-pack-20-results.md"


def _run(args: list[str], timeout: int = 180) -> dict[str, Any]:
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
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        parsed = None
        if out:
            try:
                parsed = json.loads(out)
            except json.JSONDecodeError:
                # sometimes CLI wraps or adds logs — try last {...}
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
            "stdout_chars": len(out),
            "stderr_tail": err[-800:] if err else "",
            "json": parsed,
            "stdout_preview": out[:400] if parsed is None else "",
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "returncode": -1,
            "elapsed_s": round(time.time() - t0, 3),
            "stdout_chars": 0,
            "stderr_tail": "TIMEOUT",
            "json": None,
            "stdout_preview": "",
        }


def _pick_seed(map_json: dict[str, Any] | None) -> dict[str, Any]:
    if not map_json:
        return {"file": "", "symbol": "", "source": "missing"}
    sug = map_json.get("suggested_seed") or {}
    if isinstance(sug, dict) and sug.get("file"):
        return {
            "file": str(sug.get("file") or ""),
            "symbol": str(sug.get("symbol") or ""),
            "source": "suggested_seed",
        }
    cards = map_json.get("cards") or map_json.get("results") or []
    if cards and isinstance(cards[0], dict):
        c0 = cards[0]
        return {
            "file": str(c0.get("file") or ""),
            "symbol": str(c0.get("symbol") or ""),
            "source": "cards[0]",
        }
    return {"file": "", "symbol": "", "source": "none"}


def _summarize_pack(pack_json: dict[str, Any] | None) -> dict[str, Any]:
    if not pack_json:
        return {"n_pack": 0, "n_chain": 0, "pack_ids": [], "card_locs": []}
    pack = pack_json.get("pack") or []
    chain = pack_json.get("chain") or []
    cards = pack_json.get("cards") or pack_json.get("heatmap") or []
    pack_ids = []
    for p in pack:
        if isinstance(p, dict):
            pack_ids.append(
                p.get("id")
                or p.get("node_id")
                or f"{p.get('file', '')}::{p.get('symbol', '')}"
            )
    locs = []
    for c in cards[:15]:
        if isinstance(c, dict) and c.get("loc"):
            locs.append(c["loc"])
        elif isinstance(c, dict) and c.get("file"):
            locs.append(
                f"{c.get('file')}:{c.get('start_line', '?')}-{c.get('end_line', '?')}"
            )
    return {
        "n_pack": len(pack),
        "n_chain": len(chain) if isinstance(chain, list) else 0,
        "pack_ids": pack_ids[:20],
        "card_locs": locs,
        "mode": pack_json.get("mode") or (pack_json.get("extra") or {}).get("mode"),
        "strategy": pack_json.get("strategy")
        or (pack_json.get("extra") or {}).get("engine"),
    }


def main() -> int:
    if not SCUBIEE.exists():
        raise SystemExit(f"missing scubiee at {SCUBIEE}")
    spec = json.loads(QUERIES.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    t_all = time.time()

    for case in spec["cases"]:
        cid = case["id"]
        q = case["enrich_map_query"]
        print(f"=== {cid} map ===", flush=True)
        map_res = _run(
            [str(SCUBIEE), "map", q, str(ROOT), "--k", "10"],
            timeout=240,
        )
        seed = _pick_seed(map_res.get("json"))
        (OUT_DIR / f"{cid}_map.json").write_text(
            json.dumps(map_res, indent=2), encoding="utf-8"
        )

        pack_res: dict[str, Any]
        if not seed.get("file"):
            pack_res = {
                "ok": False,
                "returncode": -2,
                "elapsed_s": 0,
                "stderr_tail": "no seed from map",
                "json": None,
            }
        else:
            print(f"=== {cid} pack seed={seed['file']}::{seed.get('symbol')} ===", flush=True)
            args = [
                str(SCUBIEE),
                "pack",
                q,
                str(ROOT),
                "--seed-file",
                seed["file"],
                "--mode",
                "lean",
            ]
            if seed.get("symbol"):
                args.extend(["--seed-symbol", seed["symbol"]])
            pack_res = _run(args, timeout=300)
        (OUT_DIR / f"{cid}_pack.json").write_text(
            json.dumps(pack_res, indent=2), encoding="utf-8"
        )

        pack_sum = _summarize_pack(pack_res.get("json"))
        map_cards = []
        mj = map_res.get("json") or {}
        for c in (mj.get("cards") or [])[:10]:
            if isinstance(c, dict):
                map_cards.append(
                    {
                        "file": c.get("file"),
                        "symbol": c.get("symbol"),
                        "loc": c.get("loc"),
                        "score": c.get("score"),
                        "rank": c.get("rank"),
                    }
                )

        row = {
            "id": cid,
            "family": case.get("family"),
            "task": case.get("task"),
            "enrich_map_query": q,
            "map_ok": map_res.get("ok"),
            "map_elapsed_s": map_res.get("elapsed_s"),
            "suggested_seed": seed,
            "map_top_cards": map_cards,
            "pack_ok": pack_res.get("ok"),
            "pack_elapsed_s": pack_res.get("elapsed_s"),
            "pack_summary": pack_sum,
            "map_stderr_tail": map_res.get("stderr_tail"),
            "pack_stderr_tail": pack_res.get("stderr_tail"),
        }
        rows.append(row)
        print(
            f"--- {cid} map_ok={row['map_ok']} pack_ok={row['pack_ok']} "
            f"seed={seed.get('file')}::{seed.get('symbol')} "
            f"n_pack={pack_sum.get('n_pack')}",
            flush=True,
        )

    result = {
        "protocol": "blind_map_pack_v1",
        "phase": "run_only_no_correctness",
        "elapsed_s": round(time.time() - t_all, 2),
        "scubiee": str(SCUBIEE),
        "n": len(rows),
        "n_map_ok": sum(1 for r in rows if r["map_ok"]),
        "n_pack_ok": sum(1 for r in rows if r["pack_ok"]),
        "rows": rows,
    }
    OUT_JSON.write_text(json.dumps(result, indent=2), encoding="utf-8")

    lines = [
        "# Blind map→pack 20 (no correctness eval)",
        "",
        f"Elapsed {result['elapsed_s']}s · map_ok {result['n_map_ok']}/20 · pack_ok {result['n_pack_ok']}/20",
        "",
        "Phase 1 only: enrich query → map seed → pack. Ground-truth comparison is deferred.",
        "",
        "| ID | Family | Map | Pack | Seed | n_pack |",
        "|----|--------|-----|------|------|--------|",
    ]
    for r in rows:
        s = r["suggested_seed"]
        seed_s = f"{s.get('file', '')}::{s.get('symbol', '')}" if s.get("file") else "—"
        lines.append(
            f"| `{r['id']}` | {r['family']} | {r['map_ok']} | {r['pack_ok']} | "
            f"`{seed_s}` | {r['pack_summary'].get('n_pack', 0)} |"
        )
    lines += ["", "## Queries + seeds", ""]
    for r in rows:
        lines.append(f"### `{r['id']}` — {r['family']}")
        lines.append("")
        lines.append(f"- Task: {r['task']}")
        lines.append(f"- Enrich query: `{r['enrich_map_query']}`")
        s = r["suggested_seed"]
        lines.append(
            f"- Seed ({s.get('source')}): `{s.get('file')}::{s.get('symbol')}`"
        )
        lines.append(f"- Pack bodies: {r['pack_summary'].get('n_pack')} · "
                     f"ids: {', '.join(str(x) for x in (r['pack_summary'].get('pack_ids') or [])[:8])}")
        lines.append("")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "elapsed_s": result["elapsed_s"],
        "n_map_ok": result["n_map_ok"],
        "n_pack_ok": result["n_pack_ok"],
        "report": str(OUT_MD),
        "json": str(OUT_JSON),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

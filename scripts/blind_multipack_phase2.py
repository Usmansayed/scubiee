"""Phase 2: score frozen multipack arms vs independent GT."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs/superpowers/plans/2026-09-06-blind-multipack-20-results.json"
GT = ROOT / "docs/superpowers/plans/2026-09-06-blind-multipack-20-ground-truth.json"
OUT_JSON = ROOT / "docs/superpowers/plans/2026-09-06-blind-multipack-20-phase2.json"
OUT_MD = ROOT / "docs/superpowers/plans/2026-09-06-blind-multipack-20-phase2.md"


def _norm(p: str) -> str:
    return p.replace("\\", "/").lstrip("./")


def _file_of(node_id: str) -> str:
    return _norm(node_id.split("::", 1)[0])


def _map_files(row: dict[str, Any]) -> set[str]:
    files: set[str] = set()
    seed = row.get("suggested_seed") or {}
    if seed.get("file"):
        files.add(_norm(seed["file"]))
    rs = row.get("resolved_seed") or {}
    if rs.get("file"):
        files.add(_norm(rs["file"]))
    for c in row.get("map_top_cards") or []:
        if c.get("file"):
            files.add(_norm(c["file"]))
    return files


def _arm_ids(arm: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for x in arm.get("top15_ids") or []:
        ids.add(_norm(str(x)))
    for x in arm.get("hot_ids") or []:
        ids.add(_norm(str(x)))
    for p in arm.get("pack_like") or []:
        if isinstance(p, dict) and p.get("id"):
            ids.add(_norm(str(p["id"])))
    return ids


def _recall(hit: set[str], need: list[str]) -> float:
    if not need:
        return 1.0
    n = {_norm(x) for x in need}
    return len(hit & n) / len(n)


def main() -> int:
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    ground = json.loads(GT.read_text(encoding="utf-8"))["cases"]
    arms = results.get("arms") or list(
        (results["rows"][0].get("arms") or {}).keys()
    )

    per_arm_rows: dict[str, list[dict[str, Any]]] = {a: [] for a in arms}
    seed_rows = []

    for row in results["rows"]:
        cid = row["id"]
        gt = ground[cid]
        must_files = [_norm(x) for x in gt["must_files"]]
        should_files = [_norm(x) for x in gt.get("should_files") or []]
        must_syms = [_norm(x) for x in gt.get("must_symbols") or []]
        map_files = _map_files(row)
        rs = row.get("resolved_seed") or {}
        seed_file = _norm(rs.get("file") or "")
        seed_sym = _norm(f"{rs.get('file','')}::{rs.get('symbol','')}") if rs.get("symbol") else ""
        seed_ok = seed_file in must_files if must_files else bool(seed_file)
        seed_rows.append(
            {
                "id": cid,
                "seed": f"{rs.get('file')}::{rs.get('symbol')}",
                "seed_in_must_files": seed_ok,
                "map_must_file_recall": round(_recall(map_files, must_files), 4),
            }
        )

        for name in arms:
            arm = (row.get("arms") or {}).get(name) or {}
            if not arm.get("ok"):
                per_arm_rows[name].append(
                    {
                        "id": cid,
                        "ok": False,
                        "pack_must_file_recall": 0.0,
                        "pack_must_symbol_recall": 0.0,
                        "union_must_file_recall": round(_recall(map_files, must_files), 4),
                        "n_hot": 0,
                        "thin": True,
                        "missing_must_files": must_files,
                        "missing_must_symbols": must_syms,
                    }
                )
                continue
            ids = _arm_ids(arm)
            pack_files = {_file_of(x) for x in ids}
            union = map_files | pack_files
            n_hot = int(arm.get("n_hot") or 0)
            rec = {
                "id": cid,
                "ok": True,
                "pack_must_file_recall": round(_recall(pack_files, must_files), 4),
                "pack_must_symbol_recall": round(_recall(ids, must_syms), 4),
                "union_must_file_recall": round(_recall(union, must_files), 4),
                "should_file_hit": round(_recall(union, should_files), 4) if should_files else None,
                "n_hot": n_hot,
                "thin": n_hot <= 3,
                "missing_must_files": [f for f in must_files if f not in union],
                "missing_must_symbols": [s for s in must_syms if s not in ids],
                "top5": [x.split("::")[-1] for x in (arm.get("top15_ids") or [])[:5]],
            }
            per_arm_rows[name].append(rec)

    summary = {}
    for name, rows in per_arm_rows.items():
        n = len(rows)
        def avg(key: str) -> float:
            return round(sum(r[key] for r in rows) / max(n, 1), 4)

        summary[name] = {
            "n": n,
            "mean_pack_must_file": avg("pack_must_file_recall"),
            "mean_pack_must_symbol": avg("pack_must_symbol_recall"),
            "mean_union_must_file": avg("union_must_file_recall"),
            "mean_n_hot": avg("n_hot"),
            "thin_packs": sum(1 for r in rows if r.get("thin")),
            "seed_ok_rate": round(
                sum(1 for s in seed_rows if s["seed_in_must_files"]) / max(len(seed_rows), 1), 4
            ),
            "map_must_file": round(
                sum(s["map_must_file_recall"] for s in seed_rows) / max(len(seed_rows), 1), 4
            ),
        }

    ranked = sorted(
        summary.items(),
        key=lambda kv: (
            -kv[1]["mean_pack_must_symbol"],
            -kv[1]["mean_pack_must_file"],
            kv[1]["thin_packs"],
            kv[1]["mean_n_hot"],  # prefer tighter when tied on recall
        ),
    )
    winner = ranked[0][0] if ranked else None

    out = {
        "protocol": "blind_multipack_v2_phase2",
        "winner": winner,
        "embed_note": results.get("embed_backend")
        or results.get("note")
        or "see results note",
        "summary": summary,
        "ranked": [a for a, _ in ranked],
        "seeds": seed_rows,
        "per_arm": {a: per_arm_rows[a] for a in arms},
    }
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    lines = [
        "# Blind multipack phase-2 (NEW 20 · 4 arms)",
        "",
        f"Winner by pack must-symbol then must-file: **`{winner}`**",
        "",
        f"Embed note: {out['embed_note']}",
        "",
        "Shared map seeds across arms. Score = coverage of independent must files/symbols in pack top15∪hot.",
        "",
        "| Arm | Pack must-file | Pack must-sym | Union must-file | Mean hot | Thin≤3 |",
        "|-----|----------------|---------------|-----------------|----------|--------|",
    ]
    for name, st in ranked:
        lines.append(
            f"| `{name}` | {st['mean_pack_must_file']:.3f} | {st['mean_pack_must_symbol']:.3f} | "
            f"{st['mean_union_must_file']:.3f} | {st['mean_n_hot']:.1f} | {st['thin_packs']}/20 |"
        )
    lines += [
        "",
        f"Map must-file (shared): {summary[arms[0]]['map_must_file']:.3f} · "
        f"seed in must-files: {summary[arms[0]]['seed_ok_rate']:.3f}",
        "",
        "## Per case (winner vs composite)",
        "",
    ]
    base = "composite_v1"
    for i, seed in enumerate(seed_rows):
        cid = seed["id"]
        lines.append(f"### `{cid}` seed=`{seed['seed']}`")
        for name in (base, winner) if winner != base else (base,):
            if name is None:
                continue
            r = per_arm_rows[name][i]
            lines.append(
                f"- `{name}`: file={r['pack_must_file_recall']:.2f} "
                f"sym={r['pack_must_symbol_recall']:.2f} hot={r['n_hot']} "
                f"miss_sym={r.get('missing_must_symbols')}"
            )
        lines.append("")

    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"winner": winner, "summary": summary}, indent=2))
    print(f"Wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

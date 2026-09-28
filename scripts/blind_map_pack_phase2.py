"""Phase 2: compare frozen blind map/pack results to independent ground truth."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs/superpowers/plans/2026-09-06-blind-map-pack-20-results.json"
GT = ROOT / "docs/superpowers/plans/2026-09-06-blind-map-pack-20-ground-truth.json"
OUT_JSON = ROOT / "docs/superpowers/plans/2026-09-06-blind-map-pack-20-phase2.json"
OUT_MD = ROOT / "docs/superpowers/plans/2026-09-06-blind-map-pack-20-phase2.md"


def _norm(p: str) -> str:
    return p.replace("\\", "/").lstrip("./")


def _file_of(node_id: str) -> str:
    return _norm(node_id.split("::", 1)[0])


def _map_files(row: dict[str, Any]) -> set[str]:
    files: set[str] = set()
    seed = row.get("suggested_seed") or {}
    if seed.get("file"):
        files.add(_norm(seed["file"]))
    for c in row.get("map_top_cards") or []:
        if c.get("file"):
            files.add(_norm(c["file"]))
    return files


def _pack_ids(row: dict[str, Any]) -> set[str]:
    ids = set()
    for x in (row.get("pack_summary") or {}).get("pack_ids") or []:
        ids.add(str(x).replace("\\", "/"))
    return ids


def _recall(hit: set[str], need: list[str]) -> float:
    if not need:
        return 1.0
    n = {_norm(x) for x in need}
    return len(hit & n) / len(n)


def main() -> int:
    results = json.loads(RESULTS.read_text(encoding="utf-8"))
    ground = json.loads(GT.read_text(encoding="utf-8"))["cases"]
    rows_out = []
    for row in results["rows"]:
        cid = row["id"]
        gt = ground[cid]
        map_files = _map_files(row)
        pack_ids = _pack_ids(row)
        pack_files = {_file_of(x) for x in pack_ids}
        must_files = [_norm(x) for x in gt["must_files"]]
        should_files = [_norm(x) for x in gt.get("should_files") or []]
        must_syms = [_norm(x) for x in gt.get("must_symbols") or []]

        seed_file = _norm((row.get("suggested_seed") or {}).get("file") or "")
        seed_ok = seed_file in must_files if must_files else bool(seed_file)

        # union coverage: map cards OR pack bodies
        union_files = map_files | pack_files
        miss_must_files = [f for f in must_files if f not in union_files]
        miss_must_syms = [s for s in must_syms if s not in pack_ids]
        # symbol may be hit at file level in map only
        miss_syms_file_fallback = [
            s for s in miss_must_syms if _file_of(s) not in union_files
        ]

        rec = {
            "id": cid,
            "family": row.get("family"),
            "task": row.get("task"),
            "seed": seed_file,
            "seed_in_must_files": seed_ok,
            "map_must_file_recall": round(_recall(map_files, must_files), 4),
            "pack_must_file_recall": round(_recall(pack_files, must_files), 4),
            "union_must_file_recall": round(_recall(union_files, must_files), 4),
            "pack_must_symbol_recall": round(_recall(pack_ids, must_syms), 4),
            "should_file_hit": round(_recall(union_files, should_files), 4) if should_files else None,
            "n_pack": (row.get("pack_summary") or {}).get("n_pack", 0),
            "pack_ids": sorted(pack_ids),
            "missing_must_files": miss_must_files,
            "missing_must_symbols": miss_must_syms,
            "missing_must_symbols_and_file": miss_syms_file_fallback,
            "gt_must_files": must_files,
            "gt_must_symbols": must_syms,
        }
        rows_out.append(rec)

    n = len(rows_out)
    def avg(key: str) -> float:
        return round(sum(r[key] for r in rows_out) / max(n, 1), 4)

    summary = {
        "n": n,
        "mean_map_must_file_recall": avg("map_must_file_recall"),
        "mean_pack_must_file_recall": avg("pack_must_file_recall"),
        "mean_union_must_file_recall": avg("union_must_file_recall"),
        "mean_pack_must_symbol_recall": avg("pack_must_symbol_recall"),
        "seed_ok_rate": round(sum(1 for r in rows_out if r["seed_in_must_files"]) / n, 4),
        "perfect_union_file": sum(1 for r in rows_out if r["union_must_file_recall"] >= 0.999),
        "perfect_pack_symbol": sum(
            1 for r in rows_out if not r["gt_must_symbols"] or r["pack_must_symbol_recall"] >= 0.999
        ),
        "thin_pack_lt2": sum(1 for r in rows_out if (r["n_pack"] or 0) < 2),
    }

    out = {"phase": "phase2_compare", "summary": summary, "rows": rows_out}
    OUT_JSON.write_text(json.dumps(out, indent=2), encoding="utf-8")

    lines = [
        "# Blind map→pack phase 2 — ground truth compare",
        "",
        "Ground truth collected **after** the blind run (independent symbol/path search). Frozen map/pack not re-run.",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Seed in must-files | {summary['seed_ok_rate']:.0%} ({sum(1 for r in rows_out if r['seed_in_must_files'])}/{n}) |",
        f"| Mean **map** must-file recall | {summary['mean_map_must_file_recall']:.2%} |",
        f"| Mean **pack** must-file recall | {summary['mean_pack_must_file_recall']:.2%} |",
        f"| Mean **union** must-file recall | {summary['mean_union_must_file_recall']:.2%} |",
        f"| Mean **pack** must-symbol recall | {summary['mean_pack_must_symbol_recall']:.2%} |",
        f"| Perfect union file coverage | {summary['perfect_union_file']}/{n} |",
        f"| Thin packs (n_pack < 2) | {summary['thin_pack_lt2']}/{n} |",
        "",
        "## Per task",
        "",
        "| ID | Seed OK | Map file | Pack file | Union file | Pack sym | Missing files | Missing syms |",
        "|----|---------|----------|-----------|------------|----------|---------------|--------------|",
    ]
    for r in rows_out:
        mf = ",".join(Path(x).name for x in r["missing_must_files"][:4]) or "—"
        ms = ",".join(x.split("::")[-1] for x in r["missing_must_symbols"][:4]) or "—"
        lines.append(
            f"| `{r['id']}` | {r['seed_in_must_files']} | {r['map_must_file_recall']:.2f} | "
            f"{r['pack_must_file_recall']:.2f} | {r['union_must_file_recall']:.2f} | "
            f"{r['pack_must_symbol_recall']:.2f} | {mf} | {ms} |"
        )

    lines += [
        "",
        "## Findings (factual)",
        "",
        "1. **Map file recall is strong** when must-files are named in the enrich query — map often surfaces the right *files*.",
        "2. **Lean pack is often thin** (many n_pack=1) and frequently misses the *symbols* that matter (`install_tool`, `pack_context_impl`, `apply_embed_keep_drop`, …).",
        "3. **Wrong/weak seeds** hurt pack: e.g. t07 landed on `policy/faction.py` instead of `__main__.py`/`locate_cli.py`; t17 on `pipeline/__init__.py`.",
        "4. **Suggested seeds often omit symbol** (file-only), so pack expands from a weak entry.",
        "5. **Tests/docs** appear in map cards (noise) — phase-1 cards included test/docs ranks for some tasks.",
        "",
        "Artifacts: ground truth JSON + this compare. No pack re-run.",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"summary": summary, "report": str(OUT_MD)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

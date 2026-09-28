"""Phase2: score frozen blind20 triple-pack results vs GT (must-file recall)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs/superpowers/plans/2026-09-06-blind20-triple-pack-results.json"
GT = ROOT / "docs/superpowers/plans/2026-09-06-blind20-triple-pack-gt.json"
OUT_MD = ROOT / "docs/superpowers/plans/2026-09-06-blind20-triple-pack-phase2.md"
OUT_JSON = ROOT / "docs/superpowers/plans/2026-09-06-blind20-triple-pack-phase2.json"


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").lstrip("./")


def _files_from_arm(arm: dict) -> set[str]:
    files: set[str] = set()
    for p in arm.get("pack") or []:
        f = _norm(str(p.get("file") or ""))
        if f:
            files.add(f)
        iid = str(p.get("id") or "")
        if "::" in iid:
            files.add(_norm(iid.split("::", 1)[0]))
    for c in arm.get("chain") or []:
        iid = str(c.get("id") or "")
        if "::" in iid:
            files.add(_norm(iid.split("::", 1)[0]))
        loc = str(c.get("loc") or "")
        if ":" in loc:
            files.add(_norm(loc.split(":")[0]))
    return files


def _files_from_map(row: dict) -> set[str]:
    return {_norm(f) for f in (row.get("map") or {}).get("top_files") or [] if f}


def _recall(got: set[str], must: list[str]) -> float:
    if not must:
        return 1.0
    hit = sum(1 for m in must if _norm(m) in got)
    return hit / len(must)


def main() -> int:
    rows = json.loads(RESULTS.read_text(encoding="utf-8"))["rows"]
    gt_cases = {c["id"]: c for c in json.loads(GT.read_text(encoding="utf-8"))["cases"]}
    arms = ["pack_context", "pack_poly_embed", "pack_semantic"]

    per: list[dict] = []
    sums = {a: 0.0 for a in arms}
    sums["map_top5"] = 0.0
    thin = {a: 0 for a in arms}
    n = 0

    for row in rows:
        cid = row["id"]
        gt = gt_cases[cid]
        must = list(gt.get("must_files") or [])
        n += 1
        map_files = _files_from_map(row)
        map_r = _recall(map_files, must)
        sums["map_top5"] += map_r
        entry = {
            "id": cid,
            "family": row.get("family"),
            "seed": (row.get("enrich_seed") or {}).get("seed"),
            "must_files": must,
            "map_recall": round(map_r, 3),
            "arms": {},
        }
        for a in arms:
            arm = (row.get("arms") or {}).get(a) or {}
            got = _files_from_arm(arm)
            r = _recall(got, must)
            sums[a] += r
            np = int(arm.get("n_pack") or 0)
            if np <= 1:
                thin[a] += 1
            entry["arms"][a] = {
                "recall": round(r, 3),
                "n_pack": np,
                "ok": arm.get("ok"),
                "files": sorted(got),
            }
        per.append(entry)

    means = {k: round(v / max(n, 1), 3) for k, v in sums.items()}
    winner = max(arms, key=lambda a: means[a])

    report = {
        "protocol": "blind20_triple_pack_phase2",
        "n": n,
        "mean_must_file_recall": means,
        "thin_packs_n_le_1": thin,
        "pack_winner": winner,
        "per_case": per,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    lines = [
        "# Blind-20 triple pack Phase2",
        "",
        f"Cases: **{n}** · Pack winner (must-file): **{winner}**",
        "",
        "## Mean must-file recall",
        "",
        "| Arm | Mean recall | Thin packs (n<=1) |",
        "|-----|-------------|-------------------|",
        f"| map top5 (baseline) | {means['map_top5']} | n/a |",
    ]
    for a in arms:
        lines.append(f"| {a} | {means[a]} | {thin[a]}/{n} |")
    lines += ["", "## Per case", ""]
    for e in per:
        seed = e.get("seed") or {}
        lines.append(
            f"- {e['id']} map={e['map_recall']} "
            + " ".join(f"{a}={e['arms'][a]['recall']}" for a in arms)
            + f" seed={seed.get('file')}::{seed.get('symbol')}"
        )
    lines += [
        "",
        "## Notes",
        "",
        "- Soft map often returns file-level hits (empty symbols); enrich used map_context on seed file.",
        "- Many packs stayed thin (n=1) when enrich-map heatmaps were tiny helpers (_root, _home, …).",
        "- Compare pack vs map_top5: if map wins, pack expansion from weak seeds is the bottleneck.",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"means": means, "thin": thin, "winner": winner}, indent=2))
    print(f"wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

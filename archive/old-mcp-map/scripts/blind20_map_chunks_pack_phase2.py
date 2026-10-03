"""Score map→chunks→pack results: must-file + must-symbol (pack-native metrics)."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "docs/superpowers/plans/2026-09-06-blind20-map-chunks-pack-results.json"
GT = ROOT / "docs/superpowers/plans/2026-09-06-blind20-triple-pack-gt.json"
OUT_MD = ROOT / "docs/superpowers/plans/2026-09-06-blind20-map-chunks-pack-phase2.md"
OUT_JSON = ROOT / "docs/superpowers/plans/2026-09-06-blind20-map-chunks-pack-phase2.json"

ARMS = ["pack_context", "pack_poly_embed", "pack_semantic"]


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").lstrip("./")


def _arm_files_syms(arm: dict) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    syms: set[str] = set()
    for p in list(arm.get("pack") or []) + list(arm.get("chain") or []):
        f = _norm(str(p.get("file") or ""))
        s = str(p.get("symbol") or "").strip()
        iid = str(p.get("id") or "")
        loc = str(p.get("loc") or "")
        if "::" in iid:
            ff, ss = iid.split("::", 1)
            f = f or _norm(ff)
            s = s or ss.strip()
        if ":" in loc and not f:
            f = _norm(loc.split(":")[0])
        if f:
            files.add(f)
        if s:
            syms.add(s)
            syms.add(s.split(".")[-1])
    return files, syms


def _chunk_files_syms(chunks: list[dict]) -> tuple[set[str], set[str]]:
    files, syms = set(), set()
    for c in chunks or []:
        f = _norm(str(c.get("file") or ""))
        s = str(c.get("symbol") or "").strip()
        if f:
            files.add(f)
        if s:
            syms.add(s)
            syms.add(s.split(".")[-1])
    return files, syms


def _recall(got: set[str], must: list[str]) -> float:
    if not must:
        return 1.0
    hit = 0
    for m in must:
        ml = m.strip()
        if not ml:
            continue
        if ml in got or ml.split(".")[-1] in got or _norm(ml) in got:
            hit += 1
            continue
        # fuzzy: any got endswith
        if any(g.endswith(ml) or ml.endswith(g) for g in got):
            hit += 1
    return hit / len(must)


def main() -> int:
    rows = json.loads(RESULTS.read_text(encoding="utf-8"))["rows"]
    gt = {c["id"]: c for c in json.loads(GT.read_text(encoding="utf-8"))["cases"]}

    sums_f = {a: 0.0 for a in ARMS}
    sums_s = {a: 0.0 for a in ARMS}
    sums_f["chunks"] = 0.0
    sums_s["chunks"] = 0.0
    sums_f["map_top5"] = 0.0
    thin = {a: 0 for a in ARMS}
    n = 0
    per = []

    for row in rows:
        cid = row["id"]
        g = gt[cid]
        must_f = list(g.get("must_files") or [])
        must_s = list(g.get("must_symbols") or [])
        n += 1
        map_files = {_norm(f) for f in (row.get("map") or {}).get("top_files") or [] if f}
        ch_f, ch_s = _chunk_files_syms(row.get("selected_chunks") or [])
        sums_f["map_top5"] += _recall(map_files, must_f)
        sums_f["chunks"] += _recall(ch_f, must_f)
        sums_s["chunks"] += _recall(ch_s, must_s) if must_s else 1.0

        entry = {
            "id": cid,
            "must_files": must_f,
            "must_symbols": must_s,
            "chunks": [c.get("symbol") for c in (row.get("selected_chunks") or [])],
            "arms": {},
        }
        for a in ARMS:
            arm = (row.get("arms") or {}).get(a) or {}
            af, asy = _arm_files_syms(arm)
            # Pack deliverable = pack/chain ∪ selected chunks (agent already has chunks)
            rf = _recall(af | ch_f, must_f)
            rs = _recall(asy | ch_s, must_s) if must_s else 1.0
            sums_f[a] += rf
            sums_s[a] += rs
            np = int(arm.get("n_pack") or 0)
            if np <= 1:
                thin[a] += 1
            entry["arms"][a] = {
                "file_recall": round(rf, 3),
                "symbol_recall": round(rs, 3),
                "n_pack": np,
                "pack_syms": sorted(asy)[:12],
            }
        per.append(entry)

    mean_f = {k: round(v / n, 3) for k, v in sums_f.items()}
    mean_s = {k: round(v / n, 3) for k, v in sums_s.items()}
    # Pack winner: prioritize symbol recall, then file, then fewer thin
    winner = max(
        ARMS,
        key=lambda a: (mean_s[a], mean_f[a], -thin[a]),
    )
    report = {
        "protocol": "blind20_map_chunks_pack_phase2",
        "n": n,
        "mean_must_file_recall": mean_f,
        "mean_must_symbol_recall": mean_s,
        "thin_packs_n_le_1": thin,
        "pack_winner": winner,
        "per_case": per,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# Blind-20 map → chunks → pack Phase2",
        "",
        "Loop: soft map → select relevant symbol chunks → pack(query+chunks).",
        "",
        f"**Pack winner:** `{winner}` (symbol recall first, then file).",
        "",
        "## Means",
        "",
        "| Arm | Must-file | Must-symbol | Thin n≤1 |",
        "|-----|-----------|-------------|----------|",
        f"| map top5 (files only) | {mean_f['map_top5']} | n/a | n/a |",
        f"| selected chunks | {mean_f['chunks']} | {mean_s['chunks']} | n/a |",
    ]
    for a in ARMS:
        lines.append(f"| {a} | {mean_f[a]} | {mean_s[a]} | {thin[a]}/{n} |")
    lines += [
        "",
        "Note: pack file/symbol recall includes selected chunks ∪ pack/chain ",
        "(agent already pasted those chunks into the pack call).",
        "",
        "## Per case (symbol recall)",
        "",
    ]
    for e in per:
        lines.append(
            f"- {e['id']} chunks={e['chunks']} "
            + " ".join(f"{a}={e['arms'][a]['symbol_recall']}/{e['arms'][a]['file_recall']}" for a in ARMS)
        )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"mean_file": mean_f, "mean_symbol": mean_s, "thin": thin, "winner": winner}, indent=2))
    print(f"wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

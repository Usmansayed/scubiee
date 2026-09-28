#!/usr/bin/env python3
"""Phase C — policy trajectory A/B (scripted agents, not GATE ship).

Three policies on the same calibration cases:

* baseline     — always map→pack→reads (current ship ladder habit)
* calibrated   — Prefer/Forbid from framework §6.3 (Phase B evidence)
* native_heavy — Grep/Glob/Read first; Scubiee only if soft miss

Measures: rounds, result_tokens, total_proxy, must_*, under_use, over_use,
scubiee_calls, traj_break (heuristic).

This is NOT production GATE text. Phase D decides ship.

Usage:
  PYTHONPATH=packages python scripts/locate_calibration_phase_c.py
  PYTHONPATH=packages python scripts/locate_calibration_phase_c.py --limit-soft 6 --limit-exact 4
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "docs" / "superpowers" / "plans" / "locate-calibration-corpus-v1.json"
OUT_JSON = ROOT / "docs" / "superpowers" / "plans" / "locate-calibration-phase-c-results.json"
OUT_MD = ROOT / "docs" / "superpowers" / "plans" / "2026-09-07-locate-calibration-phase-c.md"
RUN_DIR = ROOT / "docs" / "superpowers" / "plans" / "locate-calibration-runs-c"

sys.path.insert(0, str(ROOT / "packages"))
os.environ.setdefault("CTX_TRACE_ENGINE", "composite_v1")
os.environ.setdefault("CTX_REPO", str(ROOT).replace("\\", "/"))

_SPEC = importlib.util.spec_from_file_location(
    "locate_calibration_phase_b",
    ROOT / "scripts" / "locate_calibration_phase_b.py",
)
assert _SPEC and _SPEC.loader
_pb = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_pb)

ROUND_TRIP_TAX = _pb.ROUND_TRIP_TAX
arm_map_read = _pb.arm_map_read
arm_map_pack = _pb.arm_map_pack
arm_host_grep = _pb.arm_host_grep
mean = _pb.mean


def _tag(row: dict[str, Any], policy: str, *, scubiee: int, native: int, path: str) -> dict[str, Any]:
    out = dict(row)
    out["policy"] = policy
    out["scubiee_calls"] = scubiee
    out["native_calls"] = native
    out["path"] = path
    return out


def policy_baseline(case: dict[str, Any]) -> dict[str, Any]:
    """Current habit: always map→pack (ladder force)."""
    row = arm_map_pack(case)
    # map+pack counted inside arm; native reads are virtual
    scubiee = 2
    native = max(0, int(row.get("rounds") or 0) - scubiee)
    return _tag(row, "baseline", scubiee=scubiee, native=native, path="map→pack")


def policy_calibrated(case: dict[str, Any]) -> dict[str, Any]:
    """§6.3 Prefer/Forbid draft (not shipped)."""
    tax = case.get("taxonomy") or ""
    if tax in {"literal_needle", "name_path"} or str(case.get("id") or "").startswith(
        "anchor_literal"
    ) or str(case.get("id") or "").startswith("anchor_name"):
        row = arm_host_grep(case)
        return _tag(row, "calibrated", scubiee=0, native=int(row.get("rounds") or 1), path="grep_first")

    if tax == "known_seed":
        # Prefer pack with known seed — fall back to map_pack
        row = arm_map_pack(case)
        return _tag(
            row,
            "calibrated",
            scubiee=2,
            native=max(0, int(row.get("rounds") or 0) - 2),
            path="pack_known_seed",
        )

    # soft_understand / exact_edit: map first; pack only if seed_ok
    mapped = arm_map_read(case)
    seed = mapped.get("seed") or {}
    seed_file = str(seed.get("file") or "")
    seed_symbol = str(seed.get("symbol") or "")
    seed_ok = bool(
        seed_file.replace("\\", "/").startswith(("packages/", "src/", "app/"))
        and seed_symbol
        and not seed_symbol.startswith("_")
        and "test" not in seed_file.lower()
    )
    if tax == "exact_edit" and seed_ok:
        row = arm_map_pack(case)
        return _tag(
            row,
            "calibrated",
            scubiee=2,
            native=max(0, int(row.get("rounds") or 0) - 2),
            path="map→pack(seed_ok exact)",
        )
    if seed_ok and tax == "soft_understand":
        # Prefer map+read when soft; pack optional — Phase B: pack costs more
        return _tag(
            mapped,
            "calibrated",
            scubiee=1,
            native=max(0, int(mapped.get("rounds") or 0) - 1),
            path="map→read(soft seed_ok)",
        )
    # no seed_ok: map→read only (forbid poison pack)
    return _tag(
        mapped,
        "calibrated",
        scubiee=1,
        native=max(0, int(mapped.get("rounds") or 0) - 1),
        path="map→read(no seed_ok)",
    )


def policy_native_heavy(case: dict[str, Any]) -> dict[str, Any]:
    """Native first (blind on soft/exact); Scubiee only if Grep misses must_files."""
    native = _blind_grep_scored(case)
    mf = native.get("must_file")
    if mf is not None and mf >= 0.99:
        return _tag(
            native,
            "native_heavy",
            scubiee=0,
            native=int(native.get("rounds") or 1),
            path="grep_hit",
        )
    # miss → escalate to map→pack
    row = arm_map_pack(case)
    rounds = int(native.get("rounds") or 0) + int(row.get("rounds") or 0)
    result_tok = int(native.get("result_tokens") or 0) + int(row.get("result_tokens") or 0)
    merged = dict(row)
    merged["rounds"] = rounds
    merged["result_tokens"] = result_tok
    merged["round_trip_tax"] = rounds * ROUND_TRIP_TAX
    merged["total_proxy"] = result_tok + rounds * ROUND_TRIP_TAX
    if (native.get("must_file") or 0) > (merged.get("must_file") or 0):
        merged["must_file"] = native.get("must_file")
        merged["must_sym"] = max(native.get("must_sym") or 0, merged.get("must_sym") or 0)
    elif (native.get("must_sym") or 0) > (merged.get("must_sym") or 0):
        merged["must_sym"] = native.get("must_sym")
    return _tag(
        merged,
        "native_heavy",
        scubiee=2,
        native=int(native.get("rounds") or 0),
        path="grep_miss→map→pack",
    )


def _blind_grep_scored(case: dict[str, Any]) -> dict[str, Any]:
    """Grep using enrich tokens only (no gold symbols on soft/exact); score against gold."""
    tax = case.get("taxonomy") or ""
    if tax in {"literal_needle", "name_path"} or str(case.get("id") or "").startswith("anchor_"):
        return arm_host_grep(case)

    import re

    pats: list[str] = []
    for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", case.get("enrich_query") or ""):
        if tok.lower() not in {"that", "this", "with", "from", "when", "where", "does", "how"}:
            pats.append(tok)
    seen: set[str] = set()
    uniq: list[str] = []
    for p in pats:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    uniq = uniq[:8]
    files: set[str] = set()
    syms: set[str] = set()
    hits = 0
    for pat in uniq:
        rx = re.compile(re.escape(pat))
        for path in (ROOT / "packages").rglob("*.py"):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            if not rx.search(text):
                continue
            rel = _pb._norm_file(str(path.relative_to(ROOT)))
            files.add(rel)
            syms.add(pat)
            hits += 1
            break
    # Cost model: 1 grep + min(5, files) reads
    rounds = 1 + min(5, len(files))
    result_tok = _pb._json_tokens({"hits": hits, "patterns": uniq}) + (len(files) * 200)
    score = _pb._score(files, syms, case.get("must_files") or [], case.get("must_symbols") or [])
    return {
        "arm": "N1a_host_grep_blind",
        "ok": bool(files),
        "elapsed_s": 0.0,
        **_pb._cost(rounds, result_tok),
        **score,
    }


POLICIES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "baseline": policy_baseline,
    "calibrated": policy_calibrated,
    "native_heavy": policy_native_heavy,
}


def summarize_policy(rows: list[dict[str, Any]], policy: str) -> dict[str, Any]:
    subset = [r for r in rows if r.get("policy") == policy]
    if not subset:
        return {"policy": policy, "n": 0}
    return {
        "policy": policy,
        "n": len(subset),
        "mean_total_proxy": mean([r.get("total_proxy") for r in subset]),
        "mean_rounds": mean([r.get("rounds") for r in subset]),
        "mean_result_tokens": mean([r.get("result_tokens") for r in subset]),
        "mean_must_file": mean([r.get("must_file") for r in subset]),
        "mean_must_sym": mean([r.get("must_sym") for r in subset]),
        "mean_scubiee_calls": mean([r.get("scubiee_calls") for r in subset]),
        "mean_native_calls": mean([r.get("native_calls") for r in subset]),
        "ok_rate": round(sum(1 for r in subset if r.get("ok")) / len(subset), 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-soft", type=int, default=6)
    ap.add_argument("--limit-exact", type=int, default=4)
    ap.add_argument("--limit-needle", type=int, default=4)
    args = ap.parse_args()

    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    all_cases: list[dict[str, Any]] = list(corpus.get("cases") or [])
    soft = [c for c in all_cases if c.get("taxonomy") == "soft_understand"][: args.limit_soft]
    exact = [c for c in all_cases if c.get("taxonomy") == "exact_edit"][: args.limit_exact]
    needles = [
        c
        for c in all_cases
        if c.get("taxonomy") in {"literal_needle", "name_path"}
        or str(c.get("id") or "").startswith("anchor_")
    ][: args.limit_needle]
    cases = soft + exact + needles

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    print(f"Phase C cases={len(cases)} policies={list(POLICIES)} TAX={ROUND_TRIP_TAX}")

    for case in cases:
        cid = case["id"]
        print(f"  {cid} ({case.get('taxonomy')}) …", flush=True)
        bundle: dict[str, Any] = {"case": case}
        for name, fn in POLICIES.items():
            r = fn(case)
            r["case_id"] = cid
            r["taxonomy"] = case.get("taxonomy")
            rows.append(r)
            bundle[name] = r
        (RUN_DIR / f"{cid}.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")

    board = {name: summarize_policy(rows, name) for name in POLICIES}

    # over_use: needle/name where policy used Scubiee and total_proxy worse than calibrated grep
    over_flags = []
    over_cal_flags = []
    under_flags = []
    traj_break_flags = []
    for case in cases:
        cid = case["id"]
        tax = case.get("taxonomy")
        by_p = {r["policy"]: r for r in rows if r["case_id"] == cid}
        base, cal, nat = by_p["baseline"], by_p["calibrated"], by_p["native_heavy"]

        is_needle = tax in {"literal_needle", "name_path"} or str(cid).startswith("anchor_")
        if is_needle:
            # baseline over_use vs calibrated native path
            if (base.get("scubiee_calls") or 0) > 0 and (base.get("total_proxy") or 0) > (
                cal.get("total_proxy") or 0
            ) and (cal.get("must_file") or 0) >= (base.get("must_file") or 0) - 0.05:
                over_flags.append({"case_id": cid, "policy": "baseline"})
            # calibrated should almost never Scubiee-first needles
            if (cal.get("scubiee_calls") or 0) > 0:
                over_cal_flags.append({"case_id": cid, "policy": "calibrated"})

        if tax in {"soft_understand", "exact_edit"}:
            # under_use: calibrated/native never called Scubiee and must_file worse than baseline
            for p, r in (("calibrated", cal), ("native_heavy", nat)):
                if (r.get("scubiee_calls") or 0) == 0 and (r.get("must_file") or 0) + 0.05 < (
                    base.get("must_file") or 0
                ):
                    under_flags.append({"case_id": cid, "policy": p})

        if tax in {"soft_understand", "exact_edit"} and (nat.get("path") or "").startswith(
            "grep_miss"
        ):
            traj_break_flags.append({"case_id": cid, "policy": "native_heavy", "why": "grep_then_scubiee"})

    n_needle = sum(
        1
        for c in cases
        if c.get("taxonomy") in {"literal_needle", "name_path"}
        or str(c.get("id") or "").startswith("anchor_")
    )
    n_softish = sum(1 for c in cases if c.get("taxonomy") in {"soft_understand", "exact_edit"})
    over_rate = round(len(over_flags) / n_needle, 3) if n_needle else None
    over_rate_cal = round(len(over_cal_flags) / n_needle, 3) if n_needle else None
    under_rate_cal = (
        round(sum(1 for u in under_flags if u["policy"] == "calibrated") / n_softish, 3)
        if n_softish
        else None
    )
    under_rate_nat = (
        round(sum(1 for u in under_flags if u["policy"] == "native_heavy") / n_softish, 3)
        if n_softish
        else None
    )
    traj_rate = round(len(traj_break_flags) / len(cases), 3) if cases else None

    findings = []
    b, c, n = board["baseline"], board["calibrated"], board["native_heavy"]
    if b.get("mean_total_proxy") and c.get("mean_total_proxy"):
        delta = round(c["mean_total_proxy"] - b["mean_total_proxy"], 1)
        findings.append(
            f"Calibrated vs baseline mean total_proxy: {c['mean_total_proxy']} vs "
            f"{b['mean_total_proxy']} (Δ={delta})."
        )
    if n.get("mean_total_proxy") and c.get("mean_total_proxy"):
        findings.append(
            f"Native-heavy vs calibrated: {n['mean_total_proxy']} vs {c['mean_total_proxy']} "
            f"(blind Grep miss→remap thrash on soft/exact)."
        )
    if c.get("mean_must_file") is not None and b.get("mean_must_file") is not None:
        findings.append(
            f"must_file calibrated={c['mean_must_file']} baseline={b['mean_must_file']} "
            f"native_heavy={n.get('mean_must_file')}."
        )
    findings.append(
        f"over_use baseline-on-needles={over_rate}; calibrated-on-needles={over_rate_cal} "
        f"(Phase D bar ≤0.10 on calibrated)."
    )
    findings.append(
        f"under_use calibrated={under_rate_cal} native_heavy={under_rate_nat} "
        f"(Phase D bar ≤0.20)."
    )
    findings.append(f"traj_break heuristic rate (native grep→scubiee on soft/exact): {traj_rate}.")
    findings.append(
        f"mean scubiee_calls baseline={b.get('mean_scubiee_calls')} "
        f"calibrated={c.get('mean_scubiee_calls')} native={n.get('mean_scubiee_calls')}."
    )

    # Phase D preview checklist (not a pass/fail ship decision)
    d_preview = {
        "total_proxy_down_vs_baseline": bool(
            c.get("mean_total_proxy") and b.get("mean_total_proxy")
            and c["mean_total_proxy"] < b["mean_total_proxy"]
        ),
        "must_file_within_5pp": bool(
            c.get("mean_must_file") is not None
            and b.get("mean_must_file") is not None
            and c["mean_must_file"] + 0.05 >= b["mean_must_file"]
        ),
        "over_use_le_10pct": bool(over_rate_cal is not None and over_rate_cal <= 0.10),
        "under_use_cal_le_20pct": bool(under_rate_cal is not None and under_rate_cal <= 0.20),
    }

    report = {
        "protocol": "locate_calibration_phase_c_v1",
        "kind": "scripted_policy_trajectories",
        "note": "Not live LLM agents; policies choose Phase B arms. GATE text not shipped.",
        "framework": "docs/superpowers/specs/2026-09-06-locate-force-routing-research-framework.md",
        "round_trip_tax": ROUND_TRIP_TAX,
        "elapsed_s": round(time.perf_counter() - t0, 2),
        "n_cases": len(cases),
        "scoreboard": board,
        "over_use_rate_baseline_on_needles": over_rate,
        "over_use_rate_calibrated_on_needles": over_rate_cal,
        "under_use_rate_calibrated": under_rate_cal,
        "under_use_rate_native_heavy": under_rate_nat,
        "traj_break_rate": traj_rate,
        "over_use_details": over_flags,
        "under_use_details": under_flags,
        "traj_break_details": traj_break_flags,
        "phase_d_preview": d_preview,
        "findings_draft": findings,
        "rows": rows,
    }
    OUT_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")

    md = [
        "# Locate calibration — Phase C (policy trajectories)",
        "",
        "**Kind:** scripted Prefer/Forbid policies (not live LLM; **not GATE ship**)",
        f"**Tax:** {ROUND_TRIP_TAX}/round · **Cases:** {len(cases)} · **Elapsed:** {report['elapsed_s']}s",
        "",
        "## Scoreboard",
        "",
        "| Policy | n | total_proxy | rounds | must_file | must_sym | scubiee | native | ok |",
        "|--------|--:|----------:|------:|----------:|---------:|--------:|-------:|---:|",
    ]
    for name in ("baseline", "calibrated", "native_heavy"):
        s = board[name]
        md.append(
            f"| `{name}` | {s.get('n')} | {s.get('mean_total_proxy')} | {s.get('mean_rounds')} | "
            f"{s.get('mean_must_file')} | {s.get('mean_must_sym')} | "
            f"{s.get('mean_scubiee_calls')} | {s.get('mean_native_calls')} | {s.get('ok_rate')} |"
        )
    md += [
        "",
        "## Phase D preview (this sample)",
        "",
        f"- total_proxy ↓ vs baseline: **{d_preview['total_proxy_down_vs_baseline']}**",
        f"- must_file within −5pp: **{d_preview['must_file_within_5pp']}**",
        f"- over_use ≤10% (calibrated on needles): **{d_preview['over_use_le_10pct']}** "
        f"(cal={over_rate_cal}, baseline={over_rate})",
        f"- under_use calibrated ≤20%: **{d_preview['under_use_cal_le_20pct']}** (rate={under_rate_cal})",
        "",
        "## Caveats",
        "",
        "- Scripted policies (not live LLM compliance).",
        "- Soft/exact native Grep is **blind** to gold symbols (enrich tokens only).",
        "- Enrich queries are code-vocab heavy, so blind Grep can still hit files.",
        "",
        "## Draft findings",
        "",
    ]
    for f in findings:
        md.append(f"- {f}")
    md += [
        "",
        "## Next",
        "",
        "- Optional: live Kiro/Cursor A/B on a 3–5 task slice for compliance (traj_break).",
        "- Revise Prefer→Require only if under_use stays high with Prefer.",
        "- Do **not** ship GATE/MCP Prefer text until Phase D greens.",
        "",
        f"Raw: `{OUT_JSON.relative_to(ROOT).as_posix()}`",
        "",
    ]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "scoreboard": board,
                "phase_d_preview": d_preview,
                "findings": findings,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

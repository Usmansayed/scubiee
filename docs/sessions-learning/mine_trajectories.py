#!/usr/bin/env python3
"""Deeper trajectory mining for the research report. Reads data/sessions.jsonl and
computes signals the summary miner doesn't: trajectory shapes, grep-fallback rate,
first-move signatures, cost-vs-calls correlation, and the newmap over-ask profile.

Writes docs/sessions-learning/TRAJECTORIES.md and prints it.
"""
from __future__ import annotations

import json
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "sessions.jsonl"


def load():
    return [json.loads(l) for l in DATA.read_text(encoding="utf-8").splitlines() if l.strip()]


def _dev(rows, arm=None):
    out = [r for r in rows if r["kind"] == "dev_task_mini_bridge"]
    if arm:
        out = [r for r in out if r["arm"] == arm]
    return out


def collapse(seq):
    """Collapse runs of the same tool: ['Edit','Edit','Edit'] -> 'Edit*3'."""
    out = []
    for s in seq:
        if out and out[-1][0] == s:
            out[-1][1] += 1
        else:
            out.append([s, 1])
    return " ".join(f"{s}*{n}" if n > 1 else s for s, n in out)


def corr(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if isinstance(x, (int, float)) and isinstance(y, (int, float))]
    if len(pairs) < 3:
        return None
    try:
        return round(st.correlation([p[0] for p in pairs], [p[1] for p in pairs]), 3)
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    rows = load()
    dev = _dev(rows)
    L = ["# Trajectory-level mining (auto-generated)", "",
         "From `data/sessions.jsonl`. Regenerate: `python docs/sessions-learning/mine_trajectories.py`.", ""]

    # 1. cost vs calls correlation (the P1 claim, quantified)
    L += ["## 1. Cost is driven by call count, quantified", ""]
    for arm in ("without", "mini", "mini_v3", "newmap"):
        rs = _dev(rows, arm)
        c = corr([r["api_calls"] for r in rs], [r["total_tokens"] for r in rs])
        cg = corr([r["grep"] for r in rs], [r["total_tokens"] for r in rs])
        L.append(f"- **{arm}** (n={len(rs)}): corr(api_calls, tokens)={c}; corr(grep, tokens)={cg}")
    allc = corr([r["api_calls"] for r in dev], [r["total_tokens"] for r in dev])
    L.append(f"- **all dev cells** (n={len(dev)}): corr(api_calls, tokens)={allc}")
    L.append("")

    # 2. grep fallback: how often each arm fell back to grep, and the cost penalty
    L += ["## 2. Grep fallback incidence and penalty", ""]
    for arm in ("mini_v3", "newmap"):
        rs = _dev(rows, arm)
        fell = [r for r in rs if (r["grep"] or 0) > 0]
        clean = [r for r in rs if (r["grep"] or 0) == 0]
        mt = lambda xs: round(st.mean([x["total_tokens"] for x in xs])) if xs else None  # noqa: E731
        L.append(f"- **{arm}**: {len(fell)}/{len(rs)} cells fell back to grep. "
                 f"mean tok with grep={mt(fell)} vs no grep={mt(clean)}")
    L.append("")

    # 3. first-3-move signature of winners (cheapest) vs losers (priciest)
    L += ["## 3. Trajectory shapes, cheapest vs priciest per arm", ""]
    for arm in ("mini_v3", "newmap"):
        rs = sorted(_dev(rows, arm), key=lambda r: r["total_tokens"] or 1e9)
        L.append(f"### {arm}")
        L.append("cheapest 3:")
        for r in rs[:3]:
            L.append(f"- {r['total_tokens']:,} tok ({r['task'][:11]}): `{collapse(r['tool_sequence'])}`")
        L.append("priciest 3:")
        for r in rs[-3:]:
            L.append(f"- {r['total_tokens']:,} tok ({r['task'][:11]}): `{collapse(r['tool_sequence'])}`")
        L.append("")

    # 4. newmap over-ask: locate calls vs the known required edit sites
    #    cache_aware edits ~4 symbols (token_meter.py); dirty_files edits 1.
    L += ["## 4. newmap locate-call budget vs required edit sites", "",
          "cache_aware_savings edits ~4 symbols in one file; dirty_files_cap edits 1 symbol.",
          "Locate calls = map calls before the first Edit.", ""]
    for r in sorted(_dev(rows, "newmap"), key=lambda r: (r["task"], r["run"])):
        seq = r["tool_sequence"]
        try:
            ei = next(i for i, s in enumerate(seq) if s in ("Edit", "Write"))
        except StopIteration:
            ei = len(seq)
        locate = [s for s in seq[:ei] if s.startswith("map:")]
        L.append(f"- {r['task'][:11]} {r['run'][:13]}: {len(locate)} locate "
                 f"({' '.join(locate)}) -> tok={r['total_tokens']:,}")
    L.append("")

    # 5. Skill-call noise (task-specific, not a map signal) — flag so report excludes it
    L += ["## 5. Skill-call noise (claude-api pricing lookups)", ""]
    for arm in ("mini_v3", "newmap"):
        rs = _dev(rows, arm)
        with_skill = sum(1 for r in rs if "Skill" in r["tool_sequence"])
        L.append(f"- {arm}: {with_skill}/{len(rs)} cells made Skill calls "
                 "(cache_aware task asks for pricing; inflates tokens equally in both arms)")
    L.append("")

    (HERE / "TRAJECTORIES.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    print("wrote", HERE / "TRAJECTORIES.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

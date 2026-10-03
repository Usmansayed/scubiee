#!/usr/bin/env python3
"""Read data/sessions.jsonl and compute the aggregate patterns we tune on:

  - tokens / api_calls / map / grep / edit per arm (dev-task arms only)
  - correctness (oracle success) per arm
  - head-to-head on matched (task, rep) cells where arms are comparable
  - map config usage distribution for the newmap arm
  - follow-up-after-find rate (did one find suffice, or did view/refs follow?)
  - retrieval arms: recall / precision per policy

Prints a report and writes docs/sessions-learning/PATTERNS.md.
Run after extract_sessions.py.
"""
from __future__ import annotations

import json
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "sessions.jsonl"


def load() -> list[dict]:
    return [json.loads(l) for l in DATA.read_text(encoding="utf-8").splitlines() if l.strip()]


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(st.mean(xs)) if xs else None


def _med(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(st.median(xs)) if xs else None


def dev_arm_table(rows):
    dev = [r for r in rows if r["kind"] == "dev_task_mini_bridge"]
    by_arm = defaultdict(list)
    for r in dev:
        by_arm[r["arm"]].append(r)
    out = []
    for arm in sorted(by_arm):
        rs = by_arm[arm]
        toks = [r["total_tokens"] for r in rs]
        apis = [r["api_calls"] for r in rs]
        maps = [r["map"] for r in rs]
        greps = [r["grep"] for r in rs]
        wins = [1 for r in rs if r.get("success")]
        out.append({
            "arm": arm, "n": len(rs),
            "tok_mean": _mean(toks), "tok_med": _med(toks),
            "api_mean": _mean(apis), "map_mean": _mean(maps), "grep_mean": _mean(greps),
            "success": f"{sum(wins)}/{len(rs)}",
        })
    return out


def head_to_head(rows):
    """mini_v3 vs newmap on matched (task, rep) within the same run."""
    dev = [r for r in rows if r["kind"] == "dev_task_mini_bridge"]
    by_key = defaultdict(dict)
    for r in dev:
        if r["arm"] in ("mini_v3", "newmap"):
            by_key[(r["run"], r["task"], r["rep"])][r["arm"]] = r
    pairs = []
    for key, d in by_key.items():
        if "mini_v3" in d and "newmap" in d:
            a, b = d["mini_v3"], d["newmap"]
            pairs.append({
                "run": key[0], "task": key[1], "rep": key[2],
                "mini_v3_tok": a["total_tokens"], "newmap_tok": b["total_tokens"],
                "mini_v3_api": a["api_calls"], "newmap_api": b["api_calls"],
                "newmap_cheaper": (b["total_tokens"] or 0) < (a["total_tokens"] or 0),
                "both_pass": bool(a.get("success") and b.get("success")),
            })
    return sorted(pairs, key=lambda p: (p["task"], p["run"]))


def find_followup(rows):
    """For newmap cells, after the FIRST map:find, did a view/refs locate call follow
    before the first Edit? (Lower is better: find alone sufficed.)"""
    out = []
    for r in rows:
        if r["arm"] != "newmap":
            continue
        seq = r["tool_sequence"]
        if not any(s == "map:find" for s in seq):
            continue
        fi = seq.index("map:find")
        try:
            ei = next(i for i, s in enumerate(seq) if s in ("Edit", "Write"))
        except StopIteration:
            ei = len(seq)
        between = seq[fi + 1:ei]
        locate_followups = [s for s in between if s.startswith("map:")]
        out.append({
            "run": r["run"], "task": r["task"],
            "followup_locate_calls": len(locate_followups),
            "followups": locate_followups,
        })
    return out


def config_dist(rows):
    c = Counter()
    for r in rows:
        if r["arm"] == "newmap":
            for k, v in (r["config_use"] or {}).items():
                c[k] += v
    return dict(c)


def retrieval_table(rows):
    ret = [r for r in rows if r["kind"] == "retrieval_challenge"]
    by_arm = defaultdict(list)
    for r in ret:
        by_arm[r["arm"]].append(r)
    out = []
    for arm in sorted(by_arm):
        rs = by_arm[arm]
        out.append({
            "arm": arm, "n": len(rs),
            "recall": _mean([r["recall"] for r in rs]),
            "precision": _mean([r["precision"] for r in rs]),
            "tok_mean": _mean([r["total_tokens"] for r in rs]),
        })
    return out


def main() -> int:
    rows = load()
    dev = dev_arm_table(rows)
    h2h = head_to_head(rows)
    fu = find_followup(rows)
    cfg = config_dist(rows)
    ret = retrieval_table(rows)

    L = ["# Patterns mined from all sessions (auto-generated)", "",
         "Source: `data/sessions.jsonl` (regenerate: `python docs/sessions-learning/mine_patterns.py`).",
         f"Total cells: {len(rows)}.", "",
         "## Dev-task arms (tokens, calls, correctness)", "",
         "| arm | n | tok mean | tok med | api mean | map mean | grep mean | success |",
         "|---|--:|--:|--:|--:|--:|--:|:--:|"]
    for d in dev:
        L.append(f"| {d['arm']} | {d['n']} | {d['tok_mean']} | {d['tok_med']} | "
                 f"{d['api_mean']} | {d['map_mean']} | {d['grep_mean']} | {d['success']} |")

    L += ["", "## mini_v3 vs newmap, matched (run, task, rep)", "",
          "| run | task | rep | mini_v3 tok | newmap tok | newmap cheaper | both pass |",
          "|---|---|--:|--:|--:|:--:|:--:|"]
    for p in h2h:
        L.append(f"| {p['run'][:15]} | {p['task']} | {p['rep']} | {p['mini_v3_tok']:,} | "
                 f"{p['newmap_tok']:,} | {'Y' if p['newmap_cheaper'] else 'n'} | "
                 f"{'Y' if p['both_pass'] else 'n'} |")
    cheaper = sum(1 for p in h2h if p["newmap_cheaper"])
    L.append("")
    L.append(f"newmap cheaper in {cheaper}/{len(h2h)} matched pairs.")

    L += ["", "## find follow-up (newmap): locate calls between first find and first edit", ""]
    zero = sum(1 for f in fu if f["followup_locate_calls"] == 0)
    L.append(f"find alone sufficed (0 follow-up locate calls) in {zero}/{len(fu)} newmap cells.")
    L.append("")
    for f in fu:
        L.append(f"- {f['run'][:15]} {f['task']}: {f['followup_locate_calls']} follow-up "
                 f"({', '.join(f['followups']) or 'none'})")

    L += ["", "## newmap map-config usage (all cells)", "",
          "| config | calls |", "|---|--:|"]
    for k, v in sorted(cfg.items(), key=lambda kv: -kv[1]):
        L.append(f"| {k} | {v} |")

    L += ["", "## Retrieval-challenge arms (recall / precision)", "",
          "| arm | n | recall | precision | tok mean |", "|---|--:|--:|--:|--:|"]
    for r in ret:
        L.append(f"| {r['arm']} | {r['n']} | {r['recall']} | {r['precision']} | {r['tok_mean']} |")

    (HERE / "PATTERNS.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    print("\nwrote", HERE / "PATTERNS.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Classify every tool call in every dev cell by its PURPOSE, so we can see what
the API calls are actually spent on and which could be collapsed by a better
tool. Reads data/sessions.jsonl (needs tool_sequence). Prints + writes
CALL_PURPOSES.md.

Purpose buckets (per non-bookkeeping call):
  locate_find     - map/find (semantic "where is it")
  locate_struct   - map view path / outline / overview (structure of a file/dir)
  locate_wire     - map refs/around (callers/callees/uses) OR grep used to trace wiring
  read_body       - Read / map view targets / map include_bodies (get the code)
  grep_literal    - Grep/Glob for a literal/name (not a wiring trace)
  edit            - Edit/Write
  other           - Skill/git/etc.

Heuristic: a Grep right after a locate, or multiple greps in a row, is a
wiring/exploration trace (locate_wire); an isolated grep is grep_literal.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "sessions.jsonl"


def load():
    return [json.loads(l) for l in DATA.read_text(encoding="utf-8").splitlines() if l.strip()]


def classify(seq: list[str]) -> list[str]:
    out = []
    for i, s in enumerate(seq):
        low = s.lower()
        if s.startswith("map:find") or s == "map:find":
            out.append("locate_find")
        elif s.startswith("map:view") or s.startswith("map:open") or s.startswith("map:outline"):
            # view targets = read body; view path/outline = structure
            out.append("read_body")  # most view calls in our traces fetched bodies
        elif s.startswith("map:refs") or s.startswith("map:around"):
            out.append("locate_wire")
        elif s.startswith("map"):
            out.append("locate_find")
        elif low == "read":
            out.append("read_body")
        elif low in ("grep", "glob"):
            # grep adjacent to another grep or right after a locate = wiring trace
            prev = seq[i - 1].lower() if i else ""
            nxt = seq[i + 1].lower() if i + 1 < len(seq) else ""
            if prev in ("grep", "glob") or nxt in ("grep", "glob") or prev.startswith("map"):
                out.append("locate_wire")
            else:
                out.append("grep_literal")
        elif low in ("edit", "write"):
            out.append("edit")
        else:
            out.append("other")
    return out


def main() -> int:
    rows = [r for r in load() if r["kind"] == "dev_task_mini_bridge" and r["tool_sequence"]]
    by_arm = defaultdict(lambda: Counter())
    calls_by_arm = defaultdict(int)
    cells_by_arm = defaultdict(int)
    # locate overhead = everything that is not edit and not the first locate_find
    pre_edit_locates = defaultdict(list)

    for r in rows:
        arm = r["arm"]
        cells_by_arm[arm] += 1
        purposes = classify(r["tool_sequence"])
        by_arm[arm].update(purposes)
        calls_by_arm[arm] += len(purposes)
        # count locate-ish calls before the first edit
        try:
            ei = purposes.index("edit")
        except ValueError:
            ei = len(purposes)
        pre = purposes[:ei]
        locate_like = [p for p in pre if p in ("locate_find", "locate_struct", "locate_wire", "read_body", "grep_literal")]
        pre_edit_locates[arm].append(len(locate_like))

    L = ["# What are the API calls actually spent on? (auto-generated)", "",
         "Per-purpose call counts across dev cells, by arm. The question: which calls could a better",
         "tool collapse? Source: data/sessions.jsonl.", "",
         "## Average calls per purpose, per cell", "",
         "| arm | cells | locate_find | read_body | locate_wire | grep_literal | edit | other | pre-edit locate steps |",
         "|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    import statistics as st
    for arm in ("without", "mini", "mini_v3", "newmap", "mini_plus"):
        if arm not in by_arm:
            continue
        n = cells_by_arm[arm]
        c = by_arm[arm]

        def per(k):
            return round(c[k] / n, 1)
        ple = round(st.mean(pre_edit_locates[arm]), 1)
        L.append(f"| {arm} | {n} | {per('locate_find')} | {per('read_body')} | {per('locate_wire')} "
                 f"| {per('grep_literal')} | {per('edit')} | {per('other')} | {ple} |")

    L += ["", "## Reading it",
          "- **read_body** = the agent fetching code (native Read, or map view/include_bodies).",
          "- **locate_wire** = calls spent tracing callers/callees/uses (map refs/around or grep chains).",
          "- **pre-edit locate steps** = how many non-edit retrieval calls happen before the first edit;",
          "  this is the number a better tool must drive toward 1.", ""]

    # Which pairs of consecutive purposes recur (collapsible sequences)?
    bigram = Counter()
    for r in rows:
        p = classify(r["tool_sequence"])
        for a, b in zip(p, p[1:]):
            if a != "edit" and b != "edit":
                bigram[(a, b)] += 1
    L += ["## Most common consecutive retrieval steps (collapse targets)", "",
          "| from -> to | count |", "|---|--:|"]
    for (a, b), n in bigram.most_common(12):
        L.append(f"| {a} -> {b} | {n} |")
    L.append("")

    (HERE / "CALL_PURPOSES.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    print("wrote", HERE / "CALL_PURPOSES.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

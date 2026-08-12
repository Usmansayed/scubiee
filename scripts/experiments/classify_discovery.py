"""Measure how often the agent's discovery ops are GRAPH-shaped.

The question: do we need graph tools (usages/neighbors/imports/graph)? A graph
tool only earns its slot if the underlying NEED is frequent — even when the agent
satisfies it with grep instead. So we classify every discovery call across saved
trial transcripts:

  - symbol   : hunting a symbol's definition or call sites (def X, .X(, X(,
               bare identifier alternations) -> the `usages` / `read(neighbors)` need
  - import   : following imports / module deps -> the `imports` need
  - trace    : explicit NL graph / multi-hop question -> the `graph` need
  - text     : free-text / conceptual search -> plain search/grep

We dedupe consecutive identical calls (the SDK emits start+result, doubling raw
counts) and also count repeated native reads of the same path (dedup upside).

Usage: python scripts/experiments/classify_discovery.py <trial_dir> [<dir> ...]
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

_DISCOVERY = {"search", "grep", "usages", "neighbors", "graph", "imports",
              "outline", "read", "files", "map", "focus", "recall"}
_IDENT_ALT = re.compile(r"^[\w|()\\.*\s\[\]+-]+$")


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _arg(call: dict) -> str:
    a = call.get("arguments")
    if not isinstance(a, dict):
        return ""
    for k in ("pattern", "query", "question", "symbol", "target", "path"):
        if a.get(k):
            return str(a[k])
    return ""


def _classify(name: str, text: str) -> str:
    t = text.strip()
    low = t.lower()
    if name in {"usages", "neighbors"}:
        return "symbol"
    if name in {"imports"}:
        return "import"
    if name in {"graph"}:
        return "trace"
    # grep/search/read args: infer intent from the string.
    if "import" in low or low.startswith("from ") or "__init__" in low:
        return "import"
    # def/callsite/identifier hunt: has def, a call paren, dotted call, or is a
    # pure identifier alternation (foo|_bar|baz) with no prose spaces.
    if re.search(r"\bdef\b", t) or re.search(r"\.\w+\(", t) or re.search(r"\w+\(", t):
        return "symbol"
    if "|" in t and " " not in t.replace("|", "") and _IDENT_ALT.match(t):
        return "symbol"
    if " " not in t and re.fullmatch(r"[\w.*\\/-]+", t) and "_" in t:
        return "symbol"
    return "text"


def _dedupe(calls: list[dict]) -> list[dict]:
    out: list[dict] = []
    prev = None
    for c in calls:
        key = (c.get("provider"), c.get("name"), _arg(c))
        if key != prev:
            out.append(c)
        prev = key
    return out


def analyze(path: Path) -> None:
    arm = _load(path)
    if not isinstance(arm, dict):
        return
    name = str(arm.get("name") or path.stem)
    raw = [c for c in (arm.get("tool_calls") or []) if isinstance(c, dict)]
    calls = _dedupe(raw)

    disc = [c for c in calls if str(c.get("name") or "") in _DISCOVERY
            and str(c.get("name")) not in {"read"}]  # searches/greps, not reads
    kinds: Counter[str] = Counter()
    for c in disc:
        kinds[_classify(str(c.get("name") or ""), _arg(c))] += 1
    total = sum(kinds.values()) or 1

    # repeated native reads of the same path = dedupe opportunity
    read_paths = Counter()
    for c in calls:
        if str(c.get("name")) == "read":
            p = _arg(c)
            if p:
                read_paths[p] += 1
    repeated = sum(v - 1 for v in read_paths.values() if v > 1)

    print(f"\n=== {name} (deduped discovery ops: {total}) ===")
    for kind in ("symbol", "import", "trace", "text"):
        n = kinds.get(kind, 0)
        print(f"   {kind:<7} {n:>3}  ({n / total * 100:4.0f}%)")
    print(f"   repeated-read opportunities (same path re-read): {repeated}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for d in sys.argv[1:]:
        p = Path(d)
        print(f"\n########## {p.name} ##########")
        for arm_file in sorted(p.glob("*-arm.json")):
            analyze(arm_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

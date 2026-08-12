"""Analyze how the agent actually used tools in saved SDK trial transcripts.

Reads the `*-arm.json` files a trial writes (each has a flattened `tool_calls`
list with name/provider/kind/arguments) and prints, per arm:
  - counts by tool (mcp provider vs native), and the mcp/native split
  - the ordered call sequence (compact) so you can see the workflow
  - sample arguments for discovery tools (search/grep/read/files) = the intent

Usage:
  python scripts/experiments/analyze_tool_usage.py <trial_dir> [<trial_dir> ...]
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_ARG_KEYS = ("query", "pattern", "target", "path", "symbol", "question", "handle")


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"_error": f"{type(exc).__name__}: {exc}"}


def _calls(arm: dict) -> list[dict]:
    calls = arm.get("tool_calls")
    return [c for c in calls if isinstance(c, dict)] if isinstance(calls, list) else []


def _label(call: dict) -> str:
    name = str(call.get("name") or "?")
    provider = str(call.get("provider") or "")
    return f"{provider}:{name}" if provider else f"native:{name}"


def _arg_summary(call: dict) -> str:
    args = call.get("arguments")
    if not isinstance(args, dict):
        return ""
    for key in _ARG_KEYS:
        val = args.get(key)
        if val:
            text = str(val).replace("\n", " ")
            return f"{key}={text[:80]}"
    return ""


def analyze_arm(path: Path) -> None:
    arm = _load(path)
    if not isinstance(arm, dict) or "_error" in arm:
        print(f"  ! {path.name}: {arm.get('_error') if isinstance(arm, dict) else 'bad json'}")
        return
    name = str(arm.get("name") or path.stem)
    calls = _calls(arm)
    counts: Counter[str] = Counter(_label(c) for c in calls)
    mcp = sum(v for k, v in counts.items() if not k.startswith("native:"))
    native = sum(v for k, v in counts.items() if k.startswith("native:"))
    total = mcp + native
    usage = arm.get("usage") or {}
    tokens = usage.get("total_tokens") or usage.get("totalTokens") or "?"

    print(f"\n=== arm: {name}  (tool calls: {total}, tokens: {tokens}) ===")
    print(f"  mcp={mcp}  native={native}  "
          f"mcp_share={(mcp / total * 100):.0f}%" if total else "  (no tool calls)")
    if counts:
        print("  by tool:")
        for label, n in counts.most_common():
            print(f"    {n:>3}  {label}")

    # Discovery intent — the queries/args the agent actually issued.
    discovery = [c for c in calls if str(c.get("name") or "") in
                 {"search", "grep", "read", "files", "usages", "outline",
                  "neighbors", "graph", "imports", "map", "focus", "recall"}]
    if discovery:
        print("  discovery args (in order):")
        for c in discovery[:40]:
            summ = _arg_summary(c)
            print(f"    {_label(c):<28} {summ}")

    # Compact sequence of the whole run.
    seq = [str(c.get("name") or "?") for c in calls]
    if seq:
        print("  sequence:")
        line = " ".join(seq)
        for i in range(0, len(line), 110):
            print(f"    {line[i:i + 110]}")


def analyze_dir(trial_dir: Path) -> None:
    print(f"\n########## {trial_dir.name} ##########")
    results = trial_dir / "results.json"
    if results.is_file():
        data = _load(results)
        arms = data.get("arms") if isinstance(data, dict) else None
        if isinstance(arms, list):
            print("  results.json summary:")
            for a in arms:
                if isinstance(a, dict):
                    print(f"    {a.get('name'):<16} tokens={a.get('total_tokens')} "
                          f"mcp_used={a.get('expected_mcp_used')} "
                          f"work_complete={a.get('work_complete')}")
    for arm_file in sorted(trial_dir.glob("*-arm.json")):
        analyze_arm(arm_file)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    for arg in sys.argv[1:]:
        analyze_dir(Path(arg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

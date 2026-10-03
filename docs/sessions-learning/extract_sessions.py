#!/usr/bin/env python3
"""Walk every harness run dir, normalise each cell into one record, and emit:

  docs/sessions-learning/data/sessions.jsonl   one JSON object per cell (machine)
  docs/sessions-learning/SESSIONS_LOG.md       human-readable run-by-run log

Schema-tolerant: handles the dev-task arm cells (dev_task_mini_bridge) and the
retrieval_challenge cells, plus older untagged reports. Unknown fields are kept
under "extra" so nothing is lost.

Run:
  $env:PYTHONIOENCODING="utf-8"; python docs/sessions-learning/extract_sessions.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # context-engine
RUN_ROOT = ROOT / ".ab_workspaces" / "claude_sdk_harness"
DATA = HERE / "data"
DATA.mkdir(parents=True, exist_ok=True)


def _load(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _num(d: dict, *keys, default=None):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return default


def _config_use(cell: dict) -> dict:
    cu = cell.get("config_use")
    if isinstance(cu, dict) and cu:
        return cu
    # reconstruct from tool_results if present
    out: dict[str, int] = {}
    for tr in cell.get("tool_results") or []:
        if str(tr.get("tool", "")).endswith("__map"):
            cfg = (tr.get("input") or {}).get("config") or "?"
            out[cfg] = out.get(cfg, 0) + 1
    return out


def _tool_sequence(cell: dict) -> list[str]:
    """Compact ordered list of tool calls, e.g. ['map:find','view','Edit','Edit']."""
    seq = []
    for tr in cell.get("tool_results") or []:
        tool = str(tr.get("tool", ""))
        name = tool.split("__")[-1] if "__" in tool else tool
        if name == "map":
            cfg = (tr.get("input") or {}).get("config") or "?"
            seq.append(f"map:{cfg}")
        elif name in ("ToolSearch",):
            continue  # SDK bookkeeping, not a real step
        else:
            seq.append(name)
    return seq


def normalise(cell: dict, run_name: str, kind: str) -> dict:
    """One flat record per cell, tolerant of both schemas."""
    rec = {
        "run": run_name,
        "kind": kind,
        "arm": cell.get("arm"),
        "task": cell.get("task") or cell.get("query") or cell.get("category"),
        "rep": cell.get("rep"),
        "total_tokens": _num(cell, "total_tokens"),
        "cache_read": _num(cell, "cache_read"),
        "output_tokens": _num(cell, "output_tokens"),
        "api_calls": _num(cell, "api_calls"),
        "num_turns": _num(cell, "num_turns"),
        "tool_calls": _num(cell, "tool_calls"),
        "map": _num(cell, "map", default=0),
        "grep": _num(cell, "grep", default=0),
        "read": _num(cell, "read", default=0),
        "edit": _num(cell, "edit", default=0),
        "bash": _num(cell, "bash", default=0),
        "config_use": _config_use(cell),
        "tool_sequence": _tool_sequence(cell),
        "total_result_chars": _num(cell, "total_result_chars"),
        # dev-task oracle
        "oracle_ok": _num(cell, "oracle_ok"),
        "oracle_ratio": _num(cell, "oracle_ratio"),
        "success": cell.get("success"),
        "real_py_edits": cell.get("real_py_edits"),
        # retrieval oracle
        "recall": _num(cell, "recall"),
        "precision": _num(cell, "precision"),
        "f1": _num(cell, "f1"),
        "run_ok": cell.get("run_ok"),
        "is_error": cell.get("is_error"),
    }
    return rec


def iter_cells():
    for run_dir in sorted(RUN_ROOT.glob("*")):
        if not run_dir.is_dir():
            continue
        report = _load(run_dir / "report.json") or {}
        kind = report.get("kind") or "untagged"
        # cells can be inline in report, or separate cell_*.json files
        cells = report.get("cells")
        if isinstance(cells, list) and cells:
            for c in cells:
                if isinstance(c, dict):
                    yield normalise(c, run_dir.name, kind)
        for cf in sorted(run_dir.glob("cell_*.json")):
            c = _load(cf)
            if isinstance(c, dict):
                yield normalise(c, run_dir.name, kind)
        # retrieval arms sometimes written as arm_*.json
        for af in sorted(run_dir.glob("arm_*.json")):
            c = _load(af)
            if isinstance(c, dict):
                yield normalise(c, run_dir.name, kind)


def main() -> int:
    records = list(iter_cells())
    # de-dup: inline report cells + cell_*.json can double-count
    seen = set()
    uniq = []
    for r in records:
        key = (r["run"], r["arm"], r["task"], r["rep"], r["total_tokens"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
    records = uniq

    (DATA / "sessions.jsonl").write_text(
        "\n".join(json.dumps(r, default=str) for r in records) + "\n", encoding="utf-8")

    # human log, grouped by run
    lines = [
        "# Sessions log (auto-generated)",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')} "
        f"from `{RUN_ROOT.relative_to(ROOT)}`.",
        f"{len(records)} cells across {len({r['run'] for r in records})} runs. "
        "Regenerate with `python docs/sessions-learning/extract_sessions.py`.",
        "",
        "Columns: arm | task | tokens | api_calls | map | grep | edit | "
        "oracle/recall | tool sequence",
        "",
    ]
    by_run: dict[str, list[dict]] = {}
    for r in records:
        by_run.setdefault(r["run"], []).append(r)

    def _has_signal(rs: list[dict]) -> bool:
        # keep runs where at least one cell carries a real metric (tokens or oracle)
        return any(r["total_tokens"] or r["recall"] is not None or r["arm"] not in (None, "None")
                   for r in rs)

    scored = {run: rs for run, rs in by_run.items() if _has_signal(rs)}
    skipped = len(by_run) - len(scored)
    lines[3] = (f"{len(records)} cells across {len(by_run)} runs "
                f"({len(scored)} with measured cells, {skipped} empty-scaffold runs omitted below). "
                "Regenerate with `python docs/sessions-learning/extract_sessions.py`.")
    for run in sorted(scored):
        rs = scored[run]
        kind = rs[0]["kind"]
        lines.append(f"## {run}  _({kind})_")
        lines.append("")
        for r in rs:
            tok = r["total_tokens"]
            tok_s = f"{tok:,}" if isinstance(tok, (int, float)) else "-"
            api = r["api_calls"] if r["api_calls"] is not None else "-"
            # pick the right correctness signal
            if r["oracle_ratio"] is not None or r["success"] is not None:
                corr = f"oracle={r['oracle_ratio']}/{r['success']}"
            elif r["recall"] is not None:
                corr = f"recall={r['recall']} prec={r['precision']}"
            else:
                corr = "-"
            seq = " -> ".join(r["tool_sequence"][:14]) or "-"
            cfg = (" cfg=" + ",".join(f"{k}:{v}" for k, v in r["config_use"].items())
                   ) if r["config_use"] else ""
            lines.append(
                f"- **{r['arm']}** | {r['task']} | tok={tok_s} | api={api} | "
                f"map={r['map']} grep={r['grep']} edit={r['edit']} | {corr}{cfg}")
            lines.append(f"  - seq: {seq}")
        lines.append("")
    (HERE / "SESSIONS_LOG.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"wrote {len(records)} cell records")
    print(f"  {DATA / 'sessions.jsonl'}")
    print(f"  {HERE / 'SESSIONS_LOG.md'}")
    # quick coverage summary to stdout
    from collections import Counter
    print("by kind:", dict(Counter(r["kind"] for r in records)))
    print("by arm:", dict(Counter(str(r["arm"]) for r in records)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

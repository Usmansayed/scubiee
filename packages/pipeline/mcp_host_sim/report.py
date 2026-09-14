"""JSON + markdown reports for mcp_host_sim runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_report(
    report: dict[str, Any],
    *,
    out_dir: Path,
    stem: str | None = None,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = stem or f"mcp-host-sim-{ts}"
    json_path = out_dir / f"{base}.json"
    md_path = out_dir / f"{base}.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_to_markdown(report), encoding="utf-8")
    return {"json": json_path, "md": md_path}


def _to_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# MCP host sim — {report.get('scenario', '?')}",
        "",
        f"- **ok:** `{report.get('ok')}`",
        f"- **lane:** `{report.get('lane')}`",
        f"- **elapsed_ms:** `{report.get('elapsed_ms')}`",
        "",
        "| Phase | ok | code | elapsed_ms | budget_ms |",
        "|-------|----|------|------------|-----------|",
    ]
    for phase in report.get("phases") or []:
        lines.append(
            f"| {phase.get('name')} | {phase.get('ok')} | "
            f"{phase.get('code') or ''} | {phase.get('elapsed_ms')} | "
            f"{phase.get('budget_ms') or ''} |"
        )
    errs = report.get("errors") or []
    if errs:
        lines.extend(["", "## Errors", ""])
        for e in errs:
            lines.append(f"- {e}")
    lines.append("")
    return "\n".join(lines)

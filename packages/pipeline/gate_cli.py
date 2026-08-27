"""Local Scubiee gate line for CLI — no daemon I/O."""

from __future__ import annotations

from pathlib import Path


def gate_line_for_root(root: str | Path = "", *, project_id: str = "") -> str:
    """Return compact gate: ``0``, ``0:r``, ``1:ce_…``, or ``p``."""
    from pipeline.mcp_locate import _bind_request_repo, _gate_line
    from pipeline.pause_resume import is_paused

    root_s = str(root).strip()
    with _bind_request_repo(root=root_s, project_id=project_id):
        if is_paused():
            return "p"
        return _gate_line(just_checked=True)


def project_id_from_gate(gate_line: str) -> str:
    """Extract ``ce_…`` from ``1:ce_…``; empty if not managed."""
    if gate_line.startswith("1:"):
        return gate_line.split(":", 1)[1]
    return ""


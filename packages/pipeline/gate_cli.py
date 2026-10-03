"""Local Scubiee gate line for CLI — no daemon I/O."""

from __future__ import annotations

from pathlib import Path


def gate_line_for_root(root: str | Path = "", *, project_id: str = "") -> str:
    """Return compact gate: ``0``, ``0:r``, ``1:ce_…``, or ``p``.

    Local, no daemon I/O. Resolves the managed project_id directly from the
    checkout (``peek_project`` — never mints) instead of going through the old
    MCP tool layer (retired in the Map V3 migration).
    """
    from pipeline.pause_resume import is_paused, is_resuming
    from pipeline.project_id import _is_enrolled, peek_project

    if is_paused() and not is_resuming():
        return "p"

    root_s = str(root).strip()
    try:
        base = Path(root_s).resolve() if root_s else Path.cwd()
    except OSError:
        return "0"

    # Explicit project_id wins (caller already resolved it).
    pid = (project_id or "").strip()
    if not pid:
        try:
            ref = peek_project(base)
            pid = (getattr(ref, "project_id", "") or "").strip() if ref else ""
        except Exception:  # noqa: BLE001
            pid = ""

    if pid:
        return f"1:{pid}"
    # Enrolled but id unreadable → managed without id; else unmanaged (resolvable).
    try:
        return "1" if _is_enrolled(base) else "0:r"
    except Exception:  # noqa: BLE001
        return "0"


def project_id_from_gate(gate_line: str) -> str:
    """Extract ``ce_…`` from ``1:ce_…``; empty if not managed."""
    if gate_line.startswith("1:"):
        return gate_line.split(":", 1)[1]
    return ""


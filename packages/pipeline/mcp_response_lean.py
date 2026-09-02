"""Optional MCP JSON trims — reliability first, token savings opt-in only.

Default: no trimming. Set ``CTX_MCP_LEAN_ECHO=1`` to drop only the echoed
``budget`` field (the agent already passed it in the tool call). Session hints,
dedup signals, and boolean status fields are never suppressed.
"""

from __future__ import annotations

import os
from typing import Any, Callable


def lean_echo_enabled() -> bool:
    """True only when explicitly opted in via CTX_MCP_LEAN_ECHO=1."""
    raw = (os.environ.get("CTX_MCP_LEAN_ECHO") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def reset_session_hint_echo_cache() -> None:
    """No-op — kept for test compatibility. Echo-once was removed (reliability)."""
    return None


def apply_lean_fields(card: dict[str, Any]) -> dict[str, Any]:
    """Opt-in: drop echoed request fields only. Never touch status/dedup booleans."""
    if not lean_echo_enabled() or not isinstance(card, dict):
        return card
    out = dict(card)
    # Echo of tool input — agent already passed budget in the call args.
    if "budget" in out:
        out.pop("budget", None)
    return out


def attach_gate_lean(
    card: dict[str, Any],
    *,
    gate_line: Callable[..., str],
    session_context: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Universal compact gate + full session echo on every tool JSON (unchanged semantics)."""
    if not isinstance(card, dict):
        return card
    out = apply_lean_fields(card)
    out.setdefault("g", gate_line(just_checked=False))
    if out.get("ok") is not False and "session_id" not in out:
        ctx = session_context()
        sid = ctx.get("session_id")
        if sid and sid != "default":
            out.setdefault("session_id", sid)
            out.setdefault("session_source", ctx.get("source"))
            if ctx.get("shared_process_risk"):
                out.setdefault("session_shared_risk", True)
            if ctx.get("hint") and not out.get("session_hint"):
                out.setdefault("session_hint", ctx.get("hint"))
    return out

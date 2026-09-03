"""MCP JSON trims that do not change locate semantics.

Always: drop echoed ``budget`` (the agent already passed it). Never touch
status/dedup booleans, code/text, handles, or next/stop_locate.

Session isolation: ``session_id`` and ``session_shared_risk`` are echoed on
every call. Long ``session_hint`` prose is echoed once per session_id (re-echo
when the session id changes, e.g. a new chat after init).

``CTX_MCP_ECHO_BUDGET=1`` restores the echoed budget field for debugging.
"""

from __future__ import annotations

import os
from typing import Any, Callable

_HINT_ECHOED_SIDS: set[str] = set()


def echo_budget_enabled() -> bool:
    """True only when debugging via CTX_MCP_ECHO_BUDGET=1."""
    raw = (os.environ.get("CTX_MCP_ECHO_BUDGET") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def lean_echo_enabled() -> bool:
    """Budget is dropped by default. True unless CTX_MCP_ECHO_BUDGET=1.

    Kept for tests/callers that used CTX_MCP_LEAN_ECHO; that flag is ignored
    (lean is now the default).
    """
    return not echo_budget_enabled()


def reset_session_hint_echo_cache() -> None:
    """Clear once-per-session hint cache (tests + new MCP process)."""
    _HINT_ECHOED_SIDS.clear()


def apply_lean_fields(card: dict[str, Any]) -> dict[str, Any]:
    """Drop echoed request fields only. Never touch status/dedup/code."""
    if not isinstance(card, dict):
        return card
    if echo_budget_enabled():
        return card
    out = dict(card)
    out.pop("budget", None)
    return out


def attach_gate_lean(
    card: dict[str, Any],
    *,
    gate_line: Callable[..., str],
    session_context: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Compact gate on every JSON; session flags always; hint prose once per sid."""
    if not isinstance(card, dict):
        return card
    out = apply_lean_fields(card)
    out.setdefault("g", gate_line(just_checked=False))
    if out.get("ok") is False:
        return out
    ctx = session_context()
    sid = str(out.get("session_id") or ctx.get("session_id") or "").strip()
    if not sid or sid == "default":
        return out
    out.setdefault("session_id", sid)
    if ctx.get("source"):
        out.setdefault("session_source", ctx.get("source"))
    if ctx.get("shared_process_risk"):
        out.setdefault("session_shared_risk", True)
    hint = ctx.get("hint")
    if hint and not out.get("session_hint") and sid not in _HINT_ECHOED_SIDS:
        out["session_hint"] = hint
        _HINT_ECHOED_SIDS.add(sid)
    return out

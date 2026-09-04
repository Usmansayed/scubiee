"""MCP JSON trims — payload first (lesson: per-call coaching burned tokens).

Default (lean): return what the tool was asked for (hits/files/cards/code) plus
real signals (ok, truncated, handles, weak_match). Drop echoed ``budget``,
session chrome, and prescription fields (``next``, ``usage_hint``,
``locate_action``, per-card ``needs_outline`` / ``span_hint`` / ``follow_up``).
How/when/why to use tools lives in server instructions + project rules — not
repeated on every JSON response.

Never strip status/dedup booleans, code/text, handles, or truncation signals
(``truncated``, ``has_more``, ``next_start_line``).

Opt-in restore:
  CTX_MCP_ECHO_BUDGET=1   — keep echoed budget
  CTX_MCP_ECHO_SESSION=1  — session_source / session_shared_risk / session_hint
  CTX_MCP_ECHO_GUIDANCE=1 — next / usage_hint / locate_action / card coaching
"""

from __future__ import annotations

import os
from typing import Any, Callable

_HINT_ECHOED_SIDS: set[str] = set()
_CARD_COACHING_KEYS = (
    "needs_outline",
    "span_hint",
    "facade_hint",
    "follow_up",
    "next",
    "usage_hint",
)


def _env_flag(name: str) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def echo_budget_enabled() -> bool:
    """True only when debugging via CTX_MCP_ECHO_BUDGET=1."""
    return _env_flag("CTX_MCP_ECHO_BUDGET")


def echo_session_enabled() -> bool:
    """True when session chrome should be echoed (default: off)."""
    return _env_flag("CTX_MCP_ECHO_SESSION")


def echo_guidance_enabled() -> bool:
    """True when next/usage_hint/locate_action should be echoed (default: off)."""
    return _env_flag("CTX_MCP_ECHO_GUIDANCE")


def lean_echo_enabled() -> bool:
    """Budget is dropped by default. True unless CTX_MCP_ECHO_BUDGET=1."""
    return not echo_budget_enabled()


def reset_session_hint_echo_cache() -> None:
    """Clear once-per-session hint cache (tests + new MCP process)."""
    _HINT_ECHOED_SIDS.clear()


def _strip_card_coaching(item: dict[str, Any]) -> None:
    for key in _CARD_COACHING_KEYS:
        item.pop(key, None)


def apply_lean_fields(card: dict[str, Any]) -> dict[str, Any]:
    """Drop chrome that does not change locate fidelity."""
    if not isinstance(card, dict):
        return card
    out = dict(card)
    if not echo_budget_enabled():
        out.pop("budget", None)

    if not echo_guidance_enabled() and out.get("ok") is not False:
        for key in ("next", "usage_hint", "locate_action"):
            out.pop(key, None)
        # Success cards don't need a coaching hint; keep error hints.
        if "error" not in out:
            out.pop("hint", None)
        for list_key in ("cards", "results", "hits"):
            rows = out.get(list_key)
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        _strip_card_coaching(row)

    if not echo_session_enabled():
        out.pop("session_source", None)
        out.pop("session_shared_risk", None)
        out.pop("session_hint", None)

    # Meta noise when body/hits are present and not truncated.
    if out.get("ok") is not False and not out.get("truncated") and not out.get("has_more"):
        for key in ("chars_returned", "lines_returned", "lines_total"):
            # Keep lines_total only when useful for pagination; drop chars_* noise.
            if key == "lines_total" and out.get("next_start_line"):
                continue
            if key in {"chars_returned", "lines_returned"}:
                out.pop(key, None)

    return out


def attach_gate_lean(
    card: dict[str, Any],
    *,
    gate_line: Callable[..., str],
    session_context: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Compact gate on every JSON; session_id always; chrome only when opted in."""
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

    if echo_session_enabled():
        if ctx.get("source"):
            out.setdefault("session_source", ctx.get("source"))
        if ctx.get("shared_process_risk"):
            out.setdefault("session_shared_risk", True)
        hint = ctx.get("hint")
        if hint and not out.get("session_hint") and sid not in _HINT_ECHOED_SIDS:
            out["session_hint"] = hint
            _HINT_ECHOED_SIDS.add(sid)
    return out

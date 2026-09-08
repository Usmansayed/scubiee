"""MCP JSON trims — payload first (lesson: per-call coaching burned tokens).

Default (lean): return what the tool was asked for (hits/files/cards/code) plus
real signals (ok, truncated, handles, weak_match). Drop echoed ``budget``,
session chrome, and prescription fields (``next``, ``usage_hint``,
``locate_action``, per-card ``needs_outline`` / ``span_hint`` / ``follow_up``).
How/when/why to use tools lives in server instructions + project rules — not
repeated on every JSON response.

Locate tools (``pack_context`` / ``map_context`` / ``expand_context`` / …):
default agent pack view is a **compressed heatmap** (locs + heat ranks, no code bodies)
plus ``read.top`` guidance. Duplicate guide/howto/next_actions / engine meta are stripped.
Bodies: Native-Read ``loc`` spans, or ``collect_hot_context`` / ``CTX_MCP_PACK_BODIES=1``.

Never strip status/dedup booleans, handles, or truncation signals
(``truncated``, ``has_more``, ``next_start_line``).

Opt-in restore:
  CTX_MCP_ECHO_BUDGET=1   — keep echoed budget
  CTX_MCP_ECHO_SESSION=1  — session_source / session_shared_risk / session_hint
  CTX_MCP_ECHO_GUIDANCE=1 — next / usage_hint / locate_action / card coaching
                            + full locate chrome (heatmap/guide/next_actions)
  CTX_MCP_FULL_LOCATE=1   — full locate payloads without enabling other guidance
  CTX_MCP_PACK_BODIES=1   — pack tools include code bodies again (legacy)
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

_LOCATE_SLIM_TOOLS = frozenset(
    {
        "map",
        "map_context",
        "pack",
        "pack_context",
        "pack_poly_embed",
        "pack_semantic",
        "expand",
        "expand_context",
        "collect_hot_context",
    }
)

_LOCATE_META_DROP = frozenset(
    {
        "guide",
        "howto",
        "ladder",
        "next_actions",
        "query_tip",
        "next_cli",
        "engine",
        "graphify",
        "n_nodes",
        "budget_chars",
        "hot_threshold",
        "max_bodies",
        "calls",
        "chars",
        "packed",
        "count",
        "latency_ms",
        "query",  # already known to the caller
        "mode",
        "policy",
        "ranked_only",
        "bodies",  # boolean flag on expand/map_context — redundant with pack presence
        "seed2",
    }
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


def full_locate_enabled() -> bool:
    """True when locate tools should keep heatmap/guide chrome."""
    return echo_guidance_enabled() or _env_flag("CTX_MCP_FULL_LOCATE")


def pack_bodies_enabled() -> bool:
    """True when pack tools should collect/return code bodies (CTX_MCP_PACK_BODIES=1)."""
    return _env_flag("CTX_MCP_PACK_BODIES")


def lean_echo_enabled() -> bool:
    """Budget is dropped by default. True unless CTX_MCP_ECHO_BUDGET=1."""
    return not echo_budget_enabled()


def reset_session_hint_echo_cache() -> None:
    """Clear once-per-session hint cache (tests + new MCP process)."""
    _HINT_ECHOED_SIDS.clear()


def _strip_card_coaching(item: dict[str, Any]) -> None:
    for key in _CARD_COACHING_KEYS:
        item.pop(key, None)


def _pick(d: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {k: d[k] for k in keys if k in d and d[k] is not None}


def _slim_pack_item(item: dict[str, Any]) -> dict[str, Any]:
    """Optional body escape hatch — keep id/loc/text only."""
    out = _pick(item, ("id", "loc", "text"))
    if "text" not in out and item.get("body") is not None:
        out["text"] = item.get("body")
    return out


def _slim_loc_item(item: dict[str, Any] | str) -> dict[str, Any] | str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return item
    return _pick(item, ("id", "loc", "edge", "score"))


def _heat_card(
    item: dict[str, Any],
    *,
    rank: int,
    heat: str,
    edge: str | None = None,
) -> dict[str, Any]:
    """Compressed heatmap row — locs only, no code."""
    iid = str(item.get("id") or "")
    loc = str(item.get("loc") or "")
    sym = str(item.get("symbol") or "")
    if not sym and "::" in iid:
        sym = iid.split("::", 1)[-1]
    out: dict[str, Any] = {
        "r": rank,
        "heat": heat,
        "id": iid,
        "loc": loc,
        "s": sym,
        "sc": round(float(item.get("score") or 0), 4),
    }
    if edge:
        out["e"] = edge
    return out


def _pack_heatmap_only(payload: dict[str, Any], *, tool_name: str) -> dict[str, Any]:
    """Merge pack/chain/cold into one ranked heatmap (no bodies)."""
    hot_ids: set[str] = set()
    edge_by: dict[str, str] = {}
    by_id: dict[str, dict[str, Any]] = {}

    for p in payload.get("pack") or []:
        if not isinstance(p, dict):
            continue
        iid = str(p.get("id") or "")
        if not iid:
            continue
        hot_ids.add(iid)
        by_id[iid] = dict(p)

    for c in payload.get("chain") or []:
        if not isinstance(c, dict):
            continue
        iid = str(c.get("id") or "")
        if not iid:
            continue
        if c.get("edge"):
            edge_by[iid] = str(c.get("edge"))
        by_id.setdefault(iid, dict(c))

    for c in payload.get("cold") or []:
        if not isinstance(c, dict):
            continue
        iid = str(c.get("id") or "")
        if not iid:
            continue
        by_id.setdefault(iid, dict(c))

    for c in payload.get("heatmap") or []:
        if not isinstance(c, dict):
            continue
        iid = str(c.get("id") or "")
        if not iid:
            continue
        cur = by_id.get(iid) or {}
        merged = dict(c)
        merged.update({k: v for k, v in cur.items() if v not in (None, "")})
        by_id[iid] = merged

    # When include_bodies=False, hot nodes are those omitted from cold (not in pack[]).
    if not hot_ids and by_id:
        cold_ids = {
            str(c.get("id") or "")
            for c in (payload.get("cold") or [])
            if isinstance(c, dict) and c.get("id")
        }
        if cold_ids:
            hot_ids = {i for i in by_id if i not in cold_ids}
        else:
            ranked = sorted(by_id.values(), key=lambda c: -float(c.get("score") or 0))
            for c in ranked[:4]:
                iid = str(c.get("id") or "")
                if iid:
                    hot_ids.add(iid)

    rows = list(by_id.values())
    rows.sort(key=lambda c: -float(c.get("score") or 0))
    heatmap: list[dict[str, Any]] = []
    for i, c in enumerate(rows, 1):
        iid = str(c.get("id") or "")
        if iid in hot_ids:
            heat = "hot"
        elif iid in edge_by:
            heat = "warm"
        else:
            heat = "cold"
        heatmap.append(_heat_card(c, rank=i, heat=heat, edge=edge_by.get(iid)))

    seed = payload.get("seed")
    return {
        "ok": True,
        "tool": tool_name,
        "seed": (
            _pick(seed, ("id", "file", "symbol"))
            if isinstance(seed, dict)
            else seed
        ),
        "heatmap": heatmap,
        "read": {
            "top": 5,
            "how": (
                "Native-Read loc spans for top ~5 (heat=hot first, then warm) — "
                "file:start-end only. BAN whole-file Read of heatmap paths. "
                "expand_context if a hop is missing; collect_hot_context(ids=) "
                "or pack_context(include_bodies=1) only when you need bodies batched."
            ),
        },
    }


def _tool_name(payload: dict[str, Any]) -> str:
    return str(payload.get("tool") or payload.get("cli") or "").strip()


def slim_locate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Agent locate view: map cards / pack heatmap locs (default: no pack bodies).

    Used by MCP (via ``apply_lean_fields``) and CLI (``slim_cli_payload``).
    """
    if not isinstance(payload, dict):
        return payload
    if payload.get("ok") is False:
        return _pick(payload, ("ok", "tool", "error", "hint", "cli", "g")) or dict(payload)

    tool = _tool_name(payload)
    # Preserve CLI short names when ``cli`` is set.
    if payload.get("cli") == "pack":
        tool_out = "pack"
    elif payload.get("cli") == "expand":
        tool_out = "expand"
    elif payload.get("cli") == "map":
        tool_out = "map"
    else:
        tool_out = payload.get("tool") or tool or "pack"

    if tool in {"map"} or payload.get("cli") == "map":
        cards_in = payload.get("cards") or []
        cards = [
            _pick(c, ("rank", "file", "score", "why", "role", "loc", "symbol"))
            for c in cards_in
            if isinstance(c, dict)
        ]
        seed = payload.get("suggested_seed")
        seed_slim = (
            _pick(seed, ("file", "symbol", "loc", "score"))
            if isinstance(seed, dict)
            else seed
        )
        out: dict[str, Any] = {
            "ok": True,
            "tool": tool_out if tool_out in {"map", "map_context"} else "map",
            "cards": cards,
            "suggested_seed": seed_slim,
        }
        # CLI map: keep the one-line pack command. MCP map: no per-call coaching.
        nxt = payload.get("next")
        if payload.get("cli") == "map" and nxt:
            out["next"] = nxt
        elif isinstance(nxt, str) and nxt.strip().startswith("scubiee pack"):
            out["next"] = nxt
        for sig in ("unchanged", "truncated", "has_more", "weak_match"):
            if sig in payload:
                out[sig] = payload[sig]
        return out

    if tool in {"map_context"}:
        heat = [
            _pick(c, ("rank", "id", "loc", "score", "symbol"))
            for c in (payload.get("heatmap") or [])
            if isinstance(c, dict)
        ]
        seed = payload.get("seed")
        return {
            "ok": True,
            "tool": "map_context",
            "seed": (
                _pick(seed, ("id", "file", "symbol"))
                if isinstance(seed, dict)
                else seed
            ),
            "heatmap": heat,
        }

    if tool in {
        "pack",
        "pack_context",
        "pack_poly_embed",
        "pack_semantic",
    } or payload.get("cli") == "pack":
        named = str(tool_out or payload.get("tool") or "pack_context")
        if named not in {"pack", "pack_context", "pack_poly_embed", "pack_semantic"}:
            named = "pack_context"
        # Default: compressed heatmap only (no code). Opt-in bodies via env/flag.
        # If pack[] already carries body text (CLI default / opt-in MCP), keep that shape.
        pack_rows = payload.get("pack") or []
        has_body_text = any(
            isinstance(p, dict) and (p.get("text") or p.get("code")) for p in pack_rows
        )
        want_bodies = (
            bool(payload.get("include_bodies"))
            or pack_bodies_enabled()
            or has_body_text
        )
        if want_bodies and pack_rows:
            return {
                "ok": True,
                "tool": named,
                "seed": (
                    _pick(payload["seed"], ("id", "file", "symbol"))
                    if isinstance(payload.get("seed"), dict)
                    else payload.get("seed")
                ),
                "chain": [_slim_loc_item(c) for c in (payload.get("chain") or [])],
                "pack": [
                    _slim_pack_item(p)
                    for p in (payload.get("pack") or [])
                    if isinstance(p, dict)
                ],
                "cold": [_slim_loc_item(c) for c in (payload.get("cold") or [])],
            }
        return _pack_heatmap_only(payload, tool_name=named)

    if tool in {"expand", "expand_context"} or payload.get("cli") == "expand":
        # Session/nav ``expand`` (handle → body) must keep text/code. Only slim
        # locate ``expand_context`` (direction/delta graph walk).
        if payload.get("handle") or (
            "text" in payload and payload.get("direction") is None and not payload.get("delta")
        ):
            keep = (
                "ok",
                "tool",
                "handle",
                "file",
                "start_line",
                "end_line",
                "text",
                "code",
                "why",
                "g",
            )
            out = _pick(payload, keep) or {"ok": True, "tool": "expand"}
            out.setdefault("ok", True)
            out.setdefault("tool", "expand")
            return out
        out = {
            "ok": True,
            "tool": tool_out if tool_out in {"expand", "expand_context"} else "expand_context",
            "from": payload.get("from"),
            "direction": payload.get("direction"),
            "delta": [_slim_loc_item(c) for c in (payload.get("delta") or [])],
        }
        pack = payload.get("pack") or []
        if pack:
            out["pack"] = [
                _slim_pack_item(p) for p in pack if isinstance(p, dict)
            ]
        return out

    if tool == "collect_hot_context":
        bodies = payload.get("bodies") or payload.get("pack") or []
        out = {
            "ok": True,
            "tool": "collect_hot_context",
            "pack": [
                _slim_pack_item(p) for p in bodies if isinstance(p, dict)
            ],
        }
        return out

    # Unknown locate-ish payload — strip common chrome only.
    return {k: v for k, v in payload.items() if k not in _LOCATE_META_DROP and k != "heatmap"}


def apply_lean_fields(card: dict[str, Any]) -> dict[str, Any]:
    """Drop chrome that does not change locate fidelity."""
    if not isinstance(card, dict):
        return card
    out = dict(card)
    if not echo_budget_enabled():
        out.pop("budget", None)

    # Locate tools first (while map ``next`` / bodies still present).
    tool = _tool_name(out)
    if (
        out.get("ok") is not False
        and tool in _LOCATE_SLIM_TOOLS
        and not full_locate_enabled()
    ):
        keep_g = out.get("g")
        keep_sid = out.get("session_id")
        out = slim_locate_payload(out)
        if keep_g is not None:
            out["g"] = keep_g
        if keep_sid:
            out["session_id"] = keep_sid
        tool = _tool_name(out)

    if not echo_guidance_enabled() and out.get("ok") is not False:
        for key in ("usage_hint", "locate_action"):
            out.pop(key, None)
        # Soft map keeps a one-line pack command; other tools drop ``next``.
        if tool not in {"map"} or "next" not in out:
            out.pop("next", None)
        elif not str(out.get("next") or "").strip().startswith("scubiee pack"):
            out.pop("next", None)
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

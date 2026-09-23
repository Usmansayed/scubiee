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
    return _pick(item, ("id", "loc", "edge", "score", "symbol", "already_in_pack"))


def _ensure_loc(item: dict[str, Any]) -> str:
    """Prefer explicit loc; else synthesize file:start-end for span-Read."""
    loc = str(item.get("loc") or "").strip()
    if loc:
        return loc
    f = str(item.get("file") or "").replace("\\", "/").strip()
    if not f and "::" in str(item.get("id") or ""):
        f = str(item.get("id") or "").split("::", 1)[0]
    sl = item.get("start_line")
    el = item.get("end_line")
    if f and sl not in (None, "", 0, "0"):
        try:
            start = int(sl)
            end = int(el) if el not in (None, "") else start
        except (TypeError, ValueError):
            return f
        return f"{f}:{start}-{end}"
    return f


def _row_score(item: dict[str, Any]) -> float:
    """Rank score from either the raw card or an already-slimmed row.

    A second lean pass only has ``sc``. ``score or 0`` treated that as missing
    and wrote 0, which also made hot/cold follow row order instead of rank.
    """
    for key in ("score", "sc"):
        if key not in item:
            continue
        raw = item.get(key)
        if raw is None or raw == "":
            continue
        try:
            return float(raw)
        except (TypeError, ValueError):
            continue
    return 0.0


def _heat_card(
    item: dict[str, Any],
    *,
    rank: int,
    heat: str,
    edge: str | None = None,
) -> dict[str, Any]:
    """Compressed heatmap row — locs only, no code."""
    iid = str(item.get("id") or "")
    loc = _ensure_loc(item)
    sym = str(item.get("symbol") or "")
    if not sym and "::" in iid:
        sym = iid.split("::", 1)[-1]
    out: dict[str, Any] = {
        "r": rank,
        "heat": heat,
        "id": iid,
        "loc": loc,
        "s": sym,
        "sc": round(_row_score(item), 4),
    }
    if edge:
        out["e"] = edge
    return out


_PACK_HEATMAP_NEXT = (
    "Native-Read top heatmap loc spans (file:start-end only). "
    "Thin → expand_context; bodies → collect_hot_context(ids=) or "
    "pack_context(include_bodies=1). BAN whole-file Read of heatmap paths."
)

_MAP_LADDER_NEXT = (
    "Refine query with suggested_seed file+symbol, then "
    "pack_context(mode=lean, seed_*). Then Native-Read loc spans only "
    "(BAN whole-file until expand/collect)."
)


def _pack_seed_ids(payload: dict[str, Any]) -> set[str]:
    """Primary + optional seed2/seed3 / seeds[] ids that must stay hot and front-ranked."""
    out: set[str] = set()
    for key in ("seed", "seed2", "seed3"):
        s = payload.get(key)
        if isinstance(s, dict):
            iid = str(s.get("id") or "")
            if iid:
                out.add(iid)
            elif s.get("file"):
                f = str(s.get("file") or "").replace("\\", "/")
                sym = str(s.get("symbol") or "")
                out.add(f"{f}::{sym}" if sym else f)
    for s in payload.get("seeds") or []:
        if not isinstance(s, dict):
            continue
        iid = str(s.get("id") or "")
        if iid:
            out.add(iid)
            continue
        f = str(s.get("file") or "").replace("\\", "/")
        sym = str(s.get("symbol") or "")
        if f:
            out.add(f"{f}::{sym}" if sym else f)
    return out


def _pack_heatmap_only(payload: dict[str, Any], *, tool_name: str) -> dict[str, Any]:
    """Merge pack/chain/cold into one ranked heatmap (no bodies)."""
    hot_ids: set[str] = set()
    edge_by: dict[str, str] = {}
    by_id: dict[str, dict[str, Any]] = {}
    seed_ids = _pack_seed_ids(payload)

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
        for key, val in cur.items():
            if val in (None, ""):
                continue
            if key in {"score", "sc"}:
                try:
                    if float(val) > _row_score(merged):
                        merged[key] = val
                except (TypeError, ValueError):
                    pass
                continue
            merged[key] = val
        by_id[iid] = merged

    # Heat follows the ranker score. ``cold`` means "no body was collected",
    # not "low score" — a 0.99 callee must stay hot on the default heatmap.
    try:
        hot_threshold = float(payload.get("hot_threshold") or 0.65)
    except (TypeError, ValueError):
        hot_threshold = 0.65

    rows = list(by_id.values())

    def _rank_key(c: dict[str, Any]) -> tuple[int, float]:
        iid = str(c.get("id") or "")
        # Seeds first (stable order among seeds by score), then everyone else by score.
        seed_ord = 0 if iid in seed_ids else 1
        return (seed_ord, -_row_score(c))

    rows.sort(key=_rank_key)
    heatmap: list[dict[str, Any]] = []
    for i, c in enumerate(rows, 1):
        iid = str(c.get("id") or "")
        sc = _row_score(c)
        if iid in seed_ids or iid in hot_ids or sc >= hot_threshold:
            heat = "hot"
        elif iid in edge_by or sc >= 0.4:
            heat = "warm"
        else:
            heat = "cold"
        heatmap.append(_heat_card(c, rank=i, heat=heat, edge=edge_by.get(iid)))

    seed = payload.get("seed")
    thin = bool(payload.get("thin"))
    if not thin:
        try:
            from pipeline.context_trace import heatmap_is_thin

            thin = heatmap_is_thin(
                [
                    {
                        **c,
                        "symbol": c.get("s") or c.get("symbol"),
                        "score": _row_score(c),
                    }
                    for c in heatmap
                ]
            )
        except Exception:  # noqa: BLE001
            thin = len(heatmap) <= 3
    prefer = payload.get("prefer") or (
        "expand_context|Native-Read seed file" if thin else "Native-Read heatmap locs"
    )
    next_msg = (
        "thin=true — expand_context or Native-Read seed file; do not re-pack. "
        "BAN whole-file Read of heatmap paths."
        if thin
        else _PACK_HEATMAP_NEXT
    )
    out_hm: dict[str, Any] = {
        "ok": True,
        "tool": tool_name,
        "seed": (
            _pick(seed, ("id", "file", "symbol"))
            if isinstance(seed, dict)
            else seed
        ),
        "heatmap": heatmap,
        "thin": thin,
        "prefer": prefer,
        "read": {
            "top": 5,
            "how": (
                "Native-Read loc spans for top ~5 (heat=hot first, then warm) — "
                "file:start-end only. BAN whole-file Read of heatmap paths. "
                "expand_context if a hop is missing; collect_hot_context(ids=) "
                "or pack_context(include_bodies=1) only when you need bodies batched."
            ),
        },
        # Compact ladder steer — hosts strip verbose next_actions in lean mode.
        "next": next_msg,
    }
    for key in ("seed2", "seed3", "seeds", "multi_seed", "seed_coverage", "seed_injected", "elapsed_ms", "timing", "sla", "sla_hint"):
        val = payload.get(key)
        if val not in (None, "", [], {}):
            if key in {"seed2", "seed3"} and isinstance(val, dict):
                out_hm[key] = _pick(val, ("id", "file", "symbol"))
            elif key == "seeds" and isinstance(val, list):
                out_hm[key] = [
                    _pick(s, ("id", "file", "symbol"))
                    for s in val
                    if isinstance(s, dict)
                ]
            else:
                out_hm[key] = val
    if "escape_helped" in payload:
        out_hm["escape_helped"] = bool(payload.get("escape_helped"))
    if payload.get("seed_promoted"):
        out_hm["seed_promoted"] = payload.get("seed_promoted")
    return out_hm


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
        cards = []
        for c in cards_in:
            if not isinstance(c, dict):
                continue
            row = _pick(c, ("rank", "file", "score", "why", "role", "loc", "symbol", "source"))
            # Ensure span-Read loc when map cards only had file/lines.
            loc = _ensure_loc(c)
            if loc:
                row["loc"] = loc
            cards.append(row)
        seed = payload.get("suggested_seed")
        seed_slim = (
            _pick(seed, ("file", "symbol", "loc", "score", "kind", "seed_incomplete"))
            if isinstance(seed, dict)
            else seed
        )
        if isinstance(seed_slim, dict) and seed and isinstance(seed, dict):
            seed_loc = _ensure_loc(seed)
            if seed_loc:
                seed_slim["loc"] = seed_loc
            if seed.get("seed_incomplete"):
                seed_slim["seed_incomplete"] = True
        seeds_out: list[dict[str, Any]] = []
        for s in payload.get("suggested_seeds") or []:
            if not isinstance(s, dict):
                continue
            row = _pick(s, ("file", "symbol", "loc", "score", "kind", "seed_incomplete"))
            loc = _ensure_loc(s)
            if loc:
                row["loc"] = loc
            if s.get("seed_incomplete"):
                row["seed_incomplete"] = True
            if row.get("file"):
                seeds_out.append(row)
        out: dict[str, Any] = {
            "ok": True,
            "tool": tool_out if tool_out in {"map", "map_context"} else "map",
            "cards": cards,
            "suggested_seed": seed_slim,
        }
        if seeds_out:
            out["suggested_seeds"] = seeds_out
        # Keep ladder steer for both CLI and MCP (was CLI-only / scubiee-pack prefix).
        nxt = payload.get("next")
        if isinstance(nxt, str) and nxt.strip():
            out["next"] = nxt.strip()
        else:
            out["next"] = _MAP_LADDER_NEXT
        timings = payload.get("timings") if isinstance(payload.get("timings"), dict) else {}
        mode = payload.get("retrieve_mode") or timings.get("retrieve_mode")
        dense_flag = payload.get("dense")
        if dense_flag is None:
            dense_flag = timings.get("dense")
        if dense_flag is True:
            out["dense"] = True
        if mode:
            out["retrieve_mode"] = mode
        if timings:
            slim_t = {
                k: timings[k]
                for k in ("dense", "retrieve_mode", "embed_ms", "retrieve_ms")
                if k in timings
            }
            if slim_t:
                out["timings"] = slim_t
        for sig in ("unchanged", "truncated", "has_more", "weak_match", "elapsed_ms", "latency_ms"):
            if sig in payload:
                out[sig] = payload[sig]
        # Normalize CLI latency_ms → elapsed_ms for agents.
        if "elapsed_ms" not in out and "latency_ms" in payload:
            out["elapsed_ms"] = payload["latency_ms"]
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
        if "elapsed_ms" in payload:
            out["elapsed_ms"] = payload["elapsed_ms"]
        # Keep hydrate/struct timings so hosts can see the 50MB AST pickle tax
        # vs the cheap script-neighbor walk (not semantic search).
        for key in ("hydrate_ms", "hydrate_source", "timings", "count"):
            if key in payload:
                out[key] = payload[key]
        return out

    if tool == "collect_hot_context":
        bodies = payload.get("bodies") or payload.get("pack") or []
        slim_bodies = [
            _slim_pack_item(p) for p in bodies if isinstance(p, dict)
        ]
        out = {
            "ok": True,
            "tool": "collect_hot_context",
            "pack": slim_bodies,
            "count": int(payload.get("count") or len(slim_bodies)),
        }
        nxt = payload.get("next")
        if isinstance(nxt, str) and nxt.strip():
            out["next"] = nxt.strip()
        if payload.get("empty_bodies") or not slim_bodies:
            out["empty_bodies"] = True
            out["hint"] = str(
                payload.get("hint")
                or (
                    "No bodies collected — ids missing from index, already packed, "
                    "or below threshold. Pass ids= from heatmap locs, or Native-Read "
                    "file:start-end spans."
                )
            )
            out.setdefault(
                "next",
                "Native-Read heatmap loc spans, or retry collect_hot_context(ids=file::symbol).",
            )
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
        # Keep compact ladder ``next`` on locate tools (MCP + CLI). Drop other noise.
        _keep_next = {
            "map",
            "map_context",
            "pack",
            "pack_context",
            "pack_poly_embed",
            "pack_semantic",
            "expand_context",
            "collect_hot_context",
        }
        if tool not in _keep_next:
            out.pop("next", None)
        # Success cards don't need a coaching hint — except empty collect_hot.
        if "error" not in out and not out.get("empty_bodies"):
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

"""Stable user-facing status contract for background synchronization."""

from __future__ import annotations

from typing import Any


SYNC_STATUSES = {
    "ready",
    "syncing",
    "overlay_ready",
    "dense_pending",
    "deferred",
    "catching_up",
    "needs_full",
    "error",
}


def derive_sync_status(
    *,
    dirty: dict[str, Any] | None = None,
    syncing: bool = False,
    publish_pending: bool = False,
    needs_full: bool = False,
    catchup_chunked: bool = False,
    last_result: dict[str, Any] | None = None,
    strategy: str | None = None,
    error: str | None = None,
    dense_pending: bool = False,
    resource_deferred: bool = False,
) -> str:
    """Collapse internal sync state into one stable status value."""
    result = last_result or {}
    effective_strategy = str(strategy or result.get("strategy") or "")
    effective_error = error if error is not None else result.get("error")
    dense_is_pending = bool(dense_pending or result.get("dense_pending"))

    if needs_full or effective_strategy in {"full", "explicit_full_index_required"}:
        return "needs_full"
    if catchup_chunked or effective_strategy == "catchup_chunked":
        return "catching_up"
    if resource_deferred or effective_strategy == "deferred":
        return "deferred"
    if dense_is_pending:
        return "dense_pending"
    if effective_error:
        return "error"
    if syncing:
        return "syncing"

    paths = (dirty or {}).get("paths") or {}
    states = {
        str(entry.get("state"))
        for entry in paths.values()
        if isinstance(entry, dict)
    }
    if publish_pending or "overlay_ready" in states:
        return "overlay_ready"
    if states.intersection({"queued", "due", "processing"}):
        return "syncing"
    return "ready"


def build_sync_contract(
    *,
    warm_state: str | None = None,
    warm_error: str | None = None,
    keeper: dict[str, Any] | None = None,
    soft_search_ready: bool = False,
    last_error: str | None = None,
) -> dict[str, Any]:
    """Expand keeper/warm signals into the public sync status contract."""
    keeper = keeper or {}
    dirty = keeper.get("dirty") if isinstance(keeper.get("dirty"), dict) else {}
    last_result = keeper.get("last_sync") if isinstance(keeper.get("last_sync"), dict) else {}
    status = derive_sync_status(
        dirty=dirty,
        syncing=bool(keeper.get("running"))
        and bool((dirty.get("paths") or {})),
        publish_pending=bool(keeper.get("publish_pending")),
        needs_full=bool(keeper.get("needs_full")),
        catchup_chunked=bool(keeper.get("catchup_chunked")),
        last_result=last_result,
        error=last_error or warm_error,
        dense_pending=bool(last_result.get("dense_pending")),
        resource_deferred=str(last_result.get("strategy") or "") == "deferred",
    )
    if warm_error and status == "ready" and not soft_search_ready:
        status = "error"
    if warm_state == "error":
        status = "error"
    contract = {
        "sync_state": status,
        "sync_status": status,
        "ready": status == "ready" and soft_search_ready,
        "syncing": status == "syncing",
        "overlay_ready": status == "overlay_ready" or bool(keeper.get("overlay_ready")),
        "dense_pending": status == "dense_pending",
        "deferred": status == "deferred",
        "needs_full": status == "needs_full" or bool(keeper.get("needs_full")),
        "error": status == "error",
        "locate_streak_active": bool(keeper.get("locate_streak_active")),
        "publish_pending": bool(keeper.get("publish_pending")),
        "catchup_chunked": bool(keeper.get("catchup_chunked")),
        "warm_state": warm_state,
    }
    contract["agent_ready"] = derive_agent_ready(
        healthy=warm_state not in {None, "error"},
        soft_search_ready=soft_search_ready,
        sync_state=status,
        ready=bool(contract["ready"]),
        syncing=bool(contract["syncing"]),
        overlay_ready=bool(contract["overlay_ready"]),
        publish_pending=bool(contract["publish_pending"]),
    )
    contract["agent_ready_note"] = derive_agent_ready_note(
        agent_ready=contract["agent_ready"],
        sync_state=status,
        syncing=bool(contract["syncing"]),
        overlay_ready=bool(contract["overlay_ready"]),
        publish_pending=bool(contract["publish_pending"]),
        ready=bool(contract["ready"]),
    )
    return contract


def derive_agent_ready_note(
    *,
    agent_ready: str,
    sync_state: str,
    syncing: bool,
    overlay_ready: bool,
    publish_pending: bool,
    ready: bool,
) -> str:
    """One-line hint for agents reading status() without institutional knowledge."""
    if agent_ready == "warming":
        return "Engine or index still warming — map may work; wait before trusting edits on indexed files."
    if agent_ready == "yes":
        return "Locate and index are ready; map/focus reflect current repo state."
    if syncing or overlay_ready or publish_pending:
        return "Background sync active — recent file edits may be stale in map until sync finishes."
    if sync_state in {"needs_full", "error"}:
        return f"sync_state={sync_state} — run scubiee init or check engine logs."
    if not ready:
        return f"sync_state={sync_state} — ready=false while keeper catches up."
    return "agent_ready=stale — locate works; index may lag recent edits."


def derive_agent_ready(
    *,
    healthy: bool,
    soft_search_ready: bool,
    sync_state: str,
    ready: bool,
    syncing: bool,
    overlay_ready: bool,
    publish_pending: bool = False,
    warming: bool = False,
) -> str:
    """Single field agents can trust: yes | warming | stale."""
    if warming or not healthy or not soft_search_ready:
        return "warming"
    if ready and not syncing:
        return "yes"
    if syncing or overlay_ready or publish_pending:
        return "stale"
    if sync_state in {"error", "needs_full", "deferred", "dense_pending"}:
        return "stale"
    return "yes" if soft_search_ready else "warming"

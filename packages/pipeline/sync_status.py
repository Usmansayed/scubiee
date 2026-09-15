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
    locate = derive_locate_state(
        healthy=warm_state not in {None, "error"},
        soft_search_ready=soft_search_ready,
        warm_state=warm_state,
        warm_error=warm_error,
        project_bound=soft_search_ready,
        sync_state=status,
        syncing=bool(contract["syncing"]),
    )
    contract["locate"] = locate
    contract["agent_ready"] = derive_agent_ready(
        healthy=warm_state not in {None, "error"},
        soft_search_ready=soft_search_ready,
        sync_state=status,
        ready=bool(contract["ready"]),
        syncing=bool(contract["syncing"]),
        overlay_ready=bool(contract["overlay_ready"]),
        publish_pending=bool(contract["publish_pending"]),
        warm_state=warm_state,
        warm_error=warm_error,
        project_bound=soft_search_ready,
        locate=locate,
    )
    contract["agent_ready_note"] = derive_agent_ready_note(
        agent_ready=contract["agent_ready"],
        sync_state=status,
        syncing=bool(contract["syncing"]),
        overlay_ready=bool(contract["overlay_ready"]),
        publish_pending=bool(contract["publish_pending"]),
        ready=bool(contract["ready"]),
        locate=locate,
    )
    return contract


def derive_locate_state(
    *,
    healthy: bool,
    soft_search_ready: bool,
    warm_state: str | None = None,
    warm_error: str | None = None,
    project_bound: bool = False,
    index_usable: bool | None = None,
    sync_state: str = "ready",
    syncing: bool = False,
) -> dict[str, Any]:
    """One agent-facing locate contract — source of truth for readiness.

    States: ready | starting | indexing | unbound | error
    """
    warm = str(warm_state or "").strip().lower()
    err = str(warm_error or "").strip()
    repair: list[str] = []
    if not healthy:
        return {
            "state": "starting",
            "reason": "engine_unreachable",
            "repair": ["scubiee engine ensure ."],
            "should_use": True,
            "should_retry": True,
            "retry_after_s": 3,
        }
    if warm == "error" or err:
        repair = ["scubiee setup"] if "provider" in err.lower() or "dml" in err.lower() else [
            "scubiee doctor",
            "scubiee engine ensure .",
        ]
        return {
            "state": "error",
            "reason": err or "warm_state_error",
            "repair": repair,
            "should_use": False,
            "should_retry": False,
            "retry_after_s": 0,
        }
    if warm in {"warming", "indexing"} or index_usable is False:
        return {
            "state": "indexing" if warm == "indexing" or index_usable is False else "starting",
            "reason": warm or "index_not_usable",
            "repair": ["scubiee status", "scubiee engine ensure ."],
            "should_use": True,
            "should_retry": True,
            "retry_after_s": 5,
        }
    if not project_bound or not soft_search_ready:
        return {
            "state": "unbound",
            "reason": "repo_not_bound" if not project_bound else "soft_search_not_ready",
            "repair": ["scubiee engine ensure ."],
            "should_use": True,
            "should_retry": True,
            "retry_after_s": 2,
        }
    if syncing or sync_state in {"syncing", "overlay_ready", "catching_up"}:
        return {
            "state": "ready",
            "reason": "syncing_stale_ok",
            "repair": [],
            "should_use": True,
            "should_retry": False,
            "retry_after_s": 0,
            "stale": True,
        }
    if soft_search_ready and warm in {"", "ready", "idle"}:
        return {
            "state": "ready",
            "reason": "ok",
            "repair": [],
            "should_use": True,
            "should_retry": False,
            "retry_after_s": 0,
        }
    return {
        "state": "starting",
        "reason": f"warm_state={warm or 'unknown'}",
        "repair": ["scubiee engine ensure ."],
        "should_use": True,
        "should_retry": True,
        "retry_after_s": 3,
    }


def derive_agent_ready_note(
    *,
    agent_ready: str,
    sync_state: str,
    syncing: bool,
    overlay_ready: bool,
    publish_pending: bool,
    ready: bool,
    locate: dict[str, Any] | None = None,
    embedder_loaded: bool | None = None,
) -> str:
    """One-line hint for agents reading status() without institutional knowledge."""
    loc = locate or {}
    state = str(loc.get("state") or "")
    if state == "error":
        repair = loc.get("repair") or []
        return f"Locate blocked ({loc.get('reason')}) — repair: {', '.join(repair) or 'scubiee doctor'}"
    if state == "unbound":
        return "Repo not bound into the engine yet — call map/pack (auto-bind) or scubiee engine ensure ."
    if state in {"starting", "indexing"}:
        return f"Engine {state} — retry locate shortly (not a RAM warm-up stall)."
    if embedder_loaded is False and state == "ready":
        return (
            "Soft locate ready (BM25/index); FastEmbed still loading in background — "
            "map/pack lean OK now; dense semantic improves once embedder_loaded=true."
        )
    if agent_ready == "yes" or state == "ready":
        if loc.get("stale") or syncing or overlay_ready or publish_pending:
            return "Locate ready; background sync may lag recent edits."
        if embedder_loaded is False:
            return (
                "Soft locate ready; semantic embedder still loading — proceed with map/pack."
            )
        return "Locate and index are ready; map/pack_context reflect current repo state."
    if agent_ready == "warming":
        if embedder_loaded is False:
            return (
                "Engine still starting (index not soft-ready yet) — wait ~3s and retry once."
            )
        return "Engine or index still starting — map may work; prefer locate.state over this label."
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
    warm_state: str | None = None,
    warm_error: str | None = None,
    project_bound: bool | None = None,
    locate: dict[str, Any] | None = None,
    embedder_loaded: bool | None = None,
) -> str:
    """Legacy agent_ready derived from locate.state: yes | warming | stale.

    Soft BM25/index ready is enough for ``yes`` — map/pack lean work without
    FastEmbed. ``semantic_ready`` / ``embedder_loaded`` remain the signal that
    dense semantic is still loading (do not block locate on ORT/DML cold start).
    """
    loc = locate or derive_locate_state(
        healthy=healthy and not warming,
        soft_search_ready=soft_search_ready,
        warm_state=warm_state,
        warm_error=warm_error,
        project_bound=bool(project_bound) if project_bound is not None else soft_search_ready,
        sync_state=sync_state,
        syncing=syncing or overlay_ready or publish_pending,
    )
    state = str(loc.get("state") or "")
    if state == "error":
        return "warming"  # legacy; prefer locate.state=error
    if state in {"starting", "indexing", "unbound"}:
        return "warming"
    if state == "ready" and loc.get("stale"):
        return "stale"
    if state == "ready":
        return "yes"
    if ready and not syncing:
        return "yes"
    if syncing or overlay_ready or publish_pending:
        return "stale"
    if sync_state in {"error", "needs_full", "deferred", "dense_pending"}:
        return "stale"
    return "yes" if soft_search_ready else "warming"

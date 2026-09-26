"""Single cross-platform runtime owner for Scubiee warm/lifecycle.

Works the same on Windows, macOS, and Linux, and for every MCP host
(Cursor, Claude Code, Codex, Kiro, Copilot, Zed, Continue, …).

One entrypoint: ``RuntimeController.ensure(repo, reason)``.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

Reason = Literal["attach", "serve", "leave"]

_STATE_DOWN = "DOWN"
_STATE_STARTING = "STARTING"
_STATE_READY = "READY"
_STATE_DEGRADED = "DEGRADED"
_STATE_STOPPING = "STOPPING"

_LOCK = threading.RLock()
_INSTANCE: RuntimeController | None = None


def warm_deadline_ms() -> int:
    raw = (os.environ.get("CTX_WARM_DEADLINE_MS") or "30000").strip()
    try:
        return max(1000, int(float(raw)))
    except ValueError:
        return 30_000


def attach_warm_enabled() -> bool:
    """Single attach-warm knob (host-agnostic).

    ``CTX_MCP_ATTACH_WARM`` wins when set. Else deprecated ``CTX_MCP_AUTO_WARM``
    aliases for one release. Default: on.
    """
    if "CTX_MCP_ATTACH_WARM" in os.environ:
        raw = (os.environ.get("CTX_MCP_ATTACH_WARM") or "1").strip().lower()
        return raw not in {"0", "false", "no", "off"}
    # Deprecated alias
    if "CTX_MCP_AUTO_WARM" in os.environ:
        raw = (os.environ.get("CTX_MCP_AUTO_WARM") or "0").strip().lower()
        return raw in {"1", "true", "yes", "on"}
    return True


def is_bridge_process() -> bool:
    return (os.environ.get("CTX_MCP_BRIDGE") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True)
class ReadySnapshot:
    state: str
    engine_ok: bool
    embedder_loaded: bool
    ast_ready: bool
    elapsed_ms: float | None = None
    error: str | None = None
    soft_search_ready: bool = False

    @property
    def warm_ready(self) -> bool:
        # Binder soft-ready is enough for map; dense embed may still be loading.
        return bool(self.engine_ok and (self.soft_search_ready or self.embedder_loaded))

    @property
    def warm_ready_map(self) -> bool:
        return self.warm_ready

    def as_status_fields(self) -> dict[str, Any]:
        return {
            "warm_ready": self.warm_ready,
            "warm_ready_map": self.warm_ready_map,
            "warm_phase": self.state.lower(),
            "warm_elapsed_ms": self.elapsed_ms,
            "warm_deadline_ms": warm_deadline_ms(),
            "embedder_loaded": self.embedder_loaded,
            "soft_search_ready": self.soft_search_ready,
            "ast_hydrated": self.ast_ready,
            "warm_error": self.error,
            "attach_warm": attach_warm_enabled(),
            "runtime_state": self.state,
        }


class RuntimeController:
    """Process-local singleton owning warm start / serve join / leave."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._state = _STATE_DOWN
        self._started_at: float | None = None
        self._ensure_thread: threading.Thread | None = None
        self._attach_kicked = False
        self._last_error: str | None = None
        self._ast_ready = False

    @classmethod
    def get(cls) -> RuntimeController:
        global _INSTANCE
        with _LOCK:
            if _INSTANCE is None:
                _INSTANCE = cls()
            return _INSTANCE

    @classmethod
    def reset_for_tests(cls) -> None:
        global _INSTANCE
        with _LOCK:
            _INSTANCE = None

    def note_ast_ready(self) -> None:
        with self._lock:
            self._ast_ready = True

    def note_ast_cold(self) -> None:
        with self._lock:
            self._ast_ready = False

    def _mark_ready(self) -> None:
        with self._lock:
            self._state = _STATE_READY
            self._last_error = None

    def _elapsed_ms(self) -> float | None:
        if self._started_at is None:
            return None
        return round((time.time() - self._started_at) * 1000.0, 1)

    def _remaining_s(self) -> float:
        if self._started_at is None:
            return warm_deadline_ms() / 1000.0
        return max(0.0, (warm_deadline_ms() / 1000.0) - (time.time() - self._started_at))

    def snapshot(self, *, repo: Path | str | None = None) -> ReadySnapshot:
        health = self._probe_health(repo)
        engine_ok = bool(health.get("ok") and health.get("service"))
        embed = bool(health.get("embedder_loaded")) if "embedder_loaded" in health else False
        soft = bool(health.get("soft_search_ready"))
        with self._lock:
            state = self._state
            err = self._last_error
            ast_ready = self._ast_ready
            elapsed = self._elapsed_ms()
        if repo is not None:
            # Pack and status share this process. A hydrate that filled the
            # cache, or the flag that hydrate sets, means pack can run.
            # Do not clear that flag on a cache-key miss.
            try:
                from pipeline.context_trace import ast_cache_ready
                from pipeline.warm_contract import ast_hydrated as ast_flag

                ast_ready = bool(ast_cache_ready(repo)) or bool(ast_flag()) or ast_ready
            except Exception:  # noqa: BLE001
                ast_ready = bool(ast_ready)
            with self._lock:
                self._ast_ready = ast_ready
        if soft or (engine_ok and embed):
            state = _STATE_READY
            try:
                from pipeline.warm_contract import mark_warm_ready

                mark_warm_ready()
            except Exception:  # noqa: BLE001
                pass
        elif engine_ok and not embed and not soft:
            state = _STATE_DEGRADED if state != _STATE_STARTING else state
        return ReadySnapshot(
            state=state,
            engine_ok=engine_ok or soft,
            embedder_loaded=embed,
            soft_search_ready=soft,
            ast_ready=ast_ready,
            elapsed_ms=elapsed,
            error=err or (None if (engine_ok or soft) else str(health.get("error") or "")),
        )

    def _probe_health(self, repo: Path | str | None) -> dict[str, Any]:
        try:
            from pipeline.client import EngineClient

            return EngineClient(
                workspace_path=str(repo) if repo else None,
                timeout=1.5,
            ).health()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _spawn_engine(self, root: Path) -> dict[str, Any]:
        from pipeline.daemon import ensure_daemon

        return ensure_daemon(
            root,
            force_if_hung=False,
            spawn_owner="direct",
            wait_s=0.0,
            open_wait=False,
        )

    def _kick_embed_prewarm(self, root: Path) -> dict[str, Any]:
        try:
            from pipeline.client import EngineClient

            return EngineClient(workspace_path=str(root), timeout=3.0).post(
                "/v1/embed/prewarm",
                {"path": str(root), "wait": False, "sync": False},
            ) or {"ok": False}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _kick_open_repo(self, root: Path) -> dict[str, Any]:
        """Bind index into the engine so first map is not a cold open."""
        try:
            from pipeline.client import EngineClient

            return EngineClient(workspace_path=str(root), timeout=45.0).open_repo(
                str(root), wait=True
            ) or {"ok": False}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _kick_search_probe(self, root: Path) -> dict[str, Any]:
        """One soft search to prove binder readiness before agent map."""
        try:
            from pipeline.client import EngineClient

            # Short timeout — never park attach behind a 45s hung probe.
            return EngineClient(workspace_path=str(root), timeout=5.0).search(
                "scubiee attach warm probe",
                top_k=3,
                path=str(root),
            ) or {"ok": False}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _hydrate_ast(self, root: Path, *, bake_on_miss: bool) -> dict[str, Any]:
        if is_bridge_process():
            return {"ok": True, "source": "skipped_bridge"}
        try:
            from pipeline.context_trace import hydrate_ast_bundle

            out = hydrate_ast_bundle(root, bake_on_miss=bake_on_miss)
            if out.get("ok"):
                with self._lock:
                    self._ast_ready = True
            return out
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def _attach_worker(self, root: Path) -> None:
        with self._lock:
            self._state = _STATE_STARTING
            self._last_error = None
        try:
            self._spawn_engine(root)
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._last_error = str(exc)
        deadline = time.time() + warm_deadline_ms() / 1000.0
        healthy = False
        poll_fails = 0
        while time.time() < deadline:
            try:
                from pipeline.warm_autoload import in_prewarm, read_phase

                if in_prewarm():
                    if (read_phase() or {}).get("phase") == "dense":
                        healthy = True
                        break
                    time.sleep(2.0)
                    continue
            except Exception:  # noqa: BLE001
                try:
                    from pipeline.engine import prewarm_busy_stamp_active

                    if prewarm_busy_stamp_active():
                        time.sleep(2.0)
                        continue
                except Exception:  # noqa: BLE001
                    pass
            h = self._probe_health(root)
            if h.get("ok") and h.get("service"):
                healthy = True
                break
            poll_fails += 1
            time.sleep(0.5 if poll_fails < 4 else 2.0)
        if not healthy:
            quiet_end = time.time() + 120.0
            while time.time() < quiet_end:
                try:
                    from pipeline.warm_autoload import in_prewarm, read_phase

                    if not in_prewarm():
                        if (read_phase() or {}).get("phase") == "dense":
                            healthy = True
                        break
                except Exception:  # noqa: BLE001
                    break
                time.sleep(2.0)
            if not healthy:
                h = self._probe_health(root)
                if h.get("ok") and h.get("service"):
                    healthy = True
        if not healthy:
            with self._lock:
                self._state = _STATE_DOWN
                self._last_error = "engine_health_timeout"
            return

        # Prefer engine listen-then-bg-open soft binder. Re-open when already soft
        # force_reload'd ~5s and flapped soft_search_ready false (settle sims).
        soft_now = False
        try:
            h2 = self._probe_health(root)
            soft_now = bool(h2.get("soft_search_ready"))
        except Exception:  # noqa: BLE001
            soft_now = False

        opened: dict[str, Any] = {"ok": True, "skipped": "already_soft"} if soft_now else {}
        open_ok = soft_now
        if not soft_now:
            # Open FIRST — never race ORT prewarm against publish (GIL starves /health
            # and left soft_search_ready false for the whole warm budget).
            opened = self._kick_open_repo(root)
            open_ok = bool(
                opened.get("ok")
                or opened.get("status") in {"activated", "ready", "open"}
                or (opened.get("open") or {}).get("ok")
                or (opened.get("open") or {}).get("warm_state") in {"ready", "stale"}
                or opened.get("warm_state") in {"ready", "stale"}
            )
            try:
                h3 = self._probe_health(root)
                soft_now = bool(h3.get("soft_search_ready"))
                open_ok = open_ok or soft_now
            except Exception:  # noqa: BLE001
                pass
        if soft_now or open_ok:
            try:
                from pipeline.mcp_lifecycle import mark_soft_ready

                mark_soft_ready(ttl_s=300.0)
            except Exception:  # noqa: BLE001
                pass

        # Do not kick embed here — open already schedules a deferred prewarm.
        # Racing ORT against the first map GIL-starves /health and join_attach.
        emb: dict[str, Any] = {"ok": True, "deferred": True}

        # BM25/hash probe — do not wait for dense embed.
        probe: dict[str, Any] = {"ok": False, "skipped": True}
        if time.time() < deadline and (open_ok or soft_now):
            probe = self._kick_search_probe(root)

        # Do NOT hydrate AST on attach — pickle load GIL-starves first map/pack in
        # this MCP process for multi-seconds. Lean pack uses search; expand joins AST.
        ast: dict[str, Any] = {"ok": True, "skipped": True, "reason": "defer_until_expand"}

        probe_ok = bool(probe.get("ok") or probe.get("results") or probe.get("hits"))
        if open_ok or soft_now or probe_ok:
            # Preload locate imports in this process so first agent map is not
            # paying multi-second cold import tax after soft_ready.
            try:
                import pipeline.context_agent.tools  # noqa: F401
                import pipeline.locate  # noqa: F401
                from pipeline.context_trace import (  # noqa: F401
                    finalize_suggested_seed,
                    pick_suggested_seed,
                )
            except Exception:  # noqa: BLE001
                pass
            try:
                from pipeline.mcp_lifecycle import mark_soft_ready

                mark_soft_ready(ttl_s=300.0)
            except Exception:  # noqa: BLE001
                pass
            self._mark_ready()
            if not (emb.get("ok") or emb.get("async")):
                with self._lock:
                    self._last_error = str(emb.get("error") or "embed_prewarm_async_failed")
        else:
            with self._lock:
                self._state = _STATE_DEGRADED
                self._last_error = str(
                    opened.get("error") or probe.get("error") or "open_failed"
                )

    def ensure(
        self,
        repo: Path | str,
        reason: Reason,
        *,
        need_ast: bool = False,
        client_id: str | None = None,
    ) -> ReadySnapshot:
        root = Path(repo).resolve()
        if reason == "leave":
            with self._lock:
                self._state = _STATE_STOPPING
                self._attach_kicked = False
            return self.snapshot(repo=root)

        if reason == "attach":
            if not attach_warm_enabled():
                return self.snapshot(repo=root)
            with self._lock:
                if self._attach_kicked:
                    return self.snapshot(repo=root)
                self._attach_kicked = True
                if self._started_at is None:
                    self._started_at = time.time()
                t = self._ensure_thread
                if t is not None and t.is_alive():
                    return self.snapshot(repo=root)
                # Never block attach/stdio on ensure_daemon — that paid 2–7s into
                # first Cursor map when engine open raced duplicate processes.
                t = threading.Thread(
                    target=self._attach_worker,
                    args=(root,),
                    name="scubiee-runtime-attach",
                    daemon=True,
                )
                self._ensure_thread = t
                t.start()
            # Also stamp warm_contract for status compatibility.
            try:
                from pipeline.warm_contract import mark_warm_start

                mark_warm_start(root, now=self._started_at)
            except Exception:  # noqa: BLE001
                pass
            return self.snapshot(repo=root)

        # serve
        snap = self.snapshot(repo=root)
        if snap.warm_ready and (not need_ast or snap.ast_ready):
            return snap
        # Kick attach path if nothing running.
        if attach_warm_enabled():
            with self._lock:
                alive = self._ensure_thread is not None and self._ensure_thread.is_alive()
            if not alive and not snap.engine_ok:
                self.ensure(root, "attach", client_id=client_id)
        remaining = self._remaining_s()
        # Cap serve-join: if soft is not visible quickly, fail soft to warming
        # instead of parking the MCP tool for the full 30s budget.
        join_cap = 3.0 if self._started_at else 5.0
        deadline = time.time() + (
            min(remaining, join_cap) if self._started_at else min(remaining, join_cap)
        )
        while time.time() < deadline:
            if need_ast and not is_bridge_process():
                self._hydrate_ast(root, bake_on_miss=False)
            snap = self.snapshot(repo=root)
            # Soft-ready is enough for first map — do not kick ORT during serve-join.
            if snap.warm_ready and (not need_ast or snap.ast_ready or self._hydrate_ast(root, bake_on_miss=True).get("ok")):
                snap = self.snapshot(repo=root)
                if snap.warm_ready and (not need_ast or snap.ast_ready):
                    return snap
            time.sleep(0.1)
        if need_ast and not is_bridge_process():
            self._hydrate_ast(root, bake_on_miss=True)
        return self.snapshot(repo=root)

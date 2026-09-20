"""Serve-time memory governor — where to spend RAM for best locate latency.

Unlike ``memory_budget`` (index/sync caps), this module governs **idle and serve**
footprint: tier selection, lazy embedder load, demotion after index or semantic idle,
and an RSS breakdown for ``status()``.

**Total Scubiee process-tree budget (engine + bridge + locate + watchdog):**
  serve / live MCP     ≤ **1536 MB** combined (MCP pin; keeps DirectML warm)
  index / init / bulk  ≤ **1000 MB** combined (high-compute OK)

Per-engine soft targets (ORT cannot shrink in-place; demote on disconnect):
  locate_only         ~380 MB — BM25 + FAISS + graph; embedder unloaded
  serve_1repo         ~520 MB — one warm embedder for map/search
  serve_multi_session ~620 MB — same repo, multiple MCP sessions
  serve_2repo         ~800 MB — two active repository engines (hard serve ceiling)
  indexing            ~1000 MB — bulk index / init / bulk sync only
FastEmbed must load only in the engine process — never in mcp_bridge / mcp_locate.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pipeline.memory_budget import process_rss_mb, scubiee_tree_rss_mb

if TYPE_CHECKING:
    from pipeline.repo_runtime import RepoHub

ServeTier = Literal[
    "locate_only",
    "serve_1repo",
    "serve_multi_session",
    "serve_2repo",
    "indexing",
]

LOCATE_ONLY_TARGET_MB = 380
SERVE_1REPO_TARGET_MB = 520
SERVE_MULTI_SESSION_TARGET_MB = 620
SERVE_2REPO_TARGET_MB = 800
INDEXING_TARGET_MB = 1000

# Combined RSS for every Scubiee-related process (engine+bridge+locate+watchdog).
TOTAL_SERVE_BUDGET_MB = 1536
# Soft alert only — full-warm (embedder + AST resident while MCP clients connected).
FULL_WARM_SOFT_CAP_MB = 1536
TOTAL_INDEX_BUDGET_MB = 1000

SESSION_OVERHEAD_MB = 50
REPO_OVERHEAD_MB = 300


def total_rss_budget_mb(*, indexing: bool = False) -> int:
    raw = os.environ.get("CTX_SCUBIEE_TOTAL_RSS_MB")
    if raw is not None and str(raw).strip() != "":
        try:
            return max(256, int(float(raw)))
        except ValueError:
            pass
    return TOTAL_INDEX_BUDGET_MB if indexing else TOTAL_SERVE_BUDGET_MB


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def embed_idle_demote_s() -> float:
    """Seconds after MCP disconnect before unloading the embedder (default 10s).

    While any MCP/IDE client is registered, demote never fires. Unload is
    disconnect-driven (same knob as ``CTX_DISCONNECT_DEBOUNCE_S``).
    """
    raw = os.environ.get("CTX_EMBED_IDLE_DEMOTE_S")
    if raw is not None and str(raw).strip() != "":
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    for key in ("CTX_DISCONNECT_DEBOUNCE_S", "CTX_ENGINE_IDLE_S"):
        raw = os.environ.get(key)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            return max(0.0, float(raw))
        except ValueError:
            continue
    return 10.0


EMBED_IDLE_DEMOTE_S = embed_idle_demote_s()  # import-time default for docs/tests


@dataclass(frozen=True)
class TierConfig:
    tier: ServeTier
    rss_target_mb: int
    load_embedder: bool
    warmup_embedder: bool
    prefer_bm25: bool
    dense_enabled: bool
    hint: str


TIER_CONFIGS: dict[ServeTier, TierConfig] = {
    "locate_only": TierConfig(
        tier="locate_only",
        rss_target_mb=LOCATE_ONLY_TARGET_MB,
        load_embedder=False,
        warmup_embedder=False,
        prefer_bm25=True,
        dense_enabled=True,
        hint="BM25+FAISS for grep/glob; embedder cold until map/search",
    ),
    "serve_1repo": TierConfig(
        tier="serve_1repo",
        rss_target_mb=SERVE_1REPO_TARGET_MB,
        load_embedder=True,
        warmup_embedder=True,
        prefer_bm25=False,
        dense_enabled=True,
        hint="Warm embedder for semantic map/search on one repo",
    ),
    "serve_multi_session": TierConfig(
        tier="serve_multi_session",
        rss_target_mb=SERVE_MULTI_SESSION_TARGET_MB,
        load_embedder=True,
        warmup_embedder=True,
        prefer_bm25=False,
        dense_enabled=True,
        hint="Embedder warm; headroom for multi-session MCP overhead",
    ),
    "serve_2repo": TierConfig(
        tier="serve_2repo",
        rss_target_mb=SERVE_2REPO_TARGET_MB,
        load_embedder=True,
        warmup_embedder=True,
        prefer_bm25=False,
        dense_enabled=True,
        hint="Two repo engines; stay at the 800 MB serve cap",
    ),
    "indexing": TierConfig(
        tier="indexing",
        rss_target_mb=INDEXING_TARGET_MB,
        load_embedder=True,
        warmup_embedder=True,
        prefer_bm25=False,
        dense_enabled=True,
        hint="Bulk index/init/sync budget (1 GB); demote to ≤800 MB after publish",
    ),
}


def resolve_desired_tier(
    *,
    repo_count: int,
    max_sessions: int,
    total_sessions: int,
    indexing: bool,
) -> ServeTier:
    """Pick the serve tier implied by current workload (ignores embed-idle demotion)."""
    if indexing:
        return "indexing"
    if repo_count >= 2:
        return "serve_2repo"
    if max_sessions >= 2 or total_sessions >= 2:
        return "serve_multi_session"
    if repo_count >= 1:
        return "serve_1repo"
    return "locate_only"


@dataclass
class MemoryGovernor:
    """Process-wide serve memory policy."""

    desired_tier: ServeTier = "locate_only"
    active_tier: ServeTier = "locate_only"
    indexing: bool = False
    repo_count: int = 0
    total_sessions: int = 0
    max_sessions: int = 0
    chunk_count: int = 0
    engine_count: int = 0
    embedder_loaded: bool = False
    last_semantic_at: float | None = None
    last_refresh_at: float = field(default_factory=time.time)
    demotions: int = 0
    promotions: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def set_indexing(self, active: bool) -> None:
        with self._lock:
            self.indexing = active
            if active:
                self.desired_tier = "indexing"
                self._apply_locked("indexing")
            else:
                self._recompute_desired_locked()
                self._apply_active_locked()

    def note_semantic_activity(self) -> None:
        with self._lock:
            self.last_semantic_at = time.time()
            if self.active_tier == "locate_only" and not self.indexing:
                self.promotions += 1
                self._apply_locked(self.desired_tier)

    def note_embedder_loaded(self) -> None:
        with self._lock:
            self.embedder_loaded = True

    def note_embedder_unloaded(self) -> None:
        with self._lock:
            self.embedder_loaded = False

    def force_demote_disconnect(self) -> dict[str, Any]:
        """Immediate unload used by ``enter_standby`` after disconnect debounce fires."""
        with self._lock:
            self.demotions += 1
            self._demote_embedder_locked()
            self._apply_locked("locate_only")
            return {
                "ok": True,
                "action": "demote_disconnect",
                "tier": self.active_tier,
                "embedder_loaded": self.embedder_loaded,
            }

    def refresh_from_hub(self, hub: "RepoHub") -> ServeTier:
        with self._lock:
            runtimes = []
            try:
                for item in hub.list_status():
                    runtime = hub.get(str(item.get("project_id")))
                    if runtime is not None:
                        runtimes.append(runtime)
            except Exception:  # noqa: BLE001
                runtimes = []

            self.repo_count = len(runtimes)
            self.total_sessions = sum(len(rt.sessions) for rt in runtimes)
            self.max_sessions = max((len(rt.sessions) for rt in runtimes), default=0)
            self.engine_count = sum(1 for rt in runtimes if rt.engine is not None)
            chunks = 0
            for rt in runtimes:
                eng = rt.engine
                if eng is not None and hasattr(eng, "texts"):
                    chunks = max(chunks, len(eng.texts))
            self.chunk_count = chunks
            indexing = self.indexing or any(rt.indexing for rt in runtimes)
            self.indexing = indexing
            self.desired_tier = resolve_desired_tier(
                repo_count=self.repo_count,
                max_sessions=self.max_sessions,
                total_sessions=self.total_sessions,
                indexing=indexing,
            )
            self.last_refresh_at = time.time()
            self._apply_active_locked()
            return self.active_tier

    def ensure_semantic_tier(self) -> ServeTier:
        """Promote to semantic tier before map/search if embedder was demoted."""
        with self._lock:
            self.last_semantic_at = time.time()
            if self.indexing:
                tier = "indexing"
            else:
                tier = self.desired_tier
            if self.active_tier != tier:
                self.promotions += 1
            self._apply_locked(tier)
            return self.active_tier

    def _last_activity_at_locked(self, hub: "RepoHub | None" = None) -> float | None:
        """Newest serve signal: semantic query or MCP/HTTP front-end use.

        When no MCP clients are registered, ignore passive hub touches from
        status polls and use the newer of ``last_client_left_at`` and the last
        semantic query. The former keeps the embedder warm through the
        disconnect grace window (IDE close → reopen reconnect); the latter keeps
        CLI-driven work warm once that window has already elapsed.
        """
        try:
            from pipeline.lifecycle_runtime import active_client_count, load_policy

            if active_client_count() == 0:
                left = load_policy().get("last_client_left_at")
                idle_candidates: list[float] = []
                if left is not None:
                    try:
                        idle_candidates.append(float(left))
                    except (TypeError, ValueError):
                        pass
                if self.last_semantic_at is not None:
                    idle_candidates.append(float(self.last_semantic_at))
                if idle_candidates:
                    return max(idle_candidates)
                return None
        except Exception:  # noqa: BLE001
            pass

        candidates: list[float] = []
        if self.last_semantic_at is not None:
            candidates.append(float(self.last_semantic_at))
        if hub is not None:
            try:
                for item in hub.list_status():
                    runtime = hub.get(str(item.get("project_id")))
                    if runtime is not None and runtime.last_activity_at:
                        candidates.append(float(runtime.last_activity_at))
            except Exception:  # noqa: BLE001
                pass
        if not candidates:
            return None
        return max(candidates)

    def maybe_demote_idle(
        self,
        hub: "RepoHub | None" = None,
        *,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        """Unload embedder after MCP disconnect debounce — keep warm while tools open.

        Policy:
        - Any registered MCP/IDE client → hold forever (fast map/pack/sync).
        - Zero clients → demote ``CTX_EMBED_IDLE_DEMOTE_S`` (default 10s) after
          ``last_client_left_at`` (engine process stays until the 120s disconnect).
        """
        current = time.time() if now is None else now
        with self._lock:
            if self.indexing:
                return None
            if self.active_tier == "locate_only" and not self.embedder_loaded and self.engine_count == 0:
                return None

            try:
                from pipeline.lifecycle_runtime import active_client_count, load_policy

                n_clients = int(active_client_count())
            except Exception:  # noqa: BLE001
                n_clients = 0
            if n_clients > 0:
                return {
                    "ok": True,
                    "action": "hold_mcp_clients",
                    "clients": n_clients,
                    "reason": "mcp_connected_keep_model",
                }

            # Disconnect-driven only: require leave stamp (IDE/tool closed).
            try:
                left = load_policy().get("last_client_left_at")
            except Exception:  # noqa: BLE001
                left = None
            if left is None:
                return None
            try:
                left_at = float(left)
            except (TypeError, ValueError):
                return None
            try:
                from pipeline.lifecycle_runtime import load_transition

                last_start = load_transition().get("last_start_at")
                if last_start is not None and float(last_start) > left_at:
                    return None
            except (TypeError, ValueError):
                pass
            idle_s = current - left_at
            demote_after = embed_idle_demote_s()
            if idle_s < demote_after:
                return None
            self.demotions += 1
            self._demote_embedder_locked()
            self._apply_locked("locate_only")
            return {
                "ok": True,
                "action": "demote_serve",
                "idle_s": round(idle_s, 1),
                "demote_after_s": demote_after,
                "tier": self.active_tier,
                "engines_dropped": True,
                "reason": "mcp_disconnected_grace",
            }

    def demote_after_index(self) -> ServeTier:
        """Restore serve tier after bulk index / publish.

        MCP clients stay warm: ``maybe_demote_idle`` already holds the model
        while tools are connected. Publish/index must not dump ORT underneath
        a live MCP (that made the first map pay a cold ~20s reload).
        """
        with self._lock:
            self.indexing = False
            self._recompute_desired_locked()
            n_clients = 0
            try:
                from pipeline.lifecycle_runtime import active_client_count

                n_clients = int(active_client_count())
            except Exception:  # noqa: BLE001
                n_clients = 0
            # Live MCP/IDE → keep FastEmbed. Disconnect idle path unloads later.
            if n_clients > 0:
                self._apply_locked(self.desired_tier)
                return self.active_tier
            # After index, stay at desired serve tier but skip re-warm if recently semantic
            if (
                self.last_semantic_at is not None
                and (time.time() - self.last_semantic_at) < embed_idle_demote_s()
            ):
                self._apply_locked(self.desired_tier)
            else:
                self._demote_embedder_locked()
                self._apply_locked("locate_only")
            return self.active_tier

    def apply_tier(self, tier: ServeTier) -> None:
        with self._lock:
            self._apply_locked(tier)

    def config(self, tier: ServeTier | None = None) -> TierConfig:
        return TIER_CONFIGS[tier or self.active_tier]

    def status(self) -> dict[str, Any]:
        with self._lock:
            cfg = self.config()
            breakdown = self._breakdown_locked()
            tree = scubiee_tree_rss_mb()
            tree_total = None
            if isinstance(tree, dict):
                raw = tree.get("total_rss_mb")
                try:
                    tree_total = float(raw) if raw is not None else None
                except (TypeError, ValueError):
                    tree_total = None
            soft_budget = float(total_rss_budget_mb(indexing=self.indexing))
            unattributed = float(breakdown.get("unattributed") or 0.0)
            return {
                "desired_tier": self.desired_tier,
                "active_tier": self.active_tier,
                "indexing": self.indexing,
                "repo_count": self.repo_count,
                "total_sessions": self.total_sessions,
                "max_sessions": self.max_sessions,
                "engine_count": self.engine_count,
                "chunk_count": self.chunk_count,
                "embedder_loaded": self.embedder_loaded,
                "rss_target_mb": cfg.rss_target_mb,
                "rss_cap_mb": int(os.environ.get("CTX_CE_RSS_CAP_MB") or cfg.rss_target_mb),
                "total_budget_mb": int(soft_budget),
                "full_warm_soft_cap_mb": FULL_WARM_SOFT_CAP_MB,
                "full_warm_policy": "keep_while_clients",
                "tree_rss": tree,
                "tree_total_mb": tree_total,
                "unattributed_mb": unattributed,
                "over_soft_budget": bool(
                    tree_total is not None and tree_total > soft_budget
                ),
                "over_full_warm_soft_cap": bool(
                    tree_total is not None and tree_total > float(FULL_WARM_SOFT_CAP_MB)
                ),
                # Alerts only — never auto-demote while MCP clients hold availability.
                "availability_hold": True,
                "allocation_hint": cfg.hint,
                "prefer_bm25": cfg.prefer_bm25,
                "dense_enabled": cfg.dense_enabled,
                "last_semantic_at": self.last_semantic_at,
                "embed_idle_demote_s": embed_idle_demote_s(),
                "demotions": self.demotions,
                "promotions": self.promotions,
                "breakdown_mb": breakdown,
                "process_rss_mb": process_rss_mb(),
            }

    def _recompute_desired_locked(self) -> None:
        self.desired_tier = resolve_desired_tier(
            repo_count=self.repo_count,
            max_sessions=self.max_sessions,
            total_sessions=self.total_sessions,
            indexing=False,
        )

    def _apply_active_locked(self) -> None:
        if self.indexing:
            self._apply_locked("indexing")
            return
        # Fresh admission: start lean unless semantic happened recently
        if (
            self.last_semantic_at is not None
            and (time.time() - self.last_semantic_at) < embed_idle_demote_s()
        ):
            self._apply_locked(self.desired_tier)
        elif self.active_tier == "locate_only":
            self._apply_locked("locate_only")
        else:
            self._apply_locked(self.desired_tier)

    def _apply_locked(self, tier: ServeTier) -> None:
        cfg = TIER_CONFIGS[tier]
        self.active_tier = tier
        os.environ["CTX_CE_SERVE_TIER"] = tier
        # MCP/tree pin (CTX_SCUBIEE_TOTAL_RSS_MB) is the real budget. Do not
        # smash 1536 down to 380/520/800 — that unloaded DML while Cursor was open.
        rss = int(cfg.rss_target_mb)
        raw = (os.environ.get("CTX_SCUBIEE_TOTAL_RSS_MB") or "").strip()
        if raw:
            try:
                rss = max(rss, int(float(raw)))
            except ValueError:
                pass
        os.environ["CTX_CE_RSS_CAP_MB"] = str(rss)
        os.environ["CTX_CE_PREFER_BM25"] = "1" if cfg.prefer_bm25 else "0"
        if tier == "locate_only":
            os.environ.setdefault("CTX_CE_LAZY_EMBEDDER", "1")
        else:
            os.environ["CTX_CE_LAZY_EMBEDDER"] = "0"

    def _demote_embedder_locked(self) -> None:
        """Unload FastEmbed/ORT weights only.

        Must **not** ``clear_engines()`` or null ``ce.engine`` — locate_only still
        needs BM25/FAISS/graph bound for soft_search_ready. Dropping the binder
        right after publish left ``chunks=0`` / map timeouts on cold attach.
        Full engine teardown belongs to disconnect ``enter_standby``, not demote.
        """
        try:
            from pipeline.engine import release_embedders

            release_embedders()
        except Exception:  # noqa: BLE001
            pass
        self.embedder_loaded = False

    def _breakdown_locked(self) -> dict[str, float]:
        """Heuristic component breakdown (estimated, not measured per-allocation)."""
        chunks = max(0, self.chunk_count)
        embed_mb = 280.0 if self.embedder_loaded else 0.0
        bm25_mb = min(180.0, 40.0 + chunks * 0.0015)
        faiss_mb = min(160.0, 30.0 + chunks * 0.0012)
        graph_mb = min(60.0, 25.0 + chunks * 0.0003)
        capability_mb = min(40.0, 10.0 + chunks * 0.0001)
        session_mb = max(0, self.total_sessions - 1) * (SESSION_OVERHEAD_MB / 2)
        repo_mb = max(0, self.repo_count - 1) * (REPO_OVERHEAD_MB / 2)
        runtime_mb = 70.0 + self.engine_count * 25.0
        estimated = embed_mb + bm25_mb + faiss_mb + graph_mb + capability_mb + session_mb + repo_mb + runtime_mb
        measured = process_rss_mb()
        return {
            "embedder": round(embed_mb, 1),
            "bm25_chunks": round(bm25_mb, 1),
            "faiss_dense": round(faiss_mb, 1),
            "graph": round(graph_mb, 1),
            "capability": round(capability_mb, 1),
            "sessions": round(session_mb, 1),
            "extra_repos": round(repo_mb, 1),
            "runtime": round(runtime_mb, 1),
            "estimated_total": round(estimated, 1),
            "unattributed": round(max(0.0, (measured or 0) - estimated), 1)
            if measured is not None
            else 0.0,
        }


_GOV: MemoryGovernor | None = None
_GOV_LOCK = threading.Lock()


def get_governor() -> MemoryGovernor:
    global _GOV
    with _GOV_LOCK:
        if _GOV is None:
            _GOV = MemoryGovernor()
        return _GOV


def reset_governor_for_tests() -> None:
    global _GOV
    with _GOV_LOCK:
        _GOV = None


def should_lazy_embedder() -> bool:
    raw = os.environ.get("CTX_CE_LAZY_EMBEDDER", "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    tier = os.environ.get("CTX_CE_SERVE_TIER", "locate_only")
    return tier == "locate_only"


def current_serve_tier() -> ServeTier:
    tier = os.environ.get("CTX_CE_SERVE_TIER", "locate_only")
    if tier in TIER_CONFIGS:
        return tier  # type: ignore[return-value]
    return "locate_only"

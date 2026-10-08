"""Keeper sync loop — Cursor/Claude Context session lifecycle.

CE_LIVE_PROBE_20260818_mcp_verify

While MCP / ``scubiee serve`` is open: periodic root-hash probe → incremental sync
only when dirty. On cwd switch or process exit: one final check, then stop.
"""

from __future__ import annotations

import atexit
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from pipeline.dirty_journal import JournalingLedger
from pipeline.dirty_ledger import DirtyLedger
from pipeline.project_id import context_engine_home, peek_project
from pipeline.sync_status import derive_sync_status

DEFAULT_INTERVAL_MS = int(os.environ.get("CTX_SYNC_INTERVAL_MS", str(5 * 60 * 1000)))
DEFAULT_INITIAL_DELAY_MS = int(os.environ.get("CTX_SYNC_INITIAL_DELAY_MS", "5000"))
# Mild speedup vs old 1500/2500 — still waits out typical editor save bursts.
DEFAULT_DEBOUNCE_MS = int(os.environ.get("CTX_DEBOUNCE_MS", "1000"))
DEFAULT_REWRITE_DEBOUNCE_MS = int(os.environ.get("CTX_REWRITE_DEBOUNCE_MS", "2000"))
DEFAULT_LOCATE_STREAK_MS = int(os.environ.get("CTX_LOCATE_STREAK_MS", "60000"))
# How long a hot save's deferred graph merge waits before it becomes due. The
# merge rebuilds the whole graph (~8s on a 16k-node repo) and the keeper runs one
# batch at a time, so a catch-up that fires too eagerly becomes the thing the
# *next* save waits behind. Waiting for a quiet repo keeps saves on their budget;
# any unrelated non-hot sync carries the debt sooner anyway.
DEFAULT_GRAPH_CATCHUP_DELAY_S = float(os.environ.get("CTX_GRAPH_CATCHUP_DELAY_S", "30.0"))
# Minimum quiet period since the last save before a due catch-up may start. The
# keeper runs one batch at a time; a catch-up that starts while an agent is still
# saving blocks the next save for its whole duration.
DEFAULT_GRAPH_CATCHUP_QUIET_S = float(os.environ.get("CTX_GRAPH_CATCHUP_QUIET_S", "20.0"))
DEFAULT_LIVE_MAX_FILES = int(os.environ.get("CTX_LIVE_MAX_FILES", "200"))
DEFAULT_LIVE_MAX_CHUNKS = int(os.environ.get("CTX_LIVE_MAX_CHUNKS", "300"))
DEFAULT_AUTO_FULL_INDEX_CHUNKS = int(os.environ.get("CTX_AUTO_FULL_INDEX_CHUNKS", "10000"))
DEFAULT_BULK_REINDEX_THRESHOLD = int(os.environ.get("CTX_BULK_REINDEX_THRESHOLD", "300"))
DEFAULT_CHANGE_POLL_MS = int(os.environ.get("CTX_CHANGE_POLL_MS", "1000"))
DEFAULT_WAKE_GAP_MS = int(os.environ.get("CTX_WAKE_GAP_MS", "30000"))
TRIGGER_NAME = ".sync-trigger"

# Process-wide registry for atexit final_check
_ACTIVE_LOOPS: list["BackgroundSyncLoop"] = []
_ATEXIT_REGISTERED = False


def enable_session_keeper_defaults() -> None:
    """MCP / serve entrypoints: turn keeper + auto-index on unless user set env."""
    os.environ.setdefault("CTX_BACKGROUND_SYNC", "1")
    os.environ.setdefault("CTX_ALLOW_BG_FULL", "0")
    os.environ.setdefault("CTX_AUTO_INDEX", "1")
    os.environ.setdefault("CTX_SYNC_INTERVAL_MS", str(5 * 60 * 1000))
    os.environ.setdefault("CTX_CHANGE_POLL_MS", "1000")


def auto_index_enabled() -> bool:
    return os.environ.get("CTX_AUTO_INDEX", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _register_atexit() -> None:
    global _ATEXIT_REGISTERED
    if _ATEXIT_REGISTERED:
        return
    _ATEXIT_REGISTERED = True

    def _on_exit() -> None:
        for loop in list(_ACTIVE_LOOPS):
            try:
                loop.final_check(reason="process_exit")
            except Exception as exc:  # noqa: BLE001
                print(f"[keeper] final_check on exit failed: {exc}", file=sys.stderr, flush=True)
            try:
                loop.stop()
            except Exception:  # noqa: BLE001
                pass

    atexit.register(_on_exit)


def _vdb_fingerprint(vdb) -> tuple | None:
    """(size, mtime_ns) of every collection file — changes when anyone rewrites them."""
    try:
        root = vdb.collections_dir
        stamp = []
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                st = path.stat()
                stamp.append((path.relative_to(root).as_posix(), st.st_size, st.st_mtime_ns))
        return tuple(stamp)
    except Exception:  # noqa: BLE001
        return None


_FILE_KEY = b'"file": "'


def count_chunks_per_file(chunks_path: Path) -> dict[str, int]:
    """Chunks per file in chunks.jsonl without decoding each row.

    Rows are ``json.dumps(asdict(ChunkRecord))``: ``"file"`` is the second key,
    ahead of any text, and a quote inside a JSON string is always escaped, so
    the first ``"file": "`` on a line is the key. Rows that do not match fall
    back to ``json.loads``.
    """
    counts: dict[str, int] = {}
    try:
        data = chunks_path.read_bytes()
    except OSError:
        return counts
    for line in data.splitlines():
        if not line.strip():
            continue
        rel: str | None = None
        i = line.find(_FILE_KEY)
        if i >= 0:
            j = i + len(_FILE_KEY)
            k = j
            while True:
                k = line.find(b'"', k)
                if k < 0:
                    break
                # Count the backslashes in front: an odd number escapes it.
                n = 0
                while line[k - 1 - n] == 0x5C:
                    n += 1
                if n % 2 == 0:
                    break
                k += 1
            if k > 0:
                try:
                    rel = json.loads(b'"' + line[j:k] + b'"')
                except ValueError:
                    rel = None
        if rel is None:
            try:
                rel = str(json.loads(line).get("file") or "")
            except ValueError:
                continue
        rel = rel.replace("\\", "/")
        counts[rel] = counts.get(rel, 0) + 1
    return counts


class BackgroundSyncLoop:
    """Periodic root-probe + incremental_sync; final_check on stop/cwd/exit."""

    def __init__(
        self,
        repo: Path,
        *,
        interval_ms: int = DEFAULT_INTERVAL_MS,
        on_refresh=None,
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        rewrite_debounce_ms: int = DEFAULT_REWRITE_DEBOUNCE_MS,
        hot_debounce_ms: int | None = None,
        locate_streak_ms: int = DEFAULT_LOCATE_STREAK_MS,
        live_max_files: int = DEFAULT_LIVE_MAX_FILES,
        live_max_chunks: int = DEFAULT_LIVE_MAX_CHUNKS,
        change_poll_ms: int = DEFAULT_CHANGE_POLL_MS,
        wake_gap_ms: int = DEFAULT_WAKE_GAP_MS,
    ):
        self.repo = repo.resolve()
        from pipeline.repo_lifecycle import _project

        pid, _entry = _project(self.repo)
        if not pid:
            raise RuntimeError(
                f"keeper requires an enrolled repo (run `scubiee init .`): {self.repo}"
            )
        self.project_id = pid
        self.interval_ms = max(1000, interval_ms)
        self.on_refresh = on_refresh
        self.locate_streak_ms = max(0, locate_streak_ms)
        self.live_max_files = max(1, live_max_files)
        self.live_max_chunks = max(1, live_max_chunks)
        self.auto_full_index_chunks = max(1, DEFAULT_AUTO_FULL_INDEX_CHUNKS)
        self.bulk_reindex_threshold = max(1, DEFAULT_BULK_REINDEX_THRESHOLD)
        self.change_poll_ms = max(250, change_poll_ms)
        self.wake_gap_ms = max(1000, wake_gap_ms)
        self.graph_catchup_delay_s = DEFAULT_GRAPH_CATCHUP_DELAY_S
        self.dirty_ledger = JournalingLedger(
            self.project_id,
            DirtyLedger(
                debounce_ms=debounce_ms,
                rewrite_debounce_ms=rewrite_debounce_ms,
                hot_debounce_ms=hot_debounce_ms,
            ),
        )
        self._stop = threading.Event()
        self._poll_now = False
        self._last_newcomer_scan = 0.0
        self._last_ast_revalidate = 0.0
        self._ast_revalidate_thread: threading.Thread | None = None
        self._thread: threading.Thread | None = None
        self._syncing = False
        self._lock = threading.Lock()
        self._last_locate_at: float | None = None
        self._pending_publish: dict | None = None
        self._pending_paths: set[str] = set()
        # (payload, HotDelta) for the publish that is about to happen. Kept off
        # the payload itself because status() serializes it to JSON. The payload
        # object is held (not its id) so a recycled address cannot alias it.
        self._hot_delta: tuple[dict, Any] | None = None
        self._on_refresh_delta_arity: bool | None = None
        # Deferred collection save from the last hot sync; run after its publish.
        self._vector_flush: Any | None = None
        # When the last save was marked. Graph catch-ups wait for a quiet window
        # after it so their ~8s whole-graph merge never lands mid-burst.
        self._last_hot_mark_at: float | None = None
        self.graph_catchup_quiet_s = DEFAULT_GRAPH_CATCHUP_QUIET_S
        # Issue 6: one in-flight child-process graph merge (graph_merge_worker).
        # The keeper keeps serving saves while it runs and only commits it.
        self._graph_job: Any | None = None
        self._graph_job_failures = 0
        self.graph_job_timeout_s = float(os.environ.get("CTX_GRAPH_CATCHUP_TIMEOUT_S", "80"))
        self._newcomer_thread: threading.Thread | None = None
        # (VectorDatabase, on-disk fingerprint) kept across hot syncs; see _hot_vdb.
        self._hot_vdb_cache: tuple[Any, Any] | None = None
        self._hot_vdb_pending: Any | None = None
        self.last_result: dict | None = None
        self.last_probe: dict | None = None
        self.needs_full = False
        self.catchup_chunked = False
        self.live_batches = 0
        self.live_invalidations = 0
        self.running = False
        self._last_clock_at: float | None = None
        self._watcher_restart_count = 0
        self._watcher_last_reconcile: float | None = None
        self._watcher_last_wake_reconcile: float | None = None
        self._watcher_last_error: str | None = None
        # Adaptive change-poll backoff: track probe durations to detect slow I/O
        # (antivirus interference, network drives, etc.) and reduce poll frequency.
        self._probe_durations: list[float] = []  # last N probe durations in seconds
        self._original_change_poll_ms = self.change_poll_ms
        self._backoff_active = False
        from pipeline.root_probe import DirWatch

        self._dir_watch = DirWatch()

    def status(self) -> dict:
        dirty = self.dirty_ledger.snapshot()
        states = [entry["state"] for entry in dirty["paths"].values()]
        sync_status = derive_sync_status(
            dirty=dirty,
            syncing=self._syncing,
            publish_pending=self._pending_publish is not None,
            needs_full=self.needs_full,
            catchup_chunked=self.catchup_chunked,
            last_result=self.last_result,
        )
        return {
            "running": bool(self.running and self._thread and self._thread.is_alive()),
            "repo": str(self.repo),
            "project_id": self.project_id,
            "interval_ms": self.interval_ms,
            "last_probe": self.last_probe,
            "last_sync": self.last_result,
            "dirty": dirty,
            "overlay_ready": "overlay_ready" in states,
            "publish_pending": self._pending_publish is not None,
            "locate_streak_active": self._locate_streak_active(),
            "live_max_files": self.live_max_files,
            "live_max_chunks": self.live_max_chunks,
            "auto_full_index_chunks": self.auto_full_index_chunks,
            "bulk_reindex_threshold": self.bulk_reindex_threshold,
            "needs_full": self.needs_full,
            "catchup_chunked": self.catchup_chunked,
            "live_batches": self.live_batches,
            "session_invalidations": self.live_invalidations,
            "sync_status": sync_status,
            "journal_restore": self.dirty_ledger.restore_result,
            "watcher": {
                "restart_count": self._watcher_restart_count,
                "last_reconcile": self._watcher_last_reconcile,
                "last_wake_reconcile": self._watcher_last_wake_reconcile,
                "last_error": self._watcher_last_error,
            },
        }

    def _estimate_dirty_chunks(self, paths: list[str]) -> tuple[int, dict[str, int]]:
        """Estimate changed chunks without parsing or mutating the index.

        Existing files use their indexed chunk count. New files use a conservative
        line-based estimate because their chunk count does not exist yet. The
        estimate is only a gate for the 10000-chunk safety limit; incremental_sync
        applies the exact post-parse limit before writing graph/vector artifacts.
        """
        counts: dict[str, int] = {}
        try:
            ref = peek_project(self.repo)
            if ref is None:
                return 0, {}
            # Byte-level count, cached on the file stamp. Parsing every chunk
            # (text + enriched) of chunks.jsonl on every drain sat in front of
            # each hot save (issue 4); only the per-file counts are needed.
            chunks_path = ref.store_dir / "chunks.jsonl"
            from pipeline.fast_stat import fast_stat

            st = fast_stat(chunks_path)
            stamp = (st.st_mtime_ns, st.st_size) if st is not None else None
            cached = getattr(self, "_chunk_count_cache", None)
            if stamp is not None and cached is not None and cached[0] == stamp:
                counts = cached[1]
            elif stamp is not None:
                counts = count_chunks_per_file(chunks_path)
                self._chunk_count_cache = (stamp, counts)
        except Exception:
            counts = {}

        estimates: dict[str, int] = {}
        for raw_path in paths:
            path = str(raw_path).replace("\\", "/")
            estimate = counts.get(path, 0)
            if estimate <= 0:
                candidate = self.repo / path
                if candidate.is_file():
                    try:
                        lines = sum(1 for _ in candidate.open("r", encoding="utf-8", errors="ignore"))
                    except OSError:
                        lines = 0
                    estimate = max(1, min(2000, (lines + 24) // 25))
                else:
                    estimate = 1
            estimates[path] = estimate
        return sum(estimates.values()), estimates

    def _indexed_subset(self, paths: list[str]) -> set[str]:
        """Paths that own chunks in the index. Unreadable store → all of them."""
        wanted = {str(p).replace("\\", "/") for p in paths}
        try:
            from pipeline.store import PipelineStore

            ref = peek_project(self.repo)
            if ref is None:
                return wanted
            store = PipelineStore(
                self.repo,
                base_dir=ref.store_dir,
                project_id=ref.project_id,
                resolve=False,
            )
            if not store.chunk_merkle_path.is_file():
                return wanted
            merkle = store.load_chunk_merkle()
            found = {p for p in wanted if merkle.get(p)}
            rest = wanted - found
            if rest:
                # The chunk merkle is not the only record. A path the file
                # merkle still lists is re-reported as removed by every 1s poll
                # until a sync patches it, and a chunk-only "ghost" keeps
                # showing up in search: both still need their sync. Completing
                # them unsynced made the poll mark a hot save every second,
                # which held all graph catch-ups forever (issue 6).
                from pipeline.merkle import canonical_relpath

                file_merkle = store.load_merkle()
                found |= {p for p in rest if canonical_relpath(p) in file_merkle or p in file_merkle}
                rest = wanted - found
            if rest and store.chunks_path.is_file():
                needles = {p: f'"file": "{p}"' for p in rest}
                with store.chunks_path.open("r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        for p, needle in list(needles.items()):
                            if needle in line:
                                found.add(p)
                                needles.pop(p, None)
                        if not needles:
                            break
        except Exception:  # noqa: BLE001
            return wanted
        return found

    def mark_dirty(
        self,
        paths: Iterable[str],
        *,
        reason: str = "write",
        now: float | None = None,
    ) -> None:
        # An edit ends the locate streak: process+publish freshness beats mid-thought
        # stability once the agent has changed disk.
        from pipeline.dirty_ledger import HOT_SYNC_REASONS
        from pipeline.ignore import filter_dirty_paths

        kept, _dropped = filter_dirty_paths(self.repo, paths)
        if not kept:
            return
        if str(reason) in HOT_SYNC_REASONS or str(reason) == "disk_poll":
            self._last_locate_at = None
        if str(reason) in HOT_SYNC_REASONS:
            self._last_hot_mark_at = time.monotonic() if now is None else now
            self._last_hot_mark_info = (str(reason), list(kept)[:3])
        self.dirty_ledger.mark(kept, reason=reason, now=now)

    def note_locate(self, *, now: float | None = None) -> None:
        self._last_locate_at = time.monotonic() if now is None else now

    def poll_repo_changes(self, *, now: float | None = None) -> list[str]:
        """Cheap disk poll → enqueue changed paths for the debounced live path.

        This is the agent-write producer: Kiro/Cursor edits do not need to call
        /v1/dirty explicitly. The 5-minute keeper tick remains the backup.

        Includes adaptive backoff: if root_probe consistently takes > 2s
        (3 consecutive probes), doubles change_poll_ms up to 10s max.
        Restores original interval when probes drop back under 500ms.
        """
        from pipeline.root_probe import root_probe

        current_time = time.monotonic() if now is None else now
        # Indexed files plus folders whose mtime moved; the full newcomer walk
        # was the 7–9s stall. Skipping the poll while a client is registered
        # hid every save.
        t_probe_start = time.perf_counter()
        try:
            probe = root_probe(
                self.repo,
                discover_newcomers=False,
                dir_watch=self._dir_watch,
                store=self._poll_store(),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] change poll failed: {exc}", file=sys.stderr, flush=True)
            return []
        probe_duration = time.perf_counter() - t_probe_start

        # --- Adaptive backoff: track probe durations for slow I/O detection ---
        self._probe_durations.append(probe_duration)
        # Keep only the last 5 durations for averaging
        if len(self._probe_durations) > 5:
            self._probe_durations = self._probe_durations[-5:]
        self._adapt_poll_interval()

        if probe.clean:
            return []
        paths = sorted(
            {
                str(p).replace("\\", "/")
                for p in [*probe.added, *probe.modified, *probe.removed]
                if str(p).strip()
            }
        )
        if not paths:
            return []
        # Do not re-mark already queued/processing paths — that would slide the
        # rewrite debounce forever while the file remains dirty on disk.
        snap = self.dirty_ledger.snapshot().get("paths") or {}

        def _fresh(path: str) -> bool:
            entry = snap.get(path) or {}
            state = str(entry.get("state") or "")
            if state not in {"queued", "due", "processing", "overlay_ready"}:
                return True
            # A graph catch-up waits 30s+ for quiet; a second save to the same
            # file must not wait behind it. The hot sync already recorded the
            # file, so the poll only reports it again after a new edit.
            return state == "queued" and str(entry.get("reason") or "") == "graph_catchup"

        fresh = [path for path in paths if _fresh(path)]
        if not fresh:
            self.last_probe = {**probe.to_dict(), "reason": "change_poll"}
            return []
        try:
            hot_max = int(os.environ.get("CTX_POLL_HOT_MAX") or "5")
        except ValueError:
            hot_max = 5
        # A few changed files is a save; a checkout or bulk rewrite stays on the
        # background lane.
        reason = "disk_save" if len(fresh) <= hot_max else "disk_poll"
        self.mark_dirty(fresh, reason=reason, now=current_time)
        self.last_probe = {**probe.to_dict(), "reason": "change_poll"}
        return fresh

    def _poll_store(self):
        """One PipelineStore for the once-a-second change poll (None = let it build one).

        Building a store resolves the project (id file, registry, ~19 path
        resolves): 1.8s of a 3.1s poll while a search held the GIL (issue 4).
        Rebuilt only when the store directory disappears (wipe / re-enroll).
        """
        from pipeline.fast_stat import fast_stat

        cached = getattr(self, "_poll_store_cache", None)
        if cached is not None:
            st = fast_stat(cached.base)
            if st is not None and st.is_dir:
                return cached
        try:
            from pipeline.store import PipelineStore

            ref = peek_project(self.repo)
            if ref is None:
                return None
            store = PipelineStore(
                self.repo, base_dir=ref.store_dir, project_id=ref.project_id, resolve=False
            )
        except Exception:  # noqa: BLE001
            return None
        self._poll_store_cache = store
        return store

    def request_poll(self) -> None:
        """Ask the keeper thread to probe on its next tick. Does not touch disk."""
        self._poll_now = True

    def _hot_work_pending(self, *, now: float | None = None) -> bool:
        """True when a hot save is in flight or was marked very recently.

        Used to keep the newcomer walk (and other slow producers) off the hot
        critical path — a naive fix of the ``now=`` bug alone re-marked in-flight
        saves as ``disk_poll`` and starved hot sync (OPEN-D).
        """
        from pipeline.dirty_ledger import is_hot_reason, normalize_dirty_path

        current = time.monotonic() if now is None else now
        try:
            quiet_s = float(os.environ.get("CTX_NEWCOMER_QUIET_S") or "10")
        except ValueError:
            quiet_s = 10.0
        last = self._last_hot_mark_at
        if last is not None and (current - last) < max(0.0, quiet_s):
            return True
        snap = self.dirty_ledger.snapshot().get("paths") or {}
        for entry in snap.values():
            if not isinstance(entry, dict):
                continue
            if not is_hot_reason(entry.get("reason")):
                continue
            if str(entry.get("state") or "") in {"queued", "due", "processing"}:
                return True
        return False

    def _enqueue_newcomers(self, *, now: float) -> list[str]:
        """Slow path for files that are not in the merkle yet. Not the 1s poll."""
        from pipeline.dirty_ledger import is_hot_reason, normalize_dirty_path
        from pipeline.root_probe import root_probe

        try:
            probe = root_probe(self.repo, discover_newcomers=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] newcomer scan failed: {exc}", file=sys.stderr, flush=True)
            return []
        added = [str(p).replace("\\", "/") for p in probe.added if str(p).strip()]
        ghosts = self._corpus_ghosts()
        if ghosts:
            print(
                f"[keeper] {len(ghosts)} file(s) in the corpus are gone from disk — queued for removal: "
                f"{', '.join(ghosts[:5])}{' …' if len(ghosts) > 5 else ''}",
                file=sys.stderr,
                flush=True,
            )
            added.extend(g for g in ghosts if g not in added)
        if not added:
            return []
        # Same in-flight filter as poll_repo_changes — never downgrade a hot
        # save to disk_poll or slide its debounce (OPEN-D).
        snap = self.dirty_ledger.snapshot().get("paths") or {}
        fresh: list[str] = []
        for path in added:
            entry = snap.get(normalize_dirty_path(path)) or {}
            state = str(entry.get("state") or "")
            if state in {"queued", "due", "processing", "overlay_ready"}:
                continue
            if is_hot_reason(entry.get("reason")):
                continue
            fresh.append(path)
        if not fresh:
            return []
        self.mark_dirty(fresh, reason="disk_poll", now=now)
        return fresh

    def _corpus_ghosts(self) -> list[str]:
        """Files chunks.jsonl still serves that no longer exist on disk.

        The poll and the newcomer walk both diff disk against merkle.json. A file
        deleted while the engine was down (killed probe), or deleted between a
        full index's chunking and its merkle scan, is in chunks.jsonl but not in
        the merkle, so neither diff ever reports it and search keeps returning a
        file that is gone. Marking it dirty lets the normal slice drop its chunks.
        """
        try:
            from pipeline.project_id import peek_project

            ref = peek_project(self.repo)
            if ref is None:
                return []
            path = ref.store_dir / "chunks.jsonl"
            if not path.is_file():
                return []
            seen: set[str] = set()
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"file"' not in line:
                        continue
                    try:
                        rel = str(json.loads(line).get("file") or "").replace("\\", "/")
                    except ValueError:
                        continue
                    if rel:
                        seen.add(rel)
            return sorted(rel for rel in seen if not (self.repo / rel).exists())
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] ghost scan failed: {exc}", file=sys.stderr, flush=True)
            return []

    def _start_newcomer_scan(self, *, now: float | None = None) -> bool:
        """Run the newcomer scan on its own thread. False if one is still running.

        The scan walks the whole repo (``collect_index_relpaths``, ~7.5s here). On
        the keeper thread it froze drain_due every 30s, so any save landing in
        that window waited the full scan before syncing. It only reads the Merkle
        and marks the (locked) ledger, so it does not need the keeper thread.
        """
        existing = self._newcomer_thread
        if existing is not None and existing.is_alive():
            return False
        current = time.monotonic() if now is None else now
        if self._hot_work_pending(now=current):
            return False

        def _scan() -> None:
            try:
                # Fresh clock at enqueue time — caller's ``now`` is stale after the walk.
                self._enqueue_newcomers(now=time.monotonic())
            except Exception as exc:  # noqa: BLE001
                print(f"[keeper] newcomer scan failed: {exc}", file=sys.stderr, flush=True)

        thread = threading.Thread(target=_scan, name="ctx-newcomer-scan", daemon=True)
        self._newcomer_thread = thread
        thread.start()
        return True

    def _start_ast_revalidate(self) -> bool:
        """Background rebake of the pack AST bundle when the corpus changed (BUG-A).

        Off the keeper thread (the extraction is ~20s and runs in a fresh
        interpreter). Single-flight here and inside
        ``refresh_ast_bundle_if_stale``; it self-skips when the bundle is already
        fresh, so this is cheap on a quiet repo.
        """
        existing = self._ast_revalidate_thread
        if existing is not None and existing.is_alive():
            return False

        def _revalidate() -> None:
            try:
                from pipeline.context_trace import refresh_ast_bundle_if_stale

                out = refresh_ast_bundle_if_stale(self.repo, block=True)
                if out.get("ok") and not out.get("skipped"):
                    print(
                        f"[keeper] ast bundle revalidated source={out.get('source')} "
                        f"ms={out.get('ms')}",
                        file=sys.stderr,
                        flush=True,
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"[keeper] ast revalidate failed: {exc}", file=sys.stderr, flush=True)

        thread = threading.Thread(target=_revalidate, name="ctx-ast-revalidate", daemon=True)
        self._ast_revalidate_thread = thread
        thread.start()
        return True

    def _adapt_poll_interval(self) -> None:
        """Adaptive backoff: slow I/O → increase poll interval; fast I/O → restore.

        If the last 3 probes all took > 2s, double the poll interval (up to 10s).
        If the last 3 probes all took < 500ms, restore to the original interval.
        This handles antivirus interference and slow network drives gracefully.
        """
        MAX_POLL_MS = 10_000
        SLOW_THRESHOLD_S = 2.0
        FAST_THRESHOLD_S = 0.5
        MIN_SAMPLES = 3

        if len(self._probe_durations) < MIN_SAMPLES:
            return

        recent = self._probe_durations[-MIN_SAMPLES:]
        avg_ms = sum(recent) * 1000 / len(recent)

        if all(d > SLOW_THRESHOLD_S for d in recent):
            # All recent probes are slow — back off
            if not self._backoff_active or self.change_poll_ms < MAX_POLL_MS:
                new_poll = min(self.change_poll_ms * 2, MAX_POLL_MS)
                if new_poll != self.change_poll_ms:
                    print(
                        f"[keeper] slow I/O detected ({avg_ms:.0f}ms avg), "
                        f"backing off to {new_poll}ms poll interval",
                        file=sys.stderr,
                        flush=True,
                    )
                    self.change_poll_ms = new_poll
                    self._backoff_active = True
        elif all(d < FAST_THRESHOLD_S for d in recent) and self._backoff_active:
            # I/O recovered — restore original interval
            if self.change_poll_ms != self._original_change_poll_ms:
                print(
                    f"[keeper] I/O recovered ({avg_ms:.0f}ms avg), "
                    f"restoring {self._original_change_poll_ms}ms poll interval",
                    file=sys.stderr,
                    flush=True,
                )
                self.change_poll_ms = self._original_change_poll_ms
                self._backoff_active = False

    def reconcile(self, reason: str = "manual") -> dict:
        """Probe the repository and enqueue Merkle-discovered dirty paths."""
        try:
            paths = self.poll_repo_changes()
            self._watcher_last_reconcile = time.monotonic()
            self._watcher_last_error = None
            return {
                "reason": reason,
                "dirty_paths": paths,
                "marked": len(paths),
                "sync_status": self.status()["sync_status"],
            }
        except Exception as exc:
            self._watcher_last_error = str(exc)
            raise

    def note_watcher_overflow(self) -> dict:
        """Discard buffered watcher detail and immediately trust Merkle state."""
        self.needs_full = True
        return self.reconcile(reason="watcher_overflow")

    def note_watcher_restart(self, error: str | None = None) -> None:
        self._watcher_restart_count += 1
        self._watcher_last_error = error

    def check_time_gap(self, *, now: float | None = None) -> dict | None:
        """Detect suspend/resume from a monotonic scheduling gap."""
        current_time = time.monotonic() if now is None else now
        previous = self._last_clock_at
        self._last_clock_at = current_time
        if previous is None or current_time < previous:
            return None
        if current_time - previous <= self.wake_gap_ms / 1000:
            return None
        self._watcher_last_wake_reconcile = current_time
        return self.reconcile(reason="sleep_wake")

    def drain_due(self, *, now: float | None = None) -> list[dict]:
        current_time = time.monotonic() if now is None else now
        recovered = self.dirty_ledger.recover_stale_processing(now=current_time)
        if recovered:
            print(
                f"[keeper] recovered {len(recovered)} stale processing path(s)",
                file=sys.stderr,
                flush=True,
            )
        committed = self._poll_graph_job(now=current_time)
        paths = self._additions_before_deletions(self.dirty_ledger.due_paths(now=current_time))
        if not paths:
            self.drain_publish(now=current_time)
            return [committed] if committed else []
        if self._defer_cold_embedder(paths, now=current_time):
            return [{"refreshed": False, "strategy": "embedder_cold", "files": paths[:50]}]

        # A file the editor just saved must be embedded even when a large
        # backlog is also due. Otherwise map searches a chunk list that never
        # received the new path (the backlog slice keeps taking the first 50).
        paths = self._hold_graph_catchups(paths, now=current_time)
        if not paths:
            self.drain_publish(now=current_time)
            return []
        estimated_total, estimates = self._estimate_dirty_chunks(paths)
        writes, backlog = self._split_explicit_writes(paths)
        if writes and backlog:
            # Unconditional, not just above the bulk threshold: a single non-hot
            # path costs ~7s here (it carries the whole-graph merge), which alone
            # blows the save→map budget for anything queued behind it.
            self.dirty_ledger.defer(backlog, now=current_time + 2.0)
            paths = writes
            estimated_total, estimates = self._estimate_dirty_chunks(paths)
        elif not writes and backlog:
            # Hot save marked but not yet due — don't start a non-hot backlog ahead
            # of it (OPEN-C hot-first deferral).
            from pipeline.dirty_ledger import is_hot_reason, normalize_dirty_path

            snap = self.dirty_ledger.snapshot().get("paths") or {}
            hot_queued = any(
                is_hot_reason((e or {}).get("reason"))
                and str((e or {}).get("state") or "") == "queued"
                for e in snap.values()
                if isinstance(e, dict)
            )
            if hot_queued:
                try:
                    from pipeline.dirty_ledger import hot_debounce_ms_default

                    defer_s = (hot_debounce_ms_default() + 250) / 1000.0
                except Exception:  # noqa: BLE001
                    defer_s = 0.5
                self.dirty_ledger.defer(backlog, now=current_time + defer_s)
                self.drain_publish(now=current_time)
                return []
            paths = backlog
            estimated_total, estimates = self._estimate_dirty_chunks(paths)

        # --- Tier 3: >10000 chunks — refuse, require explicit full index ---
        if estimated_total > self.auto_full_index_chunks:
            self.needs_full = True
            payload = {
                "refreshed": False,
                "files": paths[:50],
                "chunks_upserted": 0,
                "chunks_removed": 0,
                "strategy": "explicit_full_index_required",
                "needs_full": True,
                "estimated_chunks": estimated_total,
                "auto_full_index_chunks": self.auto_full_index_chunks,
                "error": (
                    f"approximately {estimated_total} chunks changed, exceeding the "
                    f"automatic limit of {self.auto_full_index_chunks}; run "
                    f"`scubiee index {self.repo} --force` explicitly"
                ),
                "warnings": [
                    "Automatic sync paused before graph/vector mutation; explicit full indexing is required."
                ],
            }
            self.last_result = payload
            self.dirty_ledger.defer(paths, now=current_time + 60.0)
            return [payload]

        # --- Tier 2: 301–10000 chunks — sub-batches. While an IDE is locating
        # or connected, do one batch and leave the rest due in 2s so locate
        # is not stuck behind the whole set. Idle runs the set straight through.
        if estimated_total > self.bulk_reindex_threshold:
            self.catchup_chunked = True
            work = paths
            reason = "bulk_reindex"
            if self._session_busy(current_time):
                width = max(1, int(os.environ.get("CTX_BULK_SUB_BATCH", "50") or "50"))
                work, rest = paths[:width], paths[width:]
                if rest:
                    self.dirty_ledger.defer(rest, now=current_time + 2.0)
                reason = "bulk_slice"
            try:
                payload = self._bulk_sync_paths(work, reason=reason)
            except Exception:
                # Only re-mark paths that are NOT already published by
                # completed sub-batches — avoid overriding durable progress.
                snap = self.dirty_ledger.snapshot().get("paths", {})
                unpublished = [
                    p for p in paths
                    if (snap.get(p) or {}).get("state") != "published"
                ]
                if unpublished:
                    self.dirty_ledger.mark(unpublished, reason="retry", now=current_time)
                self.catchup_chunked = False
                raise
            self.live_batches += 1
            self.last_result = payload
            if payload.get("strategy") == "explicit_full_index_required":
                self.needs_full = True
                payload["needs_full"] = True
            elif payload.get("refreshed"):
                # _bulk_sync_paths already committed sub-batches to journal;
                # just notify the publication layer for generation advance.
                self._notify_refresh(payload)
            self.catchup_chunked = False
            self.drain_publish(now=current_time)
            return [payload]

        # --- Tier 1: ≤300 chunks — fast live batch ---
        batch: list[str] = []
        estimated_batch = 0
        for path in paths:
            if len(batch) >= self.live_max_files:
                break
            estimate = estimates.get(path, 1)
            if batch and estimated_batch + estimate > self.live_max_chunks:
                break
            batch.append(path)
            estimated_batch += estimate
            if estimated_batch >= self.live_max_chunks:
                break
        if not batch:
            batch = [paths[0]]
        # RETIRED (spec task 7 / R9.1): the deletion-mask hack deferred a
        # deletion-only batch whenever an UNRELATED hot save was pending, so a
        # delete's prune latency depended on concurrent save activity — the exact
        # inconsistency the unified model removes. Deletions now flow through the
        # normal batch below and prune within one consistent drain+publish bound,
        # regardless of other pending work. Default OFF; set CTX_HOT_DELETE_MASK=1
        # to restore the old conditional-defer behavior (rollback only).
        mask_on = (os.environ.get("CTX_HOT_DELETE_MASK") or "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if mask_on and batch and all(not (self.repo / p).is_file() for p in batch):
            # Only defer when a real (on-disk) hot save is still pending — not
            # merely because the deletion itself was marked with a hot reason.
            from pipeline.dirty_ledger import is_hot_reason, normalize_dirty_path

            snap = self.dirty_ledger.snapshot().get("paths") or {}
            hot_present_pending = False
            for entry in snap.values():
                if not isinstance(entry, dict):
                    continue
                if not is_hot_reason(entry.get("reason")):
                    continue
                if str(entry.get("state") or "") not in {"queued", "due", "processing"}:
                    continue
                ep = str(entry.get("path") or "")
                if ep and (self.repo / ep).is_file():
                    hot_present_pending = True
                    break
            if hot_present_pending:
                quiet_until = current_time + max(0.0, float(self.graph_catchup_quiet_s))
                self.dirty_ledger.mark(
                    batch, reason="deletion_catchup", now=current_time
                )
                self.dirty_ledger.defer(batch, now=quiet_until)
                print(
                    f"[keeper] defer deletion-only batch ({len(batch)}) until quiet",
                    file=sys.stderr,
                    flush=True,
                )
                self.drain_publish(now=current_time)
                return [
                    {
                        "refreshed": False,
                        "strategy": "deletion_deferred",
                        "files": batch[:50],
                    }
                ]
        batch_set = set(batch)
        deferred = [path for path in paths if path not in batch_set]
        if deferred:
            self.catchup_chunked = True
            self.dirty_ledger.defer(deferred, now=current_time)
        hot_batch = self._is_hot_batch(batch)
        marked_at = self._oldest_marked_at(batch) if hot_batch else 0.0
        queue_ms = (current_time - marked_at) * 1000 if marked_at > 0 else None
        catchup_paths = self._catchup_paths(batch) if not hot_batch else []
        if catchup_paths and len(catchup_paths) == len(batch):
            started = self._start_graph_job(batch, now=current_time)
            if started is not None:
                self.drain_publish(now=current_time)
                return [started]
        if catchup_paths:
            print(
                f"[keeper] graph catch-up start paths={','.join(catchup_paths[:5])} batch={len(batch)}",
                file=sys.stderr,
                flush=True,
            )
        self.dirty_ledger.begin(batch)
        t_sync_wall = time.perf_counter()
        try:
            payload = self._sync_paths(batch, reason="dirty", hot=hot_batch)
        except Exception:
            self.dirty_ledger.mark(batch, reason="retry", now=current_time)
            raise
        if catchup_paths:
            print(
                f"[keeper] graph catch-up done ms={(time.perf_counter() - t_sync_wall) * 1000:.0f} "
                f"paths={','.join(catchup_paths[:5])}",
                file=sys.stderr,
                flush=True,
            )
        self.live_batches += 1
        chunk_count = int(payload.get("chunks_upserted") or 0) + int(payload.get("chunks_removed") or 0)
        if deferred:
            self.catchup_chunked = True
            payload["strategy"] = "catchup_chunked"
            payload["catchup_chunked"] = True
            payload["live_limits"] = {
                "max_files": self.live_max_files,
                "max_chunks": self.live_max_chunks,
                "deferred_paths": len(deferred),
                "chunks": chunk_count,
            }
        elif chunk_count > self.live_max_chunks:
            payload["live_limits"] = {
                "max_files": self.live_max_files,
                "max_chunks": self.live_max_chunks,
                "deferred_paths": 0,
                "chunks": chunk_count,
            }
        self.last_result = payload
        if payload.get("strategy") == "explicit_full_index_required":
            self.needs_full = True
            payload["needs_full"] = True
            self.dirty_ledger.defer(batch, now=current_time + 60.0)
        elif payload.get("refreshed") and (
            int(payload.get("chunks_upserted") or 0) + int(payload.get("chunks_removed") or 0) > 0
        ):
            wall = payload.setdefault("wall", {})
            wall["sync_call_ms"] = round((time.perf_counter() - t_sync_wall) * 1000, 1)
            # Hot lane: publish first. Session-span invalidation scans every
            # session store (~130 here, 0.2–2s under search load) and a new file
            # has no cached spans, so running it before the publish only delayed
            # map. Other batches keep the invalidate-then-publish order.
            # Edits (chunks removed) too: the scan cost 0.1-1.6s in front of
            # the publish, and the file on disk had already changed, so the
            # cached spans were stale either way until invalidation (issue 4).
            invalidate_after = hot_batch
            if not invalidate_after:
                t_inval = time.perf_counter()
                self._invalidate_session_paths(batch)
                wall["invalidate_ms"] = round((time.perf_counter() - t_inval) * 1000, 1)
            t_pub = time.perf_counter()
            self._publish_or_hold(payload, paths=batch, now=current_time)
            wall["publish_call_ms"] = round((time.perf_counter() - t_pub) * 1000, 1)
            if invalidate_after:
                t_inval = time.perf_counter()
                self._invalidate_session_paths(batch)
                wall["invalidate_ms"] = round((time.perf_counter() - t_inval) * 1000, 1)
        elif payload.get("error"):
            print(
                f"[keeper] dirty sync retry: {payload.get('error')}",
                file=sys.stderr,
                flush=True,
            )
            self.dirty_ledger.defer(batch, now=current_time + 2.0)
        else:
            self.dirty_ledger.complete(batch, published=True)
        if hot_batch:
            self._log_hot_sync(
                payload, batch, marked_at=marked_at, queue_ms=queue_ms
            )
        self._run_vector_flush(payload)
        owed = payload.get("graph_pending")
        if owed:
            # Non-hot reason on purpose: the catch-up carries the slow whole-graph
            # merge and must not re-enter the hot lane. Held back a few seconds so
            # a burst of saves coalesces into one catch-up and the next save is
            # never queued behind this one.
            self.dirty_ledger.mark(
                list(owed),
                reason="graph_catchup",
                now=current_time + self.graph_catchup_delay_s,
            )
        self.drain_publish(now=current_time)
        if not any(
            entry.get("state") in {"queued", "due", "processing"}
            for entry in self.dirty_ledger.snapshot().get("paths", {}).values()
        ):
            self.catchup_chunked = False
        return [payload]

    def drain_publish(self, *, now: float | None = None, force: bool = False) -> bool:
        current_time = time.monotonic() if now is None else now
        if self._pending_publish is None or (
            not force and self._locate_streak_active(now=current_time)
        ):
            return False

        payload = self._pending_publish
        paths = self._pending_paths
        self._pending_publish = None
        self._pending_paths = set()
        if self._notify_refresh(payload):
            self.dirty_ledger.complete(paths, published=True)
            return True
        payload["dense_pending"] = True
        payload["publish_error"] = payload.get("publish_error") or "publish_failed"
        self._pending_publish = payload
        self._pending_paths = set(paths)
        self.dirty_ledger.complete(paths, published=False)
        return False

    def _locate_streak_active(self, *, now: float | None = None) -> bool:
        if self._last_locate_at is None:
            return False
        current_time = time.monotonic() if now is None else now
        return current_time - self._last_locate_at < self.locate_streak_ms / 1000

    def _clients_active(self) -> bool:
        """True when an MCP/IDE/experiment client is registered against the engine."""
        try:
            from pipeline.lifecycle_runtime import active_client_count

            return active_client_count() > 0
        except Exception:  # noqa: BLE001
            return False

    def _defer_interval_while_clients(self) -> bool:
        """Skip periodic keeper ticks while any IDE/MCP client is connected.

        Default on (``CTX_KEEPER_DEFER_WHILE_CLIENTS=1``). Trigger / final / write
        reasons still run so disk edits can sync; only interval/test ticks yield.
        """
        raw = (os.environ.get("CTX_KEEPER_DEFER_WHILE_CLIENTS") or "1").strip().lower()
        return raw not in {"0", "false", "no", "off"}

    def _split_explicit_writes(self, paths: list[str]) -> tuple[list[str], list[str]]:
        """Files marked by a save, ahead of a disk-poll backlog."""
        from pipeline.dirty_ledger import HOT_SYNC_REASONS, normalize_dirty_path

        snap = self.dirty_ledger.snapshot().get("paths") or {}
        writes: list[str] = []
        backlog: list[str] = []
        for path in paths:
            entry = snap.get(normalize_dirty_path(path)) or {}
            reason = str(entry.get("reason") or "")
            if reason in HOT_SYNC_REASONS and (self.repo / path).is_file():
                writes.append(path)
            else:
                backlog.append(path)
        return writes, backlog

    def _run_vector_flush(self, payload: dict | None = None) -> None:
        """Persist the collection a hot sync left in memory. Never skipped.

        Runs on the keeper thread after the publish and before the next sync, so
        the next sync (which reloads the collection from disk) sees these rows.
        """
        flush, self._vector_flush = self._vector_flush, None
        pending_vdb, self._hot_vdb_pending = self._hot_vdb_pending, None
        if not callable(flush):
            return
        t0 = time.perf_counter()
        try:
            wrote = flush()
        except Exception as exc:  # noqa: BLE001
            # chunks.jsonl already names these ids; reconcile_vector_store
            # re-embeds any chunk whose vector is missing on the next sync.
            self._hot_vdb_cache = None
            print(f"[keeper] deferred vector save failed: {exc}", file=sys.stderr, flush=True)
            return
        if pending_vdb is not None:
            # Disk now matches this in-memory collection; the next hot sync may
            # reuse it as long as nobody else rewrites the files meanwhile.
            self._hot_vdb_cache = (pending_vdb, _vdb_fingerprint(pending_vdb))
        if wrote is False:
            return  # the publisher already flushed before a full reload
        ms = (time.perf_counter() - t0) * 1000
        if isinstance(payload, dict):
            payload.setdefault("wall", {})["vector_flush_ms"] = round(ms, 1)
        print(f"[keeper] deferred vector save ms={ms:.0f}", file=sys.stderr, flush=True)

    def _oldest_marked_at(self, paths: list[str]) -> float:
        """Monotonic time of the earliest save in this batch (0.0 if unknown)."""
        from pipeline.dirty_ledger import normalize_dirty_path

        snap = self.dirty_ledger.snapshot().get("paths") or {}
        stamps = [
            float((snap.get(normalize_dirty_path(path)) or {}).get("marked_at") or 0.0)
            for path in paths
        ]
        stamps = [s for s in stamps if s > 0.0]
        return min(stamps) if stamps else 0.0

    def _log_hot_sync(
        self,
        payload: dict,
        paths: list[str],
        *,
        marked_at: float,
        queue_ms: float | None = None,
    ) -> None:
        """One line per save, with every stage of the 5s save→map budget.

        When the SLA is missed this names the stage that ate it instead of
        leaving a single opaque total. ``debounce_ms`` is how long the save sat
        in the ledger (hot debounce plus tick latency); ``total_ms`` is mark →
        published, which is the number the live probe measures.
        """
        stages = payload.get("stages") if isinstance(payload.get("stages"), dict) else {}
        wall = payload.get("wall") if isinstance(payload.get("wall"), dict) else {}
        publish_ms = payload.get("publish_ms")
        sync_ms = float(payload.get("ms") or 0.0)
        total_ms = (time.monotonic() - marked_at) * 1000 if marked_at > 0 else None
        debounce_ms = queue_ms

        def _fmt(value: Any) -> str:
            return f"{float(value):.0f}" if isinstance(value, (int, float)) else "-"

        print(
            "[keeper] hot sync "
            f"path={','.join(paths[:3])}{'…' if len(paths) > 3 else ''} "
            f"debounce_ms={_fmt(debounce_ms)} "
            f"gate_ms={_fmt(stages.get('gate_ms'))} "
            f"prep_ms={_fmt(stages.get('prep_ms'))} "
            f"slice_ms={_fmt(stages.get('slice_ms'))} "
            f"parse_ms={_fmt(stages.get('parse_ms'))} "
            f"graph_ms={_fmt(stages.get('graph_ms'))} "
            f"embed_ms={_fmt(stages.get('embed_ms'))} "
            f"write_ms={_fmt(stages.get('write_ms'))} "
            f"vectors_ms={_fmt(stages.get('vectors_ms'))} "
            f"(open={_fmt(stages.get('vec_open_ms'))} "
            f"mutate={_fmt(stages.get('vec_mutate_ms'))} "
            f"save={_fmt(stages.get('vec_save_ms'))}) "
            f"chunkfile_ms={_fmt(stages.get('chunkfile_ms'))} "
            f"reconcile_ms={_fmt(stages.get('reconcile_ms'))} "
            f"merkle_ms={_fmt(stages.get('merkle_ms'))} "
            f"publication_ms={_fmt(stages.get('publication_ms'))} "
            f"cards_ms={_fmt(stages.get('cards_ms'))} "
            f"sync_ms={_fmt(sync_ms)} "
            f"sync_call_ms={_fmt(wall.get('sync_call_ms'))} "
            f"invalidate_ms={_fmt(wall.get('invalidate_ms'))} "
            f"publish_call_ms={_fmt(wall.get('publish_call_ms'))} "
            f"publish_ms={_fmt(publish_ms)} "
            f"total_ms={_fmt(total_ms)} "
            f"upserted={payload.get('chunks_upserted')} "
            f"removed={payload.get('chunks_removed')} "
            f"publish={payload.get('publish') or '-'} "
            f"pid={os.getpid()}",
            file=sys.stderr,
            flush=True,
        )

    def _start_graph_job(self, batch: list[str], *, now: float) -> dict | None:
        """Run a catch-up-only batch's graph merge in a child process (issue 6).

        Returns a payload when the batch was handed off (or parked behind the
        job already running); None means "run it inline as before".
        """
        from pipeline import graph_merge_worker as gmw

        if not gmw.async_enabled() or self._graph_job_failures >= 2:
            return None
        if self._graph_job is not None:
            # One merge at a time: each one rewrites the whole graph.
            self.dirty_ledger.defer(batch, now=now + 1.0)
            return {"refreshed": False, "strategy": "graph_catchup_waiting", "files": batch[:50]}
        try:
            ref = peek_project(self.repo)
        except Exception:  # noqa: BLE001
            ref = None
        if ref is None or not (ref.store_dir / "graph.json").is_file():
            return None
        self.dirty_ledger.begin(batch)
        try:
            job = gmw.start_graph_merge(self.repo, ref.store_dir, list(batch))
        except Exception as exc:  # noqa: BLE001
            self._graph_job_failures += 1
            print(f"[keeper] graph catch-up spawn failed: {exc!r}; running inline", file=sys.stderr, flush=True)
            return None
        self._graph_job = job
        print(
            f"[keeper] graph catch-up start paths={','.join(batch[:5])} batch={len(batch)} "
            f"async worker_pid={getattr(job.proc, 'pid', None)}",
            file=sys.stderr,
            flush=True,
        )
        return {"refreshed": False, "strategy": "graph_catchup_async", "files": batch[:50]}

    def _poll_graph_job(self, *, now: float) -> dict | None:
        """Commit a finished child merge: rename + merkle/publication refresh."""
        job = self._graph_job
        if job is None:
            return None
        info = job.poll()
        if info is None:
            if time.monotonic() - job.started_at < self.graph_job_timeout_s:
                return None
            job.kill()
            info = {"ok": False, "error": f"timeout after {self.graph_job_timeout_s:.0f}s"}
        self._graph_job = None
        from pipeline.dirty_ledger import normalize_dirty_path

        snap = self.dirty_ledger.snapshot().get("paths") or {}
        # A save to one of these files during the merge re-marked it; that
        # entry (and the catch-up it queues) is newer than this job — leave it.
        mine = [
            p
            for p in job.paths
            if str((snap.get(normalize_dirty_path(p)) or {}).get("state") or "") == "processing"
        ]
        label = ",".join(job.paths[:5])
        if not info.get("ok"):
            self._graph_job_failures += 1
            job.discard()
            print(
                f"[keeper] graph catch-up worker failed ({self._graph_job_failures}): "
                f"{info.get('error')} paths={label}",
                file=sys.stderr,
                flush=True,
            )
            self.dirty_ledger.mark(mine, reason="graph_catchup", now=now + 5.0)
            return {"refreshed": False, "strategy": "graph_catchup_failed", "error": info.get("error")}
        if not job.graph_unchanged():
            # Something else rewrote graph.json meanwhile; committing would drop it.
            job.discard()
            print(
                f"[keeper] graph catch-up discarded: graph.json changed during merge paths={label}",
                file=sys.stderr,
                flush=True,
            )
            self.dirty_ledger.mark(mine, reason="graph_catchup", now=now)
            return {"refreshed": False, "strategy": "graph_catchup_retry"}
        self._graph_job_failures = 0
        t_commit = time.perf_counter()
        try:
            payload = self._sync_paths(
                list(job.paths), reason="graph_catchup", hot=False, graph_precomputed=job.out
            )
        except Exception as exc:  # noqa: BLE001
            job.discard()
            print(f"[keeper] graph catch-up commit failed: {exc!r}", file=sys.stderr, flush=True)
            self.dirty_ledger.mark(mine, reason="graph_catchup", now=now + 2.0)
            return {"refreshed": False, "strategy": "graph_catchup_failed", "error": repr(exc)}
        commit_ms = (time.perf_counter() - t_commit) * 1000
        job.discard()
        chunk_count = int(payload.get("chunks_upserted") or 0) + int(payload.get("chunks_removed") or 0)
        if payload.get("refreshed") and chunk_count > 0:
            self._invalidate_session_paths(mine)
            self._publish_or_hold(payload, paths=mine, now=now)
        elif payload.get("error"):
            self.dirty_ledger.mark(mine, reason="graph_catchup", now=now + 2.0)
        else:
            self.dirty_ledger.complete(mine, published=True)
        self._run_vector_flush(payload)
        self.last_result = payload
        print(
            f"[keeper] graph catch-up done ms={info.get('wall_ms', 0) + commit_ms:.0f} "
            f"worker_ms={info.get('ms')} (extract={info.get('extract_ms')} merge={info.get('merge_ms')} "
            f"export={info.get('export_ms')}) commit_ms={commit_ms:.0f} nodes={info.get('nodes')} "
            f"paths={label}",
            file=sys.stderr,
            flush=True,
        )
        return payload

    def _catchup_paths(self, paths: list[str]) -> list[str]:
        """Paths in this batch that are queued graph catch-ups (for the log)."""
        from pipeline.dirty_ledger import normalize_dirty_path

        try:
            snap = self.dirty_ledger.snapshot().get("paths") or {}
        except Exception:  # noqa: BLE001
            return []
        return [
            p
            for p in paths
            if str((snap.get(normalize_dirty_path(p)) or {}).get("reason") or "") == "graph_catchup"
        ]

    def _hold_graph_catchups(self, paths: list[str], *, now: float) -> list[str]:
        """Push due graph catch-ups back until saves have been quiet for a while."""
        from pipeline.dirty_ledger import normalize_dirty_path

        snap = self.dirty_ledger.snapshot().get("paths") or {}
        # A missing file only needs a sync if it still owns chunks (the sync is
        # what removes them); never-indexed gone paths cost a ~20s no-delta vector
        # reconcile for nothing. A gone graph catch-up is kept: its hot sync
        # deferred the graph, so this catch-up is what prunes the file's nodes.
        gone = [p for p in paths if not (self.repo / p).is_file()]
        indexed = self._indexed_subset(gone) if gone else set()
        gone_done: list[str] = []
        kept: list[str] = []
        for path in paths:
            entry = snap.get(normalize_dirty_path(path)) or {}
            reason = str(entry.get("reason") or "")
            is_gone = not (self.repo / path).is_file()
            if (
                is_gone
                and reason != "graph_catchup"
                and path.replace("\\", "/") not in indexed
            ):
                gone_done.append(path)
            else:
                kept.append(path)
        if gone_done:
            self.dirty_ledger.complete(gone_done, published=True)

        last_hot = self._last_hot_mark_at
        if last_hot is None:
            return kept
        quiet_until = last_hot + max(0.0, float(self.graph_catchup_quiet_s))
        if now >= quiet_until:
            return kept
        snap = self.dirty_ledger.snapshot().get("paths") or {}
        held = [
            p
            for p in kept
            if str((snap.get(normalize_dirty_path(p)) or {}).get("reason") or "")
            == "graph_catchup"
        ]
        if not held:
            return kept
        last_log = float(getattr(self, "_hold_log_at", 0.0) or 0.0)
        if now - last_log >= 30.0:
            self._hold_log_at = now
            print(
                f"[keeper] holding {len(held)} graph catch-up(s) {quiet_until - now:.1f}s more: "
                f"last hot mark {now - last_hot:.1f}s ago {getattr(self, '_last_hot_mark_info', None)}",
                file=sys.stderr,
                flush=True,
            )
        self.dirty_ledger.defer(held, now=quiet_until)
        held_set = set(held)
        return [p for p in kept if p not in held_set]

    def _is_hot_batch(self, paths: list[str]) -> bool:
        """True when every path in the batch was marked by a save the user awaits.

        Selects the hot lane: no vector compaction during the touch and an
        append-only patch publish instead of a full binder rebuild.
        """
        from pipeline.dirty_ledger import is_hot_reason, normalize_dirty_path

        if not paths:
            return False
        snap = self.dirty_ledger.snapshot().get("paths") or {}
        for path in paths:
            entry = snap.get(normalize_dirty_path(path)) or {}
            if not is_hot_reason(entry.get("reason")):
                return False
        return True

    def _additions_before_deletions(self, paths: list[str]) -> list[str]:
        """Index files that still exist before a backlog of deletions."""
        present: list[str] = []
        missing: list[str] = []
        for path in paths:
            if (self.repo / path).is_file():
                present.append(path)
            else:
                missing.append(path)
        return present + missing

    def _defer_cold_embedder(self, paths: list[str], *, now: float) -> bool:
        """Leave the batch queued while FastEmbed is still loading.

        The engine opts in with CTX_SYNC_WAIT_FOR_EMBEDDER=1. Unit tests leave
        it unset so a missing model does not stall the ledger.
        """
        raw = (os.environ.get("CTX_SYNC_WAIT_FOR_EMBEDDER") or "").strip().lower()
        if raw not in {"1", "true", "yes", "on"}:
            return False
        try:
            from pipeline.engine import embedder_is_loaded, prewarm_embedder_async

            if embedder_is_loaded():
                self._cold_defer_since = None
                return False
            # Never defer forever: if the load has not landed in time, sync
            # anyway (incremental_sync loads the model itself). An embedder
            # that never reported loaded wedged every save behind this gate.
            try:
                cap_s = float(os.environ.get("CTX_SYNC_COLD_DEFER_MAX_S") or 30.0)
            except ValueError:
                cap_s = 30.0
            since = getattr(self, "_cold_defer_since", None)
            if since is None:
                self._cold_defer_since = since = now
            if now - since >= cap_s:
                print(
                    f"[keeper] embedder still cold after {now - since:.0f}s — syncing "
                    f"{len(paths)} path(s) anyway",
                    file=sys.stderr,
                    flush=True,
                )
                self._cold_defer_since = None
                return False
            prewarm_embedder_async(self.repo)
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] embedder prewarm skipped: {exc}", file=sys.stderr, flush=True)
            return False
        print(
            f"[keeper] embedder cold — defer {len(paths)} path(s)",
            file=sys.stderr,
            flush=True,
        )
        self.dirty_ledger.defer(paths, now=now + 2.0)
        return True

    def _session_busy(self, now: float | None = None) -> bool:
        """True when a locate streak or a connected IDE should see one batch at a time."""
        if self._locate_streak_active(now=now):
            return True
        return bool(self._defer_interval_while_clients() and self._clients_active())

    def _defer_for_active_session(
        self, paths: list[str], *, now: float, estimated_total: int
    ) -> dict | None:
        """Kept for callers. Sizing now happens in ``drain_due``, not by dropping the set."""
        return None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        enabled = os.environ.get("CTX_BACKGROUND_SYNC", "0").strip().lower()
        if enabled in {"0", "false", "no", "off"}:
            print("[keeper] background sync disabled (CTX_BACKGROUND_SYNC)", file=sys.stderr)
            return
        self._stop.clear()
        self._requeue_graph_debt()
        self._thread = threading.Thread(target=self._run, name="ctx-keeper", daemon=True)
        self._thread.start()
        self.running = True
        if self not in _ACTIVE_LOOPS:
            _ACTIVE_LOOPS.append(self)
        _register_atexit()
        self._start_trigger_watcher()
        print(
            f"[keeper] WARNING: root-probe every {self.interval_ms}ms for {self.repo}",
            file=sys.stderr,
            flush=True,
        )

    def _requeue_graph_debt(self) -> None:
        """Queue graph work a previous process owed; its ledger entries are gone."""
        try:
            ref = peek_project(self.repo)
            if ref is None:
                return
            meta = json.loads((ref.store_dir / "meta.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        owed = [str(p).replace("\\", "/") for p in (meta.get("graph_pending") or [])]
        if owed:
            self.dirty_ledger.mark(
                owed,
                reason="graph_catchup",
                now=time.monotonic() + self.graph_catchup_delay_s,
            )

    def stop(self) -> None:
        self._stop.set()
        self.running = False
        job = getattr(self, "_graph_job", None)
        if job is not None:
            # The paths stay owed in meta.graph_pending; the next start retries.
            self._graph_job = None
            job.kill()
        if self in _ACTIVE_LOOPS:
            _ACTIVE_LOOPS.remove(self)

    def keeper_tick(self, *, reason: str = "interval") -> dict:
        """Root probe first; incremental sync only when dirty. No embed on clean."""
        from pipeline.root_probe import root_probe

        # Yield entirely while agents are mid-locate (warm map p95 — R6).
        if reason in {"interval", "test"} and self._locate_streak_active():
            out = {
                "refreshed": False,
                "strategy": "deferred_locate_streak",
                "reason": "locate_streak",
                "locate_streak_active": True,
            }
            self.last_result = out
            print(
                "[keeper] skip tick — locate_streak active",
                file=sys.stderr,
                flush=True,
            )
            return out

        # Yield interval ticks while any IDE/MCP client is connected so map/pack
        # after minutes idle does not collide with root_probe/sync (R13).
        if (
            reason in {"interval", "test"}
            and self._defer_interval_while_clients()
            and self._clients_active()
        ):
            out = {
                "refreshed": False,
                "strategy": "deferred_clients_active",
                "reason": "clients_active",
                "clients_active": True,
                "locate_streak_active": False,
            }
            self.last_result = out
            print(
                "[keeper] skip tick — clients_active",
                file=sys.stderr,
                flush=True,
            )
            return out

        # Background ticks yield under resource pressure; final/trigger still try.
        if reason == "interval":
            try:
                from pipeline.resources import get_resource_manager

                b = get_resource_manager().budget("sync")
                if not b.allow:
                    print(
                        f"[keeper] skip tick — resources {b.pressure}: {b.reason}",
                        file=sys.stderr,
                        flush=True,
                    )
                    out = {
                        "refreshed": False,
                        "strategy": "deferred",
                        "reason": reason,
                        "resources": b.to_dict(),
                    }
                    self.last_result = out
                    return out
            except Exception as exc:  # noqa: BLE001
                print(f"[keeper] resource check skipped: {exc}", file=sys.stderr, flush=True)

        with self._lock:
            if self._syncing:
                return {"skipped": True, "reason": "already syncing"}
            self._syncing = True
        try:
            probe = root_probe(self.repo)
            self.last_probe = {**probe.to_dict(), "reason": reason}
            if probe.clean:
                print(
                    f"[keeper] root clean ({probe.ms:.0f}ms, checked={probe.files_checked}) [{reason}]",
                    file=sys.stderr,
                    flush=True,
                )
                out = {
                    "refreshed": False,
                    "strategy": "root_clean",
                    "probe": probe.to_dict(),
                    "reason": reason,
                }
                self.last_result = out
                return out

            print(
                f"[keeper] root dirty changed={probe.changed_count} "
                f"(+{len(probe.added)} ~{len(probe.modified)} -{len(probe.removed)}) "
                f"[{reason}] — incremental sync",
                file=sys.stderr,
                flush=True,
            )
            return self._sync_unlocked(probe_meta=probe.to_dict(), reason=reason)
        finally:
            with self._lock:
                self._syncing = False
            # Safe point: collect garbage after sync completes. GC is disabled
            # globally in the daemon to prevent SIGSEGV during native extension
            # work (tokenizers/MLX/numpy). Skip GC while locate_streak is active
            # so map/pack do not pay a stop-the-world pause (R6/R13).
            if not self._locate_streak_active() and not (
                self._defer_interval_while_clients() and self._clients_active()
            ):
                import gc

                gc.collect()

    def final_check(self, *, reason: str = "shutdown") -> dict:
        """One last cheap probe (+ sync if dirty). Best-effort; once per stop."""
        if getattr(self, "_final_done", False):
            return {"skipped": True, "reason": "final_already_done"}
        self._final_done = True
        try:
            # Stop/shutdown must flush held overlay even mid-locate streak —
            # otherwise dirty edits stay unpublished after MCP disconnect.
            self._last_locate_at = None
            result = self.keeper_tick(reason=reason)
            forced_paths = self.dirty_ledger.force_due()
            synced: list[dict] = []
            if forced_paths:
                synced = list(self.drain_due() or [])
            delivered = self.drain_publish(force=True)
            if not delivered and synced and self._pending_publish is None:
                # drain_due published inline (no hold) after streak clear.
                delivered = any(
                    isinstance(p, dict) and p.get("refreshed") for p in synced
                )
            result["publish_delivered"] = bool(delivered)
            return result
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] final_check failed: {exc}", file=sys.stderr, flush=True)
            return {"error": str(exc), "reason": reason}

    def sync_once(self) -> dict:
        """Force incremental path (trigger file / manual). Still root-gated via tick."""
        return self.keeper_tick(reason="trigger")

    def _sync_unlocked(self, *, probe_meta: dict | None = None, reason: str = "interval") -> dict:
        from pipeline.incremental import incremental_sync

        result = incremental_sync(self.repo)
        payload = result.to_dict()
        payload["probe"] = probe_meta
        payload["reason"] = reason
        self.last_result = payload
        # Oversize refusal on the interval path must raise the needs_full flag
        # like the hot/bulk paths do; otherwise status() only sees it via the
        # transient last_sync.strategy and nothing escalates to a reindex.
        if payload.get("strategy") == "explicit_full_index_required":
            self.needs_full = True
            payload["needs_full"] = True
        if result.refreshed:
            print(
                f"[keeper] refreshed {len(result.files)} files in {result.ms:.0f}ms",
                file=sys.stderr,
                flush=True,
            )
            self._publish_or_hold(payload, paths=result.files)
        return payload

    def _hot_vdb(self):
        """Vector DB reused across consecutive hot syncs, or None for a fresh one.

        A fresh ``VectorDatabase`` per sync reopens the collection from disk and
        then re-reads the whole ``faiss.index`` before the first append (~600ms
        per save here). Reuse is only safe while nobody else wrote the collection,
        so it is guarded by the on-disk fingerprint recorded after our own save;
        any other writer (non-hot sync, compaction, full index) forces a reload.
        """
        if (os.environ.get("CTX_HOT_VDB_CACHE") or "1").strip().lower() in {"0", "false", "no", "off"}:
            return None
        cached = self._hot_vdb_cache
        if cached is None:
            return None
        vdb, fingerprint = cached
        if fingerprint is None or _vdb_fingerprint(vdb) != fingerprint:
            self._hot_vdb_cache = None
            return None
        return vdb

    def _sync_paths(
        self,
        paths: list[str],
        *,
        reason: str,
        hot: bool = False,
        graph_precomputed: Path | None = None,
    ) -> dict:
        from pipeline.incremental import incremental_sync
        from pipeline.vectordb import VectorDatabase

        extra: dict = {}
        if graph_precomputed is not None:
            extra["graph_precomputed"] = graph_precomputed

        vdb = None
        if hot:
            vdb = self._hot_vdb() or VectorDatabase()
        else:
            # OPEN-C: keep the hot collection across keeper-owned non-hot syncs so
            # the next save does not pay a multi-second FAISS reopen. Drop only
            # when there is no coherent cached vdb (fingerprint mismatch / miss).
            vdb = self._hot_vdb()
            if vdb is None:
                self._hot_vdb_cache = None
        if vdb is not None:
            result = incremental_sync(self.repo, force_files=paths, hot_lane=hot, vdb=vdb, **extra)
            # Remembered now; the fingerprint is taken after the deferred save.
            self._hot_vdb_pending = vdb
        else:
            result = incremental_sync(self.repo, force_files=paths, hot_lane=hot, **extra)
        payload = result.to_dict()
        payload["reason"] = reason
        payload["hot_lane"] = bool(hot)
        payload["dirty_paths"] = paths
        stages = getattr(result, "stages", None)
        if stages:
            payload["stages"] = dict(stages)
        # A hot save skips the ~6s whole-graph merge; drain_due re-queues these
        # once the batch is completed (marking here would be overwritten by
        # ``complete``), so a non-hot tick carries them into graph.json.
        owed = getattr(result, "graph_pending", None)
        if owed:
            payload["graph_pending"] = list(owed)
        # Hot lane: the collection save runs after publish (see drain_due).
        self._vector_flush = getattr(result, "vector_flush", None)
        # Side channel, not payload: ``last_result`` is serialized by status().
        delta = getattr(result, "hot_delta", None)
        self._hot_delta = (payload, delta) if delta is not None else None
        print(
            f"[keeper] dirty sync refreshed={payload.get('refreshed')} "
            f"upserted={payload.get('chunks_upserted')} removed={payload.get('chunks_removed')} "
            f"ms={payload.get('ms')} error={payload.get('error')}",
            file=sys.stderr,
            flush=True,
        )
        return payload

    def _bulk_sync_paths(self, paths: list[str], *, reason: str) -> dict:
        """Process dirty paths in committed sub-batches with bootstrap memory budget.

        Used for 301–10000 chunk changes (like a GitHub pull) that should
        complete in minutes. Processes files in sub-batches of ~50, committing
        each to disk atomically. If the process is interrupted (power loss,
        crash), only the in-flight sub-batch is lost — completed sub-batches
        are durable, and the dirty journal re-queues unfinished paths on restart.

        Uses 800 MB RSS cap and batch 48 — same as initial full index.
        """
        from pipeline.incremental import incremental_sync

        # Drop non-actionable paths up front and COMPLETE them in the ledger.
        # A path is non-actionable when it can neither be indexed nor removed:
        #   - it resolves OUTSIDE the repo root (a stray /v1/dirty, a watcher that
        #     saw a sibling dir) — incremental_sync's relative_to(root) would have
        #     raised and failed the whole batch; now _paths_for_files filters it so
        #     the batch "refreshes nothing" and the OLD code re-queued it forever
        #     (permanent catching_up wedge that also stalled every path behind it);
        #   - it is gone from disk AND owns no chunks in the index (nothing to prune).
        # Completing these drains the ledger instead of looping.
        root_res = self.repo.resolve()

        def _inside_repo(rel: str) -> bool:
            cand = Path(rel)
            try:
                base = cand if cand.is_absolute() else (self.repo / rel)
                base.resolve().relative_to(root_res)
                return True
            except (ValueError, OSError):
                return False

        foreign = [p for p in paths if not _inside_repo(p)]
        in_repo = [p for p in paths if _inside_repo(p)]
        gone = [p for p in in_repo if not (self.repo / p).is_file()]
        indexed_gone = self._indexed_subset(gone) if gone else set()
        # gone + not indexed => nothing to upsert, nothing to remove.
        drop_now = list(foreign) + [
            p for p in gone if p.replace("\\", "/") not in indexed_gone
        ]
        if drop_now:
            self.dirty_ledger.complete(drop_now, published=True)
            print(
                f"[keeper] bulk drop {len(drop_now)} non-actionable path(s) "
                f"({len(foreign)} outside-repo, {len(drop_now) - len(foreign)} gone+unindexed)",
                file=sys.stderr,
                flush=True,
            )
            drop_set = set(drop_now)
            paths = [p for p in paths if p not in drop_set]

        BULK_SUB_BATCH = max(1, int(os.environ.get("CTX_BULK_SUB_BATCH", "50") or "50"))
        total_files = len(paths)
        total_upserted = 0
        total_removed = 0
        batches_done = 0
        t0 = time.monotonic()
        last_error: str | None = None
        last_strategy = "bulk_reindex"

        print(
            f"[keeper] bulk sync starting: {total_files} files in ~"
            f"{(total_files + BULK_SUB_BATCH - 1) // BULK_SUB_BATCH} sub-batches [{reason}]",
            file=sys.stderr,
            flush=True,
        )

        for i in range(0, total_files, BULK_SUB_BATCH):
            sub_batch = paths[i : i + BULK_SUB_BATCH]
            # Mark this sub-batch as processing in the journal so a crash
            # leaves them in a retriable state (not marked published).
            self.dirty_ledger.begin(sub_batch)
            try:
                result = incremental_sync(self.repo, force_files=sub_batch, bulk=True)
            except Exception as exc:
                # Return this sub-batch and all remaining to queue for retry.
                self.dirty_ledger.mark(sub_batch, reason="bulk_retry", now=time.monotonic())
                remaining = paths[i + BULK_SUB_BATCH:]
                if remaining:
                    self.dirty_ledger.mark(remaining, reason="bulk_retry", now=time.monotonic())
                last_error = str(exc)
                print(
                    f"[keeper] bulk sub-batch {batches_done + 1} failed: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                break

            if result.refreshed:
                self._invalidate_session_paths(sub_batch)
                self.dirty_ledger.complete(sub_batch, published=True)
                total_upserted += result.chunks_upserted
                total_removed += result.chunks_removed
            elif result.strategy == "explicit_full_index_required":
                # Exact post-parse guard fired — stop bulk and escalate.
                # Re-queue this sub-batch and all remaining un-attempted paths.
                self.dirty_ledger.mark(sub_batch, reason="bulk_oversized", now=time.monotonic())
                remaining = paths[i + BULK_SUB_BATCH:]
                if remaining:
                    self.dirty_ledger.mark(remaining, reason="bulk_oversized", now=time.monotonic())
                last_error = result.error
                last_strategy = "explicit_full_index_required"
                break
            else:
                # Deferred (resource pressure) or other non-refresh — re-queue
                # for retry rather than marking published (files weren't indexed).
                self.dirty_ledger.mark(sub_batch, reason="bulk_deferred", now=time.monotonic())
                remaining = paths[i + BULK_SUB_BATCH:]
                if remaining:
                    self.dirty_ledger.mark(remaining, reason="bulk_deferred", now=time.monotonic())
                if result.error:
                    last_error = result.error
                if result.strategy == "deferred":
                    last_error = last_error or "resource pressure — bulk deferred"
                break

            batches_done += 1
            elapsed = time.monotonic() - t0
            print(
                f"[keeper] bulk sub-batch {batches_done} done: "
                f"{len(sub_batch)} files, {result.chunks_upserted} upserted "
                f"({elapsed:.1f}s elapsed, {total_files - i - len(sub_batch)} files remaining)",
                file=sys.stderr,
                flush=True,
            )

        elapsed_ms = (time.monotonic() - t0) * 1000
        refreshed = total_upserted > 0 or total_removed > 0
        payload = {
            "refreshed": refreshed,
            "files": paths,
            "chunks_upserted": total_upserted,
            "chunks_removed": total_removed,
            "ms": round(elapsed_ms, 1),
            "strategy": last_strategy,
            "reason": reason,
            "bulk": True,
            "dirty_paths": paths,
            "bulk_progress": {
                "sub_batches_done": batches_done,
                "sub_batch_size": BULK_SUB_BATCH,
                "total_files": total_files,
                "files_completed": min(batches_done * BULK_SUB_BATCH, total_files),
            },
            # Only surface error to status if nothing succeeded; otherwise
            # a partial failure would permanently show "error" even though
            # most chunks were indexed. Partial errors go into warnings.
            "error": last_error if not refreshed else None,
            "warnings": [last_error] if (last_error and refreshed) else [],
        }
        print(
            f"[keeper] bulk sync done: {total_upserted} upserted, "
            f"{total_removed} removed in {elapsed_ms:.0f}ms "
            f"({batches_done} sub-batches)",
            file=sys.stderr,
            flush=True,
        )

        # Restore conservative background budget so the daemon doesn't keep
        # After bulk work, restore the conservative background budget so the daemon
        # doesn't keep running at elevated resources for subsequent small live edits.
        try:
            from pipeline.memory_budget import background_budget, force_apply_memory_budget

            force_apply_memory_budget(background_budget())
            print(
                "[keeper] budget restored to background (500MB + 15% CPU)",
                file=sys.stderr,
                flush=True,
            )
            try:
                from pipeline.memory_governor import get_governor
                from pipeline.ce_service import get_context_engine

                ce = get_context_engine()
                gov = get_governor()
                gov.refresh_from_hub(ce.hub)
                gov.demote_after_index()
                print(
                    f"[keeper] serve tier demoted to {gov.active_tier} "
                    f"(target {gov.config().rss_target_mb}MB)",
                    file=sys.stderr,
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[keeper] serve tier demote failed: {exc}", file=sys.stderr, flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] budget restore failed: {exc}", file=sys.stderr, flush=True)

        return payload

    def _invalidate_session_paths(self, paths: list[str]) -> None:
        try:
            from pipeline.session_store import invalidate_paths

            result = invalidate_paths(self.repo, paths)
            self.live_invalidations += int(result.get("removed") or 0)
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] session invalidation failed: {exc}", file=sys.stderr, flush=True)

    def _publish_or_hold(
        self,
        payload: dict,
        *,
        paths: Iterable[str],
        now: float | None = None,
    ) -> None:
        current_time = time.monotonic() if now is None else now
        hold = (
            self._locate_streak_active(now=current_time)
            and int(payload.get("chunks_upserted") or 0) > self.bulk_reindex_threshold
        )
        if hold:
            payload["overlay_ready"] = True
            self._pending_publish = payload
            self._pending_paths.update(paths)
            self.dirty_ledger.complete(paths, published=False)
            return
        if self._notify_refresh(payload):
            self.dirty_ledger.complete(paths, published=True)
        else:
            payload["dense_pending"] = True
            payload["publish_error"] = payload.get("publish_error") or "publish_failed"
            self.dirty_ledger.complete(paths, published=False)

    def _on_refresh_accepts_delta(self) -> bool:
        """Probe the publisher's arity once — never call it twice to find out."""
        cached = self._on_refresh_delta_arity
        if cached is not None:
            return cached
        accepts = False
        try:
            import inspect

            positional = 0
            for param in inspect.signature(self.on_refresh).parameters.values():
                if param.kind is inspect.Parameter.VAR_POSITIONAL:
                    positional = 2
                    break
                if param.kind in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                ):
                    positional += 1
            accepts = positional >= 2
        except (TypeError, ValueError):  # builtins / C callables
            accepts = False
        self._on_refresh_delta_arity = accepts
        return accepts

    def _notify_refresh(self, payload: dict) -> bool:
        """Deliver a coherent publication. False means prior generation stays live."""
        if not self.on_refresh:
            self._hot_delta = None
            return True
        pending = self._hot_delta
        delta = pending[1] if pending is not None and pending[0] is payload else None
        try:
            if delta is not None and self._on_refresh_accepts_delta():
                result = self.on_refresh(payload, delta)
            else:
                result = self.on_refresh(payload)
        except Exception as exc:  # noqa: BLE001
            print(f"[keeper] on_refresh error: {exc}", file=sys.stderr, flush=True)
            payload["publish_error"] = str(exc)
            return False
        finally:
            # One delta belongs to one publish attempt. A held/bulk publish that
            # runs later must fall back to a full reload, not reuse these rows.
            if self._hot_delta is pending:
                self._hot_delta = None
        if isinstance(result, dict) and result.get("ok") is False:
            payload["publish_error"] = str(result.get("error") or "publish_failed")
            return False
        return True

    def _run(self) -> None:
        delay = int(os.environ.get("CTX_SYNC_INITIAL_DELAY_MS", str(DEFAULT_INITIAL_DELAY_MS)))
        if self._stop.wait(max(0, delay) / 1000.0):
            return
        next_probe = time.monotonic()
        next_change_poll = time.monotonic()
        while not self._stop.is_set():
            try:
                now = time.monotonic()
                self.check_time_gap(now=now)
                if self._poll_now or now >= next_change_poll:
                    self._poll_now = False
                    self.poll_repo_changes(now=now)
                    next_change_poll = now + self.change_poll_ms / 1000.0
                # The walk takes seconds on big repos and stretches an overlapping hot save past SLA.
                try:
                    newcomer_every = float(os.environ.get("CTX_NEWCOMER_SCAN_S") or "600")
                except ValueError:
                    newcomer_every = 600.0
                if (
                    now - self._last_newcomer_scan >= max(5.0, newcomer_every)
                    and not self._locate_streak_active(now=now)
                    and not self._hot_work_pending(now=now)
                ):
                    self._last_newcomer_scan = now
                    self._start_newcomer_scan(now=now)
                # Stale-while-revalidate the pack AST bundle (BUG-A). Serve-stale
                # stays the pack request-path behavior; this quiet-window rebake
                # keeps pack's corpus in step with edits so map's suggested seeds
                # resolve. Gated like the newcomer scan: never mid-locate or
                # mid-hot-save, and it self-skips when the bundle is already fresh.
                # Re-check staleness every few seconds (cheap: one fingerprint
                # stat; single-flight prevents pile-up). 20s made pack wait up to
                # a fixed cadence after an edit; 5s fires promptly once the repo
                # goes quiet (PERF-1).
                try:
                    ast_every = float(os.environ.get("CTX_AST_REVALIDATE_S") or "5")
                except ValueError:
                    ast_every = 5.0
                # Not gated on _hot_work_pending or the full 60s locate streak:
                # the rebake is a below-priority child in a fresh interpreter (no
                # keeper GIL, no hot path), and an actively-edited/mapped repo is
                # exactly when pack's bundle goes stale — a tight map loop would
                # otherwise starve it for the whole streak. Skip only a very
                # recent locate (default 5s) so the spawn never lands on top of an
                # in-flight map/pack. Single-flight is enforced in the refresh.
                try:
                    ast_quiet_s = float(os.environ.get("CTX_AST_REVALIDATE_QUIET_S") or "5")
                except ValueError:
                    ast_quiet_s = 5.0
                locate_recent = (
                    self._last_locate_at is not None
                    and (now - self._last_locate_at) < max(0.0, ast_quiet_s)
                )
                if (
                    ast_every > 0
                    and now - self._last_ast_revalidate >= max(5.0, ast_every)
                    and not locate_recent
                ):
                    self._last_ast_revalidate = now
                    self._start_ast_revalidate()
                if now >= next_probe:
                    self.keeper_tick(reason="interval")
                    next_probe = now + self.interval_ms / 1000.0
                self.drain_due(now=now)
                self.drain_publish(now=now)
            except Exception as exc:  # noqa: BLE001
                print(f"[keeper] error: {exc}", file=sys.stderr, flush=True)
            if self._stop.wait(0.25):
                break

    def _start_trigger_watcher(self) -> None:
        if os.environ.get("CTX_TRIGGER_WATCHER", "1").strip().lower() in {"0", "false", "off"}:
            return

        def _watch() -> None:
            home = context_engine_home()
            home.mkdir(parents=True, exist_ok=True)
            trigger = home / TRIGGER_NAME
            last = trigger.stat().st_mtime if trigger.exists() else 0.0
            while not self._stop.is_set():
                try:
                    if trigger.exists():
                        m = trigger.stat().st_mtime
                        if m > last:
                            last = m
                            print(
                                "[keeper] trigger file touched — probe",
                                file=sys.stderr,
                                flush=True,
                            )
                            time.sleep(0.5)
                            self.keeper_tick(reason="trigger")
                except OSError:
                    pass
                if self._stop.wait(1.0):
                    break

        threading.Thread(target=_watch, name="ctx-trigger", daemon=True).start()


# Alias used in docs / status
KeeperLoop = BackgroundSyncLoop


def touch_sync_trigger() -> Path:
    """Hook helper: touch after Write/Edit so MCP catches up (Claude Context)."""
    home = context_engine_home()
    home.mkdir(parents=True, exist_ok=True)
    p = home / TRIGGER_NAME
    p.write_text(str(time.time()), encoding="utf-8")
    return p

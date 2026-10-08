"""The Reconciler — one idempotent detect -> enqueue -> classify entry point.

Spec: ``.kiro/specs/indexing-state-model/design.md`` (component C2).

This is the single place that answers "what does the engine need to do to make
the index match the working tree?" It is invoked at three moments:

  * engine start / warm   (trigger="start")  — closes the offline-change gap:
      drift that happened while the engine was OFF is detected and enqueued
      BEFORE the engine reports write-current, with no MCP client required.
  * MCP client connect     (trigger="connect") — so pending state is accurate the
      moment a client attaches after offline changes.
  * periodic keeper poll   (trigger="poll"/"wake").

It is deliberately split from EXECUTION (the keeper's hot/bulk lanes consume the
journal) and from LIFECYCLE (idle-stop). The reconciler only: detects drift via
the EXISTING detectors (``root_probe``), checks for an interrupted build, enqueues
drift into the DURABLE journal, and records the resulting index state. It performs
NO lane selection and NO embedding.

Idempotent: calling twice with no new working-tree change enqueues the same set
(the journal dedups by path; merkle is the stable baseline) and yields the same
index state.

Guarded by ``CTX_UNIFIED_STATE`` (default on). Set it to 0/false to make
``reconcile`` a no-op so the pre-existing poll/lane behavior is unchanged — the
rollback switch required by the spec (R10.4).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

Trigger = Literal["start", "connect", "poll", "wake"]


def unified_state_enabled() -> bool:
    """``CTX_UNIFIED_STATE`` (default on). The reconciler is a no-op when off."""
    raw = (os.environ.get("CTX_UNIFIED_STATE") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


@dataclass
class ReconcilePlan:
    """Outcome of one reconcile pass. Returned for callers/tests to inspect."""

    index_state: str = "fresh"
    added: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    enqueued: list[str] = field(default_factory=list)
    interrupted_build: Any | None = None
    pending: Any | None = None
    clean: bool = True
    skipped: str | None = None       # set when the reconciler short-circuited

    @property
    def drift_count(self) -> int:
        return len(self.added) + len(self.modified) + len(self.removed)


def _detect_drift(repo: Path, *, trigger: Trigger, store):
    """Working-tree-vs-merkle drift via the existing root_probe.

    ``start``/``connect`` do the thorough newcomer walk so a folder of files
    added while offline is fully discovered (not only dir-mtime-moved folders);
    ``poll``/``wake`` use the cheap path the keeper already runs each second.
    """
    from pipeline.root_probe import root_probe

    thorough = trigger in {"start", "connect"}
    probe = root_probe(
        repo,
        discover_newcomers=thorough,
        store=store,
    )
    return probe


def reconcile(
    repo: Path,
    *,
    trigger: Trigger,
    store=None,
    project_id: str | None = None,
    enqueue: Callable[[list[str], str], None] | None = None,
    classify: Callable[[list[str], list[str], list[str]], Any] | None = None,
) -> ReconcilePlan:
    """Detect drift, enqueue it durably, classify, and record index state.

    ``enqueue(paths, reason)``: durable work-queue sink (the keeper's
    ``mark_dirty`` in production; a fake in tests). When None, drift is detected
    and state recorded but nothing is enqueued (read-only probe).

    ``classify(added, modified, removed) -> PendingSummary``: workload classifier.
    When None, the real ``pipeline.workload.classify_workload`` is used (bound to
    this repo/store/corpus); a test may inject a fake. A classifier error falls
    back to a non-substantial placeholder so reconcile never crashes warm.
    """
    repo = Path(repo).resolve()
    plan = ReconcilePlan()

    if not unified_state_enabled():
        plan.skipped = "unified_state_disabled"
        return plan

    from pipeline.project_id import peek_project
    from pipeline.store import PipelineStore

    # Resolve project_id + store if not supplied.
    if project_id is None or store is None:
        try:
            ref = peek_project(repo)
            if ref is not None:
                project_id = project_id or ref.project_id
                if store is None:
                    store = PipelineStore(
                        repo, base_dir=ref.store_dir, project_id=ref.project_id, resolve=False
                    )
        except Exception:  # noqa: BLE001
            pass
    if not project_id:
        plan.skipped = "unresolved_project"
        return plan

    from pipeline.index_state import (
        PendingSummary,
        detect_interrupted_build,
        load_index_state,
        transition,
    )

    # 1. Interruption check — a build whose owner pid died.
    try:
        report = detect_interrupted_build(project_id)
    except Exception:  # noqa: BLE001
        report = None
    if report is not None and getattr(report, "interrupted", False):
        plan.interrupted_build = report.build

    # 2. Detect drift via the existing probe.
    try:
        probe = _detect_drift(repo, trigger=trigger, store=store)
        plan.added = list(probe.added)
        plan.modified = list(probe.modified)
        plan.removed = list(probe.removed)
        plan.clean = bool(probe.clean)
    except Exception as exc:  # noqa: BLE001
        # Detection failure must not lose work or crash warm; record and bail.
        try:
            transition(project_id, last_error=f"reconcile_detect:{exc}")
        except Exception:  # noqa: BLE001
            pass
        plan.skipped = "detect_failed"
        return plan

    drift_paths = [*plan.added, *plan.modified, *plan.removed]

    # 3. Enqueue drift into the durable journal (closes the offline-loss gap).
    if drift_paths and enqueue is not None:
        reason = "offline_reconcile" if trigger == "start" else "reconcile"
        try:
            enqueue(drift_paths, reason)
            plan.enqueued = list(drift_paths)
        except Exception:  # noqa: BLE001
            pass

    # 4. Classify workload: is the pending work small (silent) or substantial
    #    (minutes-scale, surfaced to the agent)? Uses the real classifier bound
    #    to this repo/store/corpus unless a caller injected a fake.
    pending = None
    if drift_paths:
        classifier = classify
        if classifier is None:
            corpus_size = 0
            if store is not None:
                try:
                    corpus_size = len(store.load_merkle() or {})
                except Exception:  # noqa: BLE001
                    corpus_size = 0

            def classifier(added, modified, removed):  # noqa: ANN001
                from pipeline.workload import classify_workload

                return classify_workload(
                    added,
                    modified,
                    removed,
                    repo=repo,
                    store=store,
                    corpus_size=corpus_size,
                    reason_hint=("offline_batch" if trigger == "start" else ""),
                )

        try:
            pending = classifier(plan.added, plan.modified, plan.removed)
        except Exception:  # noqa: BLE001
            pending = None
        if pending is None:
            pending = PendingSummary(
                substantial=False,
                reason=("offline_batch" if trigger == "start" else "incremental"),
                estimated_units=len(drift_paths),
                total_units=len(drift_paths),
                search_usable=True,
                detected_at=time.time(),
            )
    plan.pending = pending

    # 5. Record the resulting index state (authoritative record; still not yet
    #    consumed by lane selection / lifecycle — those come in tasks 6-7).
    if plan.interrupted_build is not None:
        new_state = "interrupted"
    elif not drift_paths:
        new_state = "fresh"
    elif pending is not None and getattr(pending, "substantial", False):
        new_state = "reconciling"
    else:
        new_state = "stale"
    plan.index_state = new_state

    try:
        transition(
            project_id,
            state=new_state,
            pending=(pending if (pending and getattr(pending, "substantial", False)) else None),
            last_error=None,
        )
    except Exception:  # noqa: BLE001
        pass

    return plan

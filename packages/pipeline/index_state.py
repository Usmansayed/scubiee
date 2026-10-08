"""Durable per-project index-state record — the single source of truth.

``index_state.json`` (under ``projects/<project_id>/``) records what the engine
knows about a repository's index: the lifecycle state, the generation it matches,
any in-flight build (for crash/interrupt recovery), and the agent-facing pending
summary. It unifies three things the engine previously had to *infer*:

  1. "Is a build in progress?"  (was: staging-dir pid liveness)
  2. "What generation does the served index match?"  (was: an in-mem int + token)
  3. "Is the pending work substantial?"  (was: not computed)

Design: ``.kiro/specs/indexing-state-model/design.md`` (component C1).

This module is pure persistence + a typed accessor. It performs NO change
detection and NO lane selection — the reconciler and keeper own those. It never
raises on load: a missing or old-version file degrades to a sentinel the
reconciler treats as "reconcile from scratch" (requirement R5.5 / R10.4).

``merkle.json`` + ``publication_manifest.json`` advance only together on a
committed generation; ``index_state.json`` records build *intent* before a build
mutates staging and completion *after* the manifest publishes. So any crash
leaves exactly one of: coherent old generation + a stale build record (resume),
or coherent new generation + no build record (done). Never a torn served index.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from pipeline.artifact_guard import atomic_write_text
from pipeline.project_id import projects_root

STATE_NAME = "index_state.json"
SCHEMA_VERSION = 1

IndexState = Literal[
    "unindexed",   # no coherent published generation
    "indexing",    # a generation build is in progress (build record present)
    "fresh",       # published generation matches the working tree
    "stale",       # small drift detected; incremental catch-up queued (silent)
    "reconciling", # substantial drift being worked through (surfaced to agent)
    "interrupted", # a build/sync was in progress when the process died
]

# States during which the engine must NOT idle-stop and which mean "work owed".
BUSY_STATES: frozenset[str] = frozenset({"indexing", "reconciling", "interrupted"})


@dataclass
class BuildRecord:
    """Durable note that an index/sync build is in flight (interrupt recovery)."""

    build_id: str
    pid: int
    kind: Literal["full", "bulk", "incremental"]
    started_at: float
    staging_dir: str | None = None
    total_units: int = 0
    done_units: int = 0
    phase: Literal["parse", "embed", "graph", "publish"] = "parse"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BuildRecord":
        return cls(
            build_id=str(data.get("build_id") or ""),
            pid=int(data.get("pid") or 0),
            kind=str(data.get("kind") or "incremental"),  # type: ignore[arg-type]
            started_at=float(data.get("started_at") or 0.0),
            staging_dir=(str(data["staging_dir"]) if data.get("staging_dir") else None),
            total_units=int(data.get("total_units") or 0),
            done_units=int(data.get("done_units") or 0),
            phase=str(data.get("phase") or "parse"),  # type: ignore[arg-type]
        )


@dataclass
class PendingSummary:
    """Agent-facing summary of pending work — populated only when substantial."""

    substantial: bool = False
    reason: str = ""                 # offline_batch | git_switch | bulk_paste | full_reindex | resuming_interrupted
    estimated_units: int = 0
    estimated_seconds: float = 0.0
    done_units: int = 0
    total_units: int = 0
    search_usable: bool = True
    action: str | None = None        # e.g. "scubiee index . --force" when a full reindex is required
    detected_at: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PendingSummary":
        return cls(
            substantial=bool(data.get("substantial")),
            reason=str(data.get("reason") or ""),
            estimated_units=int(data.get("estimated_units") or 0),
            estimated_seconds=float(data.get("estimated_seconds") or 0.0),
            done_units=int(data.get("done_units") or 0),
            total_units=int(data.get("total_units") or 0),
            search_usable=bool(data.get("search_usable", True)),
            action=(str(data["action"]) if data.get("action") else None),
            detected_at=float(data.get("detected_at") or 0.0),
        )


@dataclass
class IndexStateDoc:
    """The whole durable record. Serialized to ``index_state.json``."""

    version: int = SCHEMA_VERSION
    state: IndexState = "unindexed"
    generation_epoch: str = ""
    generation_counter: int = 0
    indexed_head: str | None = None
    merkle_root: str | None = None
    build: BuildRecord | None = None
    pending: PendingSummary | None = None
    last_reconcile_at: float = 0.0
    last_error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "version": int(self.version),
            "state": str(self.state),
            "generation_epoch": self.generation_epoch,
            "generation_counter": int(self.generation_counter),
            "indexed_head": self.indexed_head,
            "merkle_root": self.merkle_root,
            "build": asdict(self.build) if self.build is not None else None,
            "pending": asdict(self.pending) if self.pending is not None else None,
            "last_reconcile_at": float(self.last_reconcile_at),
            "last_error": self.last_error,
        }

    @property
    def is_busy(self) -> bool:
        return self.state in BUSY_STATES


def _sentinel() -> IndexStateDoc:
    """What load returns when the file is missing / corrupt / old-version.

    ``state="unindexed"`` tells the reconciler to rebuild its understanding from
    merkle + journal + manifest rather than trusting a record it cannot read.
    """
    return IndexStateDoc(state="unindexed")


def state_path(project_id: str) -> Path:
    return projects_root() / project_id / STATE_NAME


def _parse(document: dict[str, Any]) -> IndexStateDoc | None:
    if not isinstance(document, dict):
        return None
    if int(document.get("version") or 0) != SCHEMA_VERSION:
        return None  # old / future schema -> sentinel (caller reconciles)
    build_raw = document.get("build")
    pending_raw = document.get("pending")
    return IndexStateDoc(
        version=SCHEMA_VERSION,
        state=str(document.get("state") or "unindexed"),  # type: ignore[arg-type]
        generation_epoch=str(document.get("generation_epoch") or ""),
        generation_counter=int(document.get("generation_counter") or 0),
        indexed_head=(str(document["indexed_head"]) if document.get("indexed_head") else None),
        merkle_root=(str(document["merkle_root"]) if document.get("merkle_root") else None),
        build=BuildRecord.from_dict(build_raw) if isinstance(build_raw, dict) else None,
        pending=PendingSummary.from_dict(pending_raw) if isinstance(pending_raw, dict) else None,
        last_reconcile_at=float(document.get("last_reconcile_at") or 0.0),
        last_error=(str(document["last_error"]) if document.get("last_error") else None),
    )


def load_index_state(project_id: str) -> IndexStateDoc:
    """Load the record; never raises. Missing/corrupt/old-version -> sentinel."""
    if not project_id:
        return _sentinel()
    path = state_path(project_id)
    try:
        if not path.is_file():
            return _sentinel()
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _sentinel()
    parsed = _parse(document)
    return parsed if parsed is not None else _sentinel()


# Per-project in-process lock so concurrent transition() calls serialize.
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
# Last (epoch, counter) this process wrote — enforces per-epoch monotonicity
# even if a stale caller passes a lower counter.
_WRITTEN: dict[str, tuple[str, int]] = {}


def _lock_for(project_id: str) -> threading.RLock:
    with _LOCKS_GUARD:
        lock = _LOCKS.get(project_id)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[project_id] = lock
        return lock


def write_index_state(project_id: str, doc: IndexStateDoc) -> IndexStateDoc:
    """Atomically persist the record. Enforces per-epoch monotonic counter.

    A write whose ``(epoch, counter)`` would move the counter backward within the
    same epoch is clamped to the last written counter — a late-finishing older
    publish can never resurrect a lower generation (requirement R5.4).
    """
    if not project_id:
        return doc
    with _lock_for(project_id):
        prev = _WRITTEN.get(project_id)
        if (
            prev is not None
            and prev[0] == doc.generation_epoch
            and doc.generation_counter < prev[1]
        ):
            doc.generation_counter = prev[1]
        path = state_path(project_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(
                path,
                json.dumps(doc.to_json(), indent=2, sort_keys=True) + "\n",
            )
        except OSError:
            # Persistence is best-effort; the reconciler re-derives on next start.
            return doc
        _WRITTEN[project_id] = (doc.generation_epoch, int(doc.generation_counter))
        # Mirror the generation to the cross-process cache token so MCP map
        # caches invalidate on a published generation change.
        if doc.generation_epoch:
            try:
                from pipeline.index_generation import write_stamp

                write_stamp(project_id, doc.generation_counter, epoch=doc.generation_epoch)
            except Exception:  # noqa: BLE001
                pass
        return doc


def transition(project_id: str, **changes: Any) -> IndexStateDoc:
    """Load-modify-write under the per-project lock. Returns the new document.

    Pass any ``IndexStateDoc`` field as a keyword, e.g.::

        transition(pid, state="indexing", build=BuildRecord(...))
        transition(pid, state="fresh", build=None, generation_counter=42)

    ``last_reconcile_at`` is stamped automatically unless provided.
    """
    with _lock_for(project_id):
        doc = load_index_state(project_id)
        for key, value in changes.items():
            if not hasattr(doc, key):
                raise AttributeError(f"IndexStateDoc has no field {key!r}")
            setattr(doc, key, value)
        if "last_reconcile_at" not in changes:
            doc.last_reconcile_at = time.time()
        return write_index_state(project_id, doc)


def _pid_alive(pid: int) -> bool:
    """Best-effort cross-platform liveness check for a build record's owner pid."""
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not h:
                return False
            exit_code = ctypes.c_ulong(0)
            ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(h)
            return exit_code.value == 259  # STILL_ACTIVE
        os.kill(pid, 0)
        return True
    except Exception:  # noqa: BLE001
        return False


@dataclass
class InterruptionReport:
    interrupted: bool
    build: BuildRecord | None = None
    reason: str = ""   # "" | "dead_pid" | "no_build" | "owner_alive"


def detect_interrupted_build(project_id: str) -> InterruptionReport:
    """Report whether a build was in flight and its owner process has died.

    Read-only — does NOT mutate state or touch the live store (the manifest
    fence already guards serving). Callers on the start/warm path use this to
    decide whether to sweep staging + resume. (spec C4 / task 2.4)
    """
    doc = load_index_state(project_id)
    build = doc.build
    if build is None:
        return InterruptionReport(interrupted=False, reason="no_build")
    if _pid_alive(int(build.pid)) and int(build.pid) != os.getpid():
        # Another live process owns this build — do not disturb it.
        return InterruptionReport(interrupted=False, build=build, reason="owner_alive")
    if int(build.pid) == os.getpid():
        # Our own in-flight build (same process) — not an interruption.
        return InterruptionReport(interrupted=False, build=build, reason="owner_alive")
    return InterruptionReport(interrupted=True, build=build, reason="dead_pid")


def mark_interrupted(project_id: str) -> IndexStateDoc:
    """Record that a dead-pid build was detected; keep the build record for the
    resumer to read remaining-work details. Clears nothing on the live store."""
    return transition(project_id, state="interrupted")


# States surfaced to the agent as actionable pending work. Everything else
# (fresh / stale / unindexed / indexing-small) is absorbed silently: the current
# generation keeps serving and small catch-up finishes in the background.
AGENT_PENDING_STATES: frozenset[str] = frozenset({"reconciling", "interrupted"})


def agent_pending(project_id: str) -> dict[str, Any] | None:
    """The agent-facing ``pending`` object, or None when nothing is owed.

    Read-only, never raises. Returns a dict ONLY when the index state is
    actionable (reconciling / interrupted) AND the pending summary is marked
    substantial — small incremental catch-up stays silent so the agent is not
    nagged for every save (requirement R7.1/R7.2). Shape::

        {
          "substantial": true,
          "state": "reconciling",
          "reason": "offline_batch",
          "estimated_seconds": 42.0,
          "done_units": 0,
          "total_units": 318,
          "search_usable": true,          # current generation still serves
          "action": null                   # e.g. "scubiee index . --force"
        }
    """
    if not project_id:
        return None
    try:
        doc = load_index_state(project_id)
    except Exception:  # noqa: BLE001
        return None
    if doc.state not in AGENT_PENDING_STATES:
        return None
    summary = doc.pending
    interrupted = doc.state == "interrupted"
    # Interrupted is always surfaced (work was in flight when the process died).
    # Otherwise require a substantial summary; a non-substantial reconcile is
    # background catch-up and stays silent.
    if summary is None:
        if not interrupted:
            return None
        return {
            "substantial": True,
            "state": doc.state,
            "reason": "resuming_interrupted",
            "estimated_seconds": 0.0,
            "done_units": 0,
            "total_units": 0,
            "search_usable": True,
            "action": None,
        }
    if not interrupted and not summary.substantial:
        return None
    return {
        "substantial": bool(summary.substantial or interrupted),
        "state": doc.state,
        "reason": summary.reason or ("resuming_interrupted" if interrupted else ""),
        "estimated_seconds": float(summary.estimated_seconds),
        "done_units": int(summary.done_units),
        "total_units": int(summary.total_units),
        "search_usable": bool(summary.search_usable),
        "action": summary.action,
    }


def clear_index_state(project_id: str) -> None:
    """Remove the record (e.g. on project forget). Best-effort."""
    try:
        state_path(project_id).unlink(missing_ok=True)
    except OSError:
        pass
    with _lock_for(project_id):
        _WRITTEN.pop(project_id, None)


def reset_for_tests() -> None:
    """Clear process-local monotonic memory + locks (unit tests only)."""
    with _LOCKS_GUARD:
        _LOCKS.clear()
    _WRITTEN.clear()

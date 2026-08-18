"""Validate whether a registered repository is still present at known paths."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


PresenceState = Literal["active", "missing", "replaced", "conflict"]

# A positive floor preserves the invariant that a newly missing repo cannot be
# immediately forgotten, even if a caller supplies zero or a negative value.
MIN_RETENTION_S = 1.0


@dataclass
class PresenceReport:
    state: PresenceState
    project_id: str
    last_path: str | None
    live_path: str | None
    reasons: list[str]
    forget_allowed: bool


def _read_project_id(root: Path) -> tuple[str | None, str | None]:
    marker = root / ".context-engine" / "id.json"
    if not marker.is_file():
        return None, "identity marker is missing"
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "identity marker is unreadable"

    marker_id = payload.get("project_id") if isinstance(payload, dict) else None
    if not isinstance(marker_id, str) or not marker_id:
        return None, "identity marker has no project_id"
    return marker_id, None


def assess_presence(
    project_id: str,
    paths: list[str],
    *,
    now: float | None = None,
    missing_since: float | None = None,
    retention_s: float = 86400,
) -> PresenceReport:
    """Assess aliases, clamping non-positive retention to one safe second."""

    last_path = paths[0] if paths else None
    matching_paths: list[str] = []
    replacement_ids: list[str] = []
    conflicts: list[str] = []
    reasons: list[str] = []
    existing_count = 0

    for raw_path in paths:
        root = Path(raw_path)
        if not root.exists():
            reasons.append(f"{raw_path}: path is missing")
            continue

        existing_count += 1
        marker_id, marker_error = _read_project_id(root)
        if marker_error is not None:
            conflicts.append(raw_path)
            reasons.append(f"{raw_path}: {marker_error}")
        elif marker_id == project_id:
            matching_paths.append(raw_path)
            reasons.append(f"{raw_path}: identity matches {project_id}")
        else:
            replacement_ids.append(marker_id)
            reasons.append(
                f"{raw_path}: identity belongs to {marker_id}, expected {project_id}"
            )

    if matching_paths:
        return PresenceReport(
            state="active",
            project_id=project_id,
            last_path=last_path,
            live_path=matching_paths[0],
            reasons=reasons,
            forget_allowed=False,
        )

    if existing_count:
        state: PresenceState = (
            "replaced"
            if not conflicts and len(set(replacement_ids)) == 1
            else "conflict"
        )
        return PresenceReport(
            state=state,
            project_id=project_id,
            last_path=last_path,
            live_path=None,
            reasons=reasons,
            forget_allowed=False,
        )

    current_time = time.time() if now is None else now
    effective_retention_s = max(retention_s, MIN_RETENTION_S)
    retention_elapsed = (
        missing_since is not None
        and current_time >= missing_since
        and current_time - missing_since >= effective_retention_s
    )
    if not paths:
        reasons.append("no repository paths are registered")
    if retention_s <= 0:
        reasons.append("non-positive retention was clamped to one second")
    if missing_since is None:
        reasons.append("missing retention has not started")
    elif not retention_elapsed:
        reasons.append("missing retention has not elapsed")
    else:
        reasons.append("missing retention has elapsed")

    return PresenceReport(
        state="missing",
        project_id=project_id,
        last_path=last_path,
        live_path=None,
        reasons=reasons,
        forget_allowed=retention_elapsed,
    )

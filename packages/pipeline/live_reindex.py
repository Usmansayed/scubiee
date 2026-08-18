"""Changed-file ingress shared by MCP integrations and test harnesses."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Protocol


class DirtyClient(Protocol):
    def mark_dirty(
        self, paths: list[str], *, reason: str, path: str = ""
    ) -> dict: ...


def _repo_relative_paths(paths: Iterable[str]) -> tuple[list[str], list[str]]:
    accepted: list[str] = []
    rejected: list[str] = []
    for raw in paths:
        candidate = str(raw).replace("\\", "/").strip()
        while candidate.startswith("./"):
            candidate = candidate[2:]
        if not candidate or candidate.startswith("/") or ".." in Path(candidate).parts:
            rejected.append(str(raw))
            continue
        if candidate not in accepted:
            accepted.append(candidate)
    return accepted, rejected


def notify_changed_files(
    repo: Path | str,
    paths: Iterable[str],
    *,
    reason: str = "changed_file",
    client: DirtyClient | None = None,
) -> dict:
    """Submit changed repository-relative paths to the active daemon keeper."""
    from pipeline.client import EngineClient

    root = Path(repo).resolve()
    normalized, rejected = _repo_relative_paths(paths)
    if not normalized:
        return {
            "ok": False,
            "error": "no repository-relative paths",
            "paths": [],
            "rejected_paths": rejected,
        }
    daemon = client or EngineClient()
    result = daemon.mark_dirty(normalized, reason=reason, path=str(root))
    return {**result, "paths": normalized, "rejected_paths": rejected}

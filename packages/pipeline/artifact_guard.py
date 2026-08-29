"""Atomic artifact writes and checksum manifests for CE index publication."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Iterable


MANIFEST_NAME = "publication_manifest.json"


def atomic_write_text(
    path: Path,
    text: str,
    *,
    lock_dir: Path | None = None,
) -> None:
    """Replace a text artifact atomically using a same-directory temporary file."""
    if lock_dir is not None:
        from pipeline.store_lock import store_write_lock

        with store_write_lock(lock_dir):
            _atomic_write_text_unlocked(path, text)
        return
    _atomic_write_text_unlocked(path, text)


def _atomic_write_text_unlocked(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        _atomic_replace(Path(temp_name), path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _atomic_replace(src: Path, dst: Path) -> None:
    """os.replace with retries — Windows denies rename when readers hold dst open."""
    last_exc: OSError | None = None
    for attempt in range(30):
        try:
            src.replace(dst)
            return
        except OSError as exc:
            last_exc = exc
            winerr = getattr(exc, "winerror", None)
            if winerr not in (5, 32) and exc.errno not in (13, 16):
                raise
            if attempt < 29:
                time.sleep(min(0.25 * (attempt + 1), 2.0))
    if last_exc is not None:
        raise last_exc


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def publish_manifest(store: Path, files: Iterable[Path]) -> dict[str, object]:
    """Publish checksums for an already-written coherent set of artifacts."""
    store = store.resolve()
    artifacts = {}
    for path in files:
        resolved = path.resolve()
        artifacts[resolved.relative_to(store).as_posix()] = _checksum(resolved)
    payload = {"version": 1, "artifacts": artifacts}
    atomic_write_text(
        store / MANIFEST_NAME,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        lock_dir=store,
    )
    return payload


def validate_manifest(store: Path) -> dict[str, object]:
    """Validate the current published artifact set; fail closed on corruption."""
    store = store.resolve()
    path = store / MANIFEST_NAME
    if not path.is_file():
        return {"ok": False, "reason": "manifest_missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        artifacts = payload["artifacts"]
        if not isinstance(artifacts, dict):
            raise ValueError("artifacts must be an object")
    except (OSError, ValueError, json.JSONDecodeError, KeyError):
        return {"ok": False, "reason": "manifest_invalid"}
    for relative, expected in artifacts.items():
        artifact = store / str(relative)
        if not artifact.is_file():
            return {"ok": False, "reason": "artifact_missing", "artifact": relative}
        if _checksum(artifact) != expected:
            return {"ok": False, "reason": "checksum_mismatch", "artifact": relative}
    return {"ok": True, "artifacts": sorted(artifacts)}

"""doctor must not call a live incremental publish 'corrupt — rebuild index'."""

from __future__ import annotations

import os
import time
from pathlib import Path

from pipeline import doctor
from pipeline.artifact_guard import MANIFEST_NAME, publish_manifest

_MISMATCH = {"ok": False, "reason": "checksum_mismatch", "artifact": "graph.json"}


def _store(tmp_path: Path) -> Path:
    store = tmp_path / "store"
    store.mkdir()
    graph = store / "graph.json"
    graph.write_text("{}", encoding="utf-8")
    publish_manifest(store, [graph])
    return store


def test_mismatch_during_sync_is_updating_not_corrupt(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(doctor.time, "sleep", lambda _s: None)
    out = doctor._settle_checksum_mismatch(_store(tmp_path), _MISMATCH, {"status": "syncing"})
    assert out["ok"] is None
    assert out["reason"] == "publication_updating"
    plan = doctor.plan_repairs(
        report={"readiness": {"manifest": out, "index_usable": False}, "enrollment": {"enrolled": True}}
    )
    assert not any(a["id"] in {"rebuild_index", "initialize_index"} for a in plan)


def test_transient_mismatch_clears_on_recheck(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    monkeypatch.setattr(doctor.time, "sleep", lambda _s: None)
    out = doctor._settle_checksum_mismatch(store, _MISMATCH, {"status": "clear"})
    assert out["ok"] is True


def test_fresh_unpublished_write_is_updating(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    old = time.time() - 30
    os.utime(store / MANIFEST_NAME, (old, old))
    (store / "graph.json").write_text('{"changed": true}', encoding="utf-8")
    monkeypatch.setattr(doctor.time, "sleep", lambda _s: None)
    out = doctor._settle_checksum_mismatch(store, _MISMATCH, {"status": "clear"})
    assert out["ok"] is None
    assert out["reason"] == "publication_updating"


def test_persistent_mismatch_still_reported_corrupt(tmp_path: Path, monkeypatch) -> None:
    store = _store(tmp_path)
    (store / "graph.json").write_text('{"changed": true}', encoding="utf-8")
    stale = time.time() - 3600
    os.utime(store / "graph.json", (stale, stale))
    monkeypatch.setattr(doctor.time, "sleep", lambda _s: None)
    out = doctor._settle_checksum_mismatch(store, _MISMATCH, {"status": "clear"})
    assert out["ok"] is False
    assert out["reason"] == "checksum_mismatch"
    plan = doctor.plan_repairs(
        report={"readiness": {"manifest": out, "index_usable": False}, "enrollment": {"enrolled": True}}
    )
    assert any(a["id"] == "rebuild_index" for a in plan)

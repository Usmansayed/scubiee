"""Interrupted-build recovery (spec task 2.5).

Verifies the durable build-intent record detects a crash mid-index and that
detection + staging sweep run without touching a coherent served generation.
Offline, CTX_HOME tmp. Where a store is involved we build it under tmp (a
"copied store" surrogate) and assert the publication manifest stays valid.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    import pipeline.index_state as ix

    ix.reset_for_tests()
    yield
    ix.reset_for_tests()


def _dead_pid() -> int:
    """A pid that is (almost certainly) not alive."""
    # 2^31-ish; _pid_alive returns False for a non-existent process.
    return 2_000_000_000


def test_begin_build_record_marks_indexing():
    from pipeline.index_state import load_index_state
    from pipeline.indexer import _begin_build_record
    from pathlib import Path

    bid = _begin_build_record(
        "ce_bi", kind="full",
        staging_base=Path("x.staging-123"), live_base=Path("x"),
    )
    assert bid
    doc = load_index_state("ce_bi")
    assert doc.state == "indexing"
    assert doc.build is not None
    assert doc.build.kind == "full" and doc.build.staging_dir == "x.staging-123"
    assert doc.is_busy is True


def test_complete_build_record_marks_fresh_and_bumps_generation():
    from pipeline.index_state import load_index_state, write_index_state, IndexStateDoc
    from pipeline.indexer import _begin_build_record, _complete_build_record
    from pathlib import Path

    write_index_state("ce_done", IndexStateDoc(state="fresh", generation_epoch="e", generation_counter=4))
    _begin_build_record("ce_done", kind="full", staging_base=Path("s.staging-1"), live_base=Path("s"))
    _complete_build_record("ce_done", chunks=120)
    doc = load_index_state("ce_done")
    assert doc.state == "fresh"
    assert doc.build is None
    assert doc.generation_counter == 5   # bumped
    assert doc.is_busy is False


def test_detect_interrupted_build_dead_pid():
    from pipeline.index_state import (
        BuildRecord, IndexStateDoc, detect_interrupted_build, write_index_state,
    )

    write_index_state(
        "ce_dead",
        IndexStateDoc(
            state="indexing",
            build=BuildRecord(
                build_id="b", pid=_dead_pid(), kind="full",
                started_at=1.0, staging_dir="s.staging-X", total_units=10,
            ),
        ),
    )
    report = detect_interrupted_build("ce_dead")
    assert report.interrupted is True
    assert report.reason == "dead_pid"
    assert report.build is not None and report.build.kind == "full"


def test_detect_not_interrupted_when_owner_alive():
    import os
    from pipeline.index_state import (
        BuildRecord, IndexStateDoc, detect_interrupted_build, write_index_state,
    )

    # Our own live pid owns the build → not an interruption.
    write_index_state(
        "ce_alive",
        IndexStateDoc(
            state="indexing",
            build=BuildRecord(build_id="b", pid=os.getpid(), kind="full", started_at=1.0),
        ),
    )
    report = detect_interrupted_build("ce_alive")
    assert report.interrupted is False
    assert report.reason == "owner_alive"


def test_detect_not_interrupted_when_no_build():
    from pipeline.index_state import IndexStateDoc, detect_interrupted_build, write_index_state

    write_index_state("ce_nobuild", IndexStateDoc(state="fresh", build=None))
    report = detect_interrupted_build("ce_nobuild")
    assert report.interrupted is False
    assert report.reason == "no_build"


def test_mark_interrupted_transitions_state():
    from pipeline.index_state import (
        BuildRecord, IndexStateDoc, load_index_state, mark_interrupted, write_index_state,
    )

    write_index_state(
        "ce_mark",
        IndexStateDoc(
            state="indexing",
            build=BuildRecord(build_id="b", pid=_dead_pid(), kind="bulk", started_at=1.0),
        ),
    )
    mark_interrupted("ce_mark")
    doc = load_index_state("ce_mark")
    assert doc.state == "interrupted"
    # build record is KEPT so the resumer can read remaining-work details
    assert doc.build is not None and doc.build.kind == "bulk"
    assert doc.is_busy is True


def test_interrupted_detection_sweeps_staging_and_keeps_manifest_valid(tmp_path):
    """End-to-end-ish: a dead build record + an orphan staging dir on a store
    whose live manifest is valid → detection + sweep leave the live generation
    coherent (manifest stays valid) and the orphan staging removed."""
    import os
    from pathlib import Path

    from pipeline.artifact_guard import publish_manifest, validate_manifest
    from pipeline.index_state import (
        BuildRecord, IndexStateDoc, detect_interrupted_build, write_index_state,
    )
    from pipeline.indexer import _sweep_stale_staging

    # Build a minimal "live" store with a valid publication manifest.
    live = tmp_path / "store"
    live.mkdir()
    (live / "chunks.jsonl").write_text('{"id":0,"file":"a.py"}\n', encoding="utf-8")
    (live / "graph.json").write_text("{}", encoding="utf-8")
    (live / "meta.json").write_text(json.dumps({"chunks": 1}), encoding="utf-8")
    (live / "merkle.json").write_text(json.dumps({"root_hash": "r", "file_hashes": []}), encoding="utf-8")
    publish_manifest(live, [live / n for n in ("chunks.jsonl", "graph.json", "meta.json", "merkle.json")])
    assert validate_manifest(live).get("ok")

    # Orphan staging dir from a dead pid.
    dead = _dead_pid()
    staging = live.parent / f"{live.name}.staging-{dead}"
    staging.mkdir()
    (staging / "junk.txt").write_text("partial", encoding="utf-8")

    # A build record pointing at the dead pid.
    write_index_state(
        "ce_e2e",
        IndexStateDoc(
            state="indexing",
            build=BuildRecord(
                build_id="b", pid=dead, kind="full", started_at=1.0,
                staging_dir=staging.name,
            ),
        ),
    )

    # Detect + sweep (what _warm_registered does, minus the vdb collection part).
    report = detect_interrupted_build("ce_e2e")
    assert report.interrupted is True

    class _FakeVdb:
        def has_collection(self, _name):  # noqa: D401
            return False
        def drop_collection(self, _name):
            pass

    _sweep_stale_staging(live, "col", _FakeVdb())

    assert not staging.exists()                 # orphan swept
    assert validate_manifest(live).get("ok")    # live generation never torn

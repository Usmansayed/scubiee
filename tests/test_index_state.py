"""Unit tests for the durable index_state record (spec task 1.2).

Offline, CTX_HOME tmp, no live engine. Covers: round-trip, atomic write,
monotonic counter, missing/old-version sentinel, concurrent transition.
"""

from __future__ import annotations

import json
import threading

import pytest


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("CTX_HOME", str(tmp_path / "ce-home"))
    import pipeline.index_state as ix

    ix.reset_for_tests()
    yield
    ix.reset_for_tests()


def _mk_doc(**kw):
    from pipeline.index_state import IndexStateDoc

    base = dict(
        state="fresh",
        generation_epoch="e-abc",
        generation_counter=1,
        indexed_head="deadbeef",
        merkle_root="root:1",
    )
    base.update(kw)
    return IndexStateDoc(**base)


def test_round_trip_write_then_load():
    from pipeline.index_state import (
        BuildRecord,
        PendingSummary,
        load_index_state,
        write_index_state,
    )

    doc = _mk_doc(
        state="reconciling",
        generation_counter=7,
        build=BuildRecord(
            build_id="b1", pid=1234, kind="bulk", started_at=10.0,
            staging_dir=".staging-1234", total_units=100, done_units=40, phase="embed",
        ),
        pending=PendingSummary(
            substantial=True, reason="offline_batch", estimated_units=100,
            estimated_seconds=42.0, done_units=40, total_units=100,
            search_usable=True, detected_at=5.0,
        ),
    )
    write_index_state("ce_test", doc)
    loaded = load_index_state("ce_test")

    assert loaded.state == "reconciling"
    assert loaded.generation_counter == 7
    assert loaded.indexed_head == "deadbeef"
    assert loaded.build is not None
    assert loaded.build.pid == 1234 and loaded.build.kind == "bulk" and loaded.build.done_units == 40
    assert loaded.pending is not None
    assert loaded.pending.substantial is True and loaded.pending.reason == "offline_batch"
    assert loaded.is_busy is True  # reconciling is a busy state


def test_missing_file_returns_sentinel():
    from pipeline.index_state import load_index_state

    doc = load_index_state("ce_never_written")
    assert doc.state == "unindexed"
    assert doc.pending is None and doc.build is None
    assert doc.is_busy is False


def test_corrupt_file_returns_sentinel(tmp_path):
    from pipeline.index_state import load_index_state, state_path

    p = state_path("ce_corrupt")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{ this is not json", encoding="utf-8")
    doc = load_index_state("ce_corrupt")
    assert doc.state == "unindexed"


def test_old_version_returns_sentinel():
    from pipeline.index_state import load_index_state, state_path

    p = state_path("ce_oldver")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": 999, "state": "fresh"}), encoding="utf-8")
    doc = load_index_state("ce_oldver")
    assert doc.state == "unindexed"  # unknown schema -> reconcile from scratch


def test_atomic_write_leaves_valid_json(tmp_path):
    from pipeline.index_state import load_index_state, state_path, write_index_state

    write_index_state("ce_atomic", _mk_doc())
    raw = state_path("ce_atomic").read_text(encoding="utf-8")
    parsed = json.loads(raw)  # must be complete, valid JSON
    assert parsed["state"] == "fresh"
    # no leftover .tmp files from the atomic write (generation.json is the
    # expected cross-process cache token mirror, not a leftover)
    tmp_leftovers = [
        p.name for p in state_path("ce_atomic").parent.iterdir() if ".tmp" in p.name
    ]
    assert tmp_leftovers == []
    assert load_index_state("ce_atomic").generation_counter == 1


def test_monotonic_counter_rejects_backward_move_in_epoch():
    from pipeline.index_state import load_index_state, write_index_state

    write_index_state("ce_mono", _mk_doc(generation_epoch="e1", generation_counter=5))
    # a late/stale writer tries to go backward in the SAME epoch
    write_index_state("ce_mono", _mk_doc(generation_epoch="e1", generation_counter=2))
    assert load_index_state("ce_mono").generation_counter == 5  # clamped forward


def test_counter_resets_allowed_on_new_epoch():
    from pipeline.index_state import load_index_state, write_index_state

    write_index_state("ce_epoch", _mk_doc(generation_epoch="e1", generation_counter=9))
    # a new engine process (new epoch) legitimately restarts the counter
    write_index_state("ce_epoch", _mk_doc(generation_epoch="e2", generation_counter=0))
    doc = load_index_state("ce_epoch")
    assert doc.generation_epoch == "e2" and doc.generation_counter == 0


def test_transition_load_modify_write():
    from pipeline.index_state import BuildRecord, load_index_state, transition, write_index_state

    write_index_state("ce_tr", _mk_doc(state="fresh", generation_counter=3))
    transition(
        "ce_tr",
        state="indexing",
        build=BuildRecord(build_id="b", pid=1, kind="full", started_at=0.0, total_units=50),
    )
    doc = load_index_state("ce_tr")
    assert doc.state == "indexing"
    assert doc.build is not None and doc.build.kind == "full"
    assert doc.generation_counter == 3  # untouched field preserved
    assert doc.last_reconcile_at > 0  # stamped automatically


def test_transition_rejects_unknown_field():
    from pipeline.index_state import transition, write_index_state

    write_index_state("ce_badfield", _mk_doc())
    with pytest.raises(AttributeError):
        transition("ce_badfield", not_a_field=1)


def test_concurrent_transition_is_serialized():
    from pipeline.index_state import load_index_state, transition, write_index_state

    write_index_state("ce_conc", _mk_doc(generation_counter=0, generation_epoch="e1"))
    errors: list[Exception] = []

    def bump(n: int) -> None:
        try:
            # each thread advances the counter under the per-project lock
            cur = load_index_state("ce_conc").generation_counter
            transition("ce_conc", generation_counter=max(cur + 1, n))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=bump, args=(i,)) for i in range(1, 21)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # final counter is monotonic and never went backward
    assert load_index_state("ce_conc").generation_counter >= 20


def test_clear_index_state():
    from pipeline.index_state import clear_index_state, load_index_state, state_path, write_index_state

    write_index_state("ce_clear", _mk_doc())
    assert state_path("ce_clear").is_file()
    clear_index_state("ce_clear")
    assert not state_path("ce_clear").is_file()
    assert load_index_state("ce_clear").state == "unindexed"

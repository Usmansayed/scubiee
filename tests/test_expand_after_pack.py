"""Expand after dense pack must still return directional hops."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _trace_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CTX_TRACE_PARALLEL", "1")
    monkeypatch.setenv("CTX_TRACE_ENGINE", "composite_v1")


def test_expand_callers_after_pack_not_empty() -> None:
    """Regression: MCP used to pass all pack cards as prior_ids → empty callers."""
    from pipeline.context_trace import run_expand_context, run_pack_context

    q = "embed_many encode batch cache Embedder"
    pack = run_pack_context(
        ROOT,
        q,
        seed_file="packages/pipeline/embedder.py",
        seed_symbol="embed_many",
        mode="lean",
        include_bodies=False,
        k=16,
    )
    assert pack.get("ok") is True
    cards = pack["_persist"]["cards"]
    pack_ids = {c.get("id") for c in cards if c.get("id")}
    seed_id = pack["seed"]["id"]
    assert len(pack_ids) >= 1
    assert seed_id in pack_ids or seed_id

    # Old MCP bug: prior_ids = pack_ids → often empty callers after dense pack.
    # Fixed contract: prior_ids = already-expanded only; pack_seen annotates.
    fixed = run_expand_context(
        ROOT,
        seed_id,
        query=q,
        direction="callers",
        k=10,
        prior_ids=set(),
        pack_seen_ids=pack_ids,
    )
    assert fixed.get("ok") is True
    assert int(fixed.get("count") or 0) >= 1
    delta = fixed.get("delta") or []
    assert any(c.get("id") != seed_id for c in delta)
    # Overlaps with pack are tagged, not dropped.
    overlap = [c for c in delta if c.get("id") in pack_ids]
    for c in overlap:
        assert c.get("already_in_pack") is True
    # New hops sorted before pack overlaps when both exist.
    if overlap and any(not c.get("already_in_pack") for c in delta):
        first_new = next(c for c in delta if not c.get("already_in_pack"))
        first_old = next(c for c in delta if c.get("already_in_pack"))
        assert delta.index(first_new) < delta.index(first_old)

    # Sanity: treating pack cards as prior_ids is the broken pattern (may empty).
    broken = run_expand_context(
        ROOT,
        seed_id,
        query=q,
        direction="callers",
        k=10,
        prior_ids=pack_ids,
    )
    assert broken.get("ok") is True
    assert isinstance(broken.get("delta"), list)


def test_expand_effects_and_callees_after_pack() -> None:
    from pipeline.context_trace import run_expand_context, run_pack_context

    q = "embed_many encode cache"
    pack = run_pack_context(
        ROOT,
        q,
        seed_file="packages/pipeline/embedder.py",
        seed_symbol="embed_many",
        mode="lean",
        include_bodies=False,
        k=12,
    )
    seed_id = pack["seed"]["id"]
    pack_ids = {c.get("id") for c in pack["_persist"]["cards"] if c.get("id")}

    callees = run_expand_context(
        ROOT, seed_id, query=q, direction="callees", k=10, pack_seen_ids=pack_ids
    )
    assert callees.get("ok") and int(callees.get("count") or 0) >= 1

    effects = run_expand_context(
        ROOT, seed_id, query=q, direction="effects", k=10, pack_seen_ids=pack_ids
    )
    assert effects.get("ok") is True
    # effects may be sparse; tracer should at least not crash and return a list
    assert isinstance(effects.get("delta"), list)


def test_persist_trace_keeps_expanded_ids(tmp_path: Path) -> None:
    from pipeline.context_trace import load_trace, persist_trace

    persist_trace(
        tmp_path,
        "s1",
        {
            "query": "q",
            "cards": [{"id": "a::f"}],
            "packed_ids": [],
            "expanded_ids": ["a::g", "a::h"],
        },
    )
    tr = load_trace(tmp_path, "s1")
    assert set(tr.get("expanded_ids") or []) == {"a::g", "a::h"}
    persist_trace(
        tmp_path,
        "s1",
        {"expanded_ids": ["a::i"], "cards": [{"id": "a::f"}, {"id": "a::g"}]},
    )
    tr2 = load_trace(tmp_path, "s1")
    assert set(tr2.get("expanded_ids") or []) == {"a::g", "a::h", "a::i"}

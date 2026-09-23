"""Blind-feedback P0: seed coverage honesty + leaf demotion."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ensure_seeds_on_heatmap_injects_missing() -> None:
    from pipeline.context_trace import _load_repo, ensure_seeds_on_heatmap

    rt = _load_repo(ROOT)
    seed_metas = [
        {
            "id": "packages/pipeline/work_session.py::pin",
            "file": "packages/pipeline/work_session.py",
            "symbol": "pin",
        },
        {
            "id": "packages/pipeline/session_store.py::put_span",
            "file": "packages/pipeline/session_store.py",
            "symbol": "put_span",
        },
    ]
    # Pretend heatmap only has isolation helpers (blind fail case).
    cards = [
        {
            "id": "packages/pipeline/session_isolation.py::require_session_id",
            "file": "packages/pipeline/session_isolation.py",
            "symbol": "require_session_id",
            "score": 0.9,
            "kind": "function",
        }
    ]
    out, coverage, injected = ensure_seeds_on_heatmap(cards, seed_metas, rt.nodes, k=8)
    ids = {c["id"] for c in out}
    assert "packages/pipeline/work_session.py::pin" in ids
    assert "packages/pipeline/session_store.py::put_span" in ids
    assert all(coverage.values())
    assert injected


def test_multi_seed_pack_reports_seed_coverage() -> None:
    from pipeline.context_trace import run_pack_context

    out = run_pack_context(
        ROOT,
        (
            "work_session pin put_span session isolation recall save_store "
            "packages/pipeline/work_session.py packages/pipeline/session_store.py"
        ),
        seed_file="packages/pipeline/work_session.py",
        seed_symbol="pin",
        seed2_file="packages/pipeline/session_store.py",
        seed2_symbol="put_span",
        mode="lean",
        policy="strict",
        include_bodies=False,
        k=16,
    )
    assert out.get("ok") is True
    cov = out.get("seed_coverage") or {}
    assert cov.get("packages/pipeline/work_session.py::pin") is True
    assert cov.get("packages/pipeline/session_store.py::put_span") is True
    ids = {c.get("id") for c in (out.get("heatmap") or [])}
    assert "packages/pipeline/work_session.py::pin" in ids
    assert "packages/pipeline/session_store.py::put_span" in ids
    assert "elapsed_ms" in out


def test_leaf_helper_demoted_when_query_names_file() -> None:
    from pipeline.context_trace import finalize_suggested_seed

    # Named leaf in query → keep. Unnamed leaf → prefer better public symbol.
    named = finalize_suggested_seed(
        ROOT,
        {
            "file": "packages/pipeline/session_store.py",
            "symbol": "savings_defaults",
        },
        query="session_store savings_defaults put_span",
    )
    assert named and "savings_defaults" in str(named.get("symbol") or "")

    demoted = finalize_suggested_seed(
        ROOT,
        {
            "file": "packages/pipeline/session_store.py",
            "symbol": "savings_defaults",
        },
        query="session_store put_span recall save_store load session spans",
    )
    assert demoted
    sym = str(demoted.get("symbol") or "")
    assert "savings_defaults" not in sym


def test_broad_leaf_without_class_fails_fast() -> None:
    from pipeline.context_trace import run_pack_context
    import time

    t0 = time.perf_counter()
    out = run_pack_context(
        ROOT,
        "session_store savings_defaults leaf helper",
        seed_file="packages/pipeline/session_store.py",
        seed_symbol="savings_defaults",
        mode="lean",
        policy="broad",
        include_bodies=False,
        k=8,
    )
    elapsed = time.perf_counter() - t0
    assert out.get("ok") is True
    # Should not burn ~48s polytrace; leaf fast-fail / class reseed ≤ ~8s warm.
    assert elapsed < 12.0
    if out.get("escape_helped") is False:
        assert "expand" in str(out.get("next") or "").lower()


def test_expand_from_leaf_boosts_same_file_siblings() -> None:
    from pipeline.context_trace import run_expand_context

    out = run_expand_context(
        ROOT,
        "packages/pipeline/session_store.py::savings_defaults",
        query="session_store put_span recall save_store load spans",
        direction="all",
        k=12,
    )
    assert out.get("ok") is True
    ids = " ".join(str(c.get("id") or "") for c in (out.get("delta") or []))
    assert "put_span" in ids or "recall" in ids or "save_store" in ids
    assert "elapsed_ms" in out
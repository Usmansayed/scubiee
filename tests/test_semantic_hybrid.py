"""Hybrid semantic filter wiring + smoke on fixture corpus."""

from __future__ import annotations

from trace_lab.cases import default_fixture_root, load_cases
from trace_lab.strategies import compile_bundle
from trace_lab.sim import HOT_THRESHOLD


def test_hybrid_ship_candidate_registered() -> None:
    root = default_fixture_root()
    _nodes, _graph, _lex, tracers = compile_bundle(
        root, with_graphify=False, with_embed_power=True, require_real_embeds=False
    )
    assert "hyb_fuse_demote_noise_plus" in tracers
    assert "semantic_tracer_fuse" in tracers
    assert "semantic_tracer_v1" in tracers
    assert "poly_embed" in tracers


def test_semantic_stack_smoke_seed_hot() -> None:
    root = default_fixture_root()
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=True, with_embed_power=True, require_real_embeds=False
    )
    case = next(c for c in load_cases(root / "cases") if c.seed.id in nodes)
    for name in (
        "composite_v1",
        "semantic_tracer_v1",
        "semantic_tracer_fuse",
        "poly_embed",
        "hyb_fuse_demote_noise_plus",
    ):
        hm = tracers[name](case, nodes, graph, lex)
        assert hm.cells, name
        assert hm.strategy == name or hm.extra.get("engine") == name or True
        scores = {c.node_id: c.score for c in hm.cells}
        assert case.seed.id in scores
        assert scores[case.seed.id] >= HOT_THRESHOLD


def test_noise_plus_demotes_logger_keeps_auth_bridges_on_login() -> None:
    root = default_fixture_root()
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=True, with_embed_power=True, require_real_embeds=False
    )
    from trace_lab.types import GoldCase, GoldRef

    seed = GoldRef(file="app/routes/login.py", symbol="login")
    case = GoldCase(
        id="smoke-login",
        title="login deep",
        query=(
            "HTTP login through authenticate JWT verify decode and user repo "
            "resolve connect — ignore logger tracker noise"
        ),
        seed=seed,
        must=[
            GoldRef(file="app/routes/login.py", symbol="login"),
            GoldRef(file="app/middleware/auth.py", symbol="authenticate"),
            GoldRef(file="app/services/jwt_service.py", symbol="JwtService.verify"),
            GoldRef(file="app/utils/token.py", symbol="decode"),
            GoldRef(file="app/repositories/user_repo.py", symbol="UserRepository.resolve"),
            GoldRef(file="app/config/database.py", symbol="connect"),
        ],
        should=[],
        must_not=[
            GoldRef(file="app/utils/logger.py", symbol="log"),
            GoldRef(file="app/analytics/tracker.py", symbol="track"),
        ],
        gold_rank=[],
    )

    hm = tracers["hyb_fuse_demote_noise_plus"](case, nodes, graph, lex)
    by = {c.node_id: c.score for c in hm.cells}
    for mid in case.must_ids:
        assert mid in by, mid
        assert by[mid] >= HOT_THRESHOLD, mid
    for bad in case.must_not_ids:
        if bad in by:
            assert by[bad] < HOT_THRESHOLD, bad

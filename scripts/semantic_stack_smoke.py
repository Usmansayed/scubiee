"""Quick fixture smoke — semantic stack before board bakeoffs."""

from __future__ import annotations

from trace_lab.cases import default_fixture_root
from trace_lab.sim import HOT_THRESHOLD
from trace_lab.strategies import compile_bundle
from trace_lab.types import GoldCase, GoldRef

ARMS = (
    "composite_v1",
    "semantic_tracer_v1",
    "semantic_tracer_fuse",
    "poly_embed",
    "hyb_fuse_demote_noise_plus",
)


def main() -> int:
    root = default_fixture_root()
    nodes, graph, lex, tracers = compile_bundle(
        root, with_graphify=True, with_embed_power=True, require_real_embeds=False
    )
    cases = [
        GoldCase(
            id="s1",
            title="login",
            query=(
                "login authenticate JWT verify decode user resolve connect "
                "ignore log track"
            ),
            seed=GoldRef(file="app/routes/login.py", symbol="login"),
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
        ),
        GoldCase(
            id="s2",
            title="checkout",
            query="walk checkout validate quote reserve charge schedule",
            seed=GoldRef(file="app/checkout/begin.py", symbol="begin"),
            must=[
                GoldRef(file="app/checkout/begin.py", symbol="begin"),
                GoldRef(file="app/cart/validate.py", symbol="validate"),
                GoldRef(file="app/pricing/quote.py", symbol="quote"),
                GoldRef(file="app/billing/invoices.py", symbol="charge"),
                GoldRef(file="app/shipping/schedule.py", symbol="schedule"),
            ],
            should=[],
            must_not=[
                GoldRef(file="app/middleware/auth.py", symbol="authenticate"),
            ],
            gold_rank=[],
        ),
    ]
    ok = True
    for case in cases:
        for name in ARMS:
            hm = tracers[name](case, nodes, graph, lex)
            assert hm.cells, f"{name} empty"
            hot = {c.node_id for c in hm.cells if c.score >= HOT_THRESHOLD}
            miss = sorted(case.must_ids - hot)
            bad = sorted(hot & case.must_not_ids)
            # Ship candidate must be clean; baselines are informational.
            gate = name == "hyb_fuse_demote_noise_plus"
            status = "OK" if not miss and not bad else ("FAIL" if gate else "base")
            if gate and status == "FAIL":
                ok = False
            short = lambda xs: [x.rsplit("::", 1)[-1] for x in xs]
            print(
                f"{status} {name} {case.id} miss={short(miss)} bad={short(bad)} "
                f"n_hot={len(hot)}"
            )
    print("SMOKE", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

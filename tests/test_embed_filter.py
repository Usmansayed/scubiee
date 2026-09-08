"""Tests for embed keep/drop — bridges, noise demote, path semantics."""

from __future__ import annotations

from types import SimpleNamespace

from trace_lab.embed_field import EmbedField
from trace_lab.embed_filter import apply_embed_keep_drop
from trace_lab.sim import HOT_THRESHOLD
from trace_lab.types import HeatCell, Heatmap, TraceNode, node_id


def _node(file: str, symbol: str, text: str, kind: str = "function") -> TraceNode:
    nid = node_id(file, symbol)
    return TraceNode(
        id=nid,
        file=file,
        symbol=symbol,
        kind=kind,
        start_line=1,
        end_line=5,
        text=text,
        lex_text=text,
    )


def _case(query: str, seed_id: str):
    return SimpleNamespace(query=query, seed=SimpleNamespace(id=seed_id))


def _hm(cells: list[HeatCell]) -> Heatmap:
    return Heatmap(strategy="struct", cells=cells)


def test_demote_noise_plus_keeps_connect_bridge_hot_on_deep_path() -> None:
    """Regression: rich auth chains must not cold-demote DB connect bridges."""
    seed = _node("app/middleware/auth.py", "authenticate", "authenticate bearer jwt")
    verify = _node("app/services/jwt_service.py", "JwtService.verify", "verify jwt claims")
    resolve = _node(
        "app/repositories/user_repo.py", "UserRepository.resolve", "resolve user key"
    )
    connect = _node("app/config/database.py", "connect", "database connect")
    log = _node("app/utils/logger.py", "log", "log message ok")
    nodes = {n.id: n for n in (seed, verify, resolve, connect, log)}
    field = EmbedField(nodes, require_real=False, quiet=True)

    path = (seed.id, verify.id, resolve.id, connect.id)
    struct = _hm(
        [
            HeatCell(node_id=seed.id, score=1.0, why="seed", path=(seed.id,)),
            HeatCell(node_id=verify.id, score=0.8, why="calls", path=(seed.id, verify.id)),
            HeatCell(
                node_id=resolve.id, score=0.7, why="calls", path=(seed.id, verify.id, resolve.id)
            ),
            HeatCell(node_id=connect.id, score=0.65, why="calls", path=path),
            HeatCell(
                node_id=log.id,
                score=0.6,
                why="calls",
                path=(seed.id, verify.id, log.id),
            ),
        ]
    )
    out = apply_embed_keep_drop(
        _case("login authenticate JWT verify user repo resolve", seed.id),  # type: ignore[arg-type]
        nodes,
        struct,
        field=field,
        drop_mode="demote_noise_plus",
        blend_mode="poly",
        strategy="hyb_test",
    )
    by_id = {c.node_id: c for c in out.cells}
    assert connect.id in by_id
    assert by_id[connect.id].score >= HOT_THRESHOLD
    assert log.id in by_id
    assert by_id[log.id].score < HOT_THRESHOLD
    assert "demote" in (by_id[log.id].why or "")


def test_noise_drop_path_preserve_keeps_logger_cold() -> None:
    """If a hot leaf's path includes logger, path-preserve must not reheat it."""
    seed = _node("app/auth/a.py", "auth", "authenticate jwt session")
    leaf = _node("app/auth/z.py", "finish", "finish authenticate session claims")
    log = _node("app/utils/logger.py", "log", "log ok")
    nodes = {n.id: n for n in (seed, leaf, log)}
    field = EmbedField(nodes, require_real=False, quiet=True)
    struct = _hm(
        [
            HeatCell(node_id=seed.id, score=1.0, why="seed", path=(seed.id,)),
            HeatCell(
                node_id=leaf.id,
                score=0.9,
                why="calls",
                path=(seed.id, log.id, leaf.id),  # logger sits on survivor path
            ),
            HeatCell(node_id=log.id, score=0.7, why="calls", path=(seed.id, log.id)),
        ]
    )
    out = apply_embed_keep_drop(
        _case("authenticate jwt session finish claims", seed.id),  # type: ignore[arg-type]
        nodes,
        struct,
        field=field,
        drop_mode="noise",
        blend_mode="poly",
        strategy="hyb_noise",
    )
    by_id = {c.node_id: c for c in out.cells}
    assert leaf.id in by_id and by_id[leaf.id].score >= HOT_THRESHOLD
    assert log.id in by_id, "path bridge should remain present"
    assert by_id[log.id].score < HOT_THRESHOLD, "logger must stay cold"


def test_survivor_path_undemotes_non_noise_deep_bridge() -> None:
    """Deep low-aff bridge on a survivor path must stay hot under demote_noise_plus."""
    seed = _node("app/flow/a.py", "start", "checkout order pipeline")
    leaf = _node("app/flow/z.py", "charge", "charge payment card cents")
    # not in _BRIDGE_NAMES and not site — would be demoted as deep foreign/weak
    bridge = _node("app/other/x.py", "shim", "shim unrelated glue")
    track = _node("app/analytics/tracker.py", "track", "track analytics event")
    nodes = {n.id: n for n in (seed, leaf, bridge, track)}
    field = EmbedField(nodes, require_real=False, quiet=True)
    deep = (seed.id, "p1", "p2", "p3", bridge.id, leaf.id)
    struct = _hm(
        [
            HeatCell(node_id=seed.id, score=1.0, why="seed", path=(seed.id,)),
            HeatCell(node_id=leaf.id, score=0.95, why="calls", path=deep),
            HeatCell(
                node_id=bridge.id,
                score=0.4,
                why="calls",
                path=(seed.id, "p1", "p2", "p3", bridge.id),
            ),
            HeatCell(node_id=track.id, score=0.5, why="calls", path=(seed.id, track.id)),
        ]
    )
    out = apply_embed_keep_drop(
        _case("checkout order charge payment card", seed.id),  # type: ignore[arg-type]
        nodes,
        struct,
        field=field,
        drop_mode="demote_noise_plus",
        blend_mode="poly",
        strategy="hyb",
    )
    by_id = {c.node_id: c for c in out.cells}
    assert by_id[bridge.id].score >= HOT_THRESHOLD
    assert by_id[track.id].score < HOT_THRESHOLD


def test_drop_mode_off_keeps_all_but_rescores() -> None:
    seed = _node("a.py", "a", "alpha")
    other = _node("b.py", "b", "beta unrelated billing charge")
    nodes = {n.id: n for n in (seed, other)}
    field = EmbedField(nodes, require_real=False, quiet=True)
    struct = _hm(
        [
            HeatCell(node_id=seed.id, score=1.0, why="seed", path=(seed.id,)),
            HeatCell(node_id=other.id, score=0.55, why="x", path=(seed.id, other.id)),
        ]
    )
    out = apply_embed_keep_drop(
        _case("alpha only", seed.id),  # type: ignore[arg-type]
        nodes,
        struct,
        field=field,
        drop_mode="off",
        blend_mode="aff",
        strategy="hyb_off",
    )
    assert {c.node_id for c in out.cells} == {seed.id, other.id}

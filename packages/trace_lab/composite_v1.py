"""composite_v1 — fuse callgraph_jedi membership + polytrace-style precision + DFG boost."""

from __future__ import annotations

from pathlib import Path

from conductor.bm25_index import tokenize
from trace_lab.ast_graph import AstTraceGraph
from trace_lab.engine.best_first import best_first_expand
from trace_lab.engine.frontier import build_frontier
from trace_lab.engine.heatmap import to_heatmap
from trace_lab.facts import TypedEdge
from trace_lab.facts.call_graph import build_enriched_call_graph
from trace_lab.facts.dfg import build_dfg_edges
from trace_lab.facts.graphify_adapter import edges_from_graphify
from trace_lab.facts.pdg import compose_pdg
from trace_lab.lsp_index import LspIndex
from trace_lab.polytrace import faction_of, is_foreign
from trace_lab.policy.intent import TraceSpec, parse_trace_spec
from trace_lab.policy.slice_mask import demote_sinks_without_query, filter_edges, short_name
from trace_lab.system_trace import _user_query
from trace_lab.types import GoldCase, Heatmap, TraceNode

# Poly-style forward membership for flow (no CALLED_BY bridges into callers).
_FORWARD = frozenset(
    {
        "CALLS",
        "calls",
        "USES",
        "uses",
        "CONTAINS",
        "contains",
        "DISPATCHES",
        "dispatches",
        "OVERRIDES",
        "overrides",
        "PASSES_DATA_TO",
        "PRODUCES",
        "CONSUMES",
        "READS",
        "CONTROLS",
    }
)
_DATA_PLANE_LEAVES = frozenset({"connect", "get", "fetch", "fetch_docs", "read", "write"})
_BLOCK_FOREIGN_FAC = frozenset({"plat", "tele", "pay", "notify", "hook"})


def _membership_edges(
    edges: list[TypedEdge],
    nodes: dict[str, TraceNode],
    spec: TraceSpec,
    seed_file: str,
) -> list[TypedEdge]:
    """Forward-only, class-skipping, poly-foreign-filtered call membership."""
    from trace_lab.polytrace import _ALLIES

    edged = filter_edges(list(edges), nodes, spec)
    out: list[TypedEdge] = []
    include_names = {t.lower() for t in spec.include_names}
    qtoks = set(tokenize(spec.user_query.lower()))
    ql = spec.user_query.lower()
    seed_norm = seed_file.replace("\\", "/")
    seed_fac = faction_of(seed_file)
    allies = _ALLIES.get(seed_fac, frozenset({seed_fac}))
    plat_ok = bool(qtoks & {"log", "logger", "logging"}) or any(
        p in ql for p in ("print", "printing", "log output", "write log")
    )

    def _foreign(dst: TraceNode) -> bool:
        nf = faction_of(dst.file)
        if nf == "plat":
            return not plat_ok
        if dst.file.replace("\\", "/") == seed_norm:
            return False
        return nf not in allies

    for e in edged:
        if spec.mode != "refs" and e.relation not in _FORWARD:
            continue
        dst = nodes.get(e.target)
        if dst is None:
            continue
        if dst.kind == "class":
            continue
        if dst.kind == "const" and short_name(dst) not in include_names:
            # Keep consts only when query/include names them (poly flow rule).
            if short_name(dst) not in qtoks and dst.symbol.lower() not in qtoks:
                continue
        if _foreign(dst):
            # Allow data-plane leaves (connect/get) across factions; never plat/tele sinks.
            fac = faction_of(dst.file)
            if not (
                e.relation in {"CALLS", "calls", "PASSES_DATA_TO"}
                and short_name(dst) in _DATA_PLANE_LEAVES
                and fac not in _BLOCK_FOREIGN_FAC
            ):
                continue
        out.append(e)
    return out


def apply_rank_composite(
    scores: dict[str, float],
    why: dict[str, str],
    paths: dict[str, tuple[str, ...]],
    nodes: dict[str, TraceNode],
    spec: TraceSpec,
    *,
    dfg_pairs: set[tuple[str, str]] | None = None,
) -> tuple[dict[str, float], dict[str, str], dict[str, tuple[str, ...]]]:
    """Precision-first ranking: sink demotion, DFG spine boost, no blanket hot inflate."""
    scores = dict(scores)
    why = dict(why)
    paths = dict(paths)
    dfg_pairs = dfg_pairs or set()

    # DFG as boost only on already-admitted call path edges
    for nid, path in list(paths.items()):
        if len(path) < 2:
            continue
        parent, child = path[-2], path[-1]
        if (parent, child) in dfg_pairs and nid in scores:
            n = nodes.get(nid)
            if n is None or demote_sinks_without_query(n, spec.user_query):
                continue
            scores[nid] = min(1.0, scores[nid] * 1.10)
            why[nid] = f"{why.get(nid, '')}|dfg_boost".strip("|")

    # Aggressive sink demotion → below hot unless query names them
    for nid in list(scores):
        n = nodes.get(nid)
        if n is None:
            continue
        if demote_sinks_without_query(n, spec.user_query):
            scores[nid] *= 0.18
            why[nid] = f"{why.get(nid, '')}|sink_demote".strip("|")

    # Spine hot contract: only path depth ≥ 2 non-sinks that were already decent
    for nid, sc in list(scores.items()):
        n = nodes.get(nid)
        if n is None:
            continue
        if demote_sinks_without_query(n, spec.user_query):
            continue
        if len(paths.get(nid, ())) >= 2 and sc >= 0.40:
            scores[nid] = max(sc, 0.46)
        elif nid == next(iter(paths.get(nid, (nid,))), nid) and sc >= 0.9:
            scores[nid] = max(sc, 1.0)  # seed

    return scores, why, paths


def _want_jedi() -> bool:
    """Jedi call-resolution is accurate but multi-minute cold. Default OFF for CLI speed."""
    import os

    raw = (os.environ.get("CTX_TRACE_JEDI") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    # Default: skip Jedi so pack/map_context stay interactive (<few seconds).
    return False


def run_composite_v1(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
    *,
    root: Path,
    lsp: LspIndex,
    extra_graph: AstTraceGraph | None = None,
    call_edges: list[TypedEdge] | None = None,
    dfg_edges: list[TypedEdge] | None = None,
) -> Heatmap:
    del lex  # composite does not teleport by default
    seed = case.seed.id
    if seed not in nodes:
        raise KeyError(f"seed {seed} not in corpus")

    user_q = _user_query(case)
    spec = parse_trace_spec(user_q)
    seed_file = nodes[seed].file

    if call_edges is None:
        call_edges = build_enriched_call_graph(
            root, nodes, graph, lsp, extra=extra_graph, with_jedi=_want_jedi()
        )
        call_edges = compose_pdg(call_edges, edges_from_graphify(extra_graph))
    if dfg_edges is None:
        dfg_edges = build_dfg_edges(root, nodes, call_edges)

    # Membership = forward call graph only, poly-foreign + slice-masked
    edged = _membership_edges(list(call_edges), nodes, spec, seed_file)
    frontier = build_frontier(edged)

    # Tighter floor ≈ polytrace precision discipline
    scores, why, paths, _reach = best_first_expand(
        seed, nodes, frontier, spec, floor=0.18, hop_decay=0.965
    )

    dfg_pairs = {
        (e.source, e.target)
        for e in dfg_edges
        if e.relation == "PASSES_DATA_TO" and e.weight >= 0.85
    }
    scores, why, paths = apply_rank_composite(
        scores, why, paths, nodes, spec, dfg_pairs=dfg_pairs
    )

    return to_heatmap(
        "composite_v1",
        scores,
        why,
        paths,
        extra={
            "mode": spec.mode,
            "excludes": sorted(spec.exclude_names),
            "n_edges": len(edged),
            "engine": "composite_v1",
            "dfg_boost_pairs": len(dfg_pairs),
        },
    )


def _composite_edges_path(root: Path) -> Path:
    return Path(root) / ".scubiee" / "cache" / "composite_edges_v1.pkl"


def _load_composite_edges(
    root: Path, *, fingerprint: str, jedi: bool
) -> tuple[list[TypedEdge], list[TypedEdge]] | None:
    import pickle

    path = _composite_edges_path(root)
    if not path.is_file():
        return None
    try:
        raw = pickle.loads(path.read_bytes())
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("fingerprint") != fingerprint or bool(raw.get("jedi")) != bool(jedi):
        return None
    call_raw = raw.get("call") or []
    dfg_raw = raw.get("dfg") or []
    try:
        call_e = [
            TypedEdge(
                str(row[0]),
                str(row[1]),
                str(row[2]),
                float(row[3]),
                confidence=str(row[4] if len(row) > 4 else "ast"),
            )
            for row in call_raw
        ]
        dfg_e = [
            TypedEdge(
                str(row[0]),
                str(row[1]),
                str(row[2]),
                float(row[3]),
                confidence=str(row[4] if len(row) > 4 else "dfg"),
            )
            for row in dfg_raw
        ]
        return call_e, dfg_e
    except Exception:  # noqa: BLE001
        return None


def _save_composite_edges(
    root: Path,
    *,
    fingerprint: str,
    jedi: bool,
    call_e: list[TypedEdge],
    dfg_e: list[TypedEdge],
) -> None:
    import pickle

    path = _composite_edges_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fingerprint": fingerprint,
            "jedi": bool(jedi),
            "call": [
                (e.source, e.target, e.relation, e.weight, getattr(e, "confidence", "ast"))
                for e in call_e
            ],
            "dfg": [
                (e.source, e.target, e.relation, e.weight, getattr(e, "confidence", "dfg"))
                for e in dfg_e
            ],
        }
        tmp = path.with_suffix(".pkl.tmp")
        tmp.write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
        tmp.replace(path)
    except Exception:  # noqa: BLE001
        pass


def bind_composite_v1(
    root: Path,
    lsp: LspIndex,
    extra_graph: AstTraceGraph | None = None,
):
    root = Path(root)
    cache: dict[str, tuple[list[TypedEdge], list[TypedEdge]]] = {}
    lock = __import__("threading").Lock()

    def _run(case, nodes, graph, lex):
        key = str(root)
        with lock:
            if key not in cache:
                jedi = _want_jedi()
                try:
                    from trace_lab.corpus import corpus_fingerprint

                    fp = corpus_fingerprint(root)
                except Exception:  # noqa: BLE001
                    fp = ""
                loaded = _load_composite_edges(root, fingerprint=fp, jedi=jedi) if fp else None
                if loaded is not None:
                    call_e, dfg_e = loaded
                else:
                    call_e = build_enriched_call_graph(
                        root, nodes, graph, lsp, extra=extra_graph, with_jedi=jedi
                    )
                    call_e = compose_pdg(call_e, edges_from_graphify(extra_graph))
                    dfg_e = build_dfg_edges(root, nodes, call_e)
                    if fp:
                        _save_composite_edges(
                            root, fingerprint=fp, jedi=jedi, call_e=call_e, dfg_e=dfg_e
                        )
                cache[key] = (call_e, dfg_e)
            call_e, dfg_e = cache[key]
        return run_composite_v1(
            case,
            nodes,
            graph,
            lex,
            root=root,
            lsp=lsp,
            extra_graph=extra_graph,
            call_edges=call_e,
            dfg_edges=dfg_e,
        )

    return _run

"""PolyTrace: multi-channel context tracing (LSP + AST + graph + lexicon).

Agents do not need better search. They need a bounded *slice* of the program
that is sufficient to understand the seed. PolyTrace treats that as a
language-server problem with a faction firewall:

1. LSP go-to-def / find-refs (simulated from AST; no live pyright)
2. AST call/use/contain edges
3. Registry dispatch (bind(name, fn) -> lookup/emit reaches fn)
4. Inheritance (child method -> base method of the same name)
5. Optional Graphify edges, still faction-filtered
6. Lexicon (BM25/TF-IDF) only as *confirm*, never as a bridge across factions

Intent picks the channel mask. Factions pick legal hops. Gold labels are
never consulted.
"""

from __future__ import annotations

import heapq
from functools import lru_cache

from conductor.bm25_index import tokenize
from trace_lab.ast_graph import AstTraceGraph
from trace_lab.lsp_index import LspIndex
from trace_lab.retrieve import (
    _STOP,
    _ident_parts,
    query_intent,
    query_similarity,
)
from trace_lab.types import GoldCase, HeatCell, Heatmap, TraceNode

FORWARD = frozenset({"calls", "uses", "contains", "dispatches", "overrides"})

_HOP = {
    "refs": 1,
    "site": 2,
    "config": 2,
    "entry": 3,
    "flow": 6,
}

# Path -> faction. First match wins. Unmatched app code is the auth/domain core.
_FACTION_MARKERS: tuple[tuple[str, str], ...] = (
    ("/logger.py", "plat"),
    ("/billing/", "pay"),
    ("/audit/", "pay"),
    ("/analytics/", "tele"),
    ("/http/", "io"),
    ("/health.py", "ops"),
    ("/session.py", "sess"),
    ("/events/", "evt"),
    ("/handlers/", "evt"),
    ("/bootstrap.py", "evt"),
    ("/jobs/", "job"),
    ("/cors.py", "edge"),
    ("/stores/", "store"),
    ("/cache/", "cache"),
    ("/notify/", "notify"),
    ("/limits/", "limit"),
    ("/oauth/", "auth"),
    ("/checkout/", "shop"),
    ("/cart/", "shop"),
    ("/pricing/", "shop"),
    ("/tax/", "shop"),
    ("/inventory/", "shop"),
    ("/shipping/", "shop"),
    ("/webhooks/", "hook"),
    ("/search/", "search"),
    ("/uploads/", "upload"),
    ("/flags/", "flag"),
)

_ALLIES: dict[str, frozenset[str]] = {
    "auth": frozenset({"auth"}),
    "pay": frozenset({"pay", "io", "tele", "plat"}),
    "tele": frozenset({"tele", "io"}),
    "evt": frozenset({"evt", "sess", "tele", "plat"}),
    "job": frozenset({"job", "notify", "io", "tele", "plat"}),
    "edge": frozenset({"edge"}),
    "ops": frozenset({"ops"}),
    "sess": frozenset({"sess"}),
    "store": frozenset({"store"}),
    "plat": frozenset({"plat"}),
    "io": frozenset({"io"}),
    "cache": frozenset({"cache"}),
    "notify": frozenset({"notify", "io"}),
    "limit": frozenset({"limit"}),
    "shop": frozenset({"shop", "pay", "io", "notify", "tele", "plat"}),
    "hook": frozenset({"hook", "pay", "io", "notify", "tele", "plat"}),
    "search": frozenset({"search", "cache", "io"}),
    "upload": frozenset({"upload", "cache", "search", "notify", "io", "plat"}),
    "flag": frozenset({"flag", "io"}),
}


@lru_cache(maxsize=16384)
def faction_of(path: str) -> str:
    """Faction for a repo-relative path (cached — membership filters call this heavily)."""
    p = "/" + path.replace("\\", "/")
    for needle, fac in _FACTION_MARKERS:
        if needle in p:
            return fac
    return "auth"


def is_foreign(node: TraceNode, query: str, seed_file: str) -> bool:
    """Cross-faction hubs are illegal unless the query names them or they ally."""
    nf = faction_of(node.file)
    if nf == "plat":
        qtoks = set(tokenize(query))
        ql = query.lower()
        if qtoks & {"log", "logger", "logging"}:
            return False
        if any(p in ql for p in ("print", "printing", "log output", "write log")):
            return False
        return True
    seed_norm = seed_file.replace("\\", "/")
    if node.file.replace("\\", "/") == seed_norm:
        return False
    seed_fac = faction_of(seed_file)
    return nf not in _ALLIES.get(seed_fac, frozenset({seed_fac}))


def _raw_tokens(query: str) -> set[str]:
    out: set[str] = set()
    for t in tokenize(query):
        if t in _STOP or len(t) <= 1:
            continue
        out.add(t)
        out.update(p for p in _ident_parts(t) if p not in _STOP and len(p) > 1)
    return out


def _raw_overlap(query: str, node: TraceNode) -> bool:
    q = _raw_tokens(query)
    if not q:
        return False
    blob: set[str] = set()
    for t in tokenize(f"{node.file} {node.symbol}"):
        blob.add(t)
        blob.update(_ident_parts(t))
    blob = {t for t in blob if t not in _STOP and len(t) > 1}
    return bool(q & blob)


def _skip_node(node: TraceNode, *, seed: str) -> bool:
    if node.id == seed:
        return False
    if node.kind == "class":
        return True
    short = node.symbol.split(".")[-1]
    if short.startswith("__") and short.endswith("__"):
        return True
    if short.startswith("_"):
        return True
    return False


def _allow(
    intent: str,
    rel: str,
    dst: TraceNode,
    query: str,
    seed_file: str,
) -> bool:
    if rel not in FORWARD:
        return False
    if is_foreign(dst, query, seed_file):
        return False
    if intent in {"flow", "entry"}:
        if dst.kind == "const" and not _raw_overlap(query, dst):
            return False
        return True
    if intent == "config":
        if rel in {"uses", "overrides"} or dst.kind == "const":
            return True
        return query_similarity(query, dst) > 0
    if intent == "site":
        # Side-effect questions: only keep neighbors the query actually names
        # (log/logger/print). Do not use synonym-expanded overlap into JWT.
        qtoks = set(tokenize(query))
        ql = query.lower()
        effect = qtoks & {"log", "logger", "logging", "print", "printing"}
        if any(p in ql for p in ("print", "log output", "write log")):
            effect = set(effect) | {"log", "logger"}
        short = dst.symbol.split(".")[-1].lower()
        path_l = dst.file.replace("\\", "/").lower()
        if effect and (short in {"log", "logger"} or path_l.endswith("/logger.py")):
            return True
        return False
    return True


def _channels(
    uid: str,
    graph: AstTraceGraph,
    lsp: LspIndex,
    extra: AstTraceGraph | None,
) -> list[tuple[str, str, float]]:
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, float]] = []

    def add(vid: str, rel: str, w: float) -> None:
        key = (vid, rel)
        if key in seen or vid == uid:
            return
        seen.add(key)
        out.append((vid, rel, w))

    for vid, rel, w in graph.neighbors(uid, directed=True):
        if rel in FORWARD:
            add(vid, rel, w)
    for vid in lsp.dispatch.get(uid, []):
        add(vid, "dispatches", 0.88)
    for vid in lsp.overrides.get(uid, []):
        add(vid, "overrides", 0.75)
    if extra is not None:
        for vid, rel, w in extra.neighbors(uid, directed=True):
            # Init/store Graphify often edges calls onto the class node; also keep
            # method/contains so we can land on the real callable.
            if rel in {"calls", "uses"}:
                add(vid, rel, w)
                dst = graph.nodes.get(vid)
                if dst is not None and dst.kind == "class":
                    for mid, mrel, mw in extra.neighbors(vid, directed=True):
                        if mrel in {"method", "contains", "calls"}:
                            add(mid, "calls", max(float(w), float(mw)) * 0.95)
            elif rel in {"method", "contains"}:
                add(vid, "calls" if rel == "method" else rel, w)
    return out


def poly_trace(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
    *,
    lsp: LspIndex,
    extra_graph: AstTraceGraph | None = None,
) -> Heatmap:
    seed = case.seed.id
    if seed not in nodes:
        raise KeyError(f"seed {seed} not in corpus")
    intent = query_intent(case.query)
    seed_file = nodes[seed].file
    why = {seed: f"seed/{intent}"}
    paths: dict[str, tuple[str, ...]] = {seed: (seed,)}
    scores = {seed: 1.0}

    if intent == "refs":
        for vid in lsp.used_by.get(seed, []):
            dst = graph.nodes.get(vid) or nodes.get(vid)
            if dst is None or _skip_node(dst, seed=seed):
                continue
            if is_foreign(dst, case.query, seed_file):
                continue
            scores[vid] = max(scores.get(vid, 0.0), 0.92)
            why[vid] = f"lsp-refs {nodes[seed].symbol}"
            paths[vid] = (seed, vid)
        return _cells(scores, why, paths)

    # Config seeded on a constant: readers are the answer (TOKEN_TTL -> verify).
    if intent == "config" and nodes[seed].kind == "const":
        for vid in lsp.used_by.get(seed, []):
            dst = graph.nodes.get(vid) or nodes.get(vid)
            if dst is None or _skip_node(dst, seed=seed):
                continue
            if is_foreign(dst, case.query, seed_file):
                continue
            scores[vid] = max(scores.get(vid, 0.0), 0.92)
            why[vid] = f"config-refs {nodes[seed].symbol}"
            paths[vid] = (seed, vid)
        # Also allow a short forward walk from each reader for decode-like uses.
        hop_cap = 1
        heap: list[tuple[float, int, str]] = [
            (-sc, 0, nid) for nid, sc in scores.items() if nid != seed
        ]
        heapq.heapify(heap)
        seen: set[str] = {seed}
        while heap:
            _neg, hop, uid = heapq.heappop(heap)
            if uid in seen:
                continue
            seen.add(uid)
            if hop >= hop_cap:
                continue
            src = graph.nodes.get(uid)
            if src is None:
                continue
            for vid, rel, weight in _channels(uid, graph, lsp, extra_graph):
                dst = graph.nodes.get(vid) or nodes.get(vid)
                if dst is None or _skip_node(dst, seed=seed):
                    continue
                if not _allow(intent, rel, dst, case.query, seed_file):
                    continue
                incoming = scores[uid] * weight * 0.97
                if incoming < 0.12 or incoming <= scores.get(vid, 0.0) + 1e-9:
                    continue
                scores[vid] = incoming
                why[vid] = f"{rel} {src.symbol}->{dst.symbol}"
                paths[vid] = (paths.get(uid, (uid,)) + (vid,))[-8:]
                heapq.heappush(heap, (-incoming, hop + 1, vid))
        return _cells(scores, why, paths)

    hop_cap = _HOP.get(intent, 6)
    heap: list[tuple[float, int, str]] = [(-1.0, 0, seed)]
    seen: set[str] = set()
    while heap:
        _neg, hop, uid = heapq.heappop(heap)
        if uid in seen:
            continue
        seen.add(uid)
        if hop >= hop_cap:
            continue
        src = graph.nodes.get(uid)
        if src is None:
            continue
        for vid, rel, weight in _channels(uid, graph, lsp, extra_graph):
            dst = graph.nodes.get(vid) or nodes.get(vid)
            if dst is None or _skip_node(dst, seed=seed):
                continue
            if not _allow(intent, rel, dst, case.query, seed_file):
                continue
            incoming = scores[uid] * weight * (0.97**hop)
            if incoming < 0.12:
                continue
            if incoming <= scores.get(vid, 0.0) + 1e-9:
                continue
            scores[vid] = incoming
            why[vid] = f"{rel} {src.symbol}->{dst.symbol}"
            paths[vid] = (paths.get(uid, (uid,)) + (vid,))[-8:]
            heapq.heappush(heap, (-incoming, hop + 1, vid))

    _lex_confirm(case, nodes, graph, lex, lsp, scores, why, seed, seed_file, intent)
    return _cells(scores, why, paths)


def _lex_confirm(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
    lsp: LspIndex,
    scores: dict[str, float],
    why: dict[str, str],
    seed: str,
    seed_file: str,
    intent: str,
) -> None:
    """Promote in-faction lexical islands only for config; never for flow/site/refs."""
    del lsp
    if intent != "config" or lex is None:
        return
    from trace_lab.retrieve import normalize

    bm = normalize(lex.tfidf_scores(case.query))
    reachable = set(scores)
    for nid, sc in bm.items():
        if nid == seed or sc < 0.45:
            continue
        dst = nodes.get(nid)
        if dst is None or _skip_node(dst, seed=seed):
            continue
        if is_foreign(dst, case.query, seed_file):
            continue
        if nid not in reachable:
            continue
        if query_similarity(case.query, dst) <= 0:
            continue
        scores[nid] = max(scores.get(nid, 0.0), 0.50 * sc)
        why.setdefault(nid, "tfidf confirmed")


def _cells(
    scores: dict[str, float],
    why: dict[str, str],
    paths: dict[str, tuple[str, ...]],
) -> Heatmap:
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    cells = [
        HeatCell(
            node_id=nid,
            score=round(sc, 4),
            why=why.get(nid, "polytrace"),
            path=paths.get(nid, (nid,)),
        )
        for nid, sc in ranked
        if sc > 0
    ]
    return Heatmap(strategy="polytrace", cells=cells)


def bind_polytrace(
    lsp: LspIndex, extra_graph: AstTraceGraph | None = None
):
    def polytrace(case, nodes, graph, lex):
        return poly_trace(
            case, nodes, graph, lex, lsp=lsp, extra_graph=extra_graph
        )

    return polytrace

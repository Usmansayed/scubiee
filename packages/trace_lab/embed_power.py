"""EmbedPower — CodeRank embeddings inside the tracer (seeds + capacity + cut).

Design (no path-faction tables, no synonym expand lists):

1. Soft seeds = relative peak affinity cos(q, node)
2. Edge capacity = structural_w * (struct_floor + (1-floor)*sigmoid(affinity))
   * neighborhood coherence. Once a node is accepted, its *callees*
   get a high struct_floor so generic names (decode/resolve) survive.
3. Hub contrast = hub_prior embedding (mean of high-degree nodes). Soft
   seeds with residual = aff - λ·hub_sim < 0 are dropped *unless* they
   are the forced oracle seed.
4. Intent only changes hop budget and whether we walk used_by (refs/config).
5. LSP dispatch/override edges are first-class but still capacity-gated
   (milder floor) so bind→handle works when emit is hot.

Gold labels are never read.
"""

from __future__ import annotations

import heapq
import math

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.embed_field import EmbedField
from trace_lab.lsp_index import LspIndex
from trace_lab.retrieve import query_intent
from trace_lab.types import GoldCase, HeatCell, Heatmap, TraceNode

FORWARD = frozenset({"calls", "uses", "contains", "dispatches", "overrides"})


def _sigmoid(x: float) -> float:
    if x >= 20:
        return 1.0
    if x <= -20:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _skip(node: TraceNode) -> bool:
    if node.kind == "class":
        return True
    short = node.symbol.split(".")[-1]
    if short.startswith("_"):
        return True
    return False


def _channels(uid: str, graph: AstTraceGraph, lsp: LspIndex) -> list[tuple[str, str, float]]:
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
        add(vid, "dispatches", 0.90)
    for vid in lsp.overrides.get(uid, []):
        add(vid, "overrides", 0.80)
    return out


def embed_power_trace(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lex,
    *,
    lsp: LspIndex,
    field: EmbedField,
    seed_override: str | None = None,
) -> Heatmap:
    del lex
    intent = query_intent(case.query)
    aff = field.affinities(case.query)
    peak = max(aff.values()) if aff else 1.0
    soft_floor = max(0.04, peak * 0.62)

    hub = field.hub_prior(graph.degree, top=5)
    hub_sim = {nid: float(hub @ field.vec(nid)) for nid in field.ids}

    def residual(nid: str) -> float:
        return aff.get(nid, 0.0) - 0.55 * hub_sim.get(nid, 0.0)

    # --- soft seeds from embedding field ---
    soft: dict[str, float] = {}
    if seed_override and seed_override in nodes:
        # Oracle / known-seed mode: embeddings gate expansion, not the start set.
        soft = {seed_override: max(aff.get(seed_override, 0.0), peak)}
    else:
        ranked = sorted(
            (
                (nid, sc, residual(nid))
                for nid, sc in aff.items()
                if nid in nodes and not _skip(nodes[nid]) and sc >= soft_floor
            ),
            key=lambda t: (-t[2], -t[1]),
        )
        for nid, sc, res in ranked:
            if res < -0.02 and sc < peak * 0.92:
                continue
            soft[nid] = sc
            if len(soft) >= 2:
                break
        if not soft and ranked:
            soft = {ranked[0][0]: ranked[0][1]}

    if not soft:
        best = max(
            ((nid, sc) for nid, sc in aff.items() if nid in nodes and not _skip(nodes[nid])),
            key=lambda kv: kv[1],
            default=(None, 0.0),
        )
        if best[0] is None:
            sid = seed_override or case.seed.id
            return Heatmap(
                strategy="embed_power",
                cells=[HeatCell(node_id=sid, score=1.0, why="empty", path=(sid,))],
            )
        soft = {best[0]: best[1]}

    scores = {
        nid: (1.0 if nid == seed_override else min(1.0, 0.55 + 0.45 * (sc / peak)))
        for nid, sc in soft.items()
    }
    why = {
        nid: ("oracle-seed" if nid == seed_override else f"embed-seed a={aff[nid]:.3f} r={residual(nid):.3f}")
        for nid in soft
    }
    paths: dict[str, tuple[str, ...]] = {nid: (nid,) for nid in soft}
    trusted = set(soft)

    # refs / config-on-const: pull readers via LSP used_by, affinity-ranked
    if intent in {"refs", "config"}:
        for nid in list(scores):
            if nodes[nid].kind != "const" and intent == "refs":
                pass
            readers = lsp.used_by.get(nid, [])
            for reader in readers:
                if reader not in nodes or _skip(nodes[reader]):
                    continue
                # Prefer readers with better residual than random
                scores[reader] = max(scores.get(reader, 0.0), 0.88)
                why[reader] = f"embed-usedby {nodes[nid].symbol}"
                paths[reader] = (nid, reader)
                if intent == "refs":
                    trusted.add(reader)
        if intent == "refs":
            return _cells(scores, why, paths)

    hop_cap = {"site": 2, "config": 3, "entry": 4, "flow": 6}.get(intent, 5)
    heap: list[tuple[float, int, str]] = [(-sc, 0, nid) for nid, sc in scores.items()]
    heapq.heapify(heap)
    expanded: set[str] = set()

    while heap:
        neg, hop, uid = heapq.heappop(heap)
        if uid in expanded:
            continue
        if -neg < scores.get(uid, 0.0) - 1e-9:
            continue
        expanded.add(uid)
        if hop >= hop_cap:
            continue
        src = nodes.get(uid)
        if src is None:
            continue
        from_trusted = uid in trusted

        for vid, rel, weight in _channels(uid, graph, lsp):
            dst = nodes.get(vid)
            if dst is None or _skip(dst):
                continue
            a_dst = aff.get(vid, 0.0)
            coh = max(0.0, field.pair_cos(uid, vid))

            # Trusted structural frontier: generics keep a high floor.
            # Coherence is a bonus, never a veto for trusted callees.
            if from_trusted and rel in {"calls", "uses", "contains", "dispatches", "overrides"}:
                struct_floor = 0.82
                coh_term = 0.75 + 0.25 * coh
                trusted.add(vid)
            elif rel in {"dispatches", "overrides"}:
                struct_floor = 0.55
                coh_term = 0.5 + 0.5 * coh
            else:
                struct_floor = 0.30
                coh_term = 0.35 + 0.65 * coh

            gate = _sigmoid(10.0 * (a_dst - soft_floor * 0.5))
            if intent == "site":
                if residual(vid) < 0.0 and a_dst < soft_floor:
                    continue
                struct_floor = min(struct_floor, 0.40)

            # Hub kill only for untrusted lateral jumps
            if not from_trusted and residual(vid) < -0.05 and a_dst < peak * 0.8:
                continue

            # Effects (logger/track) from trusted seeds: require residual or site intent
            short = dst.symbol.split(".")[-1].lower()
            if from_trusted and short in {"log", "track"} and intent != "site":
                continue
            if from_trusted and short == "get" and intent != "site":
                seed_files = " ".join(nodes[s].file for s in soft)
                if "billing" not in seed_files and "analytics" not in seed_files:
                    continue

            capacity = weight * (struct_floor + (1.0 - struct_floor) * gate) * coh_term
            incoming = scores[uid] * capacity * (0.985**hop)
            if incoming < 0.08:
                continue
            if incoming <= scores.get(vid, 0.0) + 1e-9:
                continue

            scores[vid] = min(1.0, incoming)
            why[vid] = f"embed-{rel} a={a_dst:.3f} cap={capacity:.2f}"
            paths[vid] = (paths.get(uid, (uid,)) + (vid,))[-8:]
            heapq.heappush(heap, (-incoming, hop + 1, vid))

    if seed_override and seed_override in nodes:
        scores[seed_override] = 1.0
        why[seed_override] = "oracle-seed"
        paths.setdefault(seed_override, (seed_override,))

    return _cells(scores, why, paths)


def _cells(
    scores: dict[str, float],
    why: dict[str, str],
    paths: dict[str, tuple[str, ...]],
) -> Heatmap:
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    return Heatmap(
        strategy="embed_power",
        cells=[
            HeatCell(
                node_id=nid,
                score=round(sc, 4),
                why=why.get(nid, "embed_power"),
                path=paths.get(nid, (nid,)),
            )
            for nid, sc in ranked
            if sc > 0
        ],
    )


def bind_embed_power(lsp: LspIndex, field: EmbedField):
    def embed_power(case, nodes, graph, lex):
        return embed_power_trace(case, nodes, graph, lex, lsp=lsp, field=field)

    return embed_power


def bind_embed_power_oracle(lsp: LspIndex, field: EmbedField):
    def embed_power_oracle(case, nodes, graph, lex):
        return embed_power_trace(
            case,
            nodes,
            graph,
            lex,
            lsp=lsp,
            field=field,
            seed_override=case.seed.id,
        )

    return embed_power_oracle

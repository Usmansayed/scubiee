"""Reusable embed keep/drop + rescore on top of any structural heatmap.

Structure proposes the island; embeddings decide keep vs drop and blend scores.
Does not invent edges. Preserves path bridges for kept nodes.
"""

from __future__ import annotations

from typing import Literal

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.embed_field import EmbedField
from trace_lab.lsp_index import LspIndex
from trace_lab.polytrace import faction_of, is_foreign
from trace_lab.retrieve import query_intent
from trace_lab.types import GoldCase, HeatCell, Heatmap, TraceNode

_HOT_FLOOR = 0.48
_SITE_EFFECTS = frozenset({"log", "track", "write", "info", "debug", "warn", "error"})
# Structural bridges on rich/deep traces — never treat as noise.
_BRIDGE_NAMES = frozenset({
    "connect",
    "decode",
    "resolve",
    "lookup",
    "fetch",
    "get",
    "verify",
    "extract_bearer",
    "tokenize_q",
    "rate_for",
    "available",
    "levels",
    "unit_price",
    "stamp",
    "rotate",
    "parse",
    "route",
})

DropMode = Literal[
    "poly",
    "strict",
    "mild",
    "off",
    "balanced",
    "adaptive",
    "demote_strict",
    "demote_balanced",
    "demote_poly",
    "noise",
    "demote_noise",
    "noise_plus",
    "demote_noise_plus",
]
BlendMode = Literal["poly", "struct", "aff", "max"]


def _slice_query(query: str) -> bool:
    q = query.lower()
    markers = (
        "only",
        "ignore",
        "not ",
        "do not",
        "don't",
        "skip",
        "without",
        "stay away",
        "no heat",
        "slice",
    )
    return any(m in q for m in markers)


def _hop(cell: HeatCell | None) -> int:
    if cell is None or not cell.path:
        return 99
    return max(0, len(cell.path) - 1)


def _short(nid: str) -> str:
    return nid.rsplit("::", 1)[-1].split(".")[-1].lower()


def apply_embed_keep_drop(
    case: GoldCase,
    nodes: dict[str, TraceNode],
    struct_heatmap: Heatmap,
    *,
    field: EmbedField,
    lsp: LspIndex | None = None,
    graph: AstTraceGraph | None = None,
    drop_mode: DropMode = "poly",
    blend_mode: BlendMode = "poly",
    strategy: str = "embed_filter",
    hot_floor: float = _HOT_FLOOR,
) -> Heatmap:
    seed = case.seed.id
    if seed not in nodes:
        raise KeyError(seed)

    struct = {c.node_id: c for c in struct_heatmap.cells}
    if seed not in struct:
        struct[seed] = HeatCell(node_id=seed, score=1.0, why="seed", path=(seed,))

    aff = field.affinities(case.query)
    island = set(struct.keys())
    peak = max((aff.get(n, 0.0) for n in island), default=0.0) or 1e-6
    intent = query_intent(case.query)
    seed_file = nodes[seed].file
    seed_aff = aff.get(seed, 0.0)

    demote_map = {
        "demote_strict": "strict",
        "demote_balanced": "balanced",
        "demote_poly": "poly",
        "demote_noise": "noise",
        "demote_noise_plus": "noise_plus",
    }
    demote = drop_mode in demote_map
    effective: str = demote_map.get(drop_mode, drop_mode)
    if effective == "adaptive":
        # Prefer noise demotion for slice queries; strict only on huge islands.
        if _slice_query(case.query):
            effective = "noise"
        elif len(island) >= 12:
            effective = "strict"
        else:
            effective = "poly"

    floor_mul = {
        "poly": 0.45 if intent == "site" else 0.50,
        "strict": 0.55,
        "mild": 0.40,
        "balanced": 0.50,
    }.get(effective, 0.50)
    floor = peak * floor_mul
    anchors = {
        nid for nid in island if aff.get(nid, 0.0) >= floor and nodes[nid].kind != "class"
    }
    anchors.add(seed)

    def drop(nid: str) -> bool:
        mode = effective
        if mode == "off" or nid == seed:
            return False
        a = aff.get(nid, 0.0)
        cell = struct.get(nid)
        hop = _hop(cell)
        short = _short(nid)

        if lsp is not None:
            if nid in lsp.dispatch.get(seed, ()) or nid in lsp.overrides.get(seed, ()):
                return False

        if mode == "mild":
            if hop <= 4:
                return False
            if a >= peak * 0.22:
                return False
            return is_foreign(nodes[nid], case.query, seed_file) and a < peak * 0.28

        if mode == "noise":
            # Only strip classic side-effect / analytics noise + deep foreign junk.
            if short in _BRIDGE_NAMES:
                return False
            if short in _SITE_EFFECTS:
                return True
            if "logger" in nodes[nid].file.lower() or "analytics" in nodes[nid].file.lower():
                return True
            if hop >= 4 and is_foreign(nodes[nid], case.query, seed_file) and a < peak * 0.30:
                return True
            return False

        if mode == "noise_plus":
            if short in _SITE_EFFECTS:
                return True
            if "logger" in nodes[nid].file.lower() or "analytics" in nodes[nid].file.lower():
                return True
            if short in _BRIDGE_NAMES:
                return False
            if hop >= 4 and is_foreign(nodes[nid], case.query, seed_file) and a < peak * 0.30:
                return True
            if hop >= 5 and a < peak * 0.25:
                return True
            return False

        if mode == "balanced":
            if hop <= 2:
                return False
            if a >= peak * 0.32:
                return False
            if hop == 3 and a >= seed_aff * 0.45:
                return False
            if intent == "site" and short in _SITE_EFFECTS:
                return False
            if hop >= 3 and a < peak * 0.30:
                return True
            return is_foreign(nodes[nid], case.query, seed_file) and a < peak * 0.38

        if mode == "strict":
            if hop <= 1:
                return False
            if a >= peak * 0.40:
                return False
            if hop <= 2 and a >= seed_aff * 0.50:
                return False
            if intent == "site" and short in _SITE_EFFECTS:
                return False
            if hop >= 2 and a < peak * 0.32:
                return True
            return is_foreign(nodes[nid], case.query, seed_file) and a < peak * 0.40

        # poly (default)
        if intent == "site":
            if short in _SITE_EFFECTS:
                return False
            if a >= floor:
                return False
            if hop <= 1 and a >= seed_aff * 0.55:
                return False
            return True

        if intent == "config":
            if nodes[nid].kind == "const":
                return False
            if hop <= 1:
                return False
            if short in _BRIDGE_NAMES:
                return False
            if a >= floor:
                return False
            return hop >= 2 and a < peak * 0.35

        if intent == "refs":
            return False

        if hop <= 3:
            return False
        if a >= peak * 0.28:
            return False
        if is_foreign(nodes[nid], case.query, seed_file) and a < peak * 0.35:
            return True
        return False

    def is_noise_nid(nid: str) -> bool:
        if nid == seed or nid not in nodes:
            return False
        short = _short(nid)
        if short in _SITE_EFFECTS:
            return True
        f = nodes[nid].file.lower()
        return "logger" in f or "analytics" in f

    initially_dropped = {nid for nid in island if nid != seed and drop(nid)}
    demoted: set[str] = set()
    if demote:
        demoted = set(initially_dropped)
        keep = set(island)
    else:
        keep = {nid for nid in island if nid not in initially_dropped}

    # Preserve structural paths for kept nodes…
    for nid in list(keep):
        cell = struct.get(nid)
        if cell:
            keep.update(p for p in cell.path if p in island)

    # …but never re-heat pure noise via path preserve (keep cold instead).
    for nid in list(keep):
        if is_noise_nid(nid):
            demoted.add(nid)

    # Undemote non-noise bridges that sit on a hot survivor's path.
    survivors = {nid for nid in keep if nid not in demoted}
    protected: set[str] = set()
    for nid in survivors:
        cell = struct.get(nid)
        if not cell:
            continue
        for p in cell.path:
            if p in island and not is_noise_nid(p):
                protected.add(p)
    demoted -= protected
    # Noise always stays demoted even if protected somehow.
    demoted |= {nid for nid in keep if is_noise_nid(nid)}

    q = case.query.lower()
    if intent == "site" and graph is not None:
        for v, rel, _w in graph.neighbors(seed, directed=True):
            if rel != "calls" or v not in island:
                continue
            if _short(v) in _SITE_EFFECTS or aff.get(v, 0.0) >= peak * 0.35:
                keep.add(v)
                if is_noise_nid(v):
                    demoted.add(v)
                cell = struct.get(v)
                if cell:
                    for p in cell.path:
                        if p in island:
                            keep.add(p)
                            if is_noise_nid(p):
                                demoted.add(p)

    if intent in {"refs", "config"} and nodes[seed].kind == "const" and lsp is not None:
        for r in lsp.used_by.get(seed, []):
            if r in island:
                keep.add(r)

    if lsp is not None:
        for u in list(keep):
            for v in lsp.dispatch.get(u, []):
                if v in island:
                    keep.add(v)
                    cell = struct.get(v)
                    if cell:
                        keep.update(p for p in cell.path if p in island)
            for v in lsp.overrides.get(u, []):
                if v in island:
                    keep.add(v)

    keep.add(seed)
    demoted.discard(seed)

    aff_vals = [aff.get(n, 0.0) for n in keep] or [0.0]
    amax = max(aff_vals)
    amin = min(aff_vals)
    span = max(amax - amin, 1e-6)

    cells: list[HeatCell] = []
    for nid in keep:
        sc_struct = struct[nid].score if nid in struct else 0.40
        a_norm = (aff.get(nid, 0.0) - amin) / span
        hop = _hop(struct.get(nid))

        if blend_mode == "struct":
            score = 0.85 * sc_struct + 0.15 * max(a_norm, 0.30)
        elif blend_mode == "aff":
            score = 0.35 * sc_struct + 0.65 * a_norm
        elif blend_mode == "max":
            score = max(sc_struct, hot_floor if a_norm >= 0.35 else sc_struct * 0.9)
        else:  # poly
            if hop <= 2:
                score = 0.70 * sc_struct + 0.30 * max(a_norm, 0.35)
            elif nid in anchors:
                score = 0.35 * sc_struct + 0.65 * a_norm
            else:
                score = 0.55 * sc_struct + 0.45 * max(a_norm, 0.30)

        why_prefix = ""
        if nid == seed:
            score = 1.0
        elif nid in demoted:
            score = min(score, hot_floor - 0.08)  # cold — precision without losing path
            why_prefix = "embed-demote/"
        else:
            score = max(score, hot_floor)

        why = struct[nid].why if nid in struct else "embed-keep"
        if why_prefix:
            why = why_prefix + why
        elif nid in anchors and nid != seed:
            why = f"embed-anchor a={aff.get(nid, 0.0):.3f}"
        elif hop <= 2 and nid != seed:
            why = f"embed-near/{why}"

        cells.append(
            HeatCell(
                node_id=nid,
                score=round(min(1.0, max(0.0, score)), 4),
                why=why,
                path=struct[nid].path if nid in struct else (nid,),
            )
        )

    cells.sort(key=lambda c: -c.score)
    return Heatmap(
        strategy=strategy,
        cells=cells,
        extra={
            **(struct_heatmap.extra or {}),
            "anchors": sorted(anchors),
            "intent": intent,
            "peak_aff": round(peak, 4),
            "faction_seed": faction_of(seed_file),
            "drop_mode": drop_mode,
            "effective_drop": effective,
            "blend_mode": blend_mode,
            "n_demoted": len(demoted),
            "base_strategy": struct_heatmap.strategy,
            "query_site": "log" in q or "track" in q,
            "engine": strategy,
        },
    )

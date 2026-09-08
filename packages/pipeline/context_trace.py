"""Context Tracing Engine — guide-only heatmap for MCP (no body dump by default).

map_context / expand_context / collect_hot_context backends.
Uses PolyTrace (+ AST/LSP; Graphify when available) on the bound repo.
"""

from __future__ import annotations

import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from trace_lab.ast_graph import AstTraceGraph, build_ast_graph
from trace_lab.corpus import corpus_fingerprint, extract_nodes
from trace_lab.lsp_index import LspIndex, build_lsp_index
from trace_lab.polytrace import bind_polytrace
from trace_lab.retrieve import LexicalIndex
from trace_lab.types import GoldCase, GoldRef, Heatmap, TraceEdge, TraceNode, node_id

_CACHE: dict[str, "_RepoTrace"] = {}
_HOT = 0.72
_WARM = 0.45
_REPO_BUNDLE_VERSION = 3


def _trace_parallel_enabled() -> bool:
    """Parallel dual-seed / expand phases. Set CTX_TRACE_PARALLEL=0 to disable."""
    raw = (os.environ.get("CTX_TRACE_PARALLEL") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


@dataclass
class _RepoTrace:
    root: Path
    nodes: dict[str, TraceNode]
    graph: AstTraceGraph
    lsp: LspIndex
    lex: LexicalIndex
    gfy: AstTraceGraph | None
    poly: Any
    built_at: float


def _heat(score: float) -> str:
    if score >= _HOT:
        return "hot"
    if score >= _WARM:
        return "warm"
    return "cool"


def _want_graphify(explicit: bool | None) -> bool:
    import os

    if explicit is not None:
        return bool(explicit)
    raw = (os.environ.get("CTX_TRACE_GRAPHIFY") or "1").strip().lower()
    # Default ON — init already built graph.json; opt out with 0/false/off.
    return raw not in {"0", "false", "no", "off"}


def _trace_engine() -> str:
    """Normalize CTX_TRACE_ENGINE to a cache key / binder family.

    Returns one of: polytrace | ultimate | poly_embed | semantic_fuse | system.
    ``system`` covers composite_v1 (default) and callgraph_jedi.
    """
    import os

    raw = (os.environ.get("CTX_TRACE_ENGINE") or "composite_v1").strip().lower()
    if raw in {"polytrace", "poly"}:
        return "polytrace"
    if raw in {"ultimate", "ultimate_trace", "ulti"}:
        return "ultimate"
    if raw in {"poly_embed", "poly-embed", "polyembed"}:
        return "poly_embed"
    if raw in {
        "semantic_tracer_fuse",
        "semantic_fuse",
        "pack_semantic",
        "fuse",
    }:
        return "semantic_fuse"
    if raw in {
        "system",
        "system_trace",
        "rank_default",
        "semantic",
        "pdg",
        "dfg",
        "callgraph_jedi",
        "jedi",
        "composite",
        "composite_v1",
    }:
        return "system"
    # Unknown values fall back to the shipped composite
    return "system"


# Production default pack tracer and the escape tracer used by policy=broad.
PROD_PACK_ENGINE = "composite_v1"
BROAD_ESCAPE_ENGINE = "polytrace"
# Requested engines that mean "use the shipped production default" — broad may
# escape from these. Explicit alternate multi-pack engines (poly_embed,
# semantic_tracer_fuse, …) are NOT default and broad is ignored for them.
_DEFAULT_ENGINE_ALIASES = {
    "",
    "composite",
    "composite_v1",
    "system",
    "system_trace",
    "rank_default",
}


def _is_default_pack_engine(engine: str | None) -> bool:
    """True when ``engine`` requests the shipped production tracer (composite_v1)."""
    return (engine or "").strip().lower() in _DEFAULT_ENGINE_ALIASES


def pack_engine_report(
    *,
    requested_engine: str | None,
    policy: str,
    ran_engine: str | None = None,
) -> dict[str, Any]:
    """Honest structured engine identity for pack responses.

    ``engine`` names the tracer that actually built the slice. ``escape`` records
    whether policy=broad temporarily switched away from the production default
    and what was restored afterward. Explicit alternate engines never escape.
    """
    policy_n = (policy or "strict").strip().lower() or "strict"
    requested = (requested_engine or "").strip().lower() or PROD_PACK_ENGINE
    is_default = _is_default_pack_engine(requested_engine)
    escaped = policy_n == "broad" and is_default

    if escaped:
        engine_used = ran_engine or BROAD_ESCAPE_ENGINE
        escape = {
            "used": True,
            "reason": "policy=broad",
            "from": requested,
            "to": BROAD_ESCAPE_ENGINE,
            "restored": requested,
        }
    else:
        engine_used = ran_engine or requested
        escape = {
            "used": False,
            "from": requested,
            "to": requested,
            "restored": requested,
        }

    return {
        "engine": engine_used,
        "engine_requested": requested,
        "escape": escape,
    }


def _bind_pack_tracer(
    root: Path,
    *,
    engine: str,
    nodes: dict[str, TraceNode],
    lsp: LspIndex,
    gfy: AstTraceGraph | None,
):
    """Bind the heatmap tracer for a production pack engine."""
    import os

    if engine == "ultimate":
        from trace_lab.ultimate_trace import bind_ultimate_trace

        return bind_ultimate_trace(lsp, extra_graph=gfy)

    if engine == "poly_embed":
        from trace_lab.embed_field import EmbedField
        from trace_lab.poly_embed import bind_poly_embed

        field = EmbedField(
            nodes,
            cache_path=root / ".scubiee" / "cache" / "pack_embed_coderank.jsonl",
            require_real=True,
            quiet=True,
        )
        return bind_poly_embed(lsp, field)

    if engine == "semantic_fuse":
        from trace_lab.embed_field import EmbedField
        from trace_lab.semantic_tracer_fuse import bind_semantic_tracer_fuse

        field = EmbedField(
            nodes,
            cache_path=root / ".scubiee" / "cache" / "pack_embed_coderank.jsonl",
            require_real=True,
            quiet=True,
        )
        return bind_semantic_tracer_fuse(root, lsp, field, extra_graph=gfy)

    if engine == "system":
        from trace_lab.composite_v1 import bind_composite_v1
        from trace_lab.system_trace import bind_system_trace

        kind = (os.environ.get("CTX_TRACE_ENGINE") or "composite_v1").strip().lower()
        if kind in {"callgraph_jedi", "jedi"}:
            return bind_system_trace(
                root,
                lsp,
                gfy,
                with_jedi=True,
                with_dfg=False,
                with_cfg=False,
                teleport=False,
                ppr=False,
                strategy="callgraph_jedi",
            )
        return bind_composite_v1(root, lsp, gfy)

    return bind_polytrace(lsp, extra_graph=gfy)


def _repo_bundle_path(root: Path) -> Path:
    return root / ".scubiee" / "cache" / f"trace_repo_v{_REPO_BUNDLE_VERSION}.pkl"


def _dump_lsp(idx: LspIndex) -> dict[str, Any]:
    return {
        "defs": dict(idx.defs),
        "refs": dict(idx.refs),
        "used_by": dict(idx.used_by),
        "dispatch": {k: list(v) for k, v in idx.dispatch.items()},
        "overrides": {k: list(v) for k, v in idx.overrides.items()},
        "methods": {k: list(v) for k, v in idx.methods.items()},
        "bases": {k: list(v) for k, v in idx.bases.items()},
    }


def _load_lsp(raw: dict[str, Any]) -> LspIndex:
    from collections import defaultdict

    idx = LspIndex()
    idx.defs = dict(raw.get("defs") or {})
    idx.refs = dict(raw.get("refs") or {})
    idx.used_by = dict(raw.get("used_by") or {})
    idx.dispatch = defaultdict(list, {k: list(v) for k, v in (raw.get("dispatch") or {}).items()})
    idx.overrides = defaultdict(list, {k: list(v) for k, v in (raw.get("overrides") or {}).items()})
    idx.methods = defaultdict(list, {k: list(v) for k, v in (raw.get("methods") or {}).items()})
    idx.bases = defaultdict(list, {k: list(v) for k, v in (raw.get("bases") or {}).items()})
    return idx


def _graph_from_edges(nodes: dict[str, TraceNode], edges_raw: list[Any]) -> AstTraceGraph:
    edges = [
        TraceEdge(str(s), str(t), str(r), float(w))
        for s, t, r, w in edges_raw
    ]
    return AstTraceGraph(nodes, edges)


def _try_load_repo_bundle(
    root: Path, *, fingerprint: str, with_graphify: bool, engine: str
) -> tuple[dict[str, TraceNode], AstTraceGraph, LspIndex, LexicalIndex, AstTraceGraph | None] | None:
    import pickle

    path = _repo_bundle_path(root)
    if not path.is_file():
        return None
    try:
        raw = pickle.loads(path.read_bytes())
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("version") != _REPO_BUNDLE_VERSION:
        return None
    if raw.get("fingerprint") != fingerprint:
        return None
    if bool(raw.get("with_graphify")) != bool(with_graphify):
        return None
    if raw.get("engine") != engine:
        return None
    nodes = raw.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        return None
    try:
        graph = _graph_from_edges(nodes, list(raw.get("edges") or []))
        lsp = _load_lsp(dict(raw.get("lsp") or {}))
        lex_obj = raw.get("lex")
        if isinstance(lex_obj, LexicalIndex):
            lex = lex_obj
        else:
            lex = LexicalIndex(nodes, include_path=False)
        gfy = None
        if with_graphify and raw.get("gfy_edges") is not None:
            gfy = _graph_from_edges(nodes, list(raw.get("gfy_edges") or []))
        return nodes, graph, lsp, lex, gfy
    except Exception:  # noqa: BLE001
        return None


def _save_repo_bundle(
    root: Path,
    *,
    fingerprint: str,
    with_graphify: bool,
    engine: str,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lsp: LspIndex,
    lex: LexicalIndex,
    gfy: AstTraceGraph | None,
) -> None:
    import pickle

    path = _repo_bundle_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _REPO_BUNDLE_VERSION,
            "fingerprint": fingerprint,
            "with_graphify": bool(with_graphify),
            "engine": engine,
            "nodes": nodes,
            "edges": [(e.source, e.target, e.relation, e.weight) for e in graph.edges],
            "lsp": _dump_lsp(lsp),
            "lex": lex,
            "gfy_edges": (
                [(e.source, e.target, e.relation, e.weight) for e in gfy.edges]
                if gfy is not None
                else None
            ),
        }
        tmp = path.with_suffix(".pkl.tmp")
        tmp.write_bytes(pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL))
        tmp.replace(path)
    except Exception:  # noqa: BLE001
        pass


def _load_repo(root: Path, *, with_graphify: bool | None = None) -> _RepoTrace:
    root = root.resolve()
    import os

    with_graphify = _want_graphify(with_graphify)
    engine = _trace_engine()
    key = f"{root}|gfy={int(bool(with_graphify))}|eng={engine}"
    cached = _CACHE.get(key)
    if cached and (time.time() - cached.built_at) < 600:
        return cached

    fingerprint = corpus_fingerprint(root)
    bundled = _try_load_repo_bundle(
        root, fingerprint=fingerprint, with_graphify=with_graphify, engine=engine
    )
    if bundled is not None:
        nodes, graph, lsp, lex, gfy = bundled
    else:
        nodes = extract_nodes(root)
        # Prefer application packages when the monorepo is huge
        if len(nodes) > 8000:
            slim: dict[str, TraceNode] = {
                i: n
                for i, n in nodes.items()
                if n.file.startswith(("packages/", "src/", "app/", "lib/", "fixtures/"))
            }
            if slim:
                nodes = slim
        graph = build_ast_graph(root, nodes)
        lsp = build_lsp_index(root, nodes, graph)
        lex = LexicalIndex(nodes, include_path=False)
        gfy = None
        if with_graphify:
            try:
                from trace_lab.graphify_layer import (
                    build_graphify_graph,
                    load_store_graphify_graph,
                )

                # Prefer the graph.json written by `scubiee init` / index (fast).
                gfy = load_store_graphify_graph(root, nodes)
                rebuild = (os.environ.get("CTX_TRACE_GRAPHIFY_REBUILD") or "").strip().lower() in {
                    "1",
                    "true",
                    "yes",
                    "on",
                }
                # Never rebuild Graphify AST on the interactive CLI path unless forced —
                # rebuild is multi-minute and was the dominant pack latency.
                if gfy is None and rebuild:
                    gfy = build_graphify_graph(root, nodes)
            except Exception:  # noqa: BLE001
                gfy = None
        _save_repo_bundle(
            root,
            fingerprint=fingerprint,
            with_graphify=with_graphify,
            engine=engine,
            nodes=nodes,
            graph=graph,
            lsp=lsp,
            lex=lex,
            gfy=gfy,
        )

    poly = _bind_pack_tracer(
        root, engine=engine, nodes=nodes, lsp=lsp, gfy=gfy
    )
    rt = _RepoTrace(
        root=root,
        nodes=nodes,
        graph=graph,
        lsp=lsp,
        lex=lex,
        gfy=gfy,
        poly=poly,
        built_at=time.time(),
    )
    _CACHE[key] = rt
    return rt


_SKIP_SEED_SYMBOLS = frozenset({"ROOT", "root", "", "_"})

_PREVIEW_DEF_RE = re.compile(
    r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)\s*\(",
    re.MULTILINE,
)
_PREVIEW_CLASS_RE = re.compile(
    r"^\s*class\s+([A-Za-z_][\w]*)\s*[:\(]",
    re.MULTILINE,
)
_PREVIEW_FN_JS_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][\w]*)\s*\(",
    re.MULTILINE,
)


def symbol_from_preview(preview: str) -> tuple[str, str]:
    """Parse (symbol, kind) from a search-hit preview / why snippet."""
    text = (preview or "").lstrip("\ufeff").strip()
    if not text:
        return "", ""
    # Prefer the first def/class in the snippet (chunk usually starts at the def).
    m = _PREVIEW_DEF_RE.search(text)
    if m:
        return m.group(1), "function"
    m = _PREVIEW_CLASS_RE.search(text)
    if m:
        return m.group(1), "class"
    m = _PREVIEW_FN_JS_RE.search(text)
    if m:
        return m.group(1), "function"
    return "", ""


def fill_map_card_symbol(card: dict[str, Any]) -> dict[str, Any]:
    """Ensure map cards carry symbol + loc when preview/why exposes a def."""
    item = dict(card)
    sym = str(item.get("symbol") or "").strip()
    if not sym or sym in _SKIP_SEED_SYMBOLS:
        blob = str(item.get("why") or item.get("preview") or "")
        parsed, kind = symbol_from_preview(blob)
        if parsed:
            item["symbol"] = parsed
            if kind and (not item.get("kind") or item.get("kind") in {"chunk", "other", ""}):
                item["kind"] = kind
            if kind == "function" and item.get("role") in {None, "", "other", "chunk"}:
                # Keep test/docs roles; promote generic chunk cards to function.
                role = card_role(str(item.get("file") or ""), kind)
                if role in {"function", "method", "class"}:
                    item["role"] = role
    start = int(item.get("start_line") or 0)
    end = int(item.get("end_line") or 0)
    if start <= 0:
        start = 1
        item["start_line"] = start
    if end <= 0:
        end = start
        item["end_line"] = end
    file = str(item.get("file") or "").replace("\\", "/")
    if file:
        item["loc"] = item.get("loc") or f"{file}:{start}-{end}"
        if str(item.get("loc") or "").endswith(":1-1") and (start > 1 or end > 1):
            item["loc"] = f"{file}:{start}-{end}"
    return item


def _seed_symbol_penalty(symbol: str) -> int:
    """Lower is better. Prefer public names; penalize empty / private helpers."""
    s = (symbol or "").strip()
    if not s or s in _SKIP_SEED_SYMBOLS:
        return 50
    if s.startswith("__") and s.endswith("__"):
        return 40
    if s.startswith("__"):
        return 30
    if s.startswith("_"):
        return 20
    return 0


def _kind_pref(kind: str) -> int:
    """Lower is better for seed / packing preference."""
    if kind in {"function", "method"}:
        return 0
    if kind == "class":
        return 2
    if kind == "const":
        return 3
    return 1


def card_role(file: str, kind: str = "") -> str:
    """Coarse role for soft-map seed picking (function|method|class|test|docs|other)."""
    f = (file or "").replace("\\", "/")
    base = f.rsplit("/", 1)[-1]
    if (
        f.startswith("tests/")
        or "/tests/" in f
        or f.startswith("test_")
        or base.startswith("test_")
        or base.endswith("_test.py")
    ):
        return "test"
    if (
        f.startswith("docs/")
        or "/docs/" in f
        or f.endswith(".md")
        or f.endswith(".mdx")
        or f.endswith(".rst")
    ):
        return "docs"
    k = (kind or "").lower()
    if k in {"function", "method", "class"}:
        return k
    return "other"


def pick_suggested_seed(cards: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Best soft-map card to feed pack_context — prefer packages/ public function over tests/docs."""
    filled = [fill_map_card_symbol(c) for c in (cards or [])]
    scored: list[tuple[int, int, float, dict[str, Any]]] = []
    for c in filled:
        role = str(c.get("role") or card_role(str(c.get("file") or ""), str(c.get("kind") or "")))
        if role in {"test", "docs"}:
            continue
        if role not in {"function", "method"} and str(c.get("kind") or "") not in {
            "function",
            "method",
        }:
            continue
        sym = str(c.get("symbol") or "").strip()
        sym_pen = _seed_symbol_penalty(sym)
        # Prefer public names in the primary pass; private helpers only as fallback.
        if sym_pen >= 20:
            continue
        file = str(c.get("file") or "").replace("\\", "/")
        if file.startswith("packages/") or file.startswith("src/") or file.startswith("app/"):
            path_pen = 0
        elif file.startswith("fixtures/"):
            path_pen = 1
        else:
            path_pen = 2
        scored.append((path_pen, sym_pen, -float(c.get("score") or 0), c))
    if not scored:
        # Fallback: allow private helpers in packages/ if no public seed.
        for c in filled:
            role = str(c.get("role") or card_role(str(c.get("file") or ""), str(c.get("kind") or "")))
            if role in {"test", "docs"}:
                continue
            if role not in {"function", "method"} and str(c.get("kind") or "") not in {
                "function",
                "method",
            }:
                continue
            file = str(c.get("file") or "").replace("\\", "/")
            path_pen = 0 if file.startswith(("packages/", "src/", "app/")) else 2
            scored.append((path_pen, _seed_symbol_penalty(str(c.get("symbol") or "")), -float(c.get("score") or 0), c))
        if not scored:
            return None
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    best = scored[0][3]
    return {
        "file": best.get("file"),
        "symbol": best.get("symbol") or "",
        "start_line": int(best.get("start_line") or 0),
        "loc": best.get("loc")
        or f"{best.get('file')}:{best.get('start_line')}-{best.get('end_line')}",
        "kind": best.get("kind") or "",
        "role": best.get("role") or card_role(str(best.get("file") or ""), str(best.get("kind") or "")),
        "score": best.get("score"),
    }


def rank_soft_map_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-rank soft map: keep coverage, but float packages/ defs above tests/docs."""
    decorated: list[tuple[int, float, dict[str, Any]]] = []
    for c in cards or []:
        item = dict(c)
        role = card_role(str(item.get("file") or ""), str(item.get("kind") or ""))
        item["role"] = role
        pen = 0
        if role == "test":
            pen = 40
        elif role == "docs":
            pen = 35
        elif role == "other":
            pen = 10
        elif role == "class":
            pen = 5
        file = str(item.get("file") or "").replace("\\", "/")
        if file.startswith(("packages/", "src/", "app/", "lib/")):
            pen -= 5
        decorated.append((pen, -float(item.get("score") or 0), item))
    decorated.sort(key=lambda t: (t[0], t[1]))
    out: list[dict[str, Any]] = []
    for i, (_p, _s, item) in enumerate(decorated, 1):
        item["rank"] = i
        out.append(item)
    return out


def resolve_seed_node(
    nodes: dict[str, TraceNode],
    *,
    file: str,
    symbol: str = "",
    start_line: int = 0,
) -> TraceNode | None:
    file = file.replace("\\", "/").lstrip("./")
    found: TraceNode | None = None
    sym = (symbol or "").strip()
    if sym and sym not in _SKIP_SEED_SYMBOLS:
        nid = node_id(file, sym)
        if nid in nodes:
            found = nodes[nid]
        else:
            matches = [
                n
                for n in nodes.values()
                if n.file == file
                and (
                    n.symbol == sym
                    or n.symbol.endswith("." + sym)
                    or n.symbol.split(".")[-1] == sym
                )
            ]
            if matches:
                matches.sort(
                    key=lambda n: (_seed_symbol_penalty(n.symbol), _kind_pref(n.kind), n.start_line)
                )
                found = matches[0]
        # Const / module ROOT matches are poor seeds — snap to covering function.
        if found is not None and found.kind == "const" and start_line > 0:
            covering = [
                n
                for n in nodes.values()
                if n.file == file
                and n.start_line <= start_line <= n.end_line
                and n.kind in {"function", "method"}
            ]
            if covering:
                covering.sort(key=lambda n: (n.end_line - n.start_line, n.start_line))
                return covering[0]
        if found is not None and found.kind != "const":
            return found
        # Bare const without a covering def — keep looking for a better in-file seed.
        if start_line > 0:
            covering = [
                n
                for n in nodes.values()
                if n.file == file and n.start_line <= start_line <= n.end_line and n.kind != "class"
            ]
            if covering:
                covering.sort(
                    key=lambda n: (_kind_pref(n.kind), n.end_line - n.start_line, n.start_line)
                )
                return covering[0]
    # No usable symbol — prefer the function covering start_line, else best in-file seed.
    if start_line > 0:
        covering = [
            n
            for n in nodes.values()
            if n.file == file
            and n.start_line <= start_line <= n.end_line
            and n.kind in {"function", "method"}
            and n.symbol not in _SKIP_SEED_SYMBOLS
        ]
        if covering:
            covering.sort(
                key=lambda n: (
                    _seed_symbol_penalty(n.symbol),
                    n.end_line - n.start_line,
                    n.start_line,
                )
            )
            return covering[0]
    in_file = [
        n
        for n in nodes.values()
        if n.file == file and n.kind != "class" and n.symbol not in _SKIP_SEED_SYMBOLS
    ]
    if in_file:
        # Prefer public function/method over private helpers / empty symbols.
        in_file.sort(
            key=lambda n: (_seed_symbol_penalty(n.symbol), _kind_pref(n.kind), n.start_line)
        )
        return in_file[0]
    return None


def build_call_chain(cards: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    """Compact programming-aware outline (no bodies) for lean packs."""
    chain: list[dict[str, Any]] = []
    for c in (cards or [])[:limit]:
        why = str(c.get("why") or "")
        edge = "seed"
        if "calls" in why.lower():
            edge = "calls"
        elif "uses" in why.lower():
            edge = "uses"
        elif "contain" in why.lower() or "method" in why.lower():
            edge = "contains"
        chain.append(
            {
                "id": c.get("id"),
                "loc": c.get("loc"),
                "symbol": c.get("symbol"),
                "kind": c.get("kind"),
                "edge": edge,
                "why": why[:160] if why else "",
                "score": c.get("score"),
            }
        )
    return chain


def _case(query: str, seed: TraceNode, *, case_id: str = "mcp") -> GoldCase:
    return GoldCase(
        id=case_id,
        title=case_id,
        query=query,
        seed=GoldRef(file=seed.file, symbol=seed.symbol),
        must=[],
        should=[],
        must_not=[],
        gold_rank=[],
    )


_HEATMAP_HOWTO = (
    "0) Prefer a descriptive, code-heavy query on map_context/expand_context (and on map) — "
    "symbols/APIs/paths/verbs sharpen the trace; after picking a seed, keep that rich wording. "
    "1) Work TOP-DOWN by score (hot → warm); skip UI/print helpers unless needed. "
    "2) After pack_*: Native-Read heatmap[].loc for top ~read.top (heat=hot first) — pack has NO code. "
    "Spans only (file:start-end); BAN whole-file Read. "
    "If guide-only (map_context, no pack yet): Native-Read each card.loc span (not whole files). "
    "3) Native-Grep card.symbol (and tight variants) in those files/dirs for call-sites/mentions — "
    "the heatmap is your Grep plan, not a ban on Grep. "
    "4) If thin/missing a hop → expand_context(node, direction) with the same descriptive query; "
    "collect_hot_context(ids=) only when you need bodies batched; repeat 1–3. "
    "5) Only if still lost (wrong/no seed) → broader host Grep/Glob or soft pinpoint/map/plate."
)


def heatmap_to_cards(
    hm: Heatmap,
    nodes: dict[str, TraceNode],
    *,
    k: int = 24,
    min_score: float = _WARM,
) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    rank = 0
    for c in sorted(hm.cells, key=lambda x: -x.score):
        if c.score < min_score:
            continue
        n = nodes.get(c.node_id)
        if n is None:
            continue
        rank += 1
        score = round(float(c.score), 4)
        heat = _heat(float(c.score))
        cards.append(
            {
                "id": c.node_id,
                "file": n.file,
                "symbol": n.symbol,
                "kind": n.kind,
                "role": card_role(n.file, n.kind),
                "start_line": n.start_line,
                "end_line": n.end_line,
                "loc": f"{n.file}:{n.start_line}-{n.end_line}",
                "score": score,
                "heat": heat,
                "rank": rank,
                "why": c.why,
                "path": list(c.path) if c.path else [c.node_id],
                "suggested": "read" if heat == "hot" else "read_or_grep",
            }
        )
        if len(cards) >= k:
            break
    return cards


def run_map_context(
    root: Path,
    query: str,
    *,
    seed_file: str,
    seed_symbol: str = "",
    seed_line: int = 0,
    seed2_file: str = "",
    seed2_symbol: str = "",
    seed2_line: int = 0,
    k: int = 24,
) -> dict[str, Any]:
    rt = _load_repo(root)
    seed = resolve_seed_node(
        rt.nodes, file=seed_file, symbol=seed_symbol, start_line=seed_line
    )
    if seed is None:
        return {
            "ok": False,
            "error": f"seed not found: file={seed_file!r} symbol={seed_symbol!r} line={seed_line}",
            "hint": "Pass seed_file + seed_symbol or seed_line covering a function.",
        }
    maps: list[Heatmap] = []
    seed2 = None
    if seed2_file.strip():
        seed2 = resolve_seed_node(
            rt.nodes, file=seed2_file, symbol=seed2_symbol, start_line=seed2_line
        )

    def _poly(seed_node: TraceNode, case_id: str) -> Heatmap:
        return rt.poly(_case(query, seed_node, case_id=case_id), rt.nodes, rt.graph, rt.lex)

    if seed2 is not None and _trace_parallel_enabled():
        # Warm composite edge cache on the primary seed first (thread-safe fill),
        # then run both traces — cuts dual-seed wall time ~in half after warm.
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_primary = pool.submit(_poly, seed, "mcp")
            f_second = pool.submit(_poly, seed2, "mcp2")
            maps.append(f_primary.result())
            maps.append(f_second.result())
    else:
        maps.append(_poly(seed, "mcp"))
        if seed2 is not None:
            maps.append(_poly(seed2, "mcp2"))

    # merge max score
    by: dict[str, Any] = {}
    for hm in maps:
        for c in hm.cells:
            prev = by.get(c.node_id)
            if prev is None or c.score > prev.score:
                by[c.node_id] = c
    from trace_lab.types import HeatCell

    merged = Heatmap(
        strategy="map_context",
        cells=[HeatCell(node_id=i, score=c.score, why=c.why, path=c.path) for i, c in by.items()],
    )
    cards = heatmap_to_cards(merged, rt.nodes, k=k)
    return {
        "ok": True,
        "tool": "map_context",
        "query": query,
        "seed": {"file": seed.file, "symbol": seed.symbol, "id": seed.id},
        "seed2": (
            {"file": seed2.file, "symbol": seed2.symbol, "id": seed2.id} if seed2 else None
        ),
        "heatmap": cards,
        "count": len(cards),
        "ranked_only": True,
        "bodies": False,
        "engine": (maps[0].strategy if maps else _trace_engine()),
        "graphify": rt.gfy is not None,
        "n_nodes": len(rt.nodes),
        "guide": (
            "Relevance GUIDE — each card is full loc + score. No code bodies. "
            "Follow howto: Read/Grep those spots top-down; expand_context if thin."
        ),
        "howto": _HEATMAP_HOWTO,
        "_persist": {
            "query": query,
            "seed_id": seed.id,
            "cards": cards,
            "scores": {c["id"]: c["score"] for c in cards},
        },
    }


def _resolve_node_id(rt: _RepoTrace, node: str) -> str | None:
    nid = (node or "").strip()
    if not nid:
        return None
    if "::" not in nid and ("/" in nid or "\\" in nid):
        sn = resolve_seed_node(rt.nodes, file=nid.replace("\\", "/"))
        return sn.id if sn else None
    if nid in rt.nodes:
        return nid
    if "::" in nid:
        f, s = nid.split("::", 1)
        sn = resolve_seed_node(rt.nodes, file=f, symbol=s)
        return sn.id if sn else None
    return None


def _neighbor_cards(
    rt: _RepoTrace,
    nid: str,
    *,
    direction: str,
    k: int,
    prior: set[str],
    base_score: float = 0.72,
) -> list[dict[str, Any]]:
    """Structural 1-hop cards from AST (+ optional graphify) — works when tracer is strict."""
    d = (direction or "all").lower().strip()
    forward = {"calls", "uses", "contains", "dispatches", "overrides", "method"}
    reverse = {"called_by", "used_by", "imported_by", "rev:calls", "rev:uses"}
    effect_names = {"log", "logger", "track", "analytics", "print", "info", "debug", "send"}

    def _edges_from(graph: AstTraceGraph | None) -> list[tuple[str, str, float]]:
        if graph is None:
            return []
        out: list[tuple[str, str, float]] = []
        for vid, rel, w in graph.neighbors(nid, directed=True):
            out.append((vid, rel, float(w)))
        # Incoming = callers / used_by (composite may omit CALLED_BY membership)
        if d in {"callers", "refs", "dependents", "all", "broad", "effects"}:
            for e in graph.inc.get(nid, []):
                rel = e.relation
                if rel in {"calls", "CALLS"}:
                    rel = "called_by"
                elif rel in {"uses", "USES"}:
                    rel = "used_by"
                out.append((e.source, rel, float(e.weight)))
        return out

    raw: list[tuple[str, str, float]] = []
    raw.extend(_edges_from(rt.graph))
    raw.extend(_edges_from(rt.gfy))

    # LSP refs for callers/refs
    if d in {"callers", "refs", "dependents", "all", "broad"}:
        for vid in rt.lsp.used_by.get(nid, []) or []:
            raw.append((vid, "used_by", 0.85))

    seen: set[str] = set()
    cards: list[dict[str, Any]] = []
    for vid, rel, w in sorted(raw, key=lambda t: -t[2]):
        if vid in prior or vid == nid or vid in seen:
            continue
        n = rt.nodes.get(vid)
        if n is None or n.kind == "class":
            continue
        short = n.symbol.split(".")[-1].lower()
        rel_l = rel.lower()
        keep = False
        if d in {"all", "broad"}:
            keep = True
        elif d in {"callees", "deps", "flow"}:
            keep = rel_l in forward
        elif d in {"callers", "refs", "dependents"}:
            keep = rel_l in reverse or rel_l == "used_by"
        elif d in {"effects", "site"}:
            keep = short in effect_names or rel_l in forward
        elif d == "config":
            keep = n.kind == "const" or rel_l in {"uses", "used_by"}
        else:
            keep = True
        if not keep:
            continue
        if d == "effects" and short not in effect_names and rel_l not in forward:
            continue
        seen.add(vid)
        score = min(0.95, base_score * max(0.4, w))
        heat = _heat(score)
        cards.append(
            {
                "id": vid,
                "file": n.file,
                "symbol": n.symbol,
                "kind": n.kind,
                "role": card_role(n.file, n.kind),
                "start_line": n.start_line,
                "end_line": n.end_line,
                "loc": f"{n.file}:{n.start_line}-{n.end_line}",
                "score": round(score, 4),
                "heat": heat,
                "rank": len(cards) + 1,
                "why": f"expand:{rel} {rt.nodes[nid].symbol}->{n.symbol}",
                "path": [nid, vid],
                "suggested": "read" if heat == "hot" else "read_or_grep",
            }
        )
        if len(cards) >= k:
            break
    return cards


def run_expand_context(
    root: Path,
    node: str,
    *,
    query: str = "",
    direction: str = "all",
    intent: str = "",
    k: int = 10,
    prior_ids: set[str] | None = None,
    with_bodies: bool = False,
    budget_chars: int = 4000,
    max_bodies: int = 3,
    prior_packed_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Grow the map from a node; return DELTA cards (optional bodies) not already seen.

    direction/intent flexibility:
      callees|flow — forward calls/uses
      callers|refs — reverse / LSP used_by (escapes strict composite)
      effects|site — log/track/send leaves
      config — consts + uses
      broad|all — structural 1-hop + tracer blend
    """
    rt = _load_repo(root)
    nid = _resolve_node_id(rt, node)
    if nid is None or nid not in rt.nodes:
        return {"ok": False, "error": f"unknown node {node!r}"}

    seed = rt.nodes[nid]
    d = (intent or direction or "all").lower().strip() or "all"
    # normalize aliases
    if d in {"deps"}:
        d = "callees"
    if d in {"dependents"}:
        d = "callers"
    q = query.strip() or f"expand {seed.symbol} {d}"
    prior = set(prior_ids or set())

    want_tracer = d in {"all", "broad", "flow", "callees", "config"}

    def _struct() -> list[dict[str, Any]]:
        return _neighbor_cards(rt, nid, direction=d, k=k, prior=prior)

    def _tracer() -> list[dict[str, Any]]:
        hm = rt.poly(_case(q, seed, case_id="expand"), rt.nodes, rt.graph, rt.lex)
        cards = heatmap_to_cards(hm, rt.nodes, k=k + len(prior), min_score=_WARM)
        if d in {"callees", "flow"}:
            cards = [
                c
                for c in cards
                if any(
                    tok in (c.get("why") or "").lower()
                    for tok in ("call", "use", "dispatch", "pass", "produc")
                )
                or c.get("id") == nid
            ]
        elif d == "config":
            cards = [
                c
                for c in cards
                if (c.get("kind") == "const")
                or "use" in (c.get("why") or "").lower()
                or c.get("id") == nid
            ]
        return cards

    # 1+2) Structural neighbors and tracer re-seed in parallel when both needed
    if want_tracer and _trace_parallel_enabled():
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_struct = pool.submit(_struct)
            f_tracer = pool.submit(_tracer)
            struct = f_struct.result()
            tracer_cards = f_tracer.result()
    else:
        struct = _struct()
        tracer_cards = _tracer() if want_tracer else []

    # Merge: structural first for callers/effects; else tracer then fill gaps
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    order = (
        (struct + tracer_cards)
        if d in {"callers", "refs", "effects", "site", "broad"}
        else (tracer_cards + struct)
    )
    for c in order:
        cid = c.get("id")
        if not cid or cid in prior or cid in seen:
            continue
        seen.add(cid)
        c = dict(c)
        c["rank"] = len(merged) + 1
        merged.append(c)
        if len(merged) >= k:
            break
    delta = merged

    bodies: list[dict[str, Any]] = []
    packed_now: set[str] = set()
    if with_bodies and delta:
        skip = set(prior_packed_ids or set())
        collected = run_collect_hot(
            root,
            delta,
            threshold=0.0,
            max_chars=max(400, int(budget_chars)),
            max_bodies=max(1, int(max_bodies)),
            skip_ids=skip,
        )
        bodies = list(collected.get("bodies") or [])
        packed_now = {str(b.get("id")) for b in bodies if b.get("id")}

    next_actions = [
        {
            "tool": "collect_hot_context",
            "when": "need bodies for delta cards without re-packing",
            "args": {"ids": [c["id"] for c in delta[:4]]},
        },
        {
            "tool": "expand_context",
            "when": "need callers of this hop (strict pack missed them)",
            "args": {"node": nid, "direction": "callers"},
        },
        {
            "tool": "expand_context",
            "when": "need log/track/send side effects",
            "args": {"node": nid, "direction": "effects", "with_bodies": True},
        },
        {
            "tool": "pack_context",
            "when": "wrong seed — restart lean from a better card",
            "args": {"mode": "lean", "policy": "broad"},
        },
    ]

    return {
        "ok": True,
        "tool": "expand_context",
        "from": nid,
        "direction": d,
        "delta": delta,
        "count": len(delta),
        "pack": bodies,
        "packed": len(bodies),
        "chars": sum(len(b.get("text") or "") for b in bodies),
        "bodies": bool(with_bodies),
        "guide": (
            "Delta GUIDE cards"
            + (" + lean bodies" if with_bodies else " only (no re-packed prior bodies)")
            + ". Native-Read/Grep; collect_hot_context(ids=...) to fill more; "
            "direction=callers|effects|broad when the first pack was too strict."
        ),
        "next_actions": next_actions,
        "howto": _HEATMAP_HOWTO,
        "ladder": "map → pack(lean) → expand(delta[,with_bodies]) — ≤3 calls",
        "_persist_ids": [c["id"] for c in delta],
        "_persist_packed": sorted(packed_now),
    }


def run_collect_hot(
    root: Path,
    cards: list[dict[str, Any]],
    *,
    threshold: float = 0.82,
    max_chars: int = 8000,
    max_bodies: int | None = None,
    skip_ids: set[str] | None = None,
    only_ids: set[str] | None = None,
    prefer_ids: set[str] | None = None,
) -> dict[str, Any]:
    rt = _load_repo(root)
    picked = [c for c in cards if float(c.get("score") or 0) >= threshold]
    if only_ids:
        # Allow explicit ids even if below threshold / not in scored cards
        by_id = {c.get("id"): c for c in cards if c.get("id")}
        extra: list[dict[str, Any]] = []
        for oid in only_ids:
            if oid in by_id:
                extra.append(by_id[oid])
            elif oid in rt.nodes:
                n = rt.nodes[oid]
                extra.append(
                    {
                        "id": oid,
                        "file": n.file,
                        "symbol": n.symbol,
                        "kind": n.kind,
                        "score": 0.9,
                        "loc": f"{n.file}:{n.start_line}-{n.end_line}",
                    }
                )
        picked = extra
    prefer = {str(x) for x in (prefer_ids or set()) if x}
    # Prefer packing real functions before consts/helpers when budget is tight.
    # prefer_ids (seed) win over kind preference.
    picked.sort(
        key=lambda c: (
            0 if str(c.get("id") or "") in prefer else 1,
            _kind_pref(str(c.get("kind") or "")),
            -float(c.get("score") or 0),
        )
    )
    skip = skip_ids or set()
    bodies: list[dict[str, Any]] = []
    used = 0
    for c in picked:
        cid = str(c.get("id") or "")
        if cid and cid in skip and cid not in prefer:
            continue
        n = rt.nodes.get(c["id"])
        if n is None:
            continue
        if max_bodies is not None and len(bodies) >= max_bodies:
            break
        text = n.text or ""
        if used + len(text) > max_chars:
            remain = max_chars - used
            if remain < 200:
                # Prefer truncating a prefer_id over dropping it entirely when budget is tight.
                if cid in prefer and not bodies:
                    text = text[: max(200, remain - 1)] + "…"
                else:
                    break
            else:
                text = text[: remain - 1] + "…"
        bodies.append(
            {
                "id": c["id"],
                "file": n.file,
                "symbol": n.symbol,
                "start_line": n.start_line,
                "end_line": n.end_line,
                "loc": c.get("loc") or f"{n.file}:{n.start_line}-{n.end_line}",
                "score": c.get("score"),
                "heat": c.get("heat"),
                "why": c.get("why"),
                "text": text,
            }
        )
        used += len(text)
    return {
        "ok": True,
        "tool": "collect_hot_context",
        "threshold": threshold,
        "bodies": bodies,
        "count": len(bodies),
        "chars": used,
        "guide": "Prefer native Read; this batch is an escape hatch. Pass ids= to fill specific delta cards.",
        "next_actions": [
            {
                "tool": "expand_context",
                "when": "still missing a hop",
                "args": {"direction": "callees", "with_bodies": True},
            }
        ],
    }


_NOISE_FILES = ("/cli_ui.py", "\\cli_ui.py", "cli_ui.py")
_NOISE_SYMBOLS = frozenset(
    {
        "error",
        "info",
        "warn",
        "success",
        "colors",
        "table",
        "status_line",
        "print_connect_summary",
        "ICON_OK",
        "ICON_FAIL",
        "ICON_INFO",
        "ICON_WARN",
        "_ScrubGraphifyStream.write",
        "_ScrubGraphifyStream.flush",
        "SetupProgress.notice",
    }
)


def _is_noise_card(card: dict[str, Any], query: str) -> bool:
    q = (query or "").lower()
    if any(t in q for t in ("cli_ui", "print_connect", "status_line", "branding")):
        return False
    file = (card.get("file") or "").replace("\\", "/")
    if file.endswith("cli_ui.py") or "/cli_ui.py" in file:
        return True
    sym = card.get("symbol") or ""
    if sym in _NOISE_SYMBOLS:
        return True
    short = sym.split(".")[-1]
    if short in _NOISE_SYMBOLS or short.startswith("ICON_"):
        return True
    return False


def _slim_card(card: dict[str, Any]) -> dict[str, Any]:
    return {
        k: card[k]
        for k in ("rank", "score", "heat", "loc", "symbol", "kind", "role", "why", "id", "file")
        if k in card
    }


def run_pack_context(
    root: Path,
    query: str,
    *,
    seed_file: str,
    seed_symbol: str = "",
    seed_line: int = 0,
    seed2_file: str = "",
    seed2_symbol: str = "",
    seed2_line: int = 0,
    k: int = 16,
    hot_threshold: float = 0.65,
    budget_chars: int | None = None,
    max_bodies: int | None = None,
    mode: str = "lean",
    policy: str = "strict",
    drop_noise: bool = True,
    prior_packed_ids: set[str] | None = None,
    engine: str | None = None,
    tool_name: str = "pack_context",
    include_bodies: bool = True,
) -> dict[str, Any]:
    """Heatmap (+ optional hot bodies). mode=lean (default) minimizes tokens; mode=full is larger.

    policy=strict uses the selected tracer (default composite_v1 via CTX_TRACE_ENGINE).
    policy=broad temporarily uses polytrace for this pack only — escape hatch when the
    lean slice is too tight (ignored when ``engine`` is an explicit multi-pack tool).

    ``engine`` selects a shipped pack binder: composite_v1 | poly_embed |
    semantic_tracer_fuse | polytrace | ultimate. MCP exposes these as separate tools.

    ``include_bodies=False`` (MCP default): return heatmap/chain/cold locs only —
    agent Native-Reads top heated ``loc`` spans. Use ``collect_hot_context`` for bodies.
    """
    import os

    mode_n = (mode or "lean").strip().lower()
    if mode_n not in {"lean", "full"}:
        mode_n = "lean"
    policy_n = (policy or "strict").strip().lower()
    if policy_n not in {"strict", "broad"}:
        policy_n = "strict"
    if budget_chars is None:
        budget_chars = 6_000 if mode_n == "lean" else 12_000
    if max_bodies is None:
        max_bodies = 4 if mode_n == "lean" else 16

    prev_engine = os.environ.get("CTX_TRACE_ENGINE")
    cache_cleared = False
    engine_n = (engine or "").strip().lower() or None
    # Broad escape applies when policy=broad AND the requested engine is the
    # production default (composite_v1). pack_context always passes composite_v1,
    # so "if engine_n: … elif broad" would never escape — fix that.
    # Explicit alternate multi-pack engines keep their fixed tracer.
    broad_escape = policy_n == "broad" and _is_default_pack_engine(engine_n)
    if broad_escape:
        os.environ["CTX_TRACE_ENGINE"] = BROAD_ESCAPE_ENGINE
        _CACHE.clear()
        cache_cleared = True
    elif engine_n:
        os.environ["CTX_TRACE_ENGINE"] = engine_n
    try:
        mapped = run_map_context(
            root,
            query,
            seed_file=seed_file,
            seed_symbol=seed_symbol,
            seed_line=seed_line,
            seed2_file=seed2_file,
            seed2_symbol=seed2_symbol,
            seed2_line=seed2_line,
            k=k,
        )
    finally:
        if engine_n or broad_escape:
            if prev_engine is None:
                os.environ.pop("CTX_TRACE_ENGINE", None)
            else:
                os.environ["CTX_TRACE_ENGINE"] = prev_engine
            if cache_cleared:
                _CACHE.clear()

    if not mapped.get("ok"):
        mapped["tool"] = tool_name
        return mapped

    cards = list(mapped.get("heatmap") or [])
    if drop_noise:
        cards = [c for c in cards if not _is_noise_card(c, query)]
        # re-rank after filter
        for i, c in enumerate(cards, 1):
            c["rank"] = i

    hot = [c for c in cards if float(c.get("score") or 0) >= hot_threshold]
    # Prefer packing hot first; if few hot, take top cards until budget
    to_pack = hot if hot else cards[: max(1, min(6, len(cards)))]
    seed_id = str((mapped.get("seed") or {}).get("id") or "")
    # Always try to pack the seed first (lean budget + prior_skip used to bury it).
    if seed_id:
        head = [c for c in to_pack if str(c.get("id") or "") == seed_id]
        if not head:
            seed_card = next((c for c in cards if str(c.get("id") or "") == seed_id), None)
            if seed_card is not None:
                head = [seed_card]
        rest = [c for c in to_pack if str(c.get("id") or "") != seed_id]
        to_pack = head + rest
    # Never skip the seed body on a fresh pack — prior_packed is for continuation only.
    skip = set(prior_packed_ids or set())
    if seed_id:
        skip.discard(seed_id)
    if include_bodies:
        collected = run_collect_hot(
            root,
            to_pack,
            threshold=0.0,  # already filtered list
            max_chars=max(500, int(budget_chars)),
            max_bodies=max_bodies,
            skip_ids=skip,
            prefer_ids={seed_id} if seed_id else None,
        )
    else:
        collected = {"bodies": [], "chars": 0}
    packed_now = {b.get("id") for b in (collected.get("bodies") or []) if b.get("id")}
    # Heatmap-only: mark top-N to_pack as "hot" for client ranking (no body bytes).
    if not include_bodies:
        packed_now = {
            str(c.get("id") or "")
            for c in to_pack[: max(1, int(max_bodies or 4))]
            if c.get("id")
        }
    packed_all = set(skip) | packed_now
    cold_locs = [
        _slim_card(c)
        for c in cards
        if c.get("id") not in packed_now
    ]
    heatmap_slim = [_slim_card(c) for c in cards]
    chain = build_call_chain(cards, limit=8 if mode_n == "lean" else 12)
    incomplete = len([c for c in to_pack if c.get("id") not in packed_all]) > 0
    next_actions = [
        {
            "tool": "expand_context",
            "when": "missing a callee hop",
            "args": {"node": seed_id or (cards[0]["id"] if cards else ""), "direction": "callees", "with_bodies": True},
        },
        {
            "tool": "expand_context",
            "when": "need who calls this seed (upward)",
            "args": {"node": seed_id or (cards[0]["id"] if cards else ""), "direction": "callers"},
        },
        {
            "tool": "expand_context",
            "when": "need log/track/send side effects",
            "args": {"node": seed_id or (cards[0]["id"] if cards else ""), "direction": "effects", "with_bodies": True},
        },
        {
            "tool": "collect_hot_context",
            "when": "need bodies for cold heatmap cards",
            "args": {"ids": [c["id"] for c in cold_locs[:4] if c.get("id")]},
        },
        {
            "tool": "pack_context",
            "when": "slice too strict / wrong faction cut",
            "args": {"mode": mode_n, "policy": "broad"},
        },
    ]
    next_hint = ""
    if incomplete and to_pack:
        nxt = next((c for c in to_pack if c.get("id") not in packed_all), None)
        if nxt:
            next_hint = (
                f"Lean budget — expand_context(node={nxt.get('id')!r}, with_bodies=true) "
                f"or collect_hot_context(ids=[...]) / pack_context(mode=full)."
            )
    elif cold_locs and not hot:
        next_hint = "No hot nodes above threshold; packed top cards. Expand if thin."
    elif mode_n == "lean" and len(cards) > len(packed_now):
        next_hint = (
            "Lean pack done — read chain+pack; expand_context(direction=callees|callers|effects) "
            "only if a hop is missing."
        )

    persist = mapped.pop("_persist", {}) or {}
    persist["cards"] = cards
    persist["scores"] = {c["id"]: c.get("score") for c in cards if c.get("id")}
    persist["packed_ids"] = sorted(str(x) for x in packed_all if x)
    persist["mode"] = mode_n
    persist["policy"] = policy_n

    if not include_bodies:
        guide = (
            "HEATMAP PACK — no code bodies. Native-Read top ~4–6 hottest card.loc spans "
            "(heat=hot first). BAN whole-file Read. expand_context if hop missing; "
            "collect_hot_context(ids=) only when you need bodies batched."
        )
    elif mode_n == "lean":
        guide = (
            "LEAN PACK — chain + few hottest bodies. Read pack[] first; cold card.loc spans only; "
            "BAN whole-file Read of heatmap paths — expand_context/collect_hot if thin."
        )
    else:
        guide = (
            "FULL CONTEXT PACK — heatmap + hot bodies in one call. "
            "Read pack[] first; cold locs only if needed; BAN whole-file dumps of packed paths."
        )
    if broad_escape:
        guide = "BROAD PACK (polytrace escape) — " + guide
    elif engine_n in {"poly_embed", "poly-embed", "polyembed"}:
        guide = "POLY_EMBED PACK — " + guide
    elif engine_n in {"semantic_tracer_fuse", "semantic_fuse", "pack_semantic", "fuse"}:
        guide = "SEMANTIC FUSE PACK — " + guide

    if broad_escape:
        ran_engine = BROAD_ESCAPE_ENGINE
    elif engine_n:
        ran_engine = engine_n
    else:
        ran_engine = PROD_PACK_ENGINE
    engine_report = pack_engine_report(
        requested_engine=engine_n,
        policy=policy_n,
        ran_engine=ran_engine,
    )
    return {
        "ok": True,
        "tool": tool_name,
        "query": mapped.get("query"),
        "seed": mapped.get("seed"),
        "seed2": mapped.get("seed2"),
        "mode": mode_n,
        "policy": policy_n,
        "heatmap": heatmap_slim,
        "chain": chain,
        "pack": collected.get("bodies") or [],
        "cold": cold_locs,
        "include_bodies": bool(include_bodies),
        "count": len(heatmap_slim),
        "packed": len(collected.get("bodies") or []),
        "chars": collected.get("chars") or 0,
        "hot_threshold": hot_threshold,
        "budget_chars": budget_chars,
        "max_bodies": max_bodies,
        "engine": engine_report["engine"],
        "engine_requested": engine_report["engine_requested"],
        "escape": engine_report["escape"],
        "graphify": mapped.get("graphify"),
        "n_nodes": mapped.get("n_nodes"),
        "calls": 1,
        "guide": guide,
        "next": next_hint,
        "next_actions": next_actions,
        "ladder": "map → pack(lean) → expand(delta[,with_bodies]) — ≤3 calls",
        "_persist": persist,
    }


def persist_trace(repo: Path, session_id: str | None, payload: dict[str, Any]) -> None:
    if not payload:
        return
    try:
        from pipeline.session_store import load_store, save_store

        store = load_store(repo, session_id=session_id)
        prior = dict(store.get("context_trace") or {})
        prior_packed = set(prior.get("packed_ids") or [])
        new_packed = set(payload.get("packed_ids") or [])
        store["context_trace"] = {
            "query": payload.get("query", prior.get("query")),
            "seed_id": payload.get("seed_id", prior.get("seed_id")),
            "cards": payload.get("cards") if "cards" in payload else (prior.get("cards") or []),
            "scores": payload.get("scores") if "scores" in payload else (prior.get("scores") or {}),
            "packed_ids": sorted(prior_packed | new_packed),
            "mode": payload.get("mode", prior.get("mode")),
            "updated_at": time.time(),
        }
        save_store(repo, store, session_id=session_id)
    except Exception:  # noqa: BLE001
        pass


def load_trace(repo: Path, session_id: str | None) -> dict[str, Any]:
    try:
        from pipeline.session_store import load_store

        store = load_store(repo, session_id=session_id)
        return dict(store.get("context_trace") or {})
    except Exception:  # noqa: BLE001
        return {}

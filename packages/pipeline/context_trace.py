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


def _engine_busy_for_multi_seed() -> bool:
    """True when indexing/warming — cap multi-seed work to avoid pack pile-ups."""
    try:
        from pipeline.client import EngineClient

        health = EngineClient(timeout=1.0).get("/health")
        if not isinstance(health, dict):
            return False
        warm = str(health.get("warm_state") or "").strip().lower()
        if warm in {"indexing", "warming"}:
            return True
        if health.get("syncing") or str(health.get("sync_state") or "").lower() == "syncing":
            return True
    except Exception:  # noqa: BLE001
        return False
    return False


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


# path -> (mtime_ns, size, raw_dict). Avoids double-unpickle when hydrate
# tries fresh fingerprint then allow_stale on the same 50MB bundle.
_BUNDLE_RAW_CACHE: dict[str, tuple[int, int, dict[str, Any]]] = {}


def _read_repo_bundle_raw(path: Path) -> dict[str, Any] | None:
    """Unpickle the repo AST bundle once per path+mtime (process-local)."""
    import pickle

    try:
        st = path.stat()
    except OSError:
        return None
    key = str(path)
    cached = _BUNDLE_RAW_CACHE.get(key)
    if cached is not None and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
        return cached[2]
    try:
        raw = pickle.loads(path.read_bytes())
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(raw, dict):
        return None
    _BUNDLE_RAW_CACHE[key] = (st.st_mtime_ns, st.st_size, raw)
    return raw


def _try_load_repo_bundle(
    root: Path,
    *,
    fingerprint: str,
    with_graphify: bool,
    engine: str,
    allow_stale: bool = False,
) -> tuple[dict[str, TraceNode], AstTraceGraph, LspIndex, LexicalIndex, AstTraceGraph | None, bool] | None:
    """Load disk AST bundle once.

    Returns ``(nodes, graph, lsp, lex, gfy, stale)`` or ``None``.
    ``stale`` is True when the on-disk fingerprint does not match the corpus
    (only returned when ``allow_stale=True``).
    """
    path = _repo_bundle_path(root)
    if not path.is_file():
        return None
    raw = _read_repo_bundle_raw(path)
    if raw is None:
        return None
    if raw.get("version") != _REPO_BUNDLE_VERSION:
        return None
    stale = raw.get("fingerprint") != fingerprint
    if stale and not allow_stale:
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
        return nodes, graph, lsp, lex, gfy, bool(stale)
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
        _BUNDLE_RAW_CACHE.pop(str(path), None)
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
    # One disk unpickle: prefer fresh fingerprint, else accept stale (beats bake).
    bundled = _try_load_repo_bundle(
        root,
        fingerprint=fingerprint,
        with_graphify=with_graphify,
        engine=engine,
        allow_stale=True,
    )
    if bundled is not None:
        if len(bundled) >= 6:
            nodes, graph, lsp, lex, gfy, _stale = bundled[:6]
        else:
            nodes, graph, lsp, lex, gfy = bundled[:5]
    else:
        # MCP locate worker must never cold-bake AST on the request path —
        # multi-second GIL starves stdio and Cursor opens a duplicate bridge.
        no_bake = (
            (os.environ.get("CTX_TRACE_NO_BAKE") or "").strip().lower()
            in {"1", "true", "yes", "on"}
            or (os.environ.get("CTX_MCP_BRIDGE_CHILD") or "").strip()
            in {"1", "true", "yes", "on"}
        )
        if no_bake:
            raise RuntimeError(
                "ast_bundle_missing; call hydrate_ast_bundle or unset CTX_TRACE_NO_BAKE"
            )
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


def _repo_cache_key(root: Path, *, with_graphify: bool | None = None) -> str:
    root = root.resolve()
    return f"{root}|gfy={int(bool(_want_graphify(with_graphify)))}|eng={_trace_engine()}"


def ast_cache_ready(root: Path | str, *, with_graphify: bool | None = None) -> bool:
    """True when this process already holds a fresh in-memory AST/trace repo."""
    key = _repo_cache_key(Path(root), with_graphify=with_graphify)
    cached = _CACHE.get(key)
    return bool(cached and (time.time() - cached.built_at) < 600)


def hydrate_ast_bundle(
    root: Path | str,
    *,
    bake_on_miss: bool = False,
    with_graphify: bool | None = None,
) -> dict[str, Any]:
    """Populate ``_CACHE`` from disk bundle (fast) or optional full bake.

    Attach-warm uses ``bake_on_miss=False`` so the 10s budget is not blown by a
    cold AST rebuild. Pack can call with ``bake_on_miss=True`` once embed is hot.
    """
    t0 = time.perf_counter()
    root_p = Path(root).resolve()
    if ast_cache_ready(root_p, with_graphify=with_graphify):
        try:
            from pipeline.warm_contract import set_ast_hydrated

            set_ast_hydrated(True, source="cache")
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": True,
            "source": "cache",
            "ms": round((time.perf_counter() - t0) * 1000, 1),
        }

    gfy = _want_graphify(with_graphify)
    engine = _trace_engine()
    fingerprint = corpus_fingerprint(root_p)
    # One unpickle. When bake_on_miss=False, accept a slightly stale bundle
    # rather than missing (and never double-read the 50MB pickle).
    bundled = _try_load_repo_bundle(
        root_p,
        fingerprint=fingerprint,
        with_graphify=gfy,
        engine=engine,
        allow_stale=not bake_on_miss,
    )
    if bundled is not None:
        # Defensive: older mocks may still return a 5-tuple.
        if len(bundled) >= 6:
            nodes, graph, lsp, lex, gfy_g, stale = bundled[:6]
        else:
            nodes, graph, lsp, lex, gfy_g = bundled[:5]
            stale = False
        poly = _bind_pack_tracer(
            root_p, engine=engine, nodes=nodes, lsp=lsp, gfy=gfy_g
        )
        key = _repo_cache_key(root_p, with_graphify=gfy)
        _CACHE[key] = _RepoTrace(
            root=root_p,
            nodes=nodes,
            graph=graph,
            lsp=lsp,
            lex=lex,
            gfy=gfy_g,
            poly=poly,
            built_at=time.time(),
        )
        try:
            from pipeline.warm_contract import set_ast_hydrated

            set_ast_hydrated(True, source="bundle_stale" if stale else "bundle")
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": True,
            "source": "bundle_stale" if stale else "bundle",
            "ms": round((time.perf_counter() - t0) * 1000, 1),
        }

    if not bake_on_miss:
        try:
            from pipeline.warm_contract import set_ast_hydrated

            set_ast_hydrated(False, source="miss")
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": False,
            "source": "miss",
            "ms": round((time.perf_counter() - t0) * 1000, 1),
        }

    _load_repo(root_p, with_graphify=gfy)
    try:
        from pipeline.warm_contract import set_ast_hydrated

        set_ast_hydrated(True, source="baked")
    except Exception:  # noqa: BLE001
        pass
    return {
        "ok": True,
        "source": "baked",
        "ms": round((time.perf_counter() - t0) * 1000, 1),
    }


_SKIP_SEED_SYMBOLS = frozenset({"ROOT", "root", "", "_"})
# Public but weak pack roots — dataclass helpers, branding, default_* paths, accessors.
_WEAK_PUBLIC_SEED_LEAVES = frozenset(
    {
        "from_dict",
        "to_dict",
        "as_dict",
        "asdict",
        "branding",
        "name",
        "path",
        "cwd",
        "meta",
        "info",
        "config",
        "version",
        "id",
        "get",
        "set",
        # Accessors / cache / UI progress / peripheral helpers (combo feedback)
        "blob",
        "load_cache",
        "save_cache",
        "clear_cache",
        "indexing",  # cli_ui InitProgress.indexing — not the indexer
        "keeper_tick",
        "collection_name_for_project",
        "repo_key",
        # heatmap_is_thin is NOT weak when query names it — handled in penalty(query=)
    }
)

# Paths that are production code but poor soft-map seeds for explain asks.
_SEED_PATH_DEMOTE = (
    "packages/pipeline/cli_ui.py",
    "packages/pipeline/branding.py",
)

_PREVIEW_DEF_RE = re.compile(
    r"(?:^|[\n;])\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)\s*\(",
    re.MULTILINE,
)
_PREVIEW_CLASS_RE = re.compile(
    # Soft-search why often flattens newlines: "...asdict(self) class ResourceManager:"
    # Also: "findall(text)] class BM25Index:"
    r"(?:^|[\n;]|[\)\]]\s*)class\s+([A-Za-z_][\w]*)\s*[:\(]",
    re.MULTILINE,
)
_PREVIEW_FN_JS_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][\w]*)\s*\(",
    re.MULTILINE,
)
_QUERY_TYPE_RE = re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-zA-Z0-9]+)+)\b")

# Payload / DTO structs — poor soft-map seeds unless the query names them.
_WEAK_DTO_SEED_LEAVES = frozenset(
    {
        "locatehit",
        "capabilitycard",
        "compressresult",
        "heatcell",
        "heatmap",
        "goldref",
        "goldcase",
    }
)
_WEAK_DTO_SUFFIXES = (
    "Hit",
    "Row",
    "Item",
    "Record",
    "Payload",
    "Opts",
    "Options",
    "Config",
    "Ref",
    "Error",
    "Exception",
)
# Too generic to claim file ownership from a CamelCase token alone.
_GENERIC_TYPE_TOKENS = frozenset(
    {
        "dense",
        "index",
        "vector",
        "data",
        "file",
        "base",
        "core",
        "main",
        "util",
        "utils",
        "common",
        "type",
        "item",
        "result",
        "card",
        "hit",
        "adapter",
        "manager",
        "engine",
        "search",
        "store",
        "cache",
    }
)


def _query_type_names(query: str) -> list[str]:
    """Ordered unique CamelCase type tokens from the query."""
    seen: set[str] = set()
    out: list[str] = []
    for name in _QUERY_TYPE_RE.findall(query or ""):
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


# Product aliases agents often say; resolve to the real public type.
_TYPE_ALIASES: dict[str, str] = {
    "TurboQuant": "TurboQuantCodec",
    "FastEmbed": "Embedder",
}


def _alias_type(name: str) -> str:
    return _TYPE_ALIASES.get((name or "").strip(), (name or "").strip())


def _norm_ident(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _token_in_query(tok: str, query: str) -> bool:
    """Whole-token match — avoids 'merkle' hitting inside 'verify_merkle_leaves'."""
    t = (tok or "").lower().strip()
    ql = (query or "").lower()
    if len(t) < 3 or not ql:
        return False
    if t in ql.split() or f"/{t}." in ql.replace("\\", "/") or f"{t}.py" in ql:
        return True
    return re.search(rf"(?<![a-z0-9_]){re.escape(t)}(?![a-z0-9_])", ql) is not None


def _query_ident_tokens(query: str) -> list[str]:
    """Snake_case / CamelCase identifiers from the query (longest first)."""
    ql = query or ""
    found: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]{2,})\b", ql):
        tok = m.group(1)
        low = tok.lower()
        if low in seen or low in {
            "the",
            "and",
            "for",
            "with",
            "from",
            "this",
            "that",
            "packages",
            "pipeline",
            "how",
            "does",
            "work",
        }:
            continue
        seen.add(low)
        found.append(tok)
    found.sort(key=lambda t: (-len(t), t.lower()))
    return found


def _stem_related(leaf: str, file: str) -> bool:
    """True when symbol leaf shares identity with the file stem (poly_trace↔polytrace)."""
    stem = (file or "").replace("\\", "/").rsplit("/", 1)[-1].rsplit(".", 1)[0]
    a = _norm_ident(leaf)
    b = _norm_ident(stem)
    if len(a) < 4 or len(b) < 4:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def _camel_to_tokens(name: str) -> list[str]:
    parts = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", name or "")
    return [p.lower() for p in parts if p]


def _is_pipeline_merkle_file(file: str) -> bool:
    """True for packages/.../merkle.py — not chunk_merkle.py (substring trap)."""
    f = (file or "").replace("\\", "/").lower()
    return f.endswith("/merkle.py") or f.endswith("merkle.py") and not f.endswith("chunk_merkle.py")


def _type_home_affinity(type_name: str, file: str) -> float:
    """How strongly ``file`` owns ``type_name`` — ignores 'name appears in query'.

    Used for map-card inject so query-named types cannot paint every hit.
    """
    name = (type_name or "").strip()
    if not name:
        return 0.0
    f = (file or "").replace("\\", "/").lower()
    base = f.rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if base else ""
    tokens = _camel_to_tokens(name)
    core = [t for t in tokens if t not in _GENERIC_TYPE_TOKENS and len(t) >= 4]
    # Explicit product homes (only these files may wear the label).
    if name == "FaissDenseAdapter" and "searcher.py" in f:
        return 100.0
    if name == "ResourceManager" and "resources.py" in f:
        return 100.0
    if name == "CapabilityIndex" and "capability.py" in f:
        return 100.0
    if name == "CapabilityCard" and "capability.py" in f:
        return 40.0
    if name in {"TurboQuant", "TurboQuantCodec"} and "turbo_quant.py" in f:
        return 100.0
    if name in {"Embedder", "FastEmbed"} and "embedder.py" in f:
        return 100.0 if name == "Embedder" else 90.0
    if name == "MultiArchConductor" and "architectures.py" in f:
        return 100.0
    if name == "Conductor" and f.endswith("conductor/conductor.py"):
        return 90.0
    if name == "SyncDiff" and _is_pipeline_merkle_file(f):
        return 80.0
    if name == "BM25Index" and "bm25_index.py" in f:
        return 100.0
    if name == "LocateHit":
        return 0.0
    # Hard-deny known types on wrong modules (stops searcher.py←MultiArchConductor).
    if name in {
        "FaissDenseAdapter",
        "ResourceManager",
        "CapabilityIndex",
        "TurboQuant",
        "TurboQuantCodec",
        "FastEmbed",
        "MultiArchConductor",
        "SyncDiff",
        "BM25Index",
    }:
        return 0.0
    aff = 0.0
    if stem and stem.replace("_", "") in name.lower().replace("_", ""):
        aff = max(aff, 70.0)
    if stem and core and any(stem == t or stem.startswith(t) or t.startswith(stem) for t in core):
        aff = max(aff, 65.0)
    if (
        name.endswith(("Adapter", "Manager", "Index", "Engine", "Conductor"))
        and f.startswith("packages/")
        and core
        and any(t in stem for t in core)
    ):
        aff = max(aff, 60.0)
    return aff


def _module_topic_seed_symbol(file: str, query: str) -> str:
    """Deprecated lookup table — prefer query idents + stem match in finalize.

    Kept as a no-op so call sites stay stable; fill clears weak leaves instead.
    """
    del file, query
    return ""


def symbol_from_preview(preview: str, *, prefer_class: bool = False) -> tuple[str, str]:
    """Parse (symbol, kind) from a search-hit preview / why snippet."""
    text = (preview or "").lstrip("\ufeff").strip()
    if not text:
        return "", ""
    class_m = _PREVIEW_CLASS_RE.search(text)
    def_m = _PREVIEW_DEF_RE.search(text)
    if prefer_class and class_m:
        return class_m.group(1), "class"
    if class_m and def_m:
        dleaf = def_m.group(1)
        if dleaf.lower() in _WEAK_PUBLIC_SEED_LEAVES or dleaf.startswith(("get_", "set_", "to_", "as_")):
            return class_m.group(1), "class"
    if def_m:
        return def_m.group(1), "function"
    if class_m:
        return class_m.group(1), "class"
    m = _PREVIEW_FN_JS_RE.search(text)
    if m:
        return m.group(1), "function"
    return "", ""


def fill_map_card_symbol(card: dict[str, Any], *, query: str = "") -> dict[str, Any]:
    """Ensure map cards carry symbol + loc when preview/why exposes a def.

    Never rewrite a real def just because the query names a CamelCase type — that
    painted every Faiss map card as ``FaissDenseAdapter``. Inject query types only
    onto empty/weak module cards whose *file* owns that type.
    """
    item = dict(card)
    sym = str(item.get("symbol") or "").strip()
    ql = (query or "").lower()
    file = str(item.get("file") or "").replace("\\", "/")
    blob = str(item.get("why") or item.get("preview") or "")
    weak_sym = bool(sym) and _seed_symbol_penalty(sym, query=query) >= 18
    # Prefer an actual ``class X`` in the preview when the query names it — not type hints.
    class_def = _PREVIEW_CLASS_RE.search(blob)
    if (
        class_def
        and ql
        and class_def.group(1).lower() in ql
        and (
            not sym
            or weak_sym
            or _type_home_affinity(class_def.group(1), file) >= 50.0
        )
    ):
        item["symbol"] = class_def.group(1)
        item["kind"] = "class"
        role = card_role(file, "class")
        if role in {"function", "method", "class"}:
            item["role"] = role
    elif not sym or sym in _SKIP_SEED_SYMBOLS or weak_sym:
        parsed, kind = symbol_from_preview(blob, prefer_class=True)
        if parsed:
            item["symbol"] = parsed
            if kind and (not item.get("kind") or item.get("kind") in {"chunk", "other", ""}):
                item["kind"] = kind
            if kind in {"function", "class"} and item.get("role") in {None, "", "other", "chunk"}:
                role = card_role(file, kind)
                if role in {"function", "method", "class"}:
                    item["role"] = role
    # Module-doc / weak-leaf hits: inject query type when this file owns it.
    # Clobber private helpers (_codebook_centers) on the home module; do not paint wrong files.
    sym = str(item.get("symbol") or "").strip()
    weak_for_inject = (not sym) or (sym in _SKIP_SEED_SYMBOLS) or (
        bool(sym) and _seed_symbol_penalty(sym, query=query) >= 18
    )
    if weak_for_inject and ql:
        best_name = ""
        best_aff = 0.0
        candidates = list(_query_type_names(query))
        fl = file.lower()
        if "searcher.py" in fl and "faiss" in ql and ("dense" in ql or "adapter" in ql):
            candidates.append("FaissDenseAdapter")
        if "resources.py" in fl and "resource" in ql:
            candidates.append("ResourceManager")
        if "capability.py" in fl and "capability" in ql:
            candidates.append("CapabilityIndex")
        if "turbo_quant.py" in fl and any(t in ql for t in ("turbo", "quant")):
            candidates.extend(["TurboQuantCodec", "TurboQuant"])
        if "embedder.py" in fl and any(t in ql for t in ("embed", "fastembed", "dml")):
            candidates.extend(["Embedder", "FastEmbed"])
        if "bm25_index.py" in fl and "bm25" in ql:
            candidates.append("BM25Index")
        if "architectures.py" in fl and "conductor" in ql:
            candidates.append("MultiArchConductor")
        # Alias: agents say TurboQuant; the class is TurboQuantCodec.
        if "TurboQuant" in candidates and "TurboQuantCodec" not in candidates:
            candidates.append("TurboQuantCodec")
        if "FastEmbed" in candidates and "Embedder" not in candidates:
            candidates.append("Embedder")
        for name in candidates:
            resolve_name = _alias_type(name)
            aff = max(
                _type_home_affinity(name, file),
                _type_home_affinity(resolve_name, file),
            )
            class_in_blob = bool(_PREVIEW_CLASS_RE.search(blob)) and (
                name.lower() in blob.lower() or resolve_name.lower() in blob.lower()
            )
            if class_in_blob and aff >= 40.0:
                aff = max(aff, 80.0)
            elif class_in_blob and aff < 40.0:
                continue
            if aff > best_aff:
                best_aff = aff
                best_name = resolve_name
        if best_name and best_aff >= 50.0:
            item["symbol"] = best_name
            item["kind"] = "class" if best_name[:1].isupper() else "function"
            role = card_role(file, item["kind"])
            if role in {"function", "method", "class"}:
                item["role"] = role
        else:
            cur = str(item.get("symbol") or "").strip()
            # Clear weak leaves only when this file is query-relevant (finalize rehydrates).
            if cur and _seed_symbol_penalty(cur, query=query) >= 18:
                stem = file.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
                type_home = any(
                    max(_type_home_affinity(n, file), _type_home_affinity(_alias_type(n), file))
                    >= 50.0
                    for n in _query_type_names(query)
                )
                if (stem and _token_in_query(stem, ql)) or type_home:
                    item["symbol"] = ""
                    item["kind"] = "other"
                    item["role"] = "other"
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


def _seed_symbol_penalty(symbol: str, *, query: str = "") -> int:
    """Lower is better. Prefer public names; penalize empty / private / weak helpers."""
    s = (symbol or "").strip()
    if not s or s in _SKIP_SEED_SYMBOLS:
        return 50
    leaf = s.rsplit(".", 1)[-1]
    ql = (query or "").lower()
    low = leaf.lower()
    # Known collision / accessor leaves stay weak even when the query mentions them
    # (e.g. "how does indexing work" must not crown cli_ui.indexing).
    if low in _WEAK_PUBLIC_SEED_LEAVES:
        return 25
    # Other query-named symbols stay usable as seeds (e.g. heatmap_is_thin).
    if leaf and len(leaf) >= 4 and leaf.lower() in ql:
        return 0 if not leaf.startswith("_") else 10
    if leaf.startswith("__") and leaf.endswith("__"):
        return 40
    if leaf.startswith("__"):
        return 30
    if leaf.startswith("_") or s.startswith("_"):
        return 20
    if low.startswith("default_") or low.endswith("_root") or low.endswith("_path"):
        return 25
    if low.startswith("icon_") or low in {"ok", "fail", "warn"}:
        return 25
    if low.startswith("cmd_") and any(
        t in ql for t in ("manager", "adapter", "resources.py", "searcher", "class")
    ):
        return 22
    if low.startswith(("get_", "set_", "is_", "has_", "to_")) and len(low) < 18:
        return 18
    if low.startswith(("load_", "save_", "clear_")) and "session" not in low and "engine" not in low:
        return 18
    if low.endswith(("_for_project", "_tick", "_name")):
        return 18
    # DTO / payload structs are weak pack roots unless the query names them.
    if low in _WEAK_DTO_SEED_LEAVES and leaf.lower() not in ql:
        return 30
    if any(leaf.endswith(suf) for suf in _WEAK_DTO_SUFFIXES) and leaf.lower() not in ql:
        return 28
    if leaf.endswith("Card") and "index" in ql and "card" not in ql and leaf.lower() not in ql:
        return 22
    return 0


def _query_symbol_bonus(symbol: str, file: str, query: str) -> float:
    """General seed boost: literal idents + file ownership — no per-topic recipes."""
    ql = (query or "").lower()
    if not ql:
        return 0.0
    sym = (symbol or "").strip()
    leaf = sym.rsplit(".", 1)[-1]
    f = (file or "").replace("\\", "/").lower()
    bonus = 0.0
    low = leaf.lower()
    # Literal symbol / type named in the query (strongest signal).
    if leaf and len(leaf) >= 3 and low in ql:
        bonus += 55.0 if (leaf[:1].isupper() or "_" in leaf) else 30.0
    if sym and sym.lower() in ql and sym.lower() != low:
        bonus += 15.0
    # Basename / stem overlap with query (token-aware).
    base = f.rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if base else ""
    if base and _token_in_query(base, ql):
        bonus += 30.0
    elif stem and _token_in_query(stem, ql):
        bonus += 22.0
    if leaf and _stem_related(leaf, f) and (stem and _token_in_query(stem, ql)):
        bonus += 35.0
    # Owned CamelCase types on their home file (fill injects these for soft queries).
    if leaf[:1].isupper():
        aff = _type_home_affinity(leaf, f)
        if aff >= 50.0:
            bonus += 45.0 if low in ql else 35.0
        aliased = _alias_type(leaf)
        if aliased != leaf:
            a2 = _type_home_affinity(aliased, f)
            if a2 >= 50.0:
                bonus += 20.0
    # Demote private / DTO / destructive helpers unless the query names them.
    if leaf.startswith("_") and low not in ql:
        bonus -= 40.0
    if _seed_symbol_penalty(leaf, query=query) >= 20 and low not in ql:
        bonus -= 25.0
    if low == "wipe" and "wipe" not in ql:
        bonus -= 50.0
    if "wipe.py" in f and not _token_in_query("wipe", ql):
        bonus -= 40.0
    # File stem not mentioned and symbol not named → soft demote (stops wipe/random public).
    if (
        stem
        and not _token_in_query(stem, ql)
        and low
        and low not in ql
        and not (leaf[:1].isupper() and _type_home_affinity(leaf, f) >= 50.0)
    ):
        bonus -= 35.0
    # Parent-package name alone (…/conductor/bm25_index.py) must not crown Conductor.
    parent = f.rsplit("/", 2)[-2] if "/" in f else ""
    if (
        leaf[:1].isupper()
        and parent
        and _token_in_query(parent, ql)
        and stem
        and not _token_in_query(stem, ql)
        and low not in ql
        and not _stem_related(leaf, f)
    ):
        bonus -= 45.0
    return bonus


def _vague_topic_bonus(file: str, symbol: str, query: str) -> float:
    """Light demotion for known collision surfaces on vague asks — not topic recipes."""
    ql = (query or "").lower()
    if not ql:
        return 0.0
    f = (file or "").replace("\\", "/")
    leaf = (symbol or "").rsplit(".", 1)[-1].lower()
    bonus = 0.0
    # UI progress hooks collide with product "indexing".
    if "index" in ql and "cli_ui" in f and leaf in {"indexing", "progress", "set_indexing"}:
        bonus -= 80.0
    if "session" in ql and leaf == "session" and "work_session" not in f and "session_store" not in f:
        bonus -= 40.0
    if "wipe" not in ql and (leaf == "wipe" or f.endswith("wipe.py")):
        if any(t in ql for t in ("merkle", "sync", "dirty", "incremental", "freshness")):
            bonus -= 60.0
    return bonus


def _path_seed_demote(file: str, query: str) -> float:
    """Negative score for UI/branding modules unless the query names them."""
    f = (file or "").replace("\\", "/")
    ql = (query or "").lower()
    for dem in _SEED_PATH_DEMOTE:
        if f.endswith(dem.split("/")[-1]) or f == dem or dem in f:
            if any(t in ql for t in ("cli_ui", "progress", "branding", "spinner", "tui")):
                return 0.0
            return -60.0
    return 0.0


def is_weak_seed_symbol(symbol: str, *, query: str = "") -> bool:
    """True when symbol should not be a pack/map suggested seed."""
    return _seed_symbol_penalty(symbol, query=query) >= 20



def _kind_pref(kind: str) -> int:
    """Lower is better for seed / packing preference (function over class)."""
    if kind in {"function", "method"}:
        return 0
    if kind == "class":
        return 2
    if kind == "const":
        return 3
    return 1


def _seed_kind_pref(kind: str) -> int:
    """Soft-map seed preference: public type/entrypoint before leaf methods."""
    if kind == "class":
        return 0
    if kind in {"function", "method"}:
        return 1
    if kind == "const":
        return 3
    return 2


def _file_stem_tokens(file: str) -> set[str]:
    f = (file or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = f.rsplit(".", 1)[0].lower()
    parts = {p for p in stem.replace("-", "_").split("_") if len(p) >= 3}
    if stem:
        parts.add(stem)
    return parts


def _query_path_bonus(file: str, query: str) -> float:
    """Boost when query names the file stem/basename (token-aware)."""
    ql = (query or "").lower().replace("\\", "/")
    if not ql:
        return 0.0
    base = (file or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    stem = base.rsplit(".", 1)[0] if base else ""
    if base and _token_in_query(base, ql):
        return 25.0
    if stem and _token_in_query(stem, ql):
        return 18.0
    toks = _file_stem_tokens(file)
    hits = sum(1 for t in toks if _token_in_query(t, ql))
    return 3.0 * hits


_LIFECYCLE_VERBS = frozenset(
    {
        "add",
        "search",
        "save",
        "load",
        "create",
        "delete",
        "update",
        "encode",
        "decode",
        "pack",
        "map",
        "index",
        "query",
        "insert",
        "remove",
        "write",
        "read",
        "open",
        "close",
        "connect",
        "build",
        "compile",
        "store",
        "fetch",
        "put",
        "get",
        "drop",
        "list",
        "register",
        "install",
        "demote",
        "expand",
        "collect",
    }
)
_TRIVIAL_ACCESSORS = frozenset(
    {
        "get",
        "name",
        "path",
        "id",
        "meta",
        "info",
        "cwd",
        "root",
        "default",
        "branding",
        "safe_name",
        "collection_path",
        "_safe_name",
        "_collection_path",
        "_read_catalog",
        "_write_catalog",
        "_ensure_catalog",
        "has_collection",
        "list_collections",
    }
)


def short_symbol_leaf(symbol: str) -> str:
    return (symbol or "").strip().rsplit(".", 1)[-1].lower()


def is_trivial_accessor_symbol(symbol: str, *, span_lines: int = 0) -> bool:
    leaf = short_symbol_leaf(symbol)
    if leaf not in _TRIVIAL_ACCESSORS and not leaf.startswith("_"):
        return False
    if leaf in _TRIVIAL_ACCESSORS:
        return span_lines <= 0 or span_lines <= 8
    # Private one-liners / tiny helpers are weak heatmap targets for explain.
    return 0 < span_lines <= 5


def heatmap_is_thin(cards: list[dict[str, Any]]) -> bool:
    """True when lean heatmap is too sparse / accessor-heavy for an explain ask."""
    rows = [c for c in (cards or []) if isinstance(c, dict)]
    if len(rows) <= 3:
        return True
    useful = 0
    for c in rows:
        sym = str(c.get("symbol") or c.get("s") or "")
        start = int(c.get("start_line") or 0)
        end = int(c.get("end_line") or 0)
        span = max(0, end - start) if end and start else 0
        if is_trivial_accessor_symbol(sym, span_lines=span):
            continue
        heat = str(c.get("heat") or "").lower()
        if heat in {"hot", "warm"} or float(c.get("score") or c.get("sc") or 0) >= 0.4:
            useful += 1
    return useful <= 2


def _seed_ids_from_meta(mapped: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("seeds",):
        for s in mapped.get(key) or []:
            if isinstance(s, dict) and s.get("id"):
                ids.append(str(s["id"]))
    if ids:
        return ids
    for key in ("seed", "seed2", "seed3"):
        s = mapped.get(key)
        if isinstance(s, dict) and s.get("id"):
            ids.append(str(s["id"]))
    return ids


def seed_coverage_report(
    cards: list[dict[str, Any]],
    seed_ids: list[str],
) -> dict[str, bool]:
    """Which accepted seed ids appear in the returned heatmap."""
    present = {str(c.get("id") or "") for c in (cards or []) if isinstance(c, dict)}
    return {sid: (sid in present) for sid in seed_ids if sid}


def ensure_seeds_on_heatmap(
    cards: list[dict[str, Any]],
    seed_metas: list[dict[str, Any]],
    nodes: dict[str, TraceNode],
    *,
    k: int = 16,
) -> tuple[list[dict[str, Any]], dict[str, bool], list[str]]:
    """Guarantee each accepted seed appears in the heatmap (inject if missing).

    Returns (cards, coverage, injected_ids). Coverage is True only when the seed
    id is present after inject; injected seeds still count as covered.
    """
    out = [dict(c) for c in (cards or []) if isinstance(c, dict)]
    by_id = {str(c.get("id") or ""): c for c in out if c.get("id")}
    injected: list[str] = []
    for meta in seed_metas or []:
        if not isinstance(meta, dict):
            continue
        sid = str(meta.get("id") or "")
        if not sid:
            file = str(meta.get("file") or "").replace("\\", "/")
            sym = str(meta.get("symbol") or "")
            if file and sym:
                sid = f"{file}::{sym}"
        if not sid:
            continue
        if sid in by_id:
            # Keep seed visible — bump score floor so it is not buried by agreement noise.
            by_id[sid]["score"] = max(float(by_id[sid].get("score") or 0), 1.05)
            by_id[sid]["heat"] = "hot"
            continue
        node = nodes.get(sid)
        if node is None:
            file = str(meta.get("file") or "").replace("\\", "/")
            sym = str(meta.get("symbol") or "")
            if file:
                node = resolve_seed_node(nodes, file=file, symbol=sym)
        if node is None:
            continue
        card = {
            "id": node.id,
            "file": node.file,
            "symbol": node.symbol,
            "kind": node.kind,
            "role": card_role(node.file, node.kind),
            "start_line": node.start_line,
            "end_line": node.end_line,
            "loc": f"{node.file}:{node.start_line}-{node.end_line}",
            "score": 1.1,
            "heat": "hot",
            "why": "seed_coverage_inject",
        }
        out.insert(0, card)
        by_id[node.id] = card
        injected.append(node.id)
    # Re-rank: hot seeds first, then by score.
    out.sort(
        key=lambda c: (
            0 if str(c.get("why") or "") == "seed_coverage_inject" or float(c.get("score") or 0) >= 1.0 else 1,
            -float(c.get("score") or 0),
        )
    )
    if k > 0:
        # Keep all seeds even if past k, then trim non-seeds.
        seed_set = {str(m.get("id") or "") for m in (seed_metas or []) if isinstance(m, dict)}
        seed_set |= set(injected)
        kept: list[dict[str, Any]] = []
        for c in out:
            cid = str(c.get("id") or "")
            if cid in seed_set or len(kept) < k:
                if cid not in {str(x.get("id") or "") for x in kept}:
                    kept.append(c)
        out = kept
    for i, c in enumerate(out, 1):
        c["rank"] = i
    coverage = seed_coverage_report(out, [str(m.get("id") or "") for m in (seed_metas or []) if isinstance(m, dict) and m.get("id")])
    for sid in injected:
        coverage[sid] = True
    return out, coverage, injected


_LEAF_SEED_LEAVES = frozenset(
    {
        "savings_defaults",
        "locate_tool_names",
        "daemon_version",
        "to_float32",
        "from_float32",
        "effective_session_id",
        "id_file_path",
        "read_id_file",
        "is_paused",
        "gate_line_for_repo",
    }
)


def _is_leaf_helper_seed(symbol: str, *, query: str = "") -> bool:
    """True when symbol is a weak leaf helper (prefer class/entrypoint instead)."""
    leaf = short_symbol_leaf(symbol)
    if not leaf:
        return True
    ql = (query or "").lower()
    # Query explicitly named this leaf → allow it.
    if leaf in ql or (symbol or "").lower() in ql:
        return False
    if leaf in _LEAF_SEED_LEAVES:
        return True
    if leaf.startswith("_"):
        return True
    if is_weak_seed_symbol(symbol) or _seed_symbol_penalty(symbol, query=query) >= 18:
        return True
    if is_trivial_accessor_symbol(symbol, span_lines=4):
        return True
    if leaf.endswith(("_defaults", "_names", "_version", "_path", "_tick")):
        return True
    return False


_HEAT_AFFINITY_DEMOTE_FILES = (
    "pause_resume.py",
    "/home.py",
    "preflight",
    "lifecycle_guard.py",
)
_HEAT_AFFINITY_DEMOTE_LEAVES = frozenset(
    {
        "is_paused",
        "read_id_file",
        "id_file_path",
        "gate_line_for_repo",
        "unmanaged_gate_rule_body",
        "paused_gate_rule_body",
        "managed_gate_overview_bullet",
    }
)


def _heat_affinity_demote(card: dict[str, Any], query: str) -> float:
    """Score penalty for helpers unrelated to the ask (pause/home/id unless queried)."""
    ql = (query or "").lower()
    file = str(card.get("file") or "").replace("\\", "/").lower()
    leaf = short_symbol_leaf(str(card.get("symbol") or ""))
    pen = 0.0
    if any(tok in ql for tok in ("pause", "resume", "stop", "home", "preflight", "gate_line")):
        return 0.0
    if any(f in file for f in _HEAT_AFFINITY_DEMOTE_FILES):
        if leaf not in ql and "pause" not in ql and "home" not in ql:
            pen += 0.55
    if leaf in _HEAT_AFFINITY_DEMOTE_LEAVES and leaf not in ql:
        pen += 0.45
    return pen


def apply_heat_affinity(cards: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Demote pause/home/id helpers unless the query names them; re-rank."""
    out: list[dict[str, Any]] = []
    for c in cards or []:
        if not isinstance(c, dict):
            continue
        row = dict(c)
        pen = _heat_affinity_demote(row, query)
        if pen:
            row["score"] = max(0.01, float(row.get("score") or 0) - pen)
            why = str(row.get("why") or "")
            row["why"] = f"{why} [affinity-demote]".strip()
        out.append(row)
    out.sort(key=lambda c: -float(c.get("score") or 0))
    for i, c in enumerate(out, 1):
        c["rank"] = i
    return out


def map_module_clustered(cards: list[dict[str, Any]], *, top_n: int = 5) -> bool:
    """True when soft-map top packages/ hits already cluster one module (explain escape)."""
    pkgs: list[str] = []
    for c in (cards or [])[: max(1, top_n)]:
        if not isinstance(c, dict):
            continue
        f = str(c.get("file") or "").replace("\\", "/")
        if f.startswith(("packages/", "src/", "app/", "lib/")):
            pkgs.append(f)
    if len(pkgs) < 2:
        return len(pkgs) == 1
    files = set(pkgs)
    dirs = {"/".join(f.split("/")[:-1]) for f in files}
    return len(files) <= 2 or len(dirs) == 1


def map_ladder_next(
    cards: list[dict[str, Any]],
    suggested: dict[str, Any] | None,
    *,
    query: str = "",
    suggested_seeds: list[dict[str, Any]] | None = None,
) -> str:
    """Steer after map: enrich query, multi-seed pack when relevant."""
    if not suggested:
        return (
            "No strong packages/ seed — rewrite map query denser (25–120 tokens, target ≥40: "
            "symbols/paths/APIs/errors/tech/verbs across the problem surface), then remmap → pack."
        )
    if suggested.get("seed_incomplete"):
        return (
            "suggested_seed has file but no resolved symbol — pack_context(seed_file only); "
            "Forbid seed_line=1 guessing. Prefer a packages/ public class card if visible."
        )
    seeds = [s for s in (suggested_seeds or []) if isinstance(s, dict) and s.get("file")]
    if len(seeds) < 1:
        seeds = [suggested]
    sym = str(suggested.get("symbol") or "")
    private = _seed_symbol_penalty(sym) >= 20
    clustered = map_module_clustered(cards)
    ql = (query or "").lower()
    explainish = any(
        w in ql for w in ("how does", "how do", "explain", "architecture", "overview", "works")
    )
    if clustered and (explainish or private) and len(seeds) < 2:
        return (
            "Module already clustered — prefer pack_context(lean, public class/entrypoint seed) "
            "OR Native-Read top packages/ map card locs for explain-only "
            "(skip pack when narrative; pack for edit/debug). "
            "Forbid _helper seeds. Enrich pack query with seed file::symbol + hot cards first."
        )
    if len(seeds) >= 2:
        # Never recommend incomplete seeds in seed2/seed3 slots.
        usable = [s for s in seeds if not s.get("seed_incomplete")]
        if not usable:
            usable = seeds[:1]
        primary = usable[0] if usable else suggested
        s2 = usable[1] if len(usable) > 1 else None
        s3 = usable[2] if len(usable) > 2 else None
        if s2 is None:
            return (
                "ENRICH pack query further (25–120 tokens, target ≥40): fold suggested_seed "
                "file::symbol + hot card symbols/paths/APIs from map into a denser sentence, then "
                "pack_context(mode=lean, seed_*)."
            )
        extra = ""
        if s3 is not None:
            extra = (
                f", seed3_file={s3.get('file')}, seed3_symbol={s3.get('symbol') or ''}"
            )
        return (
            "ENRICH pack query (25–120 tokens, target ≥40) using ALL suggested_seeds file::symbol "
            "+ 2–4 hot card names, then pack_context(mode=lean, "
            f"seed_file={primary.get('file')}, seed_symbol={primary.get('symbol') or ''}, "
            f"seed2_file={s2.get('file')}, seed2_symbol={s2.get('symbol') or ''}{extra}). "
            "Multi-seed agreement+corridor — keep seed2 when modules differ."
        )
    return (
        "ENRICH pack query further (25–120 tokens, target ≥40): fold suggested_seed "
        "file::symbol + hot card symbols/paths/APIs from map into a denser sentence, then "
        "pack_context(mode=lean, seed_*). Add seed2_* when a second packages/ module is hot."
    )


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


def pick_suggested_seed(
    cards: list[dict[str, Any]],
    *,
    query: str = "",
) -> dict[str, Any] | None:
    """Best soft-map card for pack — prefer packages/ public class/entrypoint over _helpers."""
    filled = [fill_map_card_symbol(c, query=query) for c in (cards or [])]
    _prod_prefixes = ("packages/", "src/", "app/", "lib/")
    _seed_roles = {"function", "method", "class"}
    _seed_kinds = {"function", "method", "class"}

    def _path_ok_primary(file: str) -> bool:
        f = file.replace("\\", "/")
        return f.startswith(_prod_prefixes)

    def _path_banned(file: str) -> bool:
        f = file.replace("\\", "/")
        base = f.rsplit("/", 1)[-1]
        if card_role(f) in {"test", "docs"}:
            return True
        # Eval/harness/scripts are weak seeds even when not under tests/.
        if f.startswith(("scripts/", "research/", "fixtures/", ".ab_workspaces/")):
            return True
        if any(p in f for p in ("/eval/", "/evals/", "/benchmark")):
            return True
        if base.startswith(("test_", "ab_", "kiro_")):
            return True
        return False

    def _role_kind(c: dict[str, Any], file: str) -> tuple[str, str]:
        kind = str(c.get("kind") or "").lower()
        role = str(c.get("role") or card_role(file, kind))
        return role, kind

    # tier, kind_pen, sym_pen, -score_adj, card
    scored: list[tuple[int, int, int, float, dict[str, Any]]] = []
    for c in filled:
        file = str(c.get("file") or "").replace("\\", "/")
        role, kind = _role_kind(c, file)
        if role in {"test", "docs"} or _path_banned(file):
            continue
        if not _path_ok_primary(file):
            continue
        sym = str(c.get("symbol") or "").strip()
        sym_pen = _seed_symbol_penalty(sym, query=query)
        stem = file.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
        ql = (query or "").lower()
        score_adj = (
            float(c.get("score") or 0)
            + _query_path_bonus(file, query)
            + _query_symbol_bonus(sym, file, query)
            + _vague_topic_bonus(file, sym, query)
            + _path_seed_demote(file, query)
        )
        # Primary: public class / function / method (not weak accessors / UI leaves).
        if (role in _seed_roles or kind in _seed_kinds) and sym_pen < 18:
            # Demote public leaves the query does not name when another card's file stem matches.
            if sym and sym.lower() not in ql and not _stem_related(sym, file):
                score_adj -= 20.0
            scored.append((0, _seed_kind_pref(kind or role), sym_pen, -score_adj, c))
            continue
        # Empty/weak card on a file the query names → still primary (finalize fills symbol).
        if (not sym or sym_pen >= 18) and stem and _token_in_query(stem, query or ""):
            file_card = dict(c)
            file_card["symbol"] = ""
            file_card["kind"] = "other"
            file_card["role"] = "other"
            scored.append((0, 2, 0, -(score_adj + 45.0), file_card))
            continue
        # Secondary: module cards or weak public leaves → file-level (resolve picks class).
        if role == "other" or kind in {"", "chunk", "other"} or sym_pen >= 18:
            file_card = dict(c)
            if sym_pen >= 18:
                file_card["symbol"] = ""
                file_card["kind"] = "other"
                file_card["role"] = "other"
            scored.append((1, 2, 25, -score_adj, file_card))
    if not scored:
        # Fallback: private helpers in packages/, then non-banned production-ish paths.
        for c in filled:
            file = str(c.get("file") or "").replace("\\", "/")
            role, kind = _role_kind(c, file)
            if role in {"test", "docs"} or _path_banned(file):
                continue
            if role not in _seed_roles and kind not in _seed_kinds:
                continue
            path_pen = 0 if _path_ok_primary(file) else 2
            sym = str(c.get("symbol") or "")
            score_adj = (
                float(c.get("score") or 0)
                + _query_path_bonus(file, query)
                + _query_symbol_bonus(sym, file, query)
                + _vague_topic_bonus(file, sym, query)
                + _path_seed_demote(file, query)
            )
            scored.append(
                (
                    2 + path_pen,
                    _seed_kind_pref(kind or role),
                    _seed_symbol_penalty(sym),
                    -score_adj,
                    c,
                )
            )
        if not scored:
            return None
    scored.sort(key=lambda t: (t[0], t[2], t[3], t[1]))
    best = scored[0][4]
    # If we only won with a private/weak leaf but a public class exists on same file, promote.
    best_file = str(best.get("file") or "").replace("\\", "/")
    best_sym = str(best.get("symbol") or "").strip()
    if _seed_symbol_penalty(best_sym, query=query) >= 18:
        for c in filled:
            f = str(c.get("file") or "").replace("\\", "/")
            if f != best_file:
                continue
            role, kind = _role_kind(c, f)
            sym = str(c.get("symbol") or "").strip()
            if (role == "class" or kind == "class") and _seed_symbol_penalty(sym, query=query) < 18:
                best = c
                break
        # Cross-file: promote query-named class/orchestrator if present
        for c in filled:
            f = str(c.get("file") or "").replace("\\", "/")
            if _path_banned(f) or not _path_ok_primary(f):
                continue
            role, kind = _role_kind(c, f)
            sym = str(c.get("symbol") or "").strip()
            if _seed_symbol_penalty(sym, query=query) >= 18:
                continue
            if _query_symbol_bonus(sym, f, query) >= 25 or _vague_topic_bonus(f, sym, query) >= 40:
                best = c
                break
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


def pick_suggested_seeds(
    cards: list[dict[str, Any]],
    *,
    query: str = "",
    limit: int = 3,
) -> list[dict[str, Any]]:
    """1–3 pack seeds for the same query — prefer distinct packages/ files.

    Primary is always ``pick_suggested_seed``. Extra seeds come from other strong
    production cards (different file) so multi-seed pack can form a corridor.
    """
    primary = pick_suggested_seed(cards, query=query)
    if not primary or not primary.get("file"):
        return []
    out = [dict(primary)]
    primary_file = str(primary.get("file") or "").replace("\\", "/")
    filled = [fill_map_card_symbol(c, query=query) for c in (cards or [])]
    _prod = ("packages/", "src/", "app/", "lib/")
    seen_files = {primary_file}
    candidates: list[tuple[float, dict[str, Any]]] = []
    for c in filled:
        file = str(c.get("file") or "").replace("\\", "/")
        if not file or file in seen_files:
            continue
        if not file.startswith(_prod):
            continue
        role = str(c.get("role") or card_role(file, str(c.get("kind") or "")))
        if role in {"test", "docs"}:
            continue
        if any(
            p in file
            for p in ("/eval/", "/evals/", "/benchmark", "scripts/", "research/", "fixtures/")
        ):
            continue
        sym = str(c.get("symbol") or "").strip()
        sym_pen = _seed_symbol_penalty(sym, query=query)
        # Empty/weak symbol on a query-named file can still be a secondary seed;
        # finalize_suggested_seed fills the public class/entrypoint later.
        stem = file.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
        file_named = bool(stem and _token_in_query(stem, query or ""))
        if sym_pen >= 18 and not file_named:
            continue
        if sym_pen >= 18 and file_named:
            sym = ""
        if str(c.get("kind") or "").lower() not in {"class", "function", "method", ""} and role not in {
            "class",
            "function",
            "method",
        }:
            # Allow empty kind when symbol looks public or file is query-named
            if not (file_named or (sym and not sym.startswith("_"))):
                continue
        score = (
            float(c.get("score") or 0)
            + _query_path_bonus(file, query)
            + _query_symbol_bonus(sym, file, query)
            + _vague_topic_bonus(file, sym, query)
        )
        if file_named and not sym:
            score += 40.0
        # Prefer non-leaf helpers for secondary seeds.
        if _is_leaf_helper_seed(sym, query=query):
            score -= 35.0
        candidates.append(
            (
                -score,
                {
                    "file": file,
                    "symbol": sym,
                    "start_line": int(c.get("start_line") or 0),
                    "loc": c.get("loc")
                    or f"{file}:{c.get('start_line')}-{c.get('end_line')}",
                    "kind": c.get("kind") or "",
                    "role": role,
                    "score": c.get("score"),
                },
            )
        )
    candidates.sort(key=lambda t: t[0])
    for _neg, seed in candidates:
        f = str(seed.get("file") or "")
        if f in seen_files:
            continue
        seen_files.add(f)
        out.append(seed)
        if len(out) >= max(1, min(int(limit or 3), 3)):
            break
    return out


def finalize_suggested_seed(
    root: Path,
    suggested: dict[str, Any] | None,
    *,
    query: str = "",
    load_repo: bool = True,
) -> dict[str, Any] | None:
    """Fill empty/weak map seeds via resolve — query idents and stem match, not topic tables.

    When a public class/def exists in-file, `symbol` / `loc` / `kind` are filled.
    If resolve fails, keep file-only and set `seed_incomplete: true`.

    ``load_repo=False`` (map path): never build the AST graph. Incomplete seeds
    stay file-only so first map stays search-bound (~2s), not graph-bound (~16s).
    """
    if not suggested or not isinstance(suggested, dict):
        return suggested
    out = dict(suggested)
    file = str(out.get("file") or "").replace("\\", "/").strip()
    if not file:
        return out
    sym = str(out.get("symbol") or "").strip()
    loc = str(out.get("loc") or "").strip()
    # Map cards already carry file + symbol + loc; skip the full AST graph load.
    if file and sym and ":" in loc and not is_weak_seed_symbol(sym, query=query):
        return out
    if not load_repo:
        if not sym:
            out["seed_incomplete"] = True
        return out
    try:
        rt = _load_repo(root)
        node = _pick_best_node_in_file(
            rt.nodes,
            file=file,
            query=query,
            current_symbol=sym,
            start_line=int(out.get("start_line") or 0),
        )
    except Exception:  # noqa: BLE001
        node = None
    if node is None:
        out["symbol"] = sym
        out["seed_incomplete"] = True
        return out
    out["symbol"] = node.symbol
    out["kind"] = node.kind
    out["start_line"] = node.start_line
    out["end_line"] = node.end_line
    out["loc"] = f"{node.file}:{node.start_line}-{node.end_line}"
    out["role"] = card_role(node.file, node.kind)
    out.pop("seed_incomplete", None)
    return out


def _pick_best_node_in_file(
    nodes: dict[str, TraceNode],
    *,
    file: str,
    query: str = "",
    current_symbol: str = "",
    start_line: int = 0,
) -> TraceNode | None:
    """Resolve a seed in `file` using query idents / type homes / stem — general only."""
    file = file.replace("\\", "/").lstrip("./")
    ql = (query or "").lower()
    sym = (current_symbol or "").strip()

    # 1) Query CamelCase types that live in this file (with aliases).
    for name in _query_type_names(query):
        want = _alias_type(name)
        if _type_home_affinity(want, file) < 50.0 and _type_home_affinity(name, file) < 50.0:
            continue
        node = resolve_seed_node(nodes, file=file, symbol=want)
        if node is not None:
            return node
        if want != name:
            node = resolve_seed_node(nodes, file=file, symbol=name)
            if node is not None:
                return node

    # 2) Explicit current symbol if strong AND query-compatible (skip silent leaf helpers).
    if (
        sym
        and not is_weak_seed_symbol(sym, query=query)
        and not _is_leaf_helper_seed(sym, query=query)
    ):
        low = sym.rsplit(".", 1)[-1].lower()
        stem = file.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
        # Don't keep an off-query leaf when the file stem is what the query named.
        if low in ql or not (stem and _token_in_query(stem, ql)):
            want = _alias_type(sym)
            node = resolve_seed_node(nodes, file=file, symbol=want, start_line=start_line)
            if node is not None:
                return node

    # 3) Any query identifier that resolves in this file (longest first).
    for tok in _query_ident_tokens(query):
        want = _alias_type(tok)
        node = resolve_seed_node(nodes, file=file, symbol=want)
        if node is not None and not is_weak_seed_symbol(node.symbol, query=query):
            return node

    # 4) Public symbols related to the file stem when the stem appears in the query.
    stem = file.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
    if stem and _token_in_query(stem, ql):
        related = [
            n
            for n in nodes.values()
            if n.file == file
            and n.symbol not in _SKIP_SEED_SYMBOLS
            and not is_weak_seed_symbol(n.symbol, query=query)
            and _stem_related(n.symbol.rsplit(".", 1)[-1], file)
        ]
        if related:
            related.sort(
                key=lambda n: (
                    0 if n.symbol.rsplit(".", 1)[-1].lower() in ql else 1,
                    _seed_kind_pref(n.kind),
                    _seed_symbol_penalty(n.symbol, query=query),
                    -(n.end_line - n.start_line),
                    n.start_line,
                )
            )
            return related[0]

    # 5) Bare file resolve (DTO/Error already weak via penalty).
    return resolve_seed_node(nodes, file=file, symbol="", start_line=start_line)



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
        if file.startswith(("scripts/", "fixtures/", "research/")):
            pen += 45
        if "cli_ui.py" in file:
            pen += 15
        # Literal name-collision leaves (UI progress hooks) sit below product APIs
        leaf = str(item.get("symbol") or "").rsplit(".", 1)[-1].lower()
        if leaf in _WEAK_PUBLIC_SEED_LEAVES:
            pen += 20
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
    asked_explicit = bool(sym and sym not in _SKIP_SEED_SYMBOLS)
    weak_accessor_cleared = False
    if asked_explicit:
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
        # Weak accessors (from_dict / blob / to_dict) — prefer API class.
        # Keep other exact matches (heatmap_is_thin, predicates) so pack/broad don't swap seeds.
        if found is not None and is_weak_seed_symbol(found.symbol):
            leaf = found.symbol.rsplit(".", 1)[-1].lower()
            if leaf in _WEAK_PUBLIC_SEED_LEAVES or leaf.startswith(("get_", "set_", "to_", "default_")):
                found = None
                weak_accessor_cleared = True
        # Const / module ROOT matches are poor seeds — snap to covering function.
        if found is not None and found.kind == "const" and start_line > 0:
            covering = [
                n
                for n in nodes.values()
                if n.file == file
                and n.start_line <= start_line <= n.end_line
                and n.kind in {"function", "method"}
                and not is_weak_seed_symbol(n.symbol)
            ]
            if covering:
                covering.sort(key=lambda n: (n.end_line - n.start_line, n.start_line))
                return covering[0]
        if found is not None and found.kind != "const":
            return found
        # Bare const without a covering def — keep looking for a better in-file seed.
        if found is not None and start_line > 0:
            covering = [
                n
                for n in nodes.values()
                if n.file == file
                and n.start_line <= start_line <= n.end_line
                and n.kind != "class"
                and not is_weak_seed_symbol(n.symbol)
            ]
            if covering:
                covering.sort(
                    key=lambda n: (_kind_pref(n.kind), n.end_line - n.start_line, n.start_line)
                )
                return covering[0]
        # Explicit name was not in this file — do NOT invent the largest class
        # (that turned CapabilityIndex@engine.py into WarmSearchEngine).
        if not weak_accessor_cleared:
            return None
    # No usable symbol (empty, or weak accessor cleared) — prefer covering def, else best in-file seed.
    # seed_line=1 often hits module constants / default_* — prefer class over those.
    if start_line > 0:
        covering = [
            n
            for n in nodes.values()
            if n.file == file
            and n.start_line <= start_line <= n.end_line
            and n.kind in {"function", "method"}
            and n.symbol not in _SKIP_SEED_SYMBOLS
            and not is_weak_seed_symbol(n.symbol)
        ]
        if covering:
            covering.sort(
                key=lambda n: (
                    _seed_symbol_penalty(n.symbol),
                    n.end_line - n.start_line,
                    n.start_line,
                )
            )
            # Tiny line-1 helpers (default_vectordb_root) lose to public class below.
            best_cov = covering[0]
            if (best_cov.end_line - best_cov.start_line) >= 8 or start_line > 3:
                return best_cov
    # Bare file seed (no symbol): stem-related API surface, else largest public class, else def.
    public = [
        n
        for n in nodes.values()
        if n.file == file
        and n.symbol not in _SKIP_SEED_SYMBOLS
        and _seed_symbol_penalty(n.symbol) < 20
    ]
    related = [n for n in public if _stem_related(n.symbol.rsplit(".", 1)[-1], file)]
    if related:
        related.sort(
            key=lambda n: (
                _seed_kind_pref(n.kind),
                -(n.end_line - n.start_line),
                n.start_line,
            )
        )
        return related[0]
    classes = [n for n in public if n.kind == "class"]
    if classes:
        classes.sort(key=lambda n: (-(n.end_line - n.start_line), n.start_line))
        return classes[0]
    in_file = [n for n in public if n.kind != "class"]
    if in_file:
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
    seed3_file: str = "",
    seed3_symbol: str = "",
    seed3_line: int = 0,
    k: int = 24,
) -> dict[str, Any]:
    from trace_lab.multi_seed import (
        light_seed_heatmap,
        merge_seed_heatmaps,
        multi_seed_adaptive_enabled,
        seed_covered_by_heatmap,
        seed_specs_from_args,
    )

    t0 = time.perf_counter()
    timing: dict[str, Any] = {
        "load_repo_ms": 0.0,
        "poly_ms": [],
        "merge_ms": 0.0,
        "cards_ms": 0.0,
        "adaptive_skips": [],
    }
    t_load = time.perf_counter()
    rt = _load_repo(root)
    timing["load_repo_ms"] = round((time.perf_counter() - t_load) * 1000, 1)
    specs = seed_specs_from_args(
        seed_file=seed_file,
        seed_symbol=seed_symbol,
        seed_line=seed_line,
        seed2_file=seed2_file,
        seed2_symbol=seed2_symbol,
        seed2_line=seed2_line,
        seed3_file=seed3_file,
        seed3_symbol=seed3_symbol,
        seed3_line=seed3_line,
    )
    if not specs:
        return {
            "ok": False,
            "error": f"seed not found: file={seed_file!r} symbol={seed_symbol!r} line={seed_line}",
            "hint": "Pass seed_file + seed_symbol or seed_line covering a function.",
            "timing": timing,
        }

    resolved: list[TraceNode] = []
    for i, spec in enumerate(specs):
        node = resolve_seed_node(
            rt.nodes,
            file=str(spec["file"]),
            symbol=str(spec.get("symbol") or ""),
            start_line=int(spec.get("line") or 0),
        )
        if node is None and i == 0:
            return {
                "ok": False,
                "error": (
                    f"seed not found: file={spec['file']!r} "
                    f"symbol={spec.get('symbol')!r} line={spec.get('line')}"
                ),
                "hint": "Pass seed_file + seed_symbol or seed_line covering a function.",
                "timing": timing,
            }
        if node is None:
            continue
        if any(n.id == node.id for n in resolved):
            continue
        resolved.append(node)

    if not resolved:
        return {
            "ok": False,
            "error": f"seed not found: file={seed_file!r} symbol={seed_symbol!r} line={seed_line}",
            "hint": "Pass seed_file + seed_symbol or seed_line covering a function.",
            "timing": timing,
        }

    busy = _engine_busy_for_multi_seed()
    if busy and len(resolved) > 2:
        resolved = resolved[:2]

    seed = resolved[0]
    seed2 = resolved[1] if len(resolved) > 1 else None
    seed3 = resolved[2] if len(resolved) > 2 else None

    def _poly(seed_node: TraceNode, case_id: str) -> Heatmap:
        return rt.poly(_case(query, seed_node, case_id=case_id), rt.nodes, rt.graph, rt.lex)

    maps_slot: list[Heatmap | None] = [None] * len(resolved)
    case_ids = ["mcp", "mcp2", "mcp3"]
    adaptive = multi_seed_adaptive_enabled() and len(resolved) >= 2 and not busy

    # Always full poly for seed1 (quality anchor).
    t_p0 = time.perf_counter()
    maps_slot[0] = _poly(resolved[0], case_ids[0])
    timing["poly_ms"].append(round((time.perf_counter() - t_p0) * 1000, 1))

    # Secondary seeds: light hop island when already covered by seed1, else full poly.
    need_full: list[tuple[int, TraceNode]] = []
    for i, node in enumerate(resolved[1:], start=1):
        if adaptive and seed_covered_by_heatmap(maps_slot[0], node.id):
            t_l = time.perf_counter()
            maps_slot[i] = light_seed_heatmap(node.id, rt.graph)
            timing["poly_ms"].append(round((time.perf_counter() - t_l) * 1000, 1))
            timing["adaptive_skips"].append(node.id)
        else:
            need_full.append((i, node))

    if need_full:
        if len(need_full) >= 2 and _trace_parallel_enabled() and not busy:
            t_par = time.perf_counter()
            with ThreadPoolExecutor(max_workers=min(2, len(need_full))) as pool:
                futs = {
                    pool.submit(_poly, node, case_ids[i]): i for i, node in need_full
                }
                for fut, i in futs.items():
                    maps_slot[i] = fut.result()
            timing["poly_ms"].append(round((time.perf_counter() - t_par) * 1000, 1))
        else:
            for i, node in need_full:
                t_p = time.perf_counter()
                maps_slot[i] = _poly(node, case_ids[i])
                timing["poly_ms"].append(round((time.perf_counter() - t_p) * 1000, 1))

    maps = [m for m in maps_slot if m is not None]
    t_merge = time.perf_counter()
    if len(resolved) >= 2:
        merged = merge_seed_heatmaps(maps, [n.id for n in resolved], rt.graph)
    else:
        merged = maps[0] if maps else Heatmap(strategy="map_context", cells=[])
    timing["merge_ms"] = round((time.perf_counter() - t_merge) * 1000, 1)

    t_cards = time.perf_counter()
    cards = heatmap_to_cards(merged, rt.nodes, k=k)
    timing["cards_ms"] = round((time.perf_counter() - t_cards) * 1000, 1)

    def _seed_blob(n: TraceNode | None) -> dict[str, Any] | None:
        if n is None:
            return None
        return {
            "file": n.file,
            "symbol": n.symbol,
            "id": n.id,
            "kind": n.kind,
            "start_line": n.start_line,
        }

    multi_meta: dict[str, Any] | None = None
    if len(resolved) >= 2:
        extra = dict(getattr(merged, "extra", {}) or {})
        if timing["adaptive_skips"]:
            extra["adaptive_skips"] = list(timing["adaptive_skips"])
            extra["adaptive"] = True
        multi_meta = {
            "engine": getattr(merged, "strategy", "multi_seed_v1"),
            "extra": extra,
        }

    return {
        "ok": True,
        "tool": "map_context",
        "query": query,
        "seed": _seed_blob(seed),
        "seed2": _seed_blob(seed2),
        "seed3": _seed_blob(seed3),
        "seeds": [_seed_blob(n) for n in resolved],
        "multi_seed": multi_meta,
        "heatmap": cards,
        "count": len(cards),
        "ranked_only": True,
        "bodies": False,
        "engine": (merged.strategy if merged else _trace_engine()),
        "graphify": rt.gfy is not None,
        "n_nodes": len(rt.nodes),
        "guide": (
            "Relevance GUIDE — each card is full loc + score. No code bodies. "
            "Follow howto: Read/Grep those spots top-down; expand_context if thin."
        ),
        "howto": _HEATMAP_HOWTO,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        "timing": timing,
        "_persist": {
            "query": query,
            "seed_id": seed.id,
            "cards": cards,
            "scores": {c["id"]: c["score"] for c in cards},
            "seed_ids": [n.id for n in resolved],
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


def _expand_why_is_reverse(why: str) -> bool:
    w = (why or "").lower()
    return any(
        tok in w
        for tok in (
            "called_by",
            "used_by",
            "imported_by",
            "text_call",
            "rev:calls",
            "rev:uses",
            "<-",
        )
    )


def rank_expand_delta(
    cards: list[dict[str, Any]],
    *,
    seed_file: str,
    query: str = "",
    direction: str = "all",
    seed_symbol: str = "",
) -> list[dict[str, Any]]:
    """Rank expand deltas: reverse/cross-file/query first; demote sibling forward noise."""
    seed_f = (seed_file or "").replace("\\", "/")
    ql = (query or "").lower()
    q_tokens = {t for t in ql.replace("::", " ").replace("/", " ").replace(".", " ").split() if len(t) >= 3}
    d = (direction or "").lower()
    callersish = d in {"callers", "refs", "dependents"}
    # Leaf seed → boost same-file public siblings (blind: savings_defaults → put_span).
    rescue_from_leaf = bool(seed_symbol) and _is_leaf_helper_seed(
        seed_symbol, query=""
    )

    def _key(c: dict[str, Any]) -> tuple:
        file = str(c.get("file") or "").replace("\\", "/")
        sym = str(c.get("symbol") or "")
        leaf = sym.split(".")[-1].lower()
        why = str(c.get("why") or "")
        evidence = str(c.get("evidence") or "").lower()
        reverse = (
            evidence in {"called_by", "used_by", "text_call", "imported_by"}
            or _expand_why_is_reverse(why)
        )
        forward_noise = (not reverse) and (
            "calls:" in why.lower() or ("->" in why and "<-" not in why)
        )
        same_file = 1 if file == seed_f else 0
        cross = 0 if same_file else 1
        # Prefer packages/ production over scripts/
        path_pen = 0
        if file.startswith("scripts/") or "/tests/" in file or file.startswith("tests/"):
            path_pen = 2
        elif not file.startswith(("packages/", "src/", "app/", "lib/")):
            path_pen = 1
        q_hit = 0
        blob = f"{file} {sym} {leaf}".lower()
        if q_tokens:
            q_hit = sum(1 for t in q_tokens if t in blob)
        helper_pen = 0
        if leaf.startswith("_") or any(
            x in leaf for x in ("ollama", "coreml", "pad_embed", "fastembed", "gpu")
        ):
            helper_pen = 1 if not reverse else 0
        already = 1 if c.get("already_in_pack") else 0
        # callers: reverse first; else mild preference for reverse when present
        reverse_rank = 0 if reverse else (2 if callersish else 1)
        forward_rank = 2 if (callersish and forward_noise) else 0
        # Callers climb out of seed file — unless recovering from a leaf seed
        # (boost public same-file APIs that pack missed).
        leaf_seed_rescue = 0
        if rescue_from_leaf and same_file and not reverse:
            if not _is_leaf_helper_seed(sym, query=query) and not leaf.startswith("_"):
                leaf_seed_rescue = -2
                q_hit += 1
        same_file_pen = 3 if (callersish and same_file and not reverse) else (1 if (callersish and same_file) else 0)
        if leaf_seed_rescue:
            same_file_pen = 0
        score = -float(c.get("score") or 0)
        return (
            reverse_rank,
            forward_rank,
            same_file_pen,
            leaf_seed_rescue,
            -cross,
            path_pen,
            -q_hit,
            helper_pen,
            already,
            score,
        )

    out = [dict(c) for c in cards]
    out.sort(key=_key)
    for i, c in enumerate(out, 1):
        c["rank"] = i
    return out


def _same_file_public_sibling_cards(
    rt: _RepoTrace,
    seed: TraceNode,
    *,
    prior: set[str],
    k: int = 8,
) -> list[dict[str, Any]]:
    """Inject public same-file APIs when expanding from a leaf helper."""
    if not _is_leaf_helper_seed(seed.symbol, query=""):
        return []
    file_n = seed.file.replace("\\", "/")
    out: list[dict[str, Any]] = []
    for n in rt.nodes.values():
        if n.id in prior or n.id == seed.id:
            continue
        if n.file.replace("\\", "/") != file_n:
            continue
        if n.kind not in {"function", "method", "class"}:
            continue
        if _is_leaf_helper_seed(n.symbol, query=""):
            continue
        if is_weak_seed_symbol(n.symbol) or n.symbol.split(".")[-1].startswith("_"):
            continue
        out.append(
            {
                "id": n.id,
                "file": n.file,
                "symbol": n.symbol,
                "kind": n.kind,
                "role": card_role(n.file, n.kind),
                "start_line": n.start_line,
                "end_line": n.end_line,
                "loc": f"{n.file}:{n.start_line}-{n.end_line}",
                "score": 0.88,
                "heat": "warm",
                "why": "same_file_sibling_rescue",
                "evidence": "same_file",
            }
        )
        if len(out) >= k:
            break
    return out


def _lexical_caller_cards(
    rt: _RepoTrace,
    nid: str,
    *,
    k: int,
    prior: set[str],
) -> list[dict[str, Any]]:
    """Find defs whose body calls seed.leaf(…) — catches dynamic method call sites."""
    seed = rt.nodes.get(nid)
    if seed is None:
        return []
    leaf = seed.symbol.split(".")[-1]
    if not leaf or leaf.startswith("_") or len(leaf) < 3:
        return []
    needles = (f".{leaf}(", f" {leaf}(", f"({leaf}(")
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for vid, n in rt.nodes.items():
        if vid == nid or vid in prior or vid in seen:
            continue
        if n.kind not in {"function", "method"}:
            continue
        text = n.text or ""
        if not any(tok in text for tok in needles):
            continue
        # Avoid matching the method's own def line only inside the same symbol body
        if n.file == seed.file and n.symbol.split(".")[-1] == leaf:
            continue
        seen.add(vid)
        score = 0.78
        f = n.file.replace("\\", "/")
        if f.startswith(("packages/", "src/", "app/", "lib/")):
            score = 0.88
        if f.startswith("scripts/") or f.startswith("tests/") or "/tests/" in f:
            score = 0.45
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
                "score": score,
                "heat": _heat(score),
                "rank": len(cards) + 1,
                "why": f"expand:text_call {seed.symbol}<-{n.symbol}",
                "evidence": "text_call",
                "path": [nid, vid],
                "suggested": "read",
            }
        )
        if len(cards) >= max(k, 12):
            break
    return cards


def _find_richer_subclass(
    nodes: dict[str, TraceNode],
    seed: TraceNode,
) -> TraceNode | None:
    """Public subclass in another file (e.g. Conductor → MultiArchConductor)."""
    if seed.kind != "class":
        return None
    base = seed.symbol.split(".")[-1]
    if not base or is_weak_seed_symbol(base):
        return None
    seed_file = seed.file.replace("\\", "/")
    # packages/conductor from packages/conductor/conductor.py
    parts = seed_file.split("/")
    pkg_prefix = "/".join(parts[:2]) if parts and parts[0] == "packages" and len(parts) >= 2 else "/".join(parts[:-1])
    needle = f"({base})"
    cands: list[TraceNode] = []
    for n in nodes.values():
        if n.kind != "class" or n.id == seed.id:
            continue
        if is_weak_seed_symbol(n.symbol):
            continue
        f = n.file.replace("\\", "/")
        if f == seed_file:
            continue
        if pkg_prefix and not f.startswith(pkg_prefix + "/") and f != pkg_prefix:
            continue
        head = (n.text or "").split("\n", 1)[0]
        if needle not in head and f"({base}," not in head:
            continue
        cands.append(n)
    if not cands:
        return None
    cands.sort(
        key=lambda n: (
            0 if n.file.replace("\\", "/").startswith(pkg_prefix) else 1,
            -(n.end_line - n.start_line),
            n.start_line,
        )
    )
    return cands[0]


def _heatmap_is_file_local(cards: list[dict[str, Any]], seed_file: str) -> bool:
    seed_f = (seed_file or "").replace("\\", "/")
    files = {
        str(c.get("file") or "").replace("\\", "/")
        for c in (cards or [])
        if isinstance(c, dict) and c.get("file")
    }
    files.discard("")
    if not files:
        return True
    return files <= {seed_f}


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
    pack_seen_ids: set[str] | None = None,
    with_bodies: bool = False,
    budget_chars: int = 4000,
    max_bodies: int = 3,
    prior_packed_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Grow the map from a node; return DELTA cards (optional bodies).

    ``prior_ids`` = already-expanded this session (skip to avoid thrash).
    ``pack_seen_ids`` = pack heatmap ids — annotate ``already_in_pack``, do **not** drop
    (dropping pack cards made callers/effects empty after dense packs).

    direction/intent flexibility:
      callees|flow — forward calls/uses
      callers|refs — reverse / LSP used_by (escapes strict composite)
      effects|site — log/track/send leaves
      config — consts + uses
      broad|all — structural 1-hop + tracer blend
    """
    t0 = time.perf_counter()
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
    prior = {str(x) for x in (prior_ids or set()) if x}
    pack_seen = {str(x) for x in (pack_seen_ids or set()) if x}
    # Never treat pack heatmap as expand-prior (that emptied callers after pack).
    prior.discard(nid)

    # callers/effects need tracer — structural reverse edges alone are too sparse.
    # broad/all are script-neighbor expands only (no poly / no semantic).
    want_tracer = d in {
        "flow",
        "callees",
        "config",
        "callers",
        "refs",
        "effects",
        "site",
    }

    def _struct() -> list[dict[str, Any]]:
        return _neighbor_cards(rt, nid, direction=d, k=max(k, 12), prior=prior)

    def _tracer() -> list[dict[str, Any]]:
        hm = rt.poly(_case(q, seed, case_id="expand"), rt.nodes, rt.graph, rt.lex)
        cards = heatmap_to_cards(hm, rt.nodes, k=k + len(prior) + 8, min_score=_WARM)
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
        elif d in {"callers", "refs"}:
            # Prefer reverse-ish why; drop pure forward CALLS: noise from polytrace.
            filtered: list[dict[str, Any]] = []
            for c in cards:
                if c.get("id") == nid:
                    continue
                why = str(c.get("why") or "")
                if _expand_why_is_reverse(why):
                    filtered.append(c)
                    continue
                # Keep mild "ref/from/by" without forward CALLS:
                wl = why.lower()
                if "calls:" in wl or ("->" in why and "<-" not in why):
                    continue
                if any(tok in wl for tok in ("ref", "from", "by", "use")):
                    filtered.append(c)
            cards = filtered
        elif d in {"effects", "site"}:
            cards = [
                c
                for c in cards
                if any(
                    tok in (c.get("why") or "").lower()
                    for tok in ("log", "track", "send", "print", "effect", "call", "use")
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

    t_struct = time.perf_counter()
    struct = _struct()
    struct_ms = round((time.perf_counter() - t_struct) * 1000, 1)
    tracer_cards: list[dict[str, Any]] = []
    tracer_ms = 0.0
    # broad/all = script-graph neighbors only. Never pay poly here — that was
    # the multi-second expand tax when structure was thin/already-expanded.
    if want_tracer:
        t_tr = time.perf_counter()
        tracer_cards = _tracer()
        tracer_ms = round((time.perf_counter() - t_tr) * 1000, 1)

    lexical: list[dict[str, Any]] = []
    if d in {"callers", "refs", "dependents"}:
        lexical = _lexical_caller_cards(rt, nid, k=max(k, 12), prior=prior)

    # Merge: lexical + structural first for callers; else tracer then fill gaps
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    if d in {"callers", "refs", "effects", "site", "broad", "dependents"}:
        order = lexical + struct + tracer_cards
    else:
        order = tracer_cards + struct + lexical
    for c in order:
        cid = str(c.get("id") or "")
        if not cid or cid == nid or cid in prior or cid in seen:
            continue
        seen.add(cid)
        c = dict(c)
        if cid in pack_seen:
            c["already_in_pack"] = True
        # Tag structural reverse edges
        why = str(c.get("why") or "")
        if "evidence" not in c and _expand_why_is_reverse(why):
            if "text_call" in why:
                c["evidence"] = "text_call"
            elif "used_by" in why.lower():
                c["evidence"] = "used_by"
            elif "called_by" in why.lower():
                c["evidence"] = "called_by"
        merged.append(c)
        if len(merged) >= k * 3:
            break
    # Leaf expand: ensure same-file public siblings are candidates (blind put_span miss).
    seen_ids = {str(c.get("id") or "") for c in merged}
    for sib in _same_file_public_sibling_cards(rt, seed, prior=prior | seen_ids, k=8):
        merged.append(sib)
        seen_ids.add(str(sib.get("id") or ""))
    merged = rank_expand_delta(
        merged,
        seed_file=seed.file,
        query=q,
        direction=d,
        seed_symbol=seed.symbol,
    )
    delta = merged[:k]
    for i, c in enumerate(delta, 1):
        c["rank"] = i

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
            "direction=callers|effects|broad when the first pack was too strict. "
            "already_in_pack=true means hop was on the lean heatmap — still useful for climb."
        ),
        "next_actions": next_actions,
        "howto": _HEATMAP_HOWTO,
        "ladder": "map → pack(lean) → expand(delta[,with_bodies]) — ≤3 calls",
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        "timings": {
            "struct_ms": struct_ms,
            "tracer_ms": tracer_ms,
            "tracer_used": bool(tracer_cards),
        },
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
    out: dict[str, Any] = {
        "ok": True,
        "tool": "collect_hot_context",
        "threshold": threshold,
        "bodies": bodies,
        "count": len(bodies),
        "chars": used,
        "empty_bodies": len(bodies) == 0,
        "guide": "Prefer native Read; this batch is an escape hatch. Pass ids= to fill specific delta cards.",
        "next_actions": [
            {
                "tool": "expand_context",
                "when": "still missing a hop",
                "args": {"direction": "callees", "with_bodies": True},
            }
        ],
        "next": (
            "Native-Read heatmap loc spans, or retry collect_hot_context(ids=file::symbol)."
            if not bodies
            else "Continue with returned bodies; expand_context if a hop is still missing."
        ),
    }
    if not bodies:
        out["hint"] = (
            "No bodies collected — ids missing from index, already packed, "
            "or below threshold. Pass ids= from heatmap locs, or Native-Read "
            "file:start-end spans."
        )
    return out


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


def _enclosing_public_class(
    nodes: dict[str, TraceNode],
    *,
    file: str,
    seed_symbol: str,
    seed_line: int = 0,
) -> TraceNode | None:
    """Largest public class in file that covers the seed (or any public class if none cover)."""
    file_n = file.replace("\\", "/")
    leaf = (seed_symbol or "").rsplit(".", 1)[-1]
    classes = [
        n
        for n in nodes.values()
        if n.file.replace("\\", "/") == file_n
        and n.kind == "class"
        and not is_weak_seed_symbol(n.symbol)
        and _seed_symbol_penalty(n.symbol) < 20
    ]
    if not classes:
        return None
    covering = [
        n
        for n in classes
        if seed_line > 0 and n.start_line <= seed_line <= n.end_line
    ]
    if covering:
        covering.sort(key=lambda n: (-(n.end_line - n.start_line), n.start_line))
        return covering[0]
    # Qualified Class.method → prefer Class
    if "." in (seed_symbol or ""):
        head = seed_symbol.rsplit(".", 1)[0]
        for n in classes:
            if n.symbol == head or n.symbol.endswith("." + head) or n.symbol.split(".")[-1] == head:
                return n
    classes.sort(key=lambda n: (-(n.end_line - n.start_line), n.start_line))
    # Don't reseed to a class named like the leaf method
    for n in classes:
        if n.symbol.split(".")[-1] != leaf:
            return n
    return classes[0]


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
    seed3_file: str = "",
    seed3_symbol: str = "",
    seed3_line: int = 0,
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
    _allow_broad_reseed: bool = True,
    _allow_subclass_hop: bool = True,
) -> dict[str, Any]:
    """Heatmap (+ optional hot bodies). mode=lean (default) minimizes tokens; mode=full is larger.

    policy=strict uses the selected tracer (default composite_v1 via CTX_TRACE_ENGINE).
    policy=broad temporarily uses polytrace for this pack only — escape hatch when the
    lean slice is too tight (ignored when ``engine`` is an explicit multi-pack tool).
    When broad still yields a thin leaf method, one-shot reseed to enclosing public class.
    When a class seed packs file-local (e.g. Conductor), one-shot hop to richer subclass.

    ``engine`` selects a shipped pack binder: composite_v1 | poly_embed |
    semantic_tracer_fuse | polytrace | ultimate. MCP exposes these as separate tools.

    ``include_bodies=False`` (MCP default): return heatmap/chain/cold locs only —
    agent Native-Reads top heated ``loc`` spans. Use ``collect_hot_context`` for bodies.
    """
    import os

    t0 = time.perf_counter()
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
    wanted_broad = policy_n == "broad" and _is_default_pack_engine(engine_n)
    broad_escape = wanted_broad
    # P0 blind feedback: leaf helpers must not burn ~48s on polytrace.
    # Prefer class reseed (strict) first; if no denser class on a leaf, skip polytrace
    # and pack once with composite, then report escape_helped=false.
    if wanted_broad and _allow_broad_reseed and (seed_file or seed_symbol):
        try:
            rt_pf = _load_repo(root)
            sn_pf = resolve_seed_node(
                rt_pf.nodes,
                file=seed_file,
                symbol=seed_symbol,
                start_line=int(seed_line or 0),
            )
            if sn_pf is not None and sn_pf.kind in {"function", "method"}:
                cls_pf = _enclosing_public_class(
                    rt_pf.nodes,
                    file=sn_pf.file,
                    seed_symbol=sn_pf.symbol,
                    seed_line=sn_pf.start_line,
                )
                if cls_pf is not None and cls_pf.symbol != sn_pf.symbol:
                    denser = run_pack_context(
                        root,
                        query,
                        seed_file=cls_pf.file,
                        seed_symbol=cls_pf.symbol,
                        seed_line=0,
                        seed2_file=seed2_file,
                        seed2_symbol=seed2_symbol,
                        seed2_line=seed2_line,
                        seed3_file=seed3_file,
                        seed3_symbol=seed3_symbol,
                        seed3_line=seed3_line,
                        k=k,
                        hot_threshold=hot_threshold,
                        budget_chars=budget_chars,
                        max_bodies=max_bodies,
                        mode=mode_n,
                        policy="strict",
                        drop_noise=drop_noise,
                        prior_packed_ids=prior_packed_ids,
                        engine=PROD_PACK_ENGINE,
                        tool_name=tool_name,
                        include_bodies=include_bodies,
                        _allow_broad_reseed=False,
                        _allow_subclass_hop=_allow_subclass_hop,
                    )
                    if denser.get("ok"):
                        helped = (not denser.get("thin")) or int(denser.get("count") or 0) > 3
                        denser["policy"] = policy_n
                        denser["escape_helped"] = bool(helped)
                        denser["escape_reseed"] = {
                            "from": sn_pf.symbol,
                            "to": cls_pf.symbol,
                        }
                        denser["escape"] = {
                            "reason": "policy=broad",
                            "from": PROD_PACK_ENGINE,
                            "to": "class_reseed_strict",
                        }
                        if not helped:
                            denser["next"] = (
                                "escape_helped=false — broad class reseed did not densify; "
                                "expand_context or Native-Read seed file; do not re-pack / re-broad thrash."
                            )
                            denser["prefer"] = "expand_context|Native-Read seed file"
                        denser["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                        return denser
                # Weak leaf with no enclosing class — skip polytrace burn.
                if _is_leaf_helper_seed(sn_pf.symbol, query=""):
                    broad_escape = False
        except Exception:  # noqa: BLE001
            pass

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
            seed3_file=seed3_file,
            seed3_symbol=seed3_symbol,
            seed3_line=seed3_line,
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
    # Never ship an empty heatmap when we have a resolvable seed (broad/polytrace flap).
    if not cards:
        try:
            rt0 = _load_repo(root)
            sn0 = resolve_seed_node(
                rt0.nodes,
                file=seed_file,
                symbol=seed_symbol,
                start_line=int(seed_line or 0),
            )
            if sn0 is not None:
                cards = [
                    {
                        "id": sn0.id,
                        "file": sn0.file,
                        "symbol": sn0.symbol,
                        "kind": sn0.kind,
                        "role": card_role(sn0.file, sn0.kind),
                        "start_line": sn0.start_line,
                        "end_line": sn0.end_line,
                        "loc": f"{sn0.file}:{sn0.start_line}-{sn0.end_line}",
                        "score": 0.5,
                        "heat": "warm",
                        "rank": 1,
                        "why": "seed_fallback",
                    }
                ]
                mapped["seed"] = {
                    "file": sn0.file,
                    "symbol": sn0.symbol,
                    "id": sn0.id,
                    "kind": sn0.kind,
                    "start_line": sn0.start_line,
                }
        except Exception:  # noqa: BLE001
            pass

    # Thin seed densify: class→contains/methods; function→calls/called_by/uses;
    # still thin class → same-file public siblings (CapabilityCard next to CapabilityIndex).
    seed_meta0 = mapped.get("seed") or {}
    if len(cards) <= 3:
        try:
            rt_i = _load_repo(root)
            sid = str(seed_meta0.get("id") or "")
            sn = rt_i.nodes.get(sid) if sid else None
            if sn is None:
                sn = resolve_seed_node(
                    rt_i.nodes,
                    file=str(seed_meta0.get("file") or seed_file),
                    symbol=str(seed_meta0.get("symbol") or seed_symbol),
                )
            if sn is not None and rt_i.graph is not None:
                seen_ids = {str(c.get("id") or "") for c in cards}
                extras: list[dict[str, Any]] = []

                def _add_extra(n: Any, rel: str, w: float = 1.0) -> None:
                    if n is None or n.id in seen_ids:
                        return
                    leaf = n.symbol.split(".")[-1]
                    if is_weak_seed_symbol(n.symbol) or leaf.startswith("_"):
                        return
                    seen_ids.add(n.id)
                    extras.append(
                        {
                            "id": n.id,
                            "file": n.file,
                            "symbol": n.symbol,
                            "kind": n.kind,
                            "role": card_role(n.file, n.kind),
                            "start_line": n.start_line,
                            "end_line": n.end_line,
                            "loc": f"{n.file}:{n.start_line}-{n.end_line}",
                            "score": min(0.85, 0.55 + 0.1 * float(w)),
                            "heat": "warm",
                            "rank": len(cards) + len(extras) + 1,
                            "why": f"{rel}:{sn.symbol}->{n.symbol}",
                        }
                    )

                if sn.kind == "class" or str(sn.symbol or "")[:1].isupper():
                    for vid, rel, w in rt_i.graph.neighbors(sn.id, directed=True):
                        if rel.lower() not in {"contains", "method"}:
                            continue
                        _add_extra(rt_i.nodes.get(vid), rel.lower(), w)
                        if len(extras) >= 8:
                            break
                    # Same-file public siblings when the class only has 1–2 methods.
                    # Skip DTO/payload structs (LocateHit, *Card) — they densify wrongly.
                    if len(cards) + len(extras) <= 3:
                        for n in rt_i.nodes.values():
                            if n.file != sn.file or n.id in seen_ids or n.id == sn.id:
                                continue
                            if n.kind not in {"class", "function"}:
                                continue
                            leaf_n = n.symbol.split(".")[-1]
                            if is_weak_seed_symbol(n.symbol) or leaf_n.startswith("_"):
                                continue
                            if n.kind == "class" and (
                                leaf_n.lower() in _WEAK_DTO_SEED_LEAVES
                                or any(leaf_n.endswith(suf) for suf in _WEAK_DTO_SUFFIXES)
                                or (leaf_n.endswith("Card") and "Index" in (sn.symbol or ""))
                            ):
                                continue
                            # Prefer API entrypoints / sibling indexes over glob helpers.
                            if n.kind == "function" and leaf_n.startswith(
                                ("glob_", "iter_", "expand_", "path_", "os_", "_")
                            ):
                                continue
                            _add_extra(n, "same_file", 1.0)
                            if len(extras) >= 6:
                                break
                elif sn.kind in {"function", "method"}:
                    # Prefer callers (called_by) before tiny callees so packs escape accessor islands.
                    rel_order = ("called_by", "calls", "uses", "contains", "method")
                    scored_nb: list[tuple[int, float, str, Any]] = []
                    for vid, rel, w in rt_i.graph.neighbors(sn.id, directed=True):
                        rl = rel.lower()
                        if rl not in rel_order:
                            continue
                        n = rt_i.nodes.get(vid)
                        if n is None:
                            continue
                        scored_nb.append((rel_order.index(rl), -float(w), rl, n))
                    scored_nb.sort(key=lambda t: (t[0], t[1]))
                    for _i, _w, rl, n in scored_nb:
                        _add_extra(n, rl, 1.0)
                        if len(extras) >= 8:
                            break
                if extras:
                    cards = cards + extras
                    for i, c in enumerate(cards, 1):
                        c["rank"] = i
        except Exception:  # noqa: BLE001
            pass

    # Multi-seed honesty: every accepted seed must appear in the heatmap.
    seed_metas: list[dict[str, Any]] = []
    for s in mapped.get("seeds") or []:
        if isinstance(s, dict):
            seed_metas.append(s)
    if not seed_metas:
        for key in ("seed", "seed2", "seed3"):
            s = mapped.get(key)
            if isinstance(s, dict) and (s.get("id") or s.get("file")):
                seed_metas.append(s)
    seed_coverage: dict[str, bool] = {}
    seed_injected: list[str] = []
    try:
        rt_cov = _load_repo(root)
        cards, seed_coverage, seed_injected = ensure_seeds_on_heatmap(
            cards, seed_metas, rt_cov.nodes, k=max(int(k), 16)
        )
    except Exception:  # noqa: BLE001
        seed_coverage = seed_coverage_report(
            cards, [str(s.get("id") or "") for s in seed_metas if s.get("id")]
        )
        seed_injected = []

    # Demote pause/home/id helpers unless the query asks for them.
    cards = apply_heat_affinity(cards, query)

    hot = [c for c in cards if float(c.get("score") or 0) >= hot_threshold]
    # Prefer packing hot first; if few hot, take top cards until budget
    to_pack = hot if hot else cards[: max(1, min(6, len(cards)))]
    seed_id = str((mapped.get("seed") or {}).get("id") or "")
    all_seed_ids = [str(s.get("id") or "") for s in seed_metas if s.get("id")]
    # Always surface accepted seeds first (lean budget used to bury seed2/seed3).
    prefer_ids = [sid for sid in all_seed_ids if sid] or ([seed_id] if seed_id else [])
    if prefer_ids:
        head = [c for c in to_pack if str(c.get("id") or "") in prefer_ids]
        missing = []
        have = {str(c.get("id") or "") for c in head}
        for sid in prefer_ids:
            if sid in have:
                continue
            seed_card = next((c for c in cards if str(c.get("id") or "") == sid), None)
            if seed_card is not None:
                missing.append(seed_card)
        rest = [c for c in to_pack if str(c.get("id") or "") not in prefer_ids]
        to_pack = head + missing + rest
    # Never skip seed bodies on a fresh pack — prior_packed is for continuation only.
    skip = set(prior_packed_ids or set())
    for sid in prefer_ids:
        skip.discard(sid)
    if include_bodies:
        collected = run_collect_hot(
            root,
            to_pack,
            threshold=0.0,  # already filtered list
            max_chars=max(500, int(budget_chars)),
            max_bodies=max_bodies,
            skip_ids=skip,
            prefer_ids=set(prefer_ids) if prefer_ids else None,
        )
    else:
        collected = {"bodies": [], "chars": 0}
    # Only real body ids count as packed — lean heatmap must NOT poison collect_hot skip.
    body_packed = {str(b.get("id")) for b in (collected.get("bodies") or []) if b.get("id")}
    hot_marked = set(body_packed)
    if not include_bodies:
        hot_marked = {
            str(c.get("id") or "")
            for c in to_pack[: max(1, int(max_bodies or 4))]
            if c.get("id")
        }
    packed_all = set(skip) | body_packed
    cold_locs = [
        _slim_card(c)
        for c in cards
        if c.get("id") not in hot_marked
    ]
    heatmap_slim = [_slim_card(c) for c in cards]
    chain = build_call_chain(cards, limit=8 if mode_n == "lean" else 12)
    incomplete = bool(include_bodies) and len(
        [c for c in to_pack if c.get("id") not in packed_all]
    ) > 0
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
            "when": "wrong seed — restart lean from a better card",
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
    elif mode_n == "lean" and not include_bodies:
        next_hint = (
            "Lean heatmap done — Native-Read hot locs; collect_hot_context(ids=) for bodies "
            "(not yet packed); expand_context only if a hop is missing."
        )
    elif mode_n == "lean" and len(cards) > len(body_packed):
        next_hint = (
            "Lean pack done — read chain+pack; expand_context(direction=callees|callers|effects) "
            "only if a hop is missing."
        )

    persist = mapped.pop("_persist", {}) or {}
    persist["cards"] = cards
    persist["scores"] = {c["id"]: c.get("score") for c in cards if c.get("id")}
    # Persist only real body ids so collect_hot_context can fill lean heatmap later.
    persist["packed_ids"] = sorted(str(x) for x in body_packed if x)
    persist["mode"] = mode_n
    persist["policy"] = policy_n
    if seed_id:
        persist["seed_id"] = seed_id
    persist["query"] = query

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
        guide = "BROAD PACK (polytrace escape + optional leaf→class densify) — " + guide
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
    # Leaf fast-fail skipped polytrace — still report broad escape metadata.
    if wanted_broad and not broad_escape and policy_n == "broad":
        engine_report = {
            **engine_report,
            "escape": {
                "reason": "policy=broad",
                "from": PROD_PACK_ENGINE,
                "to": "leaf_fastfail_composite",
            },
            "engine": PROD_PACK_ENGINE,
        }
    thin = heatmap_is_thin(cards)
    coverage_incomplete = bool(seed_coverage) and (not all(seed_coverage.values()))
    if coverage_incomplete:
        thin = True
    if thin:
        if coverage_incomplete:
            missing = [sid for sid, ok in seed_coverage.items() if not ok]
            next_hint = (
                f"thin=true — seed_coverage incomplete ({', '.join(missing[:3])}); "
                "expand_context on missing seed ids or Native-Read those locs; "
                "do not re-pack thrash."
            )
        else:
            next_hint = (
                "thin=true — expand_context(direction=callees|effects) or Native-Read seed file; "
                "do not re-pack thrash. Prefer public class seed if this was a _helper leaf."
            )

    # Class seed file-local → one-shot hop to richer public subclass (Conductor→MultiArch).
    seed_meta = mapped.get("seed") or {}
    seed_kind = str(seed_meta.get("kind") or "")
    if _allow_subclass_hop and (thin or _heatmap_is_file_local(cards, str(seed_meta.get("file") or seed_file))):
        try:
            rt = _load_repo(root)
            seed_node = resolve_seed_node(
                rt.nodes,
                file=seed_file,
                symbol=seed_symbol or str(seed_meta.get("symbol") or ""),
                start_line=int(seed_line or seed_meta.get("start_line") or 0),
            )
            if seed_node is not None and seed_kind != "class":
                seed_kind = seed_node.kind
            richer = None
            if seed_node is not None and seed_node.kind == "class":
                richer = _find_richer_subclass(rt.nodes, seed_node)
            if richer is not None and richer.symbol != (seed_node.symbol if seed_node else ""):
                denser = run_pack_context(
                    root,
                    query,
                    seed_file=richer.file,
                    seed_symbol=richer.symbol,
                    seed_line=0,
                    seed2_file=seed2_file,
                    seed2_symbol=seed2_symbol,
                    seed2_line=seed2_line,
                    seed3_file=seed3_file,
                    seed3_symbol=seed3_symbol,
                    seed3_line=seed3_line,
                    k=k,
                    hot_threshold=hot_threshold,
                    budget_chars=budget_chars,
                    max_bodies=max_bodies,
                    mode=mode_n,
                    policy=policy_n,
                    drop_noise=drop_noise,
                    prior_packed_ids=prior_packed_ids,
                    engine=engine,
                    tool_name=tool_name,
                    include_bodies=include_bodies,
                    _allow_broad_reseed=_allow_broad_reseed,
                    _allow_subclass_hop=False,
                )
                if denser.get("ok"):
                    new_cards = denser.get("heatmap") or denser.get("_persist", {}).get("cards") or []
                    # Never replace a non-empty pack with an empty broad/subclass result.
                    if not new_cards and heatmap_slim:
                        pass
                    else:
                        helped = (not denser.get("thin")) or (
                            not _heatmap_is_file_local(new_cards, richer.file)
                        ) or int(denser.get("count") or 0) > len(heatmap_slim)
                        denser["seed_promoted"] = {
                            "from": seed_node.symbol if seed_node else seed_symbol,
                            "to": richer.symbol,
                            "helped": bool(helped),
                        }
                        if helped:
                            return denser
        except Exception:  # noqa: BLE001
            pass

    # Broad densify: one-shot reseed leaf → enclosing public class (fast-fail if none).
    # Reseed uses policy=strict to avoid a second full polytrace burn (blind feedback: ~48s).
    escape_helped: bool | None = None
    broad_budget_s = float(os.environ.get("CTX_BROAD_ESCAPE_BUDGET_S", "3.0") or 3.0)
    broad_t0 = time.perf_counter()
    if (
        broad_escape
        and thin
        and _allow_broad_reseed
        and seed_kind in {"function", "method", ""}
        and (seed_symbol or seed_meta.get("symbol"))
    ):
        try:
            rt = _load_repo(root)
            seed_node = resolve_seed_node(
                rt.nodes,
                file=seed_file,
                symbol=seed_symbol or str(seed_meta.get("symbol") or ""),
                start_line=int(seed_line or seed_meta.get("start_line") or 0),
            )
            cls = None
            if seed_node is not None:
                cls = _enclosing_public_class(
                    rt.nodes,
                    file=seed_node.file,
                    seed_symbol=seed_node.symbol,
                    seed_line=seed_node.start_line,
                )
            if cls is None or cls.symbol == (seed_node.symbol if seed_node else ""):
                escape_helped = False
                next_hint = (
                    "escape_helped=false — no denser public class to reseed; "
                    "expand_context or Native-Read seed file; do not re-pack / re-broad thrash."
                )
            elif (time.perf_counter() - broad_t0) > broad_budget_s:
                escape_helped = False
                next_hint = (
                    "escape_helped=false — broad budget exhausted; "
                    "expand_context or Native-Read seed file; do not re-pack / re-broad thrash."
                )
            else:
                denser = run_pack_context(
                    root,
                    query,
                    seed_file=cls.file,
                    seed_symbol=cls.symbol,
                    seed_line=0,
                    seed2_file=seed2_file,
                    seed2_symbol=seed2_symbol,
                    seed2_line=seed2_line,
                    seed3_file=seed3_file,
                    seed3_symbol=seed3_symbol,
                    seed3_line=seed3_line,
                    k=k,
                    hot_threshold=hot_threshold,
                    budget_chars=budget_chars,
                    max_bodies=max_bodies,
                    mode=mode_n,
                    policy="strict",
                    drop_noise=drop_noise,
                    prior_packed_ids=prior_packed_ids,
                    engine=PROD_PACK_ENGINE,
                    tool_name=tool_name,
                    include_bodies=include_bodies,
                    _allow_broad_reseed=False,
                    _allow_subclass_hop=_allow_subclass_hop,
                )
                if denser.get("ok"):
                    new_n = int(denser.get("count") or 0)
                    new_heat = denser.get("heatmap") or []
                    if not new_heat and heatmap_slim:
                        escape_helped = False
                    else:
                        old_n = len(heatmap_slim)
                        helped = (not denser.get("thin")) or new_n > old_n
                        denser["escape_helped"] = helped
                        denser["escape_reseed"] = {
                            "from": seed_node.symbol if seed_node else seed_symbol,
                            "to": cls.symbol,
                        }
                        if not helped:
                            denser["next"] = (
                                "escape_helped=false — broad did not densify; "
                                "expand_context or Native-Read seed file; do not re-pack / re-broad thrash."
                            )
                            denser["prefer"] = "expand_context|Native-Read seed file"
                            if new_heat:
                                return denser
                        else:
                            return denser
                else:
                    escape_helped = False
        except Exception:  # noqa: BLE001
            escape_helped = False
        if escape_helped is None:
            escape_helped = False
        if escape_helped is False and not next_hint:
            next_hint = (
                "escape_helped=false — broad did not densify; "
                "expand_context or Native-Read seed file; do not re-pack / re-broad thrash."
            )

    if wanted_broad and not broad_escape and thin:
        escape_helped = False
        next_hint = (
            "escape_helped=false — no denser public class to reseed; "
            "expand_context or Native-Read seed file; do not re-pack / re-broad thrash."
        )

    out: dict[str, Any] = {
        "ok": True,
        "tool": tool_name,
        "query": mapped.get("query"),
        "seed": mapped.get("seed"),
        "seed2": mapped.get("seed2"),
        "seed3": mapped.get("seed3"),
        "seeds": mapped.get("seeds"),
        "multi_seed": mapped.get("multi_seed"),
        "seed_coverage": seed_coverage or None,
        "seed_injected": seed_injected or None,
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
        "thin": thin,
        "prefer": (
            "expand_context|Native-Read seed file"
            if thin
            else "Native-Read heatmap locs"
        ),
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
    if isinstance(mapped.get("timing"), dict):
        out["timing"] = mapped["timing"]
    if broad_escape:
        out["escape_helped"] = bool(escape_helped) if escape_helped is not None else (not thin)
    elif wanted_broad:
        out["escape_helped"] = False if escape_helped is None else bool(escape_helped)
        if out["escape_helped"] is False:
            out["prefer"] = "expand_context|Native-Read seed file"
    elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
    out["elapsed_ms"] = elapsed_ms
    # Pack is a heavy AST/trace path — surface SLA so agents don't treat
    # 15–20s as a hang (R7). Target: lean single-seed warm < 5s.
    lean_single_seed = (
        str(out.get("mode") or "lean") == "lean"
        and not bool(out.get("multi_seed") or out.get("seed2") or out.get("seed3"))
    )
    # Multi-seed target tightened after adaptive secondary skips (plan 2026-09-13).
    target_ms = 5000 if lean_single_seed else 8000
    out["sla"] = {
        "target_ms": target_ms,
        "elapsed_ms": elapsed_ms,
        "lean_single_seed": lean_single_seed,
        "profile": "lean_single_seed_warm" if lean_single_seed else "pack_multi_seed_warm",
    }
    if elapsed_ms > target_ms:
        out["sla_hint"] = (
            f"pack_context took {elapsed_ms}ms (target {target_ms}ms) — heavy path, "
            "not a hang. Prefer lean + one public seed when warm; multi-seed cold "
            "AST can still take several seconds."
        )
    return out


def persist_trace(repo: Path, session_id: str | None, payload: dict[str, Any]) -> None:
    if not payload:
        return
    try:
        from pipeline.session_store import load_store, save_store

        store = load_store(repo, session_id=session_id)
        prior = dict(store.get("context_trace") or {})
        prior_packed = set(prior.get("packed_ids") or [])
        new_packed = set(payload.get("packed_ids") or [])
        prior_expanded = set(prior.get("expanded_ids") or [])
        new_expanded = set(payload.get("expanded_ids") or [])
        store["context_trace"] = {
            "query": payload.get("query", prior.get("query")),
            "seed_id": payload.get("seed_id", prior.get("seed_id")),
            "cards": payload.get("cards") if "cards" in payload else (prior.get("cards") or []),
            "scores": payload.get("scores") if "scores" in payload else (prior.get("scores") or {}),
            "packed_ids": sorted(prior_packed | new_packed),
            "expanded_ids": sorted(prior_expanded | new_expanded),
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

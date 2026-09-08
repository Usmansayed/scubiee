"""Top-5 semantic tracer venture arms (research, feature-flagged).

Implements architectures from SCUBIEE_TOP5_SEMANTIC_TRACER_EXPERIMENTS.md:

  A1 venture_propose_verify  — vector proposes, structure verifies (1–2 hop)
  A2 venture_semantic_frontier — semantic-guided best-first (fuse core)
  A3 venture_multiview — multi-doc affinities (symbol / body / full), then propose
  A4 venture_trace_state — dynamic centroid from hot nodes → re-propose
  A5 venture_learned_heat — linear feature heat (proxy for learned ranker)

Default production remains composite_v1. Enable via compile_bundle with_embed_power
or CTX_TRACE_VENTURE=1 when registering.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Callable, Literal

from trace_lab.ast_graph import AstTraceGraph
from trace_lab.composite_v1 import bind_composite_v1, run_composite_v1
from trace_lab.embed_field import EmbedField, node_doc
from trace_lab.lsp_index import LspIndex
from trace_lab.semantic_teleport import _linked
from trace_lab.semantic_tracer_fuse import bind_semantic_tracer_fuse
from trace_lab.system_trace import _embed_query, _user_query
from trace_lab.types import GoldCase, HeatCell, Heatmap, TraceNode

VerifyMode = Literal["path1", "path2", "dfg_or_path1", "isolated_hi"]


def _env_on(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _hop_linked(
    uid: str,
    vid: str,
    graph: AstTraceGraph,
    lsp: LspIndex,
    extra: AstTraceGraph | None,
    *,
    hops: int,
) -> bool:
    if hops <= 1:
        return _linked(uid, vid, graph, lsp, extra)
    # BFS undirected up to `hops` on call/uses edges
    from collections import deque

    seen = {uid}
    q: deque[tuple[str, int]] = deque([(uid, 0)])
    while q:
        cur, d = q.popleft()
        if d >= hops:
            continue
        for dst, rel, _w in graph.neighbors(cur, directed=False):
            if rel not in {"calls", "uses", "contains", "dispatches", "overrides"}:
                continue
            if dst == vid:
                return True
            if dst not in seen:
                seen.add(dst)
                q.append((dst, d + 1))
        if extra is not None:
            for dst, _rel, _w in extra.neighbors(cur, directed=False):
                if dst == vid:
                    return True
                if dst not in seen and d + 1 <= hops:
                    seen.add(dst)
                    q.append((dst, d + 1))
    return _linked(uid, vid, graph, lsp, extra)


def _island_ids(hm: Heatmap, seed_id: str) -> set[str]:
    ids = {c.node_id for c in hm.cells if c.score >= 0.45}
    ids.add(seed_id)
    return ids


def _store_meta_for_root(root: Path) -> dict[str, Any]:
    """Load publication meta for *root*'s project store (empty dict if unavailable)."""
    try:
        import json

        from pipeline.project_id import resolve_project

        store = Path(resolve_project(Path(root)).store_dir)
        meta_path = store / "meta.json"
        if not meta_path.is_file():
            return {}
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _faiss_search_root(root: Path) -> Path:
    """Resolve which tree to search.

    Nested fixture trees often share the parent git ``project_id``. Prefer the
    store's recorded ``meta.root`` when *root* is nested inside it so we never
    treat fixture paths as a separate FAISS corpus under the product id.
    """
    root = Path(root).resolve()
    meta = _store_meta_for_root(root)
    meta_root = str(meta.get("root") or "").strip()
    if not meta_root:
        return root
    try:
        mr = Path(meta_root).resolve()
    except OSError:
        return root
    try:
        root.relative_to(mr)
        if root != mr:
            return mr
    except ValueError:
        pass
    return root


def _product_faiss_files(root: Path, query: str, *, top_k: int = 40) -> list[tuple[str, float]]:
    """Best-effort product FAISS hits → (file, score). Empty if index unavailable."""
    try:
        from pipeline.searcher import search_repo

        search_root = _faiss_search_root(Path(root))
        # Local engine only — do not probe unrelated daemons. Correct kwargs matter;
        # a TypeError here used to be swallowed and silently disabled FAISS proposal.
        hits = search_repo(search_root, query, top_k=top_k, use_server=False) or []
        out: list[tuple[str, float]] = []
        for h in hits:
            f = str(getattr(h, "file", None) or (h.get("file") if isinstance(h, dict) else "") or "")
            f = f.replace("\\", "/")
            sc = float(getattr(h, "score", None) or (h.get("score") if isinstance(h, dict) else 0.0) or 0.0)
            if f:
                out.append((f, sc))
        _product_faiss_files.last_error = ""  # type: ignore[attr-defined]
        _product_faiss_files.last_search_root = str(search_root)  # type: ignore[attr-defined]
        return out
    except Exception as exc:  # noqa: BLE001
        _product_faiss_files.last_error = f"{type(exc).__name__}: {exc}"  # type: ignore[attr-defined]
        _product_faiss_files.last_search_root = ""  # type: ignore[attr-defined]
        return []


_product_faiss_files.last_error = ""  # type: ignore[attr-defined]
_product_faiss_files.last_search_root = ""  # type: ignore[attr-defined]


def product_faiss_ok(root: Path, probe_query: str = "authenticate verify token") -> dict[str, Any]:
    """Preflight: product vector search must return ≥1 hit on an indexed root."""
    _product_faiss_files.last_error = ""  # type: ignore[attr-defined]
    root = Path(root).resolve()
    meta = _store_meta_for_root(root)
    meta_root = str(meta.get("root") or "")
    hits = _product_faiss_files(root, probe_query, top_k=8)
    err = getattr(_product_faiss_files, "last_error", "") or None
    contaminated = False
    if meta_root:
        try:
            mr = Path(meta_root).resolve()
            mr_s = str(mr).replace("\\", "/").lower()
            # Product checkout caller: refuse a fixture-only contaminated store.
            if "fixtures/trace-lab" in mr_s and "fixtures" not in str(root).replace("\\", "/").lower():
                contaminated = True
                err = err or f"store meta.root contaminated: {meta_root}"
        except OSError:
            pass
    return {
        "ok": (len(hits) > 0) and not contaminated,
        "n_hits": len(hits),
        "sample": hits[:3],
        "root": str(root),
        "meta_root": meta_root or None,
        "search_root": getattr(_product_faiss_files, "last_search_root", "") or None,
        "chunks": meta.get("chunks"),
        "error": err,
    }


def _resolve_file_to_nodes(
    file: str, nodes: dict[str, TraceNode], *, prefer_kinds: set[str] | None = None
) -> list[str]:
    prefer_kinds = prefer_kinds or {"function", "method"}
    file = file.replace("\\", "/")
    cands = [n for n in nodes.values() if n.file.replace("\\", "/") == file]
    primary = [n for n in cands if n.kind in prefer_kinds]
    use = primary or cands
    use = sorted(use, key=lambda n: (-len(n.text or ""), n.symbol))[:8]
    return [n.id for n in use]


def propose_and_verify(
    hm: Heatmap,
    *,
    seed_id: str,
    query: str,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lsp: LspIndex,
    field: EmbedField,
    extra_graph: AstTraceGraph | None,
    root: Path | None,
    strategy: str,
    top_k: int = 24,
    min_sem: float = 0.42,
    admit_floor: float = 0.48,
    verify: VerifyMode = "path2",
    use_product_faiss: bool = True,
) -> Heatmap:
    """Architecture 1 core: vector candidates → structural verification → admit."""
    by = {c.node_id: HeatCell(c.node_id, c.score, c.why, c.path, c.relation) for c in hm.cells}
    island = _island_ids(hm, seed_id)
    embed_q = query
    aff = field.affinities(embed_q)

    # Product FAISS: boost nodes in hit files
    faiss_boost: dict[str, float] = {}
    if use_product_faiss and root is not None:
        for f, sc in _product_faiss_files(root, query, top_k=max(top_k, 40)):
            for nid in _resolve_file_to_nodes(f, nodes):
                faiss_boost[nid] = max(faiss_boost.get(nid, 0.0), sc)

    scored: list[tuple[str, float, str]] = []
    for nid, sc in aff.items():
        if nid in island:
            continue
        n = nodes.get(nid)
        if n is None or n.kind == "class":
            continue
        name = n.symbol.rsplit(".", 1)[-1].lower()
        if name in {"log", "debug", "info", "warn", "error", "track"}:
            continue
        blended = float(sc)
        src = "embed_field"
        if nid in faiss_boost:
            blended = max(blended, 0.55 * blended + 0.45 * float(faiss_boost[nid]))
            src = "faiss+embed"
        if blended < min_sem:
            continue
        scored.append((nid, blended, src))

    scored.sort(key=lambda x: -x[1])
    admitted = 0
    hops = 1 if verify == "path1" else 2
    for nid, sc, src in scored[: top_k * 3]:
        if admitted >= top_k:
            break
        ok = False
        why_v = verify
        if verify == "isolated_hi":
            ok = sc >= 0.72
            why_v = "isolated_hi"
        else:
            ok = any(
                _hop_linked(a, nid, graph, lsp, extra_graph, hops=hops)
                for a in list(island)[:150]
            )
            if not ok and verify == "dfg_or_path1":
                ok = any(_linked(a, nid, graph, lsp, extra_graph) for a in list(island)[:100])
                why_v = "dfg_or_path1"
        if not ok:
            continue
        admit = max(admit_floor, min(1.0, sc))
        prev = by.get(nid)
        if prev is None or admit > prev.score:
            by[nid] = HeatCell(
                nid,
                round(admit, 4),
                f"venture_propose+{why_v} {src}={sc:.2f}",
                (seed_id, nid),
            )
        island.add(nid)
        admitted += 1

    cells = sorted(by.values(), key=lambda c: -c.score)
    meta = dict(hm.extra or {})
    meta.update(
        {
            "engine": strategy,
            "venture": "propose_verify",
            "verify": verify,
            "proposed_admitted": admitted,
            "faiss_files": len({f for f, _ in (_product_faiss_files(root, query, top_k=5) if root else [])}),
        }
    )
    return Heatmap(strategy=strategy, cells=cells, extra=meta)


def _multiview_affinities(field: EmbedField, nodes: dict[str, TraceNode], query: str) -> dict[str, float]:
    """Architecture 3: max of full / symbol-ish / body-ish query matches via field matrix."""
    # Reuse field matrix; approximate views by querying variants of the query text.
    views = [
        query,
        " ".join(t for t in query.replace("/", " ").replace(".", " ").split() if t[:1].islower() or "_" in t),
        query.split("\n")[0][:240],
    ]
    views = [v.strip() for v in views if v.strip()]
    if not views:
        views = [query]
    merged: dict[str, float] = {}
    for v in views:
        for nid, sc in field.affinities(v).items():
            merged[nid] = max(merged.get(nid, 0.0), float(sc))
    # Also boost symbol-name lexical hit in query
    qlow = query.lower()
    for nid, n in nodes.items():
        sym = n.symbol.rsplit(".", 1)[-1].lower()
        if len(sym) > 3 and sym in qlow:
            merged[nid] = max(merged.get(nid, 0.0), 0.55)
    return merged


def apply_trace_state_propose(
    hm: Heatmap,
    *,
    seed_id: str,
    query: str,
    nodes: dict[str, TraceNode],
    graph: AstTraceGraph,
    lsp: LspIndex,
    field: EmbedField,
    extra_graph: AstTraceGraph | None,
    root: Path | None,
    strategy: str,
) -> Heatmap:
    """Architecture 4: blend query with hot-node centroid proxy (concat top hot texts)."""
    hot = sorted(hm.cells, key=lambda c: -c.score)[:8]
    parts = [query.strip(), "", "## Trace state anchors"]
    for c in hot:
        n = nodes.get(c.node_id)
        if not n:
            continue
        parts.append(f"{n.symbol}: {(n.lex_text or n.text or '')[:400]}")
    state_q = "\n".join(parts)[:3500]
    # Run propose with state query on top of existing heatmap
    return propose_and_verify(
        hm,
        seed_id=seed_id,
        query=state_q,
        nodes=nodes,
        graph=graph,
        lsp=lsp,
        field=field,
        extra_graph=extra_graph,
        root=root,
        strategy=strategy,
        top_k=20,
        min_sem=0.40,
        verify="path2",
    )


def apply_learned_heat(
    hm: Heatmap,
    *,
    seed_id: str,
    query: str,
    nodes: dict[str, TraceNode],
    field: EmbedField,
    graph: AstTraceGraph,
    strategy: str,
) -> Heatmap:
    """Architecture 5 proxy: linear feature heat (train-free, research baseline)."""
    q_aff = field.affinities(query)
    # seed affinity
    seed_aff = {}
    try:
        import numpy as np

        sv = field.vec(seed_id)
        for nid in field.ids:
            seed_aff[nid] = float(sv @ field.vec(nid))
    except Exception:  # noqa: BLE001
        seed_aff = {nid: 0.0 for nid in field.ids}

    deg: dict[str, int] = {}
    for nid in nodes:
        deg[nid] = len(list(graph.neighbors(nid, directed=False)))

    by: dict[str, HeatCell] = {}
    for c in hm.cells:
        n = nodes.get(c.node_id)
        if not n:
            continue
        qsim = float(q_aff.get(c.node_id, 0.0))
        ssim = float(seed_aff.get(c.node_id, 0.0))
        d = deg.get(c.node_id, 0)
        hub = 1.0 / (1.0 + math.log1p(max(d, 0)))
        # Hand weights stand in for logistic until gold training lands
        logit = (
            1.2 * c.score
            + 0.9 * qsim
            + 0.5 * ssim
            + 0.35 * hub
            - 0.15 * (1.0 if n.kind == "class" else 0.0)
        )
        heat = 1.0 / (1.0 + math.exp(-logit + 0.8))
        by[c.node_id] = HeatCell(
            c.node_id,
            round(float(heat), 4),
            f"learned_proxy struct={c.score:.2f} q={qsim:.2f}",
            c.path,
            c.relation,
        )

    # Also propose high qsim outside island with path2 verify later via propose
    cells = sorted(by.values(), key=lambda x: -x.score)
    meta = dict(hm.extra or {})
    meta.update({"engine": strategy, "venture": "learned_heat_proxy"})
    return Heatmap(strategy=strategy, cells=cells, extra=meta)


def _embed_query_from_str(q: str) -> str:
    return q


def _wrap_composite(
    run_fn: Callable[..., Heatmap],
    *,
    root: Path,
    lsp: LspIndex,
    extra_graph: AstTraceGraph | None,
) -> Callable:
    def _run(case, nodes, graph, lex):
        return run_fn(case, nodes, graph, lex, root=root, lsp=lsp, extra_graph=extra_graph)

    return _run


def bind_venture_arms(
    tracers: dict[str, Any],
    root: Path,
    lsp: LspIndex,
    field: EmbedField,
    *,
    extra_graph: AstTraceGraph | None = None,
) -> None:
    """Register A1–A5 (+ combo A6) without replacing composite_v1."""
    base = bind_composite_v1(root, lsp, extra_graph)
    fuse = bind_semantic_tracer_fuse(root, lsp, field, extra_graph=extra_graph)

    def a1(case, nodes, graph, lex):
        hm = base(case, nodes, graph, lex)
        q = _embed_query(case)
        return propose_and_verify(
            hm,
            seed_id=case.seed.id,
            query=q,
            nodes=nodes,
            graph=graph,
            lsp=lsp,
            field=field,
            extra_graph=extra_graph,
            root=root,
            strategy="venture_propose_verify",
            verify="path2",
            use_product_faiss=True,
        )

    def a1_strict(case, nodes, graph, lex):
        hm = base(case, nodes, graph, lex)
        q = _embed_query(case)
        return propose_and_verify(
            hm,
            seed_id=case.seed.id,
            query=q,
            nodes=nodes,
            graph=graph,
            lsp=lsp,
            field=field,
            extra_graph=extra_graph,
            root=root,
            strategy="venture_propose_path1",
            verify="path1",
            top_k=16,
            min_sem=0.45,
        )

    def a2(case, nodes, graph, lex):
        # Architecture 2 ≈ fuse (semantic frontier / best-first)
        hm = fuse(case, nodes, graph, lex)
        hm.strategy = "venture_semantic_frontier"
        meta = dict(hm.extra or {})
        meta["venture"] = "semantic_frontier"
        hm.extra = meta
        return hm

    def a3(case, nodes, graph, lex):
        hm = base(case, nodes, graph, lex)
        q = _embed_query(case)
        # Temporarily swap affinities via propose using multiview scores
        mv = _multiview_affinities(field, nodes, q)

        class _MVField:
            ids = field.ids

            def affinities(self, _query: str):
                return mv

            def vec(self, nid: str):
                return field.vec(nid)

        return propose_and_verify(
            hm,
            seed_id=case.seed.id,
            query=q,
            nodes=nodes,
            graph=graph,
            lsp=lsp,
            field=_MVField(),  # type: ignore[arg-type]
            extra_graph=extra_graph,
            root=root,
            strategy="venture_multiview",
            verify="path2",
            use_product_faiss=True,
        )

    def a4(case, nodes, graph, lex):
        hm = base(case, nodes, graph, lex)
        q = _embed_query(case)
        return apply_trace_state_propose(
            hm,
            seed_id=case.seed.id,
            query=q,
            nodes=nodes,
            graph=graph,
            lsp=lsp,
            field=field,
            extra_graph=extra_graph,
            root=root,
            strategy="venture_trace_state",
        )

    def a5(case, nodes, graph, lex):
        hm = base(case, nodes, graph, lex)
        q = _embed_query(case)
        ranked = apply_learned_heat(
            hm,
            seed_id=case.seed.id,
            query=q,
            nodes=nodes,
            field=field,
            graph=graph,
            strategy="venture_learned_heat",
        )
        # Then allow modest proposal of high-qsim misses
        return propose_and_verify(
            ranked,
            seed_id=case.seed.id,
            query=q,
            nodes=nodes,
            graph=graph,
            lsp=lsp,
            field=field,
            extra_graph=extra_graph,
            root=root,
            strategy="venture_learned_heat",
            top_k=12,
            min_sem=0.48,
            verify="path2",
        )

    def a6(case, nodes, graph, lex):
        # A1 + A2: fuse island then propose-verify
        hm = fuse(case, nodes, graph, lex)
        q = _embed_query(case)
        return propose_and_verify(
            hm,
            seed_id=case.seed.id,
            query=q,
            nodes=nodes,
            graph=graph,
            lsp=lsp,
            field=field,
            extra_graph=extra_graph,
            root=root,
            strategy="venture_propose_plus_frontier",
            verify="path2",
            top_k=20,
        )

    tracers["venture_propose_verify"] = a1
    tracers["venture_propose_path1"] = a1_strict
    tracers["venture_semantic_frontier"] = a2
    tracers["venture_multiview"] = a3
    tracers["venture_trace_state"] = a4
    tracers["venture_learned_heat"] = a5
    tracers["venture_propose_plus_frontier"] = a6

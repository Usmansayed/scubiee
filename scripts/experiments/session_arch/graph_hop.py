"""GraphHop — SeedSpan + budgeted graph neighbors + BM25 confirm."""

from __future__ import annotations

import time
from typing import Any

from pipeline.engine import WarmSearchEngine

from .core import (
    SessionState,
    best_chunk_for_file,
    bm25_confirm_score,
    norm,
    pack_hit_span,
    query_state,
    read_span,
    reopen_memory_spans,
    retrieve_multishot,
    rubric,
)


def run_graph_hop(
    engine: WarmSearchEngine,
    mission: dict[str, Any],
    *,
    top_k: int = 8,
    max_chars_span: int = 700,
    expand_cap: int = 12,
    hop_keep: int = 4,
) -> SessionState:
    st = SessionState(arm="GraphHop")
    for turn in mission["turns"]:
        t0 = time.perf_counter()
        before = st.tokens_in
        opened: list[str] = []
        q = turn["queries"][0]
        st.add("goal", turn["goal"])

        used_full_search = True
        if turn.get("prefer_memory") and st.known_files:
            opened.extend(
                reopen_memory_spans(
                    engine,
                    st,
                    max_files=4,
                    max_chars=max_chars_span // 2,
                    prefer=list(turn.get("must_open") or turn.get("must_touch") or []),
                    must_avoid=list(turn.get("must_avoid") or []),
                )
            )
            if turn.get("memory_only"):
                used_full_search = False

        meta: dict[str, Any] = {}
        hits = []
        seeds: list[str] = list(st.last_turn_files[:4]) if turn.get("prefer_memory") else []
        avoid = list(turn.get("must_avoid") or [])
        seeds = [s for s in seeds if not any(a.lower() in s.lower() for a in avoid)]

        if used_full_search:
            hits, meta = retrieve_multishot(engine, q, top_k=top_k)
            st.ops.searches += max(1, len(meta.get("shots") or [1]))
            for h in hits:
                f0 = norm(h.file)
                if any(a.lower() in f0.lower() for a in avoid):
                    continue
                f = pack_hit_span(engine, st, h, max_chars=max_chars_span)
                if f:
                    opened.append(f)
                    seeds.append(f)

        # Prefer expand from session anchors / last turn, then seeds
        scored: list[tuple[float, str]] = []
        if not turn.get("memory_only"):
            expand_from = list(
                dict.fromkeys(
                    [norm(a.file) for a in st.anchors[-6:]]
                    + list(st.last_turn_files)
                    + seeds
                )
            )[:8]
            st.ops.expands += 1
            neighbors = engine.conductor.graph.neighbor_files(
                expand_from, cap=expand_cap
            )
            soft = query_state(q) == "SOFT" or bool(turn.get("must_avoid"))
            for nf in neighbors:
                n = norm(nf)
                if soft and any(
                    d in n.lower() for d in ("/figma_", "/seo_", "/dribbble")
                ):
                    continue
                if n in opened:
                    continue
                scored.append((bm25_confirm_score(engine, q, n), n))
            scored.sort(key=lambda x: -x[0])
            for _score, n in scored[:hop_keep]:
                c = best_chunk_for_file(engine, n)
                if c is None:
                    continue
                st.remember(n)
                st.ops.file_reads += 1
                st.add(
                    f"hop_span:{n}",
                    read_span(
                        engine.root,
                        n,
                        c.start_line,
                        c.end_line,
                        max_chars=max_chars_span // 2,
                    ),
                )
                opened.append(n)

        st.last_turn_files = list(dict.fromkeys(opened))
        st.retrieve_ms += (time.perf_counter() - t0) * 1000
        log = {
            "turn": turn["id"],
            "opened": opened,
            "tokens_delta": st.tokens_in - before,
            "hit_files": [norm(h.file) for h in hits],
            "retrieve_meta": meta,
            "prefer_memory": bool(turn.get("prefer_memory")),
            "used_full_search": used_full_search,
            "hops": [n for _, n in scored[:hop_keep]],
        }
        log.update(rubric(st, turn, opened=opened))
        st.turn_logs.append(log)
    return st

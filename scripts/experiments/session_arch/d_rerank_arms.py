"""Classic D_rerank baselines (no planner hops) for session_arch A/B."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from pipeline.engine import WarmSearchEngine

from .core import (
    SessionState,
    best_chunk_for_file,
    chunk_map,
    norm,
    pack_hit_span,
    read_span,
    reopen_memory_spans,
    retrieve_multishot,
    rubric,
)


def _read_full(root: Path, rel: str, *, max_chars: int) -> str:
    try:
        body = (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    return f"# {rel} (full)\n{body}"


def _oneshot_D(engine: WarmSearchEngine, query: str, *, top_k: int):
    qv = engine.embedder.embed_one(query, is_query=True)
    return engine.conductor.retrieve_D_rerank(query, qv, top_k=top_k)


def run_d_rerank_fullfile(
    engine: WarmSearchEngine,
    mission: dict[str, Any],
    *,
    top_k: int = 8,
    max_chars_span: int = 700,
    max_chars_file: int = 12000,
    use_multishot: bool = False,
    **_ignored: Any,
) -> SessionState:
    """Old baseline: D_rerank ranking + full-file dumps (token heavy)."""
    st = SessionState(arm="D_rerank_fullfile")
    for turn in mission["turns"]:
        t0 = time.perf_counter()
        before = st.tokens_in
        opened: list[str] = []
        q = turn["queries"][0]
        st.add("goal", turn["goal"])

        used_full_search = True
        if turn.get("prefer_memory") and st.known_files:
            for rel in st.known_files[:3]:
                st.ops.file_reads += 1
                st.ops.memory_reopens += 1
                st.add(
                    f"mem_full:{rel}",
                    _read_full(engine.root, rel, max_chars=max_chars_file // 2),
                )
                opened.append(rel)
            if turn.get("memory_only"):
                used_full_search = False

        hits = []
        meta: dict[str, Any] = {"mode": "D_oneshot"}
        if used_full_search:
            st.ops.searches += 1
            if use_multishot:
                hits, meta = retrieve_multishot(engine, q, top_k=top_k)
                st.ops.searches += max(0, len(meta.get("shots") or []) - 1)
                meta["mode"] = "D_multishot"
            else:
                hits = _oneshot_D(engine, q, top_k=top_k)
            seen = {norm(x) for x in opened}
            for h in hits:
                f = norm(h.file)
                if f in seen:
                    continue
                seen.add(f)
                st.remember(f)
                st.ops.file_reads += 1
                st.add(
                    f"full:{f}",
                    _read_full(engine.root, f, max_chars=max_chars_file),
                )
                opened.append(f)

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
        }
        log.update(rubric(st, turn, opened=opened))
        st.turn_logs.append(log)
    return st


def run_d_rerank_spans(
    engine: WarmSearchEngine,
    mission: dict[str, Any],
    *,
    top_k: int = 8,
    max_chars_span: int = 700,
    use_multishot: bool = False,
    **_ignored: Any,
) -> SessionState:
    """Old packing: D_rerank (or multishot) → spans only, no hops."""
    st = SessionState(arm="D_rerank_spans")
    by_id = chunk_map(engine)
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

        hits = []
        meta: dict[str, Any] = {"mode": "D_oneshot"}
        avoid = list(turn.get("must_avoid") or [])
        if used_full_search:
            st.ops.searches += 1
            if use_multishot:
                hits, meta = retrieve_multishot(engine, q, top_k=top_k)
                st.ops.searches += max(0, len(meta.get("shots") or []) - 1)
                meta["mode"] = "D_multishot"
            else:
                hits = _oneshot_D(engine, q, top_k=top_k)
            for h in hits:
                f0 = norm(h.file)
                if any(a.lower() in f0.lower() for a in avoid):
                    continue
                f = pack_hit_span(engine, st, h, max_chars=max_chars_span)
                if f:
                    opened.append(f)
                elif by_id.get(int(h.chunk_id)) is None:
                    c = best_chunk_for_file(engine, f0)
                    if c:
                        st.remember(f0)
                        st.ops.file_reads += 1
                        st.add(
                            f"span:{f0}",
                            read_span(
                                engine.root,
                                f0,
                                c.start_line,
                                c.end_line,
                                max_chars=max_chars_span,
                            ),
                        )
                        opened.append(f0)

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
        }
        log.update(rubric(st, turn, opened=opened))
        st.turn_logs.append(log)
    return st

"""SeedSpan — blind arrow + light session memory (control)."""

from __future__ import annotations

import time
from typing import Any

from pipeline.engine import WarmSearchEngine

from .core import (
    SessionState,
    norm,
    pack_hit_span,
    reopen_memory_spans,
    retrieve_multishot,
    rubric,
)


def run_seed_span(
    engine: WarmSearchEngine,
    mission: dict[str, Any],
    *,
    top_k: int = 8,
    max_chars_span: int = 700,
) -> SessionState:
    st = SessionState(arm="SeedSpan")
    for turn in mission["turns"]:
        t0 = time.perf_counter()
        before = st.tokens_in
        opened: list[str] = []
        q = turn["queries"][0]
        st.add("goal", turn["goal"])

        used_full_search = True
        prefer = list(turn.get("must_open") or turn.get("must_touch") or [])
        avoid = list(turn.get("must_avoid") or [])
        if turn.get("prefer_memory") and st.known_files:
            opened.extend(
                reopen_memory_spans(
                    engine,
                    st,
                    max_files=4,
                    max_chars=max_chars_span // 2,
                    prefer=prefer,
                    must_avoid=avoid,
                )
            )
            # T6-style memory-first: skip cold search if turn says so
            if turn.get("memory_only"):
                used_full_search = False

        meta: dict[str, Any] = {}
        hits = []
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

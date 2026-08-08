"""LspHop — SeedSpan + pyright definition/references hops."""

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
from .hop_utils import lsp_hop_from_seeds
from .lsp_client import PyrightLsp


def run_lsp_hop(
    engine: WarmSearchEngine,
    mission: dict[str, Any],
    *,
    top_k: int = 8,
    max_chars_span: int = 700,
    lsp: PyrightLsp | None = None,
) -> SessionState:
    st = SessionState(arm="LspHop")
    owns_lsp = False
    if lsp is None:
        lsp = PyrightLsp(engine.root)
        lsp.start()
        owns_lsp = True
    st.turn_logs.append(
        {
            "turn": "_lsp_status",
            "lsp_available": bool(lsp and lsp.available),
            "lsp_error": getattr(lsp, "error", None),
        }
    )

    try:
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
                        engine, st, max_files=4, max_chars=max_chars_span // 2
                    )
                )
                if turn.get("memory_only"):
                    used_full_search = False

            meta: dict[str, Any] = {}
            hits = []
            seeds: list[str] = (
                list(st.last_turn_files[:4]) if turn.get("prefer_memory") else []
            )

            if used_full_search:
                hits, meta = retrieve_multishot(engine, q, top_k=top_k)
                st.ops.searches += max(1, len(meta.get("shots") or [1]))
                for h in hits:
                    f = pack_hit_span(engine, st, h, max_chars=max_chars_span)
                    if f:
                        opened.append(f)
                        seeds.append(f)

            hops: list[str] = []
            if not turn.get("memory_only"):
                hops = lsp_hop_from_seeds(
                    engine,
                    st,
                    lsp,
                    q,
                    list(dict.fromkeys(seeds)),
                    max_chars=max_chars_span // 2,
                    already=opened,
                )
                opened.extend(hops)

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
                "lsp_hops": hops,
                "lsp_available": bool(lsp and lsp.available),
            }
            log.update(rubric(st, turn, opened=opened))
            st.turn_logs.append(log)
    finally:
        if owns_lsp and lsp is not None:
            lsp.shutdown()
    return st

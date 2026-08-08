"""OutlineHop — SeedSpan + file_outline guided hops (no LSP)."""

from __future__ import annotations

import time
from typing import Any

from pipeline.capability import file_outline
from pipeline.engine import WarmSearchEngine

from .core import (
    SessionState,
    best_chunk_for_file,
    chunk_covering_line,
    norm,
    pack_hit_span,
    query_terms,
    read_span,
    reopen_memory_spans,
    retrieve_multishot,
    rubric,
)


def _overlap(symbol: str, terms: list[str]) -> int:
    s = symbol.lower()
    return sum(1 for t in terms if t in s or s in t)


def run_outline_hop(
    engine: WarmSearchEngine,
    mission: dict[str, Any],
    *,
    top_k: int = 8,
    max_chars_span: int = 700,
    outline_picks: int = 3,
) -> SessionState:
    st = SessionState(arm="OutlineHop")
    for turn in mission["turns"]:
        t0 = time.perf_counter()
        before = st.tokens_in
        opened: list[str] = []
        q = turn["queries"][0]
        st.add("goal", turn["goal"])
        terms = query_terms(q)

        used_full_search = True
        # Related turns: start from remembered (file, symbol) anchors
        if turn.get("prefer_memory") and st.anchors:
            for a in st.anchors[-4:]:
                c = (
                    chunk_covering_line(engine, a.file, 1)
                    if not a.symbol
                    else best_chunk_for_file(engine, a.file)
                )
                # Prefer outline line if we stored symbol — re-outline cheaply
                if a.symbol:
                    st.ops.outlines += 1
                    for row in file_outline(engine.root, a.file):
                        if row.get("symbol") == a.symbol:
                            c = chunk_covering_line(
                                engine, a.file, int(row["line"])
                            )
                            break
                if c is None:
                    continue
                st.ops.memory_reopens += 1
                st.ops.file_reads += 1
                st.add(
                    f"anchor_span:{a.file}:{a.symbol or ''}",
                    read_span(
                        engine.root,
                        a.file,
                        c.start_line,
                        c.end_line,
                        max_chars=max_chars_span // 2,
                    ),
                )
                opened.append(a.file)
            # If anchors drifted (distractors), also reopen known seed files
            need = [x.lower() for x in (turn.get("must_open") or turn.get("must_touch") or [])]
            if need and not all(
                any(n in norm(f).lower() for f in opened) for n in need
            ):
                opened.extend(
                    reopen_memory_spans(
                        engine, st, max_files=6, max_chars=max_chars_span // 2
                    )
                )
            if turn.get("memory_only"):
                used_full_search = False
        elif turn.get("prefer_memory") and st.known_files:
            opened.extend(
                reopen_memory_spans(
                    engine, st, max_files=4, max_chars=max_chars_span // 2
                )
            )
            if turn.get("memory_only"):
                used_full_search = False

        meta: dict[str, Any] = {}
        hits = []
        seed_files: list[str] = []

        if used_full_search:
            hits, meta = retrieve_multishot(engine, q, top_k=top_k)
            st.ops.searches += max(1, len(meta.get("shots") or [1]))
            for h in hits:
                f = pack_hit_span(engine, st, h, max_chars=max_chars_span)
                if f:
                    opened.append(f)
                    seed_files.append(f)

        # Outline-guided hop on seed files
        for f in seed_files[:5]:
            st.ops.outlines += 1
            outline = file_outline(engine.root, f)
            ranked = sorted(
                outline,
                key=lambda row: -_overlap(str(row.get("symbol") or ""), terms),
            )
            picks = 0
            for row in ranked:
                if picks >= outline_picks:
                    break
                sym = str(row.get("symbol") or "")
                if _overlap(sym, terms) <= 0 and picks > 0:
                    continue
                line = int(row.get("line") or 1)
                c = chunk_covering_line(engine, f, line)
                if c is None:
                    continue
                st.remember(f, sym)
                st.ops.file_reads += 1
                st.add(
                    f"outline_span:{f}:{sym}",
                    read_span(
                        engine.root,
                        f,
                        c.start_line,
                        c.end_line,
                        max_chars=max_chars_span // 2,
                    ),
                )
                picks += 1

                # Second hop: BM25/grep-ish via dense D on symbol name
                if sym and "." not in sym:
                    st.ops.greps += 1
                    q2 = f"{sym} {q}"
                    hits2, _ = retrieve_multishot(engine, q2, top_k=3)
                    st.ops.searches += 1
                    for h2 in hits2[:1]:
                        f2 = norm(h2.file)
                        if f2 in opened:
                            continue
                        pack_hit_span(
                            engine,
                            st,
                            h2,
                            max_chars=max_chars_span // 2,
                            label="sym_hop",
                        )
                        opened.append(f2)
                        st.remember(f2, sym)

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

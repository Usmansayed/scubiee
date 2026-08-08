"""Shared hop helpers: graph neighbors + LSP def/refs packing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pipeline.capability import file_outline
from pipeline.engine import WarmSearchEngine

from .core import (
    SessionState,
    best_chunk_for_file,
    bm25_confirm_score,
    chunk_covering_line,
    norm,
    query_state,
    query_terms,
    read_span,
    soft_rewrite_queries,
)


def soft_demote(path: str) -> bool:
    p = path.lower().replace("\\", "/")
    return any(d in p for d in ("/figma_", "/seo_", "/dribbble", "/figma/"))


def pick_outline_symbols(
    engine: WarmSearchEngine,
    file_rel: str,
    query: str,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    terms = query_terms(query)
    outline = file_outline(engine.root, file_rel)
    if not outline:
        return []

    def score(row: dict[str, Any]) -> int:
        s = str(row.get("symbol") or "").lower()
        return sum(1 for t in terms if t in s or s.split(".")[-1] in t)

    ranked = sorted(outline, key=score, reverse=True)
    picks: list[dict[str, Any]] = []
    for row in ranked:
        if score(row) <= 0 and picks:
            continue
        picks.append(row)
        if len(picks) >= limit:
            break
    if not picks and outline:
        picks = outline[:1]
    return picks


def pack_file_line_span(
    engine: WarmSearchEngine,
    st: SessionState,
    file_rel: str,
    line: int,
    *,
    max_chars: int,
    label: str,
    symbol: str | None = None,
) -> str | None:
    rel = norm(file_rel)
    c = chunk_covering_line(engine, rel, line) or best_chunk_for_file(engine, rel)
    if c is None:
        return None
    st.remember(rel, symbol)
    st.ops.file_reads += 1
    st.add(
        f"{label}:{rel}",
        read_span(
            engine.root,
            rel,
            c.start_line,
            c.end_line,
            max_chars=max_chars,
        ),
    )
    return rel


def graph_hop_files(
    engine: WarmSearchEngine,
    st: SessionState,
    query: str,
    seeds: list[str],
    *,
    expand_cap: int,
    hop_keep: int,
    max_chars: int,
    already: list[str],
) -> list[str]:
    opened: list[str] = []
    expand_from = list(
        dict.fromkeys(
            [norm(a.file) for a in st.anchors[-6:]]
            + list(st.last_turn_files)
            + [norm(s) for s in seeds]
        )
    )[:8]
    if not expand_from:
        return opened
    st.ops.expands += 1
    neighbors = engine.conductor.graph.neighbor_files(expand_from, cap=expand_cap)
    soft = query_state(query) == "SOFT"
    scored: list[tuple[float, str]] = []
    opened_set = {norm(x) for x in already}
    cq = " ".join([query, *soft_rewrite_queries(query)])
    for nf in neighbors:
        n = norm(nf)
        if soft and soft_demote(n):
            continue
        if n in opened_set:
            continue
        scored.append((bm25_confirm_score(engine, cq, n), n))
    scored.sort(key=lambda x: -x[0])
    for _score, n in scored[:hop_keep]:
        if pack_file_line_span(
            engine, st, n, 1, max_chars=max_chars, label="graph_hop"
        ):
            opened.append(n)
            opened_set.add(n)
    return opened


def must_open_satisfied(turn: dict[str, Any], opened: list[str]) -> bool:
    need = turn.get("must_open") or turn.get("must_touch") or []
    if not need:
        return True
    opened_l = [norm(f).lower() for f in opened]
    return all(any(n.lower() in f for f in opened_l) for n in need)


def infer_goal(turn: dict[str, Any], query: str) -> str:
    if turn.get("memory_only"):
        return "memory"
    if turn.get("prefer_memory"):
        return "followup"
    q = query.lower()
    if any(
        w in q
        for w in (
            "executor",
            "dispatch",
            "registry",
            "handler",
            "binding",
            "wires",
            "invok",
            "callable",
            "lease",
            "compiled step",
            "invoked",
            "session store",
            "browser session",
            "manager",
        )
    ):
        return "wiring"
    return "locate"

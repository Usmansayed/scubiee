"""Shared session-arch experiment core: multishot seed + spans + session state.

Experiment only — does not change production engine defaults.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from conductor.conductor import Hit
from conductor.query_router import query_state
from pipeline.engine import WarmSearchEngine
from pipeline.token_meter import estimate_tokens


@dataclass
class Ops:
    searches: int = 0
    expands: int = 0
    outlines: int = 0
    greps: int = 0
    file_reads: int = 0
    memory_reopens: int = 0
    lsp_calls: int = 0
    planner_rounds: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class SessionAnchor:
    file: str
    symbol: str | None = None


@dataclass
class SessionState:
    arm: str
    known_files: list[str] = field(default_factory=list)
    anchors: list[SessionAnchor] = field(default_factory=list)
    tokens_in: int = 0
    retrieve_ms: float = 0.0
    ops: Ops = field(default_factory=Ops)
    turn_logs: list[dict[str, Any]] = field(default_factory=list)
    last_turn_files: list[str] = field(default_factory=list)

    def remember(self, rel: str, symbol: str | None = None) -> None:
        rel = norm(rel)
        if rel not in self.known_files:
            self.known_files.append(rel)
        if symbol:
            key = (rel, symbol)
            if not any((a.file, a.symbol) == key for a in self.anchors):
                self.anchors.append(SessionAnchor(file=rel, symbol=symbol))

    def add(self, label: str, text: str) -> int:
        if not text:
            return 0
        blob = f"##### {label} #####\n{text}"
        toks = estimate_tokens(blob)
        self.tokens_in += toks
        return toks


def norm(p: str) -> str:
    return p.replace("\\", "/").lstrip("./")


def rubric(
    st: SessionState,
    turn: dict[str, Any],
    *,
    opened: list[str] | None = None,
) -> dict[str, Any]:
    files = [norm(f).lower() for f in st.known_files]
    opened_l = [norm(f).lower() for f in (opened or [])]
    # Session awareness (cumulative): optional
    touch_need = turn.get("must_touch") or []
    touch_ok = all(any(need.lower() in f for f in files) for need in touch_need)
    # This-turn open (discriminates hops): if unset, fall back to must_touch on opened
    open_need = turn.get("must_open")
    if open_need is None:
        open_need = touch_need
    open_ok = all(any(need.lower() in f for f in opened_l) for need in open_need)
    avoid_hit: list[str] = []
    for bad in turn.get("must_avoid") or []:
        if any(bad.lower() in f for f in files):
            avoid_hit.append(bad)
    avoid_fail = False
    for bad in turn.get("must_avoid") or []:
        for f in opened_l:
            if bad.lower() in f and not any(
                need.lower() in f for need in (list(touch_need) + list(open_need))
            ):
                avoid_fail = True
                break
    return {
        "touch_ok": touch_ok,
        "open_ok": open_ok,
        "avoid_ok": not avoid_fail,
        "ok": touch_ok and open_ok and not avoid_fail,
        "avoid_hit": avoid_hit,
    }


def read_span(
    root: Path,
    rel: str,
    start: int,
    end: int,
    *,
    max_chars: int,
) -> str:
    try:
        lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    s = max(0, int(start) - 1)
    e = min(len(lines), max(int(end), s + 1))
    body = "\n".join(lines[s:e])
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    return f"# {rel}:{start}-{end}\n{body}"


def chunk_map(engine: WarmSearchEngine) -> dict[int, Any]:
    return {int(c.id): c for c in engine.chunks}


def best_chunk_for_file(engine: WarmSearchEngine, rel: str) -> Any | None:
    rel = norm(rel)
    for c in engine.chunks:
        if norm(c.file) == rel:
            return c
    return None


def chunk_covering_line(engine: WarmSearchEngine, rel: str, line: int) -> Any | None:
    rel = norm(rel)
    for c in engine.chunks:
        if norm(c.file) != rel:
            continue
        if int(c.start_line) <= line <= int(c.end_line):
            return c
    return best_chunk_for_file(engine, rel)


def query_terms(query: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", query)]


def bm25_confirm_score(engine: WarmSearchEngine, query: str, file_rel: str) -> float:
    """BM25 mass + path/name overlap (confirm hop candidates)."""
    terms = query_terms(query)
    if not terms:
        return 0.0
    rel = norm(file_rel)
    path_l = rel.lower()
    name = Path(rel).stem.lower()
    # Path / filename lexical boost (helps dispatch_registry vs random neighbors)
    path_boost = 0.0
    for t in terms:
        if t in path_l:
            path_boost += 2.0
        if t in name or name in t:
            path_boost += 3.0
    q = " ".join(terms[:12])
    try:
        scores = engine.conductor.bm25.score_all(q)
    except Exception:  # noqa: BLE001
        return path_boost
    best = 0.0
    for c in engine.chunks:
        if norm(c.file) != rel:
            continue
        cid = int(c.id)
        if 0 <= cid < len(scores):
            best = max(best, float(scores[cid]))
    return best + path_boost


def soft_rewrite_queries(query: str) -> list[str]:
    q = query.lower()
    out: list[str] = []
    agentish = any(
        w in q
        for w in (
            "agent",
            "should the",
            "what to do",
            "tell the",
            "tell it",
            "guidance",
            "note",
            "jot",
            "comment beside",
        )
    )
    session_fail = any(
        w in q
        for w in (
            "disappeared",
            "vanished",
            "unreachable",
            "session not found",
            "ended",
            "invalid",
            "missing",
            "went away",
            "tab",
            "browser tab",
        )
    )
    if agentish and (session_fail or "session" in q or "browser" in q):
        out.append("agent guidance session ended invalid")
        out.append("session not found Call perception_session_start again")
    playbook = any(
        w in q
        for w in (
            "playbook",
            "recovery",
            "health",
            "session_start",
            "observe",
            "spine",
        )
    )
    if playbook or (agentish and "recover" in q):
        out.append("MCP instructions health session_start observe playbook")
        out.append("agent guidance instructions recovery health session_start")
    if "guidance" in q or "note next" in q or "we found" in q or "already opened" in q:
        out.append("agent guidance session ended invalid")
    if any(w in q for w in ("lease", "unsafely", "share one browser", "step on")):
        out.append("browser_session_manager lock queue lease")
    if any(w in q for w in ("callable", "bound", "bindings", "tool name")):
        out.append("DispatchRegistry build perception_session_start handler")
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def retrieve_multishot(
    engine: WarmSearchEngine,
    query: str,
    *,
    top_k: int,
) -> tuple[list[Hit], dict[str, Any]]:
    state = query_state(query)
    shots = [query]
    rewrites = soft_rewrite_queries(query)
    if state == "SOFT" or rewrites:
        shots.extend(rewrites)

    shot_hit_lists: list[list[Hit]] = []
    shot_meta: list[dict[str, Any]] = []
    for i, q in enumerate(shots):
        qv = engine.embedder.embed_one(q, is_query=True)
        if i == 0:
            hits = engine.conductor.retrieve_R_plan(q, qv, top_k=max(top_k, 12))
        else:
            hits = engine.conductor.retrieve_D_rerank(q, qv, top_k=max(top_k, 10))
        shot_hit_lists.append(hits)
        shot_meta.append({"q": q, "top": [norm(h.file) for h in hits[:5]]})

    order = list(range(1, len(shot_hit_lists))) + ([0] if shot_hit_lists else [])
    if not order and shot_hit_lists:
        order = [0]

    demote = bool(rewrites) or state == "SOFT"
    merged: list[Hit] = []
    seen: set[str] = set()
    max_len = max((len(h) for h in shot_hit_lists), default=0)
    for rank in range(max_len):
        for si in order:
            hits = shot_hit_lists[si]
            if rank >= len(hits):
                continue
            h = hits[rank]
            f = norm(h.file)
            if demote and any(
                d in f.lower()
                for d in ("/figma_", "/seo_", "/dribbble", "/figma/", "ai_visibility")
            ):
                continue
            if f in seen:
                continue
            seen.add(f)
            merged.append(
                Hit(
                    chunk_id=h.chunk_id,
                    score=h.score,
                    file=h.file,
                    source=f"multishot:{si}",
                    graph=h.graph,
                    bm25=h.bm25,
                    dense=h.dense,
                )
            )
            if len(merged) >= top_k:
                return merged, {
                    "state": state,
                    "shots": shot_meta,
                    "pool": len(seen),
                    "merge": "interleave_rewrite_first",
                }

    return merged[:top_k], {
        "state": state,
        "shots": shot_meta,
        "pool": len(seen),
        "merge": "interleave_rewrite_first",
    }


def pack_hit_span(
    engine: WarmSearchEngine,
    st: SessionState,
    hit: Hit,
    *,
    max_chars: int,
    label: str = "span",
) -> str | None:
    f = norm(hit.file)
    by_id = chunk_map(engine)
    c = by_id.get(int(hit.chunk_id)) or best_chunk_for_file(engine, f)
    if c is None:
        return None
    st.remember(f)
    st.ops.file_reads += 1
    text = read_span(
        engine.root,
        f,
        c.start_line,
        c.end_line,
        max_chars=max_chars,
    )
    st.add(f"{label}:{f}", text)
    return f


def reopen_memory_spans(
    engine: WarmSearchEngine,
    st: SessionState,
    *,
    max_files: int,
    max_chars: int,
    prefer: list[str] | None = None,
    must_avoid: list[str] | None = None,
) -> list[str]:
    opened: list[str] = []
    avoid = [a.lower() for a in (must_avoid or [])]
    prefer_l = [p.lower() for p in (prefer or [])]

    def blocked(rel: str) -> bool:
        r = norm(rel).lower()
        return any(a in r for a in avoid)

    # Prefer files matching must_open / prefer stems first
    ordered: list[str] = []
    if prefer_l:
        for rel in st.known_files:
            if any(p in norm(rel).lower() for p in prefer_l) and not blocked(rel):
                ordered.append(rel)
    for rel in st.known_files:
        if rel not in ordered and not blocked(rel):
            ordered.append(rel)

    for rel in ordered[:max_files]:
        c = best_chunk_for_file(engine, rel)
        if c is None:
            continue
        st.ops.memory_reopens += 1
        st.ops.file_reads += 1
        st.add(
            f"mem_span:{rel}",
            read_span(
                engine.root,
                rel,
                c.start_line,
                c.end_line,
                max_chars=max_chars,
            ),
        )
        opened.append(rel)
    return opened


def pack_session(st: SessionState) -> dict[str, Any]:
    turns = [
        t
        for t in st.turn_logs
        if t.get("turn") and not str(t["turn"]).startswith("_")
    ]
    n = max(len(turns), 1)
    passed = sum(1 for t in turns if t.get("ok"))
    mem_turns = [t for t in turns if t.get("prefer_memory")]
    mem_ok = sum(1 for t in mem_turns if t.get("ok"))
    # T2/T6-style: related turns solved from anchors without full cold search
    no_cold = [
        t
        for t in mem_turns
        if t.get("ok") and t.get("used_full_search") is False
    ]
    return {
        "arm": st.arm,
        "tokens_total": st.tokens_in,
        "tokens_mean_turn": round(st.tokens_in / n, 1),
        "retrieve_ms": round(st.retrieve_ms, 1),
        "ops": st.ops.as_dict(),
        "rubric_pass_turns": passed,
        "rubric_total_turns": len(turns),
        "rubric_rate": round(passed / n, 4),
        "memory_turns": len(mem_turns),
        "memory_pass": mem_ok,
        "memory_hit_rate": round(mem_ok / max(len(mem_turns), 1), 4),
        "memory_no_cold_pass": len(no_cold),
        "memory_no_cold_rate": round(len(no_cold) / max(len(mem_turns), 1), 4),
        "known_files": st.known_files[:50],
        "anchors": [asdict(a) for a in st.anchors[:30]],
        "turns": turns,
        "meta": next(
            (t for t in st.turn_logs if str(t.get("turn") or "").startswith("_")),
            None,
        ),
    }

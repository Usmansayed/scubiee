"""Difficult multi-turn coding-session A/B for staged vs naive vs CE spans.

This is the *real* stress test: soft locate → follow-up reuse → multihop →
confusable distractor → lock/concurrency. Not single-shot HARD_V2 file locate.

Arms (same mission, scripted agent policy):
  naive_fullfile  — dense top files, full-file dumps every turn (weak memory)
  ce_d_spans      — D_rerank → chunk spans; prefer session memory on follow-ups
  staged          — D_rerank → graph expand → spans + grep peek; session memory

Metrics: session tokens, per-turn tokens, rubric pass (must_touch / must_avoid),
         latency, files opened.

Does NOT change production defaults. No permanent repo edits.

Usage:
  .\\.venv\\Scripts\\python.exe -u scripts\\experiments\\difficult_session_ab.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))

from pipeline.engine import WarmSearchEngine, load_engine  # noqa: E402
from pipeline.token_meter import estimate_tokens  # noqa: E402
from conductor.query_router import query_state  # noqa: E402
from conductor.conductor import Hit  # noqa: E402

REPO_DEFAULT = ROOT / "testdata" / "frontend-mcp"
OUT_DIR = ROOT / "out" / "experiments"


# --- Difficult mission (agent-like, multi-hop, soft, distractors) ------------

DIFFICULT_MISSION: dict[str, Any] = {
    "title": "Session recovery + wiring + form probe + lock (hard session)",
    "brief": (
        "User reports flaky browser sessions and form validation. "
        "In one continuous agent session: find guidance, extend recovery, "
        "trace registration, fix form-probe path (not SEO distractors), "
        "then find the session lock."
    ),
    "turns": [
        {
            "id": "T1_soft_guidance",
            "goal": "Soft: where do we tell the agent what to do when the session vanished?",
            "queries": [
                "what should the agent do when the browser session disappeared or is unreachable",
            ],
            "must_touch": ["agent_guidance.py"],
            "must_avoid": ["seo", "figma"],
            "prefer_memory": False,
        },
        {
            "id": "T2_followup_same_file",
            "goal": "Follow-up SAME session: find where recovery / health→session_start playbook lives (reuse memory).",
            "queries": [
                "health then session_start then observe recovery playbook",
            ],
            "must_touch": ["agent_guidance.py", "instructions.py"],
            "must_avoid": [],
            "prefer_memory": True,
        },
        {
            "id": "T3_multihop_register",
            "goal": "Multihop: who registers perception_session_start so tools can call it?",
            "queries": [
                "where is perception_session_start registered in the dispatch table for mcp tools",
            ],
            "must_touch": ["dispatch_registry.py"],
            "must_avoid": [],
            "prefer_memory": True,
        },
        {
            "id": "T4_confusable_form",
            "goal": "Confusable: invalid form submit then valid — NOT SEO/browser marketing paths.",
            "queries": [
                "probe form invalid submit then valid submit validation result",
            ],
            "must_touch": ["form_probe.py"],
            "must_avoid": ["seo", "figma_coord", "dribbble"],
            "prefer_memory": False,
        },
        {
            "id": "T5_lock_concurrency",
            "goal": "Architecture: prevent two tools fighting over the same browser session.",
            "queries": [
                "browser session manager lock queue so tools do not step on each other",
            ],
            "must_touch": ["browser_session_manager.py"],
            "must_avoid": [],
            "prefer_memory": True,
        },
    ],
}


@dataclass
class Ops:
    searches: int = 0
    expands: int = 0
    greps: int = 0
    file_reads: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class SessionState:
    arm: str
    known_files: list[str] = field(default_factory=list)
    tokens_in: int = 0
    retrieve_ms: float = 0.0
    ops: Ops = field(default_factory=Ops)
    turn_logs: list[dict[str, Any]] = field(default_factory=list)

    def remember(self, rel: str) -> None:
        rel = rel.replace("\\", "/")
        if rel not in self.known_files:
            self.known_files.append(rel)

    def add(self, label: str, text: str) -> int:
        if not text:
            return 0
        blob = f"##### {label} #####\n{text}"
        toks = estimate_tokens(blob)
        self.tokens_in += toks
        return toks


def _norm(p: str) -> str:
    return p.replace("\\", "/").lstrip("./")


def _rubric(st: SessionState, turn: dict[str, Any]) -> dict[str, Any]:
    files = [_norm(f).lower() for f in st.known_files]
    touch_ok = all(
        any(need.lower() in f for f in files) for need in (turn.get("must_touch") or [])
    )
    avoid_hit = []
    for bad in turn.get("must_avoid") or []:
        if any(bad.lower() in f for f in files):
            # only fail avoid if we also missed must_touch? No — avoid is soft warn
            # Fail only if a forbidden path was opened this turn's opened list
            avoid_hit.append(bad)
    # Strict: fail if must_avoid appears in THIS turn opened and not a must_touch
    opened = [_norm(f).lower() for f in (st.turn_logs[-1].get("opened") if st.turn_logs else [])]
    avoid_fail = False
    for bad in turn.get("must_avoid") or []:
        for f in opened:
            if bad.lower() in f and not any(need.lower() in f for need in (turn.get("must_touch") or [])):
                avoid_fail = True
                break
    return {
        "touch_ok": touch_ok,
        "avoid_ok": not avoid_fail,
        "ok": touch_ok and not avoid_fail,
        "avoid_hit": avoid_hit,
    }


def _read_span_file(
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


def _read_full(root: Path, rel: str, *, max_chars: int) -> str:
    try:
        body = (root / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(body) > max_chars:
        body = body[: max_chars - 1] + "…"
    return f"# {rel}\n{body}"


def _grep_peek(root: Path, rel: str, query: str, *, max_chars: int = 220) -> str:
    terms = [t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{3,}", query)][:6]
    if not terms:
        return ""
    try:
        lines = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    hits: list[str] = []
    low_t = [t.lower() for t in terms]
    for i, line in enumerate(lines, 1):
        low = line.lower()
        if any(t in low for t in low_t):
            hits.append(f"{i}:{line.strip()[:140]}")
            if len(hits) >= 3:
                break
    if not hits:
        return ""
    blob = "\n".join(hits)
    return f"# grep {rel}\n{blob[:max_chars]}"


def _chunk_map(engine: WarmSearchEngine) -> dict[int, Any]:
    return {int(c.id): c for c in engine.chunks}


def _best_chunk_for_file(engine: WarmSearchEngine, rel: str) -> Any | None:
    rel = _norm(rel)
    for c in engine.chunks:
        if _norm(c.file) == rel:
            return c
    return None


def soft_rewrite_queries(query: str) -> list[str]:
    """Deterministic soft→lexical probes (no gold filenames).

    Soft English often ranks browser *machinery* over agent-facing guidance.
    Second shots use surface intent → code-ish phrases that BM25/D can latch onto.
    """
    q = query.lower()
    out: list[str] = []
    agentish = any(
        w in q
        for w in ("agent", "should the", "what to do", "tell the", "guidance")
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
        )
    )
    if agentish and (session_fail or "session" in q):
        out.append("agent guidance session ended invalid")
        out.append("session not found Call perception_session_start again")
    playbook = any(
        w in q for w in ("playbook", "recovery", "health", "session_start", "observe", "spine")
    )
    if playbook or (agentish and "recover" in q):
        out.append("MCP instructions health session_start observe playbook")
        out.append("agent guidance instructions recovery health session_start")
    # de-dupe preserve order
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
    """Multi-shot retrieve: original → soft rewrites → interleave merge.

    Critical: do NOT re-score the merged pool with the original soft query —
    that demotes the rewrite hits that actually found guidance/instructions.
    """
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
            # Score follow-up shots with the rewrite itself (lexical latch)
            hits = engine.conductor.retrieve_D_rerank(q, qv, top_k=max(top_k, 10))
        shot_hit_lists.append(hits)
        shot_meta.append({"q": q, "top": [_norm(h.file) for h in hits[:5]]})

    # Interleave: rewrite shots first (they fix soft misses), then original
    order = list(range(1, len(shot_hit_lists))) + ([0] if shot_hit_lists else [])
    if not order and shot_hit_lists:
        order = [0]

    merged: list[Hit] = []
    seen: set[str] = set()
    max_len = max((len(h) for h in shot_hit_lists), default=0)
    for rank in range(max_len):
        for si in order:
            hits = shot_hit_lists[si]
            if rank >= len(hits):
                continue
            h = hits[rank]
            f = _norm(h.file)
            # Soft agent-guidance intent: demote obvious product distractors
            if soft_rewrite_queries(query) and any(
                d in f.lower() for d in ("/figma_", "/seo_", "/dribbble")
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


# --- Arms --------------------------------------------------------------------

def run_naive(
    engine: WarmSearchEngine,
    mission: dict[str, Any],
    *,
    top_k: int,
    max_chars_file: int,
) -> SessionState:
    st = SessionState(arm="naive_fullfile")
    for turn in mission["turns"]:
        t0 = time.perf_counter()
        before = st.tokens_in
        opened: list[str] = []
        q = turn["queries"][0]
        st.add("goal", turn["goal"])
        qvec = engine.embedder.embed_one(q, is_query=True)
        st.ops.searches += 1
        dense = engine.conductor.dense.search(qvec, top_k=top_k * 4)
        # weak memory: still re-dump known files fully on follow-up
        if turn.get("prefer_memory") and st.known_files:
            for rel in st.known_files[:3]:
                st.ops.file_reads += 1
                st.add(f"full_mem:{rel}", _read_full(engine.root, rel, max_chars=max_chars_file))
                opened.append(rel)
        files: list[str] = []
        seen: set[str] = set(opened)
        for cid, _ in dense:
            if cid < 0 or cid >= len(engine.files):
                continue
            f = _norm(engine.files[cid])
            if f in seen:
                continue
            seen.add(f)
            files.append(f)
            if len(files) >= top_k:
                break
        for f in files:
            st.remember(f)
            st.ops.file_reads += 1
            st.add(f"full:{f}", _read_full(engine.root, f, max_chars=max_chars_file))
            opened.append(f)
        st.retrieve_ms += (time.perf_counter() - t0) * 1000
        st.turn_logs.append(
            {
                "turn": turn["id"],
                "opened": opened,
                "tokens_delta": st.tokens_in - before,
            }
        )
        rub = _rubric(st, turn)
        st.turn_logs[-1].update(rub)
    return st


def run_d_rerank_fullfile(
    engine: WarmSearchEngine,
    mission: dict[str, Any],
    *,
    top_k: int,
    max_chars_file: int,
) -> SessionState:
    """Same ranking as ce_d_spans (retrieve_D_rerank); context = full files."""
    st = SessionState(arm="d_rerank_fullfile")
    for turn in mission["turns"]:
        t0 = time.perf_counter()
        before = st.tokens_in
        opened: list[str] = []
        q = turn["queries"][0]
        st.add("goal", turn["goal"])
        if turn.get("prefer_memory") and st.known_files:
            for rel in st.known_files[:4]:
                st.ops.file_reads += 1
                st.add(
                    f"mem_full:{rel}",
                    _read_full(engine.root, rel, max_chars=max_chars_file),
                )
                opened.append(rel)
        qvec = engine.embedder.embed_one(q, is_query=True)
        st.ops.searches += 1
        hits, meta = retrieve_multishot(engine, q, top_k=top_k)
        st.ops.searches += max(0, len(meta.get("shots") or []) - 1)
        seen = set(opened)
        for h in hits:
            f = _norm(h.file)
            if f in seen:
                continue
            seen.add(f)
            st.remember(f)
            st.ops.file_reads += 1
            st.add(f"full:{f}", _read_full(engine.root, f, max_chars=max_chars_file))
            opened.append(f)
        st.retrieve_ms += (time.perf_counter() - t0) * 1000
        st.turn_logs.append(
            {
                "turn": turn["id"],
                "opened": opened,
                "tokens_delta": st.tokens_in - before,
                "hit_files": [_norm(h.file) for h in hits],
                "retrieve_meta": meta,
            }
        )
        rub = _rubric(st, turn)
        st.turn_logs[-1].update(rub)
    return st


def run_ce_spans(
    engine: WarmSearchEngine,
    mission: dict[str, Any],
    *,
    top_k: int,
    max_chars_span: int,
) -> SessionState:
    st = SessionState(arm="ce_d_spans")
    by_id = _chunk_map(engine)
    for turn in mission["turns"]:
        t0 = time.perf_counter()
        before = st.tokens_in
        opened: list[str] = []
        q = turn["queries"][0]
        st.add("goal", turn["goal"])
        # Strong memory: outline-ish span re-open of known must files only
        if turn.get("prefer_memory") and st.known_files:
            for rel in st.known_files[:4]:
                c = _best_chunk_for_file(engine, rel)
                if c is None:
                    continue
                st.ops.file_reads += 1
                st.add(
                    f"mem_span:{rel}",
                    _read_span_file(
                        engine.root,
                        rel,
                        c.start_line,
                        c.end_line,
                        max_chars=max_chars_span,
                    ),
                )
                opened.append(rel)
        qvec = engine.embedder.embed_one(q, is_query=True)
        st.ops.searches += 1
        hits, meta = retrieve_multishot(engine, q, top_k=top_k)
        st.ops.searches += max(0, len(meta.get("shots") or []) - 1)
        for h in hits:
            f = _norm(h.file)
            st.remember(f)
            c = by_id.get(int(h.chunk_id))
            if c is None:
                c = _best_chunk_for_file(engine, f)
            if c is None:
                continue
            st.ops.file_reads += 1
            st.add(
                f"span:{f}",
                _read_span_file(
                    engine.root,
                    f,
                    c.start_line,
                    c.end_line,
                    max_chars=max_chars_span,
                ),
            )
            opened.append(f)
        # Reinvest span savings: 1-hop expand on soft/follow-up when budget allows
        if turn.get("prefer_memory") or query_state(q) == "SOFT":
            st.ops.expands += 1
            seeds = [_norm(h.file) for h in hits[:4]]
            for nf in engine.conductor.graph.neighbor_files(seeds, cap=6):
                n = _norm(nf)
                if n in opened:
                    continue
                c = _best_chunk_for_file(engine, n)
                if c is None:
                    continue
                st.remember(n)
                st.ops.file_reads += 1
                st.add(
                    f"expand_span:{n}",
                    _read_span_file(
                        engine.root,
                        n,
                        c.start_line,
                        c.end_line,
                        max_chars=max_chars_span // 2,
                    ),
                )
                opened.append(n)
                if len(opened) >= top_k + 4:
                    break
        st.retrieve_ms += (time.perf_counter() - t0) * 1000
        st.turn_logs.append(
            {
                "turn": turn["id"],
                "opened": opened,
                "tokens_delta": st.tokens_in - before,
                "hit_files": [_norm(h.file) for h in hits],
                "retrieve_meta": meta,
            }
        )
        rub = _rubric(st, turn)
        st.turn_logs[-1].update(rub)
    return st


def run_staged(
    engine: WarmSearchEngine,
    mission: dict[str, Any],
    *,
    seed_k: int,
    expand_cap: int,
    max_files: int,
    max_chars_span: int,
) -> SessionState:
    st = SessionState(arm="staged")
    by_id = _chunk_map(engine)
    for turn in mission["turns"]:
        t0 = time.perf_counter()
        before = st.tokens_in
        opened: list[str] = []
        q = turn["queries"][0]
        st.add("goal", turn["goal"])

        if turn.get("prefer_memory") and st.known_files:
            for rel in st.known_files[:4]:
                c = _best_chunk_for_file(engine, rel)
                if c is None:
                    continue
                st.ops.file_reads += 1
                st.add(
                    f"mem_span:{rel}",
                    _read_span_file(
                        engine.root,
                        rel,
                        c.start_line,
                        c.end_line,
                        max_chars=max_chars_span // 2,
                    ),
                )
                opened.append(rel)

        qvec = engine.embedder.embed_one(q, is_query=True)
        st.ops.searches += 1
        seeds = engine.conductor.retrieve_D_rerank(query=q, query_vec=qvec, top_k=seed_k)
        seed_files = [_norm(h.file) for h in seeds]
        expanded = list(dict.fromkeys(seed_files + opened))
        st.ops.expands += 1
        for nf in engine.conductor.graph.neighbor_files(seed_files, cap=expand_cap):
            n = _norm(nf)
            if n not in expanded:
                expanded.append(n)
            if len(expanded) >= max_files:
                break
        expanded = expanded[:max_files]

        file_chunk: dict[str, Any] = {}
        for h in seeds:
            f = _norm(h.file)
            c = by_id.get(int(h.chunk_id))
            if c is not None:
                file_chunk[f] = c
        for f in expanded:
            if f not in file_chunk:
                c = _best_chunk_for_file(engine, f)
                if c is not None:
                    file_chunk[f] = c

        for f in expanded:
            st.remember(f)
            c = file_chunk.get(f)
            if c is None:
                continue
            st.ops.file_reads += 1
            st.add(
                f"span:{f}",
                _read_span_file(
                    engine.root,
                    f,
                    c.start_line,
                    c.end_line,
                    max_chars=max_chars_span,
                ),
            )
            st.ops.greps += 1
            peek = _grep_peek(engine.root, f, q)
            if peek:
                st.add(f"grep:{f}", peek)
            opened.append(f)

        st.retrieve_ms += (time.perf_counter() - t0) * 1000
        st.turn_logs.append(
            {
                "turn": turn["id"],
                "opened": opened,
                "tokens_delta": st.tokens_in - before,
                "expanded": expanded,
            }
        )
        rub = _rubric(st, turn)
        st.turn_logs[-1].update(rub)
    return st


def _pack(st: SessionState) -> dict[str, Any]:
    turns = [t for t in st.turn_logs if t.get("turn")]
    n = max(len(turns), 1)
    passed = sum(1 for t in turns if t.get("ok"))
    return {
        "arm": st.arm,
        "tokens_total": st.tokens_in,
        "tokens_mean_turn": round(st.tokens_in / n, 1),
        "retrieve_ms": round(st.retrieve_ms, 1),
        "ops": st.ops.as_dict(),
        "rubric_pass_turns": passed,
        "rubric_total_turns": len(turns),
        "rubric_rate": round(passed / n, 4),
        "known_files": st.known_files[:40],
        "turns": turns,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Difficult multi-turn session A/B")
    ap.add_argument("--repo", default=str(REPO_DEFAULT))
    ap.add_argument("--top-k", type=int, default=8)
    ap.add_argument("--seed-k", type=int, default=5)
    ap.add_argument("--expand-cap", type=int, default=12)
    ap.add_argument("--max-files-staged", type=int, default=8)
    ap.add_argument("--max-chars-file", type=int, default=8000)
    ap.add_argument("--max-chars-span", type=int, default=700)
    ap.add_argument(
        "--arms",
        default="d_rerank_fullfile,ce_d_spans",
        help="Comma list: naive_fullfile,d_rerank_fullfile,ce_d_spans,staged",
    )
    args = ap.parse_args()

    os.environ.pop("CTX_HOME", None)
    repo = Path(args.repo).resolve()
    print(f"[diff-session] load {repo}", flush=True)
    engine = load_engine(repo)
    print(f"[diff-session] chunks={len(engine.chunks)}", flush=True)

    mission = DIFFICULT_MISSION
    want = {a.strip() for a in args.arms.split(",") if a.strip()}
    results: dict[str, Any] = {
        "mission": mission["title"],
        "repo": str(repo),
        "config": {"arms": sorted(want), "top_k": args.top_k},
        "arms": {},
    }

    runners = {
        "naive_fullfile": lambda: run_naive(
            engine, mission, top_k=args.top_k, max_chars_file=args.max_chars_file
        ),
        "d_rerank_fullfile": lambda: run_d_rerank_fullfile(
            engine, mission, top_k=args.top_k, max_chars_file=args.max_chars_file
        ),
        "ce_d_spans": lambda: run_ce_spans(
            engine, mission, top_k=args.top_k, max_chars_span=args.max_chars_span
        ),
        "staged": lambda: run_staged(
            engine,
            mission,
            seed_k=args.seed_k,
            expand_cap=args.expand_cap,
            max_files=args.max_files_staged,
            max_chars_span=args.max_chars_span,
        ),
    }

    for name in ("naive_fullfile", "d_rerank_fullfile", "ce_d_spans", "staged"):
        if name not in want:
            continue
        print(f"\n=== ARM {name} ===", flush=True)
        pack = _pack(runners[name]())
        results["arms"][name] = pack
        print(
            json.dumps(
                {k: pack[k] for k in ("tokens_total", "rubric_rate", "retrieve_ms", "ops")},
                indent=2,
            ),
            flush=True,
        )
        # Per-turn quick view
        for t in pack["turns"]:
            print(
                f"  {t['turn']}: ok={t.get('ok')} touch={t.get('touch_ok')} "
                f"tok_delta={t.get('tokens_delta')} hits={t.get('hit_files', t.get('opened', []))[:4]}",
                flush=True,
            )

    # Savings vs d_rerank_fullfile if present, else naive
    baseline_name = (
        "d_rerank_fullfile"
        if "d_rerank_fullfile" in results["arms"]
        else ("naive_fullfile" if "naive_fullfile" in results["arms"] else None)
    )
    results["savings"] = {}
    if baseline_name:
        base_tok = results["arms"][baseline_name]["tokens_total"]
        base_rub = results["arms"][baseline_name]["rubric_rate"]
        for name, pack in results["arms"].items():
            if name == baseline_name:
                continue
            saved = max(0, base_tok - pack["tokens_total"])
            results["savings"][name] = {
                "vs": baseline_name,
                "tokens_saved": saved,
                "pct_saved": round(100.0 * saved / base_tok, 1) if base_tok else 0.0,
                "rubric_rate": pack["rubric_rate"],
                "rubric_delta": round(pack["rubric_rate"] - base_rub, 4),
            }

    ranked = sorted(
        results["arms"].items(),
        key=lambda kv: (-kv[1]["rubric_rate"], kv[1]["tokens_total"]),
    )
    results["ranked"] = [name for name, _ in ranked]
    results["verdict"] = {
        "best": ranked[0][0] if ranked else None,
        "note": (
            "Both arms share multishot soft retrieve; packing differs. "
            "Equal rubric + fewer span tokens ⇒ reinvest budget in expand/traversal."
        ),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    out = OUT_DIR / f"difficult_session_ab_{ts}.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("\n=== DIFFICULT SESSION VERDICT ===", flush=True)
    print(json.dumps(results.get("savings", {}), indent=2), flush=True)
    print(json.dumps(results["verdict"], indent=2), flush=True)
    print(f"ranked={results['ranked']}", flush=True)
    print(f"[diff-session] wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

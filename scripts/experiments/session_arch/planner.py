"""Planner — goal-conditioned budgeted hops (graph + import/ident) with stop rule.

LSP removed: import-follow + identifier BM25/grep replace goto-def/refs.
"""

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
from .hop_utils import (
    graph_hop_files,
    infer_goal,
    must_open_satisfied,
)
from .symbol_hop import ident_bm25_grep_hop, import_hop_from_seeds


def run_planner(
    engine: WarmSearchEngine,
    mission: dict[str, Any],
    *,
    top_k: int = 8,
    max_chars_span: int = 700,
    max_rounds: int = 2,
    hop_keep: int = 4,
    expand_cap: int = 16,
    **_ignored: Any,
) -> SessionState:
    st = SessionState(arm="Planner")

    for turn in mission["turns"]:
        t0 = time.perf_counter()
        before = st.tokens_in
        opened: list[str] = []
        q = turn["queries"][0]
        goal = infer_goal(turn, q)
        st.add("goal", f"{turn['goal']} [planner:{goal}]")

        used_full_search = True
        prefer = list(turn.get("must_open") or turn.get("must_touch") or [])
        avoid = list(turn.get("must_avoid") or [])
        if turn.get("prefer_memory") and st.known_files:
            opened.extend(
                reopen_memory_spans(
                    engine,
                    st,
                    max_files=6 if turn.get("memory_only") else 4,
                    max_chars=max_chars_span // 2,
                    prefer=prefer,
                    must_avoid=avoid,
                )
            )
            if turn.get("memory_only"):
                used_full_search = False

        meta: dict[str, Any] = {}
        hits = []
        seeds: list[str] = (
            list(st.last_turn_files[:4]) if turn.get("prefer_memory") else []
        )
        # Don't seed hops from avoided distractors
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

        rounds_log: list[dict[str, Any]] = []
        # memory_only: never hop-expand (prevents token blowups from bad anchors)
        if not turn.get("memory_only"):
            for rnd in range(max_rounds):
                if must_open_satisfied(turn, opened):
                    break
                st.ops.planner_rounds += 1
                before_open = list(opened)
                # Tool order by goal — import/ident replace LSP
                if goal in ("wiring", "followup"):
                    order = ("import", "ident", "graph")
                elif goal == "memory":
                    order = ("import",)
                else:  # locate
                    order = ("import", "ident", "graph")

                seed_pool = [
                    s
                    for s in dict.fromkeys(seeds + opened)
                    if not any(a.lower() in s.lower() for a in avoid)
                ]
                # Cap fan-out when seeds are weak
                keep = hop_keep if seed_pool else 2
                for tool in order:
                    if must_open_satisfied(turn, opened):
                        break
                    if tool == "graph":
                        hops = graph_hop_files(
                            engine,
                            st,
                            q,
                            seed_pool,
                            expand_cap=expand_cap,
                            hop_keep=keep,
                            max_chars=max_chars_span // 2,
                            already=opened,
                        )
                        opened.extend(
                            [
                                x
                                for x in hops
                                if not any(a.lower() in x.lower() for a in avoid)
                            ]
                        )
                    elif tool == "import":
                        hops = import_hop_from_seeds(
                            engine,
                            st,
                            q,
                            seed_pool[:8],
                            max_chars=max_chars_span // 2,
                            already=opened,
                            keep=keep + 2,
                        )
                        opened.extend(
                            [
                                x
                                for x in hops
                                if not any(a.lower() in x.lower() for a in avoid)
                            ]
                        )
                    elif tool == "ident":
                        hops = ident_bm25_grep_hop(
                            engine,
                            st,
                            q,
                            seed_pool[:5],
                            max_chars=max_chars_span // 2,
                            already=opened,
                            keep=keep,
                        )
                        opened.extend(
                            [
                                x
                                for x in hops
                                if not any(a.lower() in x.lower() for a in avoid)
                            ]
                        )

                rounds_log.append(
                    {
                        "round": rnd,
                        "goal": goal,
                        "tools": list(order),
                        "new_files": [x for x in opened if x not in before_open],
                        "satisfied": must_open_satisfied(turn, opened),
                    }
                )
                if not rounds_log[-1]["new_files"]:
                    break

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
            "planner_goal": goal,
            "planner_rounds": rounds_log,
        }
        log.update(rubric(st, turn, opened=opened))
        st.turn_logs.append(log)
    return st

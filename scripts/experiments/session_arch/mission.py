"""Missions for session-arch A/B, including a difficulty ladder.

RELATED_SESSION_MISSION — original related multi-chat (often too easy; all arms 6/6).
HARD_HOP_MISSION — this-turn must_open targets that seed often misses but graph hop can hit.
HARDER_CHAIN_MISSION — multi-hop chain + distractors + memory reuse under tight top_k.
"""

from __future__ import annotations

from typing import Any

RELATED_SESSION_MISSION: dict[str, Any] = {
    "id": "related_v1",
    "title": "Related multi-chat session (guidance thread + side quest)",
    "brief": (
        "Continuous agent session: soft locate guidance, follow-up playbook, "
        "multihop register, form-probe side quest, session lock, then a tight "
        "memory-only follow-up on the guidance already found."
    ),
    "default_top_k": 8,
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
            "id": "T2_followup_playbook",
            "goal": "Follow-up SAME thread: health→session_start→observe playbook / instructions.",
            "queries": [
                "health then session_start then observe recovery playbook",
            ],
            "must_touch": ["agent_guidance.py", "instructions.py"],
            "must_avoid": [],
            "prefer_memory": True,
        },
        {
            "id": "T3_multihop_register",
            "goal": "Multihop from thread: who registers perception_session_start?",
            "queries": [
                "where is perception_session_start registered in the dispatch table for mcp tools",
            ],
            "must_touch": ["dispatch_registry.py"],
            "must_avoid": [],
            "prefer_memory": True,
        },
        {
            "id": "T4_confusable_form",
            "goal": "Side quest: form invalid then valid — not SEO/figma.",
            "queries": [
                "probe form invalid submit then valid submit validation result",
            ],
            "must_touch": ["form_probe.py"],
            "must_avoid": ["seo", "figma_coord", "dribbble"],
            "prefer_memory": False,
        },
        {
            "id": "T5_lock_concurrency",
            "goal": "Back to session thread: browser session lock / queue.",
            "queries": [
                "browser session manager lock queue so tools do not step on each other",
            ],
            "must_touch": ["browser_session_manager.py"],
            "must_avoid": [],
            "prefer_memory": True,
        },
        {
            "id": "T6_memory_note",
            "goal": "Tight follow-up: revisit guidance we already found (minimal cold RAG).",
            "queries": [
                "add a note next to the agent guidance we found for session recovery",
            ],
            "must_touch": ["agent_guidance.py"],
            "must_avoid": ["seo"],
            "prefer_memory": True,
            "memory_only": True,
        },
    ],
}


# Calibrated so SeedSpan @ top_k=4 often misses must_open while GraphHop
# neighbor expand from executor/runtime or session_store can hit.
HARD_HOP_MISSION: dict[str, Any] = {
    "id": "hard_hop_v1",
    "title": "Hard hop: seed-near / target-one-hop-away",
    "brief": (
        "Queries land on executor/runtime or session_store but not the true "
        "target; graph neighbors + BM25 confirm should open the target this turn. "
        "Scoring uses must_open (this-turn), not cumulative memory alone."
    ),
    "default_top_k": 4,
    "turns": [
        {
            "id": "H1_soft_guidance",
            "goal": "Cold soft: agent guidance for vanished session.",
            "queries": [
                "what should the agent do when the browser session disappeared or is unreachable",
            ],
            "must_touch": ["agent_guidance.py"],
            "must_open": ["agent_guidance.py"],
            "must_avoid": ["seo", "figma"],
            "prefer_memory": False,
        },
        {
            "id": "H2_dispatch_via_executor",
            "goal": "Seed near executor/runtime; open dispatch_registry this turn (1-hop).",
            "queries": [
                "which object the executor consults before invoking a tool handler",
            ],
            "must_touch": ["dispatch_registry.py"],
            "must_open": ["dispatch_registry.py"],
            "must_avoid": ["seo", "figma"],
            "prefer_memory": False,
        },
        {
            "id": "H3_manager_via_store",
            "goal": "Seed near session_store; open browser_session_manager this turn.",
            "queries": [
                "session store that holds active browser sessions for perception",
            ],
            "must_touch": ["browser_session_manager.py"],
            "must_open": ["browser_session_manager.py"],
            "must_avoid": ["seo", "figma_coord"],
            "prefer_memory": False,
        },
        {
            "id": "H4_form_distractor",
            "goal": "Form probe without SEO/figma distractors.",
            "queries": [
                "probe form invalid submit then valid submit validation result",
            ],
            "must_touch": ["form_probe.py"],
            "must_open": ["form_probe.py"],
            "must_avoid": ["seo", "figma_coord", "dribbble"],
            "prefer_memory": False,
        },
        {
            "id": "H5_bindings_from_memory",
            "goal": "Related follow-up: from executor thread, open dispatch bindings again.",
            "queries": [
                "after executor imports, where are tool name to handler bindings defined",
            ],
            "must_touch": ["dispatch_registry.py"],
            "must_open": ["dispatch_registry.py"],
            "must_avoid": [],
            "prefer_memory": True,
        },
        {
            "id": "H6_memory_guidance",
            "goal": "Memory-only revisit of guidance file.",
            "queries": [
                "add a note next to the agent guidance we found for session recovery",
            ],
            "must_touch": ["agent_guidance.py"],
            "must_open": ["agent_guidance.py"],
            "must_avoid": ["seo"],
            "prefer_memory": True,
            "memory_only": True,
        },
    ],
}


HARDER_CHAIN_MISSION: dict[str, Any] = {
    "id": "harder_chain_v1",
    "title": "Harder chain: vague hops + multi-open + distractors",
    "brief": (
        "Tighter top_k, vaguer wording, require opening hop targets this turn, "
        "plus a dual-open turn and a confusable soft turn."
    ),
    "default_top_k": 3,
    "turns": [
        {
            "id": "C1_guidance",
            "goal": "Soft guidance locate.",
            "queries": [
                "what should the agent do when the browser session disappeared or is unreachable",
            ],
            "must_open": ["agent_guidance.py"],
            "must_avoid": ["seo", "figma"],
            "prefer_memory": False,
        },
        {
            "id": "C2_runtime_lookup",
            "goal": "Vague: runtime looks up tool handler — need dispatch_registry via hop.",
            "queries": [
                "where does the runtime look up a tool handler before calling it",
            ],
            "must_open": ["dispatch_registry.py"],
            "must_avoid": ["seo", "figma"],
            "prefer_memory": False,
        },
        {
            "id": "C3_dual_open",
            "goal": "Same turn: open executor path AND the registry it consults.",
            "queries": [
                "execution runtime executor dispatches a named tool to its callable",
            ],
            "must_open": ["executor.py", "dispatch_registry.py"],
            "must_avoid": ["seo"],
            "prefer_memory": False,
        },
        {
            "id": "C4_store_to_manager",
            "goal": "Land on store; must open manager (graph), avoid figma browser.",
            "queries": [
                "map of session ids to live browser contexts",
            ],
            "must_open": ["browser_session_manager.py"],
            "must_avoid": ["figma", "seo"],
            "prefer_memory": False,
        },
        {
            "id": "C5_memory_dispatch",
            "goal": "Prefer memory from C2/C3; reopen registry without relying on lucky cold rank.",
            "queries": [
                "which object the executor consults before invoking a tool handler",
            ],
            "must_open": ["dispatch_registry.py"],
            "must_avoid": [],
            "prefer_memory": True,
        },
        {
            "id": "C6_form_soft",
            "goal": "Confusable form path.",
            "queries": [
                "probe form invalid submit then valid submit validation result",
            ],
            "must_open": ["form_probe.py"],
            "must_avoid": ["seo", "figma_coord", "dribbble"],
            "prefer_memory": False,
        },
        {
            "id": "C7_memory_only_guidance",
            "goal": "Memory-only guidance revisit.",
            "queries": [
                "add a note next to the agent guidance we found for session recovery",
            ],
            "must_open": ["agent_guidance.py"],
            "must_avoid": ["seo"],
            "prefer_memory": True,
            "memory_only": True,
        },
    ],
}


# Brutal: soft language, multi-file must_open, chain hops, strong distractors, tiny top_k
BRUTAL_MISSION: dict[str, Any] = {
    "id": "brutal_v1",
    "title": "Brutal: soft multihop chain + triple-open + distractors",
    "brief": (
        "Agent-like session where cold D_rerank often lands near-but-wrong; "
        "must_open forces this-turn coverage; avoid SEO/figma traps; "
        "memory turns must reopen anchors cheaply."
    ),
    "default_top_k": 3,
    "turns": [
        {
            "id": "B1_soft_vanished",
            "goal": "Soft: agent instructions when session vanished (not SEO).",
            "queries": [
                "the browser tab for the agent went away — what should we tell it to do next",
            ],
            "must_open": ["agent_guidance.py"],
            "must_avoid": ["seo", "figma", "dribbble"],
            "prefer_memory": False,
        },
        {
            "id": "B2_playbook_pair",
            "goal": "Same thread: open BOTH guidance and MCP instructions playbook.",
            "queries": [
                "where is the health then start then observe spine written for the agent",
            ],
            "must_open": ["agent_guidance.py", "instructions.py"],
            "must_avoid": ["seo", "figma"],
            "prefer_memory": True,
        },
        {
            "id": "B3_who_binds_tools",
            "goal": "Vague wiring: name→callable table (not tools.py catalog alone).",
            "queries": [
                "after the executor picks a tool name, where are the actual callables bound",
            ],
            "must_open": ["dispatch_registry.py"],
            "must_avoid": ["seo", "figma"],
            "prefer_memory": False,
        },
        {
            "id": "B4_triple_wiring",
            "goal": "One turn: executor + registry + handler runner path.",
            "queries": [
                "trace how a compiled step becomes an invoked mcp handler through the execution runtime",
            ],
            "must_open": [
                "executor.py",
                "dispatch_registry.py",
                "handler_runner.py",
            ],
            "must_avoid": ["seo"],
            "prefer_memory": True,
        },
        {
            "id": "B5_lease_not_figma",
            "goal": "Concurrency lease/queue owner — not figma community browser.",
            "queries": [
                "who owns the lease so two perception tools do not share one browser page unsafely",
            ],
            "must_open": ["browser_session_manager.py"],
            "must_avoid": ["figma", "seo", "dribbble"],
            "prefer_memory": False,
        },
        {
            "id": "B6_store_and_manager",
            "goal": "Dual open: session store record map AND the manager it leases from.",
            "queries": [
                "where session records live and which manager hands out the underlying browser",
            ],
            "must_open": ["session_store.py", "browser_session_manager.py"],
            "must_avoid": ["figma", "seo"],
            "prefer_memory": True,
        },
        {
            "id": "B7_form_not_marketing",
            "goal": "Form invalid→valid probe; avoid marketing/SEO paths.",
            "queries": [
                "drive a form through a failing submit then a succeeding one and capture validation",
            ],
            "must_open": ["form_probe.py"],
            "must_avoid": ["seo", "figma_coord", "dribbble", "ai_visibility"],
            "prefer_memory": False,
        },
        {
            "id": "B8_memory_only_note",
            "goal": "Cheap revisit of guidance only.",
            "queries": [
                "jot a comment beside the recovery guidance we already opened",
            ],
            "must_open": ["agent_guidance.py"],
            "must_avoid": ["seo"],
            "prefer_memory": True,
            "memory_only": True,
        },
    ],
}


MISSIONS: dict[str, dict[str, Any]] = {
    m["id"]: m
    for m in (
        RELATED_SESSION_MISSION,
        HARD_HOP_MISSION,
        HARDER_CHAIN_MISSION,
        BRUTAL_MISSION,
    )
}

DIFFICULTY_LADDER: list[str] = [
    "brutal_v1",
    "hard_hop_v1",
    "harder_chain_v1",
    "related_v1",
]

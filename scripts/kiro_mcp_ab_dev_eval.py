#!/usr/bin/env python3
"""One real development-task A/B: with Scubiee MCP vs without (Kiro auto).

WITH arm: Scubiee MCP only (no scubiee CLI locate). WITHOUT: native only.
Isolated snapshots (git init per arm) so edits cannot collide.
Outcome-focused prompt — no file/function spoilers.
Mandatory preflight: ask Kiro to exercise all Scubiee MCP locate tools.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
KIRO = Path(os.environ.get("KIRO_CLI", r"C:\Users\usman\AppData\Local\Kiro-Cli\kiro-cli.exe"))
BRIDGE = Path(os.environ.get("SCUBIEE_MCP_BRIDGE", r"C:\Users\usman\.local\bin\scubiee-mcp-bridge.EXE"))
PROJECT_ID = "ce_d9cb766c3820091ed9ffbc64ef33063c"
PROJECT_MCP = ROOT / ".kiro" / "settings" / "mcp.json"
USER_MCP = Path.home() / ".kiro" / "settings" / "mcp.json"
OUT_JSON = ROOT / "docs" / "superpowers" / "plans" / "2026-09-05-kiro-mcp-ab-dev.json"
OUT_MD = ROOT / "docs" / "superpowers" / "plans" / "2026-09-05-kiro-mcp-ab-dev.md"
# Snapshots must NOT live under repo `out/` — Scubiee skips `out/` in extract_nodes
# (pack then returns seed-not-found / empty heatmap). Keep workspaces outside that ban.
BASE = ROOT / ".ab_workspaces" / "kiro_ab_dev"

# Exclude heavy / volatile trees when snapshotting the dirty working tree.
_EXCLUDE_DIRS = {
    ".git",
    ".scubiee",
    "out",
    ".ab_workspaces",
    ".embed_cache",
    "models",
    "research",
    "dist",
    "build",
    "fixtures",
    "docs",
    ".worktrees",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cursor",
    ".kiro",  # rebuilt per arm
    "agent-transcripts",
    "vendor",
    "npm",
    "tools",
}

TASKS: dict[str, dict[str, Any]] = {
    "weak_start": {
        "title": "soft-locate bad-start recovery",
        "out_stem": "2026-09-05-kiro-cli-ab-dev",
        "prompt": """# Development task — soft-locate bad-start recovery

## Problem
When agents use this project's soft-locate / pack tools, they sometimes get a weak or unreliable starting point (for example something under tests or fixtures, or otherwise not a good production entry for the query). Today it is too easy to keep going from that bad start instead of recovering.

## Desired outcome
After a soft locate / pack completes, if the recommended starting point looks unreliable, the tool response must include a clear, actionable next step that tells the agent to remake the locate with a richer code-oriented query — not silently continue from the weak start.

If the starting point looks like normal production code for the query, do not spam false alarms; keep the existing happy path quiet.

## Requirements
1. Prefer a structured signal agents already consume for "what to do next" (next-step / next-action style guidance), rather than only burying a sentence in prose.
2. Cover the weak-start case with at least one automated test.
3. Cover the good-start / no-false-alarm case with at least one automated test (or an assertion in the same test module).
4. Do not break existing soft-locate / pack call shapes for happy-path callers.

## Constraints
- Stay in-process (no new network services).
- Keep the change small and reviewable.
- You may explore the codebase freely to find the right place — do not invent a parallel stack.
- Do not commit, push, or install packages globally. Local test runs are fine.

## Success criteria
- Weak/unreliable start → actionable remake-locate next step is present.
- Good production start → no false remake alarm.
- New/updated tests pass.
- Brief note in your final reply: what you changed and how to verify.

Implement this end-to-end. Explore first, then edit, then run the relevant tests yourself.
""",
        "test_keywords": (
            "suggested_seed",
            "next_actions",
            "weak seed",
            "weak_start",
            "remake",
            "start_reliability",
            "assess_start",
        ),
        "test_files": (
            "tests/test_incremental_context_ladder.py",
            "tests/test_soft_locate_weak_start.py",
        ),
    },
    "engine_visibility": {
        "title": "pack tracer-engine visibility + broad-escape honesty",
        "out_stem": "2026-09-05-kiro-cli-ab-dev2-engine",
        "prompt": """# Development task — make pack results honest about which tracer ran

## Problem
Operators and agents cannot tell, from a pack/locate response alone, which tracing engine actually built the heatmap — especially when a "broad" / escape path temporarily switches engines and then restores the default. That opacity makes debugging bad packs and measuring product behavior hard.

## Desired outcome
Every successful pack-style context response must expose a clear structured field naming the tracer engine that produced the slice (for example the production default vs an escape engine). When a temporary broad/escape switch was used for that call, the response must also say so in a structured way (that an escape happened, and what was restored), without breaking existing fields clients already read.

## Requirements
1. Happy-path default packs report the active production tracer engine in a stable structured key.
2. Broad/escape packs report both the engine that ran for the slice and that an escape/switch occurred (and restoration), in structured fields — not only buried in free-text guide strings.
3. Automated tests cover:
   - default path reports the expected production engine identity
   - broad/escape path reports escape + the engine used for that call
4. Do not break existing pack response shapes for callers that ignore the new fields.
5. Prefer extending the existing pack/trace pipeline over inventing a parallel API.

## Constraints
- In-process only; no new network services.
- Small, reviewable change.
- Explore the codebase yourself to find where pack builds its return payload and where broad/escape temporarily changes engines — the prompt will not name files or functions.
- Do not commit or push. Local tests are fine.

## Success criteria
- Default pack → structured engine identity present.
- Broad/escape pack → structured escape signal + engine identity present.
- Tests pass.
- Final reply explains what changed and how you verified.

Implement end-to-end: explore → edit → test.
""",
        # Avoid bare "engine"/"polytrace" — those pull half the suite and blow scoring.
        "test_keywords": (
            "trace_engine",
            "ctx_trace_engine",
            "composite_v1",
            "pack_engine",
            "engine_visibility",
            "broad_escape",
            "escape_engine",
            "run_pack_context",
        ),
        "test_files": (
            "tests/test_pack_engine_visibility.py",
            "tests/test_incremental_context_ladder.py",
        ),
    },
    "session_isolation": {
        "title": "shared-MCP session isolation fail-closed + dual-session proof",
        "out_stem": "2026-09-05-kiro-cli-ab-dev3-session",
        "prompt": """# Development task — stop cross-chat locate/pack leakage on a shared MCP process

## Problem
Two agent chats can share one MCP server process. Soft-locate / pack persistence (pins, packed bodies, heatmap handles) from chat A must never silently become chat B's context. Today it is too easy for a missing or ambiguous session identity to reuse the wrong store — which wastes tokens and produces wrong code slices.

## Desired outcome
When session isolation is enabled:
1. Locate/pack-style calls that persist session state must resolve a session identity.
2. If identity cannot be resolved, fail closed with a clear structured error (do not write into another chat's bucket, and do not pretend success).
3. Two different session identities must keep independent persisted locate/pack state (prove with tests).

## Requirements
1. Structured error when isolation is on and session cannot be resolved for a state-mutating locate/pack path.
2. Dual-session test: actions in session A do not appear as session B's persisted locate/pack state.
3. Happy path with a valid session id still works (no false failures).
4. Prefer fixing the existing session + locate/pack persistence pipeline — do not invent a second session system.
5. Keep the change reviewable; do not break hosts that already inject a session id.

## Constraints
- In-process only; no new network services.
- Explore the codebase yourself — this prompt will not name files or functions.
- Do not commit or push. Local tests are fine.
- Do not disable isolation to "make tests pass."

## Success criteria
- Isolation on + missing session → structured failure.
- Two sessions → isolated persisted state (test-proven).
- Valid session happy path still works.
- Final reply: what changed + how you verified.

Implement end-to-end: explore → edit → test.
""",
        # Keep narrow — bare "session"/"persist" match half the suite and blow the scorer timeout.
        "test_keywords": (
            "test_session_isolation",
            "session_isolation",
            "session_store",
            "_resolve_session",
            "fail closed",
            "fail_closed",
            "packed_ids",
            "mcp_session_isolate",
            "CTX_MCP_SESSION_ISOLATE",
        ),
        "test_files": (
            "tests/test_session_isolation.py",
            "tests/test_session_store.py",
            "tests/test_auto_sessions_observability.py",
        ),
    },
    "pack_bodies_optin": {
        "title": "MCP pack body opt-in actually collects bodies",
        "out_stem": "2026-09-06-kiro-cli-ab-dev4-pack-bodies",
        "prompt": """# Development task — make the documented pack-body opt-in actually return code bodies

## Problem
This project's MCP pack/locate tools advertise an environment-variable (and/or tool-flag) opt-in so that pack responses can include hot code bodies again. In practice, turning that opt-in on still yields heatmap/location-only responses with empty body lists — the collection step never runs, so the documented knobs for body budget / max bodies stay inert. Agents then either thrash Native-Read or call a separate collect path when they believed opt-in would be enough.

## Desired outcome
When the pack-body opt-in is enabled (env and/or explicit tool flag):
1. The pack tools that share the same implementation path actually collect and return hot bodies in the pack payload.
2. When the opt-in is off, keep today's default: compressed heatmap / locs without bodies (no regression for lean clients).
3. Field/docs language matches behavior (budget / max-bodies only matter when bodies are collected).

## Requirements
1. Opt-in on → successful pack-style responses can include non-empty body text for heated nodes (subject to existing budget caps).
2. Opt-in off → still heatmap-first / no bodies by default.
3. Automated tests cover:
   - default / opt-in-off path stays body-less (or heatmap reshape as today)
   - opt-in-on path actually requests collection (assert the pack runner is invoked with bodies enabled, and/or returned pack entries contain text when collection succeeds)
4. Prefer fixing the existing MCP pack factory + lean reshape pipeline — do not invent a parallel pack API.
5. Do not break callers that ignore bodies and only read heatmap/locs.

## Constraints
- In-process only; no new network services.
- Explore the codebase yourself — this prompt will not name files, symbols, or env var spellings beyond what you discover.
- Do not commit or push. Local tests are fine.
- Keep the change small and reviewable.

## Success criteria
- Opt-in on → bodies can appear in pack responses (proven by tests).
- Opt-in off → lean heatmap-only behavior preserved.
- Final reply: what changed + how you verified.

Implement end-to-end: explore → edit → test.
""",
        "test_keywords": (
            "include_bodies",
            "CTX_MCP_PACK_BODIES",
            "want_bodies",
            "pack_context_bodies",
            "_make_pack_impl",
            "test_pack_context_bodies",
            "heatmap_only",
        ),
        "test_files": (
            "tests/test_mcp_response_lean.py",
            "tests/test_mcp_locate.py",
        ),
    },
    "complex_retrieval": {
        "title": "complex multi-hop retrieval → single reasoning context file",
        "out_stem": "2026-09-07-kiro-mcp-ab-retrieval",
        "mode": "retrieval",
        "output_file": "out/ab_retrieval_context.md",
        # Gold is harness-only (not shown to the agent).
        "must_files": (
            "packages/pipeline/__main__.py",
            "packages/pipeline/rules_installer.py",
            "packages/pipeline/mcp_permissions.py",
            "packages/pipeline/mcp_install.py",
        ),
        "must_symbols": (
            "cmd_connect",
            "write_project_tool_surface",
            "write_project_gate_rules",
            "apply_permissions_to_repo_tool_surface",
            "managed_gate_usage_short",
            "write_cursor_rule",
        ),
        "must_terms": (
            "autoApprove",
            "mcpAllowlist",
            "AGENTS.md",
            "mcp.json",
            "permissions.json",
            "GATE",
        ),
        "prompt": """# Retrieval challenge — assemble a reasoning context pack (NO code changes)

## Mission
You must retrieve enough multi-hop codebase context to answer a hard product question later —
but you will NOT implement anything. Your ONLY deliverable is one markdown file that stores
all context needed for reasoning.

## Hard question (do not answer in chat — put evidence in the file)
Trace the full `scubiee connect` surface for Cursor-like hosts end-to-end:
1. Where connect starts and how tool-surface install is invoked.
2. Where mcp.json autoApprove / alwaysAllow (or equivalent allowlists) are written.
3. Where permissions.json mcpAllowlist (or equivalent) is applied for the project.
4. Where AGENTS.md / host GATE rule text is written for managed repos.
5. How Cursor rule install relates to that GATE text (if at all).

Ignore CLI banners/print helpers. Prefer production packages/ code over tests/docs.

## Deliverable (strict)
Write exactly one file:
  `out/ab_retrieval_context.md`

That file MUST contain:
- A short problem restatement (≤8 lines).
- An ordered call/flow narrative (entry → writers → side effects).
- A table or bullet list of concrete `path` + `symbol` (+ optional `loc` if known) for every
  hop you rely on.
- Short excerpts or paraphrases of the critical logic (enough to reason without re-opening the repo).
- A final "open questions / unknowns" section if anything is still unclear.

## Non-goals / bans
- Do NOT edit production code or tests.
- Do NOT commit or push.
- Do NOT invent paths/symbols you did not find.
- Do NOT read or copy from any sibling A/B workspace (no `../with`, `../without`, other
  `.ab_workspaces/**` trees, or another arm's `out/ab_retrieval_context.md`).
- Work ONLY inside THIS workspace root.

## Success
- File exists at `out/ab_retrieval_context.md`.
- It is self-contained enough that a later agent could reason about connect→permissions→GATE
  without rediscovering the graph.
- Stop when the file is written. Brief chat summary is OK; the file is the artifact.
""",
        "test_keywords": (),
        "test_files": (),
    },
    "complex_retrieval_pack": {
        "title": "complex pack/heatmap/session retrieval → single reasoning context file",
        "out_stem": "2026-09-07-kiro-mcp-ab-retrieval-pack",
        "mode": "retrieval",
        "output_file": "out/ab_retrieval_context.md",
        "must_files": (
            "packages/pipeline/mcp_locate.py",
            "packages/pipeline/context_trace.py",
            "packages/pipeline/session_isolation.py",
            "packages/pipeline/session_store.py",
        ),
        "must_symbols": (
            "pack_context",
            "expand_context",
            "collect_hot_context",
            "run_pack_context",
            "effective_session_id",
            "resolve_session",
        ),
        "must_terms": (
            "heatmap",
            "mode=lean",
            "suggested_seed",
            "CTX_MCP_SESSION_ISOLATE",
            "fail closed",
            "with_bodies",
        ),
        "prompt": """# Retrieval challenge — assemble a reasoning context pack (NO code changes)

## Mission
You must retrieve enough multi-hop codebase context to answer a hard product question later —
but you will NOT implement anything. Your ONLY deliverable is one markdown file that stores
all context needed for reasoning.

## Hard question (do not answer in chat — put evidence in the file)
Trace the Scubiee **incremental locate ladder + session isolation** end-to-end:
1. How `map` picks / exposes a suggested seed for packing.
2. How `pack_context` (lean / heatmap-first) is built — where the heatmap/locs come from and
   what “no bodies by default” means in the response shape.
3. How `expand_context` and `collect_hot_context` extend or hydrate that slice.
4. How session identity is resolved for persisted locate/pack state, and what happens when
   isolation is on but a session cannot be resolved (fail-closed vs shared-process fallback).
5. Where session-scoped pins / packed ids / heatmap handles are stored on disk (or equivalent).

Ignore CLI banners/print helpers. Prefer production packages/ code over tests/docs.

## Deliverable (strict)
Write exactly one file:
  `out/ab_retrieval_context.md`

That file MUST contain:
- A short problem restatement (≤8 lines).
- An ordered call/flow narrative (entry → pack/heatmap → expand/collect → session persistence).
- A table or bullet list of concrete `path` + `symbol` (+ optional `loc` if known) for every
  hop you rely on.
- Short excerpts or paraphrases of the critical logic (enough to reason without re-opening the repo).
- A final "open questions / unknowns" section if anything is still unclear.

## Non-goals / bans
- Do NOT edit production code or tests.
- Do NOT commit or push.
- Do NOT invent paths/symbols you did not find.
- Do NOT read or copy from any sibling A/B workspace (no `../with`, `../without`, other
  `.ab_workspaces/**` trees, or another arm's `out/ab_retrieval_context.md`).
- Work ONLY inside THIS workspace root.

## Success
- File exists at `out/ab_retrieval_context.md`.
- It is self-contained enough that a later agent could reason about map→pack→expand/collect
  and session isolation without rediscovering the graph.
- Stop when the file is written. Brief chat summary is OK; the file is the artifact.
""",
        "test_keywords": (),
        "test_files": (),
    },
    "complex_retrieval_index": {
        "title": "complex index/sync/engine-warm retrieval → single reasoning context file",
        "out_stem": "2026-09-07-kiro-mcp-ab-retrieval-index",
        "mode": "retrieval",
        "output_file": "out/ab_retrieval_context.md",
        "must_files": (
            "packages/pipeline/engine_client.py",
            "packages/pipeline/preflight.py",
            "packages/pipeline/mcp_locate.py",
            "packages/pipeline/context_trace.py",
        ),
        "must_symbols": (
            "ensure_engine",
            "CapabilityError",
            "run_pack_context",
            "status",
            "warm_state",
            "index_usable",
        ),
        "must_terms": (
            "DmlExecutionProvider",
            "composite_v1",
            "CTX_ENGINE_URL",
            "warming",
            "heatmap",
            "suggested_seed",
        ),
        "prompt": """# Retrieval challenge — assemble a reasoning context pack (NO code changes)

## Mission
You must retrieve enough multi-hop codebase context to answer a hard product question later —
but you will NOT implement anything. Your ONLY deliverable is one markdown file that stores
all context needed for reasoning.

## Hard question (do not answer in chat — put evidence in the file)
Trace how Scubiee becomes **ready to locate/pack** and what agents see when it is not:
1. How the local engine is contacted / ensured (URL, health, warm path).
2. Which preflight / capability gates can refuse index or embedding work (provider / deps).
3. How MCP `status` / gate-style health surfaces expose `warm_state`, index usability, or similar.
4. How a soft locate still reaches `map` → `pack_context` once the engine is usable — where
   suggested_seed and lean heatmap are produced in the pack pipeline.
5. What “warming / error / not ready” means for agents (retry vs fail vs native fallback policy
   in product instructions if present).

Ignore CLI banners/print helpers. Prefer production packages/ code over tests/docs.

## Deliverable (strict)
Write exactly one file:
  `out/ab_retrieval_context.md`

That file MUST contain:
- A short problem restatement (≤8 lines).
- An ordered call/flow narrative (engine ensure → capability/preflight → status/warm → map/pack).
- A table or bullet list of concrete `path` + `symbol` (+ optional `loc` if known) for every
  hop you rely on.
- Short excerpts or paraphrases of the critical logic (enough to reason without re-opening the repo).
- A final "open questions / unknowns" section if anything is still unclear.

## Non-goals / bans
- Do NOT edit production code or tests.
- Do NOT commit or push.
- Do NOT invent paths/symbols you did not find.
- Do NOT read or copy from any sibling A/B workspace (no `../with`, `../without`, other
  `.ab_workspaces/**` trees, or another arm's `out/ab_retrieval_context.md`).
- Work ONLY inside THIS workspace root.

## Success
- File exists at `out/ab_retrieval_context.md`.
- It is self-contained enough that a later agent could reason about engine warm/index readiness
  and the path into pack without rediscovering the graph.
- Stop when the file is written. Brief chat summary is OK; the file is the artifact.
""",
        "test_keywords": (),
        "test_files": (),
    },
    "complex_retrieval_gate_text": {
        "title": "complex GATE-text install multi-hop retrieval → single reasoning context file",
        "out_stem": "2026-09-07-kiro-mcp-ab-retrieval-gate-text",
        "mode": "retrieval",
        "output_file": "out/ab_retrieval_context.md",
        "must_files": (
            "packages/pipeline/rules_installer.py",
            "packages/pipeline/templates/scubiee.md",
            "packages/pipeline/templates/scubiee.mdc",
            "packages/pipeline/mcp_locate.py",
        ),
        "must_symbols": (
            "managed_gate_usage_short",
            "managed_gate_overview_bullet",
            "managed_gate_mcp_header",
            "write_project_gate_rules",
            "write_cursor_rule",
            "managed_gate_rule_body",
        ),
        "must_terms": (
            "Enrich/expand",
            "code-vocab",
            "Forbid-first",
            "LOCATE PRIORITY",
            "pack --mode lean",
            "scubiee:start",
        ),
        "prompt": """# Retrieval challenge — assemble a reasoning context pack (NO code changes)

## Mission
You must retrieve enough multi-hop codebase context to answer a hard product question later —
but you will NOT implement anything. Your ONLY deliverable is one markdown file that stores
all context needed for reasoning.

## Hard question (do not answer in chat — put evidence in the file)
Trace how Scubiee **managed GATE locate policy text** is authored and installed into host surfaces:
1. Where the dense Prefer/Forbid / enrich-query / map→pack ladder wording is defined in code
   (usage_short / overview / MCP header helpers — not just docs).
2. How that text is wrapped into a GATE block and written into AGENTS.md (and sibling agent files).
3. How Cursor/Kiro overview templates (`scubiee.md` / `scubiee.mdc`) carry the GATE 1 line.
4. How MCP server instructions reinforce the same enrich-query + pack policy every turn
   (header vs phase ship body).
5. Where `write_cursor_rule` / template install lands the always-apply Cursor rule.

Ignore test fixtures and marketing docs. Prefer packages/pipeline production modules.

## Deliverable (strict)
Write exactly one file:
  `out/ab_retrieval_context.md`

That file MUST contain:
- A short problem restatement (≤8 lines).
- An ordered call/flow narrative (helpers → GATE body → AGENTS install → templates → MCP header).
- A table or bullet list of concrete `path` + `symbol` (+ optional `loc` if known) for every
  hop you rely on.
- Short excerpts or paraphrases of the critical logic (enough to reason without re-opening the repo).
- A final "open questions / unknowns" section if anything is still unclear.

## Non-goals / bans
- Do NOT edit production code or tests.
- Do NOT commit or push.
- Do NOT invent paths/symbols you did not find.
- Do NOT read or copy from any sibling A/B workspace (no `../with`, `../without`, other
  `.ab_workspaces/**` trees, or another arm's `out/ab_retrieval_context.md`).
- Do NOT copy another arm's artifact — retrieve independently in THIS workspace only.
- Work ONLY inside THIS workspace root.

## Success
- File exists at `out/ab_retrieval_context.md`.
- It is self-contained enough that a later agent could reason about GATE text authorship +
  install without rediscovering the graph.
- Stop when the file is written. Brief chat summary is OK; the file is the artifact.
""",
        "test_keywords": (),
        "test_files": (),
    },
    "complex_retrieval_permissions": {
        "title": "complex MCP permissions/allowlist multi-hop retrieval → single reasoning context file",
        "out_stem": "2026-09-07-kiro-mcp-ab-retrieval-permissions",
        "mode": "retrieval",
        "output_file": "out/ab_retrieval_context.md",
        "must_files": (
            "packages/pipeline/mcp_permissions.py",
            "packages/pipeline/rules_installer.py",
            "packages/pipeline/mcp_install.py",
        ),
        "must_symbols": (
            "apply_permissions_to_repo_tool_surface",
            "enrich_server_entry_permissions",
            "write_project_tool_surface",
            "PHASE_LOCATE_TOOLS",
            "mcpAllowlist",
            "autoApprove",
        ),
        "must_terms": (
            "alwaysAllow",
            "permissions.json",
            "mcpServers",
            "locate",
            "Cursor",
            "kiro",
        ),
        "prompt": """# Retrieval challenge — assemble a reasoning context pack (NO code changes)

## Mission
You must retrieve enough multi-hop codebase context to answer a hard product question later —
but you will NOT implement anything. Your ONLY deliverable is one markdown file that stores
all context needed for reasoning.

## Hard question (do not answer in chat — put evidence in the file)
Trace how Scubiee **grants host MCP tool permissions / allowlists** end-to-end:
1. Where the locate tool name list for a host profile is defined (what tools get auto-approved).
2. How an mcpServers.scubiee entry is enriched with autoApprove / alwaysAllow (or equivalent).
3. How project-level permissions surfaces (e.g. permissions.json mcpAllowlist) are merged/written.
4. How write_project_tool_surface (or connect/install path) ties mcp.json + permissions together
   across hosts (Cursor vs Claude-like vs Kiro if present).
5. What differs for a "locate" profile vs a broader allow-all profile, if both exist.

Ignore CLI banners and test-only fixtures. Prefer packages/pipeline production modules.

## Deliverable (strict)
Write exactly one file:
  `out/ab_retrieval_context.md`

That file MUST contain:
- A short problem restatement (≤8 lines).
- An ordered call/flow narrative (tool list → enrich entry → apply permissions → tool surface write).
- A table or bullet list of concrete `path` + `symbol` (+ optional `loc` if known) for every
  hop you rely on.
- Short excerpts or paraphrases of the critical logic (enough to reason without re-opening the repo).
- A final "open questions / unknowns" section if anything is still unclear.

## Non-goals / bans
- Do NOT edit production code or tests.
- Do NOT commit or push.
- Do NOT invent paths/symbols you did not find.
- Do NOT read or copy from any sibling A/B workspace (no `../with`, `../without`, other
  `.ab_workspaces/**` trees, or another arm's `out/ab_retrieval_context.md`).
- Do NOT copy another arm's artifact — retrieve independently in THIS workspace only.
- Work ONLY inside THIS workspace root.

## Success
- File exists at `out/ab_retrieval_context.md`.
- It is self-contained enough that a later agent could reason about MCP permission/allowlist
  install without rediscovering the graph.
- Stop when the file is written. Brief chat summary is OK; the file is the artifact.
""",
        "test_keywords": (),
        "test_files": (),
    },
    "complex_retrieval_seed": {
        "title": "complex suggested-seed / weak-card multi-hop retrieval → single reasoning context file",
        "out_stem": "2026-09-07-kiro-mcp-ab-retrieval-seed",
        "mode": "retrieval",
        "output_file": "out/ab_retrieval_context.md",
        "must_files": (
            "packages/pipeline/context_trace.py",
            "packages/pipeline/mcp_locate.py",
            "packages/pipeline/session_store.py",
        ),
        "must_symbols": (
            "pick_suggested_seed",
            "suggested_seed",
            "put_span",
            "recall",
            "run_pack_context",
        ),
        "must_terms": (
            "packages/",
            "test",
            "heatmap",
            "mode=lean",
            "seed",
            "weak",
        ),
        "prompt": """# Retrieval challenge — assemble a reasoning context pack (NO code changes)

## Mission
You must retrieve enough multi-hop codebase context to answer a hard product question later —
but you will NOT implement anything. Your ONLY deliverable is one markdown file that stores
all context needed for reasoning.

## Hard question (do not answer in chat — put evidence in the file)
Trace how a soft locate picks a **usable seed** and avoids weak/test seeds:
1. Where map/card results are ranked or filtered into a suggested seed (file + symbol).
2. Which rules reject empty / `_` / test / docs helpers as seeds (if encoded in code).
3. How that seed is passed into a lean pack / heatmap step (seed_file / seed_symbol / similar).
4. How session persistence (put_span / recall or equivalent) relates to rematerializing
   locate context across turns, if at all.
5. What an agent should do when the first suggested seed is weak or missing.

Ignore CLI banners and marketing docs. Prefer packages/pipeline production modules.

## Deliverable (strict)
Write exactly one file:
  `out/ab_retrieval_context.md`

That file MUST contain:
- A short problem restatement (≤8 lines).
- An ordered call/flow narrative (cards → seed pick → pack seed args → optional session store).
- A table or bullet list of concrete `path` + `symbol` (+ optional `loc` if known) for every
  hop you rely on.
- Short excerpts or paraphrases of the critical logic (enough to reason without re-opening the repo).
- A final "open questions / unknowns" section if anything is still unclear.

## Non-goals / bans
- Do NOT edit production code or tests.
- Do NOT commit or push.
- Do NOT invent paths/symbols you did not find.
- Do NOT read or copy from any sibling A/B workspace (no `../with`, `../without`, other
  `.ab_workspaces/**` trees, or another arm's `out/ab_retrieval_context.md`).
- Do NOT copy another arm's artifact — retrieve independently in THIS workspace only.
- Work ONLY inside THIS workspace root.

## Success
- File exists at `out/ab_retrieval_context.md`.
- It is self-contained enough that a later agent could reason about suggested-seed selection
  and weak-seed rejection without rediscovering the graph.
- Stop when the file is written. Brief chat summary is OK; the file is the artifact.
""",
        "test_keywords": (),
        "test_files": (),
    },
}

# Back-compat alias used until main() selects a task.
DEV_PROMPT = TASKS["weak_start"]["prompt"]
ACTIVE_TASK_ID = "weak_start"
ACTIVE_TASK: dict[str, Any] = TASKS["weak_start"]
ACTIVE_TEST_KEYWORDS = TASKS["weak_start"]["test_keywords"]
ACTIVE_TEST_FILES: tuple[str, ...] = tuple(TASKS["weak_start"].get("test_files") or ())

SHARED_SYSTEM = """You are a coding agent doing a real development task.

Rules:
- Implement the requested behavior with tests.
- Prefer small, correct changes over large refactors.
- Do not commit or push.
- Do not modify files outside this workspace root.
- BAN reading sibling A/B workspaces (any other `.ab_workspaces/**` tree, `../with`, `../without`).
- BAN copying another arm's diffs, notes, or artifacts — discover and implement independently.
- When done, summarize what changed and which tests you ran.
"""

SHARED_SYSTEM_RETRIEVAL = """You are a coding agent on a retrieval-only challenge.

Rules:
- Your ONLY deliverable is the context file named in the task prompt.
- Do NOT edit production/test code. Do NOT commit or push.
- Do not modify files outside this workspace root except creating the required output path.
- BAN reading sibling A/B workspaces (any other `.ab_workspaces/**` tree, `../with`, `../without`,
  or another arm's retrieval output). Arms are isolated — do not peek.
- BAN copying or paraphrasing another arm's `out/ab_retrieval_context.md` (or any sibling artifact).
  You must retrieve and write your own evidence independently in THIS workspace only.
- Prefer accurate multi-hop evidence over guesses.
- When done, confirm the output file path and a one-line summary.
"""

# Explicit ladder tools (also allow @scubiee wildcard). Keep in sync with PHASE_LOCATE_TOOLS.
SCUBIEE_LOCATE_TOOLS = [
    "@scubiee",
    "@scubiee/gate",
    "@scubiee/map",
    "@scubiee/pack_context",
    "@scubiee/map_context",
    "@scubiee/expand_context",
    "@scubiee/collect_hot_context",
    "@scubiee/pinpoint",
    "@scubiee/plate",
    "@scubiee/focus",
    "@scubiee/grep",
    "@scubiee/glob",
    "@scubiee/workspace",
    "@scubiee/expand",
    "@scubiee/status",
]

SCUBIEE_AUTO_APPROVE = [
    "gate",
    "pack_context",
    "map_context",
    "expand_context",
    "collect_hot_context",
    "map",
    "pinpoint",
    "plate",
    "focus",
    "grep",
    "glob",
    "workspace",
    "expand",
    "status",
    "*",
]

WITH_EXTRA = """
Follow the project rules loaded as agent resources (AGENTS.md and .kiro/steering).
Those rules are mandatory for how you explore, locate, and gather context — obey them strictly.
Do not invent tools you do not have. Do not commit or push.
"""

WITHOUT_EXTRA = """
You do NOT have Scubiee (no MCP and no CLI locate).
BAN inventing MCP locate tools.
BAN running `scubiee map`, `scubiee pack`, or `scubiee expand`.
Use only built-in read/write/shell (rg/findstr) to explore and implement.
"""

# Experiment: with-arm job prompt must NOT name Scubiee / MCP ladder — rules carry that.
_WITH_PROMPT_SCUBIEE_LEAK = re.compile(
    r"scubiee|pack_context|@scubiee|map_context|expand_context|collect_hot_context|"
    r"MUST Use Scubiee|SCUBIEE MCP",
    re.I,
)

# MCP tools Kiro must prove in preflight (ship surface — CTX_MCP_EXPERIMENT=ship).
# Lab-only extras (map_context / pinpoint / plate) are optional, not required.
MCP_PREFLIGHT_REQUIRED = (
    "gate",
    "status",
    "map",
    "pack_context",
    "expand_context",
    "collect_hot_context",
    "workspace",
)


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b.")
_CREDIT = re.compile(r"Credits:\s*([0-9]+(?:\.[0-9]+)?)", re.I)
_TIME = re.compile(r"Time:\s*(?:(\d+)\s*m\s*)?(\d+)\s*s", re.I)
_MCP_TOOL = re.compile(
    r"Running tool\s+(\S+)\s+.*?\(from mcp server:\s*(\w+)\)",
    re.I | re.S,
)
_NATIVE_TOOL = re.compile(r"\(using tool:\s*([A-Za-z_][\w]*)", re.I)


def _load_dotenv_key() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\s*KIRO_API_KEY\s*=\s*(.+)\s*$", line)
        if m:
            os.environ["KIRO_API_KEY"] = m.group(1).strip().strip('"').strip("'")
            return


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=check,
    )


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def _scubiee_env(repo: Path) -> dict[str, str]:
    # A/B snapshots fork a new project_id without a warm index. Point locate at the
    # parent managed repo index so map/pack work; agent still edits/writes in `repo` cwd.
    locate_root = ROOT
    try:
        if ".ab_workspaces" in {p.lower() for p in repo.resolve().parts}:
            locate_root = ROOT
        else:
            locate_root = repo
    except OSError:
        locate_root = repo
    env = {
        "CTX_BACKGROUND_SYNC": "0",
        "CTX_TRACE_ENGINE": "composite_v1",
        "CTX_ALLOW_BG_FULL": "0",
        "CTX_ENGINE_URL": "http://127.0.0.1:8765",
        "CTX_AUTO_INDEX": "0",
        "CTX_MCP_SESSION_ISOLATE": "1",
        "CTX_MCP_BRIDGE_MODE": "auto",
        "CTX_REPO": str(locate_root).replace("\\", "/"),
        "CTX_MCP_CLIENT": "kiro",
        "CTX_MCP_SURFACE": "phase",
        "CTX_MCP_EXPERIMENT": "ship",
        "CTX_TRACE_GRAPHIFY": "1",
        "CTX_PROJECT_ID": PROJECT_ID,
        "CTX_TOKEN_MODE": "savings",
        "PYTHONUTF8": "1",
        "CTX_SCUBIEE_BUILD": "0.3.16-kiro-ab-dev",
    }
    if PROJECT_MCP.is_file():
        try:
            raw = PROJECT_MCP.read_text(encoding="utf-8-sig")
            data = json.loads(raw)
            src = ((data.get("mcpServers") or {}).get("scubiee") or {}).get("env") or {}
            for k, v in src.items():
                if k.startswith("CTX_") and k not in {
                    "CTX_REPO",
                    "CTX_MCP_CLIENT",
                    "CTX_BACKGROUND_SYNC",
                    "CTX_AUTO_INDEX",
                    "CTX_SCUBIEE_BUILD",
                    "CTX_PROJECT_ID",
                }:
                    env[str(k)] = str(v)
        except json.JSONDecodeError:
            pass
    env["CTX_REPO"] = str(locate_root).replace("\\", "/")
    env["CTX_PROJECT_ID"] = PROJECT_ID
    env["CTX_MCP_CLIENT"] = "kiro"
    env["CTX_TRACE_ENGINE"] = "composite_v1"
    # Prefer live package build stamp from project mcp when present
    try:
        raw = PROJECT_MCP.read_text(encoding="utf-8-sig") if PROJECT_MCP.is_file() else ""
        if raw:
            bid = (
                ((json.loads(raw).get("mcpServers") or {}).get("scubiee") or {}).get("env") or {}
            ).get("CTX_SCUBIEE_BUILD")
            if bid:
                env["CTX_SCUBIEE_BUILD"] = str(bid)
    except (OSError, json.JSONDecodeError):
        pass
    return env


def _gate_body() -> str:
    """Load strengthened GATE text from rules_installer (same source as product)."""
    sys.path.insert(0, str(ROOT / "packages"))
    from pipeline.rules_installer import managed_gate_rule_body  # noqa: WPS433

    return managed_gate_rule_body(f"1:{PROJECT_ID}", PROJECT_ID)


def _upsert_agents_gate(agents_md: Path, inner: str) -> None:
    block = f"<!-- scubiee:start -->\n{inner}\n\n<!-- scubiee:end -->\n"
    raw = agents_md.read_text(encoding="utf-8") if agents_md.is_file() else ""
    if "<!-- scubiee:start -->" in raw:
        raw = re.sub(
            r"<!-- scubiee:start -->.*?<!-- scubiee:end -->\n?",
            block,
            raw,
            flags=re.S,
        )
    else:
        raw = block + raw
    agents_md.write_text(raw, encoding="utf-8")


def _gate_body_mcp() -> str:
    """MCP-only GATE for the with-arm — product source (same STRICT policy as Scubiee installs)."""
    sys.path.insert(0, str(ROOT / "packages"))
    from pipeline.rules_installer import managed_gate_mcp_only_rule_body  # noqa: WPS433

    return managed_gate_mcp_only_rule_body(f"1:{PROJECT_ID}", PROJECT_ID)


RULES_PROBE_PROMPT = """# Rules visibility probe (NO product work)

Your ONLY job: prove you can see the project locate/GATE rules and MCP tools.

1. Open/use the agent resources AGENTS.md and .kiro/steering/scubiee.md (do not invent their contents).
2. Write exactly one file: `out/ab_rules_seen.md` containing:
   - Whether each resource was visible/readable.
   - A near-verbatim quote (≤40 lines) of the MUST Use Scubiee / WHEN SCUBIEE MCP IS AVAILABLE sections.
   - The list of Scubiee MCP tool names you can actually call (from the tool list — do not invent).
   - One sentence: will you follow those rules for soft locate even if the user chat did not name Scubiee?
3. Do NOT solve any retrieval/dev task. Stop after writing the file.
"""


def install_gate_surface(ws: Path, *, with_mcp: bool) -> dict[str, str]:
    """Write AGENTS.md + Kiro steering (+ Cursor rule) so hosts load locate policy.

    with_mcp=True  → MUST-Use-Scubiee-MCP GATE (MCP only; ban CLI locate)
    with_mcp=False → BAN Scubiee CLI+MCP / native-only (fair without arm)
    """
    agents_md = ws / "AGENTS.md"
    steering = ws / ".kiro" / "steering" / "scubiee.md"
    cursor_rule = ws / ".cursor" / "rules" / "scubiee.mdc"
    steering.parent.mkdir(parents=True, exist_ok=True)
    cursor_rule.parent.mkdir(parents=True, exist_ok=True)

    if with_mcp:
        body = _gate_body_mcp()
        _upsert_agents_gate(agents_md, body)
        # Kiro steering: always-include frontmatter so rules load without prompt nudge
        steering.write_text(
            "---\ninclusion: always\n---\n\n" + body + "\n",
            encoding="utf-8",
        )
        cursor_rule.write_text(
            "---\ndescription: Scubiee GATE locate (MCP)\nalwaysApply: true\n---\n\n"
            + body
            + "\n",
            encoding="utf-8",
        )
        return {
            "agents_md": "gate_with_scubiee_mcp",
            "steering": "gate_with_scubiee_mcp",
            "cursor_rule": "gate_with_scubiee_mcp",
        }

    ban = (
        "**GATE A/B without-Scubiee arm** — Scubiee CLI and MCP are NOT available.\n"
        "BAN inventing map/pack_context/expand_context MCP calls.\n"
        "BAN running `scubiee map` / `scubiee pack` / `scubiee expand`.\n"
        "USE native read / write / shell (rg/findstr) only.\n"
    )
    _upsert_agents_gate(agents_md, ban)
    steering.write_text(ban + "\n", encoding="utf-8")
    cursor_rule.write_text(ban + "\n", encoding="utf-8")
    return {
        "agents_md": "ban_scubiee",
        "steering": "ban_scubiee",
        "cursor_rule": "ban_scubiee",
    }


def _shell_rules_allow_scubiee(cfg: dict[str, Any]) -> bool:
    rules = ((cfg.get("permissions") or {}).get("rules")) or []
    for rule in rules:
        if rule.get("capability") != "shell":
            continue
        for match in rule.get("match") or []:
            m = str(match).lower()
            if "scubiee" in m:
                return True
    return False


def assert_agent_surface(ws: Path, agent_path: Path, *, with_mcp: bool) -> list[str]:
    """Fail-fast checks that harness wired tools/rules/permissions correctly.

    with_mcp=True means with-Scubiee MCP arm (embedded mcpServers; no CLI locate).
    """
    errs: list[str] = []
    cfg = json.loads(agent_path.read_text(encoding="utf-8"))
    if cfg.get("includeMcpJson") is not False:
        errs.append("includeMcpJson must be false")
    tools = cfg.get("tools") or []
    if "read" not in tools or "shell" not in tools:
        errs.append("missing native read/shell tools")
    if with_mcp:
        if not (cfg.get("mcpServers") or {}).get("scubiee"):
            errs.append("with-arm must embed mcpServers.scubiee")
        else:
            sc = (cfg.get("mcpServers") or {})["scubiee"]
            cmd = str(sc.get("command") or "")
            if "scubiee-mcp-bridge" not in cmd.replace("\\", "/").lower() and "mcp" not in cmd.lower():
                errs.append("with-arm scubiee command does not look like MCP bridge")
            env = sc.get("env") or {}
            if not env.get("CTX_REPO"):
                errs.append("with-arm MCP env missing CTX_REPO")
            if env.get("CTX_MCP_CLIENT") != "kiro":
                errs.append("with-arm MCP env CTX_MCP_CLIENT must be kiro")
            if not (sc.get("autoApprove") or sc.get("alwaysAllow")):
                errs.append("with-arm MCP missing autoApprove/alwaysAllow")
        if "@scubiee" not in [str(t) for t in tools] and not any(
            str(t).startswith("@scubiee/") for t in tools
        ):
            errs.append("with-arm must allow @scubiee MCP tools")
        if _shell_rules_allow_scubiee(cfg):
            errs.append("with-arm must NOT allow shell scubiee * (MCP only)")
        resources = cfg.get("resources") or []
        if "file://AGENTS.md" not in resources:
            errs.append("missing resources file://AGENTS.md")
        if "file://.kiro/steering/scubiee.md" not in resources:
            errs.append("missing resources file://.kiro/steering/scubiee.md")
        agents_txt = (ws / "AGENTS.md").read_text(encoding="utf-8", errors="replace")
        steer_txt = (ws / ".kiro" / "steering" / "scubiee.md").read_text(
            encoding="utf-8", errors="replace"
        )
        for label, txt in (("AGENTS.md", agents_txt), ("steering", steer_txt)):
            if "MUST Use Scubiee MCP" not in txt and "Use Scubiee MCP" not in txt:
                errs.append(f"{label} missing Use Scubiee MCP GATE wording")
            if "WHEN SCUBIEE MCP IS AVAILABLE" not in txt and "STRICT, NO ESCAPE" not in txt:
                errs.append(f"{label} missing STRICT when-available block (rules must carry prompt policy)")
            if "pack_context" not in txt:
                errs.append(f"{label} missing pack_context MCP instruction")
            if "map" not in txt.lower():
                errs.append(f"{label} missing map MCP instruction")
            if "BAN" not in txt or "scubiee map" not in txt.lower():
                errs.append(f"{label} missing BAN shell scubiee CLI locate")
            if "enrich" not in txt.lower() and "Expand the query" not in txt and "code-vocab" not in txt:
                errs.append(f"{label} missing expand-query / code-vocab guidance")
            if "heatmap" not in txt.lower():
                errs.append(f"{label} missing heatmap pack emphasis")
            if "BAN whole-file" not in txt and "whole-file Read" not in txt:
                errs.append(f"{label} missing whole-file Read ban after pack")
            if "automatic FAIL" not in txt and "required next" not in txt.lower():
                errs.append(f"{label} must strictly require pack_context (FAIL if skipped)")
            if "warming" not in txt.lower() and "uncallable" not in txt.lower():
                errs.append(f"{label} must forbid warming/error as excuse to skip pack")
        if (
            "After pack" not in agents_txt
            and "use the heatmap" not in agents_txt.lower()
            and "heatmap" not in agents_txt.lower()
        ):
            errs.append("AGENTS.md missing heatmap / after-pack guidance")
        if (
            "After pack" not in steer_txt
            and "use the heatmap" not in steer_txt.lower()
            and "heatmap" not in steer_txt.lower()
        ):
            errs.append("steering missing heatmap / after-pack guidance")
        prompt = cfg.get("prompt") or ""
        # Rules-only experiment: job prompt must NOT nudge Scubiee / ladder tools
        if _WITH_PROMPT_SCUBIEE_LEAK.search(prompt):
            errs.append(
                "with-arm agent prompt must NOT name Scubiee/MCP ladder "
                "(policy lives in AGENTS.md + steering resources only)"
            )
        if "AGENTS.md" not in prompt and "steering" not in prompt.lower() and "resources" not in prompt.lower():
            errs.append("with-arm prompt should point at AGENTS.md / steering resources")
    else:
        if any(str(t).startswith("@scubiee") for t in tools):
            errs.append("without-arm must not allow @scubiee tools")
        if (cfg.get("mcpServers") or {}).get("scubiee"):
            errs.append("without-arm must not embed scubiee mcpServers")
        if _shell_rules_allow_scubiee(cfg):
            errs.append("without-arm must not allow shell scubiee")
        steer_txt = (ws / ".kiro" / "steering" / "scubiee.md").read_text(
            encoding="utf-8", errors="replace"
        )
        if "BAN" not in steer_txt:
            errs.append("without-arm steering must BAN Scubiee")
    return errs


def write_agents(ws: Path, *, model: str, with_mcp: bool) -> Path:
    gate_meta = install_gate_surface(ws, with_mcp=with_mcp)
    agents = ws / ".kiro" / "agents"
    agents.mkdir(parents=True, exist_ok=True)
    name = "ab_dev_with" if with_mcp else "ab_dev_without"
    tools: list[str] = ["read", "write", "shell"]
    shell_match = [
        "pytest *",
        "python *",
        "uv *",
        "rg *",
        "findstr *",
        "dir *",
        "ls *",
        "git status*",
        "git diff*",
        "git log*",
        "mkdir *",
        "New-Item *",
    ]
    mcp_servers: dict[str, Any] = {}
    auto_approve: list[str] = []
    if with_mcp:
        tools = tools + list(SCUBIEE_LOCATE_TOOLS)
        auto_approve = list(SCUBIEE_AUTO_APPROVE)
        mcp_servers = {
            "scubiee": {
                "command": str(BRIDGE).replace("\\", "/"),
                "args": [],
                "env": _scubiee_env(ws),
                "disabled": False,
                "autoApprove": auto_approve,
                "alwaysAllow": auto_approve,
            }
        }
    shared = (
        SHARED_SYSTEM_RETRIEVAL
        if (ACTIVE_TASK.get("mode") == "retrieval")
        else SHARED_SYSTEM
    )
    cfg: dict[str, Any] = {
        "name": name,
        "description": (
            f"Dev A/B arm {'WITH Scubiee MCP only (no CLI locate)' if with_mcp else 'WITHOUT Scubiee'}"
        ),
        "includeMcpJson": False,
        "includePowers": False,
        "model": model,
        "prompt": shared + (WITH_EXTRA if with_mcp else WITHOUT_EXTRA),
        "tools": tools,
        "allowedTools": tools,
        "resources": [
            "file://AGENTS.md",
            "file://.kiro/steering/scubiee.md",
        ],
        "permissions": {
            "rules": [
                {"capability": "fs_write", "match": ["*"], "effect": "allow"},
                {
                    "capability": "shell",
                    "match": shell_match,
                    "effect": "allow",
                },
            ]
        },
        "mcpServers": mcp_servers,
    }
    path = agents / f"{name}.json"
    _write_json(path, cfg)
    # Sidecar MUST NOT live under .kiro/agents/*.json — Kiro loads every JSON there as an agent
    # and rejects sidecar shapes (missing `name`), which stalls chat mid-run.
    surface_dir = ws / ".kiro" / "ab_surface"
    surface_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        surface_dir / f"{name}.json",
        {
            "gate": gate_meta,
            "tools": tools,
            "autoApprove": auto_approve,
            "resources": cfg["resources"],
            "includeMcpJson": False,
            "mcp": bool(with_mcp),
            "locate": "mcp" if with_mcp else "none",
            "shell_scubiee": False,
        },
    )
    return path


def snapshot_workspace(dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    dst.mkdir(parents=True, exist_ok=True)

    def _ignore(dirpath: str, names: list[str]) -> set[str]:
        ignored: set[str] = set()
        for n in names:
            if n in _EXCLUDE_DIRS:
                ignored.add(n)
            elif n.endswith(".pyc") or n.endswith(".pyo"):
                ignored.add(n)
        return ignored

    # copytree with ignore
    for item in ROOT.iterdir():
        if item.name in _EXCLUDE_DIRS:
            continue
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=_ignore, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)

    # Minimal scubiee identity so gate/project_id still resolve if MCP hits it
    scub = dst / ".scubiee"
    scub.mkdir(parents=True, exist_ok=True)
    id_src = ROOT / ".scubiee" / "id.json"
    if id_src.is_file():
        shutil.copy2(id_src, scub / "id.json")
    else:
        _write_json(scub / "id.json", {"project_id": PROJECT_ID})

    # Empty project mcp.json (agent owns MCP); steering optional omit
    (dst / ".kiro" / "settings").mkdir(parents=True, exist_ok=True)
    _write_json(dst / ".kiro" / "settings" / "mcp.json", {"mcpServers": {}})

    # Baseline git commit for scoring diffs
    _run(["git", "init"], cwd=dst, check=True)
    _run(["git", "config", "user.email", "ab-dev@local"], cwd=dst, check=True)
    _run(["git", "config", "user.name", "ab-dev"], cwd=dst, check=True)
    _run(["git", "add", "-A"], cwd=dst, check=True)
    _run(
        ["git", "commit", "-m", "ab-dev baseline", "--no-verify"],
        cwd=dst,
        check=True,
    )


MCP_PREFLIGHT_PROMPT = """# Preflight — prove Scubiee MCP tools + rules + permissions work in THIS workspace

You MUST use Scubiee MCP only. BAN shell `scubiee map|pack|expand`.

## A) Readiness (do this first)
1. Confirm Scubiee MCP tools are actually in your callable tool list (not just mentioned in text).
2. Confirm you can see GATE / locate rules from AGENTS.md and/or .kiro/steering/scubiee.md resources.
3. Confirm permissions allow calling @scubiee tools (autoApprove/alwaysAllow) — call at least `gate` once to prove it.

If MCP tools are NOT callable, set mcp_tools_visible=false and can_use_scubiee_mcp=false. Do NOT pretend success. Do NOT fall back to native for this preflight.

## B) Required MCP calls (ship surface; pass project_id / root if the tool asks)
1. `gate` — confirm managed gate text.
2. `status` — confirm engine/health responds.
3. `map` — descriptive query k=5 about session isolation / pack persistence / session_store.
4. `pack_context` — SAME query, mode=lean, seed_file/seed_symbol from map suggested_seed (or best packages/ card). Confirm heatmap/read.top (bodies may be empty — that is OK).
5. `expand_context` — node from pack seed/heatmap, direction=callees, with_bodies=false.
6. `collect_hot_context` — ids= from one heatmap/pack node (or threshold) so bodies path is exercised.
7. `workspace` — show/session rematerialize path (whatever the tool accepts for a light check).

Optional if exposed (lab only — do NOT invent): `map_context`, `pinpoint`, `plate`.

Answer ONLY with one JSON object (no markdown fence):
{"can_use_scubiee_mcp":bool,"mcp_tools_visible":bool,"saw_gate_rules":bool,"permissions_ok":bool,"used_cli_locate":bool,"scubiee_tool_names":[str],"tools":{"gate":{"ok":bool},"status":{"ok":bool},"map":{"ok":bool},"pack_context":{"ok":bool,"heatmap_n":int|null},"expand_context":{"ok":bool},"collect_hot_context":{"ok":bool},"workspace":{"ok":bool},"map_context":{"ok":bool|null},"pinpoint":{"ok":bool|null},"plate":{"ok":bool|null}},"notes":str}

Rules:
- Do not edit files.
- Do not invent tools that are not on the Scubiee MCP server.
- If a tool errors, set ok=false and put the error in notes — do not pretend success.
- used_cli_locate must be false.
"""


MCP_READINESS_PROMPT = """# Readiness gate — before the real development task

Answer ONLY with one JSON object (no markdown fence).

You must:
1. Confirm Scubiee MCP tools are in your callable tool list right now.
2. Call MCP `gate` once successfully.
3. Confirm GATE/rules are loaded (AGENTS.md and/or .kiro/steering/scubiee.md).
4. Confirm you are allowed to call @scubiee tools (permissions / autoApprove).

If tools are missing, set mcp_tools_visible=false and ready=false. Do NOT use native tools as a substitute for this check. Do NOT start the development task.

JSON shape:
{"ready":bool,"mcp_tools_visible":bool,"gate_ok":bool,"saw_gate_rules":bool,"permissions_ok":bool,"scubiee_tool_names":[str],"notes":str}
"""


def _kiro_env(ws: Path) -> dict[str, str]:
    env = os.environ.copy()
    local_bin = str(Path.home() / ".local" / "bin")
    path_now = env.get("PATH") or env.get("Path") or ""
    if local_bin.lower() not in path_now.lower():
        env["PATH"] = local_bin + os.pathsep + path_now
        env["Path"] = env["PATH"]
    env.setdefault("CTX_TRACE_ENGINE", "composite_v1")
    env["CTX_REPO"] = str(ws).replace("\\", "/")
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _extract_json_obj(text: str) -> dict[str, Any] | None:
    clean = _strip_ansi(text)
    # Prefer last JSON object in the transcript
    best: dict[str, Any] | None = None
    depth = 0
    start: int | None = None
    for i, ch in enumerate(clean):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                chunk = clean[start : i + 1]
                try:
                    obj = json.loads(chunk)
                except json.JSONDecodeError:
                    start = None
                    continue
                if isinstance(obj, dict) and (
                    "can_use_scubiee_mcp" in obj
                    or "can_use_scubiee_cli" in obj
                    or "ready" in obj
                    or "mcp_tools_visible" in obj
                    or "pack_ok" in obj
                    or "map_ok" in obj
                ):
                    best = obj
                start = None
    return best


def ensure_snapshot_index(ws: Path, *, timeout_s: int = 600) -> dict[str, Any]:
    """Make CLI pack work inside a harness snapshot (index was excluded from copy)."""
    env = _kiro_env(ws)
    # Prefer register/initialize so project_id + index bind to this cwd
    cmds: list[tuple[str, list[str]]] = [
        ("register", ["scubiee", "register", str(ws), "--force"]),
        ("index", ["scubiee", "index", str(ws)]),
    ]
    steps: list[dict[str, Any]] = []
    for name, cmd in cmds:
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(ws),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                env=env,
            )
            steps.append(
                {
                    "step": name,
                    "exit": proc.returncode,
                    "stdout_tail": (proc.stdout or "")[-800:],
                    "stderr_tail": (proc.stderr or "")[-400:],
                }
            )
        except FileNotFoundError:
            steps.append({"step": name, "exit": 127, "error": "scubiee not on PATH"})
            break
        except subprocess.TimeoutExpired:
            steps.append({"step": name, "exit": 124, "error": f"timeout {timeout_s}s"})
            break
    # Deterministic pack smoke in the snapshot (no Kiro yet)
    q = (
        "session isolation require_session_id fail closed pack persistence "
        "session_store put_span"
    )
    pack_cmd = [
        "scubiee",
        "pack",
        q,
        "--seed-file",
        "packages/pipeline/session_isolation.py",
        "--mode",
        "lean",
    ]
    try:
        pack = subprocess.run(
            pack_cmd,
            cwd=str(ws),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            env=env,
        )
        pack_txt = (pack.stdout or "") + "\n" + (pack.stderr or "")
        pack_ok = '"ok": true' in pack_txt or '"ok":true' in pack_txt
        if not pack_ok:
            pack2 = subprocess.run(
                [
                    "scubiee",
                    "pack",
                    q,
                    "--seed-file",
                    "packages/pipeline/session_store.py",
                    "--seed-symbol",
                    "put_span",
                    "--mode",
                    "lean",
                ],
                cwd=str(ws),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_s,
                env=env,
            )
            pack_txt = (pack2.stdout or "") + "\n" + (pack2.stderr or "")
            pack_ok = '"ok": true' in pack_txt or '"ok":true' in pack_txt
            pack = pack2
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "steps": steps,
            "pack_ok": False,
            "error": str(exc),
        }
    return {
        "ok": bool(pack_ok),
        "steps": steps,
        "pack_ok": bool(pack_ok),
        "pack_exit": pack.returncode,
        "pack_tail": pack_txt[-1200:],
    }


# Last successful MCP preflight in this process (skip flaky second readiness chat).
_LAST_MCP_PREFLIGHT: dict[str, Any] | None = None


def run_kiro_mcp_preflight(
    *,
    ws: Path,
    model: str,
    effort: str,
    timeout_s: int,
    log_dir: Path,
) -> dict[str, Any]:
    """Ask Kiro live: can you use all Scubiee MCP locate tools? Must prove MCP ladder.

    Snapshot index smoke is recorded (engine needs an index) but does not skip the ask.
    """
    if not BRIDGE.is_file():
        return {
            "ok": False,
            "error": f"scubiee MCP bridge missing: {BRIDGE}",
            "kiro_answer": None,
        }
    agent_path = write_agents(ws, model=model, with_mcp=True)
    agent_name = agent_path.stem
    surface_errs = assert_agent_surface(ws, agent_path, with_mcp=True)
    if surface_errs:
        return {
            "ok": False,
            "error": "surface: " + "; ".join(surface_errs),
            "kiro_answer": None,
        }

    val = _run([str(KIRO), "agent", "validate", "--path", str(agent_path)], cwd=ws)
    if val.returncode != 0:
        return {
            "ok": False,
            "error": f"agent validate failed: {(val.stdout or '') + (val.stderr or '')}".strip(),
            "kiro_answer": None,
        }

    index_info = ensure_snapshot_index(ws, timeout_s=min(timeout_s, 600))

    cmd = [
        str(KIRO),
        "chat",
        "--no-interactive",
        "--trust-all-tools",
        "--require-mcp-startup",
        "--agent",
        agent_name,
        "--model",
        model,
        "--effort",
        effort,
        "--wrap",
        "never",
        "--agent-engine",
        "v1",
        "--legacy-ui",
        MCP_PREFLIGHT_PROMPT,
    ]
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "kiro_mcp_preflight.log"
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ws),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            env=_kiro_env(ws),
        )
        raw = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        raw = ""
        if isinstance(exc.stdout, str):
            raw += exc.stdout
        if isinstance(exc.stderr, str):
            raw += "\n" + exc.stderr
        raw += f"\n[TIMEOUT after {timeout_s}s]"
        exit_code = 124
    wall_ms = (time.perf_counter() - t0) * 1000
    clean = _strip_ansi(raw)
    log_path.write_text(clean, encoding="utf-8")
    tools = _parse_tools(clean)
    answer = _extract_json_obj(clean)
    mcp_seen = {str(t).lower() for t in (tools.get("mcp_scubiee_tools") or [])}
    cli_seen = tools.get("cli_locate_count") or 0

    tool_report: dict[str, Any] = {}
    if isinstance(answer, dict) and isinstance(answer.get("tools"), dict):
        tool_report = answer["tools"]

    missing_required: list[str] = []
    failed_required: list[str] = []
    for name in MCP_PREFLIGHT_REQUIRED:
        in_log = name in mcp_seen
        ans = tool_report.get(name) if isinstance(tool_report.get(name), dict) else {}
        ans_ok = bool(ans.get("ok")) if ans else False
        if not in_log and not ans_ok:
            missing_required.append(name)
        elif in_log and ans and ans.get("ok") is False:
            failed_required.append(name)
        elif not in_log and ans_ok:
            # Trust answer only if we also saw at least map+pack in log
            pass

    # Hard require core ladder tools appear in the MCP log
    core = ("gate", "map", "pack_context", "expand_context")
    core_missing = [n for n in core if n not in mcp_seen]
    used_cli = bool(cli_seen) or bool(
        answer.get("used_cli_locate") if isinstance(answer, dict) else False
    )
    can_use = bool(answer.get("can_use_scubiee_mcp")) if isinstance(answer, dict) else (
        not core_missing and not used_cli
    )
    tools_visible = True
    if isinstance(answer, dict) and "mcp_tools_visible" in answer:
        tools_visible = bool(answer.get("mcp_tools_visible"))
    denied_phrase = (
        "aren't in my available tool list" in clean.lower()
        or "not in my available tool list" in clean.lower()
        or "mcp tools aren't" in clean.lower()
        or "mcp tools are not" in clean.lower()
    )
    # Accept if Kiro claims success AND core MCP tools ran, no CLI locate
    ok = bool(
        can_use
        and tools_visible
        and not denied_phrase
        and not core_missing
        and not used_cli
        and "pack_context" in mcp_seen
        and "map" in mcp_seen
        and not missing_required
    )
    # Soften: if answer tools all ok and core in log, allow missing optional workspace in log
    if not ok and can_use and not core_missing and not used_cli:
        soft_missing = [n for n in missing_required if n not in core]
        if not soft_missing or set(soft_missing) <= {"workspace", "collect_hot_context", "status"}:
            claimed_ok = all(
                (isinstance(tool_report.get(n), dict) and tool_report[n].get("ok"))
                or n in mcp_seen
                for n in MCP_PREFLIGHT_REQUIRED
            )
            ok = bool(claimed_ok)

    err = None
    if not ok:
        bits = []
        if used_cli:
            bits.append("CLI locate used (forbidden)")
        if denied_phrase or not tools_visible:
            bits.append("Scubiee MCP tools not visible/callable to Kiro")
        if core_missing:
            bits.append("core MCP missing in log: " + ",".join(core_missing))
        if missing_required:
            bits.append("required tools missing/failed: " + ",".join(missing_required))
        if failed_required:
            bits.append("tools reported ok=false: " + ",".join(failed_required))
        if not index_info.get("pack_ok"):
            bits.append("snapshot deterministic pack smoke failed")
        if answer:
            bits.append(f"answer={answer}")
        if exit_code == 3:
            bits.append("kiro --require-mcp-startup failed (exit 3)")
        err = "Kiro MCP capability probe failed: " + "; ".join(bits)
    global _LAST_MCP_PREFLIGHT
    if ok:
        _LAST_MCP_PREFLIGHT = {
            "ok": True,
            "ws": str(ws),
            "mcp_seen": sorted(mcp_seen),
            "wall_ms": round(wall_ms, 1),
        }
    else:
        _LAST_MCP_PREFLIGHT = None
    return {
        "ok": ok,
        "mode": "mcp",
        "exit_code": exit_code,
        "wall_ms": round(wall_ms, 1),
        "log": str(log_path),
        "index": index_info,
        "kiro_answer": answer,
        "tools": tools,
        "mcp_seen": sorted(mcp_seen),
        "required": list(MCP_PREFLIGHT_REQUIRED),
        "missing_required": missing_required,
        "used_cli_locate": used_cli,
        "can_use_scubiee_mcp": can_use,
        "mcp_tools_visible": tools_visible and not denied_phrase,
        "require_mcp_startup": True,
        "error": err,
    }


# Back-compat alias
run_kiro_cli_preflight = run_kiro_mcp_preflight


def run_kiro_rules_probe(
    *,
    ws: Path,
    model: str,
    effort: str,
    timeout_s: int,
    log_dir: Path,
) -> dict[str, Any]:
    """Ask Kiro to quote GATE rules from resources (prove rules are visible without prompt nudge)."""
    agent_path = write_agents(ws, model=model, with_mcp=True)
    agent_name = agent_path.stem
    surface_errs = assert_agent_surface(ws, agent_path, with_mcp=True)
    if surface_errs:
        return {"ok": False, "error": "surface: " + "; ".join(surface_errs)}
    val = _run([str(KIRO), "agent", "validate", "--path", str(agent_path)], cwd=ws)
    if val.returncode != 0:
        return {
            "ok": False,
            "error": f"agent validate failed: {(val.stdout or '') + (val.stderr or '')}".strip(),
        }
    cmd = [
        str(KIRO),
        "chat",
        "--no-interactive",
        "--trust-all-tools",
        "--require-mcp-startup",
        "--agent",
        agent_name,
        "--model",
        model,
        "--effort",
        effort,
        "--wrap",
        "never",
        "--agent-engine",
        "v1",
        "--legacy-ui",
        RULES_PROBE_PROMPT,
    ]
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "kiro_rules_probe.log"
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ws),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
        exit_code = proc.returncode
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        out = ((exc.stdout or "") if isinstance(exc.stdout, str) else "") + "\n" + (
            (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        )
        out += "\n[timeout]"
    wall_ms = (time.perf_counter() - t0) * 1000.0
    log_path.write_text(out, encoding="utf-8")
    rules_path = ws / "out" / "ab_rules_seen.md"
    text = ""
    if rules_path.is_file():
        try:
            text = rules_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
    has_must = "MUST Use Scubiee" in text or "WHEN SCUBIEE MCP IS AVAILABLE" in text
    has_pack = "pack_context" in text
    tools = _parse_tools(_ANSI.sub("", out))
    ok = bool(rules_path.is_file() and len(text.strip()) >= 200 and has_must and has_pack)
    return {
        "ok": ok,
        "exit_code": exit_code,
        "wall_ms": round(wall_ms, 1),
        "log": str(log_path),
        "rules_file": str(rules_path),
        "rules_chars": len(text),
        "quoted_must_use": has_must,
        "quoted_pack_context": has_pack,
        "tools": tools,
        "excerpt": text[:2500],
        "error": None if ok else "rules probe missing MUST Use Scubiee / pack_context quote",
    }


def run_kiro_mcp_readiness(
    *,
    ws: Path,
    model: str,
    effort: str,
    timeout_s: int,
    log_dir: Path,
) -> dict[str, Any]:
    """Ask Kiro right before the with-arm job: are MCP tools/rules/permissions live?"""
    agent_path = write_agents(ws, model=model, with_mcp=True)
    agent_name = agent_path.stem
    surface_errs = assert_agent_surface(ws, agent_path, with_mcp=True)
    if surface_errs:
        return {
            "ok": False,
            "error": "surface: " + "; ".join(surface_errs),
            "kiro_answer": None,
        }
    val = _run([str(KIRO), "agent", "validate", "--path", str(agent_path)], cwd=ws)
    if val.returncode != 0:
        return {
            "ok": False,
            "error": f"agent validate failed: {(val.stdout or '') + (val.stderr or '')}".strip(),
            "kiro_answer": None,
        }

    cmd = [
        str(KIRO),
        "chat",
        "--no-interactive",
        "--trust-all-tools",
        "--require-mcp-startup",
        "--agent",
        agent_name,
        "--model",
        model,
        "--effort",
        effort,
        "--wrap",
        "never",
        "--agent-engine",
        "v1",
        "--legacy-ui",
        MCP_READINESS_PROMPT,
    ]
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "kiro_mcp_readiness.log"
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ws),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            env=_kiro_env(ws),
        )
        raw = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        exit_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        raw = ""
        if isinstance(exc.stdout, str):
            raw += exc.stdout
        if isinstance(exc.stderr, str):
            raw += "\n" + exc.stderr
        raw += f"\n[TIMEOUT after {timeout_s}s]"
        exit_code = 124
    wall_ms = (time.perf_counter() - t0) * 1000
    clean = _strip_ansi(raw)
    log_path.write_text(clean, encoding="utf-8")
    tools = _parse_tools(clean)
    answer = _extract_json_obj(clean)
    mcp_seen = {str(t).lower() for t in (tools.get("mcp_scubiee_tools") or [])}
    denied_phrase = (
        "aren't in my available tool list" in clean.lower()
        or "not in my available tool list" in clean.lower()
        or "mcp tools aren't" in clean.lower()
        or "mcp tools are not" in clean.lower()
    )
    gate_in_log = "gate" in mcp_seen
    ready_ans = bool(answer.get("ready")) if isinstance(answer, dict) else False
    visible_ans = bool(answer.get("mcp_tools_visible")) if isinstance(answer, dict) else gate_in_log
    gate_ok_ans = bool(answer.get("gate_ok")) if isinstance(answer, dict) else gate_in_log
    # Hard proof: MCP gate actually ran. Soft fields from JSON are supporting evidence.
    ok = bool(
        exit_code not in (3, 124)
        and not denied_phrase
        and gate_in_log
        and visible_ans
        and gate_ok_ans
        and (ready_ans or (visible_ans and gate_ok_ans))
    )
    err = None
    if not ok:
        bits = []
        if exit_code == 3:
            bits.append("kiro --require-mcp-startup failed (exit 3)")
        if denied_phrase or not visible_ans:
            bits.append("MCP tools not visible to Kiro")
        if not gate_in_log:
            bits.append("gate not called via MCP")
        if answer:
            bits.append(f"answer={answer}")
        err = "Kiro MCP readiness failed: " + "; ".join(bits) if bits else "Kiro MCP readiness failed"
    return {
        "ok": ok,
        "exit_code": exit_code,
        "wall_ms": round(wall_ms, 1),
        "log": str(log_path),
        "kiro_answer": answer,
        "tools": tools,
        "mcp_seen": sorted(mcp_seen),
        "error": err,
    }


class McpNeutralizer:
    def __init__(self) -> None:
        self._backups: list[tuple[Path, Path | None]] = []

    def __enter__(self) -> McpNeutralizer:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for path in (PROJECT_MCP, USER_MCP):
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file():
                bak = path.with_suffix(path.suffix + f".ab_dev_bak_{stamp}")
                shutil.copy2(path, bak)
                self._backups.append((path, bak))
            else:
                self._backups.append((path, None))
            path.write_text('{"mcpServers":{}}\n', encoding="utf-8")
        return self

    def __exit__(self, *exc: object) -> None:
        for path, bak in reversed(self._backups):
            if bak and bak.is_file():
                shutil.copy2(bak, path)
                bak.unlink(missing_ok=True)


_CLI_LOCATE = re.compile(r"\bscubiee(?:\.exe)?\s+(map|pack|expand)\b", re.I)
# Only count real shell invocations — not GATE text / findstr hits / artifact quotes.
_SHELL_CMD_LINES = re.compile(
    r"(?:I will run the following command:|Executing command:|Running command:)\s*(.+?)\s*"
    r"\(using tool:\s*shell\)",
    re.I | re.S,
)


def _parse_cli_locate_from_shell(text: str) -> list[str]:
    """Extract scubiee map|pack|expand only from shell tool command lines."""
    found: list[str] = []
    for m in _SHELL_CMD_LINES.finditer(text):
        cmd = m.group(1) or ""
        # Ignore findstr/rg searching *for* those strings
        if re.search(r"\b(?:findstr|rg|grep|Select-String)\b", cmd, re.I):
            continue
        for cm in _CLI_LOCATE.finditer(cmd):
            name = cm.group(1).strip().lower()
            if name == "pack":
                found.append("pack_context")
            elif name == "expand":
                found.append("expand_context")
            else:
                found.append(name)
    return found


def _parse_tools(text: str) -> dict[str, Any]:
    mcp_scubiee: list[str] = []
    cli_scubiee = _parse_cli_locate_from_shell(text)
    native: list[str] = []
    for m in _MCP_TOOL.finditer(text):
        tool = m.group(1).strip().lower()
        server = m.group(2).strip().lower()
        if server == "scubiee":
            mcp_scubiee.append(tool)
    for m in _NATIVE_TOOL.finditer(text):
        native.append(m.group(1).strip().lower())
    # Primary scubiee_tools = MCP only (MCP-only harness). CLI tracked separately.
    return {
        "scubiee_tools": list(mcp_scubiee),
        "mcp_scubiee_tools": list(mcp_scubiee),
        "cli_scubiee_tools": list(cli_scubiee),
        "native_tools": native,
        "scubiee_count": len(mcp_scubiee),
        "cli_locate_count": len(cli_scubiee),
        "native_count": len(native),
    }


def _heatmap_discipline(text: str, tools: dict[str, Any]) -> dict[str, Any]:
    """Detect pack skip or pack→whole-file Read bypass (heatmap unused as edit surface)."""
    mcp = [str(t).lower() for t in (tools.get("mcp_scubiee_tools") or tools.get("scubiee_tools") or [])]
    cli_n = int(tools.get("cli_locate_count") or 0)
    had_pack = "pack_context" in mcp
    had_map = "map" in mcp or "map_context" in mcp
    had_expand = "expand_context" in mcp or "collect_hot_context" in mcp
    full_reads = len(re.findall(r"Reading file:.*?\ball lines\b", text, re.I))
    batch_reads = len(re.findall(r"Batch fs_read operation with (\d+) operations", text, re.I))
    pack_bypass = bool(
        had_pack and not had_expand and (full_reads >= 2 or (batch_reads >= 1 and full_reads >= 1))
    )
    map_only_thrash = bool(had_map and not had_pack and (full_reads >= 2 or batch_reads >= 1))
    ok = True
    note = "ok"
    if cli_n:
        ok = False
        note = "FAIL: shell scubiee CLI locate used (MCP-only arm)"
    elif not had_pack and not had_map:
        ok = False
        note = "FAIL: no Scubiee MCP locate/pack calls"
    elif not had_pack:
        ok = False
        note = "FAIL: map without pack_context"
    elif pack_bypass:
        ok = False
        note = "FAIL: pack then whole-file Read without expand/collect (heatmap bypass)"
    elif map_only_thrash:
        ok = False
        note = "FAIL: map-only then whole-file thrash"
    elif had_pack and had_expand:
        note = "pack + expand/collect used"
    elif had_pack:
        note = "pack used; no whole-file bypass detected"
    return {
        "ok": ok,
        "had_pack": had_pack,
        "had_map": had_map,
        "had_expand": had_expand,
        "cli_locate_count": cli_n,
        "full_file_reads": full_reads,
        "batch_fs_reads": batch_reads,
        "note": note,
    }


def _git_diff_stat(ws: Path) -> dict[str, Any]:
    proc = _run(["git", "diff", "--stat", "HEAD"], cwd=ws)
    name_proc = _run(["git", "diff", "--name-only", "HEAD"], cwd=ws)
    files = [ln.strip() for ln in (name_proc.stdout or "").splitlines() if ln.strip()]
    # Include untracked new files (agents often add tests without git add)
    st = _run(["git", "status", "--porcelain"], cwd=ws)
    untracked: list[str] = []
    for ln in (st.stdout or "").splitlines():
        if ln.startswith("?? "):
            path = ln[3:].strip().replace("\\", "/")
            untracked.append(path)
            if path not in files:
                files.append(path)
    return {
        "stat": (proc.stdout or "").strip(),
        "files": files,
        "untracked": untracked,
        "changed": len(files) > 0,
    }


def _run_tests(ws: Path) -> dict[str, Any]:
    """Run focused tests related to soft-locate / seed helpers + any new tests agent added."""
    keywords = tuple(
        k.lower()
        for k in (
            "suggested_seed",
            "next_actions",
            "pick_suggested",
            "bad seed",
            "weak seed",
            "weak_start",
            "remake",
            "start_reliability",
            "assess_start",
            "pack_context",
            *ACTIVE_TEST_KEYWORDS,
        )
        if k
    )
    candidates: list[str] = []
    # Task allowlist first (narrow scoring)
    for rel in ACTIVE_TEST_FILES:
        candidates.append(str(rel).replace("\\", "/"))
    # Always include ladder smoke if present
    candidates.append("tests/test_incremental_context_ladder.py")
    # Tracked + untracked test files the agent may have added
    proc_status = _run(["git", "status", "--porcelain", "--", "tests"], cwd=ws)
    for ln in (proc_status.stdout or "").splitlines():
        path = ln[3:].strip().replace("\\", "/")
        if path.startswith("tests/test_") and path.endswith(".py"):
            candidates.append(path)

    content_hits: list[str] = []
    for p in (ws / "tests").glob("test_*.py"):
        rel = str(p.relative_to(ws)).replace("\\", "/")
        if rel in candidates:
            continue
        name_l = rel.lower()
        # Filename keyword match is high-precision
        if any(k in name_l for k in keywords if len(k) >= 6):
            content_hits.append(rel)
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")[:6000].lower()
        except OSError:
            continue
        hits = sum(1 for k in keywords if k in text)
        # Require ≥2 keyword hits so bare substrings do not pull half the suite
        if hits >= 2:
            content_hits.append(rel)
    # Cap content-discovered files to keep scoring bounded
    candidates.extend(content_hits[:8])

    # de-dupe preserve order
    seen: set[str] = set()
    existing: list[str] = []
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        if (ws / c).is_file():
            existing.append(c)
    if not existing:
        return {"ok": False, "reason": "no candidate tests found", "cmd": None}

    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=line",
        "-p",
        "no:cacheprovider",
        *existing,
    ]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ws),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "reason": "pytest timeout",
            "exit_code": None,
            "seconds": round(time.perf_counter() - t0, 2),
            "cmd": cmd,
            "files": existing,
            "stdout_tail": ((exc.stdout or "") if isinstance(exc.stdout, str) else "")[-2000:],
            "stderr_tail": ((exc.stderr or "") if isinstance(exc.stderr, str) else "")[-1500:],
        }
    return {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "seconds": round(time.perf_counter() - t0, 2),
        "cmd": cmd,
        "files": existing,
        "stdout_tail": (proc.stdout or "")[-2000:],
        "stderr_tail": (proc.stderr or "")[-1500:],
    }


def _score_retrieval(ws: Path, task: dict[str, Any]) -> dict[str, Any]:
    """Score retrieval-only deliverable against harness gold (not shown to agent)."""
    rel = str(task.get("output_file") or "out/ab_retrieval_context.md").replace("\\", "/")
    path = ws / rel
    if not path.is_file():
        return {
            "ok": False,
            "output_file": rel,
            "exists": False,
            "file_rec": 0.0,
            "symbol_rec": 0.0,
            "term_rec": 0.0,
            "chars": 0,
            "note": "missing output file",
        }
    text = path.read_text(encoding="utf-8", errors="replace")
    low = text.lower()
    must_files = [str(x) for x in (task.get("must_files") or ())]
    must_symbols = [str(x) for x in (task.get("must_symbols") or ())]
    must_terms = [str(x) for x in (task.get("must_terms") or ())]
    file_hits = [f for f in must_files if f.lower().replace("\\", "/") in low.replace("\\", "/")]
    sym_hits = [s for s in must_symbols if s.lower() in low]
    term_hits = [t for t in must_terms if t.lower() in low]
    file_rec = (len(file_hits) / len(must_files)) if must_files else 1.0
    symbol_rec = (len(sym_hits) / len(must_symbols)) if must_symbols else 1.0
    term_rec = (len(term_hits) / len(must_terms)) if must_terms else 1.0
    # Pass bar: file exists, substantial, ≥60% files and ≥50% symbols
    ok = bool(
        len(text.strip()) >= 800
        and file_rec >= 0.6
        and symbol_rec >= 0.5
        and term_rec >= 0.5
    )
    return {
        "ok": ok,
        "output_file": rel,
        "exists": True,
        "chars": len(text),
        "file_rec": round(file_rec, 3),
        "symbol_rec": round(symbol_rec, 3),
        "term_rec": round(term_rec, 3),
        "file_hits": file_hits,
        "symbol_hits": sym_hits,
        "term_hits": term_hits,
        "note": "pass" if ok else "below recall/length bar",
    }


def _cross_arm_peek(clean_log: str, ws: Path) -> dict[str, Any]:
    """Detect if the agent tried to read a sibling A/B workspace (not this arm)."""
    low = clean_log.lower().replace("\\", "/")
    bad_hits: list[str] = []
    try:
        parent = ws.resolve().parent
        me = ws.resolve()
    except OSError:
        return {"ok": True, "hits": [], "note": "no cross-arm peek (resolve failed)"}

    def _mentions(path_s: str) -> bool:
        # Avoid '/with' matching inside '/without'
        if not path_s:
            return False
        if path_s + "/" in low:
            return True
        if low.endswith(path_s):
            return True
        # quoted / whitespace-bounded
        if re.search(re.escape(path_s) + r"(?=[/\s\"']|$)", low):
            return True
        return False

    for sibling in ("with", "without"):
        other = (parent / sibling).resolve()
        if other == me:
            continue
        other_s = str(other).lower().replace("\\", "/")
        if _mentions(other_s):
            bad_hits.append(other_s)
        for pat in (
            rf"(?<![a-z])\.\./{sibling}(?![a-z])",
            rf"/{sibling}/out/ab_retrieval_context\.md",
            rf"\\\\{sibling}\\\\out\\\\ab_retrieval_context\.md",
            rf"\.ab_workspaces/[^\s\"']+/{sibling}(?![a-z])",
        ):
            if re.search(pat, low, re.I):
                bad_hits.append(pat)
    # Generic sibling artifact peeks (even without full absolute path)
    for pat in (
        r"(?<![a-z])sibling\s+(?:arm|workspace)",
        r"copy(?:ing|ed)?\s+(?:from\s+)?(?:the\s+)?(?:other|without|with)\s+arm",
        r"other\s+arm['']?s?\s+(?:out/)?ab_retrieval_context",
    ):
        if re.search(pat, low, re.I):
            bad_hits.append(pat)
    uniq = sorted(set(bad_hits))
    return {
        "ok": len(uniq) == 0,
        "hits": uniq[:12],
        "note": "no cross-arm peek" if not uniq else "CROSS-ARM PEEK",
    }


def _cross_arm_copy(runs: dict[str, Any]) -> dict[str, Any]:
    """Fail isolation if both arms wrote near-identical retrieval artifacts (likely copy)."""
    w = runs.get("with") or {}
    o = runs.get("without") or {}
    wt = ((w.get("retrieval") or {}).get("text") or "")
    ot = ((o.get("retrieval") or {}).get("text") or "")
    if not wt or not ot:
        # Fall back to reading output files from workspaces if text not stashed
        for arm, run in (("with", w), ("without", o)):
            if run.get("retrieval") and (run["retrieval"].get("text")):
                continue
            ws = Path(str(run.get("workspace") or ""))
            out_rel = str((ACTIVE_TASK.get("output_file") or "out/ab_retrieval_context.md")).replace("\\", "/")
            p = ws / out_rel if ws else None
            if p and p.is_file():
                try:
                    txt = p.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    txt = ""
                run.setdefault("retrieval", {})["text"] = txt
        wt = ((runs.get("with") or {}).get("retrieval") or {}).get("text") or ""
        ot = ((runs.get("without") or {}).get("retrieval") or {}).get("text") or ""
    if not wt or not ot:
        return {"ok": True, "ratio": None, "note": "no dual artifacts to compare"}
    import difflib

    a = re.sub(r"\s+", " ", wt.strip().lower())
    b = re.sub(r"\s+", " ", ot.strip().lower())
    if a == b:
        return {"ok": False, "ratio": 1.0, "note": "FAIL: identical retrieval artifacts (cross-arm copy)"}
    ratio = difflib.SequenceMatcher(None, a[:8000], b[:8000]).ratio()
    # Extremely high similarity on long docs is suspicious; leave room for shared gold structure
    if len(a) > 2000 and ratio >= 0.97:
        return {
            "ok": False,
            "ratio": round(ratio, 4),
            "note": "FAIL: near-identical retrieval artifacts (likely cross-arm copy)",
        }
    return {"ok": True, "ratio": round(ratio, 4), "note": "artifacts independently distinct"}


def _rubric_check(ws: Path) -> dict[str, Any]:
    """Best-effort behavioral check without prescribing agent path."""
    if ACTIVE_TASK.get("mode") == "retrieval":
        return {"ok": True, "skipped": True, "note": "retrieval mode — no weak-start rubric"}
    sys.path.insert(0, str(ws / "packages"))
    notes: list[str] = []
    try:
        # Prefer context_trace if present
        from pipeline import context_trace as ct  # type: ignore

        # Build synthetic weak cards (tests only) and good cards
        weak_cards = [
            {
                "id": "tests/test_x.py::test_a",
                "file": "tests/test_x.py",
                "symbol": "test_a",
                "kind": "function",
                "score": 20.0,
                "start_line": 1,
                "end_line": 10,
                "role": "test",
            }
        ]
        good_cards = [
            {
                "id": "packages/pipeline/mcp_locate.py::map_impl",
                "file": "packages/pipeline/mcp_locate.py",
                "symbol": "map_impl",
                "kind": "function",
                "score": 12.0,
                "start_line": 100,
                "end_line": 200,
                "role": "function",
            }
        ]

        # Heuristic 1: pick_suggested_seed still prefers packages
        seed_good = None
        if hasattr(ct, "pick_suggested_seed"):
            ranked = (
                ct.rank_soft_map_cards(weak_cards + good_cards)
                if hasattr(ct, "rank_soft_map_cards")
                else weak_cards + good_cards
            )
            seed_good = ct.pick_suggested_seed(ranked)
            notes.append(f"pick_suggested_seed={seed_good}")

        # Heuristic 2: scan source for remake/map next_action on weak seed
        src = (ws / "packages" / "pipeline" / "context_trace.py").read_text(
            encoding="utf-8", errors="replace"
        )
        has_remake_signal = bool(
            re.search(
                r"next_actions|remake|re-?map|richer query|weak.?seed|unreliable|bad.?seed",
                src,
                re.I,
            )
        )
        # Look for new helper names commonly introduced
        helpers = [
            n
            for n in (
                "weak_seed",
                "unreliable_seed",
                "bad_seed",
                "seed_quality",
                "remake_map",
                "advise_remake",
            )
            if n in src.lower()
        ]
        return {
            "ok": bool(has_remake_signal and (seed_good is None or (seed_good or {}).get("file", "").startswith("packages/"))),
            "has_remake_signal_in_context_trace": has_remake_signal,
            "helpers_mentioned": helpers,
            "notes": notes,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "notes": notes}
    finally:
        # avoid polluting later imports
        for mod in list(sys.modules):
            if mod == "pipeline" or mod.startswith("pipeline."):
                if "context_trace" in mod or mod == "pipeline":
                    sys.modules.pop(mod, None)


def run_arm(
    *,
    arm: str,
    ws: Path,
    model: str,
    effort: str,
    timeout_s: int,
    log_dir: Path,
) -> dict[str, Any]:
    with_mcp = arm == "with"
    agent_path = write_agents(ws, model=model, with_mcp=with_mcp)
    agent_name = agent_path.stem
    surface_errs = assert_agent_surface(ws, agent_path, with_mcp=with_mcp)
    if surface_errs:
        return {
            "arm": arm,
            "ok": False,
            "error": "agent surface checks failed:\n- " + "\n- ".join(surface_errs),
            "surface_errors": surface_errs,
        }
    # validate
    val = _run([str(KIRO), "agent", "validate", "--path", str(agent_path)], cwd=ws)
    if val.returncode != 0:
        return {
            "arm": arm,
            "ok": False,
            "error": f"agent validate failed: {val.stdout}\n{val.stderr}",
        }

    cmd = [
        str(KIRO),
        "chat",
        "--no-interactive",
        "--trust-all-tools",
    ]
    if with_mcp:
        cmd.append("--require-mcp-startup")
    cmd.extend(
        [
            "--agent",
            agent_name,
            "--model",
            model,
            "--effort",
            effort,
            "--wrap",
            "never",
            "--agent-engine",
            "v1",
            "--legacy-ui",
            DEV_PROMPT,
        ]
    )

    # Final readiness ask: abort with-arm before burning the expensive job if MCP missing.
    # If preflight in this process already proved MCP tools on the same workspace, skip the
    # second chat (Kiro sometimes drops MCP tools on a follow-up chat).
    readiness: dict[str, Any] | None = None
    if with_mcp:
        pf = _LAST_MCP_PREFLIGHT or {}
        same_ws = str(Path(str(pf.get("ws") or "")).resolve()) == str(ws.resolve()) if pf.get("ws") else False
        proved = bool(
            pf.get("ok")
            and same_ws
            and "gate" in set(pf.get("mcp_seen") or [])
            and "pack_context" in set(pf.get("mcp_seen") or [])
        )
        if proved:
            readiness = {
                "ok": True,
                "skipped": True,
                "reason": "preflight already proved MCP tools on this workspace",
                "mcp_seen": pf.get("mcp_seen"),
                "preflight_wall_ms": pf.get("wall_ms"),
            }
            print(
                json.dumps({"event": "readiness", **readiness}, indent=2, default=str),
                flush=True,
            )
        else:
            print(json.dumps({"event": "readiness_start", "arm": arm}), flush=True)
            readiness = run_kiro_mcp_readiness(
                ws=ws,
                model=model,
                effort=effort,
                timeout_s=min(timeout_s, 300),
                log_dir=log_dir,
            )
            _write_json(log_dir / "kiro_mcp_readiness.meta.json", readiness)
            print(
                json.dumps(
                    {
                        "event": "readiness",
                        **{
                            k: readiness.get(k)
                            for k in ("ok", "exit_code", "wall_ms", "mcp_seen", "error", "kiro_answer")
                        },
                    },
                    indent=2,
                    default=str,
                ),
                flush=True,
            )
            if not readiness.get("ok"):
                return {
                    "arm": arm,
                    "ok": False,
                    "success": False,
                    "error": "aborted: MCP readiness failed before job — " + str(readiness.get("error")),
                    "readiness": readiness,
                    "workspace": str(ws),
                    "agent": agent_name,
                    "model": model,
                    "credits": None,
                    "wall_ms": readiness.get("wall_ms"),
                    "out_tokens_est": 0,
                    "tools": readiness.get("tools") or {},
                    "isolation": {"ok": False, "note": "WARNING: with-arm never called scubiee MCP"},
                    "heatmap": {"ok": False, "note": "FAIL: readiness aborted"},
                    "exit_code": readiness.get("exit_code"),
                }

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{arm}.log"
    t0 = time.perf_counter()
    env = _kiro_env(ws)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ws),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            env=env,
        )
        raw = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        exit_code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        raw = ""
        if isinstance(exc.stdout, str):
            raw += exc.stdout
        if isinstance(exc.stderr, str):
            raw += "\n" + exc.stderr
        raw += f"\n[TIMEOUT after {timeout_s}s]"
        exit_code = 124
        timed_out = True
    wall_ms = (time.perf_counter() - t0) * 1000
    clean = _strip_ansi(raw)
    log_path.write_text(clean, encoding="utf-8")

    tools = _parse_tools(clean)
    credits_m = _CREDIT.search(clean)
    time_m = _TIME.search(clean)
    reported_time_s = None
    if time_m:
        reported_time_s = int(time_m.group(1) or 0) * 60 + int(time_m.group(2) or 0)

    diff = _git_diff_stat(ws)
    retrieval_mode = ACTIVE_TASK.get("mode") == "retrieval"
    if retrieval_mode:
        tests = {"ok": True, "skipped": True, "reason": "retrieval mode — no pytest"}
        rubric = _score_retrieval(ws, ACTIVE_TASK)
    else:
        tests = _run_tests(ws)
        rubric = _rubric_check(ws)
    heatmap = _heatmap_discipline(clean, tools) if with_mcp else {"ok": True, "note": "n/a"}
    peek = _cross_arm_peek(clean, ws)

    cli_leak = int(tools.get("cli_locate_count") or 0)
    mcp_names = {str(t).lower() for t in (tools.get("mcp_scubiee_tools") or tools.get("scubiee_tools") or [])}
    used_pack = "pack_context" in mcp_names
    # With-arm: MCP must be used AND include pack_context (map-only is a policy FAIL)
    if with_mcp:
        isolation_ok = bool(tools["scubiee_count"] > 0 and cli_leak == 0 and used_pack and peek.get("ok"))
        if not peek.get("ok"):
            iso_note = "FAIL: cross-arm workspace peek"
        elif tools["scubiee_count"] == 0:
            iso_note = "WARNING: with-arm never called scubiee MCP"
        elif cli_leak:
            iso_note = "LEAK: shell scubiee CLI locate on MCP-only arm"
        elif not used_pack:
            iso_note = "FAIL: Scubiee MCP used but pack_context missing (map-only / skip-pack)"
        else:
            iso_note = "scubiee MCP used with pack_context; no CLI locate; no cross-arm peek"
    else:
        isolation_ok = bool(tools["scubiee_count"] == 0 and cli_leak == 0 and peek.get("ok"))
        if not peek.get("ok"):
            iso_note = "FAIL: cross-arm workspace peek"
        elif isolation_ok:
            iso_note = "no scubiee leakage; no cross-arm peek"
        else:
            iso_note = "LEAK: scubiee tools appeared"

    if retrieval_mode:
        success = bool(
            (rubric or {}).get("ok")
            and isolation_ok
            and (heatmap.get("ok", True) if with_mcp else True)
            and not timed_out
            and exit_code == 0
        )
    else:
        success = bool(
            diff.get("changed")
            and tests.get("ok")
            and isolation_ok
            and heatmap.get("ok", True)
            and not timed_out
            and exit_code == 0
        )

    result = {
        "arm": arm,
        "workspace": str(ws),
        "agent": agent_name,
        "model": model,
        "effort": effort,
        "cmd": cmd,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_ms": round(wall_ms, 1),
        "out_chars": len(clean),
        "out_tokens_est": (len(clean) + 3) // 4,
        "credits": float(credits_m.group(1)) if credits_m else None,
        "reported_time_s": reported_time_s,
        "tools": tools,
        "heatmap_discipline": heatmap,
        "readiness": readiness,
        "cross_arm_peek": peek,
        "isolation": {
            "ok": isolation_ok,
            "note": iso_note,
        },
        "diff": diff,
        "tests": tests,
        "rubric": rubric,
        "retrieval": rubric if retrieval_mode else None,
        "success": success,
        "log": str(log_path.relative_to(ROOT)).replace("\\", "/"),
    }
    _write_json(log_dir / f"{arm}.meta.json", result)
    return result


def write_md(report: dict[str, Any]) -> None:
    lines = [
        "# Kiro auto — real development A/B (with vs without Scubiee)",
        "",
        f"**Date:** {report['started_at']}",
        f"**Model:** `{report['protocol']['model']}` · **Effort:** `{report['protocol']['effort']}`",
        f"**Task:** `{report['protocol'].get('task_id')}` — {report['protocol'].get('task')}",
        "",
        "## Task (outcome-focused; no path spoilers)",
        "",
        "```",
        (report.get("prompt") or DEV_PROMPT).strip(),
        "```",
        "",
        "## Fairness",
        "",
        "- Identical working-tree snapshots (git baseline commit per arm)",
        "- Same model/effort/timeout; sequential runs",
        "- `includeMcpJson=false`; user+project mcp.json neutralized during suite",
        "- With-arm: **MCP wired** + GATE in AGENTS.md + `.kiro/steering/scubiee.md` "
        "(**strict MUST Use Scubiee**); agent **prompt silent on Scubiee** (rules-only)",
        "- Without-arm: BAN Scubiee CLI + MCP; native explore only",
        "- Preflight: ask Kiro to prove MCP tools + GATE rules + permissions; "
        "`--require-mcp-startup`; abort A/B on failure",
        "- Rules probe: ask Kiro to quote GATE from resources into `out/ab_rules_seen.md`",
        "- Readiness: second ask right before with-arm job (call `gate`); abort if MCP not callable",
        "- Arms are isolated snapshots under `.ab_workspaces/.../{with,without}` — peeking the sibling arm is a FAIL",
        "",
        "## Results",
        "",
        "| arm | success | credits | wall_ms | ~tok | scubiee# | native# | files changed | tests/retrieval | isolation | heatmap |",
        "|-----|---------|--------:|--------:|-----:|---------:|--------:|--------------:|-----------------|-----------|---------|",
    ]
    for arm in ("with", "without"):
        r = report["runs"].get(arm)
        if not r:
            lines.append(f"| {arm} | — | — | — | — | — | — | — | — | — | — |")
            continue
        hm = (r.get("heatmap_discipline") or {}).get("ok")
        hm_cell = "n/a" if arm == "without" else ("OK" if hm else "BYPASS")
        ret = r.get("retrieval") or r.get("rubric") or {}
        if (report.get("protocol") or {}).get("task_mode") == "retrieval" or ret.get("output_file"):
            test_cell = (
                f"file_rec={ret.get('file_rec')} sym={ret.get('symbol_rec')} "
                f"({'PASS' if ret.get('ok') else 'FAIL'})"
            )
        else:
            test_cell = "PASS" if (r.get("tests") or {}).get("ok") else "FAIL"
        lines.append(
            f"| {arm} | {'YES' if r.get('success') or r.get('success_corrected') else 'NO'} | {r.get('credits')} | {r.get('wall_ms')} | "
            f"{r.get('out_tokens_est')} | {(r.get('tools') or {}).get('scubiee_count')} | "
            f"{(r.get('tools') or {}).get('native_count')} | {len((r.get('diff') or {}).get('files') or [])} | "
            f"{test_cell} | "
            f"{'OK' if (r.get('isolation') or {}).get('ok') else 'FAIL'} | {hm_cell} |"
        )
    w, o = report["runs"].get("with") or {}, report["runs"].get("without") or {}

    def _delta(key: str) -> str:
        a, b = w.get(key), o.get(key)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or not b:
            return "n/a"
        d = a - b
        pct = 100.0 * d / b
        return f"{d:+.3g} ({pct:+.0f}%)"

    lines += [
        "",
        "### Savings (with − without); negative = with used less",
        "",
        "| Metric | delta |",
        "|--------|------:|",
        f"| credits | {_delta('credits')} |",
        f"| wall_ms | {_delta('wall_ms')} |",
        f"| ~tokens (stdout/4) | {_delta('out_tokens_est')} |",
        "",
        "## Diffs",
        "",
    ]
    for arm in ("with", "without"):
        r = report["runs"].get(arm)
        if not r:
            lines.append(f"### {arm}")
            lines.append("_not run_")
            lines.append("")
            continue
        lines.append(f"### {arm}")
        lines.append("```")
        lines.append((r.get("diff") or {}).get("stat") or "(no diff)")
        ut = (r.get("diff") or {}).get("untracked") or []
        if ut:
            lines.append("untracked: " + ", ".join(ut))
        lines.append("```")
        lines.append("")
    lines += ["## Protocol", "", "```json", json.dumps(report["protocol"], indent=2), "```", ""]
    out_md = Path(report.get("out_md") or OUT_MD)
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    global DEV_PROMPT, ACTIVE_TASK_ID, ACTIVE_TASK, ACTIVE_TEST_KEYWORDS, ACTIVE_TEST_FILES, OUT_JSON, OUT_MD

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default="auto")
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--timeout-s", type=int, default=900)
    ap.add_argument("--arm", choices=("with", "without", "both"), default="both")
    ap.add_argument(
        "--task",
        choices=sorted(TASKS.keys()),
        default="engine_visibility",
        help="Which development job to run (default: engine_visibility)",
    )
    ap.add_argument(
        "--check-surface",
        action="store_true",
        help="Write agents into a temp snapshot and verify tools/rules/permissions; no chat.",
    )
    ap.add_argument(
        "--preflight-only",
        action="store_true",
        help="Ask Kiro live whether CLI map/pack works in a snapshot; abort without A/B.",
    )
    ap.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip mandatory Kiro CLI capability probe (not recommended).",
    )
    args = ap.parse_args()

    task = TASKS[args.task]
    ACTIVE_TASK_ID = args.task
    ACTIVE_TASK = task
    DEV_PROMPT = task["prompt"]
    ACTIVE_TEST_KEYWORDS = task["test_keywords"]
    ACTIVE_TEST_FILES = tuple(task.get("test_files") or ())
    OUT_JSON = ROOT / "docs" / "superpowers" / "plans" / f"{task['out_stem']}.json"
    OUT_MD = ROOT / "docs" / "superpowers" / "plans" / f"{task['out_stem']}.md"

    if args.check_surface:
        check_dir = BASE / "_surface_check"
        if check_dir.exists():
            shutil.rmtree(check_dir, ignore_errors=True)
        check_dir.mkdir(parents=True, exist_ok=True)
        # Minimal workspace: only files gate surface needs
        (check_dir / "AGENTS.md").write_text("# check\n", encoding="utf-8")
        report: dict[str, Any] = {"ok": True, "arms": {}}
        for arm, with_mcp in (("with", True), ("without", False)):
            ws = check_dir / arm
            ws.mkdir(parents=True, exist_ok=True)
            shutil.copy2(check_dir / "AGENTS.md", ws / "AGENTS.md")
            path = write_agents(ws, model=args.model, with_mcp=with_mcp)
            errs = assert_agent_surface(ws, path, with_mcp=with_mcp)
            val = _run([str(KIRO), "agent", "validate", "--path", str(path)], cwd=ws)
            if val.returncode != 0:
                errs.append(f"kiro validate: {(val.stdout or '') + (val.stderr or '')}".strip())
            report["arms"][arm] = {
                "agent": str(path),
                "errors": errs,
                "ok": not errs,
                "surface": json.loads(
                    (ws / ".kiro" / "ab_surface" / f"{path.stem}.json").read_text(encoding="utf-8")
                ),
            }
            if errs:
                report["ok"] = False
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    _load_dotenv_key()
    if not os.environ.get("KIRO_API_KEY"):
        print("ERROR: KIRO_API_KEY missing", file=sys.stderr)
        return 2
    if not KIRO.is_file():
        print(f"ERROR: kiro-cli missing: {KIRO}", file=sys.stderr)
        return 2
    if not BRIDGE.is_file():
        print(f"ERROR: scubiee MCP bridge missing: {BRIDGE}", file=sys.stderr)
        return 2
    # Snapshot index smoke still uses scubiee CLI register/index/pack (harness only; agents ban CLI locate)
    scubiee_cli = shutil.which("scubiee") or str(Path.home() / ".local" / "bin" / "scubiee.exe")
    if not Path(scubiee_cli).is_file() and not shutil.which("scubiee"):
        print(f"ERROR: scubiee CLI missing on PATH for snapshot index ({scubiee_cli})", file=sys.stderr)
        return 2

    if args.preflight_only:
        # Ask on the live managed repo (indexed) — same gate as "are you able to use MCP…?"
        pf_dir = BASE / "_mcp_preflight_live"
        pf_dir.mkdir(parents=True, exist_ok=True)
        print(
            json.dumps(
                {
                    "event": "preflight_ask_kiro",
                    "workspace": str(ROOT),
                    "note": "live managed repo; MCP-only agent; ask Kiro to use all Scubiee MCP tools",
                    "required_tools": list(MCP_PREFLIGHT_REQUIRED),
                }
            ),
            flush=True,
        )
        with McpNeutralizer():
            pf = run_kiro_mcp_preflight(
                ws=ROOT,
                model=args.model,
                effort=args.effort,
                timeout_s=args.timeout_s,
                log_dir=pf_dir / "logs",
            )
        _write_json(pf_dir / "preflight.json", pf)
        print(json.dumps({"event": "preflight", **pf}, indent=2), flush=True)
        return 0 if pf.get("ok") else 3

    started = datetime.now(timezone.utc).isoformat()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"_{args.task}"
    run_dir = BASE / run_id
    log_dir = run_dir / "logs"
    run_dir.mkdir(parents=True, exist_ok=True)

    arms = ["with", "without"] if args.arm == "both" else [args.arm]
    workspaces: dict[str, Path] = {}

    print(
        json.dumps(
            {
                "event": "snapshot_start",
                "run_id": run_id,
                "task": args.task,
                "title": task["title"],
                "arms": arms,
            }
        ),
        flush=True,
    )
    for arm in arms:
        ws = run_dir / arm
        print(f"SNAPSHOT {arm} -> {ws}", flush=True)
        snapshot_workspace(ws)
        workspaces[arm] = ws
    print(json.dumps({"event": "snapshot_done"}), flush=True)

    preflight_result: dict[str, Any] | None = None
    if not args.skip_preflight and "with" in arms:
        print(json.dumps({"event": "preflight_start"}), flush=True)
        with McpNeutralizer():
            preflight_result = run_kiro_mcp_preflight(
                ws=workspaces["with"],
                model=args.model,
                effort=args.effort,
                timeout_s=min(args.timeout_s, 900),
                log_dir=log_dir,
            )
        _write_json(run_dir / "preflight.json", preflight_result)
        print(json.dumps({"event": "preflight", **preflight_result}, indent=2), flush=True)
        if not preflight_result.get("ok"):
            print(
                "ERROR: mandatory Kiro CLI preflight failed — aborting A/B "
                "(use --skip-preflight only if you knowingly accept a broken locate path)",
                file=sys.stderr,
            )
            protocol = {
                "model": args.model,
                "task_id": args.task,
                "aborted": "preflight_failed",
                "preflight": preflight_result,
                "run_id": run_id,
            }
            _write_json(OUT_JSON, {"started_at": started, "protocol": protocol, "runs": {}})
            return 3
        # Re-baseline with-arm after index/register dirtied the tree
        _run(["git", "add", "-A"], cwd=workspaces["with"])
        _run(
            ["git", "commit", "-m", "ab-dev post-preflight index", "--no-verify"],
            cwd=workspaces["with"],
        )

        print("RULES PROBE (ask Kiro to quote GATE from resources) ...", flush=True)
        rules_probe = run_kiro_rules_probe(
            ws=workspaces["with"],
            model=args.model,
            effort=args.effort,
            timeout_s=min(args.timeout_s, 600),
            log_dir=log_dir,
        )
        _write_json(run_dir / "rules_probe.json", rules_probe)
        print(json.dumps({"event": "rules_probe", **{
            k: rules_probe.get(k)
            for k in (
                "ok",
                "wall_ms",
                "rules_chars",
                "quoted_must_use",
                "quoted_pack_context",
                "error",
                "excerpt",
            )
        }}, indent=2), flush=True)
        if not rules_probe.get("ok"):
            print(
                "ERROR: rules probe failed — Kiro did not surface GATE rules from resources. Aborting.",
                file=sys.stderr,
            )
            protocol = {
                "model": args.model,
                "task_id": args.task,
                "aborted": "rules_probe_failed",
                "preflight": preflight_result,
                "rules_probe": rules_probe,
                "run_id": run_id,
            }
            _write_json(OUT_JSON, {"started_at": started, "protocol": protocol, "runs": {}})
            return 3
        # Copy rules artifact to report dir for inspection
        rp = Path(str(rules_probe.get("rules_file") or ""))
        if rp.is_file():
            shutil.copy2(rp, run_dir / "ab_rules_seen.md")
        _run(["git", "add", "-A"], cwd=workspaces["with"])
        _run(
            ["git", "commit", "-m", "ab-dev post-rules-probe", "--no-verify"],
            cwd=workspaces["with"],
        )
    else:
        rules_probe = {"ok": True, "skipped": True}

    protocol = {
        "model": args.model,
        "effort": args.effort,
        "timeout_s": args.timeout_s,
        "task_id": args.task,
        "task": task["title"],
        "task_mode": task.get("mode") or "dev",
        "output_file": task.get("output_file"),
        "prompt_style": "outcome+requirements+constraints; no path spoilers; with-arm prompt silent on Scubiee (rules-only)",
        "arms_isolated": True,
        "arms": arms,
        "sequential": True,
        "agent_engine": "v1",
        "legacy_ui": True,
        "includeMcpJson": False,
        "locate": "mcp",
        "mcp": True,
        "rules_feed": [
            "AGENTS.md",
            ".kiro/steering/scubiee.md (inclusion: always)",
            "agent prompt WITH_EXTRA (no Scubiee names — points at resources only)",
        ],
        "with_prompt_silent_on_scubiee": True,
        "preflight_required": not args.skip_preflight,
        "preflight_mode": "mcp_all_tools",
        "preflight_required_tools": list(MCP_PREFLIGHT_REQUIRED),
        "preflight": preflight_result,
        "rules_probe": rules_probe,
        "snapshots": {a: str(workspaces[a]) for a in arms},
        "run_id": run_id,
        "project_id": PROJECT_ID,
        "out_json": str(OUT_JSON),
        "out_md": str(OUT_MD),
        "scubiee_cli": scubiee_cli,
    }
    print(json.dumps({"event": "protocol", **protocol}, indent=2), flush=True)

    runs: dict[str, Any] = {}
    with McpNeutralizer():
        for arm in arms:
            print(f"RUN arm={arm} task={args.task} ...", flush=True)
            row = run_arm(
                arm=arm,
                ws=workspaces[arm],
                model=args.model,
                effort=args.effort,
                timeout_s=args.timeout_s,
                log_dir=log_dir,
            )
            runs[arm] = row
            print(
                json.dumps(
                    {
                        "event": "result",
                        "arm": arm,
                        "success": row.get("success"),
                        "credits": row.get("credits"),
                        "wall_ms": row.get("wall_ms"),
                        "tokens": row.get("out_tokens_est"),
                        "files": len((row.get("diff") or {}).get("files") or []),
                        "tests": (row.get("tests") or {}).get("ok"),
                        "isolation": (row.get("isolation") or {}).get("note"),
                        "heatmap": (row.get("heatmap_discipline") or {}).get("note"),
                        "retrieval": {
                            k: (row.get("retrieval") or {}).get(k)
                            for k in (
                                "ok",
                                "file_rec",
                                "symbol_rec",
                                "term_rec",
                                "chars",
                                "note",
                            )
                        }
                        if row.get("retrieval")
                        else None,
                        "exit": row.get("exit_code"),
                        "error": row.get("error"),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            # Do not burn the without-arm if with-arm never got live MCP tools
            if arm == "with" and row.get("error") and "readiness failed" in str(row.get("error")):
                print(
                    "ERROR: aborting A/B — with-arm MCP readiness failed "
                    "(rules/tools/permissions not live). Not running without arm.",
                    file=sys.stderr,
                )
                protocol["aborted"] = "readiness_failed"
                protocol["readiness"] = row.get("readiness")
                break

    # Cross-arm copy detector (retrieval): near-identical artifacts = isolation FAIL
    copy_check = _cross_arm_copy(runs) if len(runs) >= 2 else {"ok": True, "note": "single-arm"}
    protocol["cross_arm_copy"] = copy_check
    if not copy_check.get("ok", True):
        for arm, row in runs.items():
            iso = row.setdefault("isolation", {})
            iso["ok"] = False
            iso["note"] = f"{iso.get('note') or 'isolation'}; {copy_check.get('note')}"
            row["success"] = False
            print(
                json.dumps(
                    {
                        "event": "cross_arm_copy",
                        "arm": arm,
                        "ok": False,
                        "ratio": copy_check.get("ratio"),
                        "note": copy_check.get("note"),
                    }
                ),
                flush=True,
            )

    finished = datetime.now(timezone.utc).isoformat()
    report = {
        "started_at": started,
        "finished_at": finished,
        "protocol": protocol,
        "prompt": DEV_PROMPT,
        "runs": runs,
        "out_md": str(OUT_MD),
        "out_json": str(OUT_JSON),
    }
    # credit/token deltas for claims check
    if "with" in runs and "without" in runs:
        def _d(key: str) -> dict[str, Any] | None:
            a, b = runs["with"].get(key), runs["without"].get(key)
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or not b:
                return None
            return {"with": a, "without": b, "delta": a - b, "pct": round(100.0 * (a - b) / b, 1)}

        report["savings"] = {
            "credits": _d("credits"),
            "wall_ms": _d("wall_ms"),
            "out_tokens_est": _d("out_tokens_est"),
        }
    _write_json(OUT_JSON, report)
    write_md(report)
    print(
        json.dumps(
            {
                "event": "summary",
                "task": args.task,
                "with_success": (runs.get("with") or {}).get("success"),
                "without_success": (runs.get("without") or {}).get("success"),
                "savings": report.get("savings"),
                "json": str(OUT_JSON),
                "md": str(OUT_MD),
            },
            indent=2,
        ),
        flush=True,
    )
    if runs.get("without") and not (runs["without"].get("isolation") or {}).get("ok", True):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

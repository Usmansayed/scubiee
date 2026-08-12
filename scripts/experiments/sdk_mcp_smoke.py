"""Natural Cursor SDK smoke: Context Engine MCP vs Graphify MCP."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))

from pipeline.token_meter import estimate_tokens  # noqa: E402

try:
    from cursor_sdk import StdioMcpServerConfig
except ImportError:  # pragma: no cover - preflight reports this for live runs
    StdioMcpServerConfig = None  # type: ignore[assignment,misc]


PROMPT = (
    "Could you tell me where session context handles are stored and how "
    "the map and focus retrieval flow uses them? "
    "Please don't change anything."
)

GRAPHIFY_RULE = """---
description: Graphify — graph-based repo discovery (reach for it first)
alwaysApply: true
---

# Graphify (reach for it first for discovery)

When you need to **find or understand** code in this repo — especially on a new,
vague, or unfamiliar task — start with Graphify. For structure and relationship
questions the graph is faster and cheaper than Grep sweeps. Grep stays available
as a fallback, but don't open with a blind grep when you haven't located the
code yet.

## When to use which tool

- **New / vague / "where does X happen"** → `query_graph` FIRST.
- **Known symbol** → `get_node`.
- **Callers / usages / how two things connect** → `get_neighbors` /
  `shortest_path`.
- Read a file only after the graph points you at the right symbol/file.

## Grep / Read

- Use them for exact strings / config keys, or as a fallback **after** the graph
  comes up empty — say briefly when you fall back.
- Don't lead with a blind Grep/Glob sweep to locate unfamiliar code; that's what
  `query_graph` is for.
- Running tests, builds, or `git` via the shell is expected and is **not**
  discovery — use the shell freely for those.
"""


CONTEXT_ENGINE_READ_RULE = """---
description: Context Engine — default locate; Grep is rare
alwaysApply: true
---

# Context Engine (CE) = your default code locate

Tools: search | read | status.
Use CE instead of Grep for almost all discovery. Grep is rare.

Need → do this:
- Soft / unfamiliar / "where|how|who|which|what handles X" → search(query) — NEVER Grep first
- Another topic mid-task → search again (new query) — do not Grep that question
- Thin hits → sharper query or k=10 once — then stop; if still thin, ONE Grep max
- After search hits → ALWAYS read(target) before edit (not a native full-file Read)
- Wiring / shared code / "who calls this" → read(target, neighbors=true)
- Exact literal (import/config/error) ONLY after two thin searches → Grep once (≤2 Greps/task)
- Filename you already know → Glob. Is CE up? → status() (never for finding code)

Defaults (don't tune):
- search: fetch=false; skim; then CE read — then edit. Do not skip read.
- If CE returned file+lines → do NOT Grep-thrash or re-Read that span
- Prefer another search/read over Grep. Grep ≪ 10% of locate calls
- Task asks for tests + docs: add a **new** test file + docs note before you finish

Flow: search → read → edit → test. Call CE like Grep: need → tool → continue.
Shell for tests/build/git stays native.

## Fairness constraints for this run (do not violate)

- Do NOT use the Task / explore / subagent tools. Stay in one agent.
- Do discovery yourself with Context Engine (search / read).
"""


CONTEXT_ENGINE_GRAPH_RULE = """---
description: Context Engine — prefer over Grep when layout is unknown
alwaysApply: true
---

# Context Engine (CE) — prefer over Grep when you don't know the layout

Need → do this (FIRST move):
- Unfamiliar / soft / "where does X" → search(query)  [before Grep]
- What calls / uses X → neighbors(target)
- How does A relate to B → graph(question)
- Known exact string / filename only → Grep / Glob
- Is CE up? → status()  (not for finding code)

Defaults: no blind Grep/Read sweeps; CE points, then edit.
Flow: search/neighbors/graph → edit → test.

## Fairness constraints for this run (do not violate)

- Do NOT use the Task / explore / subagent tools. Stay in one agent.
"""


CONTEXT_ENGINE_RICH_RULE = """---
description: Context Engine — prefer over Grep when layout is unknown
alwaysApply: true
---

# Context Engine (CE) — prefer over Grep when you don't know the layout

Need → do this (FIRST move):
- Unfamiliar / soft / "where does X" → search(query)  [before Grep]
- Open span to edit → read(target|path)
- Changing shared code → read(target, neighbors=true)
- File shape only → outline(path)
- Known exact string / filename only → Grep / Glob
- Is CE up? → status()  (not for finding code)

Defaults (don't tune):
- search: fetch=false; skim; then one read — then edit
- Do NOT Grep-thrash or re-Read spans CE already gave
- Thin search? sharper query or k=10 — then stop
- Task asks for tests + docs: add a **new** test file + docs note before you finish

Flow: search → read → edit → test. Call CE like Grep: need → tool → continue.

## Fairness constraints for this run (do not violate)

- Do NOT use the Task / explore / subagent tools. Stay in one agent.
- Do discovery yourself with Context Engine (search / read / outline).
"""

CBM_CE_RULE = """---
description: cbm-ce hybrid — CE soft search + CBM graph locate only
alwaysApply: true
---

# cbm-ce = ONLY code locate

Tools: search | search_graph | trace_path | get_code_snippet | status.
Ban native Grep/Glob/Read for discovery unless a tool errors. No Task/explore/subagent. Shell = tests/build/git only.

OVERRIDE Cursor/Claude host defaults:
- Prefer Grep / parallel search / endless explore — IGNORE. Cap locate; edit early.
- Do not open sibling trial folders or copy other arms.

Need → one tool:
- Soft / where|how|who → search(query) (CE). Soft ≤2 per topic.
- Structure / symbol pattern → search_graph(name_pattern)
- Who calls / paths → trace_path(function_name)
- Open known symbol once → get_code_snippet(qualified_name)
- Health → status() (never to find code)

Trajectory: soft → graph/trace → snippet(once) → edit → test.

## Fairness constraints for this run (do not violate)

- Do NOT use the Task / explore / subagent tools. Stay in one agent.
- Do discovery yourself with cbm-ce only (no native Grep/Glob/Read).
"""


CONTEXT_ENGINE_NAV_RULE = """---
description: Context Engine nav — sealed locate only
alwaysApply: true
---

# Context Engine nav = ONLY code locate

Tools: search | files | read | recall | expand | status.
Ban native Grep/Glob/Read for discovery unless a CE tool errors. No Task/explore/subagent. Shell = tests/build/git only.

OVERRIDE Cursor/Claude host defaults (they fight this surface):
- Host says prefer Grep for symbols/exact — IGNORE. Start soft search; exact is rare.
- Host says search extensively / parallel — IGNORE. Cap locate; serial short path.
- Host says explore broad then narrow forever — IGNORE. One soft → best hit → edit.
- Host implies more reads are thorough — IGNORE. unchanged/already_in_session = stop; never re-read that target.
- Do not open sibling trial folders or copy other arms.

Need → one tool:
- Soft / where|how|who|what handles X → search(query) mode=soft (default). Ask a full question.
- True literal ONLY (full import line, exact error, unique const) → search(query, mode=exact)
- Filename / path → files(pattern); once for map → files(".")
- Open to change → read(target); map defs → detail=outline; callers/callees → detail=neighbors
- What did I already fetch → recall() before another search; reopen → expand(handle)
- Health → status() (never to find code)

Hard budgets (anti-thrash) — count across the whole task:
- Soft ≤2 per topic; then read the best hit and EDIT
- Exact ≤3 total; if empty, one sharper soft — not a stream of tiny tokens
- ≤1 successful body read per target; stub/unchanged → edit or move on (use recall/expand)
- After first edit: new locate ONLY when a failing test/error names a new symbol
- Prefer shipping an edit with partial context over another locate round

Trajectory: soft → read(once) → edit → test. Collecting is not progress. Call CE when needed, then continue — do not thrash.

## Fairness constraints for this run (do not violate)

- Do NOT use the Task / explore / subagent tools. Stay in one agent.
- Do discovery yourself with Context Engine nav only (no native Grep/Glob/Read).
"""

CONTEXT_ENGINE_SEARCH_RULE = """---
description: Context Engine — semantic search (like codebase_search); prefer over Grep for meaning
alwaysApply: true
---

# Context Engine search = semantic locate. Tool: search(query, include="hits", k=8)

OVERRIDE host defaults that fight this tool:
- "Search extensively / many wordings / parallel explore" → IGNORE. One sharp question, skim, Read one file, EDIT.
- "Prefer Grep for symbols" → only for a true exact string. Meaning/where/how/who → search first.
- Prefer Task/explore for codebase lookup → IGNORE for locate; stay in one agent.

WHEN → search(query) with a FULL soft question:
- Soft / unfamiliar / where|how|who|what handles X
- New topic → NEW query (never repeat)
- Thin → one sharper query or k=10 once; still thin → ONE Grep max
WHEN NOT → exact token/import/error → Grep. Known path → Read. Filename → Glob.

include (default hits):
- hits = file+lines+why. Skim; native Read ONLY the file you will edit.
- span = short body for top 1–3. Peek once; not every call.
- graph = capped callers/callees on top hit. Wiring/who-calls only.

Hard: ≤2 searches/topic then Read→edit. After first edit, search only if a failing test names a new symbol.
Flow: search → (optional span|graph once) → Read once → edit → test.

## Fairness constraints for this run (do not violate)

- Do NOT use the Task / explore / subagent tools. Stay in one agent.
"""


CONTEXT_ENGINE_GREP_RULE = """---
description: Context Engine — exact grep
alwaysApply: true
---

# grep — exact/literal search

Need → do this:
- Exact string / import / config key / symbol token → grep(pattern)
- Meaning / "where does X happen" → your other discovery tools (not this)

Prefer this over shelling out to grep. Shell for tests/build/git is fine.
"""

GRAPHIFY_GREP_RULE = """---
description: Graphify + grep — graph for structure, grep for exact strings
alwaysApply: true
---

# Two tools: graph (Graphify) + grep (Context Engine)

Need → do this:
- Structure / what calls / relates to X → Graphify (query_graph / get_node / get_neighbors)
- Exact string / literal → grep(pattern)

Orient with the graph, pin with grep, then edit. Don't open with a blind native grep.
Shell for tests/build/git is fine.
"""


# name -> CE MCP surface. ``context_engine`` follows the ambient CTX_MCP_SURFACE
# (default "read"); the ``ce_*`` arms pin a specific surface so a single run can
# put two CE tool designs head-to-head. ``graphify_grep`` pairs the graphify
# graph server with a grep-only CE server.
_ARM_SURFACE = {
    "ce_read": "read",
    "ce_nav": "nav",
    "ce_graph": "graph",
    "ce_rich": "rich",
    "ce_search": "search",
    "graphify_grep": "grep",
}


def arm_surface(name: str) -> str:
    force = (os.environ.get("CTX_TRIAL_FORCE_SURFACE") or "").strip().lower()
    if force in {"read", "nav", "graph", "rich", "search", "grep"} and name in {
        "ce_read",
        "ce_nav",
        "context_engine",
    }:
        return force
    if name == "context_engine":
        val = (os.environ.get("CTX_MCP_SURFACE") or "read").strip().lower()
        return val if val in {"read", "nav", "graph", "rich", "search"} else "read"
    return _ARM_SURFACE.get(name, "read")


def is_graphify_arm(name: str) -> bool:
    return name == "graphify"


@dataclass(frozen=True)
class ArmConfig:
    name: str
    mcp_servers: dict[str, object]
    setting_sources: list[str]


def load_cursor_api_key(root: Path) -> str:
    exported = os.environ.get("CURSOR_API_KEY", "").strip()
    if exported:
        return exported
    env_path = root / ".env"
    if not env_path.is_file():
        return ""
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return (
        values.get("CURSOR_API_KEY", "").strip()
        or values.get("cursor_api_key", "").strip()
    )


RAW_RULE = """---
description: Native tools only — no MCP / no graph for this run
alwaysApply: true
---

# Native tools only

This run has **no MCP servers** and **no code graph**. Use the built-in
tools only: Grep, Read, Glob, Shell, Edit / Write. Do the task with those.

## Fairness constraints for this run (do not violate)

- Do **NOT** use the Task / explore / subagent tools. Stay in one agent.
- Do the discovery yourself with Grep / Read / Glob.
"""


@contextmanager
def stage_retrieval_rule(repo: Path, arm: str):
    rules = repo / ".cursor" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    context_path = rules / "context-agent.mdc"
    graphify_path = rules / "graphify-agent.mdc"
    paths = (context_path, graphify_path)
    backups = {
        path: path.read_bytes() if path.is_file() else None for path in paths
    }
    try:
        if arm == "raw":
            # Baseline: strip CE/graphify rules so nothing suggests an MCP.
            graphify_path.unlink(missing_ok=True)
            context_path.write_text(RAW_RULE, encoding="utf-8")
        elif arm == "cbm_ce":
            graphify_path.unlink(missing_ok=True)
            context_path.write_text(CBM_CE_RULE, encoding="utf-8")
        elif arm == "graphify":
            context_path.unlink(missing_ok=True)
            graphify_path.write_text(GRAPHIFY_RULE, encoding="utf-8")
        elif arm == "graphify_grep":
            # Two servers: graphify graph tools + a grep-only CE tool. One rule
            # covers both so guidance and providers line up.
            graphify_path.write_text(GRAPHIFY_GREP_RULE, encoding="utf-8")
            context_path.write_text(CONTEXT_ENGINE_GREP_RULE, encoding="utf-8")
        else:
            # Any CE arm — pick the rule that matches this arm's tool surface so
            # the agent gets the right when/why guidance.
            graphify_path.unlink(missing_ok=True)
            surface = arm_surface(arm)
            if surface == "graph":
                context_path.write_text(CONTEXT_ENGINE_GRAPH_RULE, encoding="utf-8")
            elif surface == "rich":
                context_path.write_text(CONTEXT_ENGINE_RICH_RULE, encoding="utf-8")
            elif surface == "search":
                context_path.write_text(CONTEXT_ENGINE_SEARCH_RULE, encoding="utf-8")
            elif surface == "nav":
                context_path.write_text(CONTEXT_ENGINE_NAV_RULE, encoding="utf-8")
            else:
                context_path.write_text(CONTEXT_ENGINE_READ_RULE, encoding="utf-8")
        yield
    finally:
        for path, content in backups.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)


def build_configs(
    root: Path,
    repo: Path,
    python: Path,
    graph_json: Path,
) -> dict[str, ArmConfig]:
    if StdioMcpServerConfig is None:
        raise RuntimeError("cursor-sdk is not installed")
    common_env = {
        "PYTHONPATH": str(root / "packages"),
        "PYTHONUTF8": "1",
    }

    def _ce_arm(name: str) -> ArmConfig:
        # Each CE arm pins its own tool surface so two CE designs can run head to
        # head on the same rig (e.g. ce_rich vs ce_search).
        return ArmConfig(
            name=name,
            mcp_servers={
                "context-engine": StdioMcpServerConfig(
                    command=str(python),
                    args=["-u", "-m", "pipeline.mcp_locate"],
                    env={
                        **common_env,
                        "CTX_REPO": str(repo),
                        "CTX_ENGINE_URL": "http://127.0.0.1:8765",
                        "CTX_RETRIEVE": "D_channel_best",
                        "CTX_TOKEN_MODE": "savings",
                        "CTX_MCP_SURFACE": arm_surface(name),
                    },
                )
            },
            setting_sources=["project"],
        )

    def _graphify_server() -> object:
        return StdioMcpServerConfig(
            command=str(python),
            args=["-u", "-m", "graphify.serve", str(graph_json)],
            env=common_env,
        )

    def _grep_server() -> object:
        return StdioMcpServerConfig(
            command=str(python),
            args=["-u", "-m", "pipeline.mcp_locate"],
            env={
                **common_env,
                "CTX_REPO": str(repo),
                "CTX_ENGINE_URL": "http://127.0.0.1:8765",
                "CTX_RETRIEVE": "D_channel_best",
                "CTX_TOKEN_MODE": "savings",
                "CTX_MCP_SURFACE": "grep",
            },
        )

    def _cbm_ce_arm() -> ArmConfig:
        cbm_bin = (
            (os.environ.get("CTX_CBM_BIN") or "").strip()
            or (os.environ.get("CBM_BIN") or "").strip()
            or "codebase-memory-mcp"
        )
        return ArmConfig(
            name="cbm_ce",
            mcp_servers={
                "cbm-ce": StdioMcpServerConfig(
                    command=str(python),
                    args=["-u", "-m", "hybrid_cbm"],
                    env={
                        **common_env,
                        "CTX_REPO": str(repo),
                        "CTX_ENGINE_URL": "http://127.0.0.1:8765",
                        "CTX_RETRIEVE": "D_channel_best",
                        "CTX_TOKEN_MODE": "savings",
                        "CTX_CBM_BIN": cbm_bin,
                        "CBM_BIN": cbm_bin,
                    },
                )
            },
            setting_sources=["project"],
        )

    configs: dict[str, ArmConfig] = {
        # No MCP / no graph — native Grep/Read/Glob only (token baseline).
        "raw": ArmConfig(
            name="raw",
            mcp_servers={},
            setting_sources=["project"],
        ),
        "graphify": ArmConfig(
            name="graphify",
            mcp_servers={"graphify": _graphify_server()},
            setting_sources=["project"],
        ),
        # graphify graph tools + a grep-only CE server (no search/read).
        "graphify_grep": ArmConfig(
            name="graphify_grep",
            mcp_servers={
                "graphify": _graphify_server(),
                "context-engine": _grep_server(),
            },
            setting_sources=["project"],
        ),
        "cbm_ce": _cbm_ce_arm(),
    }
    for ce_name in (
        "context_engine",
        "ce_read",
        "ce_nav",
        "ce_graph",
        "ce_rich",
        "ce_search",
    ):
        configs[ce_name] = _ce_arm(ce_name)
    return configs


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dict__"):
        return vars(value)
    return value


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    plain = _plain(value)
    if isinstance(plain, str):
        return plain
    return json.dumps(plain, ensure_ascii=False, default=str)


def _tool_call_from_mapping(item: Mapping[str, Any]) -> dict[str, object]:
    args = _plain(
        item.get("arguments")
        or item.get("args")
        or item.get("input")
        or {}
    )
    if not isinstance(args, Mapping):
        args = {}
    provider = str(args.get("providerIdentifier") or item.get("provider") or "")
    tool_name = str(
        args.get("toolName")
        or item.get("tool_name")
        or item.get("name")
        or ""
    )
    nested = args.get("args")
    arguments = nested if isinstance(nested, Mapping) else args
    kind = "mcp" if provider else str(item.get("type") or item.get("name") or "")
    return {
        "name": tool_name,
        "provider": provider,
        "kind": kind,
        "arguments": _plain(arguments) if isinstance(arguments, Mapping) else {},
        "status": str(item.get("status") or ""),
    }


def normalize_message(message: object) -> dict[str, object]:
    raw = _plain(message)
    if not isinstance(raw, Mapping):
        raw = {"type": type(message).__name__, "content": raw}
    envelope = _plain(raw.get("message", raw))
    if not isinstance(envelope, Mapping):
        envelope = raw
    content = envelope.get("content", [])
    if not isinstance(content, list):
        content = [content]

    event: dict[str, object] = {
        "type": str(raw.get("type") or envelope.get("type") or ""),
        "text": "",
        "tool_calls": [],
        "tool_results": [],
    }
    texts: list[str] = []
    calls: list[dict[str, object]] = []
    results: list[dict[str, str]] = []
    for block in content:
        item = _plain(block)
        if not isinstance(item, Mapping):
            continue
        kind = str(item.get("type") or "")
        if kind in {"text", "output_text"}:
            texts.append(_text(item.get("text") or item.get("content")))
        elif "tool" in kind and ("call" in kind or "use" in kind):
            calls.append(_tool_call_from_mapping(item))
        elif "tool" in kind and "result" in kind:
            results.append(
                {
                    "name": str(item.get("name") or item.get("tool_name") or ""),
                    "text": _text(item.get("content") or item.get("result")),
                }
            )

    # Cursor SDK emits top-level SDKToolUseMessage / SDKUsageMessage envelopes.
    msg_type = str(event["type"] or "")
    if msg_type == "tool_call" and not calls:
        call = _tool_call_from_mapping(raw)
        if not call["name"]:
            call["name"] = str(raw.get("name") or "")
        if not call["kind"] or call["kind"] == "tool_call":
            call["kind"] = "mcp" if call["provider"] else str(raw.get("name") or "")
        calls.append(call)
        if raw.get("result") is not None:
            results.append(
                {
                    "name": str(call["name"] or ""),
                    "text": _result_text(raw.get("result")),
                }
            )
    if msg_type == "usage":
        usage = _plain(raw.get("usage") or {})
        if isinstance(usage, Mapping):
            event["usage"] = usage
    if msg_type == "status":
        event["status"] = str(raw.get("status") or "")

    event["text"] = "".join(texts)
    event["tool_calls"] = calls
    event["tool_results"] = results
    return event


def _result_text(value: Any) -> str:
    plain = _plain(value)
    if isinstance(plain, str):
        return plain
    if isinstance(plain, list):
        return "\n".join(_result_text(item) for item in plain)
    if isinstance(plain, Mapping):
        if "text" in plain:
            return _result_text(plain["text"])
        if "content" in plain:
            return _result_text(plain["content"])
    return json.dumps(plain, ensure_ascii=False, default=str)


def extract_conversation_tools(conversation: Any) -> dict[str, object]:
    calls: list[dict[str, object]] = []
    results: list[dict[str, str]] = []
    turns = conversation if isinstance(conversation, list) else []
    for turn_item in turns:
        turn = _plain(turn_item)
        if not isinstance(turn, Mapping):
            continue
        body = _plain(turn.get("turn", turn))
        if not isinstance(body, Mapping):
            continue
        steps = body.get("steps") or []
        for step_item in steps if isinstance(steps, list) else []:
            step = _plain(step_item)
            if not isinstance(step, Mapping) or step.get("type") != "toolCall":
                continue
            message = _plain(step.get("message") or {})
            if not isinstance(message, Mapping):
                continue
            kind = str(message.get("type") or "")
            args = _plain(message.get("args") or {})
            if not isinstance(args, Mapping):
                args = {}
            provider = str(args.get("providerIdentifier") or "")
            name = str(args.get("toolName") or kind)
            arguments = _plain(args.get("args") or args)
            calls.append(
                {
                    "name": name,
                    "provider": provider,
                    "kind": kind,
                    "arguments": arguments,
                }
            )
            result = _plain(message.get("result") or {})
            value = result.get("value") if isinstance(result, Mapping) else result
            results.append({"name": name, "text": _result_text(value)})
    return {
        "type": "conversation_tools",
        "text": "",
        "tool_calls": calls,
        "tool_results": results,
    }


def evaluate_arm(
    name: str,
    events: list[dict],
    final_text: str,
    status: str,
    repo_unchanged: bool,
    wall_ms: float,
) -> dict[str, object]:
    calls = [
        call
        for event in events
        for call in event.get("tool_calls", [])
        if isinstance(call, dict)
    ]
    results = [
        result
        for event in events
        for result in event.get("tool_results", [])
        if isinstance(result, dict)
    ]
    result_text = "\n".join(str(r.get("text") or "") for r in results)
    evidence = f"{result_text}\n{final_text}".lower()
    rubric_pass = "session_store.py" in evidence and (
        "locate.py" in evidence or "handle" in evidence
    )
    expected_provider = (
        "context-engine" if name == "context_engine" else "graphify"
    )
    all_mcp_calls = [
        call
        for call in calls
        if call.get("kind") == "mcp" or bool(call.get("provider"))
    ]
    mcp_calls = [
        call
        for call in all_mcp_calls
        if call.get("provider") == expected_provider
    ]
    unexpected_providers = sorted(
        {
            str(call.get("provider"))
            for call in all_mcp_calls
            if call.get("provider")
            and call.get("provider") != expected_provider
        }
    )
    mcp_used = bool(mcp_calls)
    smoke_pass = (
        status == "finished"
        and mcp_used
        and not unexpected_providers
        and rubric_pass
        and repo_unchanged
    )
    return {
        "name": name,
        "status": status,
        "final_text": final_text,
        "tool_calls": calls,
        "tool_results": results,
        "mcp_call_count": len(mcp_calls),
        "unexpected_mcp_providers": unexpected_providers,
        "all_tool_call_count": len(calls),
        "native_tool_names": [
            str(call.get("name") or "")
            for call in calls
            if call not in mcp_calls
        ],
        "mcp_used": mcp_used,
        "tool_result_chars": len(result_text),
        "tool_result_tokens": estimate_tokens(result_text),
        "rubric_pass": rubric_pass,
        "repo_unchanged": repo_unchanged,
        "wall_ms": round(wall_ms, 1),
        "smoke_pass": smoke_pass,
    }


def _git_bytes(repo: Path) -> bytes:
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    return diff + b"\0STATUS\0" + status


def _tree_bytes(repo: Path) -> bytes:
    digest = hashlib.sha256()
    ignored = {
        ".context-engine",
        ".git",
        ".venv",
        "__pycache__",
        "node_modules",
    }
    for path in sorted(repo.rglob("*")):
        if not path.is_file() or any(part in ignored for part in path.parts):
            continue
        rel = path.relative_to(repo).as_posix()
        digest.update(rel.encode("utf-8", errors="replace"))
        try:
            digest.update(path.read_bytes())
        except OSError:
            continue
    return digest.digest()


def repo_snapshot(repo: Path) -> str:
    payload = _git_bytes(repo) if (repo / ".git").exists() else _tree_bytes(repo)
    return hashlib.sha256(payload).hexdigest()


def engine_repo_matches(status: Mapping[str, Any], repo: Path) -> bool:
    served = str(status.get("repo") or "").strip()
    if not served:
        return False
    return os.path.normcase(str(Path(served).resolve())) == os.path.normcase(
        str(repo.resolve())
    )


def ensure_engine_repo(repo: Path) -> None:
    from pipeline.client import EngineClient
    from pipeline.daemon import ensure_daemon, start_daemon, stop_daemon

    ensure_daemon(repo)
    status = EngineClient().status()
    if not engine_repo_matches(status, repo):
        stop_daemon()
        started = start_daemon(repo)
        if not started.get("ok"):
            raise RuntimeError(f"failed to start engine for {repo}: {started}")
        status = EngineClient().status()
    if not engine_repo_matches(status, repo):
        raise RuntimeError(
            f"engine serves {status.get('repo')!r}, expected {str(repo)!r}"
        )


def render_report(data: dict[str, Any]) -> str:
    lines = [
        "# Natural Cursor SDK MCP smoke",
        "",
        "## Prompt",
        "",
        data["prompt"],
        "",
        "## Results",
        "",
        "| Arm | Status | MCP calls | Result tokens | Rubric | Unchanged | Pass |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for name in ("context_engine", "graphify"):
        arm = data.get("arms", {}).get(name, {})
        lines.append(
            f"| {name} | {arm.get('status', '')} | "
            f"{arm.get('mcp_call_count', 0)} | "
            f"{arm.get('tool_result_tokens', 0)} | "
            f"{arm.get('rubric_pass', False)} | "
            f"{arm.get('repo_unchanged', False)} | "
            f"{arm.get('smoke_pass', False)} |"
        )
    lines += [
        "",
        "## Experimental caveat",
        "",
        "Both arms loaded equivalent arm-specific, always-applied retrieval "
        "rules. Each rule asks its available MCP to perform discovery before "
        "native broad scans; neither prompt mentions MCP or tool names.",
        "",
    ]
    return "\n".join(lines)


async def observe_run(
    run: Any,
    timeout_s: float,
) -> tuple[list[dict], str, str, str]:
    async def _observe() -> tuple[list[dict], str, str]:
        events: list[dict] = []
        async for message in run.messages():
            events.append(normalize_message(message))
        terminal = await run.wait()
        raw_status = getattr(terminal, "status", "error")
        status = str(getattr(raw_status, "value", raw_status)).lower()
        final_text = str(getattr(terminal, "result", "") or "")
        if not final_text:
            final_text = "".join(
                str(event.get("text") or "") for event in events
            )
        if run.supports("conversation"):
            raw = await run.conversation_json()
            conversation = json.loads(raw)
            events.append(extract_conversation_tools(conversation))
        return events, final_text, status

    try:
        events, final_text, status = await asyncio.wait_for(
            _observe(), timeout=timeout_s
        )
        return events, final_text, status, ""
    except asyncio.TimeoutError:
        await run.cancel()
        return [], "", "timeout", f"run timed out after {timeout_s:g}s"


async def run_arm(
    client: Any,
    config: ArmConfig,
    repo: Path,
    model: str,
    timeout_s: float,
) -> dict[str, object]:
    from cursor_sdk import AgentOptions, LocalAgentOptions, SendOptions

    before = repo_snapshot(repo)
    events: list[dict] = []
    t0 = time.perf_counter()
    status = "error"
    final_text = ""
    agent_id = ""
    run_id = ""
    error = ""
    try:
        options = AgentOptions(
            model=model,
            api_key=os.environ.get("CURSOR_API_KEY"),
            local=LocalAgentOptions(
                cwd=repo,
                setting_sources=config.setting_sources,
            ),
            mcp_servers=config.mcp_servers,
        )
        async with await client.create_agent(options) as agent:
            agent_id = str(getattr(agent, "agent_id", ""))
            run = await agent.send(
                PROMPT,
                SendOptions(mcp_servers=config.mcp_servers),
            )
            run_id = str(getattr(run, "id", ""))
            events, final_text, status, error = await observe_run(
                run, timeout_s=timeout_s
            )
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    after = repo_snapshot(repo)
    outcome = evaluate_arm(
        config.name,
        events,
        final_text,
        status,
        before == after,
        (time.perf_counter() - t0) * 1000,
    )
    outcome.update(
        {
            "agent_id": agent_id,
            "run_id": run_id,
            "error": error,
            "setting_sources": config.setting_sources,
            "mcp_servers": sorted(config.mcp_servers),
        }
    )
    return outcome


async def run_trial(
    repo: Path,
    model: str,
    timeout_s: float,
) -> dict[str, Any]:
    from cursor_sdk import AsyncClient
    from pipeline.session_store import clear_store
    from pipeline.store import PipelineStore
    from pipeline.work_session import clear_session

    store = PipelineStore(repo)
    if not store.load_chunks():
        raise RuntimeError(f"repository is not indexed: {repo}")
    graph_json = store.base / "graph.json"
    if not graph_json.is_file():
        raise RuntimeError(f"Graphify graph is missing: {graph_json}")

    ensure_engine_repo(repo)
    rule_source = ROOT / ".cursor" / "rules" / "context-agent.mdc"
    rule_target = repo / ".cursor" / "rules" / "context-agent.mdc"
    rule_target.parent.mkdir(parents=True, exist_ok=True)
    rule_target.write_text(rule_source.read_text(encoding="utf-8"), encoding="utf-8")

    configs = build_configs(ROOT, repo, Path(sys.executable), graph_json)
    arms: dict[str, dict[str, object]] = {}
    async with await AsyncClient.launch_bridge(
        workspace=repo,
        timeout=30,
    ) as client:
        for name in ("context_engine", "graphify"):
            print(f"running {name}...", flush=True)
            with stage_retrieval_rule(repo, name):
                if name == "context_engine":
                    clear_session(repo)
                    clear_store(repo)
                arms[name] = await run_arm(
                    client, configs[name], repo, model, timeout_s
                )
            print(
                f"{name}: status={arms[name]['status']} "
                f"calls={arms[name]['mcp_call_count']} "
                f"pass={arms[name]['smoke_pass']}",
                flush=True,
            )
    return {
        "prompt": PROMPT,
        "model": model,
        "repo": str(repo),
        "arms": arms,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=ROOT,
    )
    parser.add_argument("--model", default="composer-2.5")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "out" / "experiments" / "sdk_mcp_smoke",
    )
    args = parser.parse_args()
    api_key = load_cursor_api_key(ROOT)
    if not api_key:
        print("ERROR: CURSOR_API_KEY/cursor_api_key is not configured", flush=True)
        return 2
    os.environ["CURSOR_API_KEY"] = api_key
    data = asyncio.run(
        run_trial(args.repo.resolve(), args.model, args.timeout)
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (args.out / "REPORT.md").write_text(render_report(data), encoding="utf-8")
    print(f"wrote {args.out / 'results.json'}", flush=True)
    print(f"wrote {args.out / 'REPORT.md'}", flush=True)
    ce_ok = bool(data["arms"]["context_engine"]["smoke_pass"])
    graph_ok = bool(data["arms"]["graphify"]["mcp_used"])
    return 0 if ce_ok and graph_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

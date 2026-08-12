"""Isolated workspace helpers for the SDK development trial."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SMOKE_SCRIPT = Path(__file__).with_name("sdk_mcp_smoke.py")


def _load_smoke_module():
    module_name = "_sdk_mcp_smoke_for_dev_trial"
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, SMOKE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load smoke helper: {SMOKE_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


smoke = _load_smoke_module()

# Default self-trial prompt (ce profile).
CE_PROMPT = (
    "Hey, the code search in this project is kind of dumb about short or "
    "abbreviated queries. If I search for something like 'auth cfg' or 'db conn' "
    "or 'req handler', it doesn't seem to realise that 'cfg' means config, 'db "
    "conn' is a database connection, 'req' is request, and so on — and it doesn't "
    "split up camelCase / snake_case names either, so a query like "
    "'getUserConfig' misses stuff. Basically the search should be smarter about "
    "expanding terse queries into their fuller forms before it looks things up.\n\n"
    "Can you add query expansion to fix this? I don't know the codebase layout, "
    "so you'll need to poke around and figure out where a search query actually "
    "gets processed/tokenised before retrieval happens, and hook the expansion in "
    "there. Please also give me a way to turn it off, add some tests so it doesn't "
    "regress, and jot down a short note in the docs. Make it an actual working "
    "change, not a stub."
)

# Fairness: both arms must stay single-agent. Task/explore subagents made the
# previous raw run incomparable (raw offloaded discovery; CE did not).
# Public SDK name is lowercase "task" (disallowing it blocks subagents).
DISALLOWED_TOOLS = ("task",)

# Shared fairness clause appended into every arm's staged rule so the agent is
# told the same constraint even if the SDK flag is ignored.
FAIRNESS_RULE_SUFFIX = """

## Fairness constraints for this run (do not violate)

- Do **NOT** use the Task / explore / subagent tools. Stay in one agent.
- Do the discovery yourself with the tools available to this arm.
"""


# Task for the frontend-mcp repo (a real MCP server codebase). Deliberately
# vague about layout so the agent must DISCOVER where tools are declared, where
# handlers live, and how they get dispatched — which is exactly what the
# retrieval MCP is being compared on.
FRONTEND_PROMPT_THRASH = (
    "Hey — agents using our perception MCP keep thrashing. They re-run the same "
    "expensive observation / verify steps even when that evidence was already "
    "collected earlier in the session, and when a tool comes back degraded they "
    "often just plow ahead instead of noticing. Also the codebase-intelligence / "
    "code-graph side still isn't reachable as its own first-class perception "
    "tool the way the other perception tools are.\n\n"
    "I need you to fix both of these, as one coherent change:\n"
    "1) Add a first-class perception tool that queries the pure-Python codebase "
    "intelligence / code graph (search / related files / neighbors style), wired "
    "the same way other perception tools are — schema, handler, and runtime "
    "dispatch by name. Gate it behind an env toggle (default on) with a graceful "
    "degraded envelope when it's off.\n"
    "2) Add a small session-evidence recall path so an agent can ask what was "
    "already observed / verified this session (or get a clear empty answer), and "
    "make sure agent-guidance / coordinator-facing text actually points agents at "
    "that instead of redoing the same browser work. Also env-gated if that fits "
    "the project's toggle patterns.\n\n"
    "I don't know the layout at all — you'll need to poke around and find where "
    "tool schemas live, where handlers live, how dispatch works, where envelopes "
    "are built, where session/store state lives, and where agent guidance / "
    "coordinator briefing text is authored. Touch the real integration points, "
    "not stubs. Add tests so this doesn't regress, bump any tool-count / contract "
    "expectations the repo already guards, and leave a short docs note. Make it "
    "actually work across multiple sides of the codebase."
)

# Alternate vague multi-file tasks for variance rematches (same scoring shape).
FRONTEND_PROMPT_DEGRADED = (
    "Hey — when a perception tool comes back degraded or partial, agents usually "
    "just ignore it and keep going, which wastes the next few steps. Separately, "
    "there's no first-class way for an agent to ask \"what expensive browser / "
    "observe work did I already pay for this session?\" without redoing it.\n\n"
    "Please do both as one coherent change:\n"
    "1) Add a clear degraded-result path: when a tool result is degraded / partial, "
    "the envelope (or guidance attached to it) should tell the agent what failed "
    "and what a sensible next step is — not just a silent half-result. Wire this "
    "through the real envelope / guidance path the project already uses, with an "
    "env toggle if that matches existing patterns (default on).\n"
    "2) Add a session-spend / prior-evidence recall tool (or path) so an agent can "
    "list what was already observed / verified / navigated this session (or get a "
    "clear empty answer), and point agent-facing guidance at that instead of "
    "blindly re-running browser work. Env-gated if that fits.\n\n"
    "I don't know the layout — find where envelopes are built, where tool results "
    "are post-processed, where session/store state lives, where tool schemas and "
    "handlers are registered, and where agent guidance is authored. Touch real "
    "integration points, not stubs. Add tests, bump any tool-count / contract "
    "guards, and leave a short docs note."
)

FRONTEND_PROMPT_CONSISTENCY = (
    "Hey — agents keep asking for a single \"what UI consistency issues should I "
    "fix?\" move, but today that seems scattered across design-graph / audit / "
    "propose-fix style pieces and isn't easy to hit as one first-class perception "
    "tool. Also the agent guidance doesn't clearly tell them when to use that "
    "path vs jumping straight into edits.\n\n"
    "I need one coherent change:\n"
    "1) Add (or finish wiring) a first-class perception tool that returns a short "
    "list of consistency / design-graph fix proposals for the current session or "
    "page context — schema, handler, and runtime dispatch like the other "
    "perception tools. Gate it behind an env toggle (default on) with a graceful "
    "degraded envelope when the graph/audit side isn't available.\n"
    "2) Update agent-guidance / coordinator-facing text so agents are pointed at "
    "that tool before large UI edits, and add a tiny session note path if the "
    "project already stores session state (what was proposed / applied), or a "
    "clear empty answer if nothing is there yet.\n\n"
    "I don't know the layout at all — poke around for tool schemas, handlers, "
    "dispatch, envelopes, design-graph / consistency pieces, session store, and "
    "guidance text. Touch real integration points, not stubs. Add tests, bump "
    "tool-count / contract expectations if the repo guards them, and leave a "
    "short docs note."
)

# Heavier dual-feature prompt for 4–10 min rematch batteries: two distinct
# subsystems (code-graph locate + consistency fix proposals) in one ask.
FRONTEND_PROMPT_COMBO = (
    "Hey — two related gaps are slowing agents down on this perception MCP, and "
    "I'd like them fixed together as one coherent change.\n\n"
    "First: the codebase-intelligence / code-graph side still isn't reachable as "
    "its own first-class perception tool the way the other perception tools are. "
    "Agents need a real tool that can query the pure-Python code graph "
    "(search / related files / neighbors style) — schema, handler, and runtime "
    "dispatch by name, same patterns as the rest of the server. Gate it behind "
    "an env toggle (default on) with a graceful degraded envelope when it's off "
    "or unavailable.\n\n"
    "Second: agents keep asking for a single \"what UI consistency issues should "
    "I fix?\" move, but that seems scattered across design-graph / audit / "
    "propose-fix style pieces. Add (or finish wiring) a first-class perception "
    "tool that returns a short list of consistency / design-graph fix proposals "
    "for the current session or page context — again schema, handler, dispatch, "
    "env-gated (default on), degraded envelope when the graph/audit side isn't "
    "ready. Update agent-guidance / coordinator-facing text so agents are pointed "
    "at that tool before large UI edits, and add a tiny session note path if the "
    "project already stores session state (what was proposed / applied), or a "
    "clear empty answer if nothing is there yet.\n\n"
    "I don't know the layout at all — you'll need to poke around for tool "
    "schemas, handlers, dispatch, envelopes, code-graph / codebase-intelligence "
    "pieces, design-graph / consistency pieces, session store, and guidance "
    "text. Touch real integration points on both features, not stubs. Add tests "
    "(at least one new test file), bump any tool-count / contract expectations "
    "the repo already guards, and leave a short docs note covering both. Make "
    "both features actually work."
)

FRONTEND_PROMPTS = {
    "thrash": FRONTEND_PROMPT_THRASH,
    "degraded": FRONTEND_PROMPT_DEGRADED,
    "consistency": FRONTEND_PROMPT_CONSISTENCY,
    "combo": FRONTEND_PROMPT_COMBO,
}

# Back-compat alias used by older docs/tests.
FRONTEND_PROMPT = FRONTEND_PROMPT_THRASH

# Which target the trial runs against. "ce" (default) = self-trial on THIS repo
# with the pytest-gated query-expansion task. "frontend" = the frontend-mcp repo
# with a vague tool-wiring task, scored on task shape (no pytest gate, since
# that repo's heavy deps aren't installed in this tooling venv). Set via
# CTX_TRIAL_PROFILE; tooling (pipeline/graphify/venv) always stays this repo.
# CTX_FRONTEND_PROMPT selects thrash|degraded|consistency|combo when profile=frontend.
TRIAL_PROFILE = (os.environ.get("CTX_TRIAL_PROFILE") or "ce").strip().lower()


def resolve_shared_prompt() -> str:
    """Pick the active trial prompt from profile + CTX_FRONTEND_PROMPT."""
    if TRIAL_PROFILE != "frontend":
        return CE_PROMPT
    pid = (os.environ.get("CTX_FRONTEND_PROMPT") or "thrash").strip().lower()
    return FRONTEND_PROMPTS.get(pid, FRONTEND_PROMPT_THRASH)


SHARED_PROMPT = resolve_shared_prompt()

COPY_EXCLUDED_NAMES = {
    ".git",
    ".venv",
    ".context-engine",
    ".pytest_cache",
    "__pycache__",
    "out",
    ".env",
    ".superpowers",
    # Bulk trees the focus task never touches. Copying them cost ~570MB per
    # arm and dragged every tree hash over ~15k files.
    "research",
    "testdata",
    "scripts",
    "graphify-out",
    "vendor",
    "node_modules",
}

EXPERIMENT_DOC_PREFIX = (
    "2026-08-08-sdk-development-context-engine-vs-graphify"
)
_NULL_DEV = "NUL" if os.name == "nt" else "/dev/null"

# A development agent thinks for long stretches, so silence is only a failure
# signal when nothing arrives for a while; the ceiling is the backstop.
# Local SDK runs frequently do not self-finalize: after the agent completes its
# turn, neither the stream nor GetRun reports terminal, so a long stream idle is
# the practical "agent is done" signal. Kept generous so a slow silent tool call
# is not mistaken for completion. CBM graph tools can stay quiet for minutes —
# override via CTX_TRIAL_IDLE_S.
IDLE_TIMEOUT_S = float(os.environ.get("CTX_TRIAL_IDLE_S") or 300.0)
HEARTBEAT_S = 30.0
# After cancelling the run the stream should close promptly.
CANCEL_DRAIN_GRACE_S = 60.0
WAIT_GRACE_S = 60.0
CONVERSATION_GRACE_S = 45.0
# Poll interval for the cheap GetRun status snapshot. The blocking WaitLiveRun
# unary exceeds the bridge read timeout on long runs, so we poll status and only
# call WaitLiveRun once the run is already terminal (it returns immediately).
TERMINAL_POLL_S = 6.0


def _copy_ignore(directory: str, names: list[str]) -> set[str]:
    ignored = {
        name
        for name in names
        if (
            name in COPY_EXCLUDED_NAMES
            or name.startswith(".sim-ce-home")
            or name.startswith(EXPERIMENT_DOC_PREFIX)
        )
    }
    if Path(directory).name == ".cursor":
        ignored.add("mcp.json")
    return ignored


def _git_command(*args: str) -> list[str]:
    return ["git", "-c", "core.longpaths=true", *args]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _git_command(*args),
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )


def _digest_chunk(digest: "hashlib._Hash", data: bytes) -> None:
    digest.update(len(data).to_bytes(8, "big"))
    digest.update(data)


def _is_excluded_path(repo: Path, path: Path) -> bool:
    rel = path.relative_to(repo)
    for part in rel.parts:
        if (
            part in COPY_EXCLUDED_NAMES
            or part.startswith(".sim-ce-home")
            or part.startswith(EXPERIMENT_DOC_PREFIX)
        ):
            return True
    return rel.as_posix() == ".cursor/mcp.json"


def copy_workspace(source: Path, target: Path) -> str:
    shutil.copytree(source, target, ignore=_copy_ignore)
    _git(target, "init")
    info_exclude = target / ".git" / "info" / "exclude"
    info_exclude.write_text(".context-engine/\nout/\n", encoding="utf-8")
    _git(target, "add", "-A")
    _git(
        target,
        "-c",
        "user.name=Context Trial",
        "-c",
        "user.email=trial@local.invalid",
        "commit",
        "-m",
        "trial baseline",
    )
    return _git(target, "rev-parse", "HEAD").stdout.strip()


def _untracked_diff(repo: Path) -> str:
    listed = subprocess.run(
        _git_command("ls-files", "--others", "--exclude-standard", "-z"),
        cwd=repo,
        check=True,
        capture_output=True,
    )
    patches: list[str] = []
    for rel in listed.stdout.split(b"\0"):
        if not rel:
            continue
        rel_text = rel.decode("utf-8", errors="surrogateescape")
        if not (repo / rel_text).is_file():
            continue
        proc = subprocess.run(
            _git_command(
                "diff",
                "--no-index",
                "--no-ext-diff",
                _NULL_DEV,
                rel_text,
            ),
            cwd=repo,
            capture_output=True,
            text=True,
        )
        if proc.returncode not in (0, 1):
            proc.check_returncode()
        if proc.stdout:
            patches.append(proc.stdout)
    return "".join(patches)


def git_diff(repo: Path) -> str:
    tracked = _git(repo, "diff", "--no-ext-diff", "HEAD").stdout
    return tracked + _untracked_diff(repo)


_TEST_FILE_RE = re.compile(r"b/(tests/test_[\w./-]+\.py)")
_CHANGED_FILE_RE = re.compile(r"^diff --git a/[\w./-]+ b/([\w./-]+)", re.MULTILINE)


def changed_files(diff_text: str) -> list[str]:
    """All repo-relative paths touched by the diff (tracked + untracked)."""
    norm = diff_text.replace("\\", "/")
    files = set(_CHANGED_FILE_RE.findall(norm))
    # Untracked files appear via `git diff --no-index NUL b/<path>` too.
    files.update(re.findall(r"\+\+\+ b/([\w./-]+)", norm))
    return sorted(f for f in files if f and f != "dev/null")


def added_test_files(diff_text: str) -> list[str]:
    """Discover *new* test files the agent created (not merely modified).

    Counts only paths that appear as brand-new in the diff (--- /dev/null or
    --- NUL). Modified existing tests/test_*.py files do not count — that was
    inflating work_complete on the frontend profile.
    """
    norm = diff_text.replace("\\", "/")
    new_paths: set[str] = set()
    for m in re.finditer(
        r"--- (?:/dev/null|NUL)\n\+\+\+ b/(tests/test_[\w./-]+\.py)",
        norm,
    ):
        new_paths.add(m.group(1))
    new_paths.discard(REGRESSION_TEST_MODULE)
    return sorted(new_paths)


def _hashable_files(repo: Path) -> list[tuple[str, Path]]:
    """Collect hashable files, pruning excluded directories during the walk.

    Enumerating first and filtering after made this walk the whole source tree
    (including a multi-GB ``out/``) on every call.
    """
    found: list[tuple[str, Path]] = []
    for directory, dir_names, file_names in os.walk(repo):
        current = Path(directory)
        dir_names[:] = [
            name
            for name in dir_names
            if not _is_excluded_path(repo, current / name)
        ]
        for name in file_names:
            path = current / name
            if _is_excluded_path(repo, path):
                continue
            found.append((path.relative_to(repo).as_posix(), path))
    found.sort(key=lambda item: item[0])
    return found


def source_tree_hash(repo: Path) -> str:
    digest = hashlib.sha256()
    for rel, path in _hashable_files(repo):
        try:
            content = path.read_bytes()
        except OSError:
            continue
        _digest_chunk(digest, rel.encode("utf-8"))
        _digest_chunk(digest, content)
    return digest.hexdigest()


USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "total_tokens",
)


def usage_dict(usage: Any) -> dict[str, int | None] | None:
    if usage is None:
        return None
    if isinstance(usage, Mapping):
        if not all(field in usage for field in USAGE_FIELDS):
            return None
        return {field: usage[field] for field in USAGE_FIELDS}
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "total_tokens": usage.total_tokens,
    }


def _thrash_metrics(all_calls: list[dict]) -> dict[str, Any]:
    """Locate thrash KPIs from ordered tool calls."""
    first_edit: int | None = None
    locate_pre = 0
    locate_post = 0
    seen_edit = False
    native_locate = 0
    locate_native = {"grep", "glob", "read"}
    locate_mcp = {
        "search",
        "read",
        "files",
        "recall",
        "expand",
        "outline",
        "grep",
        "neighbors",
        "graph",
        "query_graph",
    }
    for i, call in enumerate(all_calls, 1):
        name = str(call.get("name") or "").lower()
        kind = str(call.get("kind") or "").lower()
        is_mcp = kind == "mcp" or bool(call.get("provider"))
        if name in {"edit", "write"} or kind in {"edit", "write"}:
            if first_edit is None:
                first_edit = i
            seen_edit = True
            continue
        is_locate = False
        if is_mcp and name in locate_mcp:
            is_locate = True
        elif (not is_mcp) and name in locate_native:
            is_locate = True
            native_locate += 1
        if not is_locate:
            continue
        if seen_edit:
            locate_post += 1
        else:
            locate_pre += 1
    return {
        "first_edit_step": first_edit,
        "pre_locate_calls": locate_pre,
        "post_locate_calls": locate_post,
        "native_locate_count": native_locate,
    }


def evaluate_development_arm(
    name: str,
    status: str,
    events: list[dict],
    usage: Any,
    diff_text: str,
    tests: Mapping[str, Any],
) -> dict[str, Any]:
    # An arm may legitimately expose more than one MCP provider (e.g.
    # graphify_grep = graphify graph tools + a grep-only Context Engine server).
    # ``raw`` is the no-MCP baseline — expected providers are empty.
    expected_providers = {
        "raw": set(),
        "graphify": {"graphify"},
        "graphify_grep": {"graphify", "context-engine"},
    }.get(name, {"context-engine"})
    expected_provider = ",".join(sorted(expected_providers)) or "(none)"
    all_calls = [
        call for event in events for call in event.get("tool_calls", [])
    ]
    mcp_calls = [
        call
        for call in all_calls
        if call.get("kind") == "mcp" or call.get("provider")
    ]
    native_calls = [call for call in all_calls if call not in mcp_calls]
    providers = sorted(
        {str(call["provider"]) for call in mcp_calls if call.get("provider")}
    )
    unexpected = [
        provider for provider in providers if provider not in expected_providers
    ]
    normalized_usage = usage_dict(usage)
    # Path-agnostic completion: the prompt is deliberately vague (no file names),
    # so we score the SHAPE of a real multi-file change rather than exact paths —
    # at least two non-test source files under packages/ plus a new test file.
    # This lets the agent discover where to wire the feature without the harness
    # dictating it.
    files = changed_files(diff_text)
    new_tests = added_test_files(diff_text)
    # The frontend-mcp repo keeps its source under src/; this repo uses packages/.
    # Read profile at call time so tests/monkeypatch can override CTX_TRIAL_PROFILE.
    profile = (os.environ.get("CTX_TRIAL_PROFILE") or "ce").strip().lower()
    src_prefix = "src/" if profile == "frontend" else "packages/"
    source_files = [
        f
        for f in files
        if f.startswith(src_prefix)
        and f.endswith(".py")
        and not f.rsplit("/", 1)[-1].startswith("test_")
    ]
    docs_touched = any(
        f.startswith("docs/") and f.endswith(".md") for f in files
    )
    # Frontend: require a multi-side change (schemas/handlers/dispatch-ish) —
    # at least 3 source files + a brand-new test file + a docs note.
    if profile == "frontend":
        implementation_present = (
            len(source_files) >= 3 and bool(new_tests) and docs_touched
        )
    else:
        implementation_present = len(source_files) >= 2 and bool(new_tests)

    task_calls = [
        call
        for call in all_calls
        if str(call.get("name") or "").lower() == "task"
        or str(call.get("kind") or "").lower() == "task"
    ]
    used_task = bool(task_calls)

    # MCP arms must actually USE their MCP at least once. The raw baseline has
    # no MCP — it "uses" the empty set as long as it didn't sneak one in.
    if not expected_providers:
        used_expected_mcp = not providers
    else:
        used_expected_mcp = bool(set(providers) & expected_providers)

    # CE arms must actually lean on the MCP for discovery — a single token
    # search while doing 100 native greps doesn't count as using CE.
    mcp_discovery_count = sum(
        1
        for n in (str(c.get("name") or "") for c in mcp_calls)
        if n
        in {
            "search",
            "read",
            "outline",
            "grep",
            "files",
            "recall",
            "expand",
            "neighbors",
            "graph",
            "query_graph",
        }
    )
    mcp_used_enough = (
        True
        if name == "raw"
        else (used_expected_mcp and mcp_discovery_count >= 5)
    )

    thrash = _thrash_metrics(all_calls)
    seal_locate = (os.environ.get("CTX_TRIAL_SEAL_LOCATE") or "").strip() in {
        "1",
        "true",
        "yes",
    }
    # Under seal, CE arms must not use native Grep/Glob/Read for locate.
    seal_ok = True
    if seal_locate and name != "raw":
        seal_ok = int(thrash.get("native_locate_count") or 0) == 0

    # ce profile gates on the repo's pytest; frontend profile scores on task
    # shape only (its deps aren't installed in the tooling venv), per the trial's
    # "did it do the assigned work" definition.
    tests_ok = True if profile == "frontend" else bool(tests.get("passed"))
    work_complete = all(
        [
            used_expected_mcp,
            mcp_used_enough,
            not unexpected,
            not used_task,  # fairness: no Task/subagent offload
            normalized_usage is not None,
            implementation_present,
            tests_ok,
            seal_ok,
        ]
    )
    quality_pass = work_complete and status == "finished"
    usage_map = normalized_usage or {}
    input_t = usage_map.get("input_tokens")
    output_t = usage_map.get("output_tokens")
    work_tokens = (
        (input_t or 0) + (output_t or 0)
        if input_t is not None and output_t is not None
        else None
    )
    return {
        "work_complete": work_complete,
        "name": name,
        "status": status,
        "expected_provider": expected_provider,
        "observed_providers": providers,
        "expected_mcp_used": used_expected_mcp,
        "mcp_used_enough": mcp_used_enough,
        "mcp_discovery_count": mcp_discovery_count,
        "used_task": used_task,
        "task_call_count": len(task_calls),
        "unexpected_mcp_providers": unexpected,
        "mcp_call_names": [
            str(call.get("name") or "") for call in mcp_calls
        ],
        "native_tool_names": [
            str(call.get("name") or "") for call in native_calls
        ],
        "native_locate_count": thrash["native_locate_count"],
        "first_edit_step": thrash["first_edit_step"],
        "pre_locate_calls": thrash["pre_locate_calls"],
        "post_locate_calls": thrash["post_locate_calls"],
        "seal_locate": seal_locate,
        "seal_ok": seal_ok,
        "implementation_present": implementation_present,
        "source_files_changed": source_files,
        "docs_touched": docs_touched,
        "new_test_files": new_tests,
        "quality_pass": quality_pass,
        "usage": normalized_usage,
        "work_tokens": work_tokens,
        "diff_size": len(diff_text),
        "tests": dict(tests),
    }


def _format_usage_cell(value: int | None) -> str:
    if value is None:
        return "unavailable"
    return str(value)


def _format_tests_cell(tests: Mapping[str, Any] | None) -> str:
    if not tests:
        return "unavailable"
    if tests.get("passed") is True:
        return "passed"
    if tests.get("passed") is False:
        return "failed"
    return str(tests.get("exit_code", "unavailable"))


def _percent_delta(ce_value: int | None, gf_value: int | None) -> str | None:
    if ce_value is None or gf_value is None or gf_value == 0:
        return None
    delta = ((ce_value - gf_value) / gf_value) * 100
    return f"{delta:+.1f}%"


def render_report(data: Mapping[str, Any]) -> str:
    arms = data.get("arms") or {}
    arm_names = tuple(data.get("arm_names") or list(arms))
    title = " vs ".join(arm_names) if arm_names else "Context Engine vs Graphify"
    lines = [
        f"# SDK Development Trial: {title}",
        "",
        "## Prompt",
        "",
        str(data.get("prompt") or SHARED_PROMPT),
        "",
        "## Configuration",
        "",
        f"- Model: {data.get('model', 'unknown')}",
        f"- SDK version: {data.get('sdk_version', 'unknown')}",
        f"- Trial profile: {data.get('trial_profile', TRIAL_PROFILE)}",
        f"- Prompt id: {data.get('prompt_id', 'unknown')}",
        f"- Source tree hash: {data.get('source_tree_hash', 'unknown')}",
        f"- Source unchanged: {data.get('source_unchanged', 'unknown')}",
    ]

    baseline_commits = data.get("baseline_commits") or {}
    workspaces = data.get("workspaces") or {}
    for arm_name in arm_names:
        lines.append(
            f"- {arm_name} baseline commit: "
            f"{baseline_commits.get(arm_name, 'unknown')}"
        )
    for arm_name in arm_names:
        lines.append(
            f"- {arm_name} workspace: {workspaces.get(arm_name, 'unknown')}"
        )
    lines.append("")

    lines += [
        "## Results",
        "",
        "| Arm | Status | Input | Output | Work (in+out) | Cache read | "
        "Total | MCP disc. | Task? | Work complete | Quality |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|---:|",
    ]

    for arm_name in arm_names:
        arm = arms.get(arm_name, {})
        usage_map = arm.get("usage") or {}
        if not isinstance(usage_map, Mapping):
            usage_map = {}
        work = arm.get("work_tokens")
        if work is None:
            inp = usage_map.get("input_tokens")
            out = usage_map.get("output_tokens")
            work = (inp or 0) + (out or 0) if inp is not None and out is not None else None
        lines.append(
            f"| {arm_name} | {arm.get('status', '')} | "
            f"{_format_usage_cell(usage_map.get('input_tokens'))} | "
            f"{_format_usage_cell(usage_map.get('output_tokens'))} | "
            f"{_format_usage_cell(work)} | "
            f"{_format_usage_cell(usage_map.get('cache_read_tokens'))} | "
            f"{_format_usage_cell(usage_map.get('total_tokens'))} | "
            f"{arm.get('mcp_discovery_count', 0)} | "
            f"{'YES' if arm.get('used_task') else 'no'} | "
            f"{arm.get('work_complete', False)} | "
            f"{arm.get('quality_pass', False)} |"
        )

    lines += [
        "",
        "`Work complete` is the task verdict: the fix is in the diff, the "
        "focused tests pass, and only the arm's own MCP was used. `Status` is "
        "the SDK run status, which can read `cancelled` when the bridge keeps "
        "the event stream open after the agent has already finished.",
        "",
        "## Locate thrash / seal",
        "",
        "| Arm | native_locate | first_edit | pre_locate | post_locate | seal | seal_ok | cross_arm |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for arm_name in arm_names:
        arm = arms.get(arm_name, {})
        contam = arm.get("cross_arm_contamination") or []
        contam_s = ",".join(str(x) for x in contam) if contam else "none"
        lines.append(
            f"| {arm_name} | {arm.get('native_locate_count', 0)} | "
            f"{arm.get('first_edit_step', '')} | "
            f"{arm.get('pre_locate_calls', '')} | "
            f"{arm.get('post_locate_calls', '')} | "
            f"{'ON' if arm.get('seal_locate') else 'off'} | "
            f"{arm.get('seal_ok', True)} | "
            f"{contam_s} |"
        )
    if data.get("arm_isolation"):
        lines += [
            "",
            f"Arm isolation mode: `{data.get('arm_isolation')}` "
            "(finished arm workspaces/sidecars are vaulted before the next arm).",
        ]

    lines += ["", "## Providers", ""]
    for arm_name in arm_names:
        arm = arms.get(arm_name, {})
        expected = arm.get("expected_provider", "unknown")
        observed = arm.get("observed_providers") or []
        observed_text = ", ".join(observed) if observed else "none"
        lines.append(
            f"- {arm_name}: expected `{expected}`, observed `{observed_text}`"
        )

    warnings: list[str] = []
    for arm_name in arm_names:
        arm = arms.get(arm_name, {})
        status = arm.get("status")
        if status != "finished":
            status_label = status if status not in (None, "") else "missing"
            warnings.append(
                f"{arm_name} run incomplete (status={status_label})"
            )
        if arm.get("usage") is None:
            warnings.append(
                f"{arm_name} authoritative SDK usage unavailable"
            )
        elif arm.get("usage_source") == "run_property":
            warnings.append(
                f"{arm_name} usage recovered from the streamed turn sum after "
                "cancel, not from a terminal RunResult"
            )
        for warning in arm.get("warnings") or []:
            warnings.append(f"{arm_name}: {warning}")

    if warnings:
        lines += ["", "## Warnings", ""]
        lines.extend(f"- {warning}" for warning in warnings)

    # Deltas of the first arm relative to the second (arm[0] vs arm[1]).
    if len(arm_names) >= 2:
        a_name, b_name = arm_names[0], arm_names[1]
        a_usage = (arms.get(a_name) or {}).get("usage") or {}
        b_usage = (arms.get(b_name) or {}).get("usage") or {}
        if isinstance(a_usage, Mapping) and isinstance(b_usage, Mapping):
            deltas = [
                ("Input", _percent_delta(a_usage.get("input_tokens"), b_usage.get("input_tokens"))),
                ("Output", _percent_delta(a_usage.get("output_tokens"), b_usage.get("output_tokens"))),
                ("Total", _percent_delta(a_usage.get("total_tokens"), b_usage.get("total_tokens"))),
            ]
            rendered = [f"{label}: {value}" for label, value in deltas if value is not None]
            if rendered:
                lines += ["", f"## {a_name} deltas vs {b_name}", ""]
                lines.extend(f"- {line}" for line in rendered)

    lines.append("")
    return "\n".join(lines)


def _source_python(source: Path) -> Path:
    if os.name == "nt":
        return source / ".venv" / "Scripts" / "python.exe"
    return source / ".venv" / "bin" / "python"


def index_workspace(workspace: Path, python: Path, root: Path) -> Path:
    env = {
        **os.environ,
        "PYTHONPATH": str(root / "packages"),
        "PYTHONUTF8": "1",
    }
    subprocess.run(
        [
            str(python),
            "-m",
            "pipeline",
            "index",
            str(workspace),
            "--fast",
            "--force",
        ],
        cwd=root,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    from pipeline.store import PipelineStore

    graph = PipelineStore(workspace).base / "graph.json"
    if not graph.is_file():
        raise RuntimeError(f"Graphify graph missing after index: {graph}")
    return graph


def index_cbm_workspace(workspace: Path) -> dict[str, object]:
    """Index the same workspace into stock CBM (required for cbm_ce arm)."""
    from hybrid_cbm.proxy import ensure_indexed, make_proxy, resolve_project_name

    proxy = make_proxy()
    if not proxy.available():
        raise RuntimeError(
            "CBM binary not found (install codebase-memory-mcp or set CTX_CBM_BIN)"
        )
    result = ensure_indexed(proxy, workspace)
    if not result.get("ok"):
        raise RuntimeError(f"CBM index failed: {result}")
    project = resolve_project_name(proxy, workspace)
    return {"ok": True, "project": project, "result": result}


REGRESSION_TEST_MODULE = "tests/test_mcp_locate.py"
# Environment-dependent live retrieval-quality check: it asserts on daemon
# results for a freshly copied workspace and fails for reasons unrelated to the
# feature, so it must not decide the arm's quality.
UNRELATED_LIVE_TEST = f"{REGRESSION_TEST_MODULE}::test_live_map_focus_workspace_flow"


def build_test_selection(extra_tests: list[str] | None = None) -> list[str]:
    """Regression module (minus the flaky live flow) + any agent-added tests.

    The regression module always runs (guards the existing MCP surface). The
    agent's new tests/test_*.py files — discovered from the diff — are appended
    so the feature's own coverage is exercised and must pass too.
    """
    selection = [REGRESSION_TEST_MODULE]
    for t in extra_tests or []:
        if t and t != REGRESSION_TEST_MODULE:
            selection.append(t)
    selection += ["--deselect", UNRELATED_LIVE_TEST]
    return selection


def run_post_tests(
    workspace: Path,
    python: Path,
    root: Path,
    *,
    arm: str = "context_engine",
    extra_tests: list[str] | None = None,
) -> dict[str, Any]:
    del root  # Kept in the public interface for source-root provenance.
    # frontend profile: the target repo's heavy deps (mcp, browser-use, CRG)
    # aren't installed in this tooling venv, so we can't run its suite. Scoring is
    # by task shape (see evaluate_development_arm), so return a neutral skip.
    if TRIAL_PROFILE == "frontend":
        return {
            "skipped": True,
            "passed": None,
            "exit_code": None,
            "reason": "frontend profile: target-repo deps absent; scored on task shape",
        }
    # Alternate --source trees (fixtures / other repos) often lack CE regression
    # modules; score those runs on MCP probe + task shape instead.
    if not (workspace / REGRESSION_TEST_MODULE).is_file():
        return {
            "skipped": True,
            "passed": None,
            "exit_code": None,
            "reason": f"workspace missing {REGRESSION_TEST_MODULE}; scored on task shape",
        }
    # Only the Context Engine arm needs the repo-scoped daemon; repointing it
    # for graphify would evict the other arm's engine as a scoring side effect.
    if arm == "context_engine":
        smoke.ensure_engine_repo(workspace)
    env = {
        **os.environ,
        "PYTHONPATH": str(workspace / "packages"),
        "PYTHONUTF8": "1",
    }
    started = time.perf_counter()
    selection = build_test_selection(extra_tests)
    completed = subprocess.run(
        [str(python), "-m", "pytest", *selection, "-q"],
        cwd=workspace,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    return {
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "passed": completed.returncode == 0,
        "selection": selection,
    }


async def _append_conversation_tools(
    run: Any,
    events: list[dict],
) -> tuple[str | None, str]:
    """Parse conversation tools without affecting RunResult.usage authority."""
    try:
        if not run.supports("conversation"):
            return None, ""
        # A wedged bridge can hang this unary call; stream events already carry
        # the MCP attribution, so bound it rather than let it stall the arm.
        raw = await asyncio.wait_for(
            run.conversation_json(), timeout=CONVERSATION_GRACE_S
        )
        conversation = json.loads(raw) if raw else []
        events.append(smoke.extract_conversation_tools(conversation))
        return str(raw or ""), ""
    except Exception as exc:  # streamed/terminal evidence remains usable
        return None, f"conversation capture failed: {type(exc).__name__}: {exc}"


def run_usage_snapshot(run: Any) -> dict[str, int | None] | None:
    """Read the SDK's running turn-usage sum without consuming the stream.

    ``Run.usage`` accumulates every ``SDKUsageMessage`` as it is handled, so it
    stays valid after a cancel, unlike ``RunResult.usage`` which requires a
    successful ``wait()``.
    """
    try:
        return usage_dict(getattr(run, "usage", None))
    except Exception:
        return None


TERMINAL_RUN_STATUSES = frozenset(
    {"finished", "error", "cancelled", "expired"}
)


@dataclass
class Observation:
    events: list[dict]
    terminal: Any | None
    error: str
    conversation_json: str | None
    usage: dict[str, int | None] | None
    usage_source: str
    stream_status: str = ""
    status_history: tuple[str, ...] = ()


async def _cancel_run(run: Any) -> str:
    try:
        await run.cancel()
        return ""
    except Exception as exc:
        return f"cancel failed: {type(exc).__name__}: {exc}"


async def observe_run(
    run: Any,
    timeout_s: float,
    *,
    idle_timeout_s: float = IDLE_TIMEOUT_S,
    heartbeat_s: float = HEARTBEAT_S,
    on_heartbeat: Any = None,
) -> Observation:
    """Observe a run to authoritative completion without idle-cancelling it.

    This bridge keeps the send stream open after the agent finishes, so the
    stream's status never flips to a terminal value and stream exhaustion never
    arrives. The reliable completion signal is the ``WaitLiveRun`` RPC
    (``run.client.wait_live_run``), which resolves on real completion and
    carries the authoritative ``RunResult``. We therefore drain the stream only
    for tool/text observation and treat the RPC as the finish line. The hard
    ceiling still cancels a genuinely stuck run; idle silence alone does not
    (a working agent can think for minutes) unless no RPC signal is available
    (test doubles), where the legacy idle/ceiling watchdog is preserved.
    """
    events: list[dict] = []
    started = time.monotonic()
    state: dict[str, Any] = {
        "last_event": started,
        "last_tool": "",
        "usage": None,
    }
    cancel_error = ""
    conversation_raw: str | None = None
    conversation_error = ""
    stop_reason = ""

    status_history: list[str] = []

    def _note_status() -> str:
        status = str(getattr(run, "status", "") or "").lower()
        if status and (not status_history or status_history[-1] != status):
            status_history.append(status)
        return status

    async def _drain() -> None:
        async for message in run.messages():
            event = smoke.normalize_message(message)
            events.append(event)
            state["last_event"] = time.monotonic()
            for call in event.get("tool_calls") or []:
                name = str(call.get("name") or "")
                if name:
                    state["last_tool"] = name
            snapshot = run_usage_snapshot(run)
            if snapshot is not None:
                state["usage"] = snapshot
            if _note_status() in TERMINAL_RUN_STATUSES:
                state["terminal_status"] = True
                return

    # Authoritative terminal signal (independent of the observation stream).
    # WaitLiveRun blocks server-side while the run is in progress, which exceeds
    # the bridge read timeout on long runs. So poll the cheap GetRun snapshot for
    # status and only call WaitLiveRun once the run is already terminal, where it
    # returns immediately with the authoritative RunResult (usage, result).
    waiter: asyncio.Task[Any] | None = None
    run_client = getattr(run, "client", None)
    run_id = str(getattr(run, "id", "") or "")
    _has_get = run_client is not None and hasattr(run_client, "get_run")
    _has_wait = run_client is not None and hasattr(run_client, "wait_live_run")

    async def _await_terminal() -> Any:
        while True:
            if _has_get:
                snap = None
                try:
                    snap = await run_client.get_run(run_id)
                except Exception:  # noqa: BLE001 - transient RPC hiccup; keep polling
                    snap = None
                st = (
                    str(getattr(snap, "status", "") or "").lower()
                    if snap is not None
                    else ""
                )
                if snap is not None and st in TERMINAL_RUN_STATUSES:
                    if _has_wait:
                        try:
                            return await run_client.wait_live_run(run_id)
                        except Exception:  # noqa: BLE001 - fall back to snapshot
                            return snap
                    return snap
                await asyncio.sleep(TERMINAL_POLL_S)
            else:
                # No snapshot poll available (test doubles / short runs): a single
                # blocking wait is fine because these resolve quickly.
                return await run_client.wait_live_run(run_id)

    if run_id and (_has_get or _has_wait):
        waiter = asyncio.create_task(_await_terminal())

    drain_task = asyncio.create_task(_drain())
    poll_s = max(1.0, min(5.0, heartbeat_s))
    last_heartbeat = started
    finished_via_waiter = False

    while not drain_task.done():
        await asyncio.wait({drain_task}, timeout=poll_s)
        if drain_task.done():
            break
        now = time.monotonic()
        if on_heartbeat is not None and now - last_heartbeat >= heartbeat_s:
            last_heartbeat = now
            usage_snapshot = state.get("usage") or {}
            on_heartbeat(
                {
                    "elapsed_s": round(now - started, 1),
                    "events": len(events),
                    "last_tool": state.get("last_tool") or "",
                    "idle_s": round(now - float(state["last_event"]), 1),
                    "total_tokens": usage_snapshot.get("total_tokens"),
                }
            )
        # Authoritative completion: stop observing, do NOT cancel the run.
        if waiter is not None and waiter.done():
            finished_via_waiter = True
            break
        idle_s = now - float(state["last_event"])
        over_ceiling = now - started >= timeout_s
        # The waiter (checked above) is the clean authoritative finish. But local
        # runs often never flip terminal, so a long stream idle finalizes the run
        # as "agent done" rather than waiting out the ceiling. Waiter is still
        # preferred: it is checked first, so a run that does finalize is never
        # cancelled.
        idle_trip = idle_s >= idle_timeout_s
        if not (over_ceiling or idle_trip):
            continue
        stop_reason = (
            f"run exceeded {timeout_s:g}s ceiling"
            if over_ceiling
            else f"run idle for {idle_s:.0f}s (limit {idle_timeout_s:g}s)"
        )
        # Grab conversation evidence before cancelling; cancellation can race
        # the availability of GetRunConversation data.
        conversation_raw, conversation_error = await _append_conversation_tools(
            run, events
        )
        cancel_error = await _cancel_run(run)
        break

    # Stop reading the (often still-open) stream. On a clean finish the stream
    # stays open, so a short flush then cancel is expected, not an error.
    drain_grace = 5.0 if finished_via_waiter else CANCEL_DRAIN_GRACE_S
    try:
        await asyncio.wait_for(drain_task, timeout=drain_grace)
    except asyncio.TimeoutError:
        drain_task.cancel()
        if not finished_via_waiter:
            stop_reason = stop_reason or "stream did not close after cancel"
    except Exception as exc:
        stop_reason = stop_reason or f"{type(exc).__name__}: {exc}"

    snapshot = run_usage_snapshot(run)
    if snapshot is not None:
        state["usage"] = snapshot

    stream_status = _note_status()
    terminal = None
    wait_error = ""
    if waiter is not None:
        try:
            terminal = await asyncio.wait_for(waiter, timeout=WAIT_GRACE_S)
        except asyncio.TimeoutError:
            wait_error = f"wait_live_run did not return within {WAIT_GRACE_S:g}s"
            waiter.cancel()
        except Exception as exc:
            wait_error = f"wait_live_run failed: {type(exc).__name__}: {exc}"
    else:
        # No RPC signal (test doubles / snapshot runs): fall back to wait(),
        # which drains any remaining buffered events and returns the result.
        try:
            terminal = await asyncio.wait_for(run.wait(), timeout=WAIT_GRACE_S)
        except asyncio.TimeoutError:
            wait_error = f"run.wait did not return within {WAIT_GRACE_S:g}s"
        except Exception as exc:
            wait_error = f"run.wait failed: {type(exc).__name__}: {exc}"
    stream_status = _note_status() or stream_status

    if conversation_raw is None and not conversation_error:
        conversation_raw, conversation_error = await _append_conversation_tools(
            run, events
        )

    terminal_usage = usage_dict(getattr(terminal, "usage", None))
    stream_usage = state.get("usage")
    if terminal_usage is not None:
        usage: dict[str, int | None] | None = terminal_usage
        usage_source = "run_result"
    elif stream_usage is not None:
        usage = stream_usage
        usage_source = "run_property"
    else:
        usage = None
        usage_source = "none"

    error = "; ".join(
        part
        for part in (stop_reason, cancel_error, wait_error, conversation_error)
        if part
    )
    return Observation(
        events=events,
        terminal=terminal,
        error=error,
        conversation_json=conversation_raw,
        usage=usage,
        usage_source=usage_source,
        stream_status=stream_status,
        status_history=tuple(status_history),
    )


def _terminal_status(
    terminal: Any | None,
    error: str,
    stream_status: str = "",
) -> str:
    if terminal is not None:
        raw = getattr(terminal, "status", "error")
        return str(getattr(raw, "value", raw)).lower()
    if stream_status in TERMINAL_RUN_STATUSES:
        return stream_status
    lowered = error.lower()
    if "idle for" in lowered or "ceiling" in lowered or "timed out" in lowered:
        return "timeout"
    return "error"


def _event_text(events: list[dict]) -> str:
    return "".join(str(event.get("text") or "") for event in events)


async def run_arm(
    client: Any,
    config: Any,
    workspace: Path,
    model: str,
    timeout_s: float,
    *,
    source: Path | None = None,
    python: Path | None = None,
) -> dict[str, Any]:
    from cursor_sdk import AgentOptions, LocalAgentOptions, SendOptions

    source = source or ROOT
    python = python or _source_python(source)
    # Most arms expose exactly one MCP provider. graphify_grep pairs two;
    # raw is the no-MCP baseline (zero providers).
    _multi_provider_arms = {"graphify_grep"}
    _no_mcp_arms = {"raw"}
    if config.name in _no_mcp_arms:
        if config.mcp_servers:
            raise ValueError(
                f"{config.name} must expose zero MCP providers, "
                f"got {sorted(config.mcp_servers)}"
            )
    elif config.name in _multi_provider_arms:
        if not config.mcp_servers:
            raise ValueError(f"{config.name} must expose at least one MCP provider")
    elif len(config.mcp_servers) != 1:
        raise ValueError(
            f"{config.name} must expose exactly one MCP provider, "
            f"got {sorted(config.mcp_servers)}"
        )

    events: list[dict] = []
    terminal = None
    error = ""
    agent_id = ""
    run_id = ""
    conversation_raw: str | None = None
    observed_usage: dict[str, int | None] | None = None
    usage_source = "none"
    stream_status = ""
    status_history: list[str] = []
    started = time.perf_counter()

    def _heartbeat(info: Mapping[str, Any]) -> None:
        print(
            f"[{config.name}] {info['elapsed_s']:.0f}s "
            f"events={info['events']} idle={info['idle_s']:.0f}s "
            f"last_tool={info['last_tool'] or '-'} "
            f"tokens={info['total_tokens'] if info['total_tokens'] is not None else '-'}",
            flush=True,
        )

    try:
        options = AgentOptions(
            model=model,
            api_key=os.environ.get("CURSOR_API_KEY", ""),
            local=LocalAgentOptions(
                cwd=workspace,
                setting_sources=config.setting_sources,
            ),
            mcp_servers=config.mcp_servers or None,
            # Keep both arms single-agent — Task/explore made prior raw runs unfair.
            disallowed_tools=list(DISALLOWED_TOOLS),
        )
        create_agent = getattr(client, "create_agent", None)
        if create_agent is None:
            create_agent = client.agents.create
        async with await create_agent(options) as agent:
            agent_id = str(getattr(agent, "agent_id", ""))
            run = await agent.send(
                SHARED_PROMPT,
                SendOptions(mcp_servers=config.mcp_servers),
            )
            run_id = str(getattr(run, "id", ""))
            print(
                f"[{config.name}] run started run_id={run_id or 'unknown'}",
                flush=True,
            )
            observation = await observe_run(
                run,
                timeout_s,
                on_heartbeat=_heartbeat,
            )
            events = observation.events
            terminal = observation.terminal
            error = observation.error
            conversation_raw = observation.conversation_json
            observed_usage = observation.usage
            usage_source = observation.usage_source
            stream_status = observation.stream_status
            status_history = list(observation.status_history)
    except Exception as exc:  # preserve artifacts even when the SDK boundary fails
        error = f"{type(exc).__name__}: {exc}"
        conversation_raw = None

    status = _terminal_status(terminal, error, stream_status)
    final_text = str(getattr(terminal, "result", "") or "")
    if not final_text:
        final_text = _event_text(events)
    diff_text = git_diff(workspace)
    tests = run_post_tests(
        workspace,
        python,
        source,
        arm=config.name,
        extra_tests=added_test_files(diff_text),
    )
    wall_ms = round((time.perf_counter() - started) * 1000, 1)
    outcome = evaluate_development_arm(
        config.name,
        status,
        events,
        observed_usage,
        diff_text,
        tests,
    )
    outcome.update(
        {
            "agent_id": agent_id,
            "run_id": run_id,
            "final_text": final_text,
            "error": error,
            "wall_ms": wall_ms,
            "usage_source": usage_source,
            "stream_status": stream_status,
            "status_history": status_history,
            "events": events,
            "conversation_json": conversation_raw,
            "tool_calls": [
                call
                for event in events
                for call in event.get("tool_calls", [])
            ],
            "diff": diff_text,
            "tests": tests,
            "setting_sources": list(config.setting_sources),
            "mcp_servers": sorted(config.mcp_servers),
            "workspace": str(workspace),
        }
    )
    return outcome


def _finalize_arm_outcome(
    workspace: Path,
    outcome: dict[str, Any],
) -> dict[str, Any]:
    diff_text = git_diff(workspace)
    reevaluated = evaluate_development_arm(
        str(outcome.get("name") or ""),
        str(outcome.get("status") or ""),
        list(outcome.get("events") or []),
        outcome.get("usage"),
        diff_text,
        outcome.get("tests") or {},
    )
    outcome.update(reevaluated)
    outcome["diff"] = diff_text
    return outcome


def _clear_context_state(workspace: Path) -> None:
    from pipeline.session_store import clear_store
    from pipeline.work_session import clear_session

    clear_session(workspace)
    clear_store(workspace)


def _sdk_version() -> str:
    try:
        return importlib.metadata.version("cursor-sdk")
    except importlib.metadata.PackageNotFoundError:
        return "unavailable"


def _test_log(tests: Mapping[str, Any]) -> str:
    return (
        f"exit_code: {tests.get('exit_code')}\n"
        f"passed: {tests.get('passed')}\n"
        f"elapsed_ms: {tests.get('elapsed_ms')}\n"
        "\n--- stdout ---\n"
        f"{tests.get('stdout') or ''}"
        "\n--- stderr ---\n"
        f"{tests.get('stderr') or ''}"
    )


ARM_NAMES = ("context_engine", "graphify")
# Arms the harness knows how to build/stage. ``ce_*`` are Context Engine tool
# surfaces (rich = many specialized tools, search = one semantic tool) so two CE
# designs can run head to head via --arms ce_rich,ce_search.
KNOWN_ARMS = (
    "context_engine",
    "graphify",
    "graphify_grep",
    "ce_read",
    "ce_nav",
    "ce_graph",
    "ce_rich",
    "ce_search",
    "cbm_ce",
    "raw",
)


def arm_sidecar_names(name: str) -> tuple[str, ...]:
    """Files written next to ``{name}_workspace`` after an arm finishes."""
    return (
        f"{name}.diff",
        f"{name}-tests.log",
        f"{name}-conversation.json",
        f"{name}-arm.json",
    )


def trial_vault_dir(output: Path) -> Path:
    """Private folder outside the shared run dir (agents must not see siblings).

    Uses a random directory name (not the run timestamp) so a later arm cannot
    guess ``…/ce_dev_trial_vault/<same-ts>`` and reopen the finished tree.
    """
    import uuid

    return Path(tempfile.gettempdir()) / f"ce_private_{uuid.uuid4().hex}"


def _move_path(src: Path, dest: Path) -> None:
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))


def quarantine_arm_artifacts(output: Path, vault: Path, name: str) -> None:
    """Hide a finished arm's workspace + sidecars so the next arm cannot copy them.

    Agents run with cwd ``{output}/{name}_workspace`` and can walk up to ``output``.
    Moving finished trees into ``vault`` (a separate temp tree) removes the cheat
    sheet before the next arm starts.
    """
    vault.mkdir(parents=True, exist_ok=True)
    workspace = output / f"{name}_workspace"
    if workspace.exists():
        last_exc: OSError | None = None
        for attempt in range(1, 6):
            try:
                _move_path(workspace, vault / f"{name}_workspace")
                last_exc = None
                break
            except OSError as exc:
                last_exc = exc
                time.sleep(min(2.0 * attempt, 8.0))
        if last_exc is not None:
            # Windows often keeps .git / MCP / indexer handles open briefly after
            # the arm ends — fail soft so the next arm still runs, but rename in
            # place so sibling peeks cannot use the obvious {name}_workspace path.
            hidden = output / f".quarantined_{name}_workspace"
            try:
                if hidden.exists():
                    shutil.rmtree(hidden, ignore_errors=True)
                workspace.rename(hidden)
                _step(
                    f"quarantine WARN: move failed ({last_exc}); "
                    f"renamed to {hidden.name}"
                )
            except OSError as exc2:
                _step(
                    f"quarantine WARN: could not hide {workspace.name} "
                    f"({last_exc}; rename={exc2}); leaving in place"
                )
    for sid in arm_sidecar_names(name):
        src = output / sid
        if not src.exists():
            continue
        last_exc = None
        for attempt in range(1, 4):
            try:
                _move_path(src, vault / sid)
                last_exc = None
                break
            except OSError as exc:
                last_exc = exc
                time.sleep(1.0 * attempt)
        if last_exc is not None:
            alt = output / f".quarantined_{sid}"
            try:
                if alt.exists():
                    alt.unlink()
                src.rename(alt)
                _step(f"quarantine WARN: moved {sid} aside as {alt.name}")
            except OSError as exc2:
                _step(f"quarantine WARN: could not hide {sid} ({last_exc}; {exc2})")


def restore_quarantined_arm_artifacts(vault: Path, output: Path) -> None:
    """Move quarantined artifacts back into the run folder for REPORT / humans."""
    if not vault.exists():
        return
    output.mkdir(parents=True, exist_ok=True)
    for item in list(vault.iterdir()):
        _move_path(item, output / item.name)
    try:
        vault.rmdir()
    except OSError:
        pass


def detect_cross_arm_contamination(
    *,
    text: str | None,
    arm_name: str,
    arm_names: tuple[str, ...] | list[str],
) -> list[str]:
    """Return sibling markers found in conversation/shell text (copy / peek)."""
    if not text:
        return []
    hits: list[str] = []
    for other in arm_names:
        if other == arm_name:
            continue
        for marker in (
            f"{other}_workspace",
            f"{other}.diff",
            f"{other}-conversation.json",
            f"{other}-arm.json",
            f"{other}-tests.log",
        ):
            if marker in text and marker not in hits:
                hits.append(marker)
    return hits


def _step(message: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


async def run_trial(
    source: Path,
    output: Path,
    model: str,
    timeout_s: float,
    *,
    arm_names: tuple[str, ...] = ARM_NAMES,
) -> dict[str, Any]:
    from cursor_sdk import AsyncClient

    source = source.resolve()
    output = output.resolve()
    vault = trial_vault_dir(output)
    _step(f"hashing source tree {source}")
    source_hash_before = source_tree_hash(source)
    output.mkdir(parents=True, exist_ok=True)
    _step(
        f"arm isolation ON — finished arms move to private vault "
        f"(not under the run folder) before the next arm starts"
    )

    # Tooling (pipeline/graphify/venv) always lives in THIS repo, even when the
    # copied/indexed source is a different repo (frontend profile). Only the
    # workspace being indexed + given to the agent changes.
    tooling_root = ROOT
    python = _source_python(tooling_root)

    # Lazy workspaces: create each arm only when it starts, then quarantine it
    # before the next arm can see sibling trees / diffs under ``output``.
    workspaces: dict[str, Path] = {}
    baseline_commits: dict[str, str] = {}
    baseline_hashes: dict[str, str] = {}
    arms: dict[str, dict[str, Any]] = {}
    reference_baseline_hash: str | None = None

    for name in arm_names:
        workspace = output / f"{name}_workspace"
        workspaces[name] = workspace
        _step(f"copying workspace for {name}")
        baseline_commits[name] = copy_workspace(source, workspace)
        baseline_hashes[name] = source_tree_hash(workspace)
        if reference_baseline_hash is None:
            reference_baseline_hash = baseline_hashes[name]
        elif baseline_hashes[name] != reference_baseline_hash:
            raise RuntimeError(
                f"copied baseline tree hashes differ: {baseline_hashes}"
            )

        if name == "raw":
            graph = workspace / ".context-engine" / "graph.json"
            _step(f"skipping index for {name} (no MCP)")
        else:
            _step(f"indexing workspace for {name}")
            graph = index_workspace(workspace, python, tooling_root)
            if name == "cbm_ce":
                _step(f"indexing CBM graph for {name}")
                index_cbm_workspace(workspace)
        config = smoke.build_configs(
            tooling_root,
            workspace,
            python,
            graph,
        )[name]

        _step(f"starting arm {name} (ceiling {timeout_s:g}s)")
        with smoke.stage_retrieval_rule(workspace, name):
            # Prove the rule actually landed before spending on the agent.
            rule_path = workspace / ".cursor" / "rules" / "context-agent.mdc"
            if name == "raw":
                rule_path = workspace / ".cursor" / "rules" / "context-agent.mdc"
                expected_snip = "no MCP servers"
            elif name in {"graphify"}:
                rule_path = workspace / ".cursor" / "rules" / "graphify-agent.mdc"
                expected_snip = "query_graph"
            elif name == "cbm_ce":
                expected_snip = "cbm-ce = ONLY code locate"
            elif smoke.arm_surface(name) == "nav":
                expected_snip = "ONLY code locate"
            else:
                expected_snip = "Context Engine"
            if not rule_path.is_file() or expected_snip not in rule_path.read_text(
                encoding="utf-8"
            ):
                raise RuntimeError(
                    f"staged rule missing/wrong for {name}: {rule_path}"
                )
            _step(f"{name}: staged rule OK ({rule_path.name})")
            # Only CE / hybrid arms need the engine daemon; graphify/raw skip it.
            if name not in {"graphify", "raw"}:
                _clear_context_state(workspace)
                smoke.ensure_engine_repo(workspace)
            async with await AsyncClient.launch_bridge(
                workspace=workspace,
                timeout=30,
            ) as client:
                arms[name] = await run_arm(
                    client,
                    config,
                    workspace,
                    model,
                    timeout_s,
                    source=tooling_root,
                    python=python,
                )
        _finalize_arm_outcome(workspace, arms[name])

        conversation_raw = arms[name].get("conversation_json")
        contam_blob = "\n".join(
            [
                str(conversation_raw or ""),
                json.dumps(arms[name].get("events") or [], default=str),
                json.dumps(arms[name].get("tool_calls") or [], default=str),
            ]
        )
        contam = detect_cross_arm_contamination(
            text=contam_blob,
            arm_name=name,
            arm_names=arm_names,
        )
        arms[name]["cross_arm_contamination"] = contam
        if contam:
            arms[name]["work_complete"] = False
            arms[name]["quality_pass"] = False
            _step(
                f"arm {name} FAILED isolation — peeked at sibling artifacts: "
                f"{contam}"
            )

        (output / f"{name}.diff").write_text(
            str(arms[name].get("diff") or ""),
            encoding="utf-8",
        )
        (output / f"{name}-tests.log").write_text(
            _test_log(arms[name].get("tests") or {}),
            encoding="utf-8",
        )
        if conversation_raw:
            (output / f"{name}-conversation.json").write_text(
                str(conversation_raw),
                encoding="utf-8",
            )
        # Persist per arm so a later failure cannot discard a finished arm.
        (output / f"{name}-arm.json").write_text(
            json.dumps(arms[name], indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        arm_usage = arms[name].get("usage") or {}
        _step(
            f"arm {name} done status={arms[name].get('status')} "
            f"usage_source={arms[name].get('usage_source')} "
            f"input={arm_usage.get('input_tokens')} "
            f"output={arm_usage.get('output_tokens')}"
        )
        _step(f"quarantining {name} artifacts into vault (hide from next arm)")
        quarantine_arm_artifacts(output, vault, name)

    _step("restoring quarantined artifacts into run folder for REPORT")
    restore_quarantined_arm_artifacts(vault, output)

    source_hash_after = source_tree_hash(source)
    data: dict[str, Any] = {
        "prompt": SHARED_PROMPT,
        "prompt_id": (
            (os.environ.get("CTX_FRONTEND_PROMPT") or "thrash")
            if TRIAL_PROFILE == "frontend"
            else "ce"
        ),
        "trial_profile": TRIAL_PROFILE,
        "model": model,
        "sdk_version": _sdk_version(),
        "source_tree_hash": source_hash_before,
        "source_tree_hash_before": source_hash_before,
        "source_tree_hash_after": source_hash_after,
        "source_unchanged": source_hash_before == source_hash_after,
        "baseline_commits": baseline_commits,
        "baseline_tree_hashes": baseline_hashes,
        "arm_isolation": "vault_quarantine",
        "workspaces": {
            name: str(workspace) for name, workspace in workspaces.items()
        },
        "arm_names": list(arm_names),
        "arms": arms,
    }
    (output / "results.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (output / "REPORT.md").write_text(
        render_report(data),
        encoding="utf-8",
    )
    return data


def _default_output() -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    # NOT under ROOT/out/...: graphify's collect_files returns [] when ANY part of
    # the scanned root is a noise dir ("out", "dist", "build", ...). A workspace
    # under out/experiments/ therefore indexes ZERO files, leaving the Context
    # Engine arm semantically blind (it silently falls back to grep). Placing the
    # workspaces in the system temp dir keeps every path component non-noise so
    # the index is actually built. See docs/sdk-dev-trial-runbook.md §3.
    return Path(tempfile.gettempdir()) / "ce_iso_trial" / timestamp


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--model", default="composer-2.5")
    # Development tasks routinely exceed 20 minutes of agent work per arm.
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument(
        "--arms",
        default=",".join(ARM_NAMES),
        help="comma separated arms to run (for single-arm shakedowns)",
    )
    parser.add_argument(
        "--prompt-id",
        default="",
        help="frontend prompt variant: thrash|degraded|consistency|combo "
        "(sets CTX_FRONTEND_PROMPT; ignored unless CTX_TRIAL_PROFILE=frontend)",
    )
    parser.add_argument(
        "--surface",
        default="",
        help="force CE locate surface for ce_read/ce_nav/context_engine "
        "(e.g. nav → CTX_MCP_SURFACE=nav)",
    )
    parser.add_argument(
        "--seal-locate",
        action="store_true",
        help="fail CE arms that use native Grep/Glob/Read (sealed locate trial)",
    )
    args = parser.parse_args()

    if args.prompt_id:
        pid = str(args.prompt_id).strip().lower()
        if pid not in FRONTEND_PROMPTS:
            print(
                f"ERROR: --prompt-id must be one of {sorted(FRONTEND_PROMPTS)}",
                file=sys.stderr,
                flush=True,
            )
            return 2
        os.environ["CTX_FRONTEND_PROMPT"] = pid

    surface = str(args.surface or "").strip().lower()
    if surface:
        if surface not in {"read", "nav", "graph", "rich", "search", "grep"}:
            print(
                "ERROR: --surface must be one of read|nav|graph|rich|search|grep",
                file=sys.stderr,
                flush=True,
            )
            return 2
        os.environ["CTX_MCP_SURFACE"] = surface
        os.environ["CTX_TRIAL_FORCE_SURFACE"] = surface
        _step(f"forced CE surface={surface}")

    if args.seal_locate:
        os.environ["CTX_TRIAL_SEAL_LOCATE"] = "1"
        _step("seal-locate ON (native Grep/Glob/Read fail CE arms)")

    global SHARED_PROMPT
    SHARED_PROMPT = resolve_shared_prompt()
    _step(
        f"prompt profile={TRIAL_PROFILE} "
        f"id={(os.environ.get('CTX_FRONTEND_PROMPT') or 'ce')} "
        f"chars={len(SHARED_PROMPT)}"
    )

    arm_names = tuple(
        name.strip() for name in str(args.arms).split(",") if name.strip()
    )
    unknown = [name for name in arm_names if name not in KNOWN_ARMS]
    if not arm_names or unknown:
        print(
            f"ERROR: --arms must be a subset of {list(KNOWN_ARMS)}",
            file=sys.stderr,
            flush=True,
        )
        return 2

    api_key = smoke.load_cursor_api_key(ROOT)
    if not api_key:
        print(
            "ERROR: CURSOR_API_KEY/cursor_api_key is not configured",
            file=sys.stderr,
            flush=True,
        )
        return 2
    os.environ["CURSOR_API_KEY"] = api_key
    output = (args.output or _default_output()).resolve()
    data = asyncio.run(
        run_trial(
            args.source.resolve(),
            output,
            args.model,
            args.timeout,
            arm_names=arm_names,
        )
    )
    paths = [output / "results.json", output / "REPORT.md"]
    for name in arm_names:
        paths.append(output / f"{name}.diff")
        paths.append(output / f"{name}-tests.log")
        paths.append(output / f"{name}-arm.json")
    for path in paths:
        if path.exists():
            print(f"wrote {path}", flush=True)
    return 0 if all(
        bool(arm.get("work_complete")) for arm in data["arms"].values()
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())

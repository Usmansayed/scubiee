#!/usr/bin/env python3
"""One real development-task A/B: with Scubiee vs without (Kiro auto).

Isolated snapshots (git init per arm) so edits cannot collide.
Outcome-focused prompt — no file/function spoilers.
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
BASE = ROOT / "out" / "kiro_ab_dev"

# Exclude heavy / volatile trees when snapshotting the dirty working tree.
_EXCLUDE_DIRS = {
    ".git",
    ".scubiee",
    "out",
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
        "out_stem": "2026-09-05-kiro-mcp-ab-dev",
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
        "out_stem": "2026-09-05-kiro-mcp-ab-dev2-engine",
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
        "out_stem": "2026-09-05-kiro-mcp-ab-dev3-session",
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
}

# Back-compat alias used until main() selects a task.
DEV_PROMPT = TASKS["weak_start"]["prompt"]
ACTIVE_TASK_ID = "weak_start"
ACTIVE_TEST_KEYWORDS = TASKS["weak_start"]["test_keywords"]
ACTIVE_TEST_FILES: tuple[str, ...] = tuple(TASKS["weak_start"].get("test_files") or ())

SHARED_SYSTEM = """You are a coding agent doing a real development task.

Rules:
- Implement the requested behavior with tests.
- Prefer small, correct changes over large refactors.
- Do not commit or push.
- Do not modify files outside this workspace root.
- When done, summarize what changed and which tests you ran.
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
You HAVE the scubiee MCP server. GATE locate rules are MANDATORY (also in AGENTS.md + .kiro/steering/scubiee.md).

TRACE / PACK FIRST
- pack_context is the tracer/heatmap step (call/data slice + hot bodies). map alone is NOT enough.
- On every non-trivial task you MUST call pack_context(mode=lean) — after map or with a known seed.
- If pack is thin → expand_context before native Grep thrash.
- Do NOT use status/gate/dir listing as a substitute for pack.

WHEN / WHICH TOOL
- Unknown area / soft question → map(descriptive code-vocab, k=10) THEN pack_context(same query, suggested_seed, mode=lean).
- Known seed needing bodies → pack_context(mode=lean) first.
- Thin after pack → expand_context(callees|callers|effects|broad) or collect_hot_context(ids=…).
- Edit-ready soft hit → pinpoint. Overview without bodies → plate.
- Exact string/import/error → native Grep. Filename → Glob. Known path → Read.

HARD REQUIREMENTS
- Before the first repo-wide native search or directory thrash: finish map+pack (or pack if seed known).
- Before editing unfamiliar code: use pack/expand bodies (or card.loc Read from the heatmap).
- Target ≥2 Scubiee locate calls with pack included (map+pack or pack+expand). Map-only / gate-only is a FAIL.
- Forbidden opener: recursive dir listing / shotgun findstr across the repo before pack.

Native Grep/Read/Write/Shell after the ladder (or if Scubiee errors). Do not deadlock.
"""

WITHOUT_EXTRA = """
You do NOT have scubiee MCP. BAN inventing MCP locate tools.
Use only built-in read/write/shell to explore and implement.
"""

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
    env = {
        "CTX_BACKGROUND_SYNC": "0",
        "CTX_TRACE_ENGINE": "composite_v1",
        "CTX_ALLOW_BG_FULL": "0",
        "CTX_ENGINE_URL": "http://127.0.0.1:8765",
        "CTX_AUTO_INDEX": "0",
        "CTX_MCP_SESSION_ISOLATE": "1",
        "CTX_MCP_BRIDGE_MODE": "auto",
        "CTX_REPO": str(repo).replace("\\", "/"),
        "CTX_MCP_CLIENT": "kiro",
        "CTX_MCP_SURFACE": "phase",
        "CTX_MCP_EXPERIMENT": "hybrid",
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
                }:
                    env[str(k)] = str(v)
        except json.JSONDecodeError:
            pass
    env["CTX_REPO"] = str(repo).replace("\\", "/")
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


def install_gate_surface(ws: Path, *, with_mcp: bool) -> dict[str, str]:
    """Write AGENTS.md + Kiro steering (+ Cursor rule) so hosts load locate policy.

    with_mcp=True  → full MUST-Use-Scubiee GATE (same text as product rules_installer)
    with_mcp=False → BAN Scubiee / native-only (fair without arm)
    """
    agents_md = ws / "AGENTS.md"
    steering = ws / ".kiro" / "steering" / "scubiee.md"
    cursor_rule = ws / ".cursor" / "rules" / "scubiee.mdc"
    steering.parent.mkdir(parents=True, exist_ok=True)
    cursor_rule.parent.mkdir(parents=True, exist_ok=True)

    if with_mcp:
        body = _gate_body()
        _upsert_agents_gate(agents_md, body)
        steering.write_text(body + "\n", encoding="utf-8")
        cursor_rule.write_text(body + "\n", encoding="utf-8")
        return {
            "agents_md": "gate_with_scubiee",
            "steering": "gate_with_scubiee",
            "cursor_rule": "gate_with_scubiee",
        }

    ban = (
        "**GATE A/B without-Scubiee arm** — Scubiee MCP tools are NOT available.\n"
        "BAN inventing map/pack_context/expand_context MCP calls.\n"
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


def assert_agent_surface(ws: Path, agent_path: Path, *, with_mcp: bool) -> list[str]:
    """Fail-fast checks that harness wired tools/rules/permissions correctly."""
    errs: list[str] = []
    cfg = json.loads(agent_path.read_text(encoding="utf-8"))
    if cfg.get("includeMcpJson") is not False:
        errs.append("includeMcpJson must be false")
    tools = cfg.get("tools") or []
    if "read" not in tools or "shell" not in tools:
        errs.append("missing native read/shell tools")
    if with_mcp:
        if "@scubiee" not in tools:
            errs.append("missing @scubiee tool allow")
        if "@scubiee/map" not in tools or "@scubiee/pack_context" not in tools:
            errs.append("missing explicit @scubiee/map or @scubiee/pack_context")
        srv = (cfg.get("mcpServers") or {}).get("scubiee") or {}
        if not srv:
            errs.append("missing mcpServers.scubiee")
        else:
            auto = srv.get("autoApprove") or []
            if "pack_context" not in auto and "*" not in auto:
                errs.append("autoApprove missing pack_context/*")
            env = srv.get("env") or {}
            if env.get("CTX_REPO", "").replace("\\", "/") != str(ws).replace("\\", "/"):
                errs.append("CTX_REPO does not point at snapshot workspace")
            if env.get("CTX_MCP_CLIENT") != "kiro":
                errs.append("CTX_MCP_CLIENT must be kiro")
            if env.get("CTX_TRACE_ENGINE") != "composite_v1":
                errs.append("CTX_TRACE_ENGINE must be composite_v1")
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
            if "MUST Use Scubiee" not in txt and "Use Scubiee" not in txt:
                errs.append(f"{label} missing Use Scubiee GATE wording")
            if "pack_context" not in txt:
                errs.append(f"{label} missing pack_context instruction")
            if "tracer" not in txt.lower() and "heatmap" not in txt.lower():
                errs.append(f"{label} missing tracer/heatmap pack emphasis")
        prompt = cfg.get("prompt") or ""
        if "pack_context" not in prompt or "map(" not in prompt:
            errs.append("agent prompt missing map/pack ladder")
        if "tracer" not in prompt.lower() and "heatmap" not in prompt.lower():
            errs.append("agent prompt missing tracer/heatmap pack emphasis")
    else:
        if any(str(t).startswith("@scubiee") for t in tools):
            errs.append("without-arm must not allow @scubiee tools")
        if (cfg.get("mcpServers") or {}).get("scubiee"):
            errs.append("without-arm must not embed scubiee mcpServers")
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
    tools_rw = ["read", "write", "shell"]
    tools = tools_rw + (SCUBIEE_LOCATE_TOOLS if with_mcp else [])
    cfg: dict[str, Any] = {
        "name": name,
        "description": f"Dev A/B arm {'WITH' if with_mcp else 'WITHOUT'} Scubiee",
        "includeMcpJson": False,
        "includePowers": False,
        "model": model,
        "prompt": SHARED_SYSTEM + (WITH_EXTRA if with_mcp else WITHOUT_EXTRA),
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
                    "match": [
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
                    ],
                    "effect": "allow",
                },
            ]
        },
        "mcpServers": {},
        "_ab_gate_surface": gate_meta,
    }
    if with_mcp:
        cfg["mcpServers"] = {
            "scubiee": {
                "command": str(BRIDGE).replace("\\", "/"),
                "args": [],
                "env": _scubiee_env(ws),
                "autoApprove": SCUBIEE_AUTO_APPROVE,
                "disabled": False,
            }
        }
    path = agents / f"{name}.json"
    # Strip harness-only meta before write
    cfg.pop("_ab_gate_surface", None)
    _write_json(path, cfg)
    # Keep a sidecar for transparency
    _write_json(
        agents / f"{name}.surface.json",
        {
            "gate": gate_meta,
            "tools": tools,
            "autoApprove": SCUBIEE_AUTO_APPROVE if with_mcp else [],
            "resources": cfg["resources"],
            "includeMcpJson": False,
            "mcp": bool(with_mcp),
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


def _parse_tools(text: str) -> dict[str, Any]:
    scubiee: list[str] = []
    native: list[str] = []
    for m in _MCP_TOOL.finditer(text):
        tool = m.group(1).strip().lower()
        server = m.group(2).strip().lower()
        if server == "scubiee":
            scubiee.append(tool)
    for m in _NATIVE_TOOL.finditer(text):
        native.append(m.group(1).strip().lower())
    return {
        "scubiee_tools": scubiee,
        "native_tools": native,
        "scubiee_count": len(scubiee),
        "native_count": len(native),
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


def _rubric_check(ws: Path) -> dict[str, Any]:
    """Best-effort behavioral check without prescribing agent path."""
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
    ]
    if with_mcp:
        cmd.append("--require-mcp-startup")
    cmd.append(DEV_PROMPT)

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{arm}.log"
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
            env=os.environ.copy(),
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
    tests = _run_tests(ws)
    rubric = _rubric_check(ws)

    isolation_ok = (tools["scubiee_count"] > 0) if with_mcp else (tools["scubiee_count"] == 0)

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
        "isolation": {
            "ok": isolation_ok,
            "note": (
                "scubiee tools used"
                if with_mcp and tools["scubiee_count"]
                else (
                    "WARNING: with-arm never called scubiee"
                    if with_mcp
                    else (
                        "no scubiee leakage"
                        if tools["scubiee_count"] == 0
                        else "LEAK: scubiee tools appeared"
                    )
                )
            ),
        },
        "diff": diff,
        "tests": tests,
        "rubric": rubric,
        "success": bool(
            diff.get("changed")
            and tests.get("ok")
            and isolation_ok
            and not timed_out
            and exit_code == 0
        ),
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
        "- With-arm: Scubiee MCP pinned to that arm's workspace `CTX_REPO`",
        "",
        "## Results",
        "",
        "| arm | success | credits | wall_ms | ~tok | scubiee# | native# | files changed | tests | isolation |",
        "|-----|---------|--------:|--------:|-----:|---------:|--------:|--------------:|-------|-----------|",
    ]
    for arm in ("with", "without"):
        r = report["runs"].get(arm)
        if not r:
            lines.append(f"| {arm} | — | — | — | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| {arm} | {'YES' if r.get('success') or r.get('success_corrected') else 'NO'} | {r.get('credits')} | {r.get('wall_ms')} | "
            f"{r.get('out_tokens_est')} | {(r.get('tools') or {}).get('scubiee_count')} | "
            f"{(r.get('tools') or {}).get('native_count')} | {len((r.get('diff') or {}).get('files') or [])} | "
            f"{'PASS' if (r.get('tests') or {}).get('ok') else 'FAIL'} | "
            f"{'OK' if (r.get('isolation') or {}).get('ok') else 'FAIL'} |"
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
    global DEV_PROMPT, ACTIVE_TASK_ID, ACTIVE_TEST_KEYWORDS, ACTIVE_TEST_FILES, OUT_JSON, OUT_MD

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
    args = ap.parse_args()

    task = TASKS[args.task]
    ACTIVE_TASK_ID = args.task
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
                    (path.parent / f"{path.stem}.surface.json").read_text(encoding="utf-8")
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
        print(f"ERROR: bridge missing: {BRIDGE}", file=sys.stderr)
        return 2

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

    protocol = {
        "model": args.model,
        "effort": args.effort,
        "timeout_s": args.timeout_s,
        "task_id": args.task,
        "task": task["title"],
        "prompt_style": "outcome+requirements+constraints; no path spoilers",
        "arms": arms,
        "sequential": True,
        "agent_engine": "v1",
        "legacy_ui": True,
        "includeMcpJson": False,
        "snapshots": {a: str(workspaces[a]) for a in arms},
        "run_id": run_id,
        "project_id": PROJECT_ID,
        "out_json": str(OUT_JSON),
        "out_md": str(OUT_MD),
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
                        "exit": row.get("exit_code"),
                    },
                    ensure_ascii=False,
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

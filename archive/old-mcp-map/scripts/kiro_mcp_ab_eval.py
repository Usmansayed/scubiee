#!/usr/bin/env python3
"""Isolated Kiro A/B: with Scubiee MCP vs native-only, same model/resources.

Fairness protocol
-----------------
* Same repo cwd, same model, same effort, same trust-all-tools.
* Sequential runs (never parallel) so CPU/RAM/network are shared fairly.
* Locate-only tasks (no edits) so arms cannot poison each other.
* Fresh chat each run (no --resume).
* Agent isolation:
  - ab_with_scubiee  → includeMcpJson=false, mcpServers={scubiee:...} only
  - ab_without_scubiee → includeMcpJson=false, mcpServers={}
  Both agents get the same built-in tools (fs_read, fileSearch, listDirectory,
  execute_bash). Only the with-arm also gets @scubiee/* tools.
* User/workspace MCP json is temporarily neutralized for BOTH arms so neither
  arm inherits a hidden global scubiee server (restored in finally).

Metrics (full transparency, per run + aggregates)
-------------------------------------------------
wall_ms, exit_code, credits (parsed), out_chars, ~tokens (chars/4),
tool_calls (scubiee vs native), gold file/symbol recall from transcript,
MCP isolation check (scubiee tool used? expected by arm).

Outputs
-------
docs/superpowers/plans/2026-09-05-kiro-mcp-ab.{json,md}
out/kiro_ab/<run_id>/*.log
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
AGENTS_DIR = ROOT / ".kiro" / "agents"
PROJECT_MCP = ROOT / ".kiro" / "settings" / "mcp.json"
USER_MCP = Path.home() / ".kiro" / "settings" / "mcp.json"
OUT_JSON = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-kiro-mcp-ab-collect.json"
OUT_MD = ROOT / "docs" / "superpowers" / "plans" / "2026-09-06-kiro-mcp-ab-collect.md"
LOG_ROOT = ROOT / "out" / "kiro_ab"

_JSON_TAIL = (
    "End with a JSON block only:\n"
    '{"files":["rel/path.py",...],"symbols":["name",...],"notes":"one sentence"}'
)

# Complex locate-only bank — multi-hop / vague / cross-module (not single-symbol lookups).
TASKS: list[dict[str, Any]] = [
    {
        "id": "C01_connect_permissions_gate",
        "complexity": "multi-hop",
        "prompt": (
            "LOCATE ONLY — do not edit any files.\n"
            "I need the full connect surface for Cursor: when someone runs scubiee connect, "
            "where do autoApprove/alwaysAllow land in mcp.json, where does mcpAllowlist land in "
            "permissions.json, AND where does the AGENTS.md / .cursor/rules GATE text get written?\n"
            "Trace cmd_connect → tool surface writers → permission writers → gate rule writers. "
            "Ignore CLI banners and print helpers.\n" + _JSON_TAIL
        ),
        "gold_files": [
            "packages/pipeline/__main__.py",
            "packages/pipeline/rules_installer.py",
            "packages/pipeline/mcp_permissions.py",
        ],
        "gold_symbols": [
            "cmd_connect",
            "write_project_tool_surface",
            "apply_permissions_to_repo_tool_surface",
            "write_project_gate_rules",
            "PHASE_LOCATE_TOOLS",
        ],
    },
    {
        "id": "C02_pack_expand_ladder",
        "complexity": "multi-hop",
        "prompt": (
            "LOCATE ONLY — do not edit any files.\n"
            "Explain the agent locate ladder end-to-end: soft map → pack_context(lean) heatmap+bodies "
            "→ expand_context delta hops. Where is pack implemented, how bodies are collected "
            "(run_collect_hot / heatmap_to_cards), and where expand_context is registered/impl?\n"
            "I care about the production MCP path, not tests.\n" + _JSON_TAIL
        ),
        "gold_files": [
            "packages/pipeline/context_trace.py",
            "packages/pipeline/mcp_locate.py",
        ],
        "gold_symbols": [
            "run_pack_context",
            "run_collect_hot",
            "heatmap_to_cards",
            "pack_context_impl",
            "expand_context_impl",
        ],
    },
    {
        "id": "C03_composite_vs_poly_escape",
        "complexity": "policy",
        "prompt": (
            "LOCATE ONLY — do not edit any files.\n"
            "Production tracing default should be composite_v1, but pack_context(policy=broad) "
            "must escape to polytrace temporarily. Find _trace_engine / bind_composite_v1 and the "
            "policy=broad temporary CTX_TRACE_ENGINE swap + restore path inside run_pack_context.\n"
            "Do not confuse this with CTX_MCP_EXPERIMENT=hybrid.\n" + _JSON_TAIL
        ),
        "gold_files": [
            "packages/pipeline/context_trace.py",
            "packages/trace_lab/composite_v1.py",
        ],
        "gold_symbols": ["_trace_engine", "bind_composite_v1", "run_pack_context", "run_composite_v1"],
    },
    {
        "id": "C04_graphify_store_vs_rebuild",
        "complexity": "multi-hop",
        "prompt": (
            "LOCATE ONLY — do not edit any files.\n"
            "When context tracing starts, how does it prefer loading init graph.json from the "
            "project store instead of rebuilding Graphify every time? Trace load_store_graphify_graph, "
            "_load_repo / _want_graphify, and the rebuild escape hatch.\n" + _JSON_TAIL
        ),
        "gold_files": [
            "packages/pipeline/context_trace.py",
            "packages/trace_lab/graphify_layer.py",
        ],
        "gold_symbols": ["load_store_graphify_graph", "_load_repo", "_want_graphify"],
    },
    {
        "id": "C05_incremental_merkle_confirm",
        "complexity": "multi-hop",
        "prompt": (
            "LOCATE ONLY — do not edit any files.\n"
            "Files change on disk — how does incremental sync detect dirty paths (merkle), "
            "patch graph.json (patch_and_save_graph), re-embed, and gate huge deltas with "
            "IndexConfirmRequired? Follow from sync_loop into incremental.\n" + _JSON_TAIL
        ),
        "gold_files": [
            "packages/pipeline/incremental.py",
            "packages/pipeline/sync_loop.py",
        ],
        "gold_symbols": ["patch_and_save_graph", "IndexConfirmRequired"],
    },
    {
        "id": "C06_session_isolation_parallel",
        "complexity": "cross-cutting",
        "prompt": (
            "LOCATE ONLY — do not edit any files.\n"
            "Two Cursor chats share one MCP process — how are pins/handles/context_trace isolated "
            "per session_id? Trace _resolve_session, session_store load/save, "
            "CTX_MCP_SESSION_ISOLATE, and where pack/map persist per-session state.\n" + _JSON_TAIL
        ),
        "gold_files": [
            "packages/pipeline/session_store.py",
            "packages/pipeline/mcp_locate.py",
        ],
        "gold_symbols": ["load_store", "save_store", "_resolve_session", "persist_trace"],
    },
    {
        "id": "C07_kiro_mcp_install",
        "complexity": "host-surface",
        "prompt": (
            "LOCATE ONLY — do not edit any files.\n"
            "scubiee connect --kiro must write .kiro/settings/mcp.json and steering. Find "
            "write_kiro_mcp (and related install path) — env pins, autoApprove, project vs user "
            "behavior. Ignore Cursor-only writers unless they share helpers.\n" + _JSON_TAIL
        ),
        "gold_files": ["packages/pipeline/mcp_install.py"],
        "gold_symbols": ["write_kiro_mcp"],
    },
    {
        "id": "C08_uv_access_denied_vague",
        "complexity": "vague",
        "prompt": (
            "LOCATE ONLY — do not edit any files.\n"
            "Vague bug: 'Access denied' when forcing a uv tool reinstall of scubiee while an MCP "
            "bridge is still running on Windows. I don't know the function names — find the unlock/"
            "lock-release path that stops engine/MCP processes so the exe can be replaced.\n"
            + _JSON_TAIL
        ),
        "gold_files": ["packages/pipeline/process_control.py"],
        "gold_symbols": [
            "prepare_uv_tool_directory_for_swap",
            "release_scubiee_process_locks",
            "stop_all_context_engine_processes",
        ],
    },
    {
        "id": "C09_auth_jwt_trap",
        "complexity": "fixture-trap",
        "prompt": (
            "LOCATE ONLY — do not edit any files.\n"
            "Fixture login fails with invalid/expired JWT. Trace the credential path only: "
            "authenticate → extract_bearer → JwtService.verify → decode → TOKEN_TTL → "
            "UserRepository.resolve under fixtures/trace-lab. Do NOT pull billing/analytics/"
            "logger side effects even if names look related.\n" + _JSON_TAIL
        ),
        "gold_files": [
            "fixtures/trace-lab/app/middleware/auth.py",
            "fixtures/trace-lab/app/services/jwt_service.py",
            "fixtures/trace-lab/app/utils/token.py",
            "fixtures/trace-lab/app/repositories/user_repo.py",
        ],
        "gold_symbols": [
            "authenticate",
            "extract_bearer",
            "JwtService.verify",
            "decode",
            "UserRepository.resolve",
        ],
    },
    {
        "id": "C10_warm_status_ready",
        "complexity": "cross-cutting",
        "prompt": (
            "LOCATE ONLY — do not edit any files.\n"
            "MCP status sometimes says soft_search_ready / agent_ready warming or stale. "
            "Where is readiness computed from the engine daemon / WarmSearchEngine, and how does "
            "status expose warm_state to agents?\n" + _JSON_TAIL
        ),
        "gold_files": [
            "packages/pipeline/mcp_locate.py",
            "packages/pipeline/engine.py",
        ],
        "gold_symbols": ["soft_search_ready", "WarmSearchEngine"],
    },
    {
        "id": "C11_pack_bodies_optin_collect",
        "complexity": "collect",
        "prompt": (
            "COLLECT CONTEXT ONLY — do not edit, implement, or run tests.\n"
            "Work prompt (find the real call sites and sketch a fix; do not code it):\n"
            "Wire MCP pack body opt-in properly: when an env flag and/or explicit tool flag "
            "turns bodies on, pack_context / pack_poly_embed / pack_semantic must actually "
            "collect bodies. Today MCP hardcodes bodies off and the env only reshapes if "
            "pack[] is already non-empty. Find the MCP pack factory call site, the pack "
            "runner include_bodies path, the lean slim/want_bodies reshape, field docs, "
            "and which tests to extend.\n"
            "WITH Scubiee: expand a descriptive code-vocab query → map(k=10) → "
            "pack_context(mode=lean) with the SAME query → Native-Read top heatmap locs only "
            "(BAN whole-file of heatmap paths) → at most one expand_context if thin.\n"
            "WITHOUT Scubiee: Grep/Read only.\n"
            "Return an ordered context pack (file:lines + what it proves) in notes, plus "
            "a short implementation sketch.\n" + _JSON_TAIL
        ),
        "gold_files": [
            "packages/pipeline/mcp_locate.py",
            "packages/pipeline/context_trace.py",
            "packages/pipeline/mcp_response_lean.py",
            "tests/test_mcp_response_lean.py",
        ],
        "gold_symbols": [
            "_make_pack_impl",
            "run_pack_context",
            "include_bodies",
            "slim_locate_payload",
            "CTX_MCP_PACK_BODIES",
            "want_bodies",
        ],
    },
]

SHARED_PROMPT = """You are a locate-only coding assistant for a fair A/B evaluation.

Hard rules:
- Do NOT edit, create, or delete files.
- Do NOT run git write commands, installs, or servers.
- Prefer read/search tools. Keep exploration tight.
- Finish with the requested JSON block (files + symbols).
"""

SCUBIEE_PROMPT_EXTRA = """
You HAVE the scubiee MCP server. There is NO Scubiee CLI locate — BAN shell `scubiee map|pack|expand`.
LOCATE PRIORITY (managed Prefer/Forbid):
- Soft/structural → Prefer map → pack_context(mode=lean, same query) → Native-Read top heatmap locs. expand_context if thin.
- When Scubiee MCP is available: MUST finish pack — map-only / warming-or-error escape = FAIL. Retry pack/status first.
- Exact literals / imports / error strings / JWT-like needles → Prefer host Grep/rg FIRST (Forbid-first map/pack).
- Filename/path → Prefer Glob/fileSearch first. Known path:lines → Prefer span Read.
- Forbid packing empty/_/test seeds. After heatmap, guided native Grep/Read on card locs is OK.
- Native OK only if Scubiee is fully uncallable — no deadlock. Do not parallel-thrash explore with Scubiee.
Then answer with the JSON block.
"""

NATIVE_PROMPT_EXTRA = """
You do NOT have scubiee MCP. BAN inventing MCP locate tools.
BAN running `scubiee map`, `scubiee pack`, or `scubiee expand`.
Use only built-in fs_read / fileSearch / listDirectory / shell (rg/findstr/dir).
"""

# Prefer category tags from Kiro agent schema (read/shell/@server).
BUILTIN_TOOLS = ["read", "shell"]
SCUBIEE_TOOLS = [
    "@scubiee",
    "@scubiee/gate",
    "@scubiee/map",
    "@scubiee/pack_context",
    "@scubiee/map_context",
    "@scubiee/expand_context",
    "@scubiee/collect_hot_context",
    "@scubiee/pinpoint",
    "@scubiee/plate",
    "@scubiee/workspace",
    "@scubiee/expand",
    "@scubiee/status",
]
SCUBIEE_AUTO_APPROVE = [
    "gate",
    "map",
    "pack_context",
    "map_context",
    "expand_context",
    "collect_hot_context",
    "pinpoint",
    "plate",
    "workspace",
    "expand",
    "status",
    "*",
]


def _load_dotenv_key() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\s*KIRO_API_KEY\s*=\s*(.+)\s*$", line)
        if m:
            os.environ["KIRO_API_KEY"] = m.group(1).strip().strip('"').strip("'")
            return


def _scubiee_mcp_entry() -> dict[str, Any]:
    """Build agent-owned scubiee MCP entry from project mcp.json (fallback defaults)."""
    entry: dict[str, Any] = {
        "command": str(BRIDGE).replace("\\", "/"),
        "args": [],
        "env": {
            "CTX_BACKGROUND_SYNC": "1",
            "CTX_TRACE_ENGINE": "composite_v1",
            "CTX_ALLOW_BG_FULL": "0",
            "CTX_ENGINE_IDLE_S": "15",
            "CTX_ENGINE_TRANSITION_DEBOUNCE_S": "15",
            "CTX_ENGINE_URL": "http://127.0.0.1:8765",
            "CTX_AUTO_INDEX": "1",
            "CTX_MCP_SESSION_ISOLATE": "1",
            "CTX_MCP_BRIDGE_MODE": "auto",
            "CTX_REPO": str(ROOT).replace("\\", "/"),
            "CTX_MCP_CLIENT": "kiro",
            "CTX_MCP_SURFACE": "phase",
            "CTX_SYNC_INTERVAL_MS": "300000",
            "CTX_REGISTRATION_MODE": "automatic",
            "CTX_MCP_EXPERIMENT": "ship",
            "CTX_TRACE_GRAPHIFY": "1",
            "CTX_PROJECT_ID": PROJECT_ID,
            "CTX_TOKEN_MODE": "savings",
            "PYTHONUTF8": "1",
            "CTX_SCUBIEE_BUILD": "0.3.15-kiro-ab",
        },
        "autoApprove": list(SCUBIEE_AUTO_APPROVE),
        "disabled": False,
    }
    if PROJECT_MCP.is_file():
        try:
            data = json.loads(PROJECT_MCP.read_text(encoding="utf-8"))
            src = (data.get("mcpServers") or {}).get("scubiee") or {}
            if src.get("command"):
                entry["command"] = src["command"]
            if isinstance(src.get("env"), dict):
                entry["env"].update({str(k): str(v) for k, v in src["env"].items()})
            entry["env"]["CTX_TRACE_ENGINE"] = "composite_v1"
            entry["env"]["CTX_MCP_CLIENT"] = "kiro"
            entry["env"]["CTX_REPO"] = str(ROOT).replace("\\", "/")
            entry["env"]["CTX_PROJECT_ID"] = PROJECT_ID
            entry["autoApprove"] = list(SCUBIEE_AUTO_APPROVE)
        except json.JSONDecodeError:
            pass
    return entry


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_agents(*, model: str) -> dict[str, Path]:
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    with_path = AGENTS_DIR / "ab_with_scubiee.json"
    without_path = AGENTS_DIR / "ab_without_scubiee.json"
    common = {
        "includeMcpJson": False,
        "includePowers": False,
        "model": model,
        "permissions": {
            "rules": [
                {"capability": "shell", "match": ["rg *", "findstr *", "dir *", "ls *", "type *", "Get-ChildItem *", "Select-String *"], "effect": "allow"},
            ]
        },
    }
    with_agent = {
        **common,
        "name": "ab_with_scubiee",
        "description": "A/B arm WITH Scubiee MCP (isolated; no legacy mcp.json merge)",
        "prompt": SHARED_PROMPT + SCUBIEE_PROMPT_EXTRA,
        "mcpServers": {"scubiee": _scubiee_mcp_entry()},
        "tools": BUILTIN_TOOLS + SCUBIEE_TOOLS,
        "allowedTools": BUILTIN_TOOLS + SCUBIEE_TOOLS,
        "resources": [
            "file://AGENTS.md",
            "file://.kiro/steering/scubiee.md",
        ],
    }
    without_agent = {
        **common,
        "name": "ab_without_scubiee",
        "description": "A/B arm WITHOUT Scubiee MCP (isolated native tools only)",
        "prompt": SHARED_PROMPT + NATIVE_PROMPT_EXTRA,
        "mcpServers": {},
        "tools": BUILTIN_TOOLS,
        "allowedTools": BUILTIN_TOOLS,
        "resources": [
            "file://AGENTS.md",
        ],
    }
    _write_json(with_path, with_agent)
    _write_json(without_path, without_agent)
    return {"with": with_path, "without": without_path}


def _validate_agent(path: Path) -> None:
    proc = subprocess.run(
        [str(KIRO), "agent", "validate", "--path", str(path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"agent validate failed for {path}:\n{proc.stdout}\n{proc.stderr}"
        )


class McpNeutralizer:
    """Temporarily replace user+project mcp.json so only agent mcpServers apply."""

    def __init__(self) -> None:
        self._backups: list[tuple[Path, Path | None]] = []

    def __enter__(self) -> McpNeutralizer:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        for path in (PROJECT_MCP, USER_MCP):
            if not path.is_file():
                # Ensure empty file exists so hosts don't recreate from elsewhere mid-run.
                path.parent.mkdir(parents=True, exist_ok=True)
                bak = None
                path.write_text('{"mcpServers":{}}\n', encoding="utf-8")
                self._backups.append((path, bak))
                continue
            bak = path.with_suffix(path.suffix + f".ab_bak_{stamp}")
            shutil.copy2(path, bak)
            path.write_text('{"mcpServers":{}}\n', encoding="utf-8")
            self._backups.append((path, bak))
        return self

    def __exit__(self, *exc: object) -> None:
        for path, bak in reversed(self._backups):
            if bak is None:
                # We created a placeholder; remove if empty MCP.
                try:
                    if path.is_file() and '"mcpServers":{}' in path.read_text(encoding="utf-8"):
                        # leave empty mcp — safer than deleting user file we invented
                        pass
                except OSError:
                    pass
                continue
            if bak.is_file():
                shutil.copy2(bak, path)
                bak.unlink(missing_ok=True)


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b.")
_CREDIT = re.compile(r"Credits:\s*([0-9]+(?:\.[0-9]+)?)", re.I)
# "Time: 6s" or "Time: 1m 47s"
_TIME = re.compile(r"Time:\s*(?:(\d+)\s*m\s*)?(\d+)\s*s", re.I)
# Only count explicit invocations — not bare words like map/gate in code dumps.
_MCP_TOOL = re.compile(
    r"Running tool\s+(\S+)\s+.*?\(from mcp server:\s*(\w+)\)",
    re.I | re.S,
)
_NATIVE_TOOL = re.compile(r"\(using tool:\s*([A-Za-z_][\w]*)", re.I)
_SCUBIEE_TOOL_NAMES = {
    "gate",
    "map",
    "pack_context",
    "expand_context",
    "collect_hot_context",
    "map_context",
    "pinpoint",
    "plate",
    "workspace",
    "expand",
    "status",
}


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def _tokens(chars: int) -> int:
    return max(0, (chars + 3) // 4)


def _parse_tools(text: str) -> dict[str, Any]:
    scubiee: list[str] = []
    native: list[str] = []
    other_mcp: list[str] = []
    for m in _MCP_TOOL.finditer(text):
        tool = m.group(1).strip().lower()
        server = m.group(2).strip().lower()
        if server == "scubiee" or tool in _SCUBIEE_TOOL_NAMES:
            scubiee.append(tool)
        else:
            other_mcp.append(f"{server}/{tool}")
    for m in _NATIVE_TOOL.finditer(text):
        name = m.group(1).strip().lower()
        if name in _SCUBIEE_TOOL_NAMES:
            # unlikely; keep out of native
            continue
        native.append(name)
    return {
        "scubiee_tools": scubiee,
        "native_tools": native,
        "other_mcp_tools": other_mcp,
        "scubiee_count": len(scubiee),
        "native_count": len(native),
        "total_tool_mentions": len(scubiee) + len(native) + len(other_mcp),
    }


def _score_gold(text: str, gold_files: list[str], gold_symbols: list[str]) -> dict[str, Any]:
    norm = text.replace("\\", "/")
    files_hit = [g for g in gold_files if g in norm or Path(g).name in norm]
    syms_hit = [g for g in gold_symbols if g in text]
    return {
        "file_hits": files_hit,
        "symbol_hits": syms_hit,
        "file_rec": round(len(files_hit) / len(gold_files), 3) if gold_files else None,
        "symbol_rec": round(len(syms_hit) / len(gold_symbols), 3) if gold_symbols else None,
    }


def _engine_health() -> dict[str, Any]:
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def run_one(
    *,
    arm: str,
    agent: str,
    task: dict[str, Any],
    model: str,
    effort: str,
    log_dir: Path,
    require_mcp: bool,
    timeout_s: int,
) -> dict[str, Any]:
    log_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{task['id']}__{arm}"
    log_path = log_dir / f"{stem}.log"
    meta_path = log_dir / f"{stem}.meta.json"

    cmd = [
        str(KIRO),
        "chat",
        "--no-interactive",
        "--trust-all-tools",
        "--agent",
        agent,
        "--model",
        model,
        "--effort",
        effort,
        "--wrap",
        "never",
        # v1+legacy-ui emits "Running tool … (from mcp server: …)" + Credits footer
        # into captured stdout (default v2 TUI often omits tool lines under pipes).
        "--agent-engine",
        "v1",
        "--legacy-ui",
    ]
    if require_mcp:
        cmd.append("--require-mcp-startup")
    cmd.append(task["prompt"])

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            env=os.environ.copy(),
        )
        wall_ms = (time.perf_counter() - t0) * 1000
        raw = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
        exit_code = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        wall_ms = (time.perf_counter() - t0) * 1000
        raw = ((exc.stdout or "") if isinstance(exc.stdout, str) else "") + (
            "\n" + (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        )
        if not raw and exc.output:
            raw = str(exc.output)
        raw += f"\n[TIMEOUT after {timeout_s}s]"
        exit_code = 124
        timed_out = True

    clean = _strip_ansi(raw)
    log_path.write_text(clean, encoding="utf-8")
    tools = _parse_tools(clean)
    gold = _score_gold(clean, task["gold_files"], task["gold_symbols"])
    credits_m = _CREDIT.search(clean)
    time_m = _TIME.search(clean)
    reported_time_s = None
    if time_m:
        mins = int(time_m.group(1) or 0)
        secs = int(time_m.group(2) or 0)
        reported_time_s = mins * 60 + secs
    result = {
        "task_id": task["id"],
        "arm": arm,
        "agent": agent,
        "model": model,
        "effort": effort,
        "require_mcp_startup": require_mcp,
        "cmd": cmd,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "wall_ms": round(wall_ms, 1),
        "out_chars": len(clean),
        "out_tokens_est": _tokens(len(clean)),
        "credits": float(credits_m.group(1)) if credits_m else None,
        "reported_time_s": reported_time_s,
        "tools": tools,
        "gold": gold,
        "isolation": {
            "scubiee_tools_seen": tools["scubiee_count"] > 0,
            "expected_scubiee": arm == "with",
            "ok": (tools["scubiee_count"] > 0) == (arm == "with")
            if arm == "without"
            else True,  # with-arm may still fail to call MCP; scored separately
        },
        "log": str(log_path.relative_to(ROOT)).replace("\\", "/"),
    }
    # Stricter isolation for with-arm: prefer MCP used, but don't fail the whole suite.
    if arm == "with":
        result["isolation"]["ok"] = tools["scubiee_count"] > 0
        result["isolation"]["note"] = (
            "scubiee tools used" if tools["scubiee_count"] else "WARNING: with-arm never called scubiee"
        )
    else:
        result["isolation"]["ok"] = tools["scubiee_count"] == 0
        result["isolation"]["note"] = (
            "no scubiee leakage" if tools["scubiee_count"] == 0 else "LEAK: scubiee tools appeared"
        )

    _write_json(meta_path, result)
    return result


def _agg(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    xs = [r for r in rows if r["arm"] == arm]
    if not xs:
        return {}

    def mean(key: str) -> float | None:
        vals = [r[key] for r in xs if isinstance(r.get(key), (int, float))]
        return round(sum(vals) / len(vals), 3) if vals else None

    def mean_nested(path: tuple[str, str]) -> float | None:
        vals = []
        for r in xs:
            cur: Any = r
            for p in path:
                cur = (cur or {}).get(p) if isinstance(cur, dict) else None
            if isinstance(cur, (int, float)):
                vals.append(cur)
        return round(sum(vals) / len(vals), 3) if vals else None

    return {
        "n": len(xs),
        "mean_wall_ms": mean("wall_ms"),
        "mean_out_tokens_est": mean("out_tokens_est"),
        "mean_credits": mean("credits"),
        "mean_file_rec": mean_nested(("gold", "file_rec")),
        "mean_symbol_rec": mean_nested(("gold", "symbol_rec")),
        "mean_scubiee_tools": mean_nested(("tools", "scubiee_count")),
        "mean_native_tools": mean_nested(("tools", "native_count")),
        "isolation_ok": all(r.get("isolation", {}).get("ok") for r in xs),
        "exit_nonzero": sum(1 for r in xs if r.get("exit_code")),
    }


def write_md(report: dict[str, Any]) -> None:
    arms = report["summary"]["arms"]
    lines = [
        "# Kiro with/without Scubiee MCP A/B",
        "",
        f"**Date:** {report['started_at']}",
        f"**Model:** `{report['protocol']['model']}` · **Effort:** `{report['protocol']['effort']}`",
        f"**Tasks:** {report['protocol']['n_tasks']} locate-only · **Runs:** {len(report['runs'])}",
        "",
        "## Fairness / isolation",
        "",
        "- Same cwd, model, effort, trust-all-tools",
        "- Sequential (not parallel) — shared machine resources",
        "- Agents: `ab_with_scubiee` vs `ab_without_scubiee`",
        "- `includeMcpJson=false` on both; agent owns MCP surface",
        "- User + project `mcp.json` neutralized during the suite (restored after)",
        "- Locate-only prompts (no edits)",
        "",
        "## Scoreboard",
        "",
        "| Arm | n | mean wall_ms | ~tokens | credits | file_rec | symbol_rec | scubiee tools | native tools | isolation |",
        "|-----|---|-------------:|--------:|--------:|---------:|-----------:|--------------:|-------------:|-----------|",
    ]
    for arm in ("with", "without"):
        a = arms.get(arm, {})
        lines.append(
            f"| {arm} | {a.get('n')} | {a.get('mean_wall_ms')} | {a.get('mean_out_tokens_est')} | "
            f"{a.get('mean_credits')} | {a.get('mean_file_rec')} | {a.get('mean_symbol_rec')} | "
            f"{a.get('mean_scubiee_tools')} | {a.get('mean_native_tools')} | "
            f"{'OK' if a.get('isolation_ok') else 'FAIL'} |"
        )
    w, o = arms.get("with") or {}, arms.get("without") or {}

    def _delta(key: str) -> str:
        a, b = w.get(key), o.get(key)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or b == 0:
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return f"{a - b:+.3g}"
            return "n/a"
        d = a - b
        pct = 100.0 * d / b
        return f"{d:+.3g} ({pct:+.0f}%)"

    lines += [
        "",
        "### Deltas (with − without)",
        "",
        "| Metric | delta |",
        "|--------|------:|",
        f"| mean wall_ms | {_delta('mean_wall_ms')} |",
        f"| mean ~tokens | {_delta('mean_out_tokens_est')} |",
        f"| mean credits | {_delta('mean_credits')} |",
        f"| mean file_rec | {_delta('mean_file_rec')} |",
        f"| mean symbol_rec | {_delta('mean_symbol_rec')} |",
        "",
        "## Per-run",
        "",
    ]
    lines.append(
        "| task | arm | wall_ms | ~tok | credits | file_rec | symbol_rec | scubiee# | native# | isolation | log |"
    )
    lines.append(
        "|------|-----|--------:|-----:|--------:|---------:|-----------:|---------:|--------:|-----------|-----|"
    )
    for r in report["runs"]:
        g = r.get("gold") or {}
        t = r.get("tools") or {}
        iso = r.get("isolation") or {}
        lines.append(
            f"| {r['task_id']} | {r['arm']} | {r['wall_ms']} | {r['out_tokens_est']} | "
            f"{r.get('credits')} | {g.get('file_rec')} | {g.get('symbol_rec')} | "
            f"{t.get('scubiee_count')} | {t.get('native_count')} | "
            f"{'OK' if iso.get('ok') else 'FAIL'} | `{r.get('log')}` |"
        )
    lines += ["", "## Protocol notes", ""]
    lines.append("```json")
    lines.append(json.dumps(report["protocol"], indent=2))
    lines.append("```")
    lines.append("")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--model",
        default="auto",
        help="Pinned model for BOTH arms (default: auto — Kiro picks per task)",
    )
    ap.add_argument("--effort", default="medium")
    ap.add_argument("--timeout-s", type=int, default=420)
    ap.add_argument("--tasks", default="", help="Comma task ids (default: all complex tasks)")
    ap.add_argument("--smoke", action="store_true", help="Run only first task both arms")
    args = ap.parse_args()

    _load_dotenv_key()
    if not os.environ.get("KIRO_API_KEY"):
        print("ERROR: KIRO_API_KEY missing (set in .env or env)", file=sys.stderr)
        return 2
    if not KIRO.is_file():
        print(f"ERROR: kiro-cli not found: {KIRO}", file=sys.stderr)
        return 2

    tasks = TASKS
    if args.smoke:
        tasks = TASKS[:1]
    elif args.tasks.strip():
        want = {t.strip() for t in args.tasks.split(",") if t.strip()}
        tasks = [t for t in TASKS if t["id"] in want]
        if not tasks:
            print("ERROR: no matching tasks", file=sys.stderr)
            return 2

    started = datetime.now(timezone.utc).isoformat()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_dir = LOG_ROOT / run_id

    paths = write_agents(model=args.model)
    _validate_agent(paths["with"])
    _validate_agent(paths["without"])

    health = _engine_health()
    protocol = {
        "model": args.model,
        "effort": args.effort,
        "timeout_s": args.timeout_s,
        "n_tasks": len(tasks),
        "arms": ["with", "without"],
        "sequential": True,
        "agent_engine": "v1",
        "legacy_ui": True,
        "trust_all_tools": True,
        "locate_only": True,
        "includeMcpJson": False,
        "mcp_neutralized": ["project .kiro/settings/mcp.json", "user ~/.kiro/settings/mcp.json"],
        "agents": {
            "with": "ab_with_scubiee",
            "without": "ab_without_scubiee",
        },
        "engine_health": health,
        "kiro_cli": str(KIRO),
        "bridge": str(BRIDGE),
        "project_id": PROJECT_ID,
        "run_id": run_id,
    }

    print(json.dumps({"event": "protocol", **protocol}, indent=2, default=str))
    print("---", flush=True)

    runs: list[dict[str, Any]] = []
    # Interleave by task: with then without — same machine state per task pair.
    order = [("with", "ab_with_scubiee", True), ("without", "ab_without_scubiee", False)]

    with McpNeutralizer():
        for task in tasks:
            for arm, agent, req_mcp in order:
                print(f"RUN {task['id']} arm={arm} ...", flush=True)
                row = run_one(
                    arm=arm,
                    agent=agent,
                    task=task,
                    model=args.model,
                    effort=args.effort,
                    log_dir=log_dir,
                    require_mcp=req_mcp,
                    timeout_s=args.timeout_s,
                )
                runs.append(row)
                print(
                    json.dumps(
                        {
                            "event": "result",
                            "task": row["task_id"],
                            "arm": row["arm"],
                            "wall_ms": row["wall_ms"],
                            "tokens": row["out_tokens_est"],
                            "credits": row["credits"],
                            "file_rec": row["gold"]["file_rec"],
                            "symbol_rec": row["gold"]["symbol_rec"],
                            "scubiee_tools": row["tools"]["scubiee_count"],
                            "native_tools": row["tools"]["native_count"],
                            "isolation": row["isolation"]["note"],
                            "exit": row["exit_code"],
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
        "tasks": [
            {
                "id": t["id"],
                "complexity": t.get("complexity"),
                "gold_files": t["gold_files"],
                "gold_symbols": t["gold_symbols"],
            }
            for t in tasks
        ],
        "runs": runs,
        "summary": {
            "arms": {
                "with": _agg(runs, "with"),
                "without": _agg(runs, "without"),
            }
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    _write_json(OUT_JSON, report)
    write_md(report)
    print("---", flush=True)
    print(json.dumps({"event": "summary", "summary": report["summary"], "json": str(OUT_JSON), "md": str(OUT_MD)}, indent=2))
    # Fail if without-arm leaked scubiee
    if not report["summary"]["arms"].get("without", {}).get("isolation_ok", True):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

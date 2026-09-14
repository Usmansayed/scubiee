"""MCP: scubiee — session-native code context, switchable surfaces.

Surface is chosen by env ``CTX_MCP_SURFACE``:

  phase (default): ship OR lab OR classic
    ship (CTX_MCP_EXPERIMENT=ship, default; legacy hybrid→ship):
      map | pack_context | expand_context | collect_hot_context |
      workspace | expand | gate | status
      Ladder: map → pack(composite heatmap) → expand. Exact/name → host Grep/Glob.
      Lab extras: CTX_MCP_EXPERIMENT=lab. Classic: CTX_MCP_EXPERIMENT=classic.
    lab:
      ship + pack_poly_embed | pack_semantic | map_context | pinpoint | plate
    classic:
      map | focus | grep | glob | pack_* | map_context | workspace | expand | gate | status

  read: search | read | status
  nav: search | files | read | recall | expand | status
  graph: search | neighbors | graph | status
  rich: search | read | outline | status
  search: search | status

Data-backed from TraceLab + SWE-chat sessions.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Annotated, Any, Iterator, Literal

ROOT = Path(__file__).resolve().parents[2]
_src = ROOT / "packages"
if _src.is_dir() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # pragma: no cover
    FastMCP = None  # type: ignore

try:
    from pydantic import BaseModel, ConfigDict, Field, ValidationError
except Exception:  # pragma: no cover
    BaseModel = object  # type: ignore
    ConfigDict = dict  # type: ignore
    Field = lambda *a, **k: None  # type: ignore
    ValidationError = Exception  # type: ignore

from pipeline.rules_installer import managed_gate_mcp_header


_SURFACES = {"read", "nav", "graph", "rich", "search", "grep", "phase"}


def _active_surface() -> str:
    # Product default is phase/ship (map→pack_context→expand_context). Legacy surfaces
    # stay available via CTX_MCP_SURFACE for experiments.
    # remain available via CTX_MCP_SURFACE=read|nav|...
    val = (os.environ.get("CTX_MCP_SURFACE") or "phase").strip().lower()
    if val in {"graphify"}:
        return "graph"
    if val in {"trajectory", "map_focus"}:
        return "phase"
    return val if val in _SURFACES else "phase"


def _phase_experiment() -> str:
    """Phase tool pack.

    ``ship`` (default) — map → pack_context(composite heatmap) → expand_context;
    native Read/Grep/Glob for path/exact/name. No focus/pinpoint/plate/poly packs.
    ``lab`` — restore poly_embed/semantic + pinpoint/plate for experiments.
    ``classic`` — map/focus/grep/glob (pre-hybrid). Set
    ``CTX_MCP_EXPERIMENT=classic`` to back off without reverting git.
    """
    raw = (os.environ.get("CTX_MCP_EXPERIMENT") or "ship").strip().lower()
    if raw in {"classic", "phase_classic", "off", "0", "false", "grep_glob", "legacy"}:
        return "classic"
    if raw in {"lab", "full", "hybrid_lab", "hybrid_full", "pinpoint", "plate"}:
        return "lab"
    # ship is default; accept legacy "hybrid" as ship
    return "ship"


def _resolve_pack_bodies(include_bodies_flag: int | bool | None) -> bool:
    """Resolve MCP pack-body opt-in (flag OR CTX_MCP_PACK_BODIES). Default off = heatmap-only."""
    try:
        if int(include_bodies_flag or 0):
            return True
    except (TypeError, ValueError):
        if bool(include_bodies_flag):
            return True
    from pipeline.mcp_response_lean import pack_bodies_enabled

    return pack_bodies_enabled()


# Default shipped locate tools (permissions + docs). Lab/classic add extras at register time.
_SHIP_PHASE_CORE: list[str] = [
    "gate",
    "map",
    "pack_context",
    "expand_context",
    "collect_hot_context",
    "workspace",
    "expand",
    "status",
]


def _phase_tool_names() -> list[str]:
    exp = _phase_experiment()
    if exp == "classic":
        return [
            "gate",
            "pack_context",
            "pack_poly_embed",
            "pack_semantic",
            "map_context",
            "expand_context",
            "collect_hot_context",
            "map",
            "focus",
            "grep",
            "glob",
            "workspace",
            "expand",
            "status",
        ]
    if exp == "lab":
        return [
            "gate",
            "pack_context",
            "pack_poly_embed",
            "pack_semantic",
            "map_context",
            "expand_context",
            "collect_hot_context",
            "map",
            "pinpoint",
            "plate",
            "workspace",
            "expand",
            "status",
        ]
    return list(_SHIP_PHASE_CORE)


# ---- server instructions (per surface) -------------------------------------
# Keep these tiny: injected every turn. Recommend how/when/why — never prescribe
# a forced recipe. Coaching belongs here, not on every tool JSON response.

SERVER_INSTRUCTIONS_READ = """\
Scubiee = code locate. Tools: search | read | status.
Prefer Scubiee when available (host Grep/Read secondary). Native OK if MCP fails. You choose tools.

When useful:
- soft/where/how meaning -> search(query) with code vocabulary (symbols, modules, error terms)
- open a span to edit -> read(target) (optional neighbors=true for wiring)
- health -> status() (not for finding code)

Query tip: pack identifiers/synonyms (not bare prose). Shell = tests/build/git.
"""

SERVER_INSTRUCTIONS_GRAPH = """\
Scubiee = code locate. Tools: search | neighbors | graph | status.
Prefer Scubiee when available (host tools secondary). Native OK if MCP fails. You choose tools.

When useful:
- meaning -> search(query)
- who calls / uses X -> neighbors(target)
- how A relates to B -> graph(question)
- health -> status()

Shell = tests/build/git.
"""

SERVER_INSTRUCTIONS_RICH = """\
Scubiee = code locate. Tools: search | read | outline | status.
Prefer Scubiee when available (host tools secondary). Native OK if MCP fails. You choose tools.

When useful:
- meaning -> search(query) with code vocabulary
- open span / wiring -> read(target) or read(..., neighbors=true)
- file shape (defs only) -> outline(path)
- health -> status()

Shell = tests/build/git.
"""

SERVER_INSTRUCTIONS_SEARCH = """\
Scubiee search = soft/meaning code locate. Tool: search(query, include="hits", k=8). status()=health only.
Prefer over Grep/Task-explore for unfamiliar where/how/who; exact literals -> Grep; known path -> Read; filename -> Glob.
Native OK if MCP fails. You choose; avoid parallel explore thrash.

Query tip: one question + denser code vocabulary (~30-80 tokens: symbols, modules, synonyms). Prefer one sharp query over many rephrasings.
include: hits (default, thin) | span (short body peek) | graph (callers/callees on top hit).
Shell = tests/build/git.
"""

SERVER_INSTRUCTIONS_GREP = """\
Scubiee grep = exact/literal search. Tool: grep(pattern, glob=…).
Useful for imports, config keys, error strings, env names. Meaning questions -> map/search. Filenames -> glob.
Prefer Scubiee grep over shell grep when available. Native OK if MCP fails. Shell = tests/build/git.
"""

SERVER_INSTRUCTIONS_PHASE_SHIP_BODY = """\
Scenario routing (Prefer/Forbid — header above is policy; this is the how-to):

WHEN SCUBIEE MCP IS AVAILABLE (tools callable) — STRICT:
 Soft/structural edit/debug → MUST map→pack_context(lean) before broad native Grep/dir thrash or edit.
 Map-only for edit/debug = FAIL. Warming/error ≠ skip pack — retry pack_context/status first.
 Explain escape: map clusters one packages/ module + narrative ask → Native-Read map locs (skip pack OK).
 Edit/debug still MUST pack. Pack thin=true → expand_context or Read seed; do not re-pack thrash.
 Native-first while MCP up = FAIL on soft/structural. Native OK only if MCP fully uncallable — no deadlock.
 After pack: needle/health OR empty heatmap → stop ladder; Grep/Read — no map/status thrash.

INCREMENTAL LADDER (soft/structural — Prefer, ≤2–3 calls; query quality > remaps):
 0) ENRICH (~25–120 tokens, target ≥40): symbols, module paths, APIs, errors, tech, outcome verbs.
    Think the full problem surface first. One tight dense sentence. BAN essays/salad/<25-token vibes.
 1) No seed → map(enriched_query, k=12). Use suggested_seeds (1–3 packages/ public class/entrypoint).
 2) BEFORE pack: re-enrich query with ALL suggested_seeds file::symbol + 2–4 hot cards (usually longer).
    pack_context(refined query + seed_* + seed2_* [+ seed3_*], mode=lean) → multi_seed_v1 when ≥2 seeds
    (agreement+corridor). Engine: composite_v1 single-seed. Escape once policy=broad only if lean too tight.
    thin=true → expand or Read seed — do not re-pack.
 3) Native-Read top ~read.top heat=hot|warm locs. BAN whole-file Read of heatmap paths.
 4) If thin → expand_context(…, query=further refined). Bodies → collect_hot_context(ids=).
 Trusted seed → skip map; still enrich query; pack_context(lean) then Read locs. Prefer 1× map + 1× pack.

QUERY QUALITY: invest in the query. Weak = bare prose / synonym dump / <25 tokens.
 After map: pack query MUST be more specific (and usually longer) than map query.
 Strong = concrete symbols + module paths + APIs/errors + outcome verbs (≥40 tokens recommended).
 When suggested_seeds has 2+, pass seed2/seed3 — do not discard direction.

EXCEPTIONS (Forbid-first map/pack — native first):
- exact literal / import / error / JWT-like → Grep; named-symbol under known path → Grep/rg.
- filename → Glob; known path → Read; health/warm_state → gate/status + Grep.
- session/rematerialize → workspace(show)/expand(handle); gate/status = health not locate.

One soft ladder beat, then edit. No parallel explore thrash with Scubiee.
Shell = tests/build/git. Lab: CTX_MCP_EXPERIMENT=lab. Classic: CTX_MCP_EXPERIMENT=classic.
"""

SERVER_INSTRUCTIONS_PHASE_CLASSIC_BODY = """\
Scenario routing (follow when tools are available):

INCREMENTAL LADDER: map(k=12) → pack_context (mode=lean, composite_v1 / multi_seed_v1) → expand_context(delta) — ≤3 calls.
- Prefer pack_context after seed(s) → compressed heatmap (no bodies). Native-Read top ~read.top locs.
  collect_hot_context for bodies. policy=broad once if lean slice too tight
  (optional leaf→class densify; check escape_helped — not a density guarantee).
  ≥2 seeds → agreement+corridor merge (pass seed2/seed3 from suggested_seeds).
- QUERY QUALITY: Enrich first (~25–120 denser tokens, target ≥40: symbols/paths/APIs/errors/verbs).
  Vague one-liner OR synonym dump = FAIL. After map re-enrich with suggested_seeds/hot cards before pack.
- After pack: Native-Read heatmap locs — BAN whole-file Read. expand_context if hop missing.
- Soft browse extras: focus / grep / glob (classic surface).

EXCEPTIONS: exact → grep; filename → glob; known path → host Read; gate/status = health.
Shell = tests/build/git.
"""

SERVER_INSTRUCTIONS_PHASE_LAB_BODY = """\
Lab surface (CTX_MCP_EXPERIMENT=lab): ship ladder PLUS pack_poly_embed / pack_semantic / map_context / pinpoint / plate.
Default locate still map → pack_context(composite lean) → expand_context.
Use poly/semantic packs only when comparing engines; prefer composite for production.
pinpoint/plate are soft-locate extras — do not replace pack heatmap for edit slices.
"""

# Back-compat alias for imports/tests that still reference HYBRID_BODY
SERVER_INSTRUCTIONS_PHASE_HYBRID_BODY = SERVER_INSTRUCTIONS_PHASE_SHIP_BODY


def _phase_server_instructions() -> str:
    header = managed_gate_mcp_header()
    exp = _phase_experiment()
    if exp == "classic":
        tools = (
            "pack_context | map_context | expand_context | collect_hot_context | "
            "map | focus | grep | glob | workspace | expand | gate | status"
        )
        body = SERVER_INSTRUCTIONS_PHASE_CLASSIC_BODY
        label = "classic"
    elif exp == "lab":
        tools = (
            "pack_context | pack_poly_embed | pack_semantic | map_context | expand_context | "
            "collect_hot_context | map | pinpoint | plate | workspace | expand | gate | status"
        )
        body = SERVER_INSTRUCTIONS_PHASE_LAB_BODY + "\n\n" + SERVER_INSTRUCTIONS_PHASE_SHIP_BODY
        label = "lab"
    else:
        tools = (
            "map | pack_context | expand_context | collect_hot_context | "
            "workspace | expand | gate | status"
        )
        body = SERVER_INSTRUCTIONS_PHASE_SHIP_BODY
        label = "ship"
    return (
        f"Scubiee MCP locate ({label}; CTX_MCP_EXPERIMENT={exp}). "
        f"Tools: {tools}.\n"
        + header
        + "\n\n"
        + body
    )


# Default binding for imports/tests that reference SERVER_INSTRUCTIONS_PHASE
SERVER_INSTRUCTIONS_PHASE = _phase_server_instructions()


SERVER_INSTRUCTIONS_PAUSED = """\
Scubiee is STOPPED (user ran scubiee stop). Do NOT call any Scubiee MCP tool.
BAN: pack_context, pack_poly_embed, pack_semantic, map_context, expand_context, collect_hot_context, map, focus, pinpoint, plate, grep, glob, workspace, expand, search, read, files, recall, neighbors, graph, outline.
USE native Read/Grep/Glob/codebase-search only. Shell for tests/build/git is fine.
gate() returns p. Other Scubiee tools return paused:true — do not retry or poll status().
Tell user: scubiee resume (NOT init), then reload MCP in the IDE.
"""

SERVER_INSTRUCTIONS_NAV = """\
Scubiee nav = code locate. Tools: search | files | read | recall | expand | status.
Prefer Scubiee when available (host Grep/Read/Glob secondary). Native OK if Scubiee errors or MCP is blocked.

Pick freely by need:
- soft meaning -> search(mode=soft)
- true literal -> search(mode=exact)
- path/name -> files(pattern)
- open body -> read(target) / expand(handle)
- prior fetches -> recall()
- health -> status() (not for finding code)

Edit when you have enough context. Shell = tests/build/git.
"""

# Spawn-unmanaged recovery (~40 tok) — NOT a truncated SERVER_INSTRUCTIONS_PHASE.
SERVER_INSTRUCTIONS_BIND_FIRST = (
    "Pass root=<workspace> or project_id=ce_… on every call. "
    "Tools: map|pack_context|expand_context|workspace|gate|status. "
    "gate(root=…) first; then locate with the same root/project_id. "
    "After scubiee init in this chat, call gate(root=) again — do not restart the host session."
)


def _is_repo_managed() -> bool:
    """Check if the resolved repository is managed by Scubiee.

    Returns True if the repo has an enrolled project ID and is in the registry as managed.
    """
    try:
        repo = _default_repo()
        bound = _REQUEST_REPO.get()

        # If the resolved repo is the user home or a system root, it's almost
        # certainly a wrong fallback from a global MCP launch — not managed.
        repo_str = str(repo).replace("\\", "/").rstrip("/").lower()
        home_str = str(Path.home()).replace("\\", "/").rstrip("/").lower()
        if repo_str == home_str or repo == repo.parent:
            return False

        from pipeline.project_id import read_id_file, load_registry

        # If explicit request repo is bound (e.g. root=...) check if that explicit repo is enrolled
        if bound is not None and not _is_enrolled(bound):
            return False

        project_id = read_id_file(repo)
        if not project_id:
            return False

        registry = load_registry()
        entry = registry.get("projects", {}).get(project_id)
        if not isinstance(entry, dict):
            return False
        return bool(entry.get("managed", True))
    except Exception:  # noqa: BLE001
        return False


def _registry_has_enrollments() -> bool:
    """True when at least one managed project exists in the registry."""
    try:
        from pipeline.project_id import load_registry

        projects = load_registry().get("projects") or {}
        for entry in projects.values():
            if isinstance(entry, dict) and entry.get("managed", True):
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _locate_bind_hint() -> str:
    if _registry_has_enrollments():
        return (
            "Spawn did not bind a repo. Pass root=<workspace path> or project_id=ce_… "
            "on gate/map/pack_context and every locate call."
        )
    return "Run `scubiee init .` in the project, then pass root=<workspace> on locate calls."


def _env_pin_project_mismatch() -> bool:
    """True when MCP env pins CTX_REPO + CTX_PROJECT_ID that disagree."""
    pin = _ctx_repo_raw()
    pid = (os.environ.get("CTX_PROJECT_ID") or "").strip()
    if pin is None or not pid:
        return False
    from pipeline.project_id import read_id_file

    by_id = _registry_path_for_project_id(pid)
    if by_id is None:
        return False
    enrolled_pin = _enrolled_walk(pin) if _path_exists(pin) else None
    if enrolled_pin is None:
        return True
    try:
        if read_id_file(enrolled_pin) != pid:
            return True
        return enrolled_pin.resolve() != by_id.resolve()
    except OSError:
        return True


def _managed_locate_err(tool: str, repo: Path) -> str:
    if _env_pin_project_mismatch():
        pin = _ctx_repo_raw()
        pid = (os.environ.get("CTX_PROJECT_ID") or "").strip()
        return _err(
            tool,
            f"CTX_REPO ({pin}) does not match CTX_PROJECT_ID ({pid!r}).",
            hint="Run `scubiee connect` in the workspace or fix MCP env pins.",
        )
    return _err(
        tool,
        f"Repository at {repo} is not managed by Scubiee.",
        hint=_locate_bind_hint(),
        next_action=(
            "gate(root=<workspace path>)"
            if _registry_has_enrollments()
            else "scubiee init ."
        ),
    )


def _paused_locate_err(tool: str) -> str:
    """Hard stop when Scubiee is globally paused — agent must not retry locate tools."""
    return _dumps({
        "ok": False,
        "tool": tool,
        "paused": True,
        "gate": "p",
        "error": "Scubiee is stopped (scubiee stop).",
        "should_use_mcp": False,
        "should_retry_status": False,
        "managed": False,
        "next_action": "scubiee resume",
        "hint": (
            "Do not call Scubiee MCP tools while stopped. "
            "Use native Read/Grep/Glob. Tell user: scubiee resume (not init)."
        ),
    })


def _bind_first_instructions(gate: str, *, surface: str) -> str:
    """Spawn-unmanaged — compact bind-first note; full trajectory only when managed."""
    prefix = f"GATE {gate}. "
    if surface == "phase":
        return prefix + SERVER_INSTRUCTIONS_BIND_FIRST
    return (
        prefix
        + "Pass root=<workspace> or project_id=ce_… on every call. "
        "Scubiee locate tools are available after bind."
    )


def _gate_instruction_prefix(gate: str | None = None) -> str:
    g = gate if gate is not None else _gate_line(just_checked=False)
    return f"GATE {g}. "


def _bare_instructions_enabled() -> bool:
    return (os.environ.get("CTX_MCP_BARE_INSTRUCTIONS") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _verbose_instructions_enabled() -> bool:
    """Legacy alias — managed repos now get trajectory by default."""
    return (os.environ.get("CTX_MCP_VERBOSE_INSTRUCTIONS") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _server_instructions(surface: str) -> str:
    """MCP instructions injected every turn.

    - Managed workspace: GATE prefix + full locate trajectory (never truncated).
    - Spawn-unmanaged: compact bind-first note (~40 tok); tools still registered.
    - Init writes prefer+escape rules; trajectory lives here — no duplication.
    """
    gate = _gate_line(just_checked=False)

    if gate == "p":
        return f"GATE p. {SERVER_INSTRUCTIONS_PAUSED}"

    if _bare_instructions_enabled():
        prefix = _gate_instruction_prefix(gate)
        if surface == "phase":
            tools = ",".join(_phase_tool_names())
            tip = (
                "Ladder: map→pack_context(composite lean)→expand_context; path→host Read; exact/name→host Grep/Glob."
                if _phase_experiment() == "ship"
                else (
                    "Use by scenario: soft->pinpoint; how-X-works->plate; cards->map; path->host Read; exact/name->host Grep/Glob."
                    if _phase_experiment() == "lab"
                    else "Use by scenario: map for meaning; grep/glob for literals; focus to edit."
                )
            )
            return prefix + f"Tools: {tools}. {tip}"
        return prefix + "Scubiee MCP tools available — use as you prefer."

    if not _is_repo_managed():
        return _bind_first_instructions(gate, surface=surface)

    prefix = _gate_instruction_prefix(gate)
    body = {
        "graph": SERVER_INSTRUCTIONS_GRAPH,
        "rich": SERVER_INSTRUCTIONS_RICH,
        "search": SERVER_INSTRUCTIONS_SEARCH,
        "grep": SERVER_INSTRUCTIONS_GREP,
        "nav": SERVER_INSTRUCTIONS_NAV,
        "phase": _phase_server_instructions(),
    }.get(surface, SERVER_INSTRUCTIONS_READ)
    return prefix + body


# Back-compat alias (imported by some tests/tools).
SERVER_INSTRUCTIONS = SERVER_INSTRUCTIONS_READ


def _stderr(*args, **kwargs) -> None:
    kwargs.setdefault("file", sys.stderr)
    kwargs.setdefault("flush", True)
    print(*args, **kwargs)


_MCP_CLIENT_ID: str | None = None
_PRELOAD_STARTED = False


def _preload_locate_hot_path() -> None:
    """Import map/search deps off the first tools/call (parallel with engine open)."""
    global _PRELOAD_STARTED
    if _PRELOAD_STARTED:
        return
    _PRELOAD_STARTED = True

    def _run() -> None:
        try:
            import pipeline.context_agent.tools  # noqa: F401
            import pipeline.locate  # noqa: F401
            from pipeline.context_trace import (  # noqa: F401
                finalize_suggested_seed,
                pick_suggested_seed,
                pick_suggested_seeds,
            )
            from pipeline.map_result_cache import get_map_cached  # noqa: F401

            # Do not hydrate AST here — GIL-starves first map. Map kicks bundle
            # hydrate after success so pack finds a warm cache.
        except Exception as exc:  # noqa: BLE001
            _stderr(f"[scubiee] locate preload skipped: {exc}")

    try:
        threading.Thread(target=_run, name="scubiee-locate-preload", daemon=True).start()
    except Exception:  # noqa: BLE001
        _run()


def _register_mcp_client(repo: Path) -> str:
    """Universal attach: leave hooks on any host. Engine warm is agent-first-call."""
    from pipeline.mcp_lifecycle import attach_mcp_session, current_client_id

    global _MCP_CLIENT_ID
    _preload_locate_hot_path()
    out = attach_mcp_session(repo)
    _MCP_CLIENT_ID = str(out.get("client_id") or current_client_id() or "")
    return _MCP_CLIENT_ID


def boot_mcp_worker(repo: Path) -> dict[str, Any]:
    """Stdio worker boot. Default: no engine/watchdog spawn (agent warms later)."""
    from pipeline.mcp_hot_reload import adopt_installed_package_on_connect
    from pipeline.mcp_lifecycle import (
        mcp_auto_warm_on_connect,
        start_locate_worker_prewarm,
    )

    auto = mcp_auto_warm_on_connect()
    report: dict[str, Any] = {"auto_warm": auto}
    try:
        report["adopt"] = adopt_installed_package_on_connect(restart_stale=auto)
    except Exception as exc:  # noqa: BLE001
        report["adopt_error"] = str(exc)
    if auto:
        try:
            from pipeline.daemon import ensure_daemon

            report["ensure"] = ensure_daemon(repo, force_if_hung=False)
        except Exception as exc:  # noqa: BLE001
            report["ensure_error"] = str(exc)
            _stderr(f"[scubiee] ensure_daemon: {exc}")
    report["client_id"] = _register_mcp_client(repo)
    # Critical: prewarm THIS process (imports + soft probe) so first map ≤1s
    # after attach settle — bridge attach alone does not warm the locate worker.
    try:
        report["locate_prewarm"] = start_locate_worker_prewarm(repo)
    except Exception as exc:  # noqa: BLE001
        report["locate_prewarm_error"] = str(exc)
        _stderr(f"[scubiee] locate prewarm kick: {exc}")
    return report


def _touch_mcp_client() -> None:
    """Refresh daemon client liveness on each MCP tool call."""
    from pipeline.mcp_lifecycle import current_client_id

    client_id = current_client_id() or _MCP_CLIENT_ID
    if not client_id:
        return
    try:
        from pipeline.client import EngineClient
        from pipeline.lifecycle_runtime import note_activity, register_client, touch_client

        if touch_client(client_id):
            note_activity()
        else:
            register_client(client_id, pid=os.getpid(), kind="mcp")
        try:
            EngineClient(workspace_path=os.environ.get("CTX_REPO") or None, timeout=1.5).post(
                "/v1/client/touch",
                {"client_id": client_id, "pid": os.getpid(), "kind": "mcp"},
            )
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        pass


_NOTE_LOCATE_LAST_AT = 0.0
_NOTE_LOCATE_LOCK = threading.Lock()
_CLIENT_ADMIT_LOCK = threading.Lock()


def _note_locate_streak(repo: Path | str | None = None) -> None:
    """Tell the keeper an agent locate is in flight — defer sync during the streak.

    Rate-limited: parallel map storms used to stampede /v1/note_locate and
    starve /v1/search on ThreadingHTTPServer.
    """
    global _NOTE_LOCATE_LAST_AT
    with _NOTE_LOCATE_LOCK:
        now = time.time()
        if (now - float(_NOTE_LOCATE_LAST_AT or 0.0)) < 2.0:
            return
        _NOTE_LOCATE_LAST_AT = now
    try:
        from pipeline.client import EngineClient

        root = str(Path(repo).resolve() if repo else _default_repo())
        EngineClient(workspace_path=root, timeout=1.0).note_locate(path=root)
    except Exception:  # noqa: BLE001
        pass


from pipeline.host_workspace import ide_workspace_env_keys

_IDE_WORKSPACE_ENV_KEYS = ide_workspace_env_keys()

_UNEXPANDED_PLACEHOLDER_MARKERS = ("${", "$(", "%{")


def _is_unexpanded_placeholder(raw: str) -> bool:
    """True when a host left ${workspaceFolder} (etc.) unexpanded in env/config."""
    s = (raw or "").strip()
    if not s:
        return True
    return any(m in s for m in _UNEXPANDED_PLACEHOLDER_MARKERS)


def _is_enrolled(path: Path) -> bool:
    try:
        from pipeline.branding import DATA_DIR_NAMES

        return any((path / name / "id.json").is_file() for name in DATA_DIR_NAMES)
    except OSError:
        return False


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _split_workspace_env_hints(raw: str) -> list[str]:
    """Split multi-root env values (e.g. WORKSPACE_FOLDER_PATHS=a,b)."""
    text = (raw or "").strip()
    if not text:
        return []
    if "," not in text and ";" not in text:
        return [text]
    parts: list[str] = []
    for chunk in text.replace(";", ",").split(","):
        piece = chunk.strip().strip('"').strip("'")
        if piece:
            parts.append(piece)
    return parts or [text]


def _ide_workspace_candidates() -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    for key in _IDE_WORKSPACE_ENV_KEYS:
        hint = os.environ.get(key)
        if not hint or _is_unexpanded_placeholder(hint):
            continue
        for piece in _split_workspace_env_hints(hint):
            # VSCODE_CWD=/ is a known useless sentinel on some Cursor builds.
            if piece.strip() in {"/", "\\"}:
                continue
            try:
                candidate = Path(piece).expanduser().resolve()
            except OSError:
                continue
            if not _path_exists(candidate):
                continue
            key_s = str(candidate).replace("\\", "/").lower()
            if key_s in seen:
                continue
            seen.add(key_s)
            found.append(candidate)
    return found

def _enrolled_walk(start: Path) -> Path | None:
    try:
        for candidate in (start, *start.parents):
            if _is_enrolled(candidate):
                return candidate
    except OSError:
        return None
    return None


def _git_root_walk(start: Path) -> Path | None:
    try:
        for candidate in (start, *start.parents):
            if (candidate / ".git").exists():
                return candidate
    except OSError:
        return None
    return None


def _is_home_or_volume_root(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return True
    home = Path.home().resolve()
    a = str(resolved).replace("\\", "/").rstrip("/").lower()
    b = str(home).replace("\\", "/").rstrip("/").lower()
    if a == b:
        return True
    return resolved == resolved.parent


def _looks_like_project_root(path: Path) -> bool:
    if not _path_exists(path) or _is_home_or_volume_root(path):
        return False
    return _is_enrolled(path) or (path / ".git").exists()


def _registry_path_for_project_id(pid: str) -> Path | None:
    """Resolve a project_id via registry live paths (survives folder renames)."""
    if not pid or _is_unexpanded_placeholder(pid):
        return None
    try:
        from pipeline.project_id import load_registry, read_id_file

        entry = (load_registry().get("projects") or {}).get(pid)
        if not isinstance(entry, dict):
            return None
        candidates: list[str] = []
        root = entry.get("root")
        if isinstance(root, str) and root.strip():
            candidates.append(root)
        paths = entry.get("paths")
        if isinstance(paths, list):
            candidates.extend(p for p in paths if isinstance(p, str) and p.strip())
        for raw in candidates:
            try:
                path = Path(raw).resolve()
            except OSError:
                continue
            if not _path_exists(path):
                continue
            if read_id_file(path) == pid or _is_enrolled(path):
                return path
    except Exception:  # noqa: BLE001
        return None
    return None


def _resolve_ctx_project_id() -> Path | None:
    """Resolve CTX_PROJECT_ID via registry live paths (survives folder renames)."""
    pid = (os.environ.get("CTX_PROJECT_ID") or "").strip()
    return _registry_path_for_project_id(pid) if pid else None


_REQUEST_REPO: ContextVar[Path | None] = ContextVar("scubiee_request_repo", default=None)
_LAST_MANAGED_REPO: Path | None = None

_BIND_ROOT_DESC = (
    "This chat's workspace folder (absolute path). Walks up to "
    ".scubiee/id.json. Pass when several repos share one MCP process. Unenrolled "
    "folder → managed false; do not keep calling Scubiee."
)
_BIND_PID_DESC = "Optional enrolled project_id (ce_…). Shorter than root after status()."
_BIND_SESSION_DESC = (
    "Optional chat/session id — isolates recall/pins/handles. "
    "Auto when the host provides one (e.g. CLAUDE_CODE_SESSION_ID, MCP_SESSION_ID) "
    "or the MCP connection differs. Parallel chats that share one MCP process: "
    "pass session_id or set CTX_MCP_SESSION_ID in the host MCP env."
)


def _resolve_session(session_id: str = "") -> str | None:
    from pipeline.session_isolation import resolve_session

    raw = (session_id or "").strip()
    info = resolve_session(raw if raw else None)
    sid = str(info.get("session_id") or "").strip()
    return sid or None


def _session_fields(session_id: str = "") -> dict[str, Any]:
    from pipeline.session_isolation import resolve_session

    return resolve_session((session_id or "").strip() or None)


@contextmanager
def _bind_request_repo(
    *,
    root: str = "",
    project_id: str = "",
    session_id: str = "",
) -> Iterator[Path | None]:
    """Bind this MCP call to repo + session (shared process safe)."""
    from pipeline.session_isolation import bind_request_session, reset_request_session

    resolved = _resolve_request_repo(root=root, project_id=project_id)
    global _LAST_MANAGED_REPO
    if resolved is not None and _is_enrolled(resolved):
        _LAST_MANAGED_REPO = resolved
    repo_token = _REQUEST_REPO.set(resolved) if resolved is not None else None
    sess_token = bind_request_session(session_id) if (session_id or "").strip() else None
    try:
        yield resolved
    finally:
        reset_request_session(sess_token)
        if repo_token is not None:
            _REQUEST_REPO.reset(repo_token)


def _resolve_request_repo(*, root: str = "", project_id: str = "") -> Path | None:
    raw = (root or "").strip()
    pid = (project_id or "").strip()

    # When explicit root is passed, the caller workspace path MUST match or contain the project
    if raw and not _is_unexpanded_placeholder(raw):
        try:
            start = Path(raw).expanduser()
            start = start.resolve() if start.is_absolute() else (Path.cwd() / start).resolve()
        except OSError:
            start = None
        if start is not None and _path_exists(start) and not _is_home_or_volume_root(start):
            enrolled = _enrolled_walk(start)
            if enrolled is not None:
                # If project_id was also specified, verify they match
                if pid:
                    from pipeline.project_id import read_id_file

                    if read_id_file(enrolled) == pid:
                        return enrolled
                    return None
                return enrolled
            git = _git_root_walk(start)
            if git is not None:
                return git
            return start

    if pid:
        found = _registry_path_for_project_id(pid)
        if found is not None:
            # Verify the project_id resolves to an actual enrolled path
            return found

    return None


def _ctx_repo_raw() -> Path | None:
    env = os.environ.get("CTX_REPO") or os.environ.get("CONTEXT_ENGINE_REPO")
    if not env or _is_unexpanded_placeholder(env):
        return None
    try:
        return Path(env).expanduser().resolve()
    except OSError:
        return None


def _ctx_repo_stale(pin: Path | None) -> bool:
    """True when pin is missing, wiped, or no longer a real project dir."""
    if pin is None:
        return False
    if not _path_exists(pin):
        return True
    if _is_enrolled(pin):
        return False
    if (pin / ".git").exists():
        return False
    return True


def _managed_candidates() -> list[dict[str, str]]:
    """Enrolled projects visible from IDE env / cwd / pin (for ambiguous multi-repo)."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    try:
        from pipeline.project_id import read_id_file
    except Exception:  # noqa: BLE001
        return out

    def add(path: Path, source: str) -> None:
        if not _is_enrolled(path):
            return
        key = str(path).replace("\\", "/").lower()
        if key in seen:
            return
        seen.add(key)
        out.append(
            {
                "path": str(path),
                "project_id": read_id_file(path) or "",
                "source": source,
            }
        )

    for candidate in _ide_workspace_candidates():
        add(candidate, "ide")
    add(Path.cwd().resolve(), "cwd")
    walked = _enrolled_walk(Path.cwd().resolve())
    if walked is not None:
        add(walked, "cwd_walk")
    pin = _ctx_repo_raw()
    if pin is not None and not _ctx_repo_stale(pin):
        add(pin, "ctx_repo")
    pid_path = _resolve_ctx_project_id()
    if pid_path is not None:
        add(pid_path, "ctx_project_id")
    return out


def _default_repo() -> Path:
    """Resolve the active repository for this MCP call.

    Per-call bind (root / project_id) wins. A live IDE/cwd *project* folder
    (``.git`` or ``.scubiee/id.json``) beats a process pin so a sidebar chat
    in an unenrolled repo is unmanaged. Pin / ``CTX_PROJECT_ID`` remain the
    fallback when spawn cwd is home and the host gives no workspace.
    """
    bound = _REQUEST_REPO.get()
    if bound is not None:
        return bound

    for candidate in _ide_workspace_candidates():
        if _is_enrolled(candidate):
            return candidate

    for candidate in _ide_workspace_candidates():
        if _looks_like_project_root(candidate):
            return candidate

    pin = _ctx_repo_raw()
    pid_env = (os.environ.get("CTX_PROJECT_ID") or "").strip()
    if pin is not None and pid_env:
        if _env_pin_project_mismatch():
            return pin
        enrolled_pin = _enrolled_walk(pin) if _path_exists(pin) else None
        if enrolled_pin is not None:
            return enrolled_pin.resolve()

    walked = _enrolled_walk(Path.cwd().resolve())
    if walked is not None:
        return walked

    cwd = Path.cwd().resolve()
    if _looks_like_project_root(cwd):
        return cwd

    if not (pin is not None and pid_env):
        by_id = _resolve_ctx_project_id()
        if by_id is not None:
            return by_id

    if pin is not None and not _ctx_repo_stale(pin):
        return pin

    for candidate in _ide_workspace_candidates():
        if (candidate / ".git").exists():
            return candidate

    if pin is not None and _path_exists(pin):
        return pin

    global _LAST_MANAGED_REPO
    if _LAST_MANAGED_REPO is not None and _is_enrolled(_LAST_MANAGED_REPO):
        return _LAST_MANAGED_REPO

    for item in _managed_candidates():
        try:
            candidate = Path(item["path"]).resolve()
        except OSError:
            continue
        if _is_enrolled(candidate):
            return candidate

    if _is_home_or_volume_root(cwd) or not _is_enrolled(cwd):
        if pin is not None and _path_exists(pin):
            return pin

    return cwd


def _dumps(obj: Any) -> str:
    """Compact JSON for MCP tool results — same data, no pretty-print tax."""
    from pipeline.mcp_response_lean import apply_lean_fields

    if isinstance(obj, dict):
        obj = apply_lean_fields(obj)
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _status_ttl_s() -> int:
    """How long a status() result stays fresh (seconds). Default 5 minutes."""
    raw = (os.environ.get("CTX_STATUS_TTL_S") or "").strip()
    if raw.isdigit():
        return max(60, min(int(raw), 3600))
    return 300


_LAST_STATUS_MONO: float | None = None


def _invalidate_status_ttl() -> None:
    """Forget cached status freshness so agents re-check after transport flaps."""
    global _LAST_STATUS_MONO
    _LAST_STATUS_MONO = None


def _managed_signal_fields(*, just_checked: bool = False) -> dict[str, Any]:
    """Fields agents use to decide whether to keep / retry Scubiee MCP.

    ``status()`` passes ``just_checked=True`` so we never ask for an immediate
    retry (avoids loops). Locate tools pass the default: retry only if status
    was never called on this MCP process, or the TTL elapsed.
    Recheck on a new chat (agent calls status at start), after the TTL, or
    when the user asks — not every turn.
    """
    global _LAST_STATUS_MONO
    now = time.monotonic()
    ttl = _status_ttl_s()
    if just_checked:
        _LAST_STATUS_MONO = now
        age = 0.0
        retry = False
    elif _LAST_STATUS_MONO is None:
        age = None
        retry = True
    else:
        age = now - _LAST_STATUS_MONO
        retry = age >= ttl

    managed = _is_repo_managed()
    pin = _ctx_repo_raw()
    stale = _ctx_repo_stale(pin)
    candidates = _managed_candidates()
    fields: dict[str, Any] = {
        "managed": managed,
        "should_use_mcp": managed,
        "should_retry_status": retry,
        "status_ttl_s": ttl,
        "status_age_s": None if age is None else round(age, 1),
        "stale_ctx_repo": stale,
    }
    if stale and pin is not None:
        fields["stale_ctx_repo_path"] = str(pin)
    if len(candidates) > 1:
        fields["ambiguous_repos"] = True
        fields["candidates"] = candidates
    if not managed:
        if _registry_has_enrollments():
            fields["hint"] = _locate_bind_hint()
        else:
            fields["hint"] = (
                "Repo is not managed. Run `scubiee init .`, then pass root=<workspace> "
                "on locate calls. Recheck gate() at a new chat or after status_ttl_s."
            )
    return fields


def _paused_gate_response() -> str:
    """Compact gate/status line when globally stopped."""
    return (
        "p\n"
        "STOPPED — BAN Scubiee locate tools. Native Read/Grep/Glob only. "
        "User: scubiee resume (not init)."
    )


def _gate_line(*, just_checked: bool = False) -> str:
    """Ultra-compact managed signal (~1–8 tokens). No daemon / session I/O.

    Formats:
      ``0``     — not managed (use native tools; do not poll)
      ``0:r``   — not managed; ``status_ttl_s`` elapsed — call ``gate()`` once
      ``1:ce_…`` — managed; reuse ``ce_…`` as ``project_id`` on locate tools
      ``p``     — Scubiee stopped; BAN locate tools; native Read/Grep/Glob only
    """
    try:
        from pipeline.pause_resume import is_paused

        if is_paused():
            return "p"
    except Exception:  # noqa: BLE001
        pass
    fields = _managed_signal_fields(just_checked=just_checked)
    if not fields["managed"]:
        return "0:r" if fields["should_retry_status"] else "0"
    pid = ""
    try:
        from pipeline.project_id import read_id_file

        pid = read_id_file(_default_repo()) or ""
    except Exception:  # noqa: BLE001
        pid = ""
    return f"1:{pid}" if pid else "1"


def _slim_status_keeper(keeper: dict[str, Any] | None, *, file_cap: int = 25) -> dict[str, Any] | None:
    """Trim verbose keeper payloads for MCP status() responses."""
    if not isinstance(keeper, dict):
        return keeper
    out = dict(keeper)
    ls = out.get("last_sync")
    if isinstance(ls, dict):
        ls = dict(ls)
        files = ls.get("files")
        if isinstance(files, list) and len(files) > file_cap:
            ls["files"] = files[:file_cap]
            ls["files_truncated"] = len(files)
        out["last_sync"] = ls
    dirty = out.get("dirty")
    if isinstance(dirty, dict):
        dirty = dict(dirty)
        paths = dirty.get("paths")
        if isinstance(paths, dict) and len(paths) > 40:
            items = list(paths.items())[:40]
            dirty["paths"] = dict(items)
            dirty["paths_truncated"] = len(paths)
        out["dirty"] = dirty
    return out


_STATUS_SUMMARY_KEYS = (
    "ok",
    "tool",
    "server",
    "surface",
    "paused",
    "managed",
    "should_use_mcp",
    "should_retry_status",
    "warming",
    "agent_ready",
    "agent_ready_note",
    "warm_ready",
    "warm_ready_map",
    "warm_phase",
    "warm_elapsed_ms",
    "embedder_loaded",
    "semantic_ready",
    "sync_state",
    "ready",
    "syncing",
    "overlay_ready",
    "needs_full",
    "error",
    "hint",
    "next_action",
    "lifecycle_hint",
    "index_available",
    "token_mode",
    "repo",
    "g",
    "tools",
    "status_ttl_s",
    "status_age_s",
    "stale_ctx_repo",
)


def _summarize_status_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Agent-facing status: action fields only. detail=full keeps keeper/meta."""
    if not isinstance(payload, dict):
        return payload
    out: dict[str, Any] = {k: payload[k] for k in _STATUS_SUMMARY_KEYS if k in payload}
    eng = payload.get("engine")
    if isinstance(eng, dict):
        slim_eng = {
            k: eng.get(k)
            for k in (
                "healthy",
                "soft_search_ready",
                "warm_state",
                "warm_error",
                "project_id",
                "embedder_loaded",
            )
            if k in eng
        }
        if slim_eng:
            out["engine"] = slim_eng
    sess = payload.get("session")
    if isinstance(sess, dict):
        sid = sess.get("session_id")
        if sid and "session_id" not in out:
            out["session_id"] = sid
        if sess.get("shared_process_risk"):
            out["session_shared_risk"] = True
        if sess.get("source"):
            out.setdefault("session_source", sess.get("source"))
        if "n_spans" in sess:
            out["n_spans"] = sess["n_spans"]
    lc = payload.get("lifecycle")
    if isinstance(lc, dict):
        if lc.get("state") is not None:
            out["lifecycle_state"] = lc.get("state")
    return out


def _annotate_locate_dedup(card: dict[str, Any]) -> dict[str, Any]:
    """Soft note only — never blank bodies or hard-stop locate (token thrash)."""
    if not isinstance(card, dict):
        return card
    if card.get("unchanged") or card.get("status") == "already_in_session":
        # Advisory: content was seen before, but ``code``/``text`` should still be present.
        card.pop("stop_locate", None)
        card.pop("locate_action", None)
    return card


def _err(tool: str, error: str, *, hint: str = "", **extra: Any) -> str:
    payload: dict[str, Any] = {"ok": False, "tool": tool, "error": error, **extra}
    if _is_transient_engine_error(error):
        payload.setdefault("should_retry", True)
        hint = hint or "Transient engine drop — retry the same call once immediately."
    # Surface managed/retry signals on errors so agents can re-check after init.
    for key, value in _managed_signal_fields().items():
        payload.setdefault(key, value)
    if hint:
        payload["hint"] = hint
    return _dumps(_attach_gate(payload))


def _parse_card_loc_span(card: dict[str, Any]) -> tuple[str, int, int] | None:
    """file, start_line, end_line from a heatmap card (no AST)."""
    file_s = str(card.get("file") or "").replace("\\", "/").strip()
    start = int(card.get("start_line") or 0)
    end = int(card.get("end_line") or 0)
    if file_s and start > 0:
        return file_s, start, end if end >= start else start
    loc = str(card.get("loc") or "").replace("\\", "/").strip()
    if not loc:
        return None
    # file:12-34 or file:12
    if ":" not in loc:
        return (loc, 1, 80) if loc else None
    path_part, _, rest = loc.rpartition(":")
    if not path_part:
        return None
    if "-" in rest:
        a, _, b = rest.partition("-")
        try:
            return path_part, int(a), int(b)
        except ValueError:
            return None
    if rest.isdigit():
        ln = int(rest)
        return path_part, ln, ln + 40
    return None


def _collect_hot_from_card_locs(
    repo: Path,
    cards: list[dict[str, Any]],
    *,
    threshold: float,
    max_chars: int,
    skip_ids: set[str],
    only_ids: set[str] | None,
    prefer_ids: set[str] | None,
    max_bodies: int = 8,
) -> dict[str, Any]:
    """Fill bodies from card loc spans via file read — no AST pickle load."""
    prefer = {str(x) for x in (prefer_ids or set()) if x}
    if only_ids:
        by_id = {str(c.get("id") or ""): c for c in cards if c.get("id")}
        picked = [by_id[oid] for oid in only_ids if oid in by_id]
        # Synthesize minimal cards for only_ids that look like file::symbol with loc missing
        for oid in only_ids:
            if oid in by_id:
                continue
            if "::" in oid:
                f, _, _sym = oid.partition("::")
                picked.append({"id": oid, "file": f, "loc": f, "score": 0.9})
    else:
        picked = [c for c in cards if float(c.get("score") or 0) >= threshold]
    picked.sort(
        key=lambda c: (
            0 if str(c.get("id") or "") in prefer else 1,
            -float(c.get("score") or 0),
        )
    )
    bodies: list[dict[str, Any]] = []
    used = 0
    root = Path(repo)
    for c in picked:
        if len(bodies) >= max_bodies:
            break
        cid = str(c.get("id") or "")
        if cid and cid in skip_ids and cid not in prefer:
            continue
        span = _parse_card_loc_span(c)
        if not span:
            continue
        file_s, start, end = span
        path = root / file_s
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:  # noqa: BLE001
            continue
        if start < 1:
            start = 1
        if end < start:
            end = min(len(lines), start + 80)
        end = min(len(lines), max(end, start))
        text = "\n".join(lines[start - 1 : end])
        if not text:
            continue
        if used + len(text) > max_chars:
            remain = max_chars - used
            if remain < 200:
                break
            text = text[: remain - 1] + "…"
        bodies.append(
            {
                "id": cid or f"{file_s}::{start}",
                "file": file_s,
                "symbol": c.get("symbol") or "",
                "start_line": start,
                "end_line": end,
                "loc": c.get("loc") or f"{file_s}:{start}-{end}",
                "score": c.get("score"),
                "heat": c.get("heat"),
                "why": c.get("why") or "card_loc_span",
                "text": text,
            }
        )
        used += len(text)
    return {
        "ok": True,
        "tool": "collect_hot_context",
        "bodies": bodies,
        "count": len(bodies),
        "engine": "card_loc_span",
        "next": "Native-Read if more body needed; expand_context for graph neighbors.",
    }


_SUCCESS_BACKEND_STATUSES = {
    "ok",
    "ready",
    "active",
    "activated",
    "success",
    "complete",
    "completed",
    "idle",
    "registered",
    "indexed",
    "published",
}


def _backend_failed(response: Any, *, require_ok: bool = True) -> bool:
    """Detect explicit and implicit daemon failures.

    The daemon can return transient states such as ``warming`` without an
    ``ok`` field. Data-bearing HTTP endpoints otherwise guarantee ``ok:true``
    on success, so a missing success marker is treated as a failed response.
    """
    if not isinstance(response, dict):
        return require_ok
    if require_ok and response.get("ok") is not True:
        return True
    if response.get("ok") is False or response.get("error"):
        return True
    if response.get("ready") is False:
        return True
    status = str(response.get("status") or "").strip().lower()
    return bool(status and status not in _SUCCESS_BACKEND_STATUSES)


def _backend_error(
    tool: str,
    repo: Path,
    response: Any,
    *,
    hint: str,
    require_ok: bool = True,
) -> str | None:
    """Preserve daemon admission/readiness failures instead of empty results."""
    if response is None:
        return None
    if not isinstance(response, dict):
        return _err(tool, "invalid Scubiee response", hint=hint, repo=str(repo))
    if not _backend_failed(response, require_ok=require_ok):
        return None

    status = str(response.get("status") or "").strip()
    error = str(
        response.get("error")
        or status
        or ("Scubiee is not ready" if response.get("ready") is False else "Scubiee request failed")
    )
    if status == "requires_initialize" or error == "requires_initialize":
        hint = f"Run: scubiee init {repo} and then reload/reconnect the MCP server."
    elif status == "paused" or error == "paused":
        hint = "Run: scubiee activate . (per-repo pause — not the same as scubiee stop)."
    elif status == "needs_registration":
        hint = f"Register this workspace first: scubiee register {repo}."
    elif str(response.get("warm_state") or "").lower() == "error" or status == "error":
        hint = "Scubiee warm_state=error — run: scubiee setup (or scubiee doctor), not status polling."
        error = str(response.get("warm_error") or error or "warm_state_error")
        status = "error"
    elif status in {"warming", "starting", "loading", "syncing", "initializing", "not_ready"} or error == "engine_warming":
        hint = (
            "Engine is warming. Wait ~3s and retry this same tool once. "
            "Do not poll status() in a loop."
        )

    if _is_transient_engine_error(error) or "unreachable" in error.lower() or "10061" in error:
        _invalidate_status_ttl()

    extra: dict[str, Any] = {"repo": str(repo)}
    if _is_transient_engine_error(error) or error == "engine_warming" or status in {
        "warming",
        "starting",
        "loading",
        "indexing",
        "not_ready",
    }:
        extra["should_retry"] = True
        extra["warming"] = True
        extra["retry_after_s"] = int(response.get("retry_after_s") or 3)
        extra["agent_ready"] = "no"
        hint = hint or (
            "Engine is warming. Wait ~3s and retry this same tool once. "
            "Do not poll status() in a loop."
        )
    if _is_transient_engine_error(error):
        extra["should_retry"] = True
        hint = hint or "Transient engine drop — retry the same call once immediately."
    if status == "error" or str(response.get("warm_state") or "").lower() == "error":
        extra["should_retry"] = False
        extra["non_retryable"] = True
        extra["locate"] = {
            "state": "error",
            "reason": error,
            "repair": ["scubiee setup", "scubiee doctor"],
            "should_use": False,
            "should_retry": False,
        }
    for key in (
        "status",
        "state",
        "ready",
        "warm_state",
        "sync_state",
        "sync_status",
        "http_status",
        "root",
        "project_id",
        "pause_reason",
        "warming",
        "should_retry",
        "retry_after_s",
        "agent_ready",
    ):
        if response.get(key) is not None:
            extra[key] = response[key]
    if status:
        extra["status"] = status
    return _err(tool, error, hint=hint, **extra)


def _norm_query(query: str) -> str:
    return " ".join((query or "").lower().split())


_MAP_STOPWORDS = frozenset({
    "the", "a", "an", "where", "how", "what", "when", "is", "are", "in", "for", "to", "of", "and", "or",
})

# Live map scores from Conductor RRF land ~1–35; gibberish tops out ~2–3.
_MAP_SCORE_LOW = 5.0
_MAP_SCORE_MEDIUM = 8.0


def _strip_bom_text(text: str) -> str:
    return (text or "").lstrip("\ufeff")


def _is_transient_engine_error(error: str) -> bool:
    from pipeline.client import is_transient_engine_error

    low = (error or "").lower()
    if "engine_warming" in low or low == "warming":
        return True
    return is_transient_engine_error(error)


def _assess_map_confidence(query: str, cards: list[dict[str, Any]]) -> dict[str, Any]:
    if not cards:
        return {"confidence": "none", "max_score": 0.0}
    scores = [float(c.get("score") or 0.0) for c in cards]
    max_score = max(scores) if scores else 0.0
    tokens = [
        t for t in _norm_query(query).split()
        if len(t) > 3 and t not in _MAP_STOPWORDS
    ]
    top_paths = " ".join(str(c.get("file") or "") for c in cards[:5]).lower()
    token_hits = sum(1 for t in tokens if t in top_paths)
    if max_score < _MAP_SCORE_LOW or (
        len(tokens) >= 3 and token_hits == 0 and max_score < _MAP_SCORE_MEDIUM
    ):
        return {"confidence": "low", "max_score": round(max_score, 4), "weak_match": True}
    if max_score < _MAP_SCORE_MEDIUM:
        return {"confidence": "medium", "max_score": round(max_score, 4)}
    return {"confidence": "high", "max_score": round(max_score, 4)}


def _map_cache_get(store: dict[str, Any], qn: str, k: int) -> list[dict[str, Any]] | None:
    entry = (store.get("map_cache") or {}).get(qn)
    if not isinstance(entry, dict):
        return None
    # Accept cache when prior map had ≥k cards (or any non-empty set).
    cached_k = int(entry.get("k") or 0)
    if cached_k and cached_k < int(k):
        return None
    cards = entry.get("cards")
    return cards if isinstance(cards, list) and cards else None


def _map_cache_put(
    repo: Path,
    qn: str,
    k: int,
    cards: list[dict[str, Any]],
    *,
    session_id: str | None = None,
) -> None:
    from pipeline.session_store import load_store, save_store

    store = load_store(repo, session_id=session_id)
    cache = store.setdefault("map_cache", {})
    cache[qn] = {"k": k, "cards": cards, "ts": time.time()}
    if len(cache) > 40:
        oldest = sorted(cache.items(), key=lambda kv: float((kv[1] or {}).get("ts") or 0))[: len(cache) - 40]
        for key, _ in oldest:
            cache.pop(key, None)
    save_store(repo, store, session_id=session_id)


def _record_locate_query(
    repo: Path,
    mode: str,
    query: str,
    *,
    session_id: str | None = None,
) -> str | None:
    """Track locate queries for workspace(show). Never return coaching prose."""
    surface = _active_surface()
    if surface not in {"nav", "search", "phase"}:
        return None
    from pipeline.session_store import load_store, save_store

    store = load_store(repo, session_id=session_id)
    thrash = store.setdefault("locate_thrash", {"soft": [], "exact": [], "seen": []})
    qn = _norm_query(query)
    duplicate = qn in (thrash.get("seen") or [])
    if mode == "exact":
        thrash.setdefault("exact", []).append(qn)
    else:
        thrash.setdefault("soft", []).append(qn)
    thrash.setdefault("seen", []).append(qn)
    save_store(repo, store, session_id=session_id)
    # Duplicate tracking is enough; per-call usage_hint burned tokens in long sessions.
    _ = duplicate
    return None


def _focus_key(target: str, mode: str, path: str = "") -> str:
    t = (path or target or "").replace("\\", "/").strip().lower()
    return f"{mode}:{t}"


def _phase_focus_remember(
    repo: Path,
    key: str,
    card: dict[str, Any],
    *,
    session_id: str | None = None,
) -> None:
    if _active_surface() != "phase":
        return
    from pipeline.session_store import load_store, save_store

    store = load_store(repo, session_id=session_id)
    seen = store.setdefault("focus_seen", {})
    seen[key] = {
        "file": card.get("file") or card.get("path"),
        "mode": card.get("mode") or card.get("detail"),
        "handle": card.get("handle"),
        "start_line": card.get("start_line"),
        "end_line": card.get("end_line"),
        "status": card.get("status"),
    }
    # Cap
    if len(seen) > 80:
        for old in list(seen.keys())[: len(seen) - 80]:
            seen.pop(old, None)
    save_store(repo, store, session_id=session_id)

def _looks_like_path(s: str) -> bool:
    s = (s or "").strip()
    if not s or " " in s:
        return False
    return "/" in s or s.endswith(
        (".py", ".ts", ".tsx", ".js", ".md", ".json", ".toml", ".cfg", ".txt")
    )


def _slim_spans(spans: list[dict[str, Any]], *, keep: int, body_chars: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for s in (spans or [])[:keep]:
        out.append(
            {
                "file": s.get("path") or s.get("file"),
                "start_line": s.get("start_line"),
                "end_line": s.get("end_line"),
                "why": (s.get("why") or s.get("label") or "")[:120],
                "code": _strip_bom_text(
                    (s.get("text") or s.get("excerpt") or s.get("code") or "")[:body_chars]
                ),
            }
        )
    return out


def _slim_grep(hits: Any, *, keep: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for h in (hits if isinstance(hits, list) else [])[:keep]:
        if isinstance(h, dict):
            out.append(
                {
                    "file": h.get("file") or h.get("path"),
                    "line": h.get("line") or h.get("start_line"),
                    "text": (h.get("text") or h.get("preview") or "")[:160],
                }
            )
    return out


_OUTLINE_KEEP_DEFAULT = 60
_BUDGET_MAX_LINES = {"cap": 200, "wide": 350, "full": 1_000}
_BUDGET_MAX_CHARS = {"cap": 50_000, "wide": 100_000, "full": 500_000}
_BUDGET_DEFAULT_CHARS = {"cap": 50_000, "wide": 100_000, "full": 500_000}
_FOCUS_CHAR_CEILING = _BUDGET_MAX_CHARS["full"]
_FOCUS_OVERLAP_MIN_LINES = 20


def _normalize_budget(budget: str | None) -> str:
    val = (budget or "cap").strip().lower()
    return val if val in _BUDGET_MAX_LINES else "cap"


def _budget_limits(
    budget: str | None,
    *,
    max_chars: int,
    default_max_chars: int,
) -> tuple[int, int]:
    """Return (max_chars, max_lines) for a read/focus budget."""
    mode = _normalize_budget(budget)
    cap_chars = _BUDGET_MAX_CHARS[mode]
    if max_chars and max_chars != default_max_chars:
        cap_chars = min(max(max_chars, 200), _BUDGET_MAX_CHARS["full"])
    return cap_chars, _BUDGET_MAX_LINES[mode]


def _line_ranges_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    if a_start <= 0 or a_end <= 0 or b_start <= 0 or b_end <= 0:
        return False
    lo = max(a_start, b_start)
    hi = min(a_end, b_end)
    return hi - lo + 1 >= _FOCUS_OVERLAP_MIN_LINES


def _check_focus_overlap(
    repo: Path | str,
    path: str,
    start: int,
    end: int,
    *,
    session_id: str | None = None,
    budget: str | None = None,
) -> dict[str, Any] | None:
    """Overlap hard-block removed — always rematerialize via normal focus/read.

    Prior versions returned an empty already_in_session stub that forced agents
    into expand() loops and wasted tokens. Kept as a no-op for call-site compat.
    """
    return None


def _slim_outline(
    symbols: Any,
    *,
    keep: int = _OUTLINE_KEEP_DEFAULT,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int, bool]:
    raw = symbols if isinstance(symbols, list) else []
    total = len(raw)
    start = max(0, int(offset or 0))
    window = raw[start : start + keep]
    out: list[dict[str, Any]] = []
    for s in window:
        if isinstance(s, dict):
            out.append(
                {
                    "name": s.get("name") or s.get("symbol") or s.get("label"),
                    "kind": s.get("kind") or s.get("type"),
                    "start_line": s.get("start_line") or s.get("line"),
                    "end_line": s.get("end_line"),
                }
            )
        else:
            out.append({"name": str(s)})
    capped = start + len(window) < total
    return out, total, capped


# Dirs we never descend into when finding files — heavy, generated, or vendored.
_FILES_IGNORE_DIRS = {
    ".git", ".venv", ".venv-proof", "__pycache__", "node_modules", "out",
    "graphify-out", ".scubiee", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "dist", "build", ".cursor", "research", "testdata",
    ".worktrees",
}


def _is_ignored_repo_dir(name: str) -> bool:
    if name in _FILES_IGNORE_DIRS or name.startswith("."):
        return True
    return name.startswith("scubiee-0.")


def _explicit_dot_dirs_in_pattern(pattern: str) -> set[str]:
    """Dot-directory names explicitly named in a glob (e.g. ``.scubiee/**``)."""
    out: set[str] = set()
    for part in (pattern or "").replace("\\", "/").split("/"):
        if part.startswith(".") and part not in {".", ".."}:
            head = part.split("*", 1)[0].split("{", 1)[0].split("[", 1)[0]
            if head:
                out.add(head)
    return out


def _should_skip_walk_dir(name: str, pattern: str) -> bool:
    if name in _explicit_dot_dirs_in_pattern(pattern):
        return False
    return _is_ignored_repo_dir(name)


def _parse_call_sites_symbol(
    *, query: str, target: str, path: str
) -> tuple[str, str]:
    """Return ``(ident, optional_scope_path)`` from focus call_sites args."""
    sym_src = (query or "").strip()
    scope = (path or "").replace("\\", "/").strip()
    tgt = (target or "").strip()
    if not sym_src and tgt:
        if ":" in tgt:
            head, _, tail = tgt.rpartition(":")
            if tail and not tail.isdigit():
                sym_src = tail
                head_n = head.replace("\\", "/")
                if not scope and ("/" in head_n or head_n.endswith(".py")):
                    scope = head_n
            else:
                sym_src = tgt
        else:
            sym_src = tgt
    ident = _normalize_symbol_query(sym_src or scope)
    if ident and "." in ident and not ident.endswith(".py"):
        ident = ident.split(".")[-1]
    return ident, scope


def _call_sites_for_ident(
    repo: Path,
    ident: str,
    *,
    keep: int = 4,
    body_chars: int = 400,
    scope_path: str = "",
) -> list[dict[str, Any]]:
    """Find Python call sites for ``ident`` (not definitions)."""
    import re

    from pipeline.capability import grep_scan

    if not ident:
        return []
    glob_pat = "**/*.py"
    scope_n = (scope_path or "").replace("\\", "/").strip()
    if scope_n:
        glob_pat = scope_n if scope_n.endswith(".py") else f"{scope_n.rstrip('/')}/**/*.py"
    pattern = rf"\b{re.escape(ident)}\s*\("
    def_re = re.compile(rf"^\s*(async\s+def|def|class)\s+{re.escape(ident)}\b")
    report = grep_scan(repo, pattern, glob=glob_pat, max_hits=max(keep * 6, 24))
    sites: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for h in report.get("hits") or []:
        rel = str(h.get("file") or h.get("path") or "").replace("\\", "/")
        line = int(h.get("line") or 0)
        text = str(h.get("text") or "")
        if not rel or not line or def_re.search(text):
            continue
        key = (rel, line)
        if key in seen:
            continue
        seen.add(key)
        block = _read_line_range(repo, rel, max(1, line - 2), line + 8, body_chars)
        sites.append(
            {
                "file": rel,
                "start_line": block.get("start_line") or line,
                "end_line": block.get("end_line") or line,
                "why": "call",
                "code": block.get("excerpt") or text,
                "line": line,
            }
        )
        if len(sites) >= keep:
            break
    return sites


def _normalize_symbol_query(q: str) -> str:
    t = (q or "").strip()
    for prefix in ("async def ", "def ", "class "):
        if t.lower().startswith(prefix):
            t = t[len(prefix) :].strip()
    return t.split("(")[0].strip()


def _looks_like_symbol_query(q: str) -> bool:
    """True when query is a single identifier (def/class name), not a phrase."""
    import re

    t = _normalize_symbol_query(q)
    if not t or " " in t:
        return False
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$", t))


def _outline_symbols(repo: Path, path_n: str) -> list[dict[str, Any]]:
    from pipeline.capability import file_outline

    return file_outline(repo, path_n.replace("\\", "/"))


def _resolve_symbol_lines(repo: Path, path_n: str, symbol_query: str) -> tuple[int, int] | None:
    """Match outline symbol to line range (Class.method, def name, etc.)."""
    q = _normalize_symbol_query(symbol_query)
    if not q:
        return None
    symbols = _outline_symbols(repo, path_n)
    if not symbols:
        return None
    q_l = q.lower()
    q_tail = q_l.split(".")[-1]
    candidates: list[tuple[int, int, int, str]] = []
    for s in symbols:
        sym = str(s.get("symbol") or s.get("name") or "")
        kind = str(s.get("kind") or "")
        line = int(s.get("line") or s.get("start_line") or 0)
        end = int(s.get("end_line") or line)
        if not line:
            continue
        sym_l = sym.lower()
        score = 0
        if sym_l == q_l:
            score = 20
        elif sym_l.endswith("." + q_tail) or sym_l == q_tail:
            score = 15 if kind in {"method", "function"} else 10
        if score:
            if kind in {"method", "function"}:
                score += 2
            candidates.append((score, line, end, sym))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    _, line, end, _ = candidates[0]
    return line, end


def _resolve_auto_end_line(
    repo: Path,
    path_n: str,
    start_line: int,
    file_lines: int,
    *,
    max_lines: int | None = None,
) -> int:
    """When end_line omitted: symbol body or capped window (not +40 only)."""
    line_cap = max_lines if max_lines is not None else _BUDGET_MAX_LINES["cap"]
    symbols = _outline_symbols(repo, path_n)
    s = max(1, int(start_line))
    for sym in symbols:
        line = int(sym.get("line") or sym.get("start_line") or 0)
        end = int(sym.get("end_line") or line)
        if line <= s <= end:
            return min(end, s + line_cap - 1, file_lines)
    for sym in symbols:
        line = int(sym.get("line") or sym.get("start_line") or 0)
        if line > s:
            return min(line - 1, s + line_cap - 1, file_lines)
    return min(s + line_cap - 1, file_lines)


def _read_line_range(
    repo: Path,
    path: str,
    start: int,
    end: int,
    max_chars: int,
    *,
    max_lines: int | None = None,
    budget: str | None = None,
) -> dict[str, Any]:
    """Read an exact line range straight from the file (no index needed)."""
    from pipeline.capability import truncation_meta

    fp = repo / path
    if not fp.is_file():
        return {
            "excerpt": "",
            "start_line": start,
            "end_line": end,
            "error": f"file not found: {path}",
            "truncated": False,
            "ok": False,
        }
    lines = fp.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    n = len(lines)
    s = max(1, int(start or 1))
    mode = _normalize_budget(budget)
    if mode == "full" and (not end or int(end) < s):
        e = n
    elif end and int(end) >= s:
        e = min(int(end), n)
    else:
        e = _resolve_auto_end_line(repo, path, s, n, max_lines=max_lines)
    wanted_e = e
    if max_lines is not None and e - s + 1 > max_lines:
        e = min(s + max_lines - 1, n)
    e = min(max(e, s), n)
    line_truncated = wanted_e > e
    full_text = _strip_bom_text("\n".join(lines[s - 1 : e]))
    char_truncated = len(full_text) > max_chars
    text = full_text[:max_chars] if char_truncated else full_text
    meta = truncation_meta(
        full_text,
        start_line=s,
        end_line=e,
        lines_total=n,
        max_chars=max_chars,
        path=path.replace("\\", "/"),
        budget=mode,
        line_truncated=line_truncated,
    )
    out = {
        "excerpt": text,
        "start_line": s,
        "end_line": e,
        "ok": True,
        "budget": mode,
        **meta,
    }
    return out


def _orient_repo(repo: Path, limit: int = 40) -> dict[str, Any]:
    """Shallow repo shape for files('.') — dirs + a few top-level files."""
    dirs: list[str] = []
    files: list[str] = []
    try:
        for child in sorted(repo.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            name = child.name
            if name in _FILES_IGNORE_DIRS or name.startswith("."):
                continue
            if child.is_dir():
                dirs.append(name + "/")
            elif child.is_file():
                files.append(name)
            if len(dirs) + len(files) >= limit:
                break
    except Exception:  # noqa: BLE001
        pass
    return {"dirs": dirs, "files": files}


def _find_repo_files(repo: Path, pattern: str, limit: int) -> tuple[list[str], bool]:
    """Find files by name or glob. Returns (relative_posix_paths, truncated).

    Collects all matches, then sorts and slices — truncated means more matched
    than ``limit`` (do not treat count=0 as absence when truncated).
    ``**`` matches across directories.
    """
    import os as _os

    from pipeline.capability import path_glob_match

    patt = (pattern or "").strip().replace("\\", "/")
    lo = patt.lower()
    has_magic = any(ch in patt for ch in "*?[{}")
    path_like = "/" in patt
    cap = max(1, int(limit or 200))

    if not has_magic:
        candidate = repo / patt
        if candidate.is_file():
            return [candidate.relative_to(repo).as_posix()], False

    if not has_magic and path_like:
        candidate = repo / patt
        if candidate.is_file():
            return [patt.lstrip("./")], False

    # Directory listing: packages/* → immediate children (dirs + files)
    if has_magic and patt.endswith("/*") and "**" not in patt and "?" not in patt and "{" not in patt:
        parent = patt[:-2].rstrip("/")
        parent_path = repo / parent if parent else repo
        if parent_path.is_dir():
            entries: list[str] = []
            try:
                for child in sorted(parent_path.iterdir(), key=lambda p: p.name.lower()):
                    name = child.name
                    if _should_skip_walk_dir(name, patt):
                        continue
                    rel = f"{parent}/{name}" if parent else name
                    if child.is_dir():
                        entries.append(rel + "/")
                    elif child.is_file():
                        entries.append(rel)
            except OSError:
                entries = []
            truncated = len(entries) > cap
            return entries[:cap], truncated

    matched: list[str] = []
    for root, dirs, files in _os.walk(repo):
        dirs[:] = [
            d for d in dirs
            if not _should_skip_walk_dir(d, patt)
            and not d.startswith(".sim-ce-home")
            and not d.endswith(".egg-info")
        ]
        for fn in files:
            rel = (Path(root) / fn).relative_to(repo).as_posix()
            if has_magic or path_like:
                ok = path_glob_match(rel, patt)
            else:
                ok = lo in fn.lower()
            if ok:
                matched.append(rel)

    matched.sort(key=lambda p: (p.count("/"), len(p), p))
    truncated = len(matched) > cap
    return matched[:cap], truncated


def _resolve_to_file(repo: Path, target: str) -> str:
    """Best-effort: a path stays a path; a symbol/phrase resolves via search."""
    t = (target or "").strip()
    if not t:
        return ""
    if _looks_like_path(t):
        return t.replace("\\", "/")
    try:
        from pipeline.locate import _search_hits

        hits = _search_hits(repo, t, top_k=1)
        if hits:
            return str(hits[0].get("file") or "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def _resolve_span_in_path(repo: Path, path_n: str, query: str) -> tuple[int, int]:
    if not query:
        return 0, 0
    sym = _resolve_symbol_lines(repo, path_n, query)
    if sym:
        return sym
    if _looks_like_symbol_query(query):
        return 0, 0
    try:
        from pipeline.locate import _search_hits

        for h in _search_hits(repo, query, top_k=24):
            hf = str(h.get("file") or "").replace("\\", "/")
            if hf == path_n or hf.endswith("/" + path_n) or path_n.endswith(hf):
                s = int(h.get("start_line") or 0)
                if s:
                    return s, int(h.get("end_line") or 0)
    except Exception:  # noqa: BLE001
        pass
    return 0, 0


def _facade_hint_for_card(card: dict[str, Any]) -> dict[str, Any] | None:
    """Lightweight facade detection for thin map cards."""
    f = str(card.get("file") or "")
    s = int(card.get("start_line") or 0)
    e = int(card.get("end_line") or 0)
    span = max(0, e - s + 1) if s and e else 0
    if span > 15:
        return None
    fl = f.replace("\\", "/").lower()
    if "extract.py" in fl or fl.endswith("/extract.py"):
        return {
            "facade_hint": True,
            "follow_up": "host Grep for def _extract_generic, or map extractors/engine implementation",
        }
    why = str(card.get("why") or "").lower()
    if span <= 15 and ("wrapper" in why or "facade" in why or "re-export" in why):
        return {
            "facade_hint": True,
            "follow_up": "host Grep the symbol or map for implementation under extractors/",
        }
    return None


def _enrich_map_cards(cards: list[dict[str, Any]], *, query: str = "") -> list[dict[str, Any]]:
    """Slim cards: file/lines/score/why/role (+ weak_match). No per-card coaching."""
    from pipeline.context_trace import card_role, fill_map_card_symbol, rank_soft_map_cards

    out: list[dict[str, Any]] = []
    for c in cards or []:
        item = fill_map_card_symbol(dict(c), query=query)
        if item.get("why"):
            item["why"] = _strip_bom_text(str(item["why"]))
        # Drop legacy coaching keys if a cached card still carries them.
        for key in ("needs_outline", "span_hint", "facade_hint", "follow_up", "next", "usage_hint"):
            item.pop(key, None)
        s = int(item.get("start_line") or 0)
        e = int(item.get("end_line") or 0)
        if s and e and (e - s + 1) > 200:
            item["display_end_line"] = min(e, s + 120)
        score = float(item.get("score") or 0.0)
        if score and score < _MAP_SCORE_LOW:
            item["weak_match"] = True
        if not item.get("role"):
            item["role"] = card_role(str(item.get("file") or ""), str(item.get("kind") or ""))
        out.append(item)
    return rank_soft_map_cards(out)


def _card_node_id(card: Any) -> str:
    if not isinstance(card, dict):
        return ""
    cid = str(card.get("id") or "").strip()
    if cid:
        return cid
    file = str(card.get("file") or "").strip().replace("\\", "/")
    if not file:
        return ""
    symbol = str(card.get("symbol") or "").strip()
    return f"{file}::{symbol}" if symbol else file


def _resolve_expand_node(
    node: str,
    seed_file: str = "",
    seed_symbol: str = "",
    prior: dict[str, Any] | None = None,
) -> str:
    """Pick the node to grow from, accepting pack_context's seed vocabulary.

    ``node`` used to be required, so an agent that had just called
    pack_context(seed_file=…, seed_symbol=…) and reused those names got a
    schema validation error instead of an expand — mid-ladder, with no way to
    tell the two spellings apart. Accept either, and fall back to the hottest
    card already in the trace so a bare expand_context() still advances.
    """
    direct = (node or "").strip()
    if direct:
        return direct
    file = (seed_file or "").strip().replace("\\", "/")
    if file:
        symbol = (seed_symbol or "").strip()
        return f"{file}::{symbol}" if symbol else file
    cards = [c for c in ((prior or {}).get("cards") or []) if isinstance(c, dict)]
    hot = [c for c in cards if str(c.get("heat") or "").lower() == "hot"]
    for card in [*hot, *cards]:
        resolved = _card_node_id(card)
        if resolved:
            return resolved
    return ""


class _WarmingClient:
    """Stand-in while /health is down — locate tools return immediately, never hang."""

    def __init__(self, admission: dict[str, Any]) -> None:
        self._scubiee_admission = admission
        self.base = str(admission.get("url") or "")

    def _payload(self, *_a: Any, **_k: Any) -> dict[str, Any]:
        from pipeline.engine import warming_response

        return warming_response(warm_state=str(self._scubiee_admission.get("warm_state") or "warming"))

    def healthy(self) -> bool:
        return False

    def health(self) -> dict[str, Any]:
        return {**self._payload(), "ok": False, "embedder_loaded": False}

    def open_repo(self, *_a: Any, **_k: Any) -> dict[str, Any]:
        return self._payload()

    def note_locate(self, **_k: Any) -> dict[str, Any]:
        return self._payload()

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        return self._payload


def _client_for(repo: Path):
    from pipeline.client import EngineClient
    from pipeline.engine import warming_response
    from pipeline.mcp_lifecycle import (
        current_client_id,
        ensure_mcp_runtime,
        mark_soft_ready,
        soft_ready_cached,
    )
    from pipeline.session_isolation import effective_session_id, mcp_client_name

    # Never block the MCP stdio request on index/FastEmbed. Kick spawn, return
    # warming if /health is down. force_restart_daemon here caused a second
    # engine start ~40s later and hung the first map past Cursor's timeout.
    warm = ensure_mcp_runtime(
        repo,
        client_id=current_client_id() or _MCP_CLIENT_ID,
        blocking=False,
    )
    if not warm.get("ok"):
        _stderr(f"[scubiee] warm gate incomplete: {warm}")

    sid = effective_session_id(None)

    def _soft_client(*, skipped: str) -> EngineClient:
        client = EngineClient(
            workspace_path=str(repo),
            client=mcp_client_name(),
            session_id=sid,
            timeout=8.0,
        )
        admission: dict[str, Any] = {
            "ok": True,
            "warm": warm,
            "soft_ready": True,
            "soft_ttl_skip": True,
            "open_status": skipped,
        }
        setattr(client, "_scubiee_admission", admission)
        return client

    # Hot path: process-local soft TTL. Parallel map storms must not all probe
    # /health+/v1/open — one admit, everyone else rides the TTL.
    if soft_ready_cached():
        return _soft_client(skipped="soft_ttl")

    with _CLIENT_ADMIT_LOCK:
        if soft_ready_cached():
            return _soft_client(skipped="soft_ttl_after_wait")

        soft_ready = False
        try:
            soft_probe = EngineClient(
                workspace_path=str(repo),
                timeout=0.75,
            ).health()
            soft_ready = bool(
                soft_probe.get("soft_search_ready") and soft_probe.get("service")
            )
        except Exception:  # noqa: BLE001
            soft_ready = False
        if soft_ready:
            mark_soft_ready()
            return _soft_client(skipped="soft_ready_skip")

        # Never join_attach_warm on the tool path (burned 15–37s into first map).
        try:
            from pipeline.mcp_lifecycle import start_locate_worker_prewarm

            start_locate_worker_prewarm(repo)
        except Exception:  # noqa: BLE001
            pass
        try:
            soft_probe2 = EngineClient(
                workspace_path=str(repo),
                timeout=0.5,
            ).health()
            soft_ready = bool(
                soft_probe2.get("soft_search_ready") and soft_probe2.get("service")
            )
            if soft_ready:
                mark_soft_ready()
                return _soft_client(skipped="soft_ready_skip")
        except Exception:  # noqa: BLE001
            soft_ready = False

        if not soft_ready:
            try:
                healthy = bool(
                    EngineClient(
                        workspace_path=str(repo),
                        timeout=0.75,
                    ).healthy()
                )
            except Exception:  # noqa: BLE001
                healthy = False
            if not healthy:
                admission = {**warming_response(), "warm": warm, "deferred_prewarm": True}
                client = _WarmingClient(admission)
                setattr(client, "_scubiee_admission", admission)
                return client

        client = EngineClient(
            workspace_path=str(repo),
            client=mcp_client_name(),
            session_id=sid,
            timeout=8.0,
        )
        admission = {"ok": True, "warm": warm, "soft_ready": False}
        try:
            opened = client.open_repo(str(repo), wait=False)
            admission["open_status"] = opened.get("status") or opened.get("warm_state")
            if (
                isinstance(opened, dict)
                and opened.get("ok") is not False
                and opened.get("project_id")
            ):
                mark_soft_ready()
                admission["soft_ready"] = True
        except Exception as exc:  # noqa: BLE001
            admission = {**warming_response(), "detail": str(exc), "warm": warm}
            stub = _WarmingClient(admission)
            setattr(stub, "_scubiee_admission", admission)
            return stub
        setattr(client, "_scubiee_admission", admission)
        # Rate-limited (shared with map streak) — do not stampede note_locate.
        _note_locate_streak(repo)
        return client


# ---- arg models ------------------------------------------------------------

class SearchArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(..., min_length=1, max_length=2000, description="NL or symbol query.")
    k: int = Field(8, ge=1, le=25, description="How many hits (r5=5, r10=10).")
    include: Literal["hits", "span", "graph"] = Field(
        "hits",
        description="hits=pointers only; span=top-1..3 bodies; graph=top-hit 1-hop neighbors.",
    )
    mode: Literal["soft", "exact"] = Field(
        "soft", description="soft=semantic hybrid; exact=literal/regex grep."
    )
    fetch: bool = Field(False, description="Deprecated alias: true → include=span.")
    max_chars: int = Field(1200, ge=200, le=6000, description="Per-hit body budget when span.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class ReadArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    target: str = Field("", max_length=512, description="Symbol / phrase / 'path' / 'path:line'.")
    path: str = Field("", max_length=512, description="Explicit repo-relative file.")
    query: str = Field("", max_length=2000, description="When path= set, pick the span for this.")
    handle: str = Field("", max_length=64, description="Re-materialize a prior span handle.")
    start_line: int = Field(0, ge=0, le=1_000_000, description="With path=, read from this line.")
    end_line: int = Field(0, ge=0, le=1_000_000, description="With path/start_line, read to this line.")
    detail: Literal["body", "outline", "neighbors"] = Field(
        "body", description="body=span; outline=defs only; neighbors=attach callers/callees."
    )
    neighbors: bool = Field(False, description="Attach 1-hop callers/callees of this span.")
    max_neighbors: int = Field(4, ge=1, le=10, description="Cap how many neighbor spans ride along.")
    budget: Literal["cap", "wide", "full"] = Field(
        "cap",
        description="Read size: cap (~200 lines), wide (~350), full (~1k lines). Chars guard density only.",
    )
    max_chars: int = Field(50_000, ge=200, le=500_000, description="Body budget for the span.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class GrepArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    pattern: str = Field(..., min_length=1, max_length=512, description="Literal/regex string.")
    glob: str = Field(
        "**/*",
        max_length=256,
        description="File glob — default **/* (all files). Supports **, *, ? and brace groups like *.{ts,tsx,md}.",
    )
    max_hits: int = Field(200, ge=1, le=500, description="Max matches to return.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class OutlineArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    path: str = Field(..., min_length=1, max_length=512, description="Repo-relative file to outline.")
    keep: int = Field(60, ge=1, le=200, description="Max symbols to list.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class NeighborsArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    target: str = Field(..., min_length=1, max_length=512, description="Symbol or file to expand around.")
    keep: int = Field(4, ge=1, le=8, description="How many neighbor spans.")
    max_chars: int = Field(500, ge=120, le=2000, description="Per-neighbor body budget.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class GraphArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    question: str = Field(..., min_length=1, max_length=2000, description="NL structural question.")
    keep: int = Field(6, ge=1, le=10, description="How many spans to return.")
    max_chars: int = Field(400, ge=120, le=2000, description="Per-span body budget.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class FilesArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    pattern: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Name or glob: 'query_router.py', 'query_*', '*.md', 'packages/**/*.py'.",
    )
    limit: int = Field(200, ge=1, le=2000, description="Max file paths to return.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class MapArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(..., min_length=1, max_length=2000, description="Cold/new-topic locate query.")
    k: int = Field(12, ge=1, le=25, description="How many cards (default 12 for seed coverage).")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class PinpointArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Soft where/how/who question — code vocabulary preferred.",
    )
    k: int = Field(5, ge=1, le=12, description="Alt card count (primary is always top-1).")
    max_chars: int = Field(
        8_000,
        ge=400,
        le=50_000,
        description="Primary body budget (lean default).",
    )
    max_neighbors: int = Field(4, ge=0, le=8, description="Graph neighbor spans on primary.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class PlateArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    query: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="How-X-works / relatedness — code vocabulary (e.g. auth login session jwt).",
    )
    k_hubs: int = Field(4, ge=1, le=8, description="Hybrid hubs (BM25+dense).")
    k_connections: int = Field(6, ge=0, le=12, description="Graph connections around hubs.")
    max_chars: int = Field(600, ge=200, le=4_000, description="Chars per hub/connection peek.")
    sketch: bool = Field(True, description="Include Graphify BFS sketch text when available.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class FocusArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    target: str = Field("", max_length=512, description="File path, path:line, or symbol/phrase.")
    mode: Literal["outline", "span", "neighbors", "call_sites"] = Field(
        "span",
        description="outline=structure; span=body; neighbors=imports; call_sites=literal refs.",
    )
    path: str = Field("", max_length=512, description="Explicit repo-relative file.")
    query: str = Field("", max_length=2000, description="Help pick span inside path.")
    start_line: int = Field(0, ge=0, le=1_000_000)
    end_line: int = Field(0, ge=0, le=1_000_000)
    budget: Literal["cap", "wide", "full"] = Field(
        "cap",
        description="Read size: cap (~200 lines), wide (~350), full (~1k lines). Chars guard density only.",
    )
    max_chars: int = Field(50_000, ge=200, le=500_000, description="Body char budget (budget sets default).")
    max_neighbors: int = Field(4, ge=1, le=10)
    outline_offset: int = Field(0, ge=0, le=10_000, description="Paginate outline symbols.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


class WorkspaceArgs(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    action: Literal["show", "pin", "clear"] = Field(
        "show", description="show=session brain; pin=mark hot file; clear=new topic."
    )
    path: str = Field("", max_length=512, description="Required for pin — repo-relative file.")
    response_format: Literal["json", "markdown"] = Field("json", description="json|markdown")


# ---- markdown ---------------------------------------------------------------

def _escape_fence(text: str) -> str:
    return str(text).replace("```", "'''")


def _to_markdown(card: dict[str, Any]) -> str:
    lines = [f"# {card.get('tool', 'result')}", ""]
    if card.get("ok") is False:
        lines.append(f"**Error:** {card.get('error')}")
        if card.get("hint"):
            lines.append(f"**Hint:** {card['hint']}")
        return "\n".join(lines)
    if card.get("results"):
        lines.append("## Results")
        for r in card["results"]:
            lines.append(
                f"- #{r.get('rank')} `{r.get('file')}` "
                f"L{r.get('start_line')}-{r.get('end_line')} — {r.get('why') or ''}"
            )
            if r.get("code"):
                lines += ["```", _escape_fence(str(r["code"])[:1200]), "```"]
        lines.append("")
    if card.get("handle") and card.get("tool") in {"read", "expand"}:
        lines.append(
            f"## Span `{card.get('handle')}` `{card.get('file')}` "
            f"L{card.get('start_line')}-{card.get('end_line')} ({card.get('status')})"
        )
        if card.get("code"):
            lines += ["```", _escape_fence(str(card["code"])[:3000]), "```"]
        elif card.get("unchanged"):
            lines.append("_unchanged — already in session_")
        lines.append("")
    if card.get("hits"):
        lines.append("## Matches")
        for h in card["hits"]:
            lines.append(f"- `{h.get('file')}`:{h.get('line')} — {h.get('text') or ''}")
        lines.append("")
    if card.get("tool") == "files" and card.get("files"):
        lines.append(f"## Files ({card.get('count')}{'+' if card.get('truncated') else ''})")
        for f in card["files"]:
            lines.append(f"- `{f}`")
        lines.append("")
    if card.get("symbols"):
        lines.append("## Outline")
        for s in card["symbols"]:
            lines.append(f"- {s.get('kind') or ''} `{s.get('name')}` L{s.get('start_line')}")
        lines.append("")
    for key, title in (
        ("alternatives", "Other hits"),
        ("neighbors", "Neighbors (1-hop)"),
        ("spans", "Spans"),
        ("usages", "Usages"),
    ):
        if card.get(key):
            lines.append(f"## {title}")
            for n in card[key]:
                lines.append(
                    f"- `{n.get('file')}` L{n.get('start_line')}-{n.get('end_line')}"
                    f" — {n.get('why') or ''}"
                )
                if n.get("code"):
                    lines += ["```", str(n["code"])[:600], "```"]
            lines.append("")
    if card.get("next"):
        lines.append(f"\n_{card['next']}_")
    return "\n".join(lines)


def _attach_gate(card: dict[str, Any]) -> dict[str, Any]:
    """Universal compact gate + session flags (hint prose once per session_id)."""
    from pipeline.mcp_response_lean import attach_gate_lean
    from pipeline.session_isolation import session_context_for_response

    return attach_gate_lean(
        card,
        gate_line=_gate_line,
        session_context=session_context_for_response,
    )


def _format(card: dict[str, Any], fmt: str) -> str:
    if fmt == "markdown":
        return _to_markdown(_attach_gate(card))
    return _dumps(_attach_gate(card))


# ---- server -----------------------------------------------------------------

def create_mcp(name: str = "scubiee") -> "FastMCP":
    if FastMCP is None:
        raise RuntimeError("pip install mcp")
    surface = _active_surface()
    from pipeline.mcp_lifecycle import mcp_lifespan_factory

    repo = _default_repo()
    mcp = FastMCP(
        name,
        instructions=_server_instructions(surface),
        lifespan=mcp_lifespan_factory(repo),
    )
    # FastMCP exposes no version parameter, so the low-level Server underneath it
    # falls back to the installed `mcp` package version and the IDE's MCP panel
    # advertises a scubiee release that does not exist.
    try:
        from pipeline.upgrade import installed_version

        mcp._mcp_server.version = installed_version()
    except Exception:  # noqa: BLE001 - a wrong version must not block startup
        pass

    def _tool(tool_name: str, title: str, fn) -> None:
        from functools import wraps

        from pipeline.session_isolation import (
            bind_resolved_session,
            bind_transport_session_from_mcp,
            reset_resolved_session,
            reset_transport_session,
            resolve_session,
        )

        @wraps(fn)
        def _wrapped(*args: Any, **kwargs: Any) -> Any:
            if tool_name not in {"gate", "status"}:
                try:
                    from pipeline.pause_resume import is_paused

                    if is_paused():
                        return _paused_locate_err(tool_name)
                except Exception:  # noqa: BLE001
                    pass
            ttok = bind_transport_session_from_mcp(mcp)
            explicit = str(kwargs.get("session_id") or "").strip()
            info = resolve_session(explicit or None)
            rtok = bind_resolved_session(info)
            root = str(kwargs.get("root") or "")
            project_id = str(kwargs.get("project_id") or "")
            session_id_kw = str(kwargs.get("session_id") or "")
            try:
                with _bind_request_repo(
                    root=root,
                    project_id=project_id,
                    session_id=session_id_kw,
                ):
                    _touch_mcp_client()
                    return fn(*args, **kwargs)
            finally:
                reset_resolved_session(rtok)
                reset_transport_session(ttok)

        mcp.tool(
            name=tool_name,
            annotations={
                "title": title,
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        )(_wrapped)

    # ---- search (all surfaces) --------------------------------------------
    def search_impl(
        query: Annotated[str, Field(description="FULL soft question, e.g. 'Where is X registered and dispatched?'")],
        k: Annotated[int, Field(description="How many hits (default 8; clamp ≤12 on search surface).")] = 8,
        include: Annotated[
            str,
            Field(description="hits (default)=pointers; span=top 1-3 bodies; graph=top-hit callers/callees."),
        ] = "hits",
        mode: Annotated[str, Field(description="soft=semantic (default). exact=legacy/nav only.")] = "soft",
        fetch: Annotated[bool, Field(description="Deprecated: true acts like include=span.")] = False,
        max_chars: Annotated[int, Field(description="Per-hit body budget when include=span.")] = 1200,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """Prefer for soft/where meaning over host Grep. Default include=hits (skinny)."""
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            try:
                args = SearchArgs(
                    query=query,
                    k=k,
                    include=include,  # type: ignore[arg-type]
                    mode=mode,  # type: ignore[arg-type]
                    fetch=fetch,
                    max_chars=max_chars,
                    response_format=response_format,  # type: ignore[arg-type]
                )
            except ValidationError as exc:
                return _err(
                    "search",
                    str(exc),
                    hint="query required; include=hits|span|graph; k in 1..25.",
                )
            repo = _default_repo()

            if not _is_repo_managed():
                return _managed_locate_err("search", repo)

            surface = _active_surface()
            # search-only product: soft meaning only; skinny k.
            if surface == "search":
                if str(args.mode).strip().lower() == "exact":
                    return _err(
                        "search",
                        "exact mode disabled on search surface",
                        thrash_blocked=True,
                        hint="Use native Grep for true literals. search() is soft/meaning only.",
                        next="Grep(literal) or search(full question)",
                    )
                args.mode = "soft"
                args.k = max(3, min(int(args.k), 12))
            include_mode = str(args.include or "hits").strip().lower()
            if args.fetch and include_mode == "hits":
                include_mode = "span"
            usage_hint = _record_locate_query(
                repo, str(args.mode), args.query, session_id=_resolve_session(session_id)
            )

            if args.mode == "exact":
                try:
                    res = _client_for(repo).grep(
                        args.query, glob="*", max_hits=max(args.k, 20), path=str(repo),
                    )
                except Exception as exc:  # noqa: BLE001
                    return _err("search", str(exc), hint="Exact mode needs a warm engine; check status().")
                backend_error = _backend_error(
                    "search",
                    repo,
                    res,
                    hint="Exact mode needs a warm engine; check status().",
                )
                if backend_error:
                    return backend_error
                hits = _slim_grep(res.get("hits") or res.get("matches"), keep=max(args.k, 20))
                out = {
                    "ok": True, "tool": "search", "mode": "exact", "query": args.query,
                    "count": len(hits), "hits": hits,
                    "next": "read(path) that one hit then edit.",
                }
                if usage_hint:
                    out["usage_hint"] = usage_hint
                return _format(out, args.response_format)

            try:
                from pipeline.locate import _read_excerpt, _search_hits
                from pipeline.mcp_lifecycle import (
                    join_locate_worker_prewarm,
                    locate_worker_prewarm_done,
                    mark_soft_ready,
                    soft_ready_cached,
                    start_locate_worker_prewarm,
                )

                # Only brief join on true cold worker. A 2s join every map while
                # prewarm stalled (soft TTL never set in-process) made warm Cursor
                # maps stick at ~3.5–5s forever.
                if not locate_worker_prewarm_done() and not soft_ready_cached():
                    start_locate_worker_prewarm(repo)
                    join_locate_worker_prewarm(timeout_s=0.35)

                hits = _search_hits(repo, args.query, top_k=args.k)
                try:
                    from pipeline.mcp_lifecycle import note_search_probe_ok

                    if hits:
                        note_search_probe_ok()
                        mark_soft_ready()
                except Exception:  # noqa: BLE001
                    pass
                results: list[dict[str, Any]] = []
                span_n = 3 if include_mode == "span" else 0
                for rank, h in enumerate(hits[: args.k], 1):
                    f = h.get("file")
                    item: dict[str, Any] = {
                        "rank": rank, "file": f,
                        "start_line": h.get("start_line"), "end_line": h.get("end_line"),
                        "score": round(float(h.get("score") or 0.0), 4),
                        "why": h.get("why") or "",
                    }
                    from pipeline.context_trace import symbol_from_preview

                    sym, kind = symbol_from_preview(str(item.get("why") or ""))
                    if sym:
                        item["symbol"] = sym
                        item["kind"] = kind or "function"
                    if span_n and rank <= span_n and f:
                        ex = _read_excerpt(
                            repo, str(f), int(h.get("start_line") or 0),
                            int(h.get("end_line") or 0), max_chars=args.max_chars,
                        )
                        item["code"] = ex.get("excerpt") or ex.get("text") or ""
                    results.append(item)

                neighbors: list[dict[str, Any]] = []
                neighbors_error: str | None = None
                if include_mode == "graph" and results:
                    top = results[0]
                    file_s = str(top.get("file") or "")
                    if file_s:
                        try:
                            gn = _client_for(repo).graph_neighbors(
                                [file_s],
                                keep=4,
                                max_chars=min(400, int(args.max_chars)),
                                repo=str(repo),
                            )
                            backend_error = _backend_error(
                                "search", repo, gn,
                                hint="Graph results need a warm engine; check status().",
                            )
                            if backend_error:
                                return backend_error
                            neighbors = _slim_spans(
                                gn.get("spans") or [], keep=4, body_chars=400
                            )
                        except Exception as exc:  # noqa: BLE001
                            backend_error = _backend_error(
                                "search", repo, getattr(exc, "response", None),
                                hint="Graph results need a warm engine; check status().",
                            )
                            if backend_error:
                                return backend_error
                            neighbors = []
                            neighbors_error = str(exc)

                if results:
                    if include_mode == "graph":
                        nxt = "Use neighbors for wiring; native Read the top file once → EDIT."
                    elif include_mode == "span":
                        nxt = "Peek done — native Read only if you need more, then EDIT."
                    else:
                        nxt = "Skim hits; native Read ONLY the one file you will edit → EDIT."
                else:
                    nxt = "no hits — one sharper soft query or k=10; then Grep once for a full literal."
                out: dict[str, Any] = {
                    "ok": True,
                    "tool": "search",
                    "mode": "soft",
                    "include": include_mode,
                    "query": args.query,
                    "k": args.k,
                    "count": len(results),
                    "results": results,
                    "next": nxt,
                }
                if include_mode == "graph":
                    out["neighbors"] = neighbors
                    out["neighbors_count"] = len(neighbors)
                    if neighbors_error:
                        out["neighbors_error"] = neighbors_error
                if usage_hint:
                    out["usage_hint"] = usage_hint
                return _format(out, args.response_format)
            except Exception as exc:  # noqa: BLE001
                backend_error = _backend_error(
                    "search",
                    repo,
                    getattr(exc, "response", None),
                    hint="Check status()/CTX_REPO; ensure index is warm.",
                )
                if backend_error:
                    return backend_error
                return _err(
                    "search",
                    str(exc),
                    repo=str(repo),
                    hint="Check status()/CTX_REPO; ensure index is warm.",
                )

    # ---- read (read, rich, nav) -------------------------------------------------
    def read_impl(
        target: Annotated[str, Field(description="Symbol / phrase / 'path' / 'path:line'.")] = "",
        path: Annotated[str, Field(description="Explicit repo-relative file (skips search).")] = "",
        query: Annotated[str, Field(description="When path= set, pick the span for this.")] = "",
        handle: Annotated[str, Field(description="Re-materialize a prior span handle.")] = "",
        start_line: Annotated[int, Field(description="With path=, read from this line.")] = 0,
        end_line: Annotated[int, Field(description="With path/start_line, read to this line.")] = 0,
        detail: Annotated[
            str, Field(description="body (default) | outline | neighbors")
        ] = "body",
        neighbors: Annotated[bool, Field(description="Attach 1-hop callers/callees of this span (the graph).")] = False,
        max_neighbors: Annotated[int, Field(description="Cap how many neighbor spans ride along (1..10).")] = 4,
        budget: Annotated[
            str, Field(description="Read size: cap (~200 lines), wide (~350), full (~1k).")
        ] = "cap",
        max_chars: Annotated[int, Field(description="Body budget for the span (budget sets default).")] = 50_000,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """Open the right span before edit. detail=outline|neighbors for shape/wiring."""
        try:
            args = ReadArgs(
                target=target, path=path, query=query, handle=handle,
                start_line=start_line, end_line=end_line,
                detail=detail,  # type: ignore[arg-type]
                neighbors=neighbors or (str(detail).strip().lower() == "neighbors"),
                max_neighbors=max_neighbors,
                budget=budget,  # type: ignore[arg-type]
                max_chars=max_chars,
                response_format=response_format,  # type: ignore[arg-type]
            )
        except ValidationError as exc:
            return _err("read", str(exc), hint="Pass target= or path= or handle=.")
        sid = _resolve_session(session_id)
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()

        if not _is_repo_managed():
            return _managed_locate_err("read", repo)

        if args.detail == "outline":
            path_o = (args.path or "").replace("\\", "/").strip()
            if not path_o and _looks_like_path((args.target or "").strip()):
                path_o = (args.target or "").replace("\\", "/").strip()
            if not path_o:
                path_o = _resolve_to_file(repo, args.target or args.query)
            if not path_o:
                return _err(
                    "read", "outline needs a file path",
                    hint="Pass path= or a path-like target=.",
                )
            try:
                res = _client_for(repo).outline(path_o.replace("\\", "/"), repo=str(repo))
            except Exception as exc:  # noqa: BLE001
                return _err("read", str(exc), hint="Ensure the engine is warm.")
            backend_error = _backend_error(
                "read", repo, res, hint="Ensure the engine is warm."
            )
            if backend_error:
                return backend_error
            symbols, symbols_total, symbols_capped = _slim_outline(
                res.get("symbols") or res.get("outline"), keep=_OUTLINE_KEEP_DEFAULT,
            )
            out = {
                "ok": True, "tool": "read", "detail": "outline", "mode": "outline",
                "path": res.get("path") or path_o, "count": len(symbols),
                "symbols": symbols, "code": "",
                "symbols_total": symbols_total,
                "symbols_shown": len(symbols),
                "symbols_capped": symbols_capped,
                "next": "read(path, query='<symbol>') to open one body; detail=neighbors for wiring.",
            }
            if symbols_capped:
                out["next"] = f"focus(outline, outline_offset={len(symbols)}) for more symbols"
            return _format(out, args.response_format)

        if args.handle:
            try:
                from pipeline.session_store import expand as _expand

                card = _expand(repo, args.handle, max_chars=args.max_chars, session_id=sid)
                if not card.get("ok"):
                    return _err("read", str(card.get("error") or "unknown handle"),
                                handle=args.handle, hint="Search again; handle may be stale.")
                out = {
                    "ok": True, "tool": "read", "mode": "handle", "handle": args.handle,
                    "file": card.get("path"), "start_line": card.get("start_line"),
                    "end_line": card.get("end_line"), "status": "materialized",
                    "code": card.get("text") or card.get("excerpt") or "",
                }
                return _format(out, args.response_format)
            except Exception as exc:  # noqa: BLE001
                return _err("read", str(exc), handle=args.handle)

        path_s = (args.path or "").replace("\\", "/").strip()
        target_s = (args.target or "").strip()
        q = (args.query or "").strip()
        alternatives: list[dict[str, Any]] = []

        if not path_s and _looks_like_path(target_s):
            if ":" in target_s and not target_s.endswith(":"):
                head, _, tail = target_s.rpartition(":")
                if tail.isdigit():
                    path_s = head
            path_s = path_s or target_s

        start_l, end_l = 0, 0
        if path_s:
            if args.start_line:
                start_l = int(args.start_line)
                end_l = int(args.end_line or 0)
                if not end_l and (q or target_s):
                    sym_rng = _resolve_symbol_lines(repo, path_s, q or target_s)
                    if sym_rng:
                        start_l, end_l = sym_rng
                resolved_from = "lines"
            else:
                sym_q = q or target_s
                sym_rng = _resolve_symbol_lines(repo, path_s, sym_q)
                if sym_rng:
                    start_l, end_l = sym_rng
                    resolved_from = "symbol"
                elif _looks_like_symbol_query(sym_q):
                    return _err(
                        "read",
                        f"symbol {_normalize_symbol_query(sym_q)!r} not found in {path_s!r}",
                        file=path_s,
                        hint="focus(mode=outline) for symbols in this file; grep repo-wide.",
                    )
                else:
                    start_l, end_l = _resolve_span_in_path(repo, path_s, sym_q)
                    resolved_from = "path"
            file_s = path_s
        else:
            tq = target_s or q
            if not tq:
                return _err("read", "target, path, or handle required",
                            hint="read(target='WarmSearchEngine.search') or read(path='pkg/x.py').")
            try:
                from pipeline.locate import _search_hits

                hits = _search_hits(repo, tq, top_k=8)
            except Exception as exc:  # noqa: BLE001
                return _err("read", str(exc), hint="Ensure the search index is warm.")
            if not hits:
                return _err("read", f"no span found for {tq!r}",
                            hint="Try search(query) first, then read(target=<a hit's file>).")
            top = hits[0]
            file_s = str(top.get("file") or "")
            start_l = int(top.get("start_line") or 0)
            end_l = int(top.get("end_line") or 0)
            resolved_from = "search"
            for h in hits[1:3]:
                alternatives.append({
                    "file": h.get("file"), "start_line": h.get("start_line"),
                    "end_line": h.get("end_line"), "why": (h.get("why") or "")[:140],
                })

        char_budget, line_budget = _budget_limits(
            args.budget,
            max_chars=args.max_chars,
            default_max_chars=ReadArgs.model_fields["max_chars"].default,
        )

        try:
            if resolved_from == "lines":
                check_end = int(end_l or 0)
                if check_end < start_l and start_l:
                    fp = repo / file_s
                    if fp.is_file():
                        n_lines = len(
                            fp.read_text(encoding="utf-8-sig", errors="replace").splitlines()
                        )
                        if _normalize_budget(args.budget) == "full":
                            check_end = n_lines
                        else:
                            check_end = _resolve_auto_end_line(
                                repo,
                                file_s,
                                start_l,
                                n_lines,
                                max_lines=line_budget,
                            )
                overlap = _check_focus_overlap(
                    repo,
                    file_s,
                    start_l,
                    check_end,
                    session_id=sid,
                    budget=args.budget,
                )
                if overlap:
                    overlap["tool"] = "read"
                    return _format(overlap, args.response_format)
                ex = _read_line_range(
                    repo,
                    file_s,
                    start_l,
                    end_l,
                    char_budget,
                    max_lines=line_budget,
                    budget=args.budget,
                )
            else:
                from pipeline.locate import _read_excerpt

                ex = _read_excerpt(repo, file_s, start_l, end_l, max_chars=char_budget)
        except Exception as exc:  # noqa: BLE001
            return _err("read", str(exc), file=file_s)
        if ex.get("error") and ex.get("ok") is False:
            return _err("read", str(ex.get("error")), file=file_s, hint="Check path spelling.")
        backend_error = _backend_error(
            "read", repo, ex, hint="Ensure the engine is warm and the file exists.",
            require_ok=False,
        )
        if backend_error:
            return backend_error
        code = _strip_bom_text(ex.get("excerpt") or ex.get("text") or "")
        if not str(code).strip():
            return _err(
                "read", f"no readable span found for {file_s!r}",
                file=file_s, hint="Try read(path=..., start_line=1) or search() first.",
            )
        start_l = int(ex.get("start_line") or start_l or 0)
        end_l = int(ex.get("end_line") or end_l or 0)

        try:
            from pipeline.session_store import put_span

            span = put_span(
                repo, path=file_s, start_line=start_l, end_line=end_l, text=code,
                why=target_s or q or file_s, source="read",
                topic=target_s or q or file_s, excerpt_chars=100,
                session_id=sid,
            )
            handle_s = span.get("handle")
            status_s = span.get("status")
        except Exception:  # noqa: BLE001
            handle_s, status_s = None, "stored"

        unchanged = status_s == "already_in_session"
        # Always return the body — empty code + stop_locate forced expand loops
        # and burned tokens. Dedup status is advisory only.
        out = {
            "ok": True, "tool": "read", "mode": resolved_from, "handle": handle_s,
            "file": file_s, "start_line": start_l, "end_line": end_l,
            "status": status_s, "unchanged": unchanged,
            "code": code,
            "truncated": bool(ex.get("truncated")),
            "session_id": sid,
        }
        from pipeline.mcp_response_lean import echo_budget_enabled

        if echo_budget_enabled():
            out["budget"] = args.budget
        for key in ("lines_total", "lines_returned", "next_start_line", "chars_returned"):
            if ex.get(key) is not None:
                out[key] = ex[key]
        if unchanged:
            # Body already in ``code`` — no expand round-trip required.
            _annotate_locate_dedup(out)
        # truncated: keep next_start_line / truncated flags only (no recipe next).
        if alternatives:
            out["alternatives"] = alternatives

        if args.neighbors and file_s:
            keep_n = max(1, min(int(args.max_neighbors or 4), 10))
            out["neighbors_mode"] = "import_adjacency"
            try:
                gn = _client_for(repo).graph_neighbors(
                    [file_s], query=target_s or q or "", keep=keep_n,
                    max_chars=400, repo=str(repo),
                )
                backend_error = _backend_error(
                    "read", repo, gn, hint="Graph neighbors need a warm engine; check status()."
                )
                if backend_error:
                    return backend_error
                nbrs = _slim_spans(gn.get("spans") or [], keep=keep_n, body_chars=400)
                for n in nbrs:
                    if isinstance(n.get("text"), str):
                        n["text"] = _strip_bom_text(n["text"])
                if nbrs:
                    out["neighbors"] = nbrs
                    out["neighbors_count"] = len(nbrs)
                else:
                    out["neighbors_note"] = "no import-adjacent files resolved for this span"
            except Exception as exc:  # noqa: BLE001
                backend_error = _backend_error(
                    "read", repo, getattr(exc, "response", None),
                    hint="Graph neighbors need a warm engine; check status().",
                )
                if backend_error:
                    return backend_error
                out["neighbors_note"] = "neighbors unavailable (graph not warm)"
                out["neighbors_error"] = str(exc)
            ident = _normalize_symbol_query(q or target_s)
            if ident and "." in ident:
                ident = ident.split(".")[-1]
            if ident and len(ident) >= 2:
                try:
                    cs = _call_sites_for_ident(repo, ident, keep=4, body_chars=400)
                    if cs:
                        out["call_sites"] = _slim_spans(cs, keep=4, body_chars=400)
                except Exception:  # noqa: BLE001
                    pass

        if not unchanged and not ex.get("truncated"):
            out["next"] = (
                "Edit now. Wiring: focus(mode=neighbors). "
                "Re-open: expand(handle=…) if needed."
            )
        return _format(out, args.response_format)

    # ---- expand (rich) -----------------------------------------------------
    # ---- grep (rich) -------------------------------------------------------
    def grep_impl(
        pattern: Annotated[str, Field(description="Literal/regex string to match.")],
        glob: Annotated[str, Field(description="File glob — default **/* (all files). Brace groups: *.{ts,tsx,md}.")] = "**/*",
        max_hits: Annotated[int, Field(description="Max matches to return.")] = 200,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """Prefer for exact string/literal/regex over shell grep when available.
        RETURNS: hits[{file,line,text}].
        """
        try:
            args = GrepArgs(pattern=pattern, glob=glob, max_hits=max_hits,
                           response_format=response_format)  # type: ignore[arg-type]
        except ValidationError as exc:
            return _err("grep", str(exc), hint="pattern required.")
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()

        if not _is_repo_managed():
            return _managed_locate_err("grep", repo)

        try:
            res = _client_for(repo).grep(
                args.pattern, glob=args.glob, max_hits=args.max_hits, path=str(repo),
            )
        except Exception as exc:  # noqa: BLE001
            return _err("grep", str(exc), hint="Ensure the engine is warm.")
        backend_error = _backend_error(
            "grep", repo, res, hint="Ensure the engine is warm."
        )
        if backend_error:
            return backend_error
        hits = _slim_grep(res.get("hits") or res.get("matches"), keep=args.max_hits)
        truncated = bool(res.get("truncated") or res.get("has_more"))
        out = {
            "ok": True, "tool": "grep", "pattern": args.pattern, "glob": args.glob,
            "count": len(hits), "hits": hits,
            "truncated": truncated, "has_more": truncated,
            "max_hits": args.max_hits,
        }
        if truncated and not hits:
            out["scan_incomplete"] = True
        return _format(out, args.response_format)

    # ---- outline (rich) ----------------------------------------------------
    def outline_impl(
        path: Annotated[str, Field(description="Repo-relative file to outline.")],
        keep: Annotated[int, Field(description="Max symbols to list.")] = 60,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """File shape only — classes/functions + lines, without reading the whole file."""
        try:
            args = OutlineArgs(path=path, keep=keep,
                              response_format=response_format)  # type: ignore[arg-type]
        except ValidationError as exc:
            return _err("outline", str(exc), hint="path required.")
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()

        if not _is_repo_managed():
            return _managed_locate_err("outline", repo)

        try:
            res = _client_for(repo).outline(args.path.replace("\\", "/"), repo=str(repo))
        except Exception as exc:  # noqa: BLE001
            return _err("outline", str(exc), hint="Ensure the engine is warm.")
        backend_error = _backend_error(
            "outline", repo, res, hint="Ensure the engine is warm."
        )
        if backend_error:
            return backend_error
        symbols, symbols_total, symbols_capped = _slim_outline(
            res.get("symbols") or res.get("outline"), keep=args.keep,
        )
        out = {
            "ok": True, "tool": "outline", "path": res.get("path") or args.path,
            "count": len(symbols), "symbols": symbols,
            "symbols_total": symbols_total,
            "symbols_shown": len(symbols),
            "symbols_capped": symbols_capped,
            "next": "read(path, query='<symbol>', neighbors=true) to open one with import-adjacent files.",
        }
        if symbols_capped:
            out["next"] = f"outline(path, keep={args.keep}) — more symbols exist ({symbols_total} total)"
        return _format(out, args.response_format)

    # ---- neighbors (graph, rich) ------------------------------------------
    def neighbors_impl(
        target: Annotated[str, Field(description="Symbol or repo-relative file to expand around.")],
        keep: Annotated[int, Field(description="How many neighbor spans (1..8).")] = 4,
        max_chars: Annotated[int, Field(description="Per-neighbor body budget.")] = 500,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """1-hop callers/callees of a symbol or file (the graph)."""
        try:
            args = NeighborsArgs(target=target, keep=keep, max_chars=max_chars,
                                response_format=response_format)  # type: ignore[arg-type]
        except ValidationError as exc:
            return _err("neighbors", str(exc), hint="Pass a symbol or a repo-relative file.")
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()

        if not _is_repo_managed():
            return _managed_locate_err("neighbors", repo)

        file_s = _resolve_to_file(repo, args.target)
        if not file_s:
            return _err("neighbors", f"could not resolve {args.target!r} to a file",
                        hint="Try search(query) first, then neighbors(target=<a hit's file>).")
        try:
            gn = _client_for(repo).graph_neighbors(
                [file_s], query=args.target, keep=args.keep, max_chars=args.max_chars, repo=str(repo),
            )
        except Exception as exc:  # noqa: BLE001
            return _err("neighbors", str(exc), hint="Ensure the graph index is warm.")
        backend_error = _backend_error(
            "neighbors", repo, gn, hint="Ensure the graph index is warm."
        )
        if backend_error:
            return backend_error
        nbrs = _slim_spans(gn.get("spans") or [], keep=args.keep, body_chars=args.max_chars)
        out = {
            "ok": True, "tool": "neighbors", "target": args.target, "file": file_s,
            "count": len(nbrs), "neighbors": nbrs,
            "next": "read(path, neighbors=true) a caller/callee to edit; search() to widen.",
        }
        return _format(out, args.response_format)

    # ---- graph (graph, rich) ----------------------------------------------
    def graph_impl(
        question: Annotated[str, Field(description="NL structural/relationship question.")],
        keep: Annotated[int, Field(description="How many spans (1..10).")] = 6,
        max_chars: Annotated[int, Field(description="Per-span body budget.")] = 400,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """Relationship query — how A connects to B (graph affinity, not just text)."""
        try:
            args = GraphArgs(question=question, keep=keep, max_chars=max_chars,
                            response_format=response_format)  # type: ignore[arg-type]
        except ValidationError as exc:
            return _err("graph", str(exc), hint="Pass a natural-language question.")
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()

        if not _is_repo_managed():
            return _managed_locate_err("graph", repo)

        try:
            gq = _client_for(repo).query_graph(
                args.question, keep=args.keep, max_chars=args.max_chars, repo=str(repo),
            )
        except Exception as exc:  # noqa: BLE001
            return _err("graph", str(exc), hint="Ensure the graph index is warm.")
        backend_error = _backend_error(
            "graph", repo, gq, hint="Ensure the graph index is warm."
        )
        if backend_error:
            return backend_error
        spans = _slim_spans(gq.get("spans") or [], keep=args.keep, body_chars=args.max_chars)
        out = {
            "ok": True, "tool": "graph", "question": args.question,
            "count": len(spans), "spans": spans,
            "next": "neighbors(target=<a file>) to expand one node; search() for meaning.",
        }
        return _format(out, args.response_format)

    # ---- files (rich, nav) ------------------------------------------------------
    def files_impl(
        pattern: Annotated[str, Field(description="Name or glob: 'query_router.py', '*.md', 'packages/**/*.py', '*.{ts,tsx}'. Use '.' for repo shape.")] = "**/*",
        limit: Annotated[int, Field(description="Max file paths to return.")] = 200,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """WHEN: locate files by NAME or path — "where is the file called X",
        "list the *.md docs", "which files are under packages/pipeline". Use this
        instead of a native glob. pattern='.' returns shallow repo shape.
        RETURNS: files[relative/posix/path] (and dirs when orienting).
        """
        try:
            args = FilesArgs(pattern=pattern, limit=limit,
                            response_format=response_format)  # type: ignore[arg-type]
        except ValidationError as exc:
            return _err("files", str(exc), hint="Pass a name or glob, e.g. '*.py' or 'query_*'.")
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()

        if not _is_repo_managed():
            return _managed_locate_err("files", repo)

        patt = (args.pattern or "").strip()
        if patt in {".", "./"}:
            card = _orient_repo(repo, limit=args.limit)
            out = {
                "ok": True, "tool": "files", "pattern": ".", "mode": "orient",
                "dirs": card["dirs"], "files": card["files"],
                "count": len(card["dirs"]) + len(card["files"]),
                "next": "files('*.py') or search(query) to locate; read(path) to open.",
            }
            return _format(out, args.response_format)
        try:
            found, truncated = _find_repo_files(repo, args.pattern, args.limit)
        except Exception as exc:  # noqa: BLE001
            return _err("files", str(exc), hint="Check CTX_REPO points at the repo root.")
        out = {
            "ok": True, "tool": "files", "pattern": args.pattern,
            "count": len(found), "truncated": truncated, "has_more": truncated,
            "files": found,
            "next": "read(path) to open; search(mode=exact) for text; read(detail=outline) for shape.",
        }
        if truncated:
            out["hint"] = (
                f"More than {args.limit} matches; raise limit or narrow the pattern. "
                "Do not treat this list as complete."
            )
        elif not found:
            out["hint"] = "No match under the repo given ignore dirs (node_modules, testdata, …)."
        return _format(out, args.response_format)

    def glob_impl(
        pattern: Annotated[
            str,
            Field(
                description=(
                    "Filename or path glob — e.g. 'packages/pipeline/mcp_locate.py', "
                    "'**/*.md', 'packages/*'. Use '.' for shallow repo shape. "
                    "Do NOT use glob= — this param is pattern=."
                ),
            ),
        ] = "**/*",
        glob: Annotated[
            str,
            Field(
                description="Alias for pattern (some agents pass glob= by mistake).",
            ),
        ] = "",
        limit: Annotated[int, Field(description="Max file paths to return.")] = 200,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """Prefer for finding paths by name/pattern over host Glob when available."""
        glob_alias = (glob or "").strip()
        effective = (pattern or "").strip()
        if effective in {"", "**/*"} and glob_alias:
            effective = glob_alias
        elif glob_alias and effective != glob_alias and effective not in {".", "./"}:
            effective = glob_alias
        if not effective:
            effective = "**/*"
        raw = files_impl(
            pattern=effective, limit=limit, response_format=response_format,
            root=root, project_id=project_id, session_id=session_id,
        )
        try:
            card = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        card["tool"] = "glob"
        if card.get("ok"):
            card["pattern"] = effective
            if glob_alias and (pattern or "").strip() in {"", "**/*"}:
                card["pattern_source"] = "glob_alias"
            # Payload only: files + truncated/has_more. No next/usage_hint recipes.
        return _format(card, response_format)

    # ---- recall / expand (nav) --------------------------------------------
    def recall_impl(
        need: Annotated[str, Field(description="Optional filter: topic / path fragment / symbol.")] = "",
        top_n: Annotated[int, Field(description="Max spans to list.")] = 20,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """List what this session already fetched — handles only, no file bodies."""
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()

        if not _is_repo_managed():
            return _managed_locate_err("recall", repo)

        sid = _resolve_session(session_id)
        try:
            from pipeline.session_store import recall as _recall

            card = _recall(repo, need=need, top_n=max(1, min(int(top_n or 20), 50)), session_id=sid)
        except Exception as exc:  # noqa: BLE001
            return _err("recall", str(exc))
        spans = card.get("spans") or []
        out = {
            "ok": True, "tool": "recall", "need": need or "",
            "session_id": sid,
            "count": len(spans), "spans": spans,
            "pins": card.get("pins") or [],
            "hot": card.get("heatmap") or card.get("hot") or [],
            "next": "expand(handle) to reopen a span; search only if recall is empty.",
        }
        return _format(out, response_format)

    def expand_impl(
        handle: Annotated[str, Field(description="Session span handle from read/recall.")],
        max_chars: Annotated[int, Field(description="Body budget.")] = 50000,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """Re-materialize a stored span by handle (edit-time body)."""
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()

        if not _is_repo_managed():
            return _managed_locate_err("expand", repo)

        sid = _resolve_session(session_id)
        try:
            from pipeline.session_store import expand as _expand

            card = _expand(
                repo,
                handle,
                max_chars=max(200, min(int(max_chars or 50000), _FOCUS_CHAR_CEILING)),
                session_id=sid,
            )
        except Exception as exc:  # noqa: BLE001
            return _err("expand", str(exc), handle=handle)
        if not card.get("ok"):
            return _err(
                "expand", str(card.get("error") or "unknown handle"),
                handle=handle, hint="recall() for valid handles; search again if stale.",
            )
        out = {
            "ok": True, "tool": "expand", "handle": handle,
            "file": card.get("path"), "start_line": card.get("start_line"),
            "end_line": card.get("end_line"), "text": _strip_bom_text(card.get("text") or ""),
            "chars": card.get("chars"), "truncated": card.get("truncated"),
            "next": "Edit now. recall() for other handles.",
        }
        return _format(out, response_format)

    # ---- phase surface: map / focus / pinpoint / workspace ---------------------------
    def pinpoint_impl(
        query: Annotated[
            str,
            Field(description="Soft where/how/who — denser CODE VOCABULARY ~30-80 tokens."),
        ],
        k: Annotated[int, Field(description="How many alt cards (default 5).")] = 5,
        max_chars: Annotated[int, Field(description="Primary body budget (default 8000).")] = 8_000,
        max_neighbors: Annotated[int, Field(description="Graph neighbors on primary (0..8).")] = 4,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """Prefer for soft where/how/who: Conductor BM25+dense+graph -> body + neighbors.
        Collapses map+outline+span+neighbors into one call. Exact literals -> host Grep.
        """
        try:
            args = PinpointArgs(
                query=query,
                k=k,
                max_chars=max_chars,
                max_neighbors=max_neighbors,
                response_format=response_format,  # type: ignore[arg-type]
            )
        except ValidationError as exc:
            return _err("pinpoint", str(exc), hint="Pass query= with code vocabulary.")
        sid = _resolve_session(session_id)
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()

        if not _is_repo_managed():
            return _managed_locate_err("pinpoint", repo)

        try:
            from pipeline.locate import _read_excerpt, _search_hits

            hits = _search_hits(repo, args.query, top_k=max(args.k, 3))
        except Exception as exc:  # noqa: BLE001
            backend_error = _backend_error(
                "pinpoint",
                repo,
                getattr(exc, "response", None),
                hint="Check status(); ensure index is warm.",
            )
            if backend_error:
                return backend_error
            return _err(
                "pinpoint",
                str(exc),
                repo=str(repo),
                hint="Check status(); ensure index is warm.",
            )

        if not hits:
            return _format(
                {
                    "ok": True,
                    "tool": "pinpoint",
                    "query": args.query,
                    "primary": None,
                    "neighbors": [],
                    "alts": [],
                    "count": 0,
                    "weak_match": True,
                    "session_id": sid,
                    "hint": "No hits — sharpen code vocab or use host Grep for a literal.",
                },
                args.response_format,
            )

        top = hits[0]
        file_s = str(top.get("file") or "").replace("\\", "/")
        start_l = int(top.get("start_line") or 0)
        end_l = int(top.get("end_line") or 0)
        score = round(float(top.get("score") or 0.0), 4)
        why = str(top.get("why") or "")[:160]

        code = ""
        handle_s = None
        status_s = "stored"
        if file_s:
            try:
                ex = _read_excerpt(
                    repo, file_s, start_l, end_l, max_chars=int(args.max_chars),
                )
                code = _strip_bom_text(ex.get("excerpt") or ex.get("text") or "")
                start_l = int(ex.get("start_line") or start_l or 0)
                end_l = int(ex.get("end_line") or end_l or 0)
            except Exception:  # noqa: BLE001
                code = ""
            if code.strip():
                try:
                    from pipeline.session_store import put_span

                    span = put_span(
                        repo,
                        path=file_s,
                        start_line=start_l,
                        end_line=end_l,
                        text=code,
                        why=args.query,
                        source="pinpoint",
                        topic=args.query,
                        excerpt_chars=100,
                        session_id=sid,
                    )
                    handle_s = span.get("handle")
                    status_s = span.get("status") or "stored"
                except Exception:  # noqa: BLE001
                    handle_s, status_s = None, "stored"

        neighbors: list[dict[str, Any]] = []
        neighbors_error: str | None = None
        if file_s and int(args.max_neighbors) > 0:
            try:
                gn = _client_for(repo).graph_neighbors(
                    [file_s],
                    query=args.query,
                    keep=int(args.max_neighbors),
                    max_chars=min(400, int(args.max_chars)),
                    repo=str(repo),
                )
                backend_error = _backend_error(
                    "pinpoint",
                    repo,
                    gn,
                    hint="Graph neighbors need a warm engine; check status().",
                )
                if backend_error:
                    neighbors_error = "graph_neighbors unavailable"
                else:
                    neighbors = _slim_spans(
                        gn.get("spans") or [],
                        keep=int(args.max_neighbors),
                        body_chars=400,
                    )
            except Exception as exc:  # noqa: BLE001
                neighbors_error = str(exc)

        alts: list[dict[str, Any]] = []
        for rank, h in enumerate(hits[1 : args.k], 2):
            alts.append(
                {
                    "rank": rank,
                    "file": h.get("file"),
                    "start_line": h.get("start_line"),
                    "end_line": h.get("end_line"),
                    "score": round(float(h.get("score") or 0.0), 4),
                    "why": (h.get("why") or "")[:120],
                }
            )

        weak = score < 5.0
        primary = {
            "file": file_s,
            "start_line": start_l,
            "end_line": end_l,
            "score": score,
            "why": why,
            "code": code,
            "handle": handle_s,
            "status": status_s,
        }
        out: dict[str, Any] = {
            "ok": True,
            "tool": "pinpoint",
            "query": args.query,
            "channels": "bm25+dense+graph",
            "primary": primary,
            "neighbors": neighbors,
            "neighbors_count": len(neighbors),
            "alts": alts,
            "count": 1 + len(alts),
            "session_id": sid,
            "weak_match": weak,
        }
        if neighbors_error and not neighbors:
            out["neighbors_error"] = neighbors_error[:200]
        try:
            from pipeline.work_session import touch

            touch(
                repo,
                [{"file": file_s, "role": "pinpoint"}] if file_s else [],
                query=args.query,
                session_id=sid,
            )
        except Exception:  # noqa: BLE001
            pass
        return _format(out, args.response_format)

    def plate_impl(
        query: Annotated[
            str,
            Field(description="How X works / relatedness — denser CODE VOCABULARY ~30-80 tokens."),
        ],
        k_hubs: Annotated[int, Field(description="Hybrid hubs (default 4).")] = 4,
        k_connections: Annotated[int, Field(description="Graph connections (default 6).")] = 6,
        max_chars: Annotated[int, Field(description="Chars per peek (default 600).")] = 600,
        sketch: Annotated[bool, Field(description="Include Graphify BFS sketch.")] = True,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """How-X-works plate: BM25+dense hubs + Graphify connections + flow (no LLM).
        For subsystem wiring / relatedness. Soft edit-ready span -> pinpoint instead.
        """
        try:
            args = PlateArgs(
                query=query,
                k_hubs=k_hubs,
                k_connections=k_connections,
                max_chars=max_chars,
                sketch=sketch,
                response_format=response_format,  # type: ignore[arg-type]
            )
        except ValidationError as exc:
            return _err("plate", str(exc), hint="Pass query= with code vocabulary.")
        sid = _resolve_session(session_id)
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()

        if not _is_repo_managed():
            return _managed_locate_err("plate", repo)

        try:
            from pipeline.locate import _read_excerpt, _search_hits
            from pipeline.mcp_plate import assemble_plate

            client = _client_for(repo)

            def _gn(
                paths: list[str],
                *,
                query: str = "",
                keep: int = 4,
                max_chars: int = 400,
                repo: str = "",
            ) -> dict[str, Any]:
                return client.graph_neighbors(
                    paths,
                    query=query,
                    keep=keep,
                    max_chars=max_chars,
                    repo=repo,
                )

            def _qg(
                question: str,
                *,
                keep: int = 4,
                neighbor_keep: int = 4,
                max_chars: int = 400,
                repo: str = "",
            ) -> dict[str, Any]:
                return client.query_graph(
                    question,
                    keep=keep,
                    neighbor_keep=neighbor_keep,
                    max_chars=max_chars,
                    repo=repo,
                )

            def _sketch(r: Path, q: str) -> str:
                if not args.sketch:
                    return ""
                try:
                    from pipeline.graphify_mcp_tools import query_graph_text

                    return query_graph_text(r, q, depth=3, token_budget=1800)
                except Exception:  # noqa: BLE001
                    return ""

            out = assemble_plate(
                repo,
                args.query,
                search_hits=_search_hits,
                read_excerpt=_read_excerpt,
                graph_neighbors=_gn,
                query_graph=_qg,
                graph_sketch=_sketch if args.sketch else None,
                k_hubs=int(args.k_hubs),
                k_connections=int(args.k_connections),
                max_chars=int(args.max_chars),
            )
        except Exception as exc:  # noqa: BLE001
            backend_error = _backend_error(
                "plate",
                repo,
                getattr(exc, "response", None),
                hint="Check status(); ensure index is warm.",
            )
            if backend_error:
                return backend_error
            return _err(
                "plate",
                str(exc),
                repo=str(repo),
                hint="Check status(); ensure index is warm.",
            )

        if not out.get("ok"):
            return _err("plate", str(out.get("error") or "plate failed"))

        out["session_id"] = sid
        # Persist first hub for expand() / workspace heat
        hubs = out.get("hubs") or []
        if hubs:
            h0 = hubs[0]
            code0 = str(h0.get("code") or "")
            file0 = str(h0.get("file") or "")
            if file0 and code0.strip():
                try:
                    from pipeline.session_store import put_span

                    span = put_span(
                        repo,
                        path=file0,
                        start_line=int(h0.get("start_line") or 0),
                        end_line=int(h0.get("end_line") or 0),
                        text=code0,
                        why=args.query,
                        source="plate",
                        topic=args.query,
                        excerpt_chars=100,
                        session_id=sid,
                    )
                    h0["handle"] = span.get("handle")
                    h0["status"] = span.get("status") or "stored"
                except Exception:  # noqa: BLE001
                    pass
            try:
                from pipeline.work_session import touch

                touch(
                    repo,
                    [{"file": file0, "role": "plate"}] if file0 else [],
                    query=args.query,
                    session_id=sid,
                )
            except Exception:  # noqa: BLE001
                pass
        return _format(out, args.response_format)

    def map_impl(
        query: Annotated[
            str,
            Field(
                description=(
                    "Cold/new-topic flow query — denser CODE VOCABULARY 25–120 tokens "
                    "(target ≥40: symbols/paths/APIs/errors/tech/verbs across the problem surface). "
                    "Call 1 of incremental ladder."
                )
            ),
        ],
        k: Annotated[int, Field(description="How many cards (default 12).")] = 12,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """Soft locate (call 1): ranked cards + suggested_seed. No bodies. Then pack_context(mode=lean)."""
        import time as _time

        _map_t0 = _time.perf_counter()
        try:
            args = MapArgs(query=query, k=k, response_format=response_format)  # type: ignore[arg-type]
        except ValidationError as exc:
            return _err("map", str(exc), hint="Pass query= with code vocabulary.")
        sid = _resolve_session(session_id)
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()

        if not _is_repo_managed():
            return _managed_locate_err("map", repo)

        _note_locate_streak(repo)

        from pipeline.session_store import load_store

        qn = _norm_query(args.query)
        # Process-local cache first (identical query remaps after warmup).
        try:
            from pipeline.map_result_cache import get_map_cached

            hit = get_map_cached(repo=str(repo), query=args.query, fingerprint="soft_v1")
            if hit is not None:
                hit["elapsed_ms"] = round((_time.perf_counter() - _map_t0) * 1000, 1)
                hit["session_id"] = sid
                return _format(hit, args.response_format)
        except Exception:  # noqa: BLE001
            pass

        store = load_store(repo, session_id=sid)
        thrash = store.get("locate_thrash") or {}
        duplicate = qn in (thrash.get("seen") or [])
        cached_cards = _map_cache_get(store, qn, args.k) if duplicate else None
        if duplicate and cached_cards:
            cards = _enrich_map_cards(cached_cards, query=args.query)
            conf = _assess_map_confidence(args.query, cards)
            if conf.get("confidence") == "low":
                cards = cards[:3]
                for c in cards:
                    c["weak_match"] = True
            from pipeline.context_trace import (
                finalize_suggested_seed,
                map_ladder_next,
                pick_suggested_seed,
                pick_suggested_seeds,
            )

            suggested = pick_suggested_seed(cards, query=args.query)
            suggested = finalize_suggested_seed(
                Path(repo), suggested, query=args.query, load_repo=False
            )
            seeds_raw = pick_suggested_seeds(cards, query=args.query, limit=3)
            suggested_seeds = [
                finalize_suggested_seed(Path(repo), s, query=args.query, load_repo=False)
                or s
                for s in seeds_raw
            ]
            suggested_seeds = [s for s in suggested_seeds if s and s.get("file")]
            if suggested and not any(
                str(s.get("file")) == str(suggested.get("file"))
                and str(s.get("symbol") or "") == str(suggested.get("symbol") or "")
                for s in suggested_seeds
            ):
                suggested_seeds = [suggested] + suggested_seeds
            suggested_seeds = suggested_seeds[:3]
            out = {
                "ok": True,
                "tool": "map",
                "query": args.query,
                "k": args.k,
                "cards": cards,
                "count": len(cards),
                "scope": "indexed_chunks",
                "ranked_only": True,
                "cached": True,
                "session_id": sid,
                "suggested_seed": suggested,
                "suggested_seeds": suggested_seeds,
                "ladder": "map → pack(lean) → expand(delta) — ≤3 calls",
                "next": map_ladder_next(
                    cards,
                    suggested,
                    query=args.query,
                    suggested_seeds=suggested_seeds,
                ),
                "elapsed_ms": round((_time.perf_counter() - _map_t0) * 1000, 1),
                **conf,
            }
            return _format(out, args.response_format)

        # Reuse search path (hits only); duplicate queries get advisory usage_hint only
        raw = search_impl(
            query=args.query,
            k=args.k,
            include="hits",
            mode="soft",
            fetch=False,
            max_chars=1200,
            response_format=args.response_format,
            root=root,
            project_id=project_id,
            session_id=session_id,
        )
        try:
            card = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if not card.get("ok"):
            card["tool"] = "map"
            if card.get("error") and _is_transient_engine_error(str(card.get("error"))):
                card["should_retry"] = True
            return _format(card, args.response_format)
        card["tool"] = "map"
        card.pop("include", None)
        raw_cards = card.pop("results", [])
        card["cards"] = _enrich_map_cards(raw_cards, query=args.query)
        conf = _assess_map_confidence(args.query, card["cards"])
        card.update(conf)
        if conf.get("confidence") == "low":
            card["cards"] = card["cards"][:3]
            for c in card["cards"]:
                c["weak_match"] = True
        card["count"] = len(card.get("cards") or [])
        card["scope"] = "indexed_chunks"
        card["ranked_only"] = True
        card["session_id"] = sid
        try:
            from pipeline.context_trace import (
                finalize_suggested_seed,
                map_ladder_next,
                pick_suggested_seed,
                pick_suggested_seeds,
            )

            card["suggested_seed"] = finalize_suggested_seed(
                Path(repo),
                pick_suggested_seed(list(card.get("cards") or []), query=args.query),
                query=args.query,
                load_repo=False,
            )
            seeds_raw = pick_suggested_seeds(
                list(card.get("cards") or []), query=args.query, limit=3
            )
            suggested_seeds = [
                finalize_suggested_seed(
                    Path(repo), s, query=args.query, load_repo=False
                )
                or s
                for s in seeds_raw
            ]
            suggested_seeds = [s for s in suggested_seeds if s and s.get("file")]
            sug = card.get("suggested_seed")
            if sug and not any(
                str(s.get("file")) == str(sug.get("file"))
                and str(s.get("symbol") or "") == str(sug.get("symbol") or "")
                for s in suggested_seeds
            ):
                suggested_seeds = [sug] + suggested_seeds
            card["suggested_seeds"] = suggested_seeds[:3]
            card["ladder"] = "map → pack(lean) → expand(delta) — ≤3 calls"
            card["next"] = map_ladder_next(
                list(card.get("cards") or []),
                card.get("suggested_seed"),
                query=args.query,
                suggested_seeds=card.get("suggested_seeds"),
            )
        except Exception:  # noqa: BLE001
            card["suggested_seed"] = None
        try:
            _map_cache_put(repo, qn, args.k, list(card["cards"]), session_id=sid)
        except Exception:  # noqa: BLE001
            pass
        try:
            from pipeline.map_result_cache import put_map_cached

            put_map_cached(
                repo=str(repo),
                query=args.query,
                fingerprint="soft_v1",
                payload=card,
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            from pipeline.work_session import touch

            touch(
                _resolve_request_repo(root=root, project_id=project_id) or _default_repo(),
                [{"file": c.get("file"), "role": "map"} for c in (card.get("cards") or [])[:8]],
                query=args.query,
                session_id=_resolve_session(session_id),
            )
        except Exception:  # noqa: BLE001
            pass
        card["elapsed_ms"] = round((_time.perf_counter() - _map_t0) * 1000, 1)
        # Do not kick AST after map — 50MB pickle GIL-starves the following pack.
        # Pack (singleflight) / expand hydrate when those tools need the graph.
        return _format(card, args.response_format)

    def focus_impl(
        target: Annotated[str, Field(description="File path, path:line, or symbol from a map card.")] = "",
        mode: Annotated[
            str, Field(description="outline | span | neighbors | call_sites")
        ] = "span",
        path: Annotated[str, Field(description="Explicit repo-relative file.")] = "",
        query: Annotated[str, Field(description="Help pick span inside path.")] = "",
        start_line: Annotated[int, Field(description="Optional start line with path=.")] = 0,
        end_line: Annotated[int, Field(description="Optional end line with path=.")] = 0,
        budget: Annotated[
            str, Field(description="Read size: cap (~200 lines), wide (~350), full (~1k).")
        ] = "cap",
        max_chars: Annotated[int, Field(description="Body budget for span (budget sets default).")] = 50_000,
        max_neighbors: Annotated[int, Field(description="Cap neighbors spans.")] = 4,
        outline_offset: Annotated[int, Field(description="Paginate outline symbols.")] = 0,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """Prefer for opening bounded code to edit over full-file Read.
        Modes: outline | span | neighbors | call_sites (pick what you need).
        """
        try:
            args = FocusArgs(
                target=target, mode=mode, path=path, query=query,  # type: ignore[arg-type]
                start_line=start_line, end_line=end_line,
                budget=budget,  # type: ignore[arg-type]
                max_chars=max_chars, max_neighbors=max_neighbors,
                outline_offset=outline_offset,
                response_format=response_format,  # type: ignore[arg-type]
            )
        except ValidationError as exc:
            return _err("focus", str(exc), hint="Pass target= or path=; mode=outline|span|neighbors|call_sites.")
        sid = _resolve_session(session_id)
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()

        if not _is_repo_managed():
            return _managed_locate_err("focus", repo)

        path_s = (args.path or "").replace("\\", "/").strip()
        target_s = (args.target or "").strip()
        if not path_s and _looks_like_path(target_s):
            if ":" in target_s and not target_s.endswith(":"):
                head, _, tail = target_s.rpartition(":")
                if tail.isdigit():
                    path_s = head
                    if not args.start_line:
                        args.start_line = int(tail)
            path_s = path_s or target_s.replace("\\", "/")

        if args.mode == "call_sites":
            ident, scope_path = _parse_call_sites_symbol(
                query=args.query or "", target=target_s, path=path_s
            )
            if not ident or len(ident) < 2:
                return _err(
                    "focus",
                    "call_sites needs a symbol name in query= or target=",
                    hint="focus(query=func_name, mode=call_sites) or target=file.py:func_name",
                )
            try:
                sites = _call_sites_for_ident(
                    repo,
                    ident,
                    keep=max(1, min(int(args.max_neighbors or 4), 10)),
                    body_chars=min(int(args.max_chars or 6000), 4000),
                    scope_path=scope_path,
                )
            except Exception as exc:  # noqa: BLE001
                return _err("focus", str(exc), hint="Ensure the engine is warm.")
            card = {
                "ok": True,
                "tool": "focus",
                "mode": "call_sites",
                "ident": ident,
                "count": len(sites),
                "call_sites": _slim_spans(sites, keep=4, body_chars=400),
                "session_id": sid,
                "next": (
                    "grep(pattern) for import-only or dynamic refs; "
                    "focus(mode=span) on a hit file."
                ),
            }
            if not sites:
                card["usage_hint"] = (
                    f"No call sites for {ident!r} in scope. "
                    "Try grep(pattern) or broaden scope_path."
                )
            _phase_focus_remember(repo, _focus_key(ident, "call_sites", path_s or ident), card, session_id=sid)
            return _format(card, args.response_format)

        if args.mode == "outline":
            path_o = path_s or _resolve_to_file(repo, target_s or args.query)
            if not path_o:
                return _err(
                    "focus", "outline needs a file path",
                    hint="Pass path= or a path-like target=.",
                )
            try:
                res = _client_for(repo).outline(path_o.replace("\\", "/"), repo=str(repo))
            except Exception as exc:  # noqa: BLE001
                return _err("focus", str(exc), hint="Ensure the engine is warm.")
            backend_error = _backend_error(
                "focus", repo, res, hint="Ensure the engine is warm."
            )
            if backend_error:
                return backend_error
            symbols, symbols_total, symbols_capped = _slim_outline(
                res.get("symbols") or res.get("outline"),
                keep=_OUTLINE_KEEP_DEFAULT,
                offset=args.outline_offset,
            )
            card = {
                "ok": True,
                "tool": "focus",
                "mode": "outline",
                "file": res.get("path") or path_o,
                "path": res.get("path") or path_o,
                "count": len(symbols),
                "symbols": symbols,
                "symbols_total": symbols_total,
                "symbols_shown": len(symbols),
                "symbols_capped": symbols_capped,
                "session_id": sid,
                "next": "focus(same target, mode=span, start_line/end_line from symbols)",
            }
            if symbols_capped:
                nxt = args.outline_offset + len(symbols)
                card["next"] = f"focus(outline, outline_offset={nxt}) for more symbols"
            fp = str(card.get("file") or path_o)
            suffix = Path(fp).suffix.lower()
            if fp and suffix not in {".py", ".pyi"}:
                card["language_unsupported"] = True
                card["note"] = "outline is Python AST only; use focus(mode=span) for this file."
            _phase_focus_remember(repo, _focus_key(path_o, "outline", path_o), card, session_id=sid)
            return _format(card, args.response_format)

        key_target = path_s or target_s
        fkey = _focus_key(key_target, args.mode, path_s)

        detail = {"outline": "outline", "span": "body", "neighbors": "neighbors", "call_sites": "body"}[args.mode]
        raw = read_impl(
            target=args.target,
            path=path_s or args.path,
            query=args.query,
            handle="",
            start_line=args.start_line,
            end_line=args.end_line,
            detail=detail,
            neighbors=(args.mode == "neighbors"),
            max_neighbors=args.max_neighbors,
            budget=args.budget,
            max_chars=args.max_chars,
            response_format=args.response_format,
            root=root,
            project_id=project_id,
            session_id=session_id,
        )
        try:
            card = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        card["tool"] = "focus"
        card["mode"] = args.mode
        if card.get("detail") == "body":
            card["detail"] = "span"
        rem_path = str(card.get("file") or card.get("path") or path_s or target_s)
        rem_key = _focus_key(rem_path, args.mode, rem_path)
        if card.get("unchanged") or card.get("status") == "already_in_session":
            # Rematerialized body is already on the card - do not strip or hard-stop.
            card["already_shown"] = True
            card["ok"] = True
            card["should_retry"] = False
            if not (card.get("code") or card.get("excerpt") or card.get("text")):
                card["usage_hint"] = (
                    "already_in_session without body - call expand(handle) once."
                )
            else:
                card.pop("usage_hint", None)
            card["next"] = "Edit cited lines. Body rematerialized."
            card["session_id"] = sid
            _annotate_locate_dedup(card)
            _phase_focus_remember(repo, rem_key, card, session_id=sid)
            return _format(card, args.response_format)
        if not card.get("ok"):
            return _format(card, args.response_format)

        _phase_focus_remember(repo, rem_key, card, session_id=sid)
        card["session_id"] = sid
        if args.mode == "neighbors":
            card["neighbors_mode"] = card.get("neighbors_mode") or "import_adjacency"
            card["next"] = "See focus(mode=call_sites) for literal references; workspace(show) to reorient."
        else:
            code = card.get("code") or card.get("excerpt") or ""
            if card.get("truncated") or (isinstance(code, str) and "[truncated]" in code):
                card["truncated"] = True
            if card.get("truncated"):
                card["next"] = card.get("next") or (
                    f"focus(path={rem_path!r}, budget=wide|full, "
                    f"start_line={card.get('next_start_line') or card.get('start_line')}) "
                    f"or expand(handle={card.get('handle')!r})"
                )
            else:
                card["next"] = "Edit cited lines. Wiring: focus(mode=neighbors)."
        try:
            from pipeline.work_session import touch

            if rem_path:
                touch(
                    repo,
                    [{"file": rem_path, "role": f"focus:{args.mode}"}],
                    query=args.query or args.target,
                    session_id=sid,
                )
        except Exception:  # noqa: BLE001
            pass
        return _format(card, args.response_format)

    def workspace_impl(
        action: Annotated[str, Field(description="show | pin | clear")] = "show",
        path: Annotated[str, Field(description="Repo-relative file — required for pin.")] = "",
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """Mid-session brain: show pins/heatmap/focus_seen; pin a file; clear for new topic."""
        try:
            args = WorkspaceArgs(action=action, path=path, response_format=response_format)  # type: ignore[arg-type]
        except ValidationError as exc:
            return _err("workspace", str(exc), hint="action=show|pin|clear; path= required for pin.")
        sid = _resolve_session(session_id)
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()

        if not _is_repo_managed():
            return _managed_locate_err("workspace", repo)

        if args.action == "clear":
            from pipeline.session_store import clear_store
            from pipeline.work_session import clear_session

            clear_store(repo, session_id=sid)
            clear_session(repo, session_id=sid)
            return _format(
                {
                    "ok": True,
                    "tool": "workspace",
                    "action": "clear",
                    "next": "New topic — map(query) once, then pack_context(mode=lean).",
                },
                args.response_format,
            )

        if args.action == "pin":
            p = (args.path or "").replace("\\", "/").strip()
            if not p:
                return _err("workspace", "path required for pin", hint="workspace(action=pin, path='pkg/x.py')")
            from pipeline.work_session import pin as _pin

            sess = _pin(repo, p, session_id=sid)
            return _format(
                {
                    "ok": True,
                    "tool": "workspace",
                    "action": "pin",
                    "path": p,
                    "pins": list(sess.get("pins") or []),
                    "next": "workspace(show) to reorient; pack_context or host Read on pinned path.",
                },
                args.response_format,
            )

        # show
        from pipeline.session_store import load_store, recall as _recall
        from pipeline.work_session import heatmap, load_session

        store = load_store(repo, session_id=sid)
        sess = load_session(repo, session_id=sid)
        try:
            recalled = _recall(repo, need="", top_n=20, session_id=sid)
        except Exception:  # noqa: BLE001
            recalled = {"spans": [], "pins": [], "heatmap": []}
        focus_seen = store.get("focus_seen") or {}
        out = {
            "ok": True,
            "tool": "workspace",
            "action": "show",
            "session_id": sid,
            "topic": sess.get("topic") or store.get("topic") or "",
            "pins": list(sess.get("pins") or recalled.get("pins") or []),
            "heatmap": heatmap(repo, top_n=8, session_id=sid),
            "spans": recalled.get("spans") or [],
            "focus_seen": [
                {"key": k, **(v if isinstance(v, dict) else {"pointer": v})}
                for k, v in list(focus_seen.items())[-30:]
            ],
            "map_queries": list((store.get("locate_thrash") or {}).get("seen") or [])[-10:],
            "next": (
                "Use focus_seen to avoid redundant re-fetch. "
                "Deepen a new target with focus, or edit."
            ),
        }
        return _format(out, args.response_format)

    # ---- status (all surfaces) --------------------------------------------
    def gate_impl(
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """Session gate — ~5 tokens. Call once at chat start instead of status()."""
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            from pipeline.pause_resume import is_paused

            if is_paused():
                return _paused_gate_response()
            try:
                from pipeline.mcp_lifecycle import ensure_mcp_runtime

                ensure_mcp_runtime(_default_repo(), blocking=False)
            except Exception:  # noqa: BLE001
                pass
            line = _gate_line(just_checked=True)
            if line.startswith("1:"):
                try:
                    from pipeline.client import EngineClient

                    if not EngineClient(timeout=1.5).healthy():
                        line = f"{line} warming retry:3"
                except Exception:  # noqa: BLE001
                    line = f"{line} warming retry:3"
                sess = _session_fields(session_id)
                sid = sess.get("session_id") or _resolve_session(session_id)
                if sid:
                    line = f"{line} sid:{sid}"
                if sess.get("shared_process_risk"):
                    line = f"{line} shared"
                    hint = sess.get("hint") or (
                        "Pass a distinct session_id per chat or set CTX_MCP_SESSION_ID in MCP env."
                    )
                    return f"{line}\n{hint}"
            return line

    def status_impl(
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
        detail: Annotated[
            str,
            Field(
                description=(
                    "summary = default agent card (no keeper dump). "
                    "full = engine health + session + keeper. "
                    "gate = same ~5-token line as gate() — use for managed checks."
                ),
            ),
        ] = "summary",
    ) -> str:
        """Health / tool list only — not for finding code."""
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            if (detail or "summary").strip().lower() == "gate":
                from pipeline.pause_resume import is_paused

                if is_paused():
                    return _paused_gate_response()
                return _gate_line(just_checked=True)

            from pipeline.pause_resume import is_paused

            if is_paused():
                # Polling status cannot unpause. Recheck after resume / user ask / TTL.
                from pipeline.lifecycle_guidance import next_actions, primary_recovery_action

                guide = next_actions(_default_repo())
                fields = _managed_signal_fields(just_checked=True)
                fields.update({
                    "ok": False,
                    "paused": True,
                    "tool": "status",
                    "server": "scubiee",
                    "managed": False,
                    "should_use_mcp": False,
                    "should_retry_status": False,
                    "lifecycle_state": guide.get("state"),
                    "next_action": primary_recovery_action(guide) or "scubiee resume",
                    "agent_action": (guide.get("steps") or [{}])[0].get("action"),
                    "hint": (
                        "Scubiee is stopped. Do not call Scubiee MCP tools. "
                        "Use the host's native file/search tools. User: scubiee resume (not init)."
                    ),
                    "lifecycle": guide,
                })
                return _dumps(fields)

            from pipeline.client import EngineClient
            from pipeline.mcp_lifecycle import current_client_id, ensure_mcp_runtime
            from pipeline.session_store import load_store, token_mode

            tool_lists = {
                "read": ["gate", "search", "read", "status"],
                "nav": ["gate", "search", "files", "read", "recall", "expand", "status"],
                "graph": ["gate", "search", "neighbors", "graph", "status"],
                "rich": ["gate", "search", "read", "outline", "status"],
                "search": ["gate", "search", "status"],
                "grep": ["gate", "grep", "status"],
                "phase": _phase_tool_names(),
            }
            try:
                repo = _default_repo()
                sid = _resolve_session(session_id)
                sess = _session_fields(session_id)
                try:
                    ensure_mcp_runtime(
                        repo,
                        client_id=current_client_id() or _MCP_CLIENT_ID,
                        blocking=False,
                    )
                except Exception:  # noqa: BLE001
                    pass
                from pipeline.session_isolation import mcp_client_name

                eng = EngineClient(
                    timeout=8.0 if (detail or "summary").strip().lower() != "full" else 20.0,
                    workspace_path=str(repo),
                    client=mcp_client_name(),
                    session_id=sid,
                )
                store = load_store(repo, session_id=sid)
                healthy = eng.healthy()
                opened: dict[str, Any] = {}
                health_payload: dict[str, Any] = {}
                detail_s = (detail or "summary").strip().lower()
                if healthy:
                    try:
                        health_payload = eng.health() if hasattr(eng, "health") else {}
                    except Exception:  # noqa: BLE001
                        health_payload = {}
                    soft_from_health = bool(
                        isinstance(health_payload, dict)
                        and health_payload.get("soft_search_ready")
                    )
                    try:
                        from pipeline.mcp_lifecycle import mark_soft_ready, soft_ready_cached

                        # Soft already confirmed — skip open_repo HTTP (was multi-second).
                        if soft_ready_cached() or soft_from_health:
                            mark_soft_ready()
                            opened = {
                                "ok": True,
                                "project_id": (
                                    (health_payload.get("project_id") if isinstance(health_payload, dict) else None)
                                    or getattr(eng, "project_id", None)
                                ),
                                "soft_search_ready": True,
                                "warm_state": (
                                    (health_payload.get("warm_state") if isinstance(health_payload, dict) else None)
                                    or "ready"
                                ),
                                "skipped": "soft_cached",
                                "engine": True,
                            }
                        else:
                            # Bind the workspace the same way map/pack do — otherwise
                            # soft_search_ready stays false and agents see eternal "warming".
                            opened = eng.open_repo(str(repo), wait=False)
                            soft_ok = bool(
                                (isinstance(opened, dict) and opened.get("ok") is not False and opened.get("project_id"))
                                or soft_from_health
                            )
                            if soft_ok:
                                mark_soft_ready()
                    except Exception as exc:  # noqa: BLE001
                        opened = {"ok": False, "error": str(exc)}
                daemon_status: dict[str, Any] = {}
                # summary: avoid full /v1/status keeper dump — health + open_repo + local probe.
                if healthy and detail_s == "full":
                    try:
                        daemon_status = eng.status(str(repo))
                    except Exception as exc:  # noqa: BLE001
                        # Honest starting/unbound — never fake warm_state=ready.
                        daemon_status = {
                            "ok": False,
                            "error": f"status_unreachable: {exc}",
                            "warm_state": "warming",
                            "hint": "Run: scubiee engine ensure .",
                        }
                elif healthy:
                    warm_from_open = (
                        opened.get("warm_state")
                        if isinstance(opened, dict)
                        else None
                    )
                    soft_skipped = bool(
                        isinstance(opened, dict) and opened.get("skipped") == "soft_cached"
                    )
                    daemon_status = {
                        "ok": bool(opened.get("ok", True)) if isinstance(opened, dict) else True,
                        "warm_state": warm_from_open or "ready",
                        "warm_error": (opened.get("error") if isinstance(opened, dict) and opened.get("ok") is False else None),
                        "project_id": (opened.get("project_id") if isinstance(opened, dict) else None),
                        "soft_search_ready": bool(
                            soft_skipped
                            or (
                                isinstance(opened, dict)
                                and opened.get("ok") is not False
                                and opened.get("project_id")
                            )
                            or (
                                isinstance(health_payload, dict)
                                and health_payload.get("soft_search_ready")
                            )
                        ),
                        "engine": opened.get("engine") if isinstance(opened, dict) else True,
                    }
                    # Soft path: trust health chunks — skip open_repo; peek only
                    # if project_id still missing (local disk, not HTTP).
                    if soft_skipped and isinstance(health_payload, dict):
                        chunks = int(health_payload.get("chunks") or 0)
                        if chunks > 0:
                            daemon_status["meta"] = {"chunks": chunks}
                        if health_payload.get("project_id"):
                            daemon_status["project_id"] = (
                                daemon_status.get("project_id") or health_payload.get("project_id")
                            )
                        if not daemon_status.get("project_id"):
                            try:
                                from pipeline.project_id import peek_project

                                ref = peek_project(repo)
                                if ref is not None:
                                    daemon_status["project_id"] = ref.project_id
                            except Exception:  # noqa: BLE001
                                pass
                    else:
                        try:
                            from pipeline.project_id import index_is_usable, peek_project

                            ref = peek_project(repo)
                            if ref is not None:
                                daemon_status["project_id"] = daemon_status.get("project_id") or ref.project_id
                                usable = index_is_usable(ref.store_dir)
                                daemon_status["meta"] = {"chunks": 1 if usable else 0}
                                if not usable:
                                    daemon_status["soft_search_ready"] = False
                                    daemon_status["warm_state"] = "warming"
                        except Exception:  # noqa: BLE001
                            pass
                else:
                    daemon_status = {
                        "ok": False,
                        "error": f"Scubiee unreachable at {eng.base}",
                        "hint": "Run: scubiee engine ensure .",
                    }
                bound_pid = (
                    daemon_status.get("project_id")
                    or (opened.get("project_id") if isinstance(opened, dict) else None)
                )
                meta = daemon_status.get("meta") if isinstance(daemon_status.get("meta"), dict) else None
                warm_state = daemon_status.get("warm_state") if healthy else None
                warm_error = (
                    daemon_status.get("warm_error")
                    if healthy
                    else daemon_status.get("error")
                )
                index_usable = None
                if isinstance(meta, dict) and "chunks" in meta:
                    index_usable = int(meta.get("chunks") or 0) > 0
                soft_search_ready = bool(
                    healthy
                    and not warm_error
                    and str(warm_state or "").lower() in {"ready", "idle", ""}
                    and bound_pid
                    and (index_usable is not False)
                    and (
                        daemon_status.get("soft_search_ready")
                        if "soft_search_ready" in daemon_status
                        else (daemon_status.get("engine") is not None or bound_pid)
                    )
                )
                embedder_loaded: bool | None = None
                if healthy:
                    if "embedder_loaded" in daemon_status:
                        embedder_loaded = bool(daemon_status.get("embedder_loaded"))
                    elif isinstance(health_payload, dict) and "embedder_loaded" in health_payload:
                        embedder_loaded = bool(health_payload.get("embedder_loaded"))
                    else:
                        mem = daemon_status.get("memory") if isinstance(daemon_status.get("memory"), dict) else {}
                        if "embedder_loaded" in mem:
                            embedder_loaded = bool(mem.get("embedder_loaded"))
                from pipeline.sync_status import build_sync_contract, derive_locate_state

                contract = build_sync_contract(
                    warm_state=warm_state,
                    warm_error=warm_error,
                    keeper=daemon_status.get("keeper") if healthy else None,
                    soft_search_ready=soft_search_ready,
                    last_error=None if healthy else daemon_status.get("error"),
                )
                if healthy:
                    for key in (
                        "sync_state",
                        "ready",
                        "syncing",
                        "overlay_ready",
                        "dense_pending",
                        "deferred",
                        "needs_full",
                        "locate_streak_active",
                        "publish_pending",
                        "catchup_chunked",
                    ):
                        if key in daemon_status:
                            contract[key] = daemon_status[key]
                    contract["error"] = daemon_status.get("error") if daemon_status.get("ok") is False else None
                managed = _is_repo_managed()
                warming = bool(managed and not healthy)
                locate = derive_locate_state(
                    healthy=healthy,
                    soft_search_ready=soft_search_ready,
                    warm_state=warm_state,
                    warm_error=str(warm_error or "") or None,
                    project_bound=bool(bound_pid),
                    index_usable=index_usable,
                    sync_state=str(contract.get("sync_state") or "ready"),
                    syncing=bool(contract.get("syncing")),
                )
                # Prefer explicit locate over sync-contract default when unbound.
                contract["locate"] = locate
                payload: dict[str, Any] = {
                    # ok = daemon reachable only. Do not conflate with managed (agents misread
                    # readiness when ok=true while warming=true). Use warming branch in rules.
                    "ok": healthy,
                    "tool": "status",
                    "server": "scubiee",
                    "surface": surface,
                    "engine": {
                        "healthy": healthy,
                        "soft_search_ready": soft_search_ready,
                        "warm_state": warm_state,
                        "warm_error": warm_error,
                        "project_id": bound_pid,
                        "embedder_loaded": embedder_loaded,
                        "meta": meta,
                    },
                    "repo": str(repo),
                    "token_mode": token_mode(),
                    # Managed check: user can ask the agent to call status() anytime
                    # to re-test after scubiee init / connect.
                    **_managed_signal_fields(just_checked=True),
                    "warming": warming,
                    "index_available": bool(index_usable),
                    "embedder_loaded": embedder_loaded,
                    "semantic_ready": bool(embedder_loaded) if embedder_loaded is not None else None,
                    "tools": tool_lists.get(surface, tool_lists["read"]),
                    "keeper": _slim_status_keeper(daemon_status.get("keeper") if healthy else None),
                    "soft_search_ready": soft_search_ready,
                    **contract,
                    "locate": locate,
                    "session": {
                        "session_id": sid,
                        "source": sess.get("source"),
                        "host": sess.get("host"),
                        "shared_process_risk": bool(sess.get("shared_process_risk")),
                        "env_key": sess.get("env_key"),
                        "hint": sess.get("hint"),
                        "topic": store.get("topic"),
                        "n_spans": len(store.get("spans") or {}),
                        "n_focus_seen": len(store.get("focus_seen") or {}),
                        "ledger": store.get("ledger") or {},
                    },
                }
                if warming:
                    payload["hint"] = (
                        "Engine is warming. Wait ~3s and retry the same locate tool once. "
                        "Do not poll status() in a loop. Process tree: Cursor→mcp_bridge→mcp_locate "
                        "(+ separate engine pythonw)."
                    )
                elif embedder_loaded is False:
                    payload["hint"] = (
                        "Index up; FastEmbed still loading. Wait ~3s and retry map once — "
                        "do not claim fully ready until embedder_loaded=true."
                    )
                elif locate.get("state") == "unbound":
                    payload["hint"] = (
                        "Repo not bound — map/pack auto-bind; or run: scubiee engine ensure ."
                    )
                from pipeline.sync_status import derive_agent_ready, derive_agent_ready_note

                payload["agent_ready"] = derive_agent_ready(
                    healthy=healthy,
                    soft_search_ready=soft_search_ready,
                    sync_state=str(contract.get("sync_state") or "ready"),
                    ready=bool(contract.get("ready")),
                    syncing=bool(contract.get("syncing")),
                    overlay_ready=bool(contract.get("overlay_ready")),
                    publish_pending=bool(contract.get("publish_pending")),
                    warming=warming,
                    warm_state=warm_state,
                    warm_error=str(warm_error or "") or None,
                    project_bound=bool(bound_pid),
                    locate=locate,
                    embedder_loaded=embedder_loaded,
                )
                payload["agent_ready_note"] = derive_agent_ready_note(
                    agent_ready=payload["agent_ready"],
                    sync_state=str(contract.get("sync_state") or "ready"),
                    syncing=bool(contract.get("syncing")),
                    overlay_ready=bool(contract.get("overlay_ready")),
                    publish_pending=bool(contract.get("publish_pending")),
                    ready=bool(contract.get("ready")),
                    locate=locate,
                    embedder_loaded=embedder_loaded,
                )
                try:
                    from pipeline.runtime_controller import RuntimeController

                    snap = RuntimeController.get().snapshot(repo=repo)
                    payload.update(snap.as_status_fields())
                    # Honesty: never claim warm_ready without embedder.
                    if payload.get("embedder_loaded") is False:
                        payload["warm_ready"] = False
                        payload["warm_ready_map"] = False
                    elif snap.embedder_loaded and payload.get("embedder_loaded") is None:
                        payload["embedder_loaded"] = True
                except Exception:  # noqa: BLE001
                    try:
                        from pipeline.warm_contract import warm_status_fields

                        payload.update(
                            warm_status_fields(
                                engine_healthy=bool(healthy),
                                embedder_loaded=embedder_loaded,
                                need_ast=False,
                            )
                        )
                    except Exception:  # noqa: BLE001
                        pass
                # Honest should_use from locate.state (managed alone is not enough).
                signals = _managed_signal_fields(just_checked=True)
                signals["should_use_mcp"] = bool(
                    managed and locate.get("should_use") is not False
                )
                if locate.get("state") == "error":
                    signals["should_use_mcp"] = False
                    signals["should_retry_status"] = False
                payload.update(signals)
                try:
                    from pipeline.lifecycle_guidance import next_actions, primary_recovery_action

                    guide = next_actions(repo)
                    payload["lifecycle"] = guide
                    if guide.get("state") != "ready":
                        recovery = primary_recovery_action(guide)
                        if recovery:
                            payload.setdefault("next_action", recovery)
                            for step in guide.get("steps") or []:
                                if step.get("action") == recovery:
                                    payload.setdefault(
                                        "lifecycle_hint",
                                        str(step.get("why") or ""),
                                    )
                                    break
                except Exception:  # noqa: BLE001
                    pass
                detail_s = (detail or "summary").strip().lower()
                if detail_s == "full":
                    return _dumps(_attach_gate(payload))
                return _dumps(_attach_gate(_summarize_status_payload(payload)))
            except Exception as exc:  # noqa: BLE001
                return _err("status", str(exc))

    def register_project_impl(
        path: str = "",
        always_allow: bool = False,
        fast: bool = False,
        response_format: Literal["json", "markdown"] = "json",
    ) -> str:
        """Register and optionally index a repository after user consent."""
        from pipeline.registration import register_project

        repo = Path(path).resolve() if path.strip() else _default_repo()
        try:
            result = register_project(
                repo,
                always_allow=always_allow,
                index=True,
                fast=fast,
                confirm=False,
            )
            out = result.to_dict()
            out["tool"] = "register_project"
            if not result.ok:
                return _err("register_project", str(out.get("error") or "registration failed"))
            return _format(out, response_format)
        except Exception as exc:  # noqa: BLE001
            from pipeline.incremental import IndexConfirmRequired

            if isinstance(exc, IndexConfirmRequired):
                payload = exc.to_payload(repo)
                payload["tool"] = "register_project"
                return _format(payload, response_format)
            return _err("register_project", str(exc))

    def map_context_impl(
        query: Annotated[
            str,
            Field(
                description=(
                    "Descriptive task paragraph — prefer concrete symbols, APIs, file/module "
                    "paths, error tokens, and action verbs (write/apply/verify/decode/install). "
                    "Richer wording sharpens the trace after you pick a seed."
                )
            ),
        ],
        seed_file: Annotated[str, Field(description="Seed file path relative to repo (e.g. app/middleware/auth.py).")],
        seed_symbol: Annotated[str, Field(description="Seed symbol/function (optional if seed_line set).")] = "",
        seed_line: Annotated[int, Field(description="Line inside seed function (optional if seed_symbol set).")] = 0,
        seed2_file: Annotated[str, Field(description="Optional second seed file.")] = "",
        seed2_symbol: Annotated[str, Field(description="Optional second seed symbol.")] = "",
        seed2_line: Annotated[int, Field(description="Optional second seed line.")] = 0,
        seed3_file: Annotated[str, Field(description="Optional third seed file.")] = "",
        seed3_symbol: Annotated[str, Field(description="Optional third seed symbol.")] = "",
        seed3_line: Annotated[int, Field(description="Optional third seed line.")] = 0,
        k: Annotated[int, Field(description="Max heatmap cards (default 24).")] = 24,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """Context TRACE guide: descriptive query+seed → ranked loc+score heatmap. Prefer rich code words; native Read/Grep top-down."""
        sid = _resolve_session(session_id)
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()
        if not _is_repo_managed():
            return _managed_locate_err("map_context", repo)
        try:
            from pipeline.context_trace import persist_trace, run_map_context

            out = run_map_context(
                repo,
                query,
                seed_file=seed_file,
                seed_symbol=seed_symbol,
                seed_line=int(seed_line or 0),
                seed2_file=seed2_file,
                seed2_symbol=seed2_symbol,
                seed2_line=int(seed2_line or 0),
                seed3_file=seed3_file,
                seed3_symbol=seed3_symbol,
                seed3_line=int(seed3_line or 0),
                k=max(4, min(int(k or 24), 48)),
            )
            out["session_id"] = sid
            if out.get("ok"):
                persist_trace(repo, sid, out.pop("_persist", {}))
                try:
                    from pipeline.work_session import touch

                    touch(
                        repo,
                        [{"file": c.get("file"), "role": "map_context"} for c in (out.get("heatmap") or [])[:12]],
                        query=query,
                        session_id=sid,
                    )
                except Exception:  # noqa: BLE001
                    pass
            else:
                out["tool"] = "map_context"
            return _format(out, response_format)
        except Exception as exc:  # noqa: BLE001
            return _err("map_context", str(exc))

    def expand_context_impl(
        node: Annotated[
            str,
            Field(
                description=(
                    "Heatmap node id (file::symbol) or file path to grow from. "
                    "Optional: falls back to seed_file/seed_symbol, then to the "
                    "hottest card of the current trace."
                )
            ),
        ] = "",
        seed_file: Annotated[
            str,
            Field(description="Alias of node by path — same vocabulary as pack_context."),
        ] = "",
        seed_symbol: Annotated[
            str,
            Field(description="Symbol within seed_file — same vocabulary as pack_context."),
        ] = "",
        direction: Annotated[
            str,
            Field(
                description=(
                    "callees|callers|effects|config|broad|all (default all). "
                    "Use callers when upward refs missing; effects for log/track/send; "
                    "broad for structural 1-hop escape from a strict pack."
                )
            ),
        ] = "all",
        intent: Annotated[
            str,
            Field(description="Alias of direction (callers|effects|…). Empty = use direction."),
        ] = "",
        query: Annotated[
            str,
            Field(
                description=(
                    "Keep a descriptive code-heavy reminder (symbols/paths/verbs); "
                    "defaults to last map query if empty."
                )
            ),
        ] = "",
        k: Annotated[int, Field(description="Max DELTA cards (default 10).")] = 10,
        with_bodies: Annotated[
            bool,
            Field(description="If true, also pack ≤max_bodies lean bodies for new delta cards."),
        ] = False,
        budget_chars: Annotated[
            int, Field(description="Body budget when with_bodies=true (default 4000).")
        ] = 4000,
        max_bodies: Annotated[
            int, Field(description="Max delta bodies when with_bodies=true (default 3).")
        ] = 3,
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """Call 3 ladder: delta cards (+ optional bodies). direction=callers|effects|broad for flexibility."""
        sid = _resolve_session(session_id)
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()
        if not _is_repo_managed():
            return _managed_locate_err("expand_context", repo)
        try:
            from pipeline.context_trace import (
                ast_cache_ready,
                hydrate_ast_bundle,
                load_trace,
                persist_trace,
                run_expand_context,
            )

            # Prefer disk-bundle hydrate. Never cold-bake AST on the MCP request
            # thread — that GIL-starves the locate worker for 20s+ and Cursor
            # often opens a second bridge while the first is wedged.
            t_hyd = time.perf_counter()
            hyd = hydrate_ast_bundle(repo, bake_on_miss=False)
            hyd_ms = round((time.perf_counter() - t_hyd) * 1000, 1)
            if not ast_cache_ready(repo):
                try:
                    from pipeline.mcp_lifecycle import start_ast_hydrate_bg

                    start_ast_hydrate_bg(repo)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    import threading

                    def _bg_bake() -> None:
                        try:
                            hydrate_ast_bundle(repo, bake_on_miss=True)
                        except Exception:  # noqa: BLE001
                            pass

                    threading.Thread(
                        target=_bg_bake, name="scubiee-expand-ast-bake", daemon=True
                    ).start()
                except Exception:  # noqa: BLE001
                    pass
                return _err(
                    "expand_context",
                    "ast_warming",
                    hint=(
                        f"AST bundle not ready (hydrate={hyd.get('source') or hyd.get('error')}, "
                        f"{hyd_ms}ms). Background bake started — retry expand_context in a few "
                        "seconds; map/pack stay available."
                    ),
                    status="warming",
                    hydrate_ms=hyd_ms,
                )

            prior = load_trace(repo, sid)
            # Only skip already-expanded hops — NOT the whole pack heatmap
            # (that made callers/effects empty after dense packs).
            prior_ids = {str(x) for x in (prior.get("expanded_ids") or []) if x}
            pack_seen_ids = {c.get("id") for c in (prior.get("cards") or []) if c.get("id")}
            prior_packed = {str(x) for x in (prior.get("packed_ids") or []) if x}
            q = (query or "").strip() or str(prior.get("query") or "")
            target = _resolve_expand_node(node, seed_file, seed_symbol, prior)
            if not target:
                return _err(
                    "expand_context",
                    "no node to expand from",
                    hint=(
                        "Pass node=file::symbol (or seed_file=/seed_symbol=), "
                        "or run map/pack_context first so a trace exists."
                    ),
                )
            out = run_expand_context(
                repo,
                target,
                query=q,
                direction=direction or "all",
                intent=intent or "",
                k=max(4, min(int(k or 12), 24)),
                prior_ids=prior_ids,  # type: ignore[arg-type]
                pack_seen_ids=pack_seen_ids,  # type: ignore[arg-type]
                with_bodies=bool(with_bodies),
                budget_chars=max(400, int(budget_chars or 4000)),
                max_bodies=max(1, min(int(max_bodies or 3), 8)),
                prior_packed_ids=prior_packed,
            )
            out["session_id"] = sid
            out["hydrate_ms"] = hyd_ms
            out["hydrate_source"] = hyd.get("source")
            if out.get("ok"):
                # merge delta into persisted cards
                cards = list(prior.get("cards") or [])
                seen = {c.get("id") for c in cards}
                for c in out.get("delta") or []:
                    if c.get("id") not in seen:
                        cards.append(c)
                        seen.add(c.get("id"))
                packed = set(prior_packed) | {str(x) for x in (out.get("_persist_packed") or []) if x}
                expanded = set(prior_ids) | {
                    str(x) for x in (out.get("_persist_ids") or []) if x
                }
                persist_trace(
                    repo,
                    sid,
                    {
                        "query": q,
                        "seed_id": prior.get("seed_id"),
                        "cards": cards,
                        "scores": {c["id"]: c.get("score") for c in cards if c.get("id")},
                        "packed_ids": sorted(packed),
                        "expanded_ids": sorted(expanded),
                    },
                )
                out.pop("_persist_packed", None)
                out.pop("_persist_ids", None)
            return _format(out, response_format)
        except Exception as exc:  # noqa: BLE001
            return _err("expand_context", str(exc))

    def _make_pack_impl(*, tool_name: str, engine: str, doc: str):
        def pack_impl(
            query: Annotated[
                str,
                Field(
                    description=(
                        "ENRICHED pack query after map (25–120 tokens, target ≥40). "
                        "Fold suggested_seeds file::symbol + hot cards + APIs/errors/paths "
                        "from the problem surface — denser and more specific than the map query."
                    )
                ),
            ],
            seed_file: Annotated[str, Field(description="Seed file path relative to repo.")],
            seed_symbol: Annotated[
                str, Field(description="Seed symbol (optional if seed_line set).")
            ] = "",
            seed_line: Annotated[int, Field(description="Line inside seed function.")] = 0,
            seed2_file: Annotated[
                str,
                Field(
                    description=(
                        "Optional second seed (from suggested_seeds[1]) — enables "
                        "multi_seed_v1 agreement+corridor merge."
                    )
                ),
            ] = "",
            seed2_symbol: Annotated[str, Field(description="Optional second seed symbol.")] = "",
            seed2_line: Annotated[int, Field(description="Optional second seed line.")] = 0,
            seed3_file: Annotated[
                str,
                Field(description="Optional third seed (from suggested_seeds[2])."),
            ] = "",
            seed3_symbol: Annotated[str, Field(description="Optional third seed symbol.")] = "",
            seed3_line: Annotated[int, Field(description="Optional third seed line.")] = 0,
            mode: Annotated[
                str,
                Field(
                    description=(
                        "lean (default): compressed heatmap locs only (no bodies). "
                        "full: larger heatmap card set. Native-Read top heats; "
                        "collect_hot_context only if you need bodies batched."
                    )
                ),
            ] = "lean",
            policy: Annotated[
                str,
                Field(
                    description=(
                        "strict (default). On pack_context only: broad = one-shot polytrace escape. "
                        "Ignored for pack_poly_embed / pack_semantic (engine is fixed)."
                    )
                ),
            ] = "strict",
            k: Annotated[int, Field(description="Max heatmap cards (default 16).")] = 16,
            hot_threshold: Annotated[
                float,
                Field(
                    description=(
                        "Min score for hot labeling on the heatmap (default 0.65). "
                        "Default pack is heatmap-only; use collect_hot_context or "
                        "include_bodies=1 / CTX_MCP_PACK_BODIES=1 for bodies."
                    )
                ),
            ] = 0.65,
            budget_chars: Annotated[
                int,
                Field(
                    description=(
                        "Total char budget for collected bodies. Applies only when "
                        "bodies are collected (include_bodies=1 or "
                        "CTX_MCP_PACK_BODIES=1); otherwise heatmap-only and this is inert."
                    )
                ),
            ] = 0,
            max_bodies: Annotated[
                int,
                Field(
                    description=(
                        "Max hot bodies to collect. Applies only when bodies are "
                        "collected (include_bodies=1 or CTX_MCP_PACK_BODIES=1); "
                        "otherwise heatmap-only and this is inert."
                    )
                ),
            ] = 0,
            include_bodies: Annotated[
                int,
                Field(
                    description=(
                        "Opt-in: 1 = collect and return hot code bodies in the pack "
                        "payload (subject to budget_chars / max_bodies). "
                        "0/unset = env CTX_MCP_PACK_BODIES decides; default is "
                        "heatmap/locs only (no bodies)."
                    )
                ),
            ] = 0,
            response_format: Annotated[
                str, Field(description="json (default) or markdown.")
            ] = "json",
            root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
            project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
            session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
        ) -> str:
            sid = _resolve_session(session_id)
            with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
                repo = _default_repo()
            if not _is_repo_managed():
                return _managed_locate_err(tool_name, repo)
            _note_locate_streak(repo)
            try:
                from pipeline.context_trace import (
                    ast_cache_ready,
                    hydrate_ast_bundle,
                    load_trace,
                    persist_trace,
                    run_pack_context,
                )
                from pipeline.mcp_lifecycle import join_attach_warm_if_needed

                # Lean heatmap: never cold-bake or load a 50MB AST pickle on the
                # request thread (GIL + disk → multi-second). Prefer in-process
                # AST cache; otherwise build a search-seed heatmap (sub-second).
                mode_n = (mode or "lean").strip().lower() or "lean"
                want_bodies = _resolve_pack_bodies(include_bodies)
                policy_n = (policy or "strict").strip().lower() or "strict"
                # Search/map-reuse lean path: heatmap only. Broad/escape packs and
                # body packs still go through run_pack_context.
                lean_fast = (
                    mode_n in {"lean", "heatmap"}
                    and not want_bodies
                    and policy_n in {"strict", "lean"}
                )
                if not lean_fast:
                    # Full/AST packs may join attach; lean never waits on serve-join
                    # (observed ~3–4s LOCATE_SLA when warm_ready briefly flapped).
                    join_attach_warm_if_needed(repo, need_ast=False)
                if lean_fast:
                    # Lean heatmap only — do not kick AST hydrate here.
                    # Parallel 50MB pickle IO GIL-starves map-reuse/search on
                    # the same worker. expand/collect hydrate when they need it.
                    from pipeline.session_store import load_store

                    t_pack = time.perf_counter()
                    heatmap: list[dict[str, Any]] = []
                    seed_file_n = (seed_file or "").replace("\\", "/")
                    seed_card = {
                        "id": f"{seed_file_n}::{seed_symbol}" if seed_symbol else seed_file_n,
                        "file": seed_file_n,
                        "symbol": seed_symbol or "",
                        "start_line": int(seed_line or 0) or None,
                        "end_line": None,
                        "score": 1.0,
                        "heat": "hot",
                        "rank": 1,
                        "why": "seed",
                        "loc": (
                            f"{seed_file_n}:{int(seed_line or 0)}"
                            if seed_file_n and int(seed_line or 0)
                            else seed_file_n
                        ),
                    }
                    if seed_card.get("file"):
                        heatmap.append(seed_card)

                    # Prefer recent map cards (process cache, then session) —
                    # avoids a second engine search that GIL-contended to ~3–4s.
                    engine_tag = "map_reuse"
                    cards: list[dict[str, Any]] = []
                    try:
                        from pipeline.map_result_cache import get_recent_map_cards

                        cards = get_recent_map_cards(repo=str(repo), limit=max(4, min(int(k or 16), 48)))
                    except Exception:  # noqa: BLE001
                        cards = []
                    if not cards:
                        try:
                            store = load_store(repo, session_id=sid)
                            qn = _norm_query(query)
                            cache = store.get("map_cache") or {}
                            row = cache.get(qn)
                            cards = list((row or {}).get("cards") or [])
                            if not cards:
                                for _qk, crow in sorted(
                                    cache.items(),
                                    key=lambda kv: float((kv[1] or {}).get("ts") or 0),
                                    reverse=True,
                                ):
                                    cards = list((crow or {}).get("cards") or [])
                                    if cards:
                                        break
                        except Exception:  # noqa: BLE001
                            cards = []
                    for i, c in enumerate(cards, start=2):
                        f = str(c.get("file") or "").replace("\\", "/")
                        if not f or f == seed_card.get("file"):
                            continue
                        s = int(c.get("start_line") or 0)
                        e = int(c.get("end_line") or 0)
                        heatmap.append(
                            {
                                "id": str(c.get("id") or (f"{f}:{s}-{e}" if s and e else f)),
                                "file": f,
                                "symbol": str(c.get("symbol") or ""),
                                "start_line": s or None,
                                "end_line": e or None,
                                "score": float(c.get("score") or 0.0),
                                "heat": (
                                    "hot"
                                    if float(c.get("score") or 0) >= float(hot_threshold or 0.65)
                                    else "warm"
                                ),
                                "rank": i,
                                "why": (c.get("why") or "")[:160],
                                "loc": c.get("loc")
                                or (f"{f}:{s}-{e}" if s and e else f),
                            }
                        )

                    # Search only if map reuse left us thin (standalone pack).
                    if len(heatmap) < 3:
                        engine_tag = "search_lean"
                        hits_raw: list[dict[str, Any]] = []
                        try:
                            from pipeline.client import EngineClient
                            from pipeline.mcp_lifecycle import soft_ready_cached
                            from pipeline.session_isolation import mcp_client_name

                            if soft_ready_cached():
                                res = EngineClient(
                                    workspace_path=str(repo),
                                    client=mcp_client_name(),
                                    timeout=3.0,
                                ).search(
                                    query,
                                    top_k=max(4, min(int(k or 16), 48)),
                                    path=str(repo),
                                )
                                if isinstance(res, dict) and res.get("ok") is not False:
                                    hits_raw = list(res.get("hits") or [])
                        except Exception:  # noqa: BLE001
                            hits_raw = []
                        seen = {str(h.get("file") or "").replace("\\", "/") for h in heatmap}
                        for i, h in enumerate(hits_raw, start=len(heatmap) + 1):
                            f = str(h.get("file") or h.get("path") or "").replace("\\", "/")
                            if not f or f in seen:
                                continue
                            seen.add(f)
                            s = int(h.get("start_line") or 0)
                            e = int(h.get("end_line") or 0)
                            heatmap.append(
                                {
                                    "id": f"{f}:{s}-{e}" if s and e else f,
                                    "file": f,
                                    "symbol": "",
                                    "start_line": s or None,
                                    "end_line": e or None,
                                    "score": float(h.get("score") or 0.0),
                                    "heat": (
                                        "hot"
                                        if float(h.get("score") or 0) >= float(hot_threshold or 0.65)
                                        else "warm"
                                    ),
                                    "rank": i,
                                    "why": (h.get("why") or "")[:160],
                                    "loc": f"{f}:{s}-{e}" if s and e else f,
                                }
                            )

                    out = {
                        "ok": True,
                        "tool": tool_name,
                        "query": query,
                        "mode": mode_n,
                        "policy": policy_n,
                        "include_bodies": False,
                        "heatmap": heatmap[: max(4, min(int(k or 16), 48))],
                        "count": len(heatmap),
                        "seed": seed_card if seed_card.get("file") else None,
                        "thin": len(heatmap) < 3,
                        "engine": engine_tag,
                        "elapsed_ms": round((time.perf_counter() - t_pack) * 1000, 1),
                        "next": "Native-Read top heatmap locs → EDIT; expand_context if thin.",
                    }
                    return _format(out, response_format)
                if not ast_cache_ready(repo):
                    # Never cold-bake AST on the pack request thread (20s+ GIL).
                    try:
                        from pipeline.mcp_lifecycle import start_ast_hydrate_bg

                        start_ast_hydrate_bg(repo)
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        import threading

                        def _bg_bake_pack() -> None:
                            try:
                                hydrate_ast_bundle(repo, bake_on_miss=True)
                            except Exception:  # noqa: BLE001
                                pass

                        threading.Thread(
                            target=_bg_bake_pack, name="scubiee-pack-ast-bake", daemon=True
                        ).start()
                    except Exception:  # noqa: BLE001
                        pass
                    return _err(
                        tool_name,
                        "ast_warming",
                        hint=(
                            "AST bundle not ready for broad/body pack. "
                            "Use mode=lean (heatmap only) now, or retry after expand "
                            "warms the graph; Native-Read top locs."
                        ),
                        status="warming",
                    )

                prior = load_trace(repo, sid)
                # Per-tool packed ledger: pack_poly_embed / pack_semantic must not
                # inherit pack_context bodies (that made alternate packs look "thin").
                by_tool = dict(prior.get("packed_ids_by_tool") or {})
                prior_packed = {str(x) for x in (by_tool.get(tool_name) or []) if x}
                if not prior_packed and tool_name == "pack_context":
                    prior_packed = {str(x) for x in (prior.get("packed_ids") or []) if x}
                policy_n = (policy or "strict").strip().lower() or "strict"
                budget = int(budget_chars or 0)
                bodies_cap = int(max_bodies or 0)
                out = run_pack_context(
                    repo,
                    query,
                    seed_file=seed_file,
                    seed_symbol=seed_symbol,
                    seed_line=int(seed_line or 0),
                    seed2_file=seed2_file,
                    seed2_symbol=seed2_symbol,
                    seed2_line=int(seed2_line or 0),
                    seed3_file=seed3_file,
                    seed3_symbol=seed3_symbol,
                    seed3_line=int(seed3_line or 0),
                    k=max(4, min(int(k or 16), 48)),
                    hot_threshold=float(hot_threshold if hot_threshold is not None else 0.65),
                    budget_chars=budget if budget > 0 else None,
                    max_bodies=bodies_cap if bodies_cap > 0 else None,
                    mode=mode_n,
                    policy=policy_n,
                    prior_packed_ids=prior_packed,
                    engine=engine,
                    tool_name=tool_name,
                    include_bodies=want_bodies,
                )
                out["session_id"] = sid
                if out.get("ok"):
                    persist = out.pop("_persist", {}) or {}
                    new_ids = {str(x) for x in (persist.get("packed_ids") or []) if x}
                    by_tool[tool_name] = sorted(
                        {str(x) for x in (by_tool.get(tool_name) or []) if x} | new_ids
                    )
                    persist["packed_ids_by_tool"] = by_tool
                    # Global union still feeds expand/collect_hot continuum
                    persist["packed_ids"] = sorted(
                        {str(x) for ids in by_tool.values() for x in (ids or []) if x}
                    )
                    persist_trace(repo, sid, persist)
                    try:
                        from pipeline.work_session import touch

                        touch(
                            repo,
                            [
                                {"file": c.get("file"), "role": tool_name}
                                for c in (out.get("heatmap") or [])[:12]
                            ],
                            query=query,
                            session_id=sid,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    out["tool"] = tool_name
                return _format(out, response_format)
            except Exception as exc:  # noqa: BLE001
                return _err(tool_name, str(exc))

        pack_impl.__doc__ = doc
        return pack_impl

    pack_context_impl = _make_pack_impl(
        tool_name="pack_context",
        engine="composite_v1",
        doc=(
            "Call 2 ladder (composite_v1): lean heatmap locs by default. "
            "Native-Read top heats; include_bodies=1 or CTX_MCP_PACK_BODIES=1 for bodies."
        ),
    )
    pack_poly_embed_impl = _make_pack_impl(
        tool_name="pack_poly_embed",
        engine="poly_embed",
        doc="Pack with poly_embed (structural poly + real CodeRank embeds).",
    )
    pack_semantic_impl = _make_pack_impl(
        tool_name="pack_semantic",
        engine="semantic_tracer_fuse",
        doc="Pack with semantic_tracer_fuse (best safe semantic heat; real CodeRank embeds).",
    )

    def collect_hot_context_impl(
        threshold: Annotated[float, Field(description="Min score to include (default 0.82).")] = 0.82,
        max_chars: Annotated[int, Field(description="Total body budget.")] = 8000,
        ids: Annotated[
            str,
            Field(
                description=(
                    "Optional comma-separated node ids (file::symbol) to fill — "
                    "use after expand_context delta. Empty = score threshold over session cards."
                )
            ),
        ] = "",
        response_format: Annotated[str, Field(description="json (default) or markdown.")] = "json",
        root: Annotated[str, Field(description=_BIND_ROOT_DESC)] = "",
        project_id: Annotated[str, Field(description=_BIND_PID_DESC)] = "",
        session_id: Annotated[str, Field(description=_BIND_SESSION_DESC)] = "",
    ) -> str:
        """Optional: return code bodies for last heatmap / explicit ids. Prefer native Read."""
        sid = _resolve_session(session_id)
        with _bind_request_repo(root=root, project_id=project_id, session_id=session_id):
            repo = _default_repo()
        if not _is_repo_managed():
            return _managed_locate_err("collect_hot_context", repo)
        try:
            from pipeline.context_trace import (
                ast_cache_ready,
                load_trace,
                persist_trace,
                run_collect_hot,
            )

            prior = load_trace(repo, sid)
            cards = list(prior.get("cards") or [])
            only = {x.strip() for x in (ids or "").split(",") if x.strip()}
            if not cards and not only:
                return _err(
                    "collect_hot_context",
                    "no session heatmap — call map/pack_context first (or pass ids=)",
                )
            prior_packed = {str(x) for x in (prior.get("packed_ids") or []) if x}
            # Explicit ids always win — never skip them (lean pack used to poison packed_ids).
            skip = prior_packed - only if only else prior_packed
            # Session collect after lean: use pack hot_threshold-ish floor, not 0.82 default.
            thr = float(threshold or 0.82)
            if not only and thr >= 0.82:
                thr = 0.45
            budget = max(500, min(int(max_chars or 8000), 50_000))
            # Prefer span-read when AST cold — never sync-load 50MB pickle here.
            if not ast_cache_ready(repo):
                try:
                    from pipeline.mcp_lifecycle import start_ast_hydrate_bg

                    start_ast_hydrate_bg(repo)
                except Exception:  # noqa: BLE001
                    pass
                out = _collect_hot_from_card_locs(
                    Path(repo),
                    cards,
                    threshold=0.0 if only else thr,
                    max_chars=budget,
                    skip_ids=skip,
                    only_ids=only or None,
                    prefer_ids=only or None,
                )
                if not out.get("bodies"):
                    return _err(
                        "collect_hot_context",
                        "ast_warming",
                        hint=(
                            "No card loc spans to read yet and AST not warm. "
                            "Native-Read heatmap locs, or retry after expand hydrates."
                        ),
                        status="warming",
                    )
            else:
                out = run_collect_hot(
                    repo,
                    cards,
                    threshold=0.0 if only else thr,
                    max_chars=budget,
                    skip_ids=skip,
                    only_ids=only or None,
                    prefer_ids=only or None,
                )
            out["session_id"] = sid
            if out.get("ok") and out.get("bodies"):
                packed = prior_packed | {str(b.get("id")) for b in out["bodies"] if b.get("id")}
                persist_trace(
                    repo,
                    sid,
                    {
                        "query": prior.get("query"),
                        "seed_id": prior.get("seed_id"),
                        "cards": cards,
                        "scores": prior.get("scores") or {},
                        "packed_ids": sorted(packed),
                    },
                )
            return _format(out, response_format)
        except Exception as exc:  # noqa: BLE001
            return _err("collect_hot_context", str(exc))

    # ---- register per surface ---------------------------------------------
    if surface == "phase":
        exp = _phase_experiment()
        _tool("gate", "Session gate - managed check (~5 tokens)", gate_impl)
        _tool(
            "pack_context",
            "Call 2 ladder (composite_v1): lean heatmap locs by default. "
            "Native-Read top heats; include_bodies=1 / CTX_MCP_PACK_BODIES=1 for bodies.",
            pack_context_impl,
        )
        if exp in {"lab", "classic"}:
            _tool(
                "pack_poly_embed",
                "poly_embed pack: compressed heatmap locs (no bodies). Native-Read top heats.",
                pack_poly_embed_impl,
            )
            _tool(
                "pack_semantic",
                "semantic_fuse pack: compressed heatmap locs (no bodies). Native-Read top heats.",
                pack_semantic_impl,
            )
            _tool(
                "map_context",
                "Context TRACE: descriptive query+seed → loc+score heatmap (prefer rich code words; Read/Grep cards)",
                map_context_impl,
            )
        _tool(
            "expand_context",
            "Call 3: delta cards; direction=callers|effects|broad; with_bodies optional",
            expand_context_impl,
        )
        _tool(
            "collect_hot_context",
            "Fill bodies for session cards or ids= after expand (prefer native Read)",
            collect_hot_context_impl,
        )
        _tool(
            "map",
            "Call 1 ladder: soft cards k=12 + suggested_seeds (25–120 tok query, target ≥40)",
            map_impl,
        )
        if exp == "lab":
            _tool(
                "pinpoint",
                "Prefer for soft where/how to edit - BM25+dense+graph body+neighbors",
                pinpoint_impl,
            )
            _tool(
                "plate",
                "How-X-works plate - BM25+dense hubs + Graphify connections (no LLM)",
                plate_impl,
            )
        elif exp == "classic":
            _tool("focus", "Prefer for opening code to edit - span|outline|neighbors|call_sites", focus_impl)
            _tool("grep", "Prefer for exact literals - imports, keys, error strings", grep_impl)
            _tool("glob", "Prefer for finding paths by name/pattern", glob_impl)
        _tool("workspace", "Mid reorient: show|pin|clear", workspace_impl)
        _tool("expand", "Re-materialize a stored span by handle", expand_impl)
        _tool("status", "Engine + session status (default summary; detail=full|gate)", status_impl)
        return mcp

    if surface == "nav":
        _tool("gate", "Session gate — managed check (~5 tok)", gate_impl)
        _tool("search", "Soft or exact locate (mode=soft|exact)", search_impl)
        _tool("files", "Find files by name/glob; '.' = repo shape", files_impl)
        _tool("read", "Read span (detail=body|outline|neighbors)", read_impl)
        _tool("recall", "List session handles (no bodies)", recall_impl)
        _tool("expand", "Materialize a stored span by handle", expand_impl)
        _tool("status", "Engine + session status", status_impl)
        return mcp

    _tool("gate", "Session gate — managed check (~5 tok)", gate_impl)

    if surface != "grep":
        _tool("search", "Semantic code search (simple, flexible)", search_impl)
    if surface == "read":
        _tool("read", "Read the right span (deduped, + neighbors)", read_impl)
    elif surface == "grep":
        _tool("grep", "Exact/literal text search", grep_impl)
    elif surface == "graph":
        _tool("neighbors", "1-hop graph neighbors (callers/callees)", neighbors_impl)
        _tool("graph", "NL structural/relationship query (graph)", graph_impl)
    elif surface == "rich":
        # Value-add ("MCP creativity") tools only — the things native can't do:
        # meaning (search), structure (outline), and the graph (read neighbors).
        # grep/files were dropped: they just reroute native grep/glob through the
        # MCP with no capability gain, costing doc + context space. Use native
        # grep/glob for exact strings / filenames.
        _tool("read", "Read a span / exact lines (deduped, +neighbors)", read_impl)
        _tool("outline", "File structure (defs/classes)", outline_impl)
    # surface == "search": only search + status
    _tool("status", "Engine + session status", status_impl)

    return mcp


def main() -> None:
    from pipeline.ctx_home_guard import enforce_ctx_home_or_exit

    enforce_ctx_home_or_exit()
    # Disable automatic GC in the MCP process. Native extensions (tokenizers,
    # MLX, numpy) release the GIL; concurrent GC can traverse freed objects → SIGSEGV.
    # Same fix as the daemon (server.py). Manual gc.collect() at safe points.
    import gc

    gc.disable()

    # Disable Rayon parallelism in tokenizers to prevent memory corruption on
    # macOS ARM64. The Rayon thread pool interacts badly with CPython's memory
    # allocator, causing SIGSEGV in random threads.
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    os.environ.setdefault("CTX_MCP_SESSION_ISOLATE", "1")
    from pipeline.session_isolation import detect_mcp_host

    os.environ.setdefault("CTX_MCP_CLIENT", detect_mcp_host())
    repo = _default_repo()
    os.environ.setdefault("CTX_REPO", str(repo))
    os.environ.setdefault("CTX_TOKEN_MODE", "savings")
    os.environ.setdefault("CTX_SESSION_GOVERNOR", "1")
    os.environ.setdefault("CTX_ENGINE_IDLE_S", "120")
    os.environ.setdefault("CTX_DISCONNECT_DEBOUNCE_S", "10")
    os.environ.setdefault("CTX_ENGINE_TRANSITION_DEBOUNCE_S", "5")
    os.environ.setdefault("CTX_EMBED_IDLE_DEMOTE_S", "10")
    os.environ.setdefault("CTX_EMBED_PREWARM", "1")
    # faiss on the main thread before FastMCP worker threads (#3182 Windows deadlock).
    try:
        import pipeline.vectordb  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        _stderr(f"[scubiee] faiss preload: {exc}")

    boot_mcp_worker(repo)
    surface = _active_surface()
    tool_lists = {
        "read": "search,read,status",
        "nav": "search,files,read,recall,expand,status",
        "graph": "search,neighbors,graph,status",
        "rich": "search,read,outline,status",
        "search": "search,status",
        "grep": "grep,status",
        "phase": ",".join(_phase_tool_names()),
    }
    _stderr(
        f"[scubiee] surface={surface} tools={tool_lists.get(surface)} "
        f"repo={repo} token_mode={os.environ.get('CTX_TOKEN_MODE')}"
    )
    create_mcp().run(transport="stdio")


if __name__ == "__main__":
    main()

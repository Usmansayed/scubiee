"""Guardrails for Scubiee lifecycle action combinations.

Two different "stop" commands (do not conflate):

- ``scubiee stop``       — **global stop**. Removes MCP/rules/repo``.scubiee``,
  blocks action CLI until ``scubiee resume``.
- ``scubiee engine stop`` — **daemon only**. MCP + rules stay; ``engine start`` or
  first MCP call brings the engine back.

See ``docs/scubiee-action-matrix.md`` for the full combination table.
"""

from __future__ import annotations

from typing import Any

from pipeline.pause_resume import PAUSED_BLOCK_MESSAGE

# Commands allowed while globally stopped (read-only + recovery).
_READONLY_COMMANDS = frozenset({"doctor", "preflight", "diagnose", "gate", "list"})
_RECOVERY_COMMANDS = frozenset({
    "resume",
    "stop",
    "halt",
    "unlock-tool",
    "wipe",
    "connect",
    "disconnect",
    "upgrade",
})
_ALLOWED_WHEN_STOPPED = _READONLY_COMMANDS | _RECOVERY_COMMANDS

# Engine subcommands allowed while globally stopped.
_ENGINE_READONLY = frozenset({"status"})


def lifecycle_axes() -> dict[str, Any]:
    """Compact state for guard decisions and status()."""
    from pipeline.daemon import is_running
    from pipeline.lifecycle_guidance import lifecycle_snapshot

    snap = lifecycle_snapshot()
    return {
        **snap,
        "engine_running": is_running(),
        "global_stop": snap.get("globally_paused", False),
    }


def paused_blocks_command(cmd: str | None, argv: list[str] | None = None) -> str | None:
    """Return a block message when globally stopped and the command is not allowed."""
    from pipeline.pause_resume import is_paused

    if not is_paused():
        return None
    args = list(argv or [])
    if any(flag in args for flag in ("-h", "--help")):
        return None
    if not cmd:
        return None
    if cmd in _ALLOWED_WHEN_STOPPED:
        return None
    if cmd == "setup" and "--repair" in args:
        return None
    if cmd == "engine":
        sub = args[1] if len(args) >= 2 else ""
        if sub in _ENGINE_READONLY:
            return None
        if sub == "stop":
            return (
                "Scubiee is already stopped (scubiee stop). "
                "Engine is off. Run `scubiee resume` to restore MCP and engine."
            )
        if sub in {"start", "ensure", "run"}:
            return (
                "Scubiee is globally stopped — MCP and rules were removed. "
                "Run `scubiee resume` (not `scubiee engine start`)."
            )
    return PAUSED_BLOCK_MESSAGE


def guard_engine_action(action: str) -> dict[str, Any] | None:
    """Block engine actions that conflict with global stop. Return error payload or None."""
    from pipeline.pause_resume import is_paused

    if not is_paused():
        return None
    if action in _ENGINE_READONLY:
        return None
    if action == "stop":
        return {
            "ok": True,
            "skipped": True,
            "reason": "globally_paused",
            "hint": (
                "Scubiee is already stopped (scubiee stop). "
                "Run `scubiee resume` to restore MCP, rules, and engine."
            ),
        }
    if action in {"start", "ensure", "run"}:
        return {
            "ok": False,
            "skipped": True,
            "reason": "globally_paused",
            "hint": (
                "Scubiee is globally stopped — use `scubiee resume`, "
                "not `scubiee engine start`."
            ),
        }
    return {
        "ok": False,
        "reason": "globally_paused",
        "hint": PAUSED_BLOCK_MESSAGE,
    }


def describe_state() -> str:
    """One-line human state for CLI hints."""
    axes = lifecycle_axes()
    if axes.get("global_stop"):
        return "globally stopped (scubiee stop) - run scubiee resume"
    if not axes.get("engine_running"):
        return "engine stopped (scubiee engine stop) - run scubiee engine start or use MCP"
    if not axes.get("repo_enrolled"):
        return "repo not enrolled - run scubiee init ."
    if not axes.get("cursor_connected"):
        return "not connected - run scubiee connect --cursor"
    return "ready"


# Read-only CLI commands that show lifecycle notice when not ready.
COMMANDS_WITH_LIFECYCLE_NOTICE = frozenset({
    "doctor",
    "preflight",
    "diagnose",
    "gate",
    "stop",
})


def emit_lifecycle_notice(*, stream: Any | None = None) -> bool:
    """Print a one-line recovery hint to stderr when Scubiee is not ready."""
    import sys

    msg = describe_state()
    if msg == "ready":
        return False
    out = stream or sys.stderr
    text = msg[0].upper() + msg[1:] if msg else msg
    print(f"[scubiee] {text}.", file=out, flush=True)
    return True


def globally_paused_hint() -> str:
    """Hint payload for ensure_daemon and other programmatic callers."""
    return (
        "Scubiee is stopped (scubiee stop). "
        "Run `scubiee resume` to restore MCP, rules, and engine."
    )

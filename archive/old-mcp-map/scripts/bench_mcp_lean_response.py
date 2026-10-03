"""Quick benchmark: compact MCP dumps vs pretty JSON; budget echo off by default."""

from __future__ import annotations

import json
import os

from pipeline.mcp_response_lean import attach_gate_lean, reset_session_hint_echo_cache

CTX = {
    "session_id": "cursor@conn-525940",
    "source": "transport_conn",
    "shared_process_risk": True,
    "hint": (
        "Session 'cursor@conn-525940' may be shared across parallel chats on cursor "
        "(one MCP process). For isolation: pass a distinct session_id per chat/task, "
        "or set CTX_MCP_SESSION_ID in the host MCP env block."
    ),
}


def gate_line(**_: object) -> str:
    return "1:ce_223fe983ee19e5629ce88102e6581038"


def focus_body(n: int, code_lines: int = 40) -> dict:
    return {
        "ok": True,
        "tool": "focus",
        "mode": "span",
        "handle": f"sp_{n:04d}",
        "file": "tests/test_foo.py",
        "start_line": 1,
        "end_line": code_lines,
        "status": "stored",
        "unchanged": False,
        "code": "def test_x(): pass\n" * code_lines,
        "truncated": False,
        "budget": "wide",
        "session_id": CTX["session_id"],
        "next": "Edit cited lines. Wiring: focus(mode=neighbors).",
    }


def main() -> None:
    n_calls = 20
    reset_session_hint_echo_cache()
    os.environ.pop("CTX_MCP_ECHO_BUDGET", None)

    lean = [
        attach_gate_lean(focus_body(i), gate_line=gate_line, session_context=lambda: CTX)
        for i in range(n_calls)
    ]
    compact = sum(len(json.dumps(p, ensure_ascii=False, separators=(",", ":"))) for p in lean)
    pretty = sum(len(json.dumps(p, indent=2, default=str)) for p in lean)

    os.environ["CTX_MCP_ECHO_BUDGET"] = "1"
    reset_session_hint_echo_cache()
    echoed = [
        attach_gate_lean(focus_body(i), gate_line=gate_line, session_context=lambda: CTX)
        for i in range(n_calls)
    ]
    os.environ.pop("CTX_MCP_ECHO_BUDGET", None)
    echoed_compact = sum(
        len(json.dumps(p, ensure_ascii=False, separators=(",", ":"))) for p in echoed
    )

    print("=== 20x focus(span) payload chrome ===")
    print(f"Default compact (no budget echo): {compact:,} chars")
    print(f"Same cards pretty-printed:        {pretty:,} chars")
    print(
        f"Pretty-print tax:                 {pretty - compact:,} chars "
        f"({100 * (pretty - compact) / pretty:.1f}%)"
    )
    print(f"Debug echo budget (compact):      {echoed_compact:,} chars")


if __name__ == "__main__":
    main()

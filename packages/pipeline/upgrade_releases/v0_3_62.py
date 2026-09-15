"""Release 0.3.62 — Cursor just-works lifecycle ownership."""

from __future__ import annotations

from pipeline.upgrade_registry import release


@release(
    "0.3.62",
    notes=(
        "MCP never parents the engine (supervisor-only spawn); lock/pid bind to "
        "listener; coalesce duplicate Cursor MCP clients; locate streak defers all "
        "sync; multi-seed caps while warming; connect installs session supervisor"
    ),
)
class Release_0_3_62:
    pass
